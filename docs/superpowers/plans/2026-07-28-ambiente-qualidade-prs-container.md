# Ambiente de Qualidade por PRs — Fase Container Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** Implementar no KorpSetupLinux a aplicação incremental e o reset de imagens de PR em serviços container, incluindo resolução híbrida de conflitos e playbooks operacionais.

**Architecture:** A role qa_pr_apply orquestra entrada, leitura anônima do MinIO, descoberta dos serviços nos composes renderizados, preflight de conflitos, escrita de overrides e aplicação dirigida aos serviços afetados. A lógica determinística fica em um filter plugin Python sem dependências externas, permitindo TDD com unittest; a role qa_pr_reset lê os overrides, remove-os e reaplica os composes base.

**Tech Stack:** Ansible Core, community.docker.docker_compose_v2, Python 3 standard library, unittest, Docker Compose v2, MinIO S3 HTTP API.

## Global Constraints

- Escopo deste plano: somente kind=container na VM Linux; Delphi permanece na fase 2.
- Não alterar setup.sh, main.yml nem o baseline usado em cliente final.
- Não adicionar collection, CLI, boto3 ou credencial para ler o MinIO.
- Usar somente https://minio-interno-api.korp.com.br, com TLS verificado.
- Ler anonimamente o bucket qa-prs e o prefixo prs/<repo>/<N>/.
- Receber PRs por links completos https://github.com/viasoftkorp/<repo>/pull/<N>.
- Usar imagem e tag exatamente como vierem do relatório; não reconstruir a tag.
- Procurar somente composes renderizados na raiz e em versioned_compose_dir_path.
- Manter overrides dentro do project_src em pr-overrides/pr<N>/.
- Nunca habilitar remove_orphans.
- Aplicar somente as chaves YAML dos serviços afetados por meio de services.
- O default de pr_conflict_policy é ask; políticas não interativas são replace, keep e fail.
- Resolver todos os conflitos antes da primeira mutação.
- Reset remove todos os overrides e reaplica os composes base afetados.
- Não validar versão do PR contra a VM e não adicionar guarda de ambiente cliente.
- Preservar community.docker >=3.10.3 já instalada pelo setup.

---

### Task 1: Contrato de entrada e parsing do MinIO

**Files:**
- Create: roles/qa_pr_apply/filter_plugins/qa_pr_filters.py
- Create: tests/unit/test_qa_pr_filters.py
- Create: tests/fixtures/qa_prs/listing.xml
- Create: tests/fixtures/qa_prs/korp.compras.core.json

**Interfaces:**
- Produces: normalize_pr_links(value, organization="viasoftkorp") -> list[dict]
- Produces: parse_minio_listing(xml_text, prefix) -> list[str]
- Produces: load_report(json_text, expected_repo, expected_pr, expected_key) -> dict
- Consumes: string CSV ou lista de links, XML ListObjectsV2 e JSON de relatório.

- [ ] **Step 1: Write failing input parsing tests**

Create tests/unit/test_qa_pr_filters.py with imports through importlib.util so Ansible does not need to be installed:

~~~python
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import json
import unittest

ROOT = Path(__file__).resolve().parents[2]
PLUGIN_PATH = ROOT / "roles/qa_pr_apply/filter_plugins/qa_pr_filters.py"
spec = spec_from_file_location("qa_pr_filters", PLUGIN_PATH)
filters = module_from_spec(spec)
spec.loader.exec_module(filters)


