from copy import deepcopy
import json
import re
from pathlib import PurePosixPath
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


def index_active_overrides(override_files):
    owners = {}
    marker = "/pr-overrides/"
    for override_file in override_files:
        override_path = str(PurePosixPath(override_file["path"]))
        if marker not in override_path:
            raise ValueError(f"Override fora de pr-overrides: {override_path}")
        project_src, relative_path = override_path.split(marker, 1)
        compose_file = PurePosixPath(relative_path).name
        content = override_file.get("content") or {}
        services = content.get("services") or {}
        for service_key, config in services.items():
            labels = config.get("labels") if isinstance(config, dict) else {}
            raw_pr = (labels or {}).get("korp.pr")
            if raw_pr is None:
                continue
            try:
                pr = int(raw_pr)
            except (TypeError, ValueError) as error:
                raise ValueError(
                    f"Label korp.pr inválida em {override_path}: {raw_pr!r}"
                ) from error
            identity = f"{project_src}|{compose_file}|{service_key}"
            if identity in owners:
                raise ValueError(f"Mais de um override ativo para {identity}")

            owners[identity] = {
                "identity": identity,
                "pr_key": f"#{pr}",
                "pr": pr,
                "override_path": override_path,
                "override_content": deepcopy(content),
                "project_src": project_src,
                "compose_file": compose_file,
                "service_key": service_key,
            }
    return owners


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
            "labels": {"korp.pr": str(target["pr"])},
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
        conflict = state and state["owner"]["pr"] != target["pr"]
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
            "qa_pr_build_targets": build_targets,
            "qa_pr_index_active_overrides": index_active_overrides,
            "qa_pr_detect_conflicts": detect_conflicts,
            "qa_pr_resolve_application": resolve_application,
        }
