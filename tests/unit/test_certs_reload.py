"""certs_reload.sh: deploy hook do certbot e fim da renovação do autoassinado (self_signed_renew-playbook.yml).

O script reiniciava 'Viasoft.Authentication', mas o container se chama 'Viasoft.Authentication-<versão>': o
docker restart falhava e o Authentication seguia com o certificado anterior. Com mais de uma versão instalada
há um Authentication por versão, e todos montam o mesmo diretório de certificados.
"""
import os
import shutil
import subprocess
import tempfile
import unittest

import jinja2

from _loader import REPO

CERTS_RELOAD = "roles/infrastructure/templates/scripts/certs_reload.sh.j2"
CONTAINERS = ["nginx", "Viasoft.Authentication-2024.2.0", "Viasoft.Authentication-2025.1.0", "login-2025.1.0",
              "Korp.Legacy.Authentication-2025.1.0", "Viasoft.Authorization-2025.1.0"]
DOCKER_FALSO = """#!/bin/sh
echo "$*" >> "$DOCKER_CHAMADAS"
if [ "$1" = ps ]; then
  printf '%s\\n' $DOCKER_CONTAINERS
elif [ "$1" = restart ]; then
  for c in $DOCKER_CONTAINERS; do [ "$c" = "$2" ] && echo "$2" && exit 0; done
  echo "Error response from daemon: No such container: $2" >&2
  exit 1
fi
"""


class CertsReloadTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)
        os.makedirs(os.path.join(self.dir, "certs", "logs"))
        os.makedirs(os.path.join(self.dir, "bin"))
        docker = os.path.join(self.dir, "bin", "docker")
        with open(docker, "w") as f:
            f.write(DOCKER_FALSO)
        os.chmod(docker, 0o755)

    def executa(self, containers):
        env = jinja2.Environment(undefined=jinja2.StrictUndefined, keep_trailing_newline=True)
        with open(os.path.join(REPO, CERTS_RELOAD)) as f:
            script = env.from_string(f.read()).render(
                certs_directory=os.path.join(self.dir, "certs"), redis_container_name="redis",
                redis={"password": "x"})
        caminho = os.path.join(self.dir, "certs_reload.sh")
        with open(caminho, "w") as f:
            f.write(script)
        chamadas = os.path.join(self.dir, "chamadas")
        # sem shebang: o certbot e o ansible.builtin.shell executam o script pelo /bin/sh
        subprocess.run(["sh", caminho], check=True, env=dict(
            os.environ, PATH=os.path.join(self.dir, "bin") + os.pathsep + os.environ["PATH"],
            DOCKER_CHAMADAS=chamadas, DOCKER_CONTAINERS=" ".join(containers)))
        with open(chamadas) as f:
            linhas = f.read().splitlines()
        self.assertIn("ps --format {{.Names}}", linhas)
        restarts = [linha.split()[1] for linha in linhas if linha.startswith("restart ")]
        with open(os.path.join(self.dir, "certs", "logs", "certs_reload.log")) as f:
            return restarts, f.read()

    def test_reinicia_o_authentication_de_cada_versao(self):
        restarts, log = self.executa(CONTAINERS)
        self.assertEqual(restarts, ["Viasoft.Authentication-2024.2.0", "Viasoft.Authentication-2025.1.0"])
        self.assertNotIn("No such container", log)
        self.assertIn("Reload de serviços finalizada", log)

    def test_sem_authentication_no_ar(self):
        restarts, log = self.executa(["nginx", "login-2025.1.0"])
        self.assertEqual(restarts, [])
        self.assertIn("Reload de serviços finalizada", log)


if __name__ == "__main__":
    unittest.main()
