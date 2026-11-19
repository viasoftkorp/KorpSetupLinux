"""Cadastro do salt-minion não para o setup (DEVO-8135).

Com o AWX operando pelo Zabbix, o salt-master fica desligado fora de operações pontuais. O cadastro do minion
(Vault Manager -> salt-api) responde erro com o salt desligado e, antes, interrompia a instalação. Agora a falha vira
um aviso e o teste de conexão com o salt só roda quando o cadastro deu certo. Executa as tarefas reais do bloco
"Cadastro de salt-minion" no Ansible, contra um gateway local.
"""
import json
import os
import shutil
import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

import yaml

from _loader import REPO

SALT_SETUP = os.path.join(REPO, "roles/provisioning/tasks/salt_minion_setup.yml")
REGISTER = "/vault/manager/server-deploy/salt/register/x"
TEST = "/vault/manager/server-deploy/salt/test/x"


def bloco_de_cadastro():
    with open(SALT_SETUP) as f:
        tarefas = yaml.safe_load(f)
    return next(t for t in tarefas if t.get("name") == "Cadastro de salt-minion")


def sem_espera(tarefa):
    """Mesma tarefa sem a espera entre tentativas (também dentro de blocos)."""
    tarefa = dict(tarefa)
    if "retries" in tarefa:
        tarefa["delay"] = 0
    if "block" in tarefa:
        tarefa["block"] = [sem_espera(t) for t in tarefa["block"]]
    return tarefa


class _Gateway(BaseHTTPRequestHandler):
    status = {}  # caminho -> status da resposta
    chamadas = {}

    def do_GET(self):
        _Gateway.chamadas[self.path] = _Gateway.chamadas.get(self.path, 0) + 1
        corpo = b"{}"
        self.send_response(_Gateway.status[self.path])
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def log_message(self, *args):
        pass


def ansible_available():
    try:
        return subprocess.run(["ansible-playbook", "--version"], capture_output=True, stdin=subprocess.DEVNULL,
                              timeout=60).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


class SaltMinionOptionalDefinitionTest(unittest.TestCase):
    def test_cadastro_sem_sucesso_nao_tem_fail(self):
        nomes = [t["name"] for t in bloco_de_cadastro()["block"] if "ansible.builtin.fail" in t]
        self.assertNotIn("Validação de resultado de registro", nomes)


@unittest.skipUnless(ansible_available(), "ansible-playbook indisponível")
class SaltMinionOptionalTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        _Gateway.chamadas = {}
        self.server = HTTPServer(("127.0.0.1", 0), _Gateway)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        play = {
            "hosts": "localhost", "connection": "local", "gather_facts": False,
            "tasks": [sem_espera(bloco_de_cadastro())],
            "handlers": [{"name": "Reinicio de salt-minion", "ansible.builtin.debug": {"msg": "reinicio"}}],
        }
        with open(os.path.join(self.dir, "play.yml"), "w") as f:
            yaml.safe_dump([play], f, allow_unicode=True, sort_keys=False)

    def run_play(self, register, test):
        _Gateway.status = {REGISTER: register, TEST: test}
        extra = {"gateway_url": f"http://127.0.0.1:{self.server.server_port}", "token": "x"}
        env = dict(os.environ, ANSIBLE_NOCOLOR="1", ANSIBLE_LOCALHOST_WARNING="false",
                   ANSIBLE_INVENTORY_UNPARSED_WARNING="false", ANSIBLE_RETRY_FILES_ENABLED="false", HOME=self.dir)
        p = subprocess.run(["ansible-playbook", "-i", "localhost,", "play.yml", "-e", json.dumps(extra)],
                           cwd=self.dir, env=env, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=300)
        return p.returncode, p.stdout + p.stderr

    def test_salt_desligado_o_setup_continua_sem_testar_o_minion(self):
        rc, out = self.run_play(register=500, test=500)
        self.assertEqual(rc, 0, out)
        self.assertIn("não foi possível cadastrar o salt-minion", out)
        self.assertNotIn(TEST, _Gateway.chamadas)

    def test_cadastro_ok_e_minion_sem_resposta_ainda_falha_o_setup(self):
        rc, out = self.run_play(register=200, test=500)
        self.assertNotEqual(rc, 0, out)
        self.assertIn("teste de conexão com o minion", out)

    def test_cadastro_ok_e_minion_respondendo(self):
        rc, out = self.run_play(register=200, test=200)
        self.assertEqual(rc, 0, out)
        self.assertEqual(_Gateway.chamadas[TEST], 1)


if __name__ == "__main__":
    unittest.main()
