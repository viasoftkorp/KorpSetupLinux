# Desempenho do setup — Plano de implementação

**Goal:** reduzir o número de tarefas/execuções de módulo por serviço no setup (fast path) mantendo o mesmo estado final e o código original como fallback.

**Architecture:** dois pontos quentes passam a ter um caminho rápido: (1) a reconciliação de compose ganha um módulo somente-leitura que decide se os loops originais por serviço são necessários; (2) o cadastro de serviços (`add_service`) processa todos os serviços da role na primeira iteração do loop, com um módulo de KV em lote e scripts SQL em lote. Tudo atrás de `korp_setup_fast_path` (padrão `true`, `setup.sh fast_path=false` desliga).

**Tech Stack:** Ansible (ansible-core 2.17, Python 3.10 no host), community.docker 5.x, community.general 9.x (`mssql_script`), python-consul, Docker 24 / Compose 2.18. Testes: `unittest` (stdlib).

**Spec:** `docs/desempenho/2026-10-02-desempenho-setup-design.md`

## Global Constraints

- O host executa ansible-core 2.17 com Python 3.10; nenhum código novo pode exigir Python > 3.10 nem bibliotecas não instaladas pelo setup (`python-consul`, `pymssql`, `docker==7.0.0` já são instaladas por provisioning/infrastructure).
- Templates de compose/KV/SQL, `vars/main.yml` das roles, formato de `installed_apps.yml`, nomes de projeto Compose e regras de segurança do DEVO-7182 não mudam.
- Com `korp_setup_fast_path: false` o comportamento deve ser exatamente o original (mesmas tarefas).
- Nunca ler/alterar `group_vars/all` (restrição desta execução); novas variáveis vão em `roles/utils/defaults/main.yml`.
- Mesmo código nas duas releases (os arquivos tocados são idênticos em 2024.2 e 2025.1, exceto `setup.sh`).

## Review Focus

1. Servidor com container legado/parcial/backup em **um** serviço de um compose grande → o caminho original precisa rodar para aquele compose (teste `test_pre_*`/`test_post_*` em Task 4).
2. Serviço sem nenhuma propriedade em `vars/main.yml` (`Svc:` → `None`) → mesmos padrões de `kv_skip`/`oauth_client.skip` (Task 2 `test_none_service`).
3. KV já existente com `custom_kv_overwrite` em um serviço anterior → o vazamento do fact é reproduzido (Task 3 `test_custom_overwrite_leaks_across_items`).
4. Template de KV que o Ansible não converte para dict (texto que não começa com `{`) → mesma serialização do original (Task 3 `test_new_key_from_string_value`).
5. Banco com `db_suffix` definido → nome do banco com sufixo nos scripts MSSQL/Postgres (Task 2 `test_db_suffix_and_lists`).

---

## File Structure

| Arquivo | Responsabilidade |
|---|---|
| `roles/utils/module_utils/korp_kv_merge.py` (novo) | merge de KV e serialização `to_nice_json` — fonte única |
| `roles/utils/library/consul_kv.py` (alterado) | passa a usar `korp_kv_merge.merge_kv` |
| `roles/utils/library/korp_consul_kv_batch.py` (novo) | ensure_kv + leitura do ensure_client, em lote |
| `roles/utils/library/korp_compose_state.py` (novo) | `docker compose config` + classificação somente-leitura |
| `filter_plugins/korp_setup_batch.py` (novo) | plano dos serviços (vars_validation), segredos, itens do lote de KV, hash OAuth |
| `roles/utils/tasks/apps/reconciled_compose_up.yml` (alterado) | usa `korp_compose_state`; loops originais só quando necessário |
| `roles/utils/tasks/services/add_service.yml` (alterado) | primeira iteração chama o lote; tarefas originais sob `when` |
| `roles/utils/tasks/services/add_services_batch.yml` (novo) | cadastro em lote |
| `roles/utils/templates/queries/create_db_postgres.sh.j2` (novo) | mesmo comando de `create_db/postgres.yml`, para o lote |
| `roles/utils/defaults/main.yml` (novo) | `korp_setup_fast_path: true` |
| `setup.sh` (alterado) | parâmetro `fast_path` |
| `tests/unit/*` (novo) | testes unitários |
| `tests/sim/*` (novo) | ambiente isolado + comparação de estado |
| `docs/files/guias/desempenho_setup.rst` (novo) + `docs/index.rst` | documentação de operação |

---

### Task 1: Merge de KV compartilhado

**Files:**
- Create: `roles/utils/module_utils/korp_kv_merge.py`
- Modify: `roles/utils/library/consul_kv.py`
- Test: `tests/unit/test_korp_kv_merge.py`, `tests/unit/_loader.py`, `tests/run_unit_tests.sh`

**Interfaces:**
- Produces: `merge_kv(current_kv: dict, new_kv: dict, keys_to_overwrite: list[str]) -> dict`, `to_nice_json(value) -> str` (igual a `to_nice_json(indent=2)`), `replace_key`, `access_value` (mesmas assinaturas do original).

- [ ] **Step 1: loader de testes** — `tests/unit/_loader.py`:

```python
"""Carrega módulos/filtros do repositório por caminho (sem instalar nada)."""
import importlib.util
import os
import sys

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def load(relpath, name):
    path = os.path.join(REPO, relpath)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_module_utils():
    """Registra roles/utils/module_utils/* como ansible.module_utils.* (como o Ansible faz)."""
    return load("roles/utils/module_utils/korp_kv_merge.py", "ansible.module_utils.korp_kv_merge")
```

- [ ] **Step 2: teste que falha** — `tests/unit/test_korp_kv_merge.py` compara com uma cópia literal das funções originais de `consul_kv.py` (base `f065d7ce`), em casos fixos e aleatórios:

```python
import copy, json, random, unittest
from _loader import load_module_utils


# Cópia literal de roles/utils/library/consul_kv.py (antes da refatoração)
def _orig_replace_key(keys_sequence, dictionary, new_val):
    current_key = keys_sequence[0]
    if len(keys_sequence) == 1:
        dictionary[current_key] = new_val
    else:
        dictionary[current_key] = _orig_replace_key(keys_sequence[1:], dictionary[current_key], new_val)
    return dictionary


def _orig_access_value(keys_sequence, dictionary):
    if not keys_sequence:
        return dictionary
    current_key = keys_sequence[0]
    if current_key in dictionary:
        return _orig_access_value(keys_sequence[1:], dictionary[current_key])
    else:
        return None


def _orig_merge(current_kv, new_kv, keys_to_overwrite):
    merged_kv = new_kv.copy()
    merged_kv.update(current_kv)
    for key_path in keys_to_overwrite:
        keys_sequence = key_path.split(".")
        new_val = _orig_access_value(keys_sequence, new_kv)
        if new_val:
            merged_kv = _orig_replace_key(keys_sequence, merged_kv, new_val)
    return merged_kv


class MergeTest(unittest.TestCase):
    def setUp(self):
        self.m = load_module_utils()

    def test_readme_table(self):
        current = {"a": {"b": "Valor antigo1", "d": "Valor antigo2"}}
        new = {"a": {"b": {"c": "Valor novo"}}}
        self.assertEqual(self.m.merge_kv(copy.deepcopy(current), copy.deepcopy(new), ["a.b"]),
                         {"a": {"b": {"c": "Valor novo"}, "d": "Valor antigo2"}})
        self.assertEqual(self.m.merge_kv(copy.deepcopy(current), copy.deepcopy(new), ["a"]),
                         {"a": {"b": {"c": "Valor novo"}}})
        self.assertEqual(self.m.merge_kv(copy.deepcopy(current), copy.deepcopy(new), ["a.b.c"]), current)
        self.assertEqual(self.m.merge_kv(copy.deepcopy(current), copy.deepcopy(new), ["b"]), current)

    def test_falsy_new_values_never_overwrite(self):
        for falsy in ("", 0, False, None, [], {}):
            self.assertEqual(self.m.merge_kv({"k": "old"}, {"k": falsy}, ["k"]), {"k": "old"})

    def test_random_equivalence_with_original(self):
        rnd = random.Random(7)
        keys = ["A", "B", "C"]

        def tree(depth):
            if depth == 0 or rnd.random() < 0.3:
                return rnd.choice(["x", "y", "", 0, 1, True, False, None, [1], {}])
            return {k: tree(depth - 1) for k in rnd.sample(keys, rnd.randint(1, 3))}

        for _ in range(3000):
            cur, new = tree(3), tree(3)
            if not isinstance(cur, dict) or not isinstance(new, dict):
                continue
            paths = [".".join(rnd.sample(keys, rnd.randint(1, 2))) for _ in range(rnd.randint(0, 3))]
            try:
                expected = _orig_merge(copy.deepcopy(cur), copy.deepcopy(new), paths)
            except Exception as exc:  # original também falha
                with self.assertRaises(type(exc)):
                    self.m.merge_kv(copy.deepcopy(cur), copy.deepcopy(new), paths)
                continue
            self.assertEqual(self.m.merge_kv(copy.deepcopy(cur), copy.deepcopy(new), paths), expected)

    def test_to_nice_json_matches_ansible_filter(self):
        from ansible.plugins.filter.core import to_nice_json as ansible_to_nice_json
        value = {"b": [1, 2, {"z": None}], "a": "çé", "c": True, "d": 1.5}
        self.assertEqual(self.m.to_nice_json(value), ansible_to_nice_json(value, indent=2))


if __name__ == "__main__":
    unittest.main()
```

