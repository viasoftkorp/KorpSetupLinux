"""korp-ops: única execução remota que o agente Zabbix permite nos servidores onpremise (DEVO-8135).

O AWX deixa de usar o salt (cmd.run como root em todos os clientes) e passa a pedir ao Zabbix que rode
`sudo -n /usr/local/sbin/korp-ops <operação> <args>`. Estes testes garantem que:
  - só existem as operações do catálogo e todo argumento é validado antes de executar qualquer coisa;
  - a resposta é sempre um JSON com "ok" (o Zabbix não devolve o código de saída ao AWX);
  - operações longas viram jobs em segundo plano, acompanhados por 'status', sem dois jobs iguais ao mesmo tempo;
  - os uploads só vão para o Backblaze, com o token fora da linha de comando, e o Viasoft.Email sempre volta;
  - o agente só libera o korp-ops (DenyKey de metacaracteres antes do AllowKey e DenyKey de todo o resto no fim).
"""
import hashlib
import importlib.machinery
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import zipfile
from unittest import mock

import jinja2
import yaml

from _loader import REPO

KORP_OPS = os.path.join(REPO, "roles/provisioning/files/scripts/korp-ops")
AGENT_TEMPLATE = "roles/provisioning/templates/configs/zabbix-agent.conf.j2"
ZABBIX_SETUP = "roles/provisioning/tasks/zabbix_setup.yml"
TENANT = "11111111-2222-3333-4444-555555555555"
UPLOAD_URL = "https://pod-000-1005-03.backblaze.com/b2api/v2/b2_upload_file/4a48fe8875c6214145260818/c001_v0001005_t0014"
UPLOAD_TOKEN = "4_0018228b62563a9000000001c_01b2c3d4_d20261111_m203000_c001_v0001005_t0014_tUPL"

DOCKER_FALSO = """#!/bin/sh
echo "$*" >> "$DOCKER_CHAMADAS"
case "$1" in
  logs) [ "$4" = nao-existe ] && { echo "Error: No such container: $4" >&2; exit 1; }; echo "log de $4 (tail $3)" ;;
  ps) printf 'Korp.Compras.Gateway-2025.2.0\\nViasoft.Email\\n' ;;
  inspect)
    fmt=$3; shift 3
    for n in "$@"; do
      [ "$n" = nao-existe ] && { echo "Error: No such object: $n" >&2; exit 1; }
      case "$fmt" in
        *.Name*) echo "/$n;c0ffee;2025.2.0.7" ;;
        *.Id*) echo "id-$n" ;;
        *Running*) echo true ;;
        *) echo "c0ffee 2025.2.0.7" ;;
      esac
    done ;;
esac
"""


class KorpOpsCase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)
        for sub in ("bin", "state", "scripts", "docker", "email"):
            os.makedirs(os.path.join(self.dir, sub))
        self.calls = os.path.join(self.dir, "docker-calls")
        self.write(os.path.join(self.dir, "bin", "docker"), DOCKER_FALSO, executable=True)
        self.env = {
            **os.environ,
            "PATH": f"{self.dir}/bin:{os.environ['PATH']}",
            "DOCKER_CHAMADAS": self.calls,
            "KORP_OPS_STATE_DIR": os.path.join(self.dir, "state"),
            "KORP_OPS_SCRIPTS_DIR": os.path.join(self.dir, "scripts"),
            "KORP_OPS_DOCKER_ROOT": os.path.join(self.dir, "docker"),
            "KORP_OPS_EMAIL_DATA_DIR": os.path.join(self.dir, "email"),
            "KORP_OPS_NO_SYSTEMD": "1",
        }
        self.env.pop("SUDO_USER", None)

    @staticmethod
    def write(path, content, executable=False):
        with open(path, "w") as handle:
            handle.write(content)
        if executable:
            os.chmod(path, 0o755)

    def korp_ops(self, *args, env=None):
        result = subprocess.run([sys.executable, KORP_OPS, *args], capture_output=True, text=True, timeout=60,
                                env=env or self.env)
        self.assertEqual(result.stderr, "", result.stderr)
        lines = result.stdout.strip().splitlines()
        self.assertEqual(len(lines), 1, f"esperado um único JSON, veio: {result.stdout!r}")
        response = json.loads(lines[0])
        self.assertEqual(result.returncode, 0 if response["ok"] else 1)
        return response

    def docker_calls(self):
        if not os.path.exists(self.calls):
            return []
        with open(self.calls) as handle:
            return handle.read().splitlines()

    def wait_job(self, job, limit=30):
        deadline = time.time() + limit
        while time.time() < deadline:
            status = self.korp_ops("status", job)
            if status["state"] != "running":
                return status
            time.sleep(0.2)
        self.fail(f"job {job} não terminou em {limit}s")


