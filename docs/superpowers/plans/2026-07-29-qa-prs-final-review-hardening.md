# QA PRs Final Review Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Corrigir ownership repo-qualified, validação de chaves MinIO e preflight destrutivo do reset sem alterar a interface operacional do MVP.

**Architecture:** O filtro Python continua sendo a fonte pura de validação e planejamento. Overrides novos persistem repositório e número, enquanto overrides legados permanecem legíveis e conflitam conservadoramente. A role de reset reutiliza a validação pura e executa um Compose check mode completo antes de qualquer deleção.

**Tech Stack:** Python 3 `unittest`, filtros Ansible, YAML/PyYAML, `community.docker.docker_compose_v2`, ansible-core 2.18, ansible-lint.

## Global Constraints

- Apenas relatórios `kind=container`.
- Manter `https://minio-interno-api.korp.com.br`, bucket `qa-prs`, acesso anônimo e TLS validado.
- Manter `<project_src>/pr-overrides/pr<N>/<compose_file>` e a label `korp.pr`.
- Adicionar `korp.repositorio` sem incluir o repositório no caminho.
- Comparar ownership por `<repositorio>#<N>`; owner legado `#<N>` conflita com qualquer PR repo-qualified.
- Resolver todos os conflitos antes de qualquer mutação.
- Reset deve provar parse, schema, arquivo base regular e Compose válido antes da primeira deleção.
- O plugin canônico deve existir somente em `filter_plugins/qa_pr_filters.py`, compartilhado pelos dois playbooks.
- Não usar `remove_orphans`, não alterar `setup.sh`, `main.yml`, Delphi ou manifests de dependência.
- Manter a exceção de lint existente fora do escopo deste hardening.

---

### Task 1: Ownership repo-qualified, MinIO direto e alerta operacional

**Files:**
- Modify: `roles/qa_pr_apply/filter_plugins/qa_pr_filters.py`
- Modify: `roles/qa_pr_apply/tasks/load_report.yml`
- Modify: `docs/ambiente-qualidade-prs.md`
- Modify: `tests/unit/test_qa_pr_filters.py`
- Modify: `tests/unit/test_qa_pr_role_yaml.py`

**Interfaces:**
- Consumes: targets com `repo`, `pr` e `pr_key="<repo>#<N>"`.
- Produces: owners persistidos com `pr_key="<repo>#<N>"` ou `pr_key="#<N>"` para legado.
- Produces: writes com labels `korp.pr` e `korp.repositorio`.
- Produces: `parse_minio_listing(...)` contendo somente objetos JSON diretamente sob o prefixo.

- [ ] **Step 1: Escrever regressões de ownership e listagem**

Adicionar casos equivalentes a:

```python
def test_same_number_from_different_repositories_conflicts(self):
    current = target("repo-a#123", 123, "wms-core")
    incoming = target("repo-b#123", 123, "wms-core")
    conflicts = detect_conflicts([current, incoming], {})
    self.assertEqual([incoming["target_id"]], [c["target_id"] for c in conflicts])

def test_repo_qualified_refresh_does_not_conflict(self):
    incoming = target("repo-a#123", 123, "wms-core")
    owner = {**incoming, "pr_key": "repo-a#123"}
    self.assertEqual([], detect_conflicts([incoming], {incoming["identity"]: owner}))

def test_legacy_numeric_owner_conflicts_conservatively(self):
    incoming = target("repo-a#123", 123, "wms-core")
    owner = {**incoming, "pr_key": "#123"}
    self.assertEqual(1, len(detect_conflicts([incoming], {incoming["identity"]: owner})))

def test_listing_rejects_nested_json_objects(self):
    xml = """
    <ListBucketResult>
      <IsTruncated>false</IsTruncated>
      <Contents><Key>prs/repo-a/123/service.json</Key></Contents>
      <Contents><Key>prs/repo-a/123/nested/other.json</Key></Contents>
    </ListBucketResult>
    """
    self.assertEqual(
        ["prs/repo-a/123/service.json"],
        parse_minio_listing(xml, "prs/repo-a/123/"),
    )
```

