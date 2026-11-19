"""Cadastro do salt-minion não para o setup (DEVO-8135).

Com o AWX operando pelo Zabbix, o salt-master fica desligado fora de operações pontuais. O cadastro do
minion (Vault Manager -> salt) falharia em todo setup e, antes, interrompia a instalação. Agora a falha vira
um aviso e o teste de conexão com o salt só roda quando o cadastro deu certo.
"""
import os
import unittest

import yaml

from _loader import REPO

SALT_SETUP = os.path.join(REPO, "roles/provisioning/tasks/salt_minion_setup.yml")


class SaltMinionOptionalTests(unittest.TestCase):
    def setUp(self):
        with open(SALT_SETUP) as handle:
            tasks = yaml.safe_load(handle)
        self.block = next(t for t in tasks if t["name"] == "Cadastro de salt-minion")["block"]

    def test_failed_registration_is_a_warning_not_a_failure(self):
        self.assertFalse([t["name"] for t in self.block if "ansible.builtin.fail" in t])
        warning = next(t for t in self.block if t["name"] == "Aviso de cadastro do salt-minion não concluído")
        self.assertIn("ansible.builtin.debug", warning)
        self.assertEqual(warning["when"], "(result.status | default(0)) not in [200, 201]")

    def test_connection_test_runs_only_after_a_successful_registration(self):
        test = next(t for t in self.block if t["name"] == "Teste de conexão com salt")
        self.assertEqual(test["when"], "not skip_salt_test | default(false) and (result.status | default(0)) in [200, 201]")


if __name__ == "__main__":
    unittest.main()