class ValidationTests(KorpOpsCase):
    def test_version(self):
        self.assertEqual(self.korp_ops("version"), {"ok": True, "op": "version", "version": "1"})

    def test_rejects_unknown_operations_and_bad_arguments_without_running_anything(self):
        cases = [
            (("rm", "-rf", "/"), "operação desconhecida"),
            (("logs", "../../etc"), "nome de container inválido"),
            (("logs", "Korp.Teste", "0"), "quantidade de linhas"),
            (("logs", "Korp.Teste", "99999"), "quantidade de linhas"),
            (("update", "-rf"), "nome de container inválido"),
            (("elt", "nao-e-guid"), "GUID inválido"),
            (("upload-logs", "Korp.Teste", "https://pod-1.example.com/b2api/v2/b2_upload_file/a/b", UPLOAD_TOKEN, "temp/a.zip"), "URL de upload inválida"),
            (("upload-logs", "Korp.Teste", "http://pod-000-1.backblaze.com/b2api/v2/b2_upload_file/a/b", UPLOAD_TOKEN, "temp/a.zip"), "URL de upload inválida"),
            (("upload-logs", "Korp.Teste", UPLOAD_URL, "curto", "temp/a.zip"), "token de upload inválido"),
            (("upload-logs", "Korp.Teste", UPLOAD_URL, UPLOAD_TOKEN, "outro/a.zip"), "nome de arquivo no Backblaze inválido"),
            (("upload-logs", "Korp.Teste", UPLOAD_URL, UPLOAD_TOKEN, "dbs/a.zip"), "nome de arquivo no Backblaze inválido"),
            (("upload-email-db", "nao-e-guid", UPLOAD_URL, UPLOAD_TOKEN, "dbs/a.zip"), "GUID inválido"),
            (("upload-email-db", TENANT, UPLOAD_URL, UPLOAD_TOKEN, "temp/a.zip"), "nome de arquivo no Backblaze inválido"),
            (("status", "../x"), "job_id inválido"),
            (("labels",), "número de argumentos"),
            (("update", "a", "b"), "uso: korp-ops update"),
        ]
        for args, message in cases:
            with self.subTest(args=args):
                response = self.korp_ops(*args)
                self.assertFalse(response["ok"])
                self.assertIn(message, response["error"])
        self.assertEqual(self.docker_calls(), [])
        self.assertFalse(os.path.exists(os.path.join(self.dir, "state", "jobs")) and os.listdir(os.path.join(self.dir, "state", "jobs")))

    def test_internal_run_is_refused_when_called_through_sudo(self):
        response = self.korp_ops("_run", "update-20261111T000000-abcdef", env={**self.env, "SUDO_USER": "zabbix"})
        self.assertEqual(response, {"ok": False, "op": "_run", "error": "operação interna"})


class DirectOperationTests(KorpOpsCase):
    def test_logs(self):
        self.assertEqual(self.korp_ops("logs", "Korp.Compras.Gateway-2025.2.0")["output"].strip(),
                         "log de Korp.Compras.Gateway-2025.2.0 (tail 200)")
        self.korp_ops("logs", "Korp.Compras.Gateway-2025.2.0", "50")
        self.assertEqual(self.docker_calls(), ["logs --tail 200 Korp.Compras.Gateway-2025.2.0",
                                               "logs --tail 50 Korp.Compras.Gateway-2025.2.0"])

    def test_logs_of_missing_container_returns_the_docker_error(self):
        response = self.korp_ops("logs", "nao-existe")
        self.assertFalse(response["ok"])
        self.assertIn("No such container: nao-existe", response["error"])

    def test_services_keeps_the_salt_format_name_commit_version(self):
        self.assertEqual(self.korp_ops("services")["services"],
                         ["Korp.Compras.Gateway-2025.2.0;c0ffee;2025.2.0.7", "Viasoft.Email;c0ffee;2025.2.0.7"])

    def test_labels(self):
        response = self.korp_ops("labels", "Korp.Compras.Gateway-2025.2.0")
        self.assertEqual((response["commit"], response["version"]), ("c0ffee", "2025.2.0.7"))
        self.assertFalse(self.korp_ops("labels", "nao-existe")["ok"])


