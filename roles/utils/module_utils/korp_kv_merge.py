# -*- coding: utf-8 -*-
"""Regra de merge dos KVs do Consul (fonte única).

Usado por roles/utils/library/consul_kv.py e roles/utils/library/korp_consul_kv_batch.py.
As funções são exatamente as que existiam em consul_kv.py:

  1. adiciona chaves inéditas de new_kv;
  2. mantém os valores atuais de current_kv;
  3. sobrescreve os caminhos de keys_to_overwrite quando o valor novo é "verdadeiro".
"""
from __future__ import absolute_import, division, print_function
__metaclass__ = type

import json


def replace_key(keys_sequence, dictionary, new_val):
    current_key = keys_sequence[0]
    if len(keys_sequence) == 1:
        dictionary[current_key] = new_val
    else:
        dictionary[current_key] = replace_key(keys_sequence[1:], dictionary[current_key], new_val)
    return dictionary


def access_value(keys_sequence, dictionary):
    if not keys_sequence:
        return dictionary
    current_key = keys_sequence[0]
    if current_key in dictionary:
        return access_value(keys_sequence[1:], dictionary[current_key])
    else:
        return None  # Tratado posteriormente para não criar chaves nulas


def merge_kv(current_kv, new_kv, keys_to_overwrite):
    merged_kv = new_kv.copy()
    merged_kv.update(current_kv)  # armazena novas chaves
    # Removendo chaves antigas se houverem chaves atualizadas
    for key_path in keys_to_overwrite:
        keys_sequence = key_path.split(".")
        new_val = access_value(keys_sequence, new_kv)
        if new_val:
            merged_kv = replace_key(keys_sequence, merged_kv, new_val)
    return merged_kv


def to_nice_json(value):
    """Mesma saída do filtro Ansible `to_nice_json(indent=2)` para dados vindos de JSON."""
    return json.dumps(value, indent=2, sort_keys=True, separators=(',', ': '))
