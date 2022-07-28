#!/usr/bin/python

from pkg_resources import require
from ansible.module_utils.basic import *

def main():
    module = AnsibleModule(
        argument_spec= dict(
            current_consul_json = dict(type='dict', required=True),
            new_consul_json = dict(type='dict', required=True)
        )
    )

    new_consul_json = module.params['new_consul_json']
    current_consul_json = module.params['current_consul_json']

    new_consul_json.update(current_consul_json)

    result = dict(
        changed=False,
        prop=new_consul_json,
    )

    module.exit_json(**result)

if __name__ == "__main__":
    main()
