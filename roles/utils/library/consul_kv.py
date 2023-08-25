#!/usr/bin/python

# Modulo garante que nenhum propriedade já existente no consul seja sobrescrita
# Caso isso seja alterado irá quebrar a adição de cliente oauth (secret será sobrescrito no consul), e lógica do KV de Viasoft.ELT

from pkg_resources import require
from ansible.module_utils.basic import *

def main():
    module = AnsibleModule(
        argument_spec= dict(
            current_kv = dict(type='dict', required=True),
            new_kv = dict(type='dict', required=True)
        )
    )

    new_kv = module.params['new_kv']
    current_kv = module.params['current_kv']

    new_kv.update(current_kv)

    result = dict(
        changed=False,
        prop=new_kv,
    )

    module.exit_json(**result)

if __name__ == "__main__":
    main()