`tests/run_unit_tests.sh`:

```bash
#!/bin/bash
# Executa os testes unitários (precisa de python3 com ansible-core instalado, como o host do setup).
set -euo pipefail
cd "$(dirname "$0")/unit"
exec python3 -m unittest discover -v -p 'test_*.py'
```

- [ ] **Step 3: rodar e ver falhar** — `bash tests/run_unit_tests.sh` → FAIL (`No such file ... korp_kv_merge.py`).

- [ ] **Step 4: implementação** — `roles/utils/module_utils/korp_kv_merge.py`:

```python
# -*- coding: utf-8 -*-
"""Regra de merge dos KVs do Consul (fonte única).

Usado por roles/utils/library/consul_kv.py e roles/utils/library/korp_consul_kv_batch.py.
As funções são exatamente as que existiam em consul_kv.py:

  1. adiciona chaves inéditas de new_kv;
  2. mantém os valores atuais de current_kv;
  3. sobrescreve os caminhos de keys_to_overwrite quando o valor novo é "verdadeiro".
"""
from __future__ import absolute_import, division, print_function
__metaclass__ = type

import json


def replace_key(keys_sequence, dictionary, new_val):
    current_key = keys_sequence[0]
    if len(keys_sequence) == 1:
        dictionary[current_key] = new_val
    else:
        dictionary[current_key] = replace_key(keys_sequence[1:], dictionary[current_key], new_val)
    return dictionary


def access_value(keys_sequence, dictionary):
    if not keys_sequence:
        return dictionary
    current_key = keys_sequence[0]
    if current_key in dictionary:
        return access_value(keys_sequence[1:], dictionary[current_key])
    else:
        return None  # Tratado posteriormente para não criar chaves nulas


def merge_kv(current_kv, new_kv, keys_to_overwrite):
    merged_kv = new_kv.copy()
    merged_kv.update(current_kv)  # armazena novas chaves
    # Removendo chaves antigas se houverem chaves atualizadas
    for key_path in keys_to_overwrite:
        keys_sequence = key_path.split(".")
        new_val = access_value(keys_sequence, new_kv)
        if new_val:
            merged_kv = replace_key(keys_sequence, merged_kv, new_val)
    return merged_kv


def to_nice_json(value):
    """Mesma saída do filtro Ansible `to_nice_json(indent=2)` para dados vindos de JSON."""
    return json.dumps(value, indent=2, sort_keys=True, separators=(',', ': '))
```

`roles/utils/library/consul_kv.py`: remover `replace_key`/`access_value` locais, importar `from ansible.module_utils.korp_kv_merge import merge_kv` e substituir o bloco de merge por `merged_kv = merge_kv(current_kv, new_kv, keys_to_overwrite)` (o restante — argument_spec, retorno `prop` — não muda).

- [ ] **Step 5: rodar** — `bash tests/run_unit_tests.sh` → PASS.
- [ ] **Step 6: commit** — `git add roles/utils/module_utils roles/utils/library/consul_kv.py tests/unit/_loader.py tests/unit/test_korp_kv_merge.py tests/run_unit_tests.sh && git commit -m "perf(setup): extrai merge de KV para module_utils compartilhado"`

---

### Task 2: Filtros do cadastro em lote

**Files:**
- Create: `filter_plugins/korp_setup_batch.py`
- Test: `tests/unit/test_korp_setup_batch_filters.py`

**Interfaces:**
- Produces (filtros Jinja):
  - `services | korp_service_plan(names: list[str], db_suffix_divider: str, db_suffix: str) -> dict` com chaves
    `services` (dict atualizado como em `vars_validation.yml`), `service_vars` (dict nome→vars), `secrets` (nome→str),
    `invalid` (nomes com `db` sem `type`), `kv_services`, `oauth_services` (listas de nomes, na ordem),
    `mssql_databases`/`postgres_databases` (listas `{service, name}`), `unsupported_databases` (`{service, type}`),
    `volume_directories` (lista de caminhos), `last_service` (str|None).
  - `render_results | korp_kv_batch_items(services: dict) -> list[dict]` — itens `{key, new_kv, has_custom_kv_overwrite, custom_kv_overwrite}`.
  - `values | korp_oauth_clients(names: list[str]) -> list[dict]` — `{service_name, secret_as_hash}`; erro se o KV não existir ou não tiver `Authorization.Secret`.
  - `value | korp_sha256_base64 -> str` — igual a `encrypt_to_sha256_base64.py`.

- [ ] **Step 1: teste que falha** — `tests/unit/test_korp_setup_batch_filters.py`:

