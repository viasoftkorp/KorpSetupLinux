import importlib.machinery
import importlib.util
import json
import os
import sys
import tempfile
import unittest

from _loader import REPO, load

runner = load("scripts/acompanhamento/korp_setup_runner.py", "korp_setup_runner")
_path = os.path.join(REPO, "scripts/acompanhamento/korp-setup-acompanhar")
_spec = importlib.util.spec_from_loader("korp_setup_acompanhar",
                                        importlib.machinery.SourceFileLoader("korp_setup_acompanhar", _path))
monitor = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(monitor)

BASE = {"run_id": "r", "tags": "update", "branch": "release/x", "started_at": "2026-10-08T10:00:00+00:00",
        "log": "/etc/korp/ansible/logs/a.log", "counts": {"ok": 10, "changed": 2, "skipped": 3, "failed": 0}}
T0 = monitor.parse_time(BASE["started_at"])


class MonitorRenderTest(unittest.TestCase):
    def test_running_with_apps_and_estimate(self):
        st = dict(BASE, state="running", phase="Aplicativos", task="utils : Cadastro",
                  apps={"items": ["A", "B", "C", "D"], "index": 1, "current": "B", "dependency": "wms"},
                  last_run={"duration_s": 1200})
        text = "\n".join(monitor.render(st, T0 + 300))
        self.assertIn("Aplicativos 2/4", text)
        self.assertIn("B (dependência: wms)", text)
        self.assertIn("5m00s decorridos · última execução 20m00s (faltam ~15m00s)", text)
        self.assertIn("10 ok · 2 alteradas · 3 puladas · 0 falhas", text)
        self.assertIn("Ctrl+C fecha esta tela", text)
        self.assertNotIn("\033[", text)

    def test_running_without_apps_and_over_estimate(self):
        st = dict(BASE, state="running", phase="Infraestrutura", last_run={"duration_s": 60})
        text = "\n".join(monitor.render(st, T0 + 120))
        self.assertIn("Etapa    Infraestrutura", text)
        self.assertIn("já passou do tempo da última execução (1m00s)", text)

    def test_failure_block(self):
        st = dict(BASE, state="failed", rc=11, duration_s=95, phase="Aplicativos",
                  apps={"items": ["A"], "index": 0, "current": "A"},
                  error={"role": "utils", "task": "Garantia dos KVs", "item": "svc", "message": "linha1\nlinha2"})
        text = "\n".join(monitor.render(st, T0))
        self.assertIn("✖ O setup falhou depois de 1m35s (código 11).", text)
        self.assertIn("Etapa:  Aplicativos — A", text)
        self.assertIn("Tarefa: utils : Garantia dos KVs", text)
        self.assertIn("Item:   svc", text)
        self.assertIn("    linha2", text)
        self.assertNotIn("Ctrl+C", text)

    def test_success_and_interrupted(self):
        self.assertIn("✔ Setup concluído em 1h01m01s.",
                      "\n".join(monitor.render(dict(BASE, state="success", duration_s=3661), T0)))
        text = "\n".join(monitor.render(dict(BASE, state="failed", interrupted=True, rc=-15, duration_s=5), T0))
        self.assertIn("O setup interrompido", text)

    def test_fit_uses_visible_width_and_ignores_unknown_width(self):
        colored = "\033[1mKorp Setup · update · release/2025.1.0.x-performance-test\033[0m"
        self.assertEqual(monitor.fit([colored, "curta"], 0), [colored, "curta"])  # pty sem tamanho
        self.assertEqual(monitor.fit([colored], 80), [colored])  # cabe: os códigos de cor não contam
        cut = monitor.fit([colored], 20)[0]
        self.assertEqual(cut, "Korp Setup · update…")
        self.assertNotIn("\033", cut)

    def test_color_only_when_requested(self):
        self.assertIn("\033[32m", "\n".join(monitor.render(dict(BASE, state="success", duration_s=1), T0, color=True)))

    def test_exit_codes_from_status_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "status.json")
            for state, rc in (("success", 0), ("failed", monitor.EXIT_FAILED)):
                with open(path, "w") as f:
                    json.dump(dict(BASE, state=state, duration_s=1, runner_pid=os.getpid()), f)
                self.assertEqual(monitor.main(["--status", path]), rc)
            with open(path, "w") as f:
                json.dump(dict(BASE, state="running", runner_pid=99999999), f)
            self.assertEqual(monitor.main(["--status", path]), 1)  # processo morreu sem resultado
            self.assertEqual(monitor.main(["--status", path, "--run-id", "outra", "--wait", "1"]), 1)


class RunnerTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        j = lambda n: os.path.join(self.d.name, n)
        self.status, self.log, self.history, self.envf = j("status.json"), j("out.log"), j("h.jsonl"), j("run.env")
        self.junk = j("repo")
        os.mkdir(self.junk)
        with open(self.envf, "w") as f:
            f.write("ANSIBLE_COLLECTIONS_PATH=/opt/col\n")

    def tearDown(self):
        self.d.cleanup()

    def run_cmd(self, script, run_id="r1"):
        return runner.main(["--status", self.status, "--log", self.log, "--run-id", run_id, "--history", self.history,
                            "--env-file", self.envf, "--callback-dir", "/cb", "--meta", "tags=update",
                            "--meta", "branch=b", "--cleanup", self.junk, "--", sys.executable, "-c", script])

    def read(self, path):
        with open(path) as f:
            return f.read()

    def test_success_records_status_history_env_and_cleans(self):
        script = ("import os; print(os.environ['ANSIBLE_CALLBACKS_ENABLED'], os.environ['ANSIBLE_CALLBACK_PLUGINS'], "
                  "os.environ['ANSIBLE_COLLECTIONS_PATH'], os.environ['KORP_PROGRESS_FILE'].endswith('status.json'), "
                  "os.environ['LANG'], 'LC_TIME' in os.environ)")
        os.environ["LC_TIME"] = "pt_BR.UTF-8"
        try:
            self.assertEqual(self.run_cmd(script), 0)
        finally:
            os.environ.pop("LC_TIME")
        self.assertIn("korp_progress /cb /opt/col True C.UTF-8 False", self.read(self.log))
        st = json.loads(self.read(self.status))
        self.assertEqual((st["state"], st["rc"], st["tags"], st["branch"], st["run_id"]), ("success", 0, "update", "b", "r1"))
        self.assertFalse(os.path.exists(self.junk))
        h = [json.loads(x) for x in self.read(self.history).splitlines()]
        self.assertEqual((h[0]["rc"], h[0]["tags"]), (0, "update"))
        # a próxima execução com as mesmas tags recebe a duração da última
        self.run_cmd("pass", run_id="r2")
        self.assertEqual(json.loads(self.read(self.status))["last_run"]["duration_s"], h[0]["duration_s"])

    def test_failure_without_callback_uses_log_tail(self):
        self.assertEqual(self.run_cmd("import sys; print('ERROR! playbook inválido'); sys.exit(4)"), 4)
        st = json.loads(self.read(self.status))
        self.assertEqual((st["state"], st["rc"]), ("failed", 4))
        self.assertIn("ERROR! playbook inválido", st["error"]["message"])

    def test_keeps_error_written_by_callback(self):
        script = ("import json,os,sys; p=os.environ['KORP_PROGRESS_FILE']; d=json.load(open(p)); "
                  "d['error']={'message':'falha real'}; json.dump(d, open(p,'w')); sys.exit(2)")
        self.assertEqual(self.run_cmd(script), 2)
        self.assertEqual(json.loads(self.read(self.status))["error"]["message"], "falha real")

    def test_missing_command(self):
        rc = runner.main(["--status", self.status, "--log", self.log, "--run-id", "r", "--", "/nao/existe"])
        self.assertEqual(rc, 127)
        self.assertEqual(json.loads(self.read(self.status))["state"], "failed")


if __name__ == "__main__":
    unittest.main()