Estender os testes de mutation plan para exigir:

```python
self.assertEqual(
    {"korp.pr": "123", "korp.repositorio": "repo-a"},
    written_service["labels"],
)
```

No teste YAML da role, exigir `qa_pr_report_key | urlencode` na URL de
`load_report.yml`. No teste documental, exigir a expressão
`ambiente de cliente final` no guia.

- [ ] **Step 2: Executar RED focado**

Run:

```bash
python3 -m unittest \
  tests.unit.test_qa_pr_filters.ConflictPlanningTests \
  tests.unit.test_qa_pr_filters.MutationShapeTests \
  tests.unit.test_qa_pr_filters.MinioParsingTests \
  tests.unit.test_qa_pr_role_yaml -v
```

Expected: falhas apenas por comparação numérica, ausência de
`korp.repositorio`, aceitação da chave aninhada, URL sem `urlencode` e alerta
operacional ausente.

- [ ] **Step 3: Implementar ownership repo-qualified**

Em `index_active_overrides`, validar o repositório opcional com o mesmo
alfabeto aceito pelos links e construir:

```python
raw_repo = labels.get("korp.repositorio")
if raw_repo is None:
    pr_key = f"#{pr}"
elif not isinstance(raw_repo, str) or not _REPOSITORY.fullmatch(raw_repo):
    raise ValueError(
        f"Label korp.repositorio inválida em {override_path}: {raw_repo!r}"
    )
else:
    pr_key = f"{raw_repo}#{pr}"
```

Em `detect_conflicts` e `resolve_application`, substituir comparações de
`current["pr"] != target["pr"]` por:

```python
current["pr_key"] != target["pr_key"]
```

Ao construir o conteúdo final do override, persistir:

```python
"labels": {
    "korp.pr": str(target["pr"]),
    "korp.repositorio": target["repo"],
}
```

- [ ] **Step 4: Restringir listagem e codificar chave**

Em `parse_minio_listing`, aceitar a chave somente quando o sufixo após o
prefixo for um único filename:

```python
suffix = key[len(prefix):]
if suffix and "/" not in suffix and suffix.endswith(".json"):
    keys.append(key)
```

Em `load_report.yml`, usar:

```yaml
url: >-
  {{ qa_pr_minio_api }}/{{ qa_pr_minio_bucket }}/{{
    qa_pr_report_key | urlencode
  }}
```

- [ ] **Step 5: Corrigir o risco documentado**

Em `docs/ambiente-qualidade-prs.md`, declarar separadamente:

```markdown
- Não há trava automática contra executar estes playbooks privilegiados em
  ambiente de cliente final; confirme o host antes da execução.
- A aplicação pode inicializar serviços e executar seus efeitos de startup.
```

- [ ] **Step 6: Executar GREEN e suíte completa**

Run:

```bash
python3 -m unittest \
  tests.unit.test_qa_pr_filters \
  tests.unit.test_qa_pr_role_yaml -v
python3 -m unittest discover -s tests/unit -v
git diff --check
```

Expected: todos os comandos exit 0.

- [ ] **Step 7: Commit**

```bash
git add \
  roles/qa_pr_apply/filter_plugins/qa_pr_filters.py \
  roles/qa_pr_apply/tasks/load_report.yml \
  docs/ambiente-qualidade-prs.md \
  tests/unit/test_qa_pr_filters.py \
  tests/unit/test_qa_pr_role_yaml.py
git commit -m "DEVO-6789 - Qualifica ownership por repositorio"
```

---

### Task 2: Preflight completo antes do reset