```python
import base64, hashlib, re, unittest
from _loader import load

f = load("filter_plugins/korp_setup_batch.py", "korp_setup_batch")
UUID_UP = re.compile(r"^[0-9A-F]{8}-[0-9A-F]{4}-5[0-9A-F]{3}-[89AB][0-9A-F]{3}-[0-9A-F]{12}$")


class PlanTest(unittest.TestCase):
    def test_none_service(self):
        plan = f.korp_service_plan({"Svc.A": None}, ["Svc.A"], "_", "")
        self.assertEqual(plan["services"]["Svc.A"], {"kv_skip": False, "oauth_client": {"skip": False}})
        self.assertEqual(plan["service_vars"]["Svc.A"], {"kv_skip": False, "oauth_client": {"skip": False}})
        self.assertEqual(plan["kv_services"], ["Svc.A"])
        self.assertEqual(plan["oauth_services"], ["Svc.A"])
        self.assertRegex(plan["secrets"]["Svc.A"], UUID_UP)
        self.assertEqual(plan["last_service"], "Svc.A")

    def test_existing_values_are_kept(self):
        svc = {"kv_skip": True, "oauth_client": {"skip": True, "x": 1}, "custom_kv_overwrite": ["Core"]}
        plan = f.korp_service_plan({"S": svc}, ["S"], "_", "")
        self.assertEqual(plan["services"]["S"], svc)
        self.assertEqual(plan["kv_services"], [])
        self.assertEqual(plan["oauth_services"], [])

    def test_oauth_client_without_skip_gets_default_and_keeps_keys(self):
        plan = f.korp_service_plan({"S": {"oauth_client": {"x": 1}}}, ["S"], "_", "")
        self.assertEqual(plan["services"]["S"]["oauth_client"], {"x": 1, "skip": False})

    def test_db_name_default_and_suffix(self):
        plan = f.korp_service_plan({"Korp.Svc.Core": {"db": {"type": "mssql"}}}, ["Korp.Svc.Core"], "_", "HML")
        self.assertEqual(plan["services"]["Korp.Svc.Core"]["db"], {"type": "mssql", "name": "Korp_Svc_Core"})
        self.assertEqual(plan["service_vars"]["Korp.Svc.Core"]["db"]["name"], "Korp_Svc_Core_HML")
        self.assertEqual(plan["mssql_databases"], [{"service": "Korp.Svc.Core", "name": "Korp_Svc_Core_HML"}])

    def test_db_suffix_and_lists(self):
        services = {
            "A": {"db": {"type": "postgres", "name": "dba"}, "volumes_directories": ["/d/a", "/d/b"]},
            "B": {"db": {"type": "mssql", "name": None}},
            "C": {"db": {"type": "oracle"}},
        }
        plan = f.korp_service_plan(services, ["A", "B", "C"], "_", "x")
        self.assertEqual(plan["postgres_databases"], [{"service": "A", "name": "dba_x"}])
        self.assertEqual(plan["mssql_databases"], [{"service": "B", "name": "B_x"}])
        self.assertEqual(plan["unsupported_databases"], [{"service": "C", "type": "oracle"}])
        self.assertEqual(plan["volume_directories"], ["/d/a", "/d/b"])
        self.assertEqual(services["B"]["db"]["name"], None, "a entrada não pode ser alterada")

    def test_invalid_db_type(self):
        for db in ({}, {"type": None}, None, "x"):
            plan = f.korp_service_plan({"A": {"db": db}, "B": None}, ["A", "B"], "_", "")
            self.assertEqual(plan["invalid"], ["A"])

    def test_order_follows_names(self):
        plan = f.korp_service_plan({"A": None, "B": None, "C": None}, ["C", "A", "B"], "_", "")
        self.assertEqual(plan["kv_services"], ["C", "A", "B"])
        self.assertEqual(plan["last_service"], "B")

    def test_secret_like_ansible_expression(self):
        from ansible.plugins.filter.core import to_uuid
        valid = {to_uuid(i).upper() for i in range(10000)}
        plan = f.korp_service_plan({"A": None, "B": None}, ["A", "B"], "_", "")
        self.assertIn(plan["secrets"]["A"], valid)
        self.assertIn(plan["secrets"]["B"], valid)


class ItemsTest(unittest.TestCase):
    def test_items_with_custom_overwrite(self):
        results = [{"korp_svc": "A", "ansible_facts": {"korp_rendered_kv": {"x": 1}}},
                   {"korp_svc": "B", "ansible_facts": {"korp_rendered_kv": "texto"}}]
        services = {"A": {"custom_kv_overwrite": ["Core"]}, "B": None}
        self.assertEqual(f.korp_kv_batch_items(results, services), [
            {"key": "A", "new_kv": {"x": 1}, "has_custom_kv_overwrite": True, "custom_kv_overwrite": ["Core"]},
            {"key": "B", "new_kv": "texto", "has_custom_kv_overwrite": False, "custom_kv_overwrite": None},
        ])


class OAuthTest(unittest.TestCase):
    def test_hash_matches_original_module(self):
        secret = "0F1E2D3C-0000-5000-8000-000000000000"
        expected = base64.b64encode(hashlib.sha256(secret.encode("utf-8")).digest()).decode()
        self.assertEqual(f.korp_sha256_base64(secret), expected)

    def test_clients(self):
        values = {"A": '{"Authorization": {"Secret": "S1"}}'}
        self.assertEqual(f.korp_oauth_clients(values, ["A"]),
                         [{"service_name": "A", "secret_as_hash": f.korp_sha256_base64("S1")}])

    def test_missing_kv_or_secret_fails(self):
        from ansible.errors import AnsibleFilterError
        for values in ({"A": None}, {"A": '{"x": 1}'}, {}):
            with self.assertRaises(AnsibleFilterError):
                f.korp_oauth_clients(values, ["A"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: rodar e ver falhar** — `bash tests/run_unit_tests.sh` → FAIL (arquivo inexistente).

- [ ] **Step 3: implementação** — `filter_plugins/korp_setup_batch.py`:

```python
# -*- coding: utf-8 -*-
"""Filtros do cadastro de serviços em lote (fast path do setup).

Reproduzem, para todos os serviços de uma role de uma vez, o que
roles/utils/tasks/services/vars_validation.yml, add_service.yml (segredo),
consul_kv/ensure_kv.yml (itens) e oauth_client/* (hash) faziam por serviço.
"""
import base64
import copy
import hashlib
import json
import random

from ansible.errors import AnsibleFilterError
from ansible.module_utils.common.text.converters import to_text
from ansible.plugins.filter.core import to_uuid


