#!/usr/bin/python
# STUB DO AMBIENTE ISOLADO (tests/sim): não há login no registry com credenciais falsas;
# as imagens usadas no ambiente isolado são locais. Nunca é usado em servidores.
from ansible.module_utils.basic import AnsibleModule

def main():
    module = AnsibleModule(argument_spec=dict(
        registry_url=dict(type='str', default='https://index.docker.io/v1/', aliases=['registry', 'url']),
        username=dict(type='str'), password=dict(type='str', no_log=True), reauthorize=dict(type='bool', default=False),
        state=dict(type='str', default='present'), config_path=dict(type='path'),
    ), supports_check_mode=True)
    module.exit_json(changed=False, login_result={'sim_stub': True})

if __name__ == '__main__':
    main()
