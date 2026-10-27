"""As leituras de configuração da nuvem em roles/infrastructure/tasks/main.yml repetem antes de falhar o setup.

O vault manager responde 500 de vez em quando em minio-gateway-config (e onpremise-auth-config, onde existe); sem
retentativa, uma falha passageira da nuvem derrubava o setup inteiro. Executa as tarefas reais no Ansible, contra um
gateway local que responde 500 (corpo vazio, como a nuvem) antes de responder a configuração.
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

PRIMEIRA = "Leitura de configuração de minio da nuvem"
ULTIMA = "Definição de minio_gateway_config"


def tarefas_da_nuvem():
    """Tarefas de main.yml da leitura de minio até a definição de minio_gateway_config, inclusive."""
    with open(os.path.join(REPO, "roles/infrastructure/tasks/main.yml")) as f:
        tarefas = yaml.safe_load(f)
    nomes = [t.get("name") for t in tarefas]
    return tarefas[nomes.index(PRIMEIRA):nomes.index(ULTIMA) + 1]


class _Gateway(BaseHTTPRequestHandler):
    falhas = None  # quantas respostas 500 por caminho antes da 200; None: sempre 500
    chamadas = {}

    def do_GET(self):
        n = _Gateway.chamadas[self.path] = _Gateway.chamadas.get(self.path, 0) + 1
        if _Gateway.falhas is None or n <= _Gateway.falhas:
            self.send_response(500)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        corpo = json.dumps({"AccessKey": "ACESSO-TESTE", "SecretKey": "s"}).encode()
        self.send_response(200)
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


class CloudConfigRetryDefinitionTest(unittest.TestCase):
    def test_leituras_da_nuvem_repetem_ate_dar_certo(self):
        leituras = [t for t in tarefas_da_nuvem() if "ansible.builtin.uri" in t]
        self.assertTrue(leituras)
        for t in leituras:
            with self.subTest(t["name"]):
                self.assertGreaterEqual(t.get("retries", 0), 3)
                self.assertEqual(t.get("until"), f"{t['register']} is not failed")


@unittest.skipUnless(ansible_available(), "ansible-playbook indisponível")
class CloudConfigRetryTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        _Gateway.chamadas = {}
        self.server = HTTPServer(("127.0.0.1", 0), _Gateway)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.tarefas = tarefas_da_nuvem()
        # mesmas tarefas, sem a espera entre as tentativas
        tarefas = [dict(t, delay=0) if "retries" in t else t for t in self.tarefas]
        tarefas.append({"name": "Resultado", "ansible.builtin.debug": {"msg": "{{ minio_gateway_config.AccessKey }}"}})
        with open(os.path.join(self.dir, "play.yml"), "w") as f:
            yaml.safe_dump([{"hosts": "localhost", "connection": "local", "gather_facts": False, "tasks": tarefas}],
                           f, allow_unicode=True, sort_keys=False)

    def run_play(self):
        extra = {"gateway_url": f"http://127.0.0.1:{self.server.server_port}", "token": "x"}
        env = dict(os.environ, ANSIBLE_NOCOLOR="1", ANSIBLE_LOCALHOST_WARNING="false",
                   ANSIBLE_INVENTORY_UNPARSED_WARNING="false", ANSIBLE_RETRY_FILES_ENABLED="false", HOME=self.dir)
        p = subprocess.run(["ansible-playbook", "-i", "localhost,", "play.yml", "-e", json.dumps(extra)],
                           cwd=self.dir, env=env, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=300)
        return p.returncode, p.stdout + p.stderr

    def caminhos(self):
        return ["/" + t["ansible.builtin.uri"]["url"].split("}}/", 1)[1].replace("{{ token }}", "x")
                for t in self.tarefas if "ansible.builtin.uri" in t]

    def test_falha_passageira_nao_derruba_o_setup(self):
        _Gateway.falhas = 2
        rc, out = self.run_play()
        self.assertEqual(rc, 0, out)
        self.assertIn("ACESSO-TESTE", out)
        self.assertEqual(_Gateway.chamadas, {c: 3 for c in self.caminhos()})

    def test_falha_persistente_ainda_falha_o_setup(self):
        _Gateway.falhas = None
        rc, out = self.run_play()
        self.assertNotEqual(rc, 0, out)
        self.assertIn("Status code was 500", out)
        minio = self.caminhos()[0]
        self.assertEqual(_Gateway.chamadas, {minio: self.tarefas[0]["retries"] + 1})


if __name__ == "__main__":
    unittest.main()
