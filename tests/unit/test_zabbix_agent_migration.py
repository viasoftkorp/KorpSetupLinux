"""Migração do agente Zabbix dos clientes já instalados sem rodar o setup (DEVO-8135).

O scripts/migracao-zabbix/migrar-agente.sh roda pelo salt em cada cliente e não tem o token do cliente, então mantém
a configuração atual (korp-default.conf e PSK) e instala só o que o zabbix_setup.yml acrescentou: zabbix-release 7.0,
zabbix-agent2 7.0, korp-ops, sudoers e as regras do agente. Estes testes garantem que o script e o setup instalam a
mesma coisa, nos mesmos lugares e com as mesmas permissões; o comportamento é validado no laboratório (Zabbix 7.0.5 e
cliente Ubuntu 22.04 com agente 6.2.9).
"""
import os
import re
import subprocess
import unittest

import yaml

from _loader import REPO

SCRIPT = os.path.join(REPO, "scripts/migracao-zabbix/migrar-agente.sh")
ZABBIX_SETUP = os.path.join(REPO, "roles/provisioning/tasks/zabbix_setup.yml")
FILES = "roles/provisioning/files/"


class MigrationScriptTests(unittest.TestCase):
    def setUp(self):
        with open(SCRIPT) as handle:
            self.script = handle.read()
        with open(ZABBIX_SETUP) as handle:
            self.tasks = {t["name"]: t for t in yaml.safe_load(handle)}

    def copy_task(self, name):
        return self.tasks[name]["ansible.builtin.copy"]

    def installed(self, dest):
        found = re.findall(rf"install -o (\S+) -g (\S+) -m (\d+) \S+ {re.escape(dest)}\n", self.script)
        self.assertEqual(len(found), 1, f"o script deve instalar {dest} uma vez")
        return found[0]

    def test_is_valid_bash(self):
        result = subprocess.run(["bash", "-n", SCRIPT], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_downloads_the_files_the_setup_installs(self):
        downloaded = set(re.findall(r'"\$RAW/([^"]+)"', self.script))
        sources = {FILES + self.copy_task(name)["src"] for name in
                   ("Instalação do korp-ops", "Regras de comandos remotos do zabbix-agent2 (somente korp-ops)")}
        self.assertEqual(downloaded, sources)
        for path in downloaded:
            self.assertTrue(os.path.isfile(os.path.join(REPO, path)), path)

    def test_installs_to_the_same_places_with_the_same_permissions(self):
        for name in ("Instalação do korp-ops", "Permissão de sudo do zabbix somente para o korp-ops",
                     "Regras de comandos remotos do zabbix-agent2 (somente korp-ops)"):
            task = self.copy_task(name)
            with self.subTest(dest=task["dest"]):
                self.assertEqual(self.installed(task["dest"]), (task["owner"], task["group"], task["mode"]))

    def test_restricts_the_psk_like_the_setup(self):
        psk = self.copy_task("Criação de arquivo de contendo a PSK de zabbix-agent2")
        # A PSK continua a mesma; o arquivo vem do TLSPSKFile do korp-default.conf
        self.assertIn("sed -n 's/^TLSPSKFile=//p' \"$CONF_DIR/korp-default.conf\"", self.script)
        self.assertIn(f'chown {psk["owner"]}:{psk["group"]} "$psk"', self.script)
        self.assertIn(f'chmod {psk["mode"]} "$psk"', self.script)

    def test_sudoers_line_is_the_same_as_the_setup(self):
        line = re.search(r"^SUDOERS_LINE='([^']+)'$", self.script, re.M).group(1)
        self.assertEqual(line + "\n", self.copy_task("Permissão de sudo do zabbix somente para o korp-ops")["content"])
        self.assertIn('visudo -cf "$work/sudoers"', self.script)

    def test_uses_the_same_zabbix_release_as_the_setup(self):
        setup_deb = self.tasks["Instalação de pacote de zabbix"]["ansible.builtin.apt"]["deb"]
        version = re.search(r"zabbix-release_([0-9.-]+)%2Bubuntu", setup_deb).group(1)
        self.assertIn(f"zabbix-release_{version}+ubuntu", self.script)
        self.assertIn("https://repo.zabbix.com/zabbix/7.0/ubuntu/pool/main/z/zabbix-release/", self.script)
        # Mesmo motivo do setup: o add-apt-repository reescreve o zabbix.list (ver test_zabbix_agent_upgrade.py)
        install = next(line for line in self.script.splitlines()
                       if line.endswith('install "$work/$deb"') and "--reinstall" not in line)
        self.assertIn("apt-get", re.search(r"^APT=\((.*)\)$", self.script, re.M).group(1))
        self.assertIn("-o Dpkg::Options::=--force-confnew", install)
        self.assertNotIn("confdef", install)
        self.assertNotIn("confold", install)


if __name__ == "__main__":
    unittest.main()