def _combine(base, extra):
    """`combine(recursive=True)` do Ansible: dicts são mesclados, o resto é substituído."""
    result = dict(base) if isinstance(base, dict) else {}
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _combine(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def _legacy_secret(rng):
    """Mesmo valor de `10000 | random | to_uuid | upper`."""
    return to_text(to_uuid(rng.randrange(0, 10000, 1))).upper()


def korp_service_plan(services, names, db_suffix_divider, db_suffix):
    if not isinstance(services, dict):
        raise AnsibleFilterError("korp_service_plan: 'services' deve ser um dicionário")
    services = copy.deepcopy(services)
    rng = random.SystemRandom()
    plan = {
        "services": services, "service_vars": {}, "secrets": {}, "invalid": [],
        "kv_services": [], "oauth_services": [], "mssql_databases": [], "postgres_databases": [],
        "unsupported_databases": [], "volume_directories": [], "last_service": None,
    }
    for name in names:
        current = services.get(name)
        current = current if isinstance(current, dict) else {}
        # vars_validation.yml: db definido e (db.type indefinido ou None)
        if "db" in current and (not isinstance(current["db"], dict) or current["db"].get("type") is None):
            plan["invalid"].append(name)
            continue
        # vars_validation.yml: valores padrão gravados de volta em `services`
        if "kv_skip" not in current:
            services[name] = _combine(services.get(name), {"kv_skip": False})
        oauth = services[name].get("oauth_client")
        if not (isinstance(oauth, dict) and "skip" in oauth):
            services[name] = _combine(services[name], {"oauth_client": {"skip": False}})
        db = services[name].get("db")
        if isinstance(db, dict) and db.get("name") is None:
            services[name] = _combine(services[name], {"db": {"name": name.replace(".", "_")}})
        service_vars = copy.deepcopy(services[name])
        if "db" in service_vars and db_suffix != "":
            service_vars = _combine(service_vars, {
                "db": {"name": service_vars["db"]["name"] + db_suffix_divider + db_suffix}})
        plan["service_vars"][name] = service_vars
        plan["secrets"][name] = _legacy_secret(rng)
        if not service_vars.get("kv_skip"):
            plan["kv_services"].append(name)
        if not service_vars["oauth_client"].get("skip"):
            plan["oauth_services"].append(name)
        if "db" in service_vars:
            db = service_vars["db"]
            if db["type"] == "mssql":
                plan["mssql_databases"].append({"service": name, "name": db["name"]})
            elif db["type"] == "postgres":
                plan["postgres_databases"].append({"service": name, "name": db["name"]})
            else:
                plan["unsupported_databases"].append({"service": name, "type": db["type"]})
        if "volumes_directories" in service_vars:
            plan["volume_directories"].extend(service_vars["volumes_directories"])
        plan["last_service"] = name
    return plan


def korp_kv_batch_items(render_results, services, loop_var="korp_svc", fact="korp_rendered_kv"):
    items = []
    for result in render_results:
        name = result[loop_var]
        service = services.get(name) if isinstance(services, dict) else None
        has_custom = isinstance(service, dict) and "custom_kv_overwrite" in service
        items.append({
            "key": name,
            "new_kv": result["ansible_facts"][fact],
            "has_custom_kv_overwrite": has_custom,
            "custom_kv_overwrite": service["custom_kv_overwrite"] if has_custom else None,
        })
    return items


def korp_sha256_base64(value):
    """Mesmo resultado de roles/utils/library/encrypt_to_sha256_base64.py."""
    digest = hashlib.sha256(to_text(value).encode("utf-8")).digest()
    return base64.b64encode(digest).decode("ascii")


def korp_oauth_clients(values, names):
    clients = []
    for name in names:
        raw = (values or {}).get(name)
        try:
            secret = json.loads(raw)["Authorization"]["Secret"]
        except Exception:
            raise AnsibleFilterError(
                "Não foi possível ler Authorization.Secret do KV de %s no Consul" % name)
        clients.append({"service_name": name, "secret_as_hash": korp_sha256_base64(secret)})
    return clients


class FilterModule:
    def filters(self):
        return {
            "korp_service_plan": korp_service_plan,
            "korp_kv_batch_items": korp_kv_batch_items,
            "korp_sha256_base64": korp_sha256_base64,
            "korp_oauth_clients": korp_oauth_clients,
        }
```

- [ ] **Step 4: rodar** — `bash tests/run_unit_tests.sh` → PASS.
- [ ] **Step 5: commit** — `git add filter_plugins/korp_setup_batch.py tests/unit/test_korp_setup_batch_filters.py && git commit -m "perf(setup): filtros do cadastro de serviços em lote"`

---

### Task 3: Módulo `korp_consul_kv_batch`

**Files:**
- Create: `roles/utils/library/korp_consul_kv_batch.py`
- Test: `tests/unit/test_korp_consul_kv_batch.py`

**Interfaces:**
- Consumes: `merge_kv`, `to_nice_json` (Task 1); itens de `korp_kv_batch_items` (Task 2).
- Produces: módulo com parâmetros `items` (list[dict]), `default_kv_overwrite` (list[str]), `custom_kv_overwrite` (raw, opcional), `custom_kv_overwrite_defined` (bool), `read_keys` (list[str]), `host`/`port`/`scheme`/`validate_certs`/`token`/`datacenter` (mesmos padrões de `community.general.consul_kv`). Retorno: `changed`, `results` (`[{key, action}]`, action ∈ created|updated|unchanged|cas_conflict), `values` (chave→texto|None), `custom_kv_overwrite`, `custom_kv_overwrite_set` (bool). Função pura testável: `ensure_kvs(kv, items, default_kv_overwrite, custom_kv_overwrite, custom_defined, read_keys) -> dict`.

- [ ] **Step 1: teste que falha** — `tests/unit/test_korp_consul_kv_batch.py`:

```python
import json, unittest
from _loader import load, load_module_utils

load_module_utils()
mod = load("roles/utils/library/korp_consul_kv_batch.py", "korp_consul_kv_batch")
nice = load_module_utils().to_nice_json


class FakeKV:
    """Imita python-consul: get -> (index, {'Value': bytes}|None); put -> bool."""
    def __init__(self, data=None):
        self.data = {k: v.encode() for k, v in (data or {}).items()}
        self.puts = []

    def get(self, key):
        return 1, ({"Key": key, "Value": self.data[key]} if key in self.data else None)

    def put(self, key, value, cas=None):
        self.puts.append((key, value, cas))
        if cas == 0 and key in self.data:
            return False
        self.data[key] = value.encode()
        return True


class BatchTest(unittest.TestCase):
    def run_batch(self, kv, items, default=("D",), custom=None, custom_defined=False, read=()):
        return mod.ensure_kvs(kv, items, list(default), custom, custom_defined, list(read))

    def test_new_key_created_with_cas_zero(self):
        kv = FakeKV()
        res = self.run_batch(kv, [{"key": "A", "new_kv": {"b": 1, "a": True}, "has_custom_kv_overwrite": False}])
        self.assertEqual(kv.puts, [("A", nice({"b": 1, "a": True}), 0)])
        self.assertTrue(res["changed"])
        self.assertEqual(res["results"], [{"key": "A", "action": "created"}])

    def test_new_key_from_string_value(self):
        kv = FakeKV()
        self.run_batch(kv, [{"key": "A", "new_kv": "nao-json", "has_custom_kv_overwrite": False}])
        self.assertEqual(kv.puts[0][1], json.dumps("nao-json"))

    def test_existing_unchanged_is_not_written(self):
        current = {"Authorization": {"Secret": "S"}, "D": "x"}
        kv = FakeKV({"A": nice(current)})
        res = self.run_batch(kv, [{"key": "A", "new_kv": {"Authorization": {"Secret": "N"}, "D": "x"},
                                   "has_custom_kv_overwrite": False}])
        self.assertEqual(kv.puts, [])
        self.assertFalse(res["changed"])

    def test_existing_merged_and_written_without_cas(self):
        kv = FakeKV({"A": '{"Authorization": {"Secret": "S"}, "D": "old"}'})
        res = self.run_batch(kv, [{"key": "A", "new_kv": {"Authorization": {"Secret": "N"}, "D": "new", "E": 1},
                                   "has_custom_kv_overwrite": False}])
        self.assertEqual(kv.puts, [("A", nice({"Authorization": {"Secret": "S"}, "D": "new", "E": 1}), None)])
        self.assertEqual(res["results"], [{"key": "A", "action": "updated"}])

    def test_existing_from_json_string_new_kv(self):
        kv = FakeKV({"A": '{"D": "old"}'})
        self.run_batch(kv, [{"key": "A", "new_kv": '{"D": "new"}', "has_custom_kv_overwrite": False}])
        self.assertEqual(kv.data["A"].decode(), nice({"D": "new"}))

    def test_custom_overwrite_leaks_across_items(self):
        kv = FakeKV({"A": '{"C": "a0"}', "B": '{"C": "b0"}', "N": '{"C": "n0"}'})
        items = [
            {"key": "N", "new_kv": {"C": "n1"}, "has_custom_kv_overwrite": False},  # usa o valor inicial
            {"key": "A", "new_kv": {"C": "a1"}, "has_custom_kv_overwrite": True, "custom_kv_overwrite": ["C"]},
            {"key": "B", "new_kv": {"C": "b1"}, "has_custom_kv_overwrite": False},  # herda ["C"] de A
        ]
        res = self.run_batch(kv, items, default=(), custom=None, custom_defined=False)
        self.assertEqual(json.loads(kv.data["N"]), {"C": "n0"})
        self.assertEqual(json.loads(kv.data["A"]), {"C": "a1"})
        self.assertEqual(json.loads(kv.data["B"]), {"C": "b1"})
        self.assertEqual(res["custom_kv_overwrite"], ["C"])
        self.assertTrue(res["custom_kv_overwrite_set"])

    def test_custom_overwrite_only_updated_when_key_exists(self):
        kv = FakeKV()
        res = self.run_batch(kv, [{"key": "A", "new_kv": {}, "has_custom_kv_overwrite": True,
                                   "custom_kv_overwrite": ["C"]}], custom=["X"], custom_defined=True)
        self.assertEqual(res["custom_kv_overwrite"], ["X"])
        self.assertFalse(res["custom_kv_overwrite_set"])

    def test_initial_custom_overwrite_is_used(self):
        kv = FakeKV({"A": '{"C": "old"}'})
        self.run_batch(kv, [{"key": "A", "new_kv": {"C": "new"}, "has_custom_kv_overwrite": False}],
                       default=(), custom=["C"], custom_defined=True)
        self.assertEqual(json.loads(kv.data["A"]), {"C": "new"})

    def test_cas_conflict_is_not_changed(self):
        class Racy(FakeKV):
            def get(self, key):
                return 1, None
        kv = Racy({"A": '{"x": 1}'})
        res = self.run_batch(kv, [{"key": "A", "new_kv": {"x": 2}, "has_custom_kv_overwrite": False}])
        self.assertFalse(res["changed"])
        self.assertEqual(res["results"], [{"key": "A", "action": "cas_conflict"}])

    def test_read_keys_after_writes(self):
        kv = FakeKV({"B": '{"Authorization": {"Secret": "SB"}}'})
        res = self.run_batch(kv, [{"key": "A", "new_kv": {"Authorization": {"Secret": "SA"}},
                                   "has_custom_kv_overwrite": False}], read=("A", "B", "Z"))
        self.assertEqual(json.loads(res["values"]["A"])["Authorization"]["Secret"], "SA")
        self.assertEqual(json.loads(res["values"]["B"])["Authorization"]["Secret"], "SB")
        self.assertIsNone(res["values"]["Z"])

    def test_invalid_current_value_raises_with_key(self):
        kv = FakeKV({"A": "nao-json"})
        with self.assertRaises(mod.KorpKVError) as ctx:
            self.run_batch(kv, [{"key": "A", "new_kv": {}, "has_custom_kv_overwrite": False}])
        self.assertIn("A", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: rodar e ver falhar** — FAIL (módulo inexistente).

- [ ] **Step 3: implementação** — `roles/utils/library/korp_consul_kv_batch.py`:

```python
#!/usr/bin/python
# -*- coding: utf-8 -*-
from __future__ import absolute_import, division, print_function
__metaclass__ = type

DOCUMENTATION = r'''
module: korp_consul_kv_batch
short_description: Garante em lote os KVs dos serviços de uma role no Consul
description:
  - Equivale a executar, na mesma ordem e por serviço, roles/utils/tasks/consul_kv/ensure_kv.yml
    (leitura; merge com a mesma regra de consul_kv.py; escrita só quando o texto muda; criação com cas=0)
    e, ao final, a leitura do KV feita por roles/utils/tasks/oauth_client/ensure_client.yml.
  - Reproduz o comportamento do fact custom_kv_overwrite, que permanece definido para os serviços seguintes.
options:
  items: {type: list, elements: dict, required: true}
  default_kv_overwrite: {type: list, elements: str, required: true}
  custom_kv_overwrite: {type: raw}
  custom_kv_overwrite_defined: {type: bool, default: false}
  read_keys: {type: list, elements: str, default: []}
  host: {type: str, default: localhost}
  port: {type: int, default: 8500}
  scheme: {type: str, default: http}
  validate_certs: {type: bool, default: true}
  token: {type: str}
  datacenter: {type: str}
requirements: [python-consul]
'''

import json

from ansible.module_utils.basic import AnsibleModule, missing_required_lib
from ansible.module_utils.common.text.converters import to_text
from ansible.module_utils.common.validation import check_type_dict
from ansible.module_utils.korp_kv_merge import merge_kv, to_nice_json

try:
    import consul
    HAS_CONSUL = True
except ImportError:
    HAS_CONSUL = False


class KorpKVError(Exception):
    pass


def _stored_text(data):
    value = data.get("Value")
    if isinstance(value, bytes):
        return value.decode("utf-8", "surrogateescape")
    return value


def _text_changed(data, target):
    """Mesma comparação de community.general.consul_kv (_has_value_changed)."""
    try:
        return to_text(data["Value"], errors="surrogate_or_strict") != target
    except UnicodeError:
        return True


def ensure_kvs(kv, items, default_kv_overwrite, custom_kv_overwrite, custom_defined, read_keys):
    changed = False
    custom_set = False
    results = []
    for item in items:
        key = item["key"]
        new_kv = item["new_kv"]
        _, existing = kv.get(key)
        if existing is not None:
            # ensure_kv.yml: custom_kv_overwrite só é (re)definido quando o KV já existe
            if item.get("has_custom_kv_overwrite"):
                custom_kv_overwrite = item.get("custom_kv_overwrite")
                custom_defined = True
                custom_set = True
            keys = list(custom_kv_overwrite or []) + list(default_kv_overwrite)
            try:
                current_kv = json.loads(_stored_text(existing))
                new_dict = new_kv if isinstance(new_kv, dict) else check_type_dict(new_kv)
                merged = merge_kv(current_kv, new_dict, keys)
            except Exception as exc:
                raise KorpKVError("Falha ao mesclar o KV de %s: %s" % (key, to_text(exc)))
            value = to_nice_json(merged)
            if _text_changed(existing, value):
                kv.put(key, value)
                changed = True
                action = "updated"
            else:
                action = "unchanged"
        else:
            value = to_nice_json(new_kv)
            created = bool(kv.put(key, value, cas=0))
            changed = changed or created
            action = "created" if created else "cas_conflict"
        results.append({"key": key, "action": action})

    values = {}
    for key in read_keys:
        _, data = kv.get(key)
        values[key] = None if data is None or data.get("Value") is None else _stored_text(data)
    return {
        "changed": changed,
        "results": results,
        "values": values,
        "custom_kv_overwrite": custom_kv_overwrite if custom_defined else None,
        "custom_kv_overwrite_set": custom_set,
    }


def main():
    module = AnsibleModule(
        argument_spec=dict(
            items=dict(type="list", elements="dict", required=True),
            default_kv_overwrite=dict(type="list", elements="str", required=True),
            custom_kv_overwrite=dict(type="raw"),
            custom_kv_overwrite_defined=dict(type="bool", default=False),
            read_keys=dict(type="list", elements="str", default=[]),
            host=dict(type="str", default="localhost"),
            port=dict(type="int", default=8500),
            scheme=dict(type="str", default="http"),
            validate_certs=dict(type="bool", default=True),
            token=dict(type="str", no_log=True),
            datacenter=dict(type="str"),
        ),
        supports_check_mode=False,
    )
    if not HAS_CONSUL:
        module.fail_json(msg=missing_required_lib("python-consul"))
    p = module.params
    client = consul.Consul(host=p["host"], port=p["port"], scheme=p["scheme"],
                           verify=p["validate_certs"], token=p["token"], dc=p["datacenter"])
    try:
        result = ensure_kvs(client.kv, p["items"], p["default_kv_overwrite"], p["custom_kv_overwrite"],
                            p["custom_kv_overwrite_defined"], p["read_keys"])
    except Exception as exc:
        module.fail_json(msg=to_text(exc))
    module.exit_json(**result)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: rodar** — PASS.
- [ ] **Step 5: commit** — `git commit -m "perf(setup): módulo korp_consul_kv_batch"`

---

### Task 4: Módulo `korp_compose_state`

**Files:**
- Create: `roles/utils/library/korp_compose_state.py`
- Test: `tests/unit/test_korp_compose_state.py`

**Interfaces:**
- Produces: módulo com `project_src`, `project_name`, `files`, `env_files` (default []), `version`, `phase` (`pre`|`post`), `services` (dict, só em `post`), `migration_enabled` (bool, default true), `force_slow_path` (bool, default false). Retorno: `services` (config efetiva), `needs_action` (bool), `reasons` (serviço→lista). Funções puras: `compose_config_argv(docker, project_src, project_name, env_files, files) -> list`, `parse_container_names(text) -> set`, `classify(services, names, labels_by_name, project_name, version, phase) -> dict`, `legacy_container_name`, `partial_container_names` (iguais a `filter_plugins/compose_migration.py`).

- [ ] **Step 1: teste que falha** — `tests/unit/test_korp_compose_state.py`:

```python
import unittest
from _loader import load

m = load("roles/utils/library/korp_compose_state.py", "korp_compose_state")
cm = load("filter_plugins/compose_migration.py", "compose_migration")
P, V = "202510", "2025.1.0"
SVC = {"svc-a": {"container_name": "Korp.A-2025.1.0", "image": "acct/korp.a:2025.1.0.x"}}
OK_LABELS = {"com.docker.compose.project": P, "com.docker.compose.service": "svc-a"}


class ArgvTest(unittest.TestCase):
    def test_same_argv_as_original_tasks(self):
        self.assertEqual(
            m.compose_config_argv("docker", "/etc/korp/composes/2025.1.0", P, ["/etc/korp/composes/.env"],
                                  ["ERP-compose.yml", "/abs/x.yml"]),
            ["docker", "compose", "--ansi", "never", "--project-directory", "/etc/korp/composes/2025.1.0",
             "--project-name", P, "--env-file", "/etc/korp/composes/.env",
             "--file", "/etc/korp/composes/2025.1.0/ERP-compose.yml", "--file", "/abs/x.yml",
             "config", "--format", "json"])

    def test_names_parsing(self):
        self.assertEqual(m.parse_container_names("a\nb,c\n\n d \n"), {"a", "b", "c", "d"})

    def test_helpers_equal_filter_plugin(self):
        for name in ("Korp.A-2025.1.0", "Korp.A", "x-2025.1.0-2025.1.0", ""):
            self.assertEqual(m.legacy_container_name(name, V), cm.legacy_container_name(name, V))
        names = ["0123456789ab_Korp.A", "0123456789ab_Korp.AB", "Korp.A", "zz3456789ab_Korp.A"]
        self.assertEqual(m.partial_container_names(names, "Korp.A"), cm.partial_container_names(names, "Korp.A"))


class ClassifyTest(unittest.TestCase):
    def pre(self, names, labels=None, services=SVC):
        return m.classify(services, set(names), labels or {}, P, V, "pre")

    def post(self, names, services=SVC):
        return m.classify(services, set(names), {}, P, V, "post")

    def test_canonical_is_noop(self):
        self.assertEqual(self.pre(["Korp.A-2025.1.0"], {"Korp.A-2025.1.0": OK_LABELS}), {})
        self.assertEqual(self.post(["Korp.A-2025.1.0"]), {})

    def test_new_service_is_noop(self):
        self.assertEqual(self.pre([]), {})
        self.assertEqual(self.post(["Korp.A-2025.1.0"]), {})

    def test_pre_partial_when_target_missing(self):  # estado E
        self.assertEqual(self.pre(["0123456789ab_Korp.A-2025.1.0"]), {"svc-a": ["partial_recovery"]})

    def test_pre_partial_ignored_when_target_exists(self):
        names = ["Korp.A-2025.1.0", "0123456789ab_Korp.A-2025.1.0"]
        self.assertEqual(self.pre(names, {"Korp.A-2025.1.0": OK_LABELS}), {})
        self.assertEqual(self.post(names), {"svc-a": ["partial_leftover"]})

    def test_pre_backup(self):  # estado F
        self.assertEqual(self.pre(["Korp.A-2025.1.0-legacy-compose-migration"]), {"svc-a": ["migration_backup"]})

    def test_pre_wrong_project_or_service(self):  # estados A e B
        for labels in ({"com.docker.compose.project": "composes", "com.docker.compose.service": "svc-a"},
                       {"com.docker.compose.project": P, "com.docker.compose.service": "old-key"},
                       {}):
            self.assertEqual(self.pre(["Korp.A-2025.1.0"], {"Korp.A-2025.1.0": labels}),
                             {"svc-a": ["identity_conflict"]})

    def test_pre_unknown_labels_are_conflict(self):
        self.assertEqual(self.pre(["Korp.A-2025.1.0"], {}), {"svc-a": ["identity_conflict"]})

    def test_post_legacy_container(self):  # estado C
        self.assertEqual(self.post(["Korp.A-2025.1.0", "Korp.A"]), {"svc-a": ["legacy_container"]})

    def test_service_without_container_name_is_ignored(self):
        services = {"svc-b": {"image": "x"}}
        self.assertEqual(self.pre(["svc-b", "0123456789ab_"], services=services), {})
        self.assertEqual(self.post(["svc-b"], services=services), {})

    def test_unsuffixed_target_has_no_legacy(self):
        services = {"consul": {"container_name": "consul-server"}}
        self.assertEqual(self.post(["consul-server"], services=services), {})


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: rodar e ver falhar** — FAIL.

- [ ] **Step 3: implementação** — `roles/utils/library/korp_compose_state.py`:

```python
#!/usr/bin/python
# -*- coding: utf-8 -*-
from __future__ import absolute_import, division, print_function
__metaclass__ = type

DOCUMENTATION = r'''
module: korp_compose_state
short_description: Resolve um compose e verifica, só com leituras, se a reconciliação por serviço é necessária
description:
  - Executa o mesmo "docker compose ... config --format json" de reconciled_compose_up.yml.
  - Indica (needs_action) se algum serviço está em um estado em que as tarefas originais
    recover_partial_compose_service.yml / reconcile_compose_service.yml (fase pre) ou
    cleanup_legacy_compose_service.yml (fase post) fariam alguma ação ou validação.
  - Nunca altera containers.
options:
  project_src: {type: str, required: true}
  project_name: {type: str, required: true}
  files: {type: list, elements: str, required: true}
  env_files: {type: list, elements: str, default: []}
  version: {type: str, required: true}
  phase: {type: str, required: true, choices: [pre, post]}
  services: {type: dict}
  migration_enabled: {type: bool, default: true}
  force_slow_path: {type: bool, default: false}
'''

import json
import re

from ansible.module_utils.basic import AnsibleModule

BACKUP_SUFFIX = "-legacy-compose-migration"
PROJECT_LABEL = "com.docker.compose.project"
SERVICE_LABEL = "com.docker.compose.service"


def legacy_container_name(container_name, version):
    """Igual a filter_plugins/compose_migration.py."""
    name = str(container_name or "")
    suffix = "-%s" % version
    if version and name.endswith(suffix):
        return name[: -len(suffix)]
    return name


def partial_container_names(container_names, target_name):
    """Igual a filter_plugins/compose_migration.py."""
    target = str(target_name or "")
    if not target:
        return []
    pattern = re.compile(r"^[0-9a-f]{12}_%s$" % re.escape(target))
    return [str(n) for n in container_names or [] if pattern.fullmatch(str(n))]


def compose_config_argv(docker, project_src, project_name, env_files, files):
    argv = [docker, "compose", "--ansi", "never", "--project-directory", project_src,
            "--project-name", project_name]
    for env_file in env_files:
        argv += ["--env-file", env_file]
    for compose_file in files:
        argv += ["--file", compose_file if compose_file.startswith("/") else project_src + "/" + compose_file]
    return argv + ["config", "--format", "json"]


def parse_container_names(text):
    names = set()
    for line in (text or "").splitlines():
        for name in line.split(","):
            name = name.strip()
            if name:
                names.add(name)
    return names


def classify(services, names, labels_by_name, project_name, version, phase):
    """Serviço -> motivos pelos quais as tarefas originais não seriam apenas leituras."""
    reasons = {}
    for key, service in (services or {}).items():
        target = str((service or {}).get("container_name") or "")
        if not target:
            continue
        found = []
        partials = partial_container_names(sorted(names), target)
        if phase == "pre":
            if target not in names and partials:
                found.append("partial_recovery")
            if target + BACKUP_SUFFIX in names:
                found.append("migration_backup")
            if target in names:
                labels = labels_by_name.get(target)
                if (not isinstance(labels, dict)
                        or labels.get(PROJECT_LABEL, "") != project_name
                        or labels.get(SERVICE_LABEL, "") != key):
                    found.append("identity_conflict")
        else:
            legacy = legacy_container_name(target, version)
            if legacy != target and legacy in names:
                found.append("legacy_container")
            if partials:
                found.append("partial_leftover")
        if found:
            reasons[key] = found
    return reasons


def _labels(module, docker, names):
    if not names:
        return {}
    rc, out, err = module.run_command(
        [docker, "container", "inspect", "--format", "{{json .Name}} {{json .Config.Labels}}"] + sorted(names))
    labels = {}
    for line in out.splitlines():
        try:
            name_json, labels_json = line.split(" ", 1)
            labels[json.loads(name_json).lstrip("/")] = json.loads(labels_json) or {}
        except ValueError:
            continue
    return labels  # nomes ausentes ficam sem labels -> tratados como conflito (caminho original)


def main():
    module = AnsibleModule(
        argument_spec=dict(
            project_src=dict(type="str", required=True),
            project_name=dict(type="str", required=True),
            files=dict(type="list", elements="str", required=True),
            env_files=dict(type="list", elements="str", default=[]),
            version=dict(type="str", required=True),
            phase=dict(type="str", required=True, choices=["pre", "post"]),
            services=dict(type="dict"),
            migration_enabled=dict(type="bool", default=True),
            force_slow_path=dict(type="bool", default=False),
        ),
        supports_check_mode=True,
    )
    p = module.params
    docker = module.get_bin_path("docker", required=True)
    services = p["services"]
    if p["phase"] == "pre" or services is None:
        argv = compose_config_argv(docker, p["project_src"], p["project_name"], p["env_files"], p["files"])
        rc, out, err = module.run_command(argv)
        if rc != 0:
            module.fail_json(msg="docker compose config falhou", rc=rc, stderr=err)
        services = (json.loads(out) or {}).get("services") or {}

    if not p["migration_enabled"]:
        module.exit_json(changed=False, services=services, needs_action=False, reasons={})

    rc, out, err = module.run_command([docker, "ps", "--all", "--format", "{{.Names}}"])
    if rc != 0:
        module.fail_json(msg="docker ps falhou", rc=rc, stderr=err)
    names = parse_container_names(out)
    targets = {str((s or {}).get("container_name") or "") for s in services.values()}
    labels = _labels(module, docker, [t for t in targets if t and t in names]) if p["phase"] == "pre" else {}
    reasons = classify(services, names, labels, p["project_name"], p["version"], p["phase"])
    module.exit_json(changed=False, services=services,
                     needs_action=bool(reasons) or p["force_slow_path"], reasons=reasons)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: rodar** — PASS.
- [ ] **Step 5: commit** — `git commit -m "perf(setup): módulo korp_compose_state (classificação somente-leitura)"`

---

### Task 5: Reconciliação de compose usando o fast path + chave de desligamento

**Files:**
- Modify: `roles/utils/tasks/apps/reconciled_compose_up.yml`
- Create: `roles/utils/defaults/main.yml`
- Modify: `setup.sh`

**Interfaces:**
- Consumes: `korp_compose_state` (Task 4).
- Produces: variável `korp_setup_fast_path` (bool); `setup.sh fast_path=<true|false>`.

- [ ] **Step 1:** `roles/utils/defaults/main.yml`:

```yaml
# Fast path do setup (docs/files/guias/desempenho_setup.rst).
# true  -> pula verificações por serviço que não teriam efeito e cadastra os serviços de cada role em lote.
# false -> executa exatamente as tarefas originais por serviço (setup.sh fast_path=false).
korp_setup_fast_path: true
```

- [ ] **Step 2:** substituir em `reconciled_compose_up.yml` as tarefas de montagem de argv/`config`/`set_fact` e os três loops por:

```yaml
- name: Resolução da configuração efetiva do compose e análise das identidades
  korp_compose_state:
    project_src: "{{ compose_reconcile_project_src }}"
    project_name: "{{ compose_reconcile_project_name }}"
    files: "{{ compose_reconcile_files }}"
    env_files: "{{ compose_reconcile_env_files }}"
    version: "{{ version_without_build }}"
    phase: pre
    migration_enabled: "{{ compose_migration_enabled | default(true) | bool }}"
    force_slow_path: "{{ not (korp_setup_fast_path | default(true) | bool) }}"
  register: compose_reconcile_state
  no_log: true

- name: Definição dos serviços efetivos do compose
  ansible.builtin.set_fact:
    compose_reconcile_services: "{{ compose_reconcile_state.services }}"
  no_log: true

- name: Serviços que exigem reconciliação de identidade
  ansible.builtin.debug:
    msg: "{{ compose_reconcile_state.reasons }}"
  when: compose_reconcile_state.reasons | length > 0

- name: Recuperação de containers parciais sem identidade canônica
  ansible.builtin.include_tasks: "{{ role_path }}/tasks/apps/recover_partial_compose_service.yml"
  loop: "{{ (compose_reconcile_services | dict2items) if compose_reconcile_state.needs_action else [] }}"
  loop_control:
    loop_var: compose_reconcile_service
    label: "{{ compose_reconcile_service.key }}"

- name: Reconciliação de containers com nome físico conflitante
  ansible.builtin.include_tasks: "{{ role_path }}/tasks/apps/reconcile_compose_service.yml"
  loop: "{{ (compose_reconcile_services | dict2items) if compose_reconcile_state.needs_action else [] }}"
  loop_control:
    loop_var: compose_reconcile_service
    label: "{{ compose_reconcile_service.key }}"

- name: Inicialização do compose reconciliado
  community.docker.docker_compose_v2:
    project_src: "{{ compose_reconcile_project_src }}"
    project_name: "{{ compose_reconcile_project_name }}"
    env_files: "{{ compose_reconcile_env_files }}"
    files: "{{ compose_reconcile_files }}"

- name: Análise de containers legados após a inicialização
  korp_compose_state:
    project_src: "{{ compose_reconcile_project_src }}"
    project_name: "{{ compose_reconcile_project_name }}"
    files: "{{ compose_reconcile_files }}"
    env_files: "{{ compose_reconcile_env_files }}"
    version: "{{ version_without_build }}"
    phase: post
    services: "{{ compose_reconcile_services }}"
    force_slow_path: "{{ not (korp_setup_fast_path | default(true) | bool) }}"
  register: compose_reconcile_state_post
  no_log: true
  when: compose_migration_enabled | default(true) | bool

- name: Containers legados a remover
  ansible.builtin.debug:
    msg: "{{ compose_reconcile_state_post.reasons }}"
  when: compose_reconcile_state_post.reasons | default({}) | length > 0

- name: Remoção segura de containers legados substituídos
  ansible.builtin.include_tasks: "{{ role_path }}/tasks/apps/cleanup_legacy_compose_service.yml"
  loop: "{{ (compose_reconcile_services | dict2items) if (compose_reconcile_state_post.needs_action | default(false)) else [] }}"
  loop_control:
    loop_var: compose_reconcile_service
    label: "{{ compose_reconcile_service.key }}"
```

Com `migration_enabled: false` o módulo devolve `needs_action: false` → loops vazios (igual ao `when` original).

- [ ] **Step 3:** `setup.sh`: documentar `fast_path=<bool> - OPCIONAL, padrão true` no cabeçalho de parâmetros; inicializar `fast_path=true;` junto de `skip_salt_test=false;`; acrescentar `"korp_setup_fast_path": '$fast_path'` ao JSON de `--extra-vars` do `bootstrap-playbook.yml` (depois de `should_update_rabbitmq`).
- [ ] **Step 4:** `ansible-playbook --syntax-check` de `bootstrap-playbook.yml` e `main.yml` (no container do ambiente isolado) → OK.
- [ ] **Step 5: commit** — `git commit -m "perf(setup): reconciliação de compose só executa loops por serviço quando necessário"`

---

### Task 6: Cadastro de serviços em lote

**Files:**
- Modify: `roles/utils/tasks/services/add_service.yml`
- Create: `roles/utils/tasks/services/add_services_batch.yml`, `roles/utils/templates/queries/create_db_postgres.sh.j2`

**Interfaces:**
- Consumes: filtros (Task 2), `korp_consul_kv_batch` (Task 3), `korp_setup_fast_path` (Task 5).

- [ ] **Step 1:** `add_service.yml` — manter "Startup" (primeira iteração) e "Setup de composes e registro" (última) como estão; inserir após o Startup:

```yaml
- name: "Cadastro em lote dos serviços de {{ id }}"
  ansible.builtin.include_tasks: "{{ role_path }}/tasks/services/add_services_batch.yml"
  when:
    - korp_setup_fast_path | default(true) | bool
    - ansible_loop.first
```

e envolver as tarefas por serviço originais (validação, secret, KV, oauth, banco, volumes) num bloco:

```yaml
- name: "Cadastro individual de {{ service_name }}"
  when: not (korp_setup_fast_path | default(true) | bool)
  block:
    # (tarefas originais, sem alteração)
```

- [ ] **Step 2:** `roles/utils/templates/queries/create_db_postgres.sh.j2` com exatamente a linha de comando de `create_db/postgres.yml`:

```
docker exec -i "{{ postgres_container_name }}" bash -c "psql -U '{{ postgres.korp_user }}' -d postgres -tAc \"SELECT 'CREATE DATABASE \\\"{{ db_name}}\\\" OWNER ''{{ postgres.korp_user }}''' WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = '{{ db_name}}')\"" | docker exec -i postgres psql -U postgres -d postgres
```

- [ ] **Step 3:** `add_services_batch.yml`:

```yaml
# Cadastro em lote (fast path) dos serviços do loop de add_service.yml.
# Para cada serviço, na mesma ordem, equivale a vars_validation.yml, ensure_kv.yml,
# ensure_client.yml/add_client.yml, create_db/<tipo>.yml e ensure_volume_folder.yml.
# Ver docs/desempenho/2026-10-02-desempenho-setup-design.md (seção 4.2).

- name: "Planejamento do cadastro dos serviços de {{ id }}"
  ansible.builtin.set_fact:
    korp_batch: >-
      {{ services | korp_service_plan(ansible_loop.allitems | map(attribute='key') | list,
                                      db_suffix_divider, db_suffix) }}

- name: "Validação de variáveis dos serviços de {{ id }}"
  ansible.builtin.fail:
    msg: "Um ou mais valores não foram setados nas variáveis de {{ korp_batch.invalid[0] }}"
  when: korp_batch.invalid | length > 0

- name: "Validação do tipo de banco dos serviços de {{ id }}"
  ansible.builtin.fail:
    msg: >-
      Tipo de banco '{{ korp_batch.unsupported_databases[0].type }}' não suportado
      ({{ korp_batch.unsupported_databases[0].service }})
  when: korp_batch.unsupported_databases | length > 0

- name: "Definição dos valores padrão das variáveis dos serviços de {{ id }}"
  ansible.builtin.set_fact:
    services: "{{ korp_batch.services }}"

- name: "Renderização dos KVs dos serviços de {{ id }}"
  ansible.builtin.set_fact:
    korp_rendered_kv: >-
      {{ lookup('ansible.builtin.template', 'consul_kv/' ~ (korp_svc | lower) ~ '.json.j2',
                template_vars={'service_name': korp_svc,
                               'service_vars': korp_batch.service_vars[korp_svc],
                               'secret': korp_batch.secrets[korp_svc]}) }}
  loop: "{{ korp_batch.kv_services }}"
  loop_control:
    loop_var: korp_svc
  register: korp_kv_render

- name: "Garantia dos KVs no Consul dos serviços de {{ id }}"
  korp_consul_kv_batch:
    items: "{{ korp_kv_render.results | default([]) | korp_kv_batch_items(services) }}"
    default_kv_overwrite: "{{ default_kv_overwrite }}"
    custom_kv_overwrite: "{{ custom_kv_overwrite | default(omit) }}"
    custom_kv_overwrite_defined: "{{ custom_kv_overwrite is defined }}"
    read_keys: "{{ korp_batch.oauth_services }}"
  register: korp_kv_batch_result
  when: (korp_batch.kv_services | length > 0) or (korp_batch.oauth_services | length > 0)

- name: "Manutenção de custom_kv_overwrite para os próximos serviços"
  ansible.builtin.set_fact:
    custom_kv_overwrite: "{{ korp_kv_batch_result.custom_kv_overwrite }}"
  when: korp_kv_batch_result.custom_kv_overwrite_set | default(false)

- name: "Renderização dos clientes oauth de {{ id }}"
  ansible.builtin.set_fact:
    korp_rendered_sql: >-
      {{ lookup('ansible.builtin.template', 'queries/add_oauth_client.sql.j2',
                template_vars={'service_name': korp_client.service_name,
                               'secret_as_hash': korp_client.secret_as_hash}) | string }}
  loop: "{{ korp_kv_batch_result.values | default({}) | korp_oauth_clients(korp_batch.oauth_services) }}"
  loop_control:
    loop_var: korp_client
    label: "{{ korp_client.service_name }}"
  register: korp_oauth_render

- name: "Adição dos clientes oauth2 de {{ id }}"
  community.general.mssql_script:
    login_user: "{{ mssql.korp_user }}"
    login_password: "{{ mssql.korp_password }}"
    login_host: "{{ mssql.address }}"
    name: "{{ authentication_db_name }}"
    script: "{{ korp_oauth_render.results | map(attribute='ansible_facts.korp_rendered_sql') | join(korp_sql_go) }}"
  vars:
    korp_sql_go: "\nGO\n"
  when: korp_batch.oauth_services | length > 0

- name: "Renderização dos bancos SQL Server de {{ id }}"
  ansible.builtin.set_fact:
    korp_rendered_sql: >-
      {{ lookup('ansible.builtin.template', 'templates/queries/create_db_mssql.j2',
                template_vars={'db_name': korp_db.name}) | string }}
  loop: "{{ korp_batch.mssql_databases }}"
  loop_control:
    loop_var: korp_db
    label: "{{ korp_db.name }}"
  register: korp_mssql_render

- name: "Criação dos bancos de dados SQL Server de {{ id }}"
  community.general.mssql_script:
    login_user: "{{ mssql.korp_user }}"
    login_password: "{{ mssql.korp_password }}"
    login_host: "{{ mssql.address }}"
    name: master
    script: "{{ korp_mssql_render.results | map(attribute='ansible_facts.korp_rendered_sql') | join(korp_sql_go) }}"
  vars:
    korp_sql_go: "\nGO\n"
  when: korp_batch.mssql_databases | length > 0

- name: "Renderização dos bancos PostgreSql de {{ id }}"
  ansible.builtin.set_fact:
    korp_rendered_cmd: >-
      {{ lookup('ansible.builtin.template', 'queries/create_db_postgres.sh.j2',
                template_vars={'db_name': korp_db.name}) | string }}
  loop: "{{ korp_batch.postgres_databases }}"
  loop_control:
    loop_var: korp_db
    label: "{{ korp_db.name }}"
  register: korp_pg_render

- name: "Criação dos bancos de dados PostgreSql de {{ id }}"
  ansible.builtin.shell: "{{ (['set -e'] + (korp_pg_render.results | map(attribute='ansible_facts.korp_rendered_cmd') | list)) | join(korp_newline) }}"
  vars:
    korp_newline: "\n"
  when: korp_batch.postgres_databases | length > 0

- name: "Verificação dos diretórios de volume de {{ id }}"
  ansible.builtin.stat:
    path: "{{ korp_volume_path }}"
  loop: "{{ korp_batch.volume_directories }}"
  loop_control:
    loop_var: korp_volume_path
  register: korp_volume_stat

- name: "Criação dos diretórios de volume de {{ id }}"
  ansible.builtin.file:
    path: "{{ korp_volume_missing.korp_volume_path }}"
    state: directory
    mode: '0755'
    owner: "{{ linux_korp.user }}"
    group: root
  loop: "{{ korp_volume_stat.results | default([]) | rejectattr('stat.exists') | list }}"
  loop_control:
    loop_var: korp_volume_missing
    label: "{{ korp_volume_missing.korp_volume_path }}"

- name: "Definição das variáveis do último serviço de {{ id }}"
  ansible.builtin.set_fact:
    service_vars: "{{ korp_batch.service_vars[korp_batch.last_service] }}"
    secret: "{{ korp_batch.secrets[korp_batch.last_service] }}"
  when: korp_batch.last_service is not none
```

- [ ] **Step 4:** syntax-check (como Task 5) → OK.
- [ ] **Step 5: commit** — `git commit -m "perf(setup): cadastro de serviços em lote por role"`

---

### Task 7: Ambiente isolado e comparação de estado

**Files:**
- Create: `tests/sim/` (Dockerfile, `simctl.sh`, `sim-entry`, `sim-prepare.sh`, `pty_run.py`, `sim_tag_images.py`, `gateway/mock_gateway.py`, `sql/auth_schema.sql`, `fake-image/`, `stubs/docker_login.py`, `state_dump.py`, `README.md`), `.gitignore` (`tests/sim/.work/`)

- [ ] **Step 1:** levar para o repositório o ambiente usado nas medições (sem nada da QA12 ou desta VM): imagem Ubuntu 22.04 + Docker 24.0.2 + Compose 2.18.1 + Ansible PPA + community.docker 5.3.0; gateway simulado; MSSQL; imagem falsa; stub de `docker_login` (só no ambiente isolado); `simctl.sh` com `infra-up`, `host-up`, `seed`, `pull-public`, `setup`, `snapshot`, `restore`, `dump`.
- [ ] **Step 2:** `state_dump.py` (roda dentro do host isolado) gera JSON determinístico com: KVs do Consul (JSON normalizado; `Authorization.Secret` mascarado apenas para chaves criadas na execução), tabelas OAuth (ApiResources/ApiScopes/Clients/ClientGrantTypes/ClientScopes/ClientSecrets sem datas, `Value` mascarado como o segredo), bancos MSSQL e usuários, bancos Postgres e donos, árvore `/etc/korp` (caminho, tipo, modo, dono, sha256 — exceto `ansible/logs`, certificados gerados e `.env`), `installed_apps.yml`, containers (nome, imagem, projeto, serviço, estado).
- [ ] **Step 3:** `simctl.sh dump NAME OUT` + `simctl.sh compare A B` (diff dos JSON).
- [ ] **Step 4: commit** — `git commit -m "test(setup): ambiente isolado de medição e comparação de estado"`

### Task 8: Execução da matriz no ambiente isolado (2025.1)

Para cada cenário: restaurar o mesmo snapshot, rodar original (`sim/base-2025.1`) e otimizado (branch de desempenho), medir (`pty_run.py`), extrair dump e comparar.

| # | Cenário | Snapshot inicial | Comando (`simctl.sh setup ...`) |
|---|---|---|---|
| S1 | instalação 2024.2 | `seeded` | `branch_name=<ref 2024.2> ... apps=vendas,LOG103,LOG102,ERP,FLOW01,logistica,workflow,fiscal` |
| S2 | reexecução sem mudanças 2024.2 (`update`) | após S1 | `custom_tags=update` |
| S3 | atualização 2024.2→2025.1 (`update`) | após S1 | token na versão 2025.1.0 |
| S4 | reexecução sem mudanças 2025.1 | após S3 | `custom_tags=update` |
| S5 | primeira execução sobre estado legado real (instalação com `repro/devo-7182*-old`, atualização com o código novo) | `seeded` | — |
| S6 | estados construídos (parcial, backup, conflito de identidade, legado sem sufixo) | após S3 | — |
| S7 | `install-only` de app novo | após S4 | `custom_tags=install-only apps=VEN27` |
| S8 | `remove-apps`/`uninstall-version` | após S4 | — |
| S9 | falha no meio (MSSQL parado) + reexecução + volta ao branch original | após S3 | — |
| S10 | `fast_path=false` igual ao original | após S1 | — |

- [ ] **Step 1..n:** executar, registrar tempos e diffs em `docs/files/guias/desempenho_setup_resultados.rst`; investigar toda divergência (systematic-debugging) e corrigir com teste.

### Task 9: Porte para 2024.2

- [ ] **Step 1:** `git cherry-pick` dos commits das Tasks 1–7 na branch `release/2024.2.0.x-performance-test`; resolver apenas `setup.sh` (a 2024.2 usa `PIPESTATUS[0]`).
- [ ] **Step 2:** testes unitários + syntax-check + cenários S1, S2, S6, S10 com o código 2024.2.

### Task 10: Documentação, revisão e publicação

- [ ] `docs/files/guias/desempenho_setup.rst` (diagnóstico, decisões, compatibilidade, execução, recuperação) + entrada no `docs/index.rst` + seção curta no `readme.md`.
- [ ] Revisão de código independente nas duas branches; corrigir achados relevantes.
- [ ] `git push -u origin release/2025.1.0.x-performance-test` e `release/2024.2.0.x-performance-test`; conferir com `git ls-remote`.