class JobTests(KorpOpsCase):
    def test_update_runs_in_background_and_returns_the_new_labels(self):
        self.write(os.path.join(self.dir, "scripts", "containers_update.sh"),
                   "#!/bin/sh\necho \"atualizando $1\"\nsleep 1\necho fim\n", executable=True)
        started = self.korp_ops("update", "Korp.Compras.Gateway-2025.2.0")
        self.assertEqual(started["state"], "started")
        self.assertRegex(started["job_id"], r"^update-[0-9]{8}T[0-9]{6}-[0-9a-f]{6}$")

        duplicate = self.korp_ops("update", "Korp.Compras.Gateway-2025.2.0")
        self.assertFalse(duplicate["ok"])
        self.assertIn(started["job_id"], duplicate["error"])

        status = self.wait_job(started["job_id"])
        self.assertEqual(status["state"], "ok")
        self.assertEqual(status["result"], {"commit": "c0ffee", "version": "2025.2.0.7"})
        self.assertIn("atualizando Korp.Compras.Gateway-2025.2.0", status["log"])
        self.assertNotIn("pid", status)
        self.assertEqual(self.korp_ops("update", "Korp.Compras.Gateway-2025.2.0")["state"], "started")

    def test_update_runs_the_script_without_shebang_with_bash(self):
        # o containers_update.sh do setup (template) não tem shebang; pelo salt ele roda via bash
        self.write(os.path.join(self.dir, "scripts", "containers_update.sh"),
                   "# Para atualizar apenas um container, execute './containers_update.sh <container_name>'\n"
                   "[[ -n \"$1\" ]] && echo \"bash: atualizando $1\"\n", executable=True)
        status = self.wait_job(self.korp_ops("update", "Korp.Compras.Gateway-2025.2.0")["job_id"])
        self.assertEqual(status["state"], "ok", status)
        self.assertIn("bash: atualizando Korp.Compras.Gateway-2025.2.0", status["log"])

    def test_elt_runs_the_script_without_shebang_with_bash(self):
        self.write(os.path.join(self.dir, "scripts", "carga_inicial_elt.sh"), "[[ -n \"$1\" ]] && echo \"bash: $1\"\n",
                   executable=True)
        status = self.wait_job(self.korp_ops("elt", TENANT)["job_id"])
        self.assertEqual(status["state"], "ok", status)
        self.assertIn(f"bash: environmentId={TENANT}", status["log"])

    def test_failed_script_ends_the_job_with_error(self):
        self.write(os.path.join(self.dir, "scripts", "containers_update.sh"), "#!/bin/sh\necho falhou\nexit 3\n", executable=True)
        status = self.wait_job(self.korp_ops("update", "Korp.Teste")["job_id"])
        self.assertEqual(status["state"], "error")
        self.assertIn("código 3", status["error"])

    def test_elt_passes_the_environment_id(self):
        self.write(os.path.join(self.dir, "scripts", "carga_inicial_elt.sh"), "#!/bin/sh\necho \"$@\"\n", executable=True)
        status = self.wait_job(self.korp_ops("elt", TENANT)["job_id"])
        self.assertEqual(status["state"], "ok")
        self.assertIn(f"environmentId={TENANT}", status["log"])

    def test_job_that_died_is_reported_as_error(self):
        jobs = os.path.join(self.dir, "state", "jobs", "restart-20261111T000000-abcdef")
        os.makedirs(jobs)
        self.write(os.path.join(jobs, "request.json"), json.dumps({"op": "restart", "args": ["x"], "target": "x", "created": time.time()}))
        self.write(os.path.join(jobs, "status.json"), json.dumps({"state": "running", "pid": 2 ** 22 + 12345}))
        status = self.korp_ops("status", "restart-20261111T000000-abcdef")
        self.assertEqual(status["state"], "error")
        self.assertIn("interrompido", status["error"])

    def test_old_finished_jobs_are_removed(self):
        old = os.path.join(self.dir, "state", "jobs", "restart-20261001T000000-abcdef")
        os.makedirs(old)
        self.write(os.path.join(old, "request.json"), json.dumps({"op": "restart", "args": ["x"], "target": "x", "created": 0}))
        self.write(os.path.join(old, "status.json"), json.dumps({"state": "ok"}))
        os.utime(old, (0, 0))
        self.write(os.path.join(self.dir, "scripts", "containers_update.sh"), "#!/bin/sh\n", executable=True)
        self.wait_job(self.korp_ops("update", "Korp.Teste")["job_id"])
        self.assertFalse(os.path.exists(old))


