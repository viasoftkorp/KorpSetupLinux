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
