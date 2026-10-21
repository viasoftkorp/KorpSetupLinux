#!/usr/bin/python

from pkg_resources import require
from ansible.module_utils.basic import *
from ansible.module_utils.korp_kv_merge import merge_kv

# Este módulo permite a manipulação de KVs do consul.
# Ele realiza as seguintes operações:
#
#   1. Adiciona valores inéditos;      
#   2. Sobrescreve valores referentes ao caminho passado explicitamente em 'keys_to_overwrite'; 
#   3. Retorna um novo dicionário resultante da operação.

def main():

    module = AnsibleModule(
        argument_spec= dict(
            current_kv = dict(type='dict', required=True),
            new_kv = dict(type='dict', required=True),
            keys_to_overwrite = dict(type='list', elements='str', required=True)
        )
    )
 
    # Definição de variáveis consul
    new_kv = module.params['new_kv']
    current_kv = module.params['current_kv']
    keys_to_overwrite = module.params["keys_to_overwrite"]

    merged_kv = merge_kv(current_kv, new_kv, keys_to_overwrite)
    
    # Retornando resultado
    result = dict(
        changed=False,
        prop=merged_kv,
    )
   
    module.exit_json(**result)
 
if __name__ == "__main__":
    main()
 