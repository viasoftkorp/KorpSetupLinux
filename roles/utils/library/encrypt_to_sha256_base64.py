#!/usr/bin/python

import base64
import hashlib

from pkg_resources import require
from ansible.module_utils.basic import *

def main():
    module = AnsibleModule(
        argument_spec= dict(
            uuid = dict(type='str', required=True)
        )
    )

    hashed_secret = hashlib.sha256(module.params['uuid'].encode('utf-8'))

    base64_secret = base64.b64encode(hashed_secret.digest())

    result = dict(
        changed=False,
        secret=base64_secret,
    )

    module.exit_json(**result)

if __name__ == "__main__":
    main()