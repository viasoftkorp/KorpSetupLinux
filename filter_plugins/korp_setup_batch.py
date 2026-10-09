# -*- coding: utf-8 -*-
"""Filtros do cadastro de serviços em lote (fast path do setup).

Reproduzem, para todos os serviços de uma role de uma vez, o que
roles/utils/tasks/services/vars_validation.yml, add_service.yml (segredo),
consul_kv/ensure_kv.yml (itens) e oauth_client/* (hash) faziam por serviço, e, em uma tarefa,
o que default/get_latest_installed_version.yml, services/gather_info.yml e apps/ensure_mapping.yml
calculavam em várias.
"""
import base64
import copy
import hashlib
import json
import os
import random
import uuid

from ansible.errors import AnsibleFilterError
from ansible.module_utils.common.text.converters import to_text
from ansible.plugins.test.core import version_compare
from ansible.utils.vars import merge_hash


def _combine(base, extra):
    """`combine(recursive=True)` do Ansible: dicts são mesclados, o resto é substituído."""
    result = dict(base) if isinstance(base, dict) else {}
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _combine(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


# Namespace usado pelo filtro `to_uuid` do Ansible
_ANSIBLE_UUID_NAMESPACE = uuid.UUID("361E6D51-FAEC-444A-9079-341386DA8E2E")


def _to_uuid(value):
    return str(uuid.uuid5(_ANSIBLE_UUID_NAMESPACE, to_text(value, errors="surrogate_or_strict")))


def _legacy_secret(rng):
    """Mesmo valor de `10000 | random | to_uuid | upper`."""
    return _to_uuid(rng.randrange(0, 10000, 1)).upper()


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
            if not isinstance(service_vars["volumes_directories"], list):
                raise AnsibleFilterError("'volumes_directories' de %s deve ser uma lista" % name)
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


def korp_path_stat(path):
    """Subconjunto do retorno de ansible.builtin.stat usado por services/gather_info.yml.

    Como no stat, `path` só existe no resultado quando o arquivo existe (gather_info depende disso:
    a lookup do compose não versionado fica indefinida e a tarefa é pulada pelo `when`).
    Avaliado no controlador, que é o próprio host (os plays usam connection: local).
    """
    if os.path.lexists(path):  # mesmo critério do stat (follow: false)
        return {"stat": {"exists": True, "path": path}}
    return {"stat": {"exists": False}}


def korp_latest_installed_version(apps_map):
    """Facts de default/get_latest_installed_version.yml sem is_updating, a partir de installed_apps.yml.

    Mesma sequência das tarefas: has_versioned_apps = versioned != None; sem aplicativos versionados,
    versioned recebe o valor temporário {1: 'temp_value'} (combine recursive, list_merge append_rp);
    a última versão é a maior pelo teste `version` (loose), na ordem do with_dict.
    """
    if not isinstance(apps_map, dict) or "versioned" not in apps_map:
        raise AnsibleFilterError("installed_apps.yml sem a chave 'versioned'")
    temp_apps_map = copy.deepcopy(apps_map)
    has_versioned_apps = temp_apps_map["versioned"] is not None
    if not has_versioned_apps:
        temp_apps_map = merge_hash(temp_apps_map, {"versioned": {1: "temp_value"}}, True, "append_rp")
    versioned = temp_apps_map["versioned"]
    if not isinstance(versioned, dict):
        raise AnsibleFilterError("'versioned' de installed_apps.yml não é um mapeamento")
    latest = "0.0.0"
    if has_versioned_apps:
        for key, value in versioned.items():
            if version_compare(latest, key, "<") and value != "temp_value":
                latest = to_text(key)
    return {"temp_apps_map": temp_apps_map, "latest_installed_version": latest,
            "has_versioned_apps": has_versioned_apps}


def _jinja_attr(value, name):
    """`value.name` do Jinja sobre dados YAML: chave do dict ou indefinido (None aqui)."""
    if isinstance(value, dict) and name in value:
        return True, value[name]
    return False, None


def korp_service_lists(compose_services, services):
    """Listas de services/gather_info.yml (tarefas com with_dict e set_fact acumulando à esquerda).

    compose_services: services do compose não versionado renderizado ({} se ele não existe).
    exclusivos: container_name dos serviços cuja tag tem mais de 3 partes separadas por ponto;
    não versionados: chaves de services com version.unversioned definido e verdadeiro.
    """
    exclusive = []
    for name, service in (compose_services or {}).items():
        try:
            tag = service["image"].split(":")[1]
            if len(tag.split(".")) > 3:
                exclusive = [service["container_name"]] + exclusive
        except (KeyError, IndexError, TypeError, AttributeError) as e:
            raise AnsibleFilterError("serviço %s do compose sem image/container_name válidos: %s" % (name, e))
    if not isinstance(services, dict):
        raise AnsibleFilterError("services deve ser um mapeamento")
    unversioned = []
    for name, value in services.items():
        has_version, version = _jinja_attr(value, "version")
        defined, flag = _jinja_attr(version, "unversioned") if has_version else (False, None)
        if defined and flag:
            unversioned = [name] + unversioned
    return {"exclusive": exclusive, "unversioned": unversioned}


def korp_apps_mapping(apps_map, app_id, version, unversioned, versioned):
    """apps_map de apps/ensure_mapping.yml fora do caso só exclusivo (que mantém as tarefas originais).

    Normalização (combine não recursivo com default(..., true)), depois, se for o caso, [app_id] em
    unversioned e em versioned[version], com combine recursive e list_merge append_rp.
    """
    if not isinstance(apps_map, dict):
        raise AnsibleFilterError("installed_apps.yml não contém um mapeamento")
    apps_map = merge_hash(apps_map, {"unversioned": apps_map.get("unversioned") or [],
                                     "versioned": apps_map.get("versioned") or {}}, False, "replace")
    if unversioned:
        apps_map = merge_hash(apps_map, {"unversioned": [app_id]}, True, "append_rp")
    if versioned:
        apps_map = merge_hash(apps_map, {"versioned": {version: [app_id]}}, True, "append_rp")
    return apps_map


class FilterModule:
    def filters(self):
        return {
            "korp_service_plan": korp_service_plan,
            "korp_kv_batch_items": korp_kv_batch_items,
            "korp_sha256_base64": korp_sha256_base64,
            "korp_oauth_clients": korp_oauth_clients,
            "korp_path_stat": korp_path_stat,
            "korp_latest_installed_version": korp_latest_installed_version,
            "korp_service_lists": korp_service_lists,
            "korp_apps_mapping": korp_apps_mapping,
        }