class UploadTests(KorpOpsCase):
    """Executa as funções dos jobs no próprio processo, trocando só a chamada HTTP ao Backblaze."""

    def setUp(self):
        super().setUp()
        # Sem extensão .py: carrega com o SourceFileLoader, lendo as variáveis de ambiente do teste
        loader = importlib.machinery.SourceFileLoader("korp_ops_upload_test", KORP_OPS)
        spec = importlib.util.spec_from_loader(loader.name, loader)
        self.module = importlib.util.module_from_spec(spec)
        with mock.patch.dict(os.environ, self.env, clear=True):
            loader.exec_module(self.module)
        self.work = os.path.join(self.dir, "work")
        os.makedirs(self.work)
        # Os jobs escrevem a saída dos subprocessos no log: precisa ser um arquivo de verdade
        self.log = open(os.path.join(self.dir, "job.log"), "w")
        self.addCleanup(self.log.close)
        self.sent = []

    def fake_urlopen(self, request, timeout):
        body = request.data.read()
        self.sent.append({"url": request.full_url, "headers": dict(request.header_items()), "body": body})
        return io.BytesIO(b"{}")

    def run_job(self, function, *args):
        with mock.patch.dict(os.environ, self.env, clear=True), mock.patch.object(self.module.urllib.request, "urlopen", self.fake_urlopen):
            return function(self.log, *args, self.work)

    def test_logs_go_to_temp_and_the_email_database_to_dbs(self):
        # Mesmos prefixos do AWX: logs em temp/ (chave BackblazeLogs) e bancos em dbs/ (chave Backblaze)
        for op, name in (("upload-logs", "temp/id-Korp.Teste-json.zip"), ("upload-email-db", f"dbs/{TENANT}.zip")):
            with self.subTest(op=op):
                validate_name = self.module.JOBS[op][1][-1]
                self.assertEqual(validate_name(name), name)

    def test_upload_logs_zips_rotated_logs_and_sends_token_only_in_header(self):
        log_dir = os.path.join(self.dir, "docker", "containers", "id-Korp.Teste")
        os.makedirs(log_dir)
        for suffix in ("", ".1", ".2"):
            self.write(os.path.join(log_dir, f"id-Korp.Teste-json.log{suffix}"), f"log{suffix}\n")
        self.write(os.path.join(log_dir, "hostconfig.json"), "{}")

        result = self.run_job(self.module.job_upload_logs, "Korp.Teste", UPLOAD_URL, UPLOAD_TOKEN, "temp/id-Korp.Teste-json.zip")

        sent = self.sent[0]
        headers = {k.lower(): v for k, v in sent["headers"].items()}
        self.assertEqual(sent["url"], UPLOAD_URL)
        self.assertEqual(headers["authorization"], UPLOAD_TOKEN)
        self.assertEqual(headers["x-bz-file-name"], "temp/id-Korp.Teste-json.zip")
        self.assertEqual(headers["x-bz-content-sha1"], hashlib.sha1(sent["body"]).hexdigest())
        self.assertEqual(int(headers["content-length"]), len(sent["body"]))
        with zipfile.ZipFile(io.BytesIO(sent["body"])) as archive:
            self.assertEqual(sorted(archive.namelist()), [f"id-Korp.Teste-json.log{s}" for s in ("", ".1", ".2")])
        self.assertEqual(result, {"b2_file_name": "temp/id-Korp.Teste-json.zip", "size": len(sent["body"])})
        self.assertEqual(os.listdir(self.work), [], "o zip temporário deve ser removido")

    @unittest.skipUnless(shutil.which("zip"), "zip não instalado")
    def test_upload_email_db_restarts_the_container_and_returns_the_generated_password(self):
        db_dir = os.path.join(self.dir, "email", TENANT)
        os.makedirs(db_dir)
        self.write(os.path.join(db_dir, f"{TENANT}.db"), "sqlite\n")

        result = self.run_job(self.module.job_upload_email_db, TENANT, UPLOAD_URL, UPLOAD_TOKEN, f"dbs/{TENANT}.zip")

        calls = [c for c in self.docker_calls() if c.split()[0] in ("stop", "start")]
        self.assertEqual(calls, ["stop Viasoft.Email", "start Viasoft.Email"])
        self.assertEqual(len(result["zip_password"]), 64)
        self.assertTrue(result["email_running"])
        with zipfile.ZipFile(io.BytesIO(self.sent[0]["body"])) as archive:
            self.assertEqual(archive.read(f"{TENANT}.db", pwd=result["zip_password"].encode()), b"sqlite\n")
        self.assertEqual(os.listdir(self.work), [])

    def test_upload_email_db_starts_the_container_again_when_zip_fails(self):
        db_dir = os.path.join(self.dir, "email", TENANT)
        os.makedirs(db_dir)
        self.write(os.path.join(db_dir, f"{TENANT}.db"), "sqlite\n")
        self.write(os.path.join(self.dir, "bin", "zip"), "#!/bin/sh\nexit 12\n", executable=True)

        with self.assertRaises(self.module.OpsError) as error:
            self.run_job(self.module.job_upload_email_db, TENANT, UPLOAD_URL, UPLOAD_TOKEN, f"dbs/{TENANT}.zip")

        self.assertIn("zip código 12", str(error.exception))
        self.assertIn("start Viasoft.Email", self.docker_calls())
        self.assertEqual(self.sent, [])


