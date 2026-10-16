"""O tratamento de erro (roles/finishing/tasks/error.yml) termina com a falha original em qualquer play.

O play de provisioning (bootstrap-playbook.yml) também usa error.yml, mas não define korp_prefetch_status (variável
do play de main.yml): com prefetch=true, encerrar o download antecipado não pode quebrar o tratamento do erro.
Executa o Ansible de verdade, com um gateway local que aceita a notificação do TenantManagement.
"""
import json
import os
import shutil
import subprocess
import tempfile
import textwrap
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

from _loader import REPO

PLAYBOOK = """
- hosts: localhost
  connection: local
  gather_facts: false
  tasks:
    - name: Bloco que falha
      block:
        - name: Falha original
          ansible.builtin.fail:
            msg: FALHA-ORIGINAL
      rescue:
        - name: Tratativa de erro
          ansible.builtin.import_role:
            name: finishing
            tasks_from: error
"""


class _Gateway(BaseHTTPRequestHandler):
    def do_PUT(self):
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        self.send_response(200)
        self.end_headers()

    def log_message(self, *args):
        pass


def ansible_available():
    try:
        return subprocess.run(["ansible-playbook", "--version"], capture_output=True, stdin=subprocess.DEVNULL,
                              timeout=60).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


@unittest.skipUnless(ansible_available(), "ansible-playbook indisponível")
class FinishingErrorPathTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.server = HTTPServer(("127.0.0.1", 0), _Gateway)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.shutdown)
        with open(os.path.join(self.dir, "play.yml"), "w") as f:
            f.write(textwrap.dedent(PLAYBOOK))

    def run_play(self, extra):
        extra = dict({"gateway_url": f"http://127.0.0.1:{self.server.server_port}", "token": "x"}, **extra)
        env = dict(os.environ, ANSIBLE_ROLES_PATH=os.path.join(REPO, "roles"), ANSIBLE_NOCOLOR="1",
                   ANSIBLE_LOCALHOST_WARNING="false", ANSIBLE_INVENTORY_UNPARSED_WARNING="false",
                   ANSIBLE_RETRY_FILES_ENABLED="false", HOME=self.dir)
        p = subprocess.run(["ansible-playbook", "-i", "localhost,", "play.yml", "-e", json.dumps(extra)],
                           cwd=self.dir, env=env, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=300)
        return p.returncode, p.stdout + p.stderr

    def test_play_without_prefetch_status_ends_with_original_error(self):
        rc, out = self.run_play({"korp_image_prefetch": True})
        self.assertNotEqual(rc, 0)
        self.assertNotIn("korp_prefetch_status' is undefined", out)
        self.assertIn("TASK [finishing : Falha do playbook]", out)
        self.assertIn("FALHA-ORIGINAL", out.split("TASK [finishing : Falha do playbook]")[1])

    def test_prefetch_disabled_ends_with_original_error(self):
        rc, out = self.run_play({"korp_image_prefetch": False})
        self.assertNotEqual(rc, 0)
        self.assertIn("TASK [finishing : Falha do playbook]", out)


if __name__ == "__main__":
    unittest.main()
