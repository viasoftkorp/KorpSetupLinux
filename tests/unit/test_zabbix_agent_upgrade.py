"""Troca do agente Zabbix 6.2 -> 7.0 nos clientes (DEVO-8135).

O /etc/apt/sources.list.d/zabbix.list é conffile do zabbix-release. O add-apt-repository que o setup.sh roda para o
PPA do Ansible reescreve todos os .list do apt (muda os comentários), e o dpkg passa a tratar o zabbix.list como
alterado: com as opções padrão do módulo apt (force-confdef,force-confold) ele mantém o repositório 6.2 e grava o
novo como .dpkg-dist, e o zabbix-agent2 continua no 6.2.9 sem erro (visto na qa-dev em 12/11/2026).
"""
import os
import re
import unittest

import yaml

from _loader import REPO

ZABBIX_SETUP = os.path.join(REPO, "roles/provisioning/tasks/zabbix_setup.yml")


class ZabbixAgentUpgradeTests(unittest.TestCase):
    def setUp(self):
        with open(ZABBIX_SETUP) as handle:
            self.tasks = yaml.safe_load(handle)

    def task(self, name):
        found = [t for t in self.tasks if t.get("name") == name]
        self.assertEqual(len(found), 1, f"task '{name}' em zabbix_setup.yml")
        return found[0]

    def test_release_package_replaces_the_rewritten_repository_file(self):
        apt = self.task("Instalação de pacote de zabbix")["ansible.builtin.apt"]
        options = apt.get("dpkg_options", "force-confdef,force-confold").split(",")
        self.assertIn("force-confnew", options)
        # com force-confdef o dpkg escolhe a ação padrão (manter o arquivo alterado) antes de olhar o force-confnew
        self.assertNotIn("force-confdef", options)
        self.assertNotIn("force-confold", options)

    def test_setup_fails_when_the_agent_is_not_7_0(self):
        names = [t.get("name") for t in self.tasks]
        check = self.task("Validação da versão do zabbix-agent2")
        self.assertIn("ansible.builtin.fail", check)
        self.assertLess(names.index("Instalação de zabbix-agent2"), names.index("Versão do zabbix-agent2"))
        self.assertLess(names.index("Versão do zabbix-agent2"), names.index("Validação da versão do zabbix-agent2"))
        version = self.task("Versão do zabbix-agent2")
        self.assertEqual(version["ansible.builtin.command"], "zabbix_agent2 -V")
        self.assertIs(version["changed_when"], False)

        pattern = re.fullmatch(r"zabbix_agent2_version\.stdout is not search\('(.+)'\)", check["when"]).group(1)
        self.assertIsNone(re.search(pattern, "zabbix_agent2 (Zabbix) 6.2.9\nRevision 7b6b0ba1c4d 4 April 2023"))
        self.assertIsNotNone(re.search(pattern, "zabbix_agent2 (Zabbix) 7.0.32\nRevision 1a2b3c4d5e6 1 October 2026"))
        self.assertIsNone(re.search(pattern, "zabbix_agent2 (Zabbix) 7.2.1"))


if __name__ == "__main__":
    unittest.main()
