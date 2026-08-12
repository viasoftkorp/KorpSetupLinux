from copy import deepcopy
import json
import re
from pathlib import PurePosixPath
from xml.etree import ElementTree

_PR_LINK = re.compile(
    r"^https://github[.]com/(?P<org>[A-Za-z0-9_.-]+)/"
    r"(?P<repo>[A-Za-z0-9_.-]+)/pull/(?P<pr>[1-9][0-9]*)/?$"
)
_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+$")
_VERSION = re.compile(r"^[0-9]+[.][0-9]+[.][0-9]+$")
_OVERRIDE_PATH = re.compile(
    r"^.+/pr-overrides/pr(?P<pr>[1-9][0-9]*)/"
    r"(?P<compose_file>[^/]+-compose[.]yml)$"
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
    keys = []
    for node in root.iter():
        key = node.text
        if not node.tag.endswith("Key") or not key or not key.startswith(prefix):
            continue
        suffix = key[len(prefix):]
        if suffix and "/" not in suffix and suffix.endswith(".json"):
            keys.append(key)
    return sorted(set(keys))


def load_report(
    json_text,
    expected_repo,
    expected_pr,
    expected_key,
    harbor_registry="harbor.korp.com.br",
    harbor_project="qa-prs",
):
    report = json.loads(json_text)
    missing = _REQUIRED_CONTAINER_FIELDS - set(report)
    if missing:
        raise ValueError(f"Relatório sem campos obrigatórios: {sorted(missing)}")
    if report["kind"] != "container":
        raise ValueError(f"kind ainda não suportado nesta fase: {report['kind']}")
    expected_service = expected_key.rsplit("/", 1)[-1][:-5]
    registry = str(harbor_registry).strip().strip("/")
    project = str(harbor_project).strip().strip("/")
    dockerhub_image = f"korp/{report['servico']}"
    harbor_image = f"{registry}/{project}/{report['servico']}"
    if (
        report["repositorio"] != expected_repo
        or report["pr"] != expected_pr
        or report["servico"] != expected_service
        or report["imagem"] not in {dockerhub_image, harbor_image}
    ):
        raise ValueError(f"Relatório inconsistente com {expected_key}")
    report = dict(report)
    report["pr_key"] = f"{expected_repo}#{expected_pr}"
    report["compose_image"] = dockerhub_image
    report["desired_image"] = f"{report['imagem']}:{report['tag']}"
    return report


def resolve_registry_image(
    report,
    harbor_status,
    harbor_registry="harbor.korp.com.br",
    harbor_project="qa-prs",
):
    if harbor_status not in {200, 404}:
        raise ValueError(
            f"Status inesperado ao consultar artefato no Harbor: {harbor_status}"
        )
    registry = str(harbor_registry).strip().strip("/")
    project = str(harbor_project).strip().strip("/")
    if not registry or not project:
        raise ValueError("Registry e projeto do Harbor são obrigatórios")
    harbor_image = f"{registry}/{project}/{report['servico']}"
    dockerhub_image = f"korp/{report['servico']}"
    resolved = dict(report)
    if harbor_status == 200:
        resolved["desired_image"] = (
            f"{harbor_image}:{report['tag']}"
        )
        resolved["image_registry"] = "harbor"
    else:
        if report["imagem"] != dockerhub_image:
            raise ValueError(
                "Relatório declara Harbor, mas o artefato não foi encontrado: "
                f"{harbor_image}:{report['tag']}"
            )
        resolved["desired_image"] = f"{dockerhub_image}:{report['tag']}"
        resolved["image_registry"] = "dockerhub"
    return resolved


def select_report_version(reports):
    if not reports:
        raise ValueError("Nenhum relatório disponível para selecionar a versão")
    versions = set()
    for report in reports:
        version = str(report.get("versao", "")).strip()
        if not _VERSION.fullmatch(version):
            raise ValueError(f"Versão inválida no relatório: {version!r}")
        versions.add(version)
    if len(versions) != 1:
        raise ValueError(
            "Os relatórios apontam para versões diferentes: "
            f"{sorted(versions)}. Execute os PRs separadamente."
        )
    return next(iter(versions))


def build_targets(reports, compose_files):
    targets = []
    for report in reports:
        matches = []
        compose_image = report.get("compose_image", report["imagem"])
        for compose in compose_files:
            services = (compose.get("content") or {}).get("services") or {}
            for service_key, config in services.items():
                image = config.get("image") if isinstance(config, dict) else None
                if isinstance(image, str) and image.rsplit(":", 1)[0] == compose_image:
                    matches.append((compose["path"], service_key))
        if len(matches) != 1:
            raise ValueError(
                f"Esperado um compose para {compose_image}; encontrados {len(matches)}"
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


def index_active_overrides(override_files):
    owners = {}
    for override_file in override_files:
        override_path = str(override_file["path"])
        project_src = override_file.get("project_src")
        if not isinstance(project_src, str) or not project_src:
            raise ValueError(f"Project src inválido em {override_path}")
        match = _OVERRIDE_PATH.fullmatch(override_path)
        if not match:
            raise ValueError(f"Caminho de override inválido: {override_path}")
        compose_file = match.group("compose_file")
        path_pr = int(match.group("pr"))
        expected_path = (
            f"{project_src}/pr-overrides/pr{path_pr}/{compose_file}"
        )
        if override_path != expected_path:
            raise ValueError(f"Caminho de override inválido: {override_path}")
        content = override_file.get("content")
        if not isinstance(content, dict):
            raise ValueError(f"Override YAML inválido em {override_path}")
        services = content.get("services")
        if not isinstance(services, dict) or not services:
            raise ValueError(f"Override sem services em {override_path}")
        for service_key, config in services.items():
            if not isinstance(config, dict):
                raise ValueError(
                    f"Serviço inválido em {override_path}: {service_key}"
                )
            if not isinstance(config.get("image"), str) or not config["image"]:
                raise ValueError(
                    f"Imagem inválida em {override_path}: {service_key}"
                )
            if not isinstance(config.get("labels"), dict):
                raise ValueError(
                    f"Labels inválidas em {override_path}: {service_key}"
                )
            labels = config["labels"]
            raw_pr = labels.get("korp.pr")
            try:
                pr = int(raw_pr)
            except (TypeError, ValueError) as error:
                raise ValueError(
                    f"Label korp.pr inválida em {override_path}: {raw_pr!r}"
                ) from error
            if pr <= 0:
                raise ValueError(
                    f"Label korp.pr inválida em {override_path}: {raw_pr!r}"
                )
            if pr != path_pr:
                raise ValueError(
                    f"PR do caminho diverge da label em {override_path}"
                )
            raw_repo = labels.get("korp.repositorio")
            if raw_repo is None:
                pr_key = f"#{pr}"
            elif not isinstance(raw_repo, str) or not _REPOSITORY.fullmatch(raw_repo):
                raise ValueError(
                    f"Label korp.repositorio inválida em {override_path}: {raw_repo!r}"
                )
            else:
                pr_key = f"{raw_repo}#{pr}"
            identity = f"{project_src}|{compose_file}|{service_key}"
            if identity in owners:
                raise ValueError(f"Mais de um override ativo para {identity}")

            owners[identity] = {
                "identity": identity,
                "pr_key": pr_key,
                "pr": pr,
                "override_path": override_path,
                "override_content": deepcopy(content),
                "project_src": project_src,
                "compose_file": compose_file,
                "service_key": service_key,
            }
    return owners


def detect_conflicts(targets, active_owners, decisions=None):
    conflicts = []
    owners = dict(active_owners)
    interactive = decisions is not None
    decisions = decisions or {}
    for target in targets:
        current = owners.get(target["identity"])
        if current and current["pr_key"] != target["pr_key"]:
            conflicts.append({
                "target_id": target["target_id"],
                "identity": target["identity"],
                "current": current,
                "incoming": target,
            })
            if interactive:
                if target["target_id"] not in decisions:
                    break
                decision = decisions[target["target_id"]]
                if decision == "replace":
                    owners[target["identity"]] = target
                elif decision != "keep":
                    break
            continue
        owners[target["identity"]] = target
    return conflicts


def _empty_plan(conflicts):
    return {
        "may_mutate": False,
        "conflicts": conflicts,
        "apply_targets": [],
        "skipped_targets": [],
        "remove_services": [],
        "writes": [],
        "deletes": [],
        "compose_runs": [],
    }


def _build_mutation_plan(
    accepted, skipped, removals, conflicts, active_owners
):
    contents_by_path = {}
    for owner in active_owners.values():
        path = owner.get("override_path")
        if path and "override_content" in owner and path not in contents_by_path:
            contents_by_path[path] = deepcopy(owner["override_content"])

    modified_paths = {}
    for removal in removals:
        path = removal["path"]
        content = contents_by_path.setdefault(path, {"services": {}})
        services = content.setdefault("services", {})
        services.pop(removal["service_key"], None)
        modified_paths[path] = None

    compose_runs_by_key = {}
    for target in accepted:
        path = target["override_path"]
        content = contents_by_path.setdefault(path, {"services": {}})
        services = content.setdefault("services", {})
        services[target["service_key"]] = {
            "image": target["desired_image"],
            "labels": {
                "korp.pr": str(target["pr"]),
                "korp.repositorio": target["repo"],
            },
        }
        modified_paths[path] = None

        run_key = (
            target["project_src"],
            target["compose_file"],
            target["override_path"],
        )
        run = compose_runs_by_key.setdefault(run_key, {
            "project_src": target["project_src"],
            "files": [
                target["compose_file"],
                str(
                    PurePosixPath(target["override_path"]).relative_to(
                        PurePosixPath(target["project_src"])
                    )
                ),
            ],
            "services": [],
        })
        if target["service_key"] not in run["services"]:
            run["services"].append(target["service_key"])

    writes, deletes = [], []
    for path in modified_paths:
        content = contents_by_path[path]
        if content.get("services"):
            writes.append({"path": path, "content": content})
        else:
            deletes.append(path)

    return {
        "may_mutate": True,
        "conflicts": conflicts,
        "apply_targets": accepted,
        "skipped_targets": skipped,
        "remove_services": removals,
        "writes": writes,
        "deletes": deletes,
        "compose_runs": list(compose_runs_by_key.values()),
    }


def resolve_application(targets, active_owners, policy, decisions=None):
    if policy not in {"ask", "replace", "keep", "fail"}:
        raise ValueError(f"Política de conflito inválida: {policy}")
    decisions = decisions or {}
    if policy == "ask":
        conflicts = detect_conflicts(targets, active_owners, decisions)
    elif policy in {"replace", "keep"}:
        policy_decisions = {
            target["target_id"]: policy for target in targets
        }
        conflicts = detect_conflicts(
            targets, active_owners, policy_decisions
        )
    else:
        conflicts = detect_conflicts(targets, active_owners)
    if policy == "fail" and conflicts:
        return _empty_plan(conflicts)
    accepted_by_identity, skipped, removals = {}, [], []
    owners = {
        identity: {
            "owner": owner,
            "persisted": True,
            "persisted_owner": owner,
        }
        for identity, owner in active_owners.items()
    }
    for target in targets:
        state = owners.get(target["identity"])
        conflict = state and state["owner"]["pr_key"] != target["pr_key"]
        if not conflict:
            persisted_owner = state.get("persisted_owner") if state else None
            accepted_by_identity[target["identity"]] = target
            owners[target["identity"]] = {
                "owner": target,
                "persisted": False,
                "persisted_owner": persisted_owner,
            }
            continue
        decision = policy if policy != "ask" else decisions.get(
            target["target_id"], "abort"
        )
        if decision == "abort":
            return _empty_plan(conflicts)
        if decision == "keep":
            skipped.append(target)
            continue
        if decision != "replace":
            return _empty_plan(conflicts)
        persisted_owner = state.get("persisted_owner")
        accepted_by_identity.pop(target["identity"], None)
        if persisted_owner:
            removals.append({
                "path": persisted_owner["override_path"],
                "service_key": persisted_owner["service_key"],
            })
        accepted_by_identity[target["identity"]] = target
        owners[target["identity"]] = {
            "owner": target,
            "persisted": False,
            "persisted_owner": None,
        }
    return _build_mutation_plan(
        list(accepted_by_identity.values()),
        skipped,
        removals,
        conflicts,
        active_owners,
    )


class FilterModule:
    def filters(self):
        return {
            "qa_pr_normalize_links": normalize_pr_links,
            "qa_pr_parse_minio_listing": parse_minio_listing,
            "qa_pr_load_report": load_report,
            "qa_pr_resolve_registry_image": resolve_registry_image,
            "qa_pr_select_report_version": select_report_version,
            "qa_pr_build_targets": build_targets,
            "qa_pr_index_active_overrides": index_active_overrides,
            "qa_pr_detect_conflicts": detect_conflicts,
            "qa_pr_resolve_application": resolve_application,
        }