class NormalizePrLinksTests(unittest.TestCase):
    def test_accepts_csv_and_preserves_order(self):
        value = (
            "https://github.com/viasoftkorp/compras/pull/123,"
            " https://github.com/viasoftkorp/vendas/pull/456/"
        )
        self.assertEqual(
            filters.normalize_pr_links(value),
            [
                {
                    "url": "https://github.com/viasoftkorp/compras/pull/123",
                    "repo": "compras",
                    "pr": 123,
                    "key": "compras#123",
                },
                {
                    "url": "https://github.com/viasoftkorp/vendas/pull/456/",
                    "repo": "vendas",
                    "pr": 456,
                    "key": "vendas#456",
                },
            ],
        )

    def test_rejects_unqualified_or_foreign_links(self):
        for value in ("123", "https://github.com/outra/compras/pull/123"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                filters.normalize_pr_links(value)

    def test_rejects_empty_input(self):
        with self.assertRaises(ValueError):
            filters.normalize_pr_links("")


class MinioParsingTests(unittest.TestCase):
    def test_extracts_only_json_keys_under_expected_prefix(self):
        xml_text = (ROOT / "tests/fixtures/qa_prs/listing.xml").read_text()
        self.assertEqual(
            filters.parse_minio_listing(xml_text, "prs/compras/123/"),
            ["prs/compras/123/korp.compras.core.json"],
        )

    def test_rejects_truncated_listing(self):
        xml_text = """
        <ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">
          <IsTruncated>true</IsTruncated>
        </ListBucketResult>
        """
        with self.assertRaises(ValueError):
            filters.parse_minio_listing(xml_text, "prs/compras/123/")


class ReportParsingTests(unittest.TestCase):
    def test_validates_container_report_against_object_key(self):
        raw = (ROOT / "tests/fixtures/qa_prs/korp.compras.core.json").read_text()
        report = filters.load_report(
            raw,
            "compras",
            123,
            "prs/compras/123/korp.compras.core.json",
        )
        self.assertEqual(report["desired_image"], "korp/korp.compras.core:2025.1.0.42-pr123")

    def test_rejects_kind_not_implemented_in_phase_one(self):
        raw = json.dumps({
            "kind": "delphi",
            "pr": 123,
            "repositorio": "compras",
            "branch": "DEVO-6789-delphi",
            "servico": "KorpCadastrosService",
            "imagem": "korp/KorpCadastrosService",
            "tag": "2025.1.0.42-pr123",
            "versao": "2025.1.0",
            "commit": "abc1234",
            "build": 42,
        })
        with self.assertRaises(ValueError):
            filters.load_report(raw, "compras", 123, "prs/compras/123/KorpCadastrosService.json")
~~~

Create listing.xml with the literal fixture:

~~~xml
<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">
  <IsTruncated>false</IsTruncated>
  <Contents><Key>prs/compras/123/korp.compras.core.json</Key></Contents>
  <Contents><Key>prs/compras/999/outro.json</Key></Contents>
</ListBucketResult>
~~~

Create korp.compras.core.json with:

~~~json
{
  "kind": "container",
  "pr": 123,
  "repositorio": "compras",
  "branch": "DEVO-6789-ajuste",
  "servico": "korp.compras.core",
  "imagem": "korp/korp.compras.core",
  "tag": "2025.1.0.42-pr123",
  "versao": "2025.1.0",
  "commit": "abc1234",
  "build": 42
}
~~~

- [ ] **Step 2: Run tests to verify RED**

Run:

~~~bash
python3 -m unittest tests.unit.test_qa_pr_filters -v
~~~

Expected: ERROR because roles/qa_pr_apply/filter_plugins/qa_pr_filters.py does not exist.

- [ ] **Step 3: Implement minimal parsing filters**

Create qa_pr_filters.py with:

~~~python
import json
import re
from xml.etree import ElementTree

_PR_LINK = re.compile(
    r"^https://github[.]com/(?P<org>[A-Za-z0-9_.-]+)/"
    r"(?P<repo>[A-Za-z0-9_.-]+)/pull/(?P<pr>[1-9][0-9]*)/?$"
)
_REQUIRED_CONTAINER_FIELDS = {
    "kind", "pr", "repositorio", "branch", "servico",
    "imagem", "tag", "versao", "commit", "build",
}


def normalize_pr_links(value, organization="viasoftkorp"):
    items = value.split(",") if isinstance(value, str) else list(value or [])
    result = []
    for raw in items:
        url = str(raw).strip()
        match = _PR_LINK.fullmatch(url)
        if not match or match.group("org") != organization:
            raise ValueError(f"Link de PR inválido: {url!r}")
        repo = match.group("repo")
        pr = int(match.group("pr"))
        result.append({"url": url, "repo": repo, "pr": pr, "key": f"{repo}#{pr}"})
    if not result:
        raise ValueError("Informe ao menos um link de PR em prs")
    return result


def parse_minio_listing(xml_text, prefix):
    root = ElementTree.fromstring(xml_text)
    truncated = next((node.text for node in root.iter() if node.tag.endswith("IsTruncated")), "false")
    if str(truncated).lower() == "true":
        raise ValueError(f"Listagem truncada para {prefix}; paginação não implementada")
    keys = [
        node.text for node in root.iter()
        if node.tag.endswith("Key") and node.text
        and node.text.startswith(prefix) and node.text.endswith(".json")
    ]
    return sorted(set(keys))


def load_report(json_text, expected_repo, expected_pr, expected_key):
    report = json.loads(json_text)
    missing = _REQUIRED_CONTAINER_FIELDS - set(report)
    if missing:
        raise ValueError(f"Relatório sem campos obrigatórios: {sorted(missing)}")
    if report["kind"] != "container":
        raise ValueError(f"kind ainda não suportado nesta fase: {report['kind']}")
    expected_service = expected_key.rsplit("/", 1)[-1][:-5]
    if (
        report["repositorio"] != expected_repo
        or report["pr"] != expected_pr
        or report["servico"] != expected_service
        or report["imagem"] != f"korp/{report['servico']}"
    ):
        raise ValueError(f"Relatório inconsistente com {expected_key}")
    report = dict(report)
    report["pr_key"] = f"{expected_repo}#{expected_pr}"
    report["desired_image"] = f"{report['imagem']}:{report['tag']}"
    return report


class FilterModule:
    def filters(self):
        return {
            "qa_pr_normalize_links": normalize_pr_links,
            "qa_pr_parse_minio_listing": parse_minio_listing,
            "qa_pr_load_report": load_report,
        }
~~~

- [ ] **Step 4: Run tests to verify GREEN**

Run the unittest command from Step 2.

Expected: all parsing tests PASS.

- [ ] **Step 5: Commit**

~~~bash
git add roles/qa_pr_apply/filter_plugins/qa_pr_filters.py tests/
git commit -m "DEVO-6789 - Adiciona contrato dos relatorios de PR"
~~~

---

### Task 2: Descoberta de serviços nos composes renderizados

**Files:**
- Modify: roles/qa_pr_apply/filter_plugins/qa_pr_filters.py
- Modify: tests/unit/test_qa_pr_filters.py
- Create: tests/fixtures/qa_prs/base-compose.yml

**Interfaces:**
- Consumes: reports list[dict] da Task 1.
- Consumes: compose_files list[{"path": str, "content": dict}].
- Produces: build_targets(reports, compose_files) -> list[dict].
- Target identity: project_src + compose_file + service_key.

- [ ] **Step 1: Write failing discovery tests**

Add tests that build one root compose and one versioned compose and assert:

~~~python
class BuildTargetsTests(unittest.TestCase):
    def test_finds_service_by_image_and_keeps_yaml_service_key(self):
        reports = [{
            "pr_key": "compras#123",
            "repositorio": "compras",
            "pr": 123,
            "servico": "korp.compras.core",
            "imagem": "korp/korp.compras.core",
            "tag": "2025.1.0.42-pr123",
            "desired_image": "korp/korp.compras.core:2025.1.0.42-pr123",
        }]
        compose_files = [{
            "path": "/etc/korp/composes/compras-compose.yml",
            "content": {
                "services": {
                    "korp-compras-core": {
                        "image": "korp/korp.compras.core:2025.1.0.x"
                    }
                }
            },
        }]
        targets = filters.build_targets(reports, compose_files)
        self.assertEqual(targets[0]["service_key"], "korp-compras-core")
        self.assertEqual(targets[0]["project_src"], "/etc/korp/composes")
        self.assertEqual(
            targets[0]["override_path"],
            "/etc/korp/composes/pr-overrides/pr123/compras-compose.yml",
        )

    def test_rejects_service_not_found_or_duplicated(self):
        report = {
            "pr_key": "compras#123",
            "repositorio": "compras",
            "pr": 123,
            "servico": "korp.compras.core",
            "imagem": "korp/korp.compras.core",
            "tag": "2025.1.0.42-pr123",
            "desired_image": "korp/korp.compras.core:2025.1.0.42-pr123",
        }
        with self.assertRaises(ValueError):
            filters.build_targets([report], [])
        duplicate = [
            {"path": f"/tmp/{name}-compose.yml",
             "content": {"services": {"core": {"image": "korp/korp.compras.core:base"}}}}
            for name in ("a", "b")
        ]
        with self.assertRaises(ValueError):
            filters.build_targets([report], duplicate)
~~~

- [ ] **Step 2: Run tests to verify RED**

Run:

~~~bash
python3 -m unittest tests.unit.test_qa_pr_filters.BuildTargetsTests -v
~~~

Expected: FAIL because build_targets is missing.

- [ ] **Step 3: Implement compose discovery**

Add a function that ignores malformed service entries, compares the repository portion before the image tag, requires exactly one match, and emits:

~~~python
{
    "target_id": "compras#123|/etc/korp/composes|compras-compose.yml|korp-compras-core",
    "identity": "/etc/korp/composes|compras-compose.yml|korp-compras-core",
    "pr_key": "compras#123",
    "repo": "compras",
    "pr": 123,
    "service": "korp.compras.core",
    "service_key": "korp-compras-core",
    "desired_image": "korp/korp.compras.core:2025.1.0.42-pr123",
    "project_src": "/etc/korp/composes",
    "compose_file": "compras-compose.yml",
    "override_path": "/etc/korp/composes/pr-overrides/pr123/compras-compose.yml",
}
~~~

Use pathlib.PurePosixPath for dirname/basename calculations. The implementation body is:

~~~python
from pathlib import PurePosixPath


def build_targets(reports, compose_files):
    targets = []
    for report in reports:
        matches = []
        for compose in compose_files:
            services = (compose.get("content") or {}).get("services") or {}
            for service_key, config in services.items():
                image = config.get("image") if isinstance(config, dict) else None
                if isinstance(image, str) and image.rsplit(":", 1)[0] == report["imagem"]:
                    matches.append((compose["path"], service_key))
        if len(matches) != 1:
            raise ValueError(
                f"Esperado um compose para {report['imagem']}; encontrados {len(matches)}"
            )
        compose_path, service_key = matches[0]
        compose = PurePosixPath(compose_path)
        project_src = str(compose.parent)
        identity = f"{project_src}|{compose.name}|{service_key}"
        target_id = f"{report['pr_key']}|{identity}"
        targets.append({
            "target_id": target_id,
            "identity": identity,
            "pr_key": report["pr_key"],
            "repo": report["repositorio"],
            "pr": report["pr"],
            "service": report["servico"],
            "service_key": service_key,
            "desired_image": report["desired_image"],
            "project_src": project_src,
            "compose_file": compose.name,
            "override_path": (
                f"{project_src}/pr-overrides/pr{report['pr']}/{compose.name}"
            ),
        })
    return targets
~~~

Register qa_pr_build_targets in FilterModule.

- [ ] **Step 4: Run all unit tests**

Run:

~~~bash
python3 -m unittest discover -s tests/unit -v
~~~

Expected: PASS.

- [ ] **Step 5: Commit**

~~~bash
git add roles/qa_pr_apply/filter_plugins/qa_pr_filters.py tests/
git commit -m "DEVO-6789 - Localiza servicos de PR nos composes"
~~~

---

### Task 3: Preflight e plano híbrido de conflitos

**Files:**
- Modify: roles/qa_pr_apply/filter_plugins/qa_pr_filters.py
- Modify: tests/unit/test_qa_pr_filters.py
- Create: tests/fixtures/qa_prs/existing-override.yml

**Interfaces:**
- Consumes: targets da Task 2.
- Consumes: override_files list[{"path": str, "content": dict}].
- Produces: index_active_overrides(override_files) -> dict por identity.
- Produces: detect_conflicts(targets, active_owners) -> list[dict].
- Produces: resolve_application(targets, active_owners, policy, decisions={}) -> execution plan.
- Execution plan keys: apply_targets, skipped_targets, remove_services, writes, deletes e compose_runs.

- [ ] **Step 1: Write failing conflict tests**

Add focused tests for:

~~~python
class ConflictPlanningTests(unittest.TestCase):
    def setUp(self):
        self.current = target(pr_key="logistica#579", pr=579, service_key="wms-core")
        self.incoming = target(pr_key="logistica#580", pr=580, service_key="wms-core")
        self.other_service = target(
            pr_key="logistica#580", pr=580, service_key="wms-gateway"
        )
        self.active = {
            self.current["identity"]: {
                "pr_key": "#579",
                "pr": 579,
                "override_path": self.current["override_path"],
                "service_key": "wms-core",
            }
        }

    def test_different_service_in_same_compose_is_not_a_conflict(self):
        plan = filters.resolve_application(
            [self.other_service], self.active, policy="fail"
        )
        self.assertEqual(plan["conflicts"], [])
        self.assertEqual(plan["apply_targets"], [self.other_service])

    def test_reapplying_same_pr_is_not_a_conflict(self):
        plan = filters.resolve_application(
            [self.current], self.active, policy="fail"
        )
        self.assertEqual(plan["conflicts"], [])

    def test_fail_and_abort_produce_no_mutations(self):
        for policy, decisions in (
            ("fail", {}),
            ("ask", {self.incoming["target_id"]: "abort"}),
        ):
            plan = filters.resolve_application(
                [self.incoming], self.active, policy=policy, decisions=decisions
            )
            self.assertFalse(plan["may_mutate"])
            self.assertEqual(plan["writes"], [])
            self.assertEqual(plan["deletes"], [])

    def test_keep_skips_only_conflicting_target(self):
        plan = filters.resolve_application(
            [self.incoming, self.other_service], self.active, policy="keep"
        )
        self.assertEqual(plan["skipped_targets"], [self.incoming])
        self.assertEqual(plan["apply_targets"], [self.other_service])

    def test_replace_removes_old_owner_and_applies_new_target(self):
        plan = filters.resolve_application(
            [self.incoming], self.active, policy="replace"
        )
        self.assertEqual(
            plan["remove_services"],
            [{
                "path": self.current["override_path"],
                "service_key": "wms-core",
            }],
        )
        self.assertEqual(plan["apply_targets"], [self.incoming])
~~~

The target helper must construct deterministic identity, target_id, project_src, compose_file and override_path values.

- [ ] **Step 2: Run tests to verify RED**

Run the ConflictPlanningTests class.

Expected: FAIL because conflict functions are missing.

- [ ] **Step 3: Implement deterministic preflight**

Implement these rules in pure Python:

1. Validate policy against ask, replace, keep and fail.
2. Group existing owners and incoming targets by identity.
3. Same numeric pr is a refresh, not a conflict; active overrides only persist korp.pr=<N>, so the existing owner is displayed as #<N>.
4. Different pr_key is a conflict containing current and incoming.
5. For ask, require one decision per target_id; missing/invalid input becomes abort.
6. If any decision is abort, or policy is fail with conflicts, return may_mutate=False and no writes/deletes/compose_runs.
7. keep removes only the incoming conflict from apply_targets.
8. replace records removal from the current override and accepts the incoming target.
9. Group accepted targets by override_path and compose run identity.
10. compose_runs contains project_src, files=[compose_file, relative override path] and the unique service keys in services.
11. Build writes by removing replaced service keys from old override dictionaries and merging accepted targets.
12. Delete an old override file if its services dictionary becomes empty.

Implement the public functions with this control flow:

~~~python
def detect_conflicts(targets, active_owners):
    conflicts = []
    owners = dict(active_owners)
    for target in targets:
        current = owners.get(target["identity"])
        if current and current["pr"] != target["pr"]:
            conflicts.append({
                "target_id": target["target_id"],
                "identity": target["identity"],
                "current": current,
                "incoming": target,
            })
        owners[target["identity"]] = target
    return conflicts


def resolve_application(targets, active_owners, policy, decisions=None):
    if policy not in {"ask", "replace", "keep", "fail"}:
        raise ValueError(f"Política de conflito inválida: {policy}")
    decisions = decisions or {}
    conflicts = detect_conflicts(targets, active_owners)
    if policy == "fail" and conflicts:
        return empty_plan(conflicts)
    accepted, skipped, removals = [], [], []
    conflict_by_target = {item["target_id"]: item for item in conflicts}
    for target in targets:
        conflict = conflict_by_target.get(target["target_id"])
        if not conflict:
            accepted.append(target)
            continue
        decision = policy if policy != "ask" else decisions.get(target["target_id"], "abort")
        if decision == "abort":
            return empty_plan(conflicts)
        if decision == "keep":
            skipped.append(target)
            continue
        if decision != "replace":
            return empty_plan(conflicts)
        removals.append({
            "path": conflict["current"]["override_path"],
            "service_key": target["service_key"],
        })
        accepted.append(target)
    return build_mutation_plan(accepted, skipped, removals, conflicts, active_owners)
~~~

empty_plan always returns may_mutate false and empty mutation lists. build_mutation_plan performs rules 9–12 above without filesystem access, using deep copies of the supplied override content. Register qa_pr_index_active_overrides, qa_pr_detect_conflicts and qa_pr_resolve_application in FilterModule.

- [ ] **Step 4: Add mutation-shape tests**

Assert that replace of the only service deletes the old file; replace when the old file has another service rewrites it; multiple accepted services for the same PR/AppId produce one write and one compose run with two service keys.

- [ ] **Step 5: Run all unit tests**

Run unittest discovery.

Expected: PASS with parsing, discovery and conflict cases.

- [ ] **Step 6: Commit**

~~~bash
git add roles/qa_pr_apply/filter_plugins/qa_pr_filters.py tests/
git commit -m "DEVO-6789 - Planeja conflitos de PR sem mutacao parcial"
~~~

---

### Task 4: Role de aplicação de PRs

**Files:**
- Create: roles/qa_pr_apply/defaults/main.yml
- Create: roles/qa_pr_apply/tasks/main.yml
- Create: roles/qa_pr_apply/tasks/load_pr.yml
- Create: roles/qa_pr_apply/tasks/load_report.yml
- Create: roles/qa_pr_apply/tasks/read_compose.yml
- Create: roles/qa_pr_apply/tasks/read_override.yml
- Create: roles/qa_pr_apply/tasks/prompt_conflict.yml
- Create: roles/qa_pr_apply/tasks/write_override.yml
- Create: roles/qa_pr_apply/tasks/apply_compose.yml
- Create: tests/unit/test_qa_pr_role_yaml.py

**Interfaces:**
- Input: prs string CSV ou lista.
- Input: pr_conflict_policy default ask.
- Uses: compose_dir_path, versioned_compose_dir_path e docker_env_file_path de group_vars/all.
- Output on disk: project_src/pr-overrides/pr<N>/<AppId>-compose.yml.
- Side effect: docker_compose_v2 base + override limitado a services.

- [ ] **Step 1: Write failing role structure tests**

Use PyYAML to load every task/default file and assert:

- defaults define qa_pr_minio_api, qa_pr_minio_bucket and pr_conflict_policy.
- main.yml uses qa_pr_normalize_links before any uri/file/copy/docker task.
- MinIO tasks use ansible.builtin.uri with return_content true and validate_certs true.
- Compose task has project_src, env_files, files, services and never sets remove_orphans true.
- Prompt task uses ansible.builtin.pause and defaults missing user_input to abort.
- No task references mc, aws, boto3 or setup.sh.

Run:

~~~bash
python3 -m unittest tests.unit.test_qa_pr_role_yaml -v
~~~

Expected: FAIL because role YAML files do not exist.

- [ ] **Step 2: Add defaults and input preflight**

Create defaults/main.yml:

~~~yaml
---
qa_pr_minio_api: "https://minio-interno-api.korp.com.br"
qa_pr_minio_bucket: "qa-prs"
qa_pr_github_organization: "viasoftkorp"
pr_conflict_policy: "ask"
qa_pr_reports: []
qa_pr_compose_files: []
qa_pr_override_files: []
qa_pr_conflict_decisions: {}
~~~

Start main.yml with set_fact using qa_pr_normalize_links and an assert that the policy is one of ask, replace, keep, fail.

- [ ] **Step 3: Read MinIO reports without credentials**

For each normalized PR, load_pr.yml must:

- GET /qa-prs/?list-type=2&prefix=prs/<repo>/<N>/ with return_content true and validate_certs true.
- Parse XML with qa_pr_parse_minio_listing.
- Fail clearly when no JSON key exists.
- Include load_report.yml for every key.
- GET each object using its exact key.
- Parse/validate with qa_pr_load_report.
- Append to qa_pr_reports.

Run the YAML structure tests and confirm GREEN for MinIO assertions.

- [ ] **Step 4: Discover base composes and existing overrides**

Use ansible.builtin.find with recurse=false and patterns ["*-compose.yml"] for base files in compose_dir_path and versioned_compose_dir_path. Read each with slurp + b64decode + from_yaml.

Search override roots with recurse=true only under each project_src/pr-overrides, read them separately, and pass both collections to the filters. Never include an override in the base compose collection.

- [ ] **Step 5: Resolve all conflicts before mutations**

main.yml must:

1. Build targets and active owners.
2. Detect conflicts.
3. For ask, include prompt_conflict.yml once per conflict and store replace, keep or abort by target_id.
4. Build the final execution plan.
5. Fail with the conflict summary when may_mutate is false.
6. Only after that task, execute deletes, writes and Compose runs.

prompt_conflict.yml must show current pr_key, incoming pr_key, service and compose. Normalize user_input with lower/trim and treat anything outside replace/keep as abort.

- [ ] **Step 6: Write overrides and apply targeted services**

write_override.yml must create the parent directory mode 0755 and copy:

~~~yaml
services:
  <service_key>:
    image: "<desired_image>"
    labels:
      korp.pr: "<N>"
~~~

The copy content comes from the pure execution plan and to_nice_yaml. apply_compose.yml must call:

~~~yaml
community.docker.docker_compose_v2:
  project_src: "{{ qa_pr_compose_run.project_src }}/"
  env_files:
    - "{{ docker_env_file_path }}"
  files: "{{ qa_pr_compose_run.files }}"
  services: "{{ qa_pr_compose_run.services }}"
~~~

Do not set project_name, remove_orphans, pull or recreate.

- [ ] **Step 7: Run role tests and syntax check**

Run:

~~~bash
python3 -m unittest discover -s tests/unit -v
ansible-playbook --syntax-check pr-playbook.yml
~~~

Expected: unit tests PASS. The syntax command is expected to become available in Task 6 setup; if absent now, record only that environment limitation and run it in Task 6.

- [ ] **Step 8: Commit**

~~~bash
git add roles/qa_pr_apply tests/unit/test_qa_pr_role_yaml.py
git commit -m "DEVO-6789 - Implementa aplicacao incremental de PRs"
~~~

---

### Task 5: Role de reset

**Files:**
- Create: roles/qa_pr_reset/tasks/main.yml
- Create: roles/qa_pr_reset/tasks/read_override.yml
- Create: roles/qa_pr_reset/tasks/reset_compose.yml
- Create: tests/unit/test_qa_pr_reset_role_yaml.py

**Interfaces:**
- Consumes: compose_dir_path, versioned_compose_dir_path e docker_env_file_path.
- Discovers: override files before deleting pr-overrides.
- Produces: unique reset runs by project_src + compose_file.
- Side effect: deletes override roots and reapplies only each base compose.

- [ ] **Step 1: Write failing reset role tests**

Assert the task ordering:

1. find/read overrides;
2. derive affected base composes;
3. remove pr-overrides;
4. run docker_compose_v2 with only the base file;
5. remove_orphans is absent or false.

Also assert an empty environment is a successful no-op.

- [ ] **Step 2: Run tests to verify RED**

Run the reset test module.

Expected: FAIL because roles/qa_pr_reset does not exist.

- [ ] **Step 3: Implement reset discovery and deletion**

Read every override before deletion and derive unique:

~~~python
{
    "project_src": "/etc/korp/composes/2025.1.0",
    "compose_file": "LOG102-compose.yml",
}
~~~

Validate that the base file exists. Then remove compose_dir_path/pr-overrides and versioned_compose_dir_path/pr-overrides with ansible.builtin.file state=absent.

- [ ] **Step 4: Reapply baseline**

For each affected compose run:

~~~yaml
community.docker.docker_compose_v2:
  project_src: "{{ qa_pr_reset_run.project_src }}/"
  env_files:
    - "{{ docker_env_file_path }}"
  files:
    - "{{ qa_pr_reset_run.compose_file }}"
~~~

Reset intentionally targets the full base compose because every PR override is being removed.

- [ ] **Step 5: Run reset and full unit tests**

Run unittest discovery.

Expected: PASS.

- [ ] **Step 6: Commit**

~~~bash
git add roles/qa_pr_reset tests/unit/test_qa_pr_reset_role_yaml.py
git commit -m "DEVO-6789 - Implementa reset do ambiente de PRs"
~~~

---

### Task 6: Playbooks operacionais e verificação integrada

**Files:**
- Create: pr-playbook.yml
- Create: pr-reset-playbook.yml
- Create: docs/ambiente-qualidade-prs.md
- Modify: readme.md
- Test: all tests under tests/unit

**Interfaces:**
- Operator apply command: ansible-playbook pr-playbook.yml -e "prs=<links>".
- Automation conflict command: add -e "pr_conflict_policy=replace|keep|fail".
- Operator reset command: ansible-playbook pr-reset-playbook.yml.
- Neither playbook is imported by setup.sh or main.yml.

- [ ] **Step 1: Write failing playbook contract tests**

Extend YAML tests to assert both playbooks:

- hosts 127.0.0.1 with connection local;
- become true and same linux_korp user convention as auxiliary playbooks;
- apply imports only qa_pr_apply;
- reset imports only qa_pr_reset;
- neither imports main.yml nor changes setup.sh.

- [ ] **Step 2: Run tests to verify RED**

Run unittest discovery.

Expected: FAIL because playbooks are missing.

- [ ] **Step 3: Create operational playbooks**

Use the existing auxiliary playbook shape:

~~~yaml
---
- name: Aplicação de PRs no ambiente de qualidade
  hosts: 127.0.0.1
  connection: local
  vars:
    ansible_become_password: "{{ linux_korp.password }}"
  become_user: "{{ linux_korp.user }}"
  become: true
  roles:
    - qa_pr_apply
~~~

Create pr-reset-playbook.yml with the full counterpart:

~~~yaml
---
- name: Reset do ambiente de qualidade
  hosts: 127.0.0.1
  connection: local
  vars:
    ansible_become_password: "{{ linux_korp.password }}"
  become_user: "{{ linux_korp.user }}"
  become: true
  roles:
    - qa_pr_reset
~~~

- [ ] **Step 4: Document operator flows**

Document:

- CSV and JSON-list input examples;
- ask/replace/keep/fail;
- meaning of conflict and non-conflict;
- no mutation on abort/fail;
- Portainer label korp.pr;
- reapply after a new push;
- reset behavior;
- MinIO API host warning;
- accepted MVP risks: version mismatch, client execution, dirty schema and no automatic refresh.

Add a short link from readme.md without changing setup instructions.

- [ ] **Step 5: Provision temporary validation tooling**

Because the development checkout currently lacks Ansible, create an isolated temporary venv outside the repository and install:

~~~bash
python3 -m venv /tmp/devo-6789-ansible
/tmp/devo-6789-ansible/bin/pip install "ansible-core>=2.16,<2.20" ansible-lint
/tmp/devo-6789-ansible/bin/ansible-galaxy collection install "community.docker:>=3.10.3" -p /tmp/devo-6789-collections
~~~

This needs network approval at execution time and must not modify setup.sh or add dependency files to the repository.

- [ ] **Step 6: Run full verification**

Run:

~~~bash
python3 -m unittest discover -s tests/unit -v
ANSIBLE_COLLECTIONS_PATH=/tmp/devo-6789-collections \
  /tmp/devo-6789-ansible/bin/ansible-playbook --syntax-check pr-playbook.yml
ANSIBLE_COLLECTIONS_PATH=/tmp/devo-6789-collections \
  /tmp/devo-6789-ansible/bin/ansible-playbook --syntax-check pr-reset-playbook.yml
/tmp/devo-6789-ansible/bin/ansible-lint roles/qa_pr_apply roles/qa_pr_reset pr-playbook.yml pr-reset-playbook.yml
git diff --check
~~~

Expected: every command exits 0.

- [ ] **Step 7: Verify spec coverage**

Map final evidence:

- report parsing: Task 1 tests;
- compose discovery: Task 2 tests;
- incremental and conflicts: Task 3 tests;
- apply orchestration: Task 4 YAML and syntax tests;
- reset: Task 5 tests;
- operator interface: Task 6 playbook/docs tests.

Confirm no Delphi code, no setup.sh change and no unrelated files.

- [ ] **Step 8: Commit**

~~~bash
git add pr-playbook.yml pr-reset-playbook.yml docs/ambiente-qualidade-prs.md readme.md tests/
git commit -m "DEVO-6789 - Adiciona operacao do ambiente de PRs"
~~~
