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
