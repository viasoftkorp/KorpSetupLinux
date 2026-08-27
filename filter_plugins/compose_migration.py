"""Filtros usados pela reconciliação de containers Docker Compose."""

import re


_ANONYMOUS_VOLUME_NAME = re.compile(r"^[0-9a-f]{64}$")


def docker_image_repository(image):
    """Remove tag ou digest sem confundir a porta de um registry."""
    value = str(image or "")
    if "@sha256:" in value:
        return value.split("@sha256:", 1)[0]

    last_slash = value.rfind("/")
    last_colon = value.rfind(":")
    if last_colon > last_slash:
        return value[:last_colon]
    return value


def legacy_container_name(container_name, version):
    """Retorna o nome sem o sufixo exato da versão, quando existir."""
    name = str(container_name or "")
    suffix = f"-{version}"
    if version and name.endswith(suffix):
        return name[: -len(suffix)]
    return name


def has_anonymous_volume(mounts):
    """Identifica volumes anônimos que não podem ser migrados automaticamente."""
    for mount in mounts or []:
        if (
            mount.get("Type") == "volume"
            and _ANONYMOUS_VOLUME_NAME.fullmatch(str(mount.get("Name", "")))
        ):
            return True
    return False


def partial_compose_container_names(container_names, target_name):
    """Seleciona nomes temporários exatos criados pelo Docker Compose."""
    target = str(target_name or "")
    if not target:
        return []

    pattern = re.compile(rf"^[0-9a-f]{{12}}_{re.escape(target)}$")
    return [
        str(container_name)
        for container_name in container_names or []
        if pattern.fullmatch(str(container_name))
    ]


class FilterModule:
    def filters(self):
        return {
            "docker_image_repository": docker_image_repository,
            "legacy_container_name": legacy_container_name,
            "has_anonymous_volume": has_anonymous_volume,
            "partial_compose_container_names": partial_compose_container_names,
        }
