from pathlib import Path
import os
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / "qa-pr"


class QaPrCliTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(CLI.exists(), "qa-pr deve existir na raiz")
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.temp = Path(self.temp_dir.name)
        self.bin_dir = self.temp / "bin"
        self.bin_dir.mkdir()
        self.inventory = self.temp / "inventory.yml"
        self.inventory.write_text("all: {}\n")
        self.vault = self.temp / ".vault_key"
        self.vault.write_text("test\n")
        self.compose_root = self.temp / "composes"
        self.compose_root.mkdir()
        self.calls = self.temp / "calls"
        self._fake_command(
            "ansible-playbook",
            '#!/usr/bin/env bash\nprintf "%s\\n" "$@" >> "$QA_PR_FAKE_CALLS"\n',
        )
        self._fake_command("ansible-galaxy", "#!/usr/bin/env bash\nexit 0\n")
        self._fake_command("curl", "#!/usr/bin/env bash\nexit 0\n")
        self._fake_command(
            "docker",
            (
                "#!/usr/bin/env bash\n"
                'if [[ "${1:-}" == "ps" ]]; then\n'
                "  echo 'workflow|korp/workflow:pr330|330|sdk|running'\n"
                "fi\n"
            ),
        )
        self.environment = os.environ.copy()
        self.environment.update({
            "PATH": f"{self.bin_dir}:{self.environment['PATH']}",
            "QA_PR_FAKE_CALLS": str(self.calls),
            "QA_PR_INVENTORY": str(self.inventory),
            "QA_PR_VAULT_ID": str(self.vault),
            "QA_PR_COMPOSE_ROOT": str(self.compose_root),
            "QA_PR_LOG_DIR": str(self.temp / "logs"),
            "QA_PR_SUDO": "",
        })

    def _fake_command(self, name, content):
        path = self.bin_dir / name
        path.write_text(content)
        path.chmod(0o755)

    def _run(self, *arguments, input_text=None):
        return subprocess.run(
            [str(CLI), *arguments],
            cwd=ROOT,
            env=self.environment,
            input=input_text,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_apply_translates_url_and_policy_to_playbook(self):
        result = self._run(
            "apply",
            "https://github.com/viasoftkorp/sdk/pull/330",
            "--replace",
        )

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        call = self.calls.read_text()
        self.assertIn(str(ROOT / "pr-playbook.yml"), call)
        self.assertIn("prs=https://github.com/viasoftkorp/sdk/pull/330", call)
        self.assertIn("pr_conflict_policy=replace", call)

    def test_apply_rejects_non_korp_pull_request(self):
        result = self._run(
            "apply",
            "https://github.com/outra-org/sdk/pull/330",
        )

        self.assertNotEqual(0, result.returncode)
        self.assertIn("URL de PR inválida", result.stderr)
        self.assertFalse(self.calls.exists())

    def test_reset_requires_confirmation_and_supports_yes(self):
        cancelled = self._run("reset", input_text="nao\n")
        self.assertEqual(2, cancelled.returncode)
        self.assertFalse(self.calls.exists())

        accepted = self._run("reset", "--yes")
        self.assertEqual(0, accepted.returncode, accepted.stdout + accepted.stderr)
        self.assertIn(
            str(ROOT / "pr-reset-playbook.yml"),
            self.calls.read_text(),
        )

    def test_status_lists_override_and_labeled_container(self):
        override = (
            self.compose_root
            / "pr-overrides/pr330/workflow-compose.yml"
        )
        override.parent.mkdir(parents=True)
        override.write_text("services: {}\n")

        result = self._run("status")

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn(str(override), result.stdout)
        self.assertIn("workflow|korp/workflow:pr330|330|sdk|running", result.stdout)

    def test_doctor_checks_runtime_without_running_playbooks(self):
        result = self._run("doctor")

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn("Ambiente pronto", result.stdout)
        self.assertIn("[ok] API Harbor", result.stdout)
        self.assertFalse(self.calls.exists())


if __name__ == "__main__":
    unittest.main()
