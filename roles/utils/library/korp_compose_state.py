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