class AgentConfigTests(unittest.TestCase):
    def render(self):
        env = jinja2.Environment(loader=jinja2.FileSystemLoader(REPO), undefined=jinja2.StrictUndefined, trim_blocks=True)
        secrets = {"Others": {"Zabbix": {"ServerAdress": "zabbix.exemplo:10051", "PSK": {"Identity": "id", "Key": "k"}}}}
        text = env.get_template(AGENT_TEMPLATE).render(services_secrets=secrets, tenant_id=TENANT, korp_dir_path="/etc/korp")
        return [line for line in text.splitlines() if line and not line.startswith("#")]

    def test_only_korp_ops_is_allowed_and_shell_metacharacters_are_denied_first(self):
        lines = self.render()
        rules = [line for line in lines if line.startswith(("AllowKey=", "DenyKey="))]
        allow = rules.index("AllowKey=system.run[sudo -n /usr/local/sbin/korp-ops *,*]")
        self.assertEqual([r for r in rules if r.startswith("AllowKey=")], [rules[allow]])
        self.assertEqual(rules[-1], "DenyKey=system.run[*]")
        denied_before = {r[len("DenyKey=system.run[*"):-len("*,*]")] for r in rules[:allow]}
        self.assertEqual(denied_before, set(";|&`$><(){}\\'\""))

    def test_keeps_psk_and_identity(self):
        lines = self.render()
        self.assertIn("TLSConnect=psk", lines)
        self.assertIn("TLSPSKFile=/etc/korp/certs/zabbix.psk", lines)
        self.assertIn(f"Hostname=zabbix-agent_{TENANT}", lines)


class ZabbixSetupTasksTests(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(REPO, ZABBIX_SETUP)) as handle:
            self.tasks = {t["name"]: t for t in yaml.safe_load(handle)}

    def test_agent_7_0_is_installed_and_upgraded(self):
        deb = self.tasks["Instalação de pacote de zabbix"]["ansible.builtin.apt"]["deb"]
        self.assertIn("/zabbix/7.0/", deb)
        self.assertEqual(self.tasks["Instalação de zabbix-agent2"]["ansible.builtin.apt"]["state"], "latest")

    def test_sudo_allows_zabbix_to_run_only_korp_ops(self):
        sudoers = self.tasks["Permissão de sudo do zabbix somente para o korp-ops"]["ansible.builtin.copy"]
        self.assertEqual(sudoers["content"], "zabbix ALL=(root) NOPASSWD: /usr/local/sbin/korp-ops\n")
        self.assertEqual((sudoers["dest"], sudoers["mode"]), ("/etc/sudoers.d/korp-ops", "0440"))
        self.assertEqual(sudoers["validate"], "/usr/sbin/visudo -cf %s")
        script = self.tasks["Instalação do korp-ops"]["ansible.builtin.copy"]
        self.assertEqual((script["dest"], script["owner"], script["mode"]), ("/usr/local/sbin/korp-ops", "root", "0755"))

    def test_psk_is_readable_only_by_root_and_the_agent(self):
        psk = self.tasks["Criação de arquivo de contendo a PSK de zabbix-agent2"]["ansible.builtin.copy"]
        self.assertEqual((psk["owner"], psk["group"], psk["mode"]), ("root", "zabbix", "0440"))


if __name__ == "__main__":
    unittest.main()