**Files:**
- Move: `roles/qa_pr_apply/filter_plugins/qa_pr_filters.py` → `filter_plugins/qa_pr_filters.py`
- Modify: `roles/qa_pr_reset/tasks/main.yml`
- Modify: `roles/qa_pr_reset/tasks/read_override.yml`
- Modify: `tests/unit/test_qa_pr_filters.py`
- Modify: `tests/unit/test_qa_pr_reset_role_yaml.py`

**Interfaces:**
- Consumes: lista `qa_pr_reset_override_files` com `path` e conteúdo YAML convertido.
- Uses: `qa_pr_index_active_overrides` do plugin compartilhado como validação pura de path/schema/labels.
- Produces: `qa_pr_reset_runs` únicos e validados antes da deleção.
- Side effect preflight: `docker_compose_v2` com `check_mode: true`; não altera containers.

- [ ] **Step 1: Escrever regressões de schema e ordering**

Adicionar testes Python que rejeitem:

```python
invalid_overrides = [
    {"path": "/srv/pr-overrides/pr123/app-compose.yml", "content": []},
    {"path": "/srv/pr-overrides/pr123/app-compose.yml", "content": {"services": {}}},
    {
        "path": "/srv/pr-overrides/pr123/app-compose.yml",
        "content": {"services": {"api": {"labels": {"korp.pr": "123"}}}},
    },
    {
        "path": "/srv/pr-overrides/pr123/nested/app-compose.yml",
        "content": {"services": {"api": {
            "image": "korp/api:pr123",
            "labels": {"korp.pr": "123"},
        }}},
    },
]
```

Cada caso deve levantar `ValueError`. Adicionar caso válido legado sem
`korp.repositorio`, que deve produzir `pr_key="#123"`.

Nos testes YAML, exigir esta ordem:

```python
self.assertLess(read_index, validate_override_index)
self.assertLess(validate_override_index, stat_index)
self.assertLess(stat_index, assert_index)
self.assertLess(assert_index, compose_check_index)
self.assertLess(compose_check_index, delete_index)
self.assertLess(delete_index, reset_index)
```

Exigir também:

```python
self.assertTrue(base_assert_checks_exists_and_isreg)
self.assertTrue(compose_check_task["check_mode"])
self.assertEqual(
    compose_check_module["files"],
    ["{{ qa_pr_reset_run.compose_file }}"],
)
```

- [ ] **Step 2: Executar RED focado**

Run:

```bash
python3 -m unittest \
  tests.unit.test_qa_pr_filters.MutationShapeTests \
  tests.unit.test_qa_pr_reset_role_yaml -v
```

Expected: falhas por schema permissivo, ausência da coleção parseada, ausência
de `stat.isreg` e ausência do Compose check mode antes da deleção.

- [ ] **Step 3: Provar RED de carregamento e compartilhar o plugin**

Antes da movimentação, executar pela raiz:

```bash
source /tmp/devo-6789-ansible/bin/activate
ANSIBLE_COLLECTIONS_PATH=/tmp/devo-6789-collections \
  ansible localhost -i 'localhost,' -c local \
  -m ansible.builtin.debug \
  -a 'msg={{ [] | qa_pr_index_active_overrides }}'
```

Expected RED: falha `Could not load "qa_pr_index_active_overrides"` porque o
plugin ainda é privado de `qa_pr_apply`.

Mover a implementação única:

```bash
mkdir -p filter_plugins
git mv \
  roles/qa_pr_apply/filter_plugins/qa_pr_filters.py \
  filter_plugins/qa_pr_filters.py
```

Atualizar `PLUGIN_PATH` em `tests/unit/test_qa_pr_filters.py` para:

```python
PLUGIN_PATH = ROOT / "filter_plugins/qa_pr_filters.py"
```

Repetir o comando Ansible. Expected GREEN: exit 0 e mensagem `{}`. Não
criar cópia, wrapper ou import entre roles.

- [ ] **Step 4: Fortalecer a validação pura**

Em `index_active_overrides`, exigir:

```python
if not isinstance(content, dict):
    raise ValueError(f"Override YAML inválido em {override_path}")
services = content.get("services")
if not isinstance(services, dict) or not services:
    raise ValueError(f"Override sem services em {override_path}")
if not isinstance(config, dict):
    raise ValueError(f"Serviço inválido em {override_path}: {service_key}")
if not isinstance(config.get("image"), str) or not config["image"]:
    raise ValueError(f"Imagem inválida em {override_path}: {service_key}")
if not isinstance(config.get("labels"), dict):
    raise ValueError(f"Labels inválidas em {override_path}: {service_key}")
```

Restringir `_OVERRIDE_PATH` a um arquivo direto terminado em
`-compose.yml`. Manter as validações de PR positivo, igualdade path/label,
repositório opcional e owner duplicado.

- [ ] **Step 5: Acumular e validar overrides no reset**

Inicializar em `main.yml`:

```yaml
qa_pr_reset_override_files: []
```

Em `read_override.yml`, após o `slurp`, acumular:

```yaml
qa_pr_reset_override_files: >-
  {{
    qa_pr_reset_override_files
    + [
        {
          'path': qa_pr_reset_slurped_override.qa_pr_reset_override.path,
          'content': (
            qa_pr_reset_slurped_override.content | b64decode | from_yaml
          )
        }
      ]
  }}
```

Depois de todos os includes de leitura e antes do `stat`, executar:

```yaml
- name: Validar todos os overrides antes do reset
  ansible.builtin.set_fact:
    qa_pr_reset_active_owners: >-
      {{ qa_pr_reset_override_files | qa_pr_index_active_overrides }}
```

- [ ] **Step 6: Provar baseline executável antes da deleção**

No assert de base, exigir:

```yaml
that:
  - qa_pr_reset_base_file.stat.exists | bool
  - qa_pr_reset_base_file.stat.isreg | bool
```

Antes da task que remove as raízes, adicionar:

```yaml
- name: Validar composes base antes de remover overrides
  community.docker.docker_compose_v2:
    project_src: "{{ qa_pr_reset_run.project_src }}/"
    env_files:
      - "{{ docker_env_file_path }}"
    files:
      - "{{ qa_pr_reset_run.compose_file }}"
  check_mode: true
  loop: "{{ qa_pr_reset_runs }}"
  loop_control:
    loop_var: qa_pr_reset_run
```

Qualquer erro do módulo deve interromper o play antes da primeira task
`state: absent`.

- [ ] **Step 7: Executar GREEN e gates integrados**

Run:

```bash
python3 -m unittest \
  tests.unit.test_qa_pr_filters \
  tests.unit.test_qa_pr_reset_role_yaml -v
python3 -m unittest discover -s tests/unit -v
source /tmp/devo-6789-ansible/bin/activate
export ANSIBLE_COLLECTIONS_PATH=/tmp/devo-6789-collections
/tmp/devo-6789-ansible/bin/ansible-playbook \
  -i '127.0.0.1,' --syntax-check pr-playbook.yml
/tmp/devo-6789-ansible/bin/ansible-playbook \
  -i '127.0.0.1,' --syntax-check pr-reset-playbook.yml
/tmp/devo-6789-ansible/bin/ansible-lint \
  filter_plugins \
  roles/qa_pr_apply roles/qa_pr_reset \
  pr-playbook.yml pr-reset-playbook.yml
git diff --check
```

Expected: todos os comandos exit 0, sem warnings de lint ou syntax-check.

- [ ] **Step 8: Commit**

```bash
git add \
  filter_plugins/qa_pr_filters.py \
  roles/qa_pr_apply/filter_plugins/qa_pr_filters.py \
  roles/qa_pr_reset/tasks/main.yml \
  roles/qa_pr_reset/tasks/read_override.yml \
  tests/unit/test_qa_pr_filters.py \
  tests/unit/test_qa_pr_reset_role_yaml.py
git commit -m "DEVO-6789 - Valida reset antes de remover overrides"
```

