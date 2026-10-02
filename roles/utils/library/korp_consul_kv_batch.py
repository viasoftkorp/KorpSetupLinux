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
    def __init__(self, message, results=None):
        super(KorpKVError, self).__init__(message)
        self.results = results or []


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
    results = []
    try:
        return _ensure_kvs(kv, items, default_kv_overwrite, custom_kv_overwrite, custom_defined, read_keys,
                           results)
    except KorpKVError as exc:
        exc.results = list(results)
        raise


def _kv_call(key, func, *args, **kwargs):
    try:
        return func(*args, **kwargs)
    except Exception as exc:
        raise KorpKVError("Falha ao acessar o KV de %s: %s" % (key, to_text(exc)))


def _ensure_kvs(kv, items, default_kv_overwrite, custom_kv_overwrite, custom_defined, read_keys, results):
    changed = False
    custom_set = False
    for item in items:
        key = item["key"]
        new_kv = item["new_kv"]
        _, existing = _kv_call(key, kv.get, key)
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
                _kv_call(key, kv.put, key, value)
                changed = True
                action = "updated"
            else:
                action = "unchanged"
        else:
            value = to_nice_json(new_kv)
            created = bool(_kv_call(key, kv.put, key, value, cas=0))
            changed = changed or created
            action = "created" if created else "cas_conflict"
        results.append({"key": key, "action": action})

    values = {}
    for key in read_keys:
        _, data = _kv_call(key, kv.get, key)
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
        module.fail_json(msg=to_text(exc), results=getattr(exc, "results", []))
    module.exit_json(**result)


if __name__ == "__main__":
    main()
