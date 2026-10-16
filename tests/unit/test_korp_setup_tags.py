import os
import subprocess
import sys
import unittest

from _loader import REPO, load

tags = load("scripts/korp_setup_tags.py", "korp_setup_tags")
SCRIPT = os.path.join(REPO, "scripts", "korp_setup_tags.py")


def run(texto, repo=REPO):
    p = subprocess.run([sys.executable, SCRIPT, repo, texto], capture_output=True, text=True, timeout=60)
    return p.returncode, p.stdout + p.stderr


class SetupTagsTest(unittest.TestCase):
    def test_repository_tags_include_the_setup_tags(self):
        existentes = tags.tags_do_repositorio(REPO)
        for t in ("default-setup", "install", "install-only", "update", "update-only", "update-versioned",
                  "install-versioned-only", "remove-apps", "uninstall-version", "provisioning", "infrastructure",
                  "infrastructure-web", "infrastructure-desktop", "finishing"):
            self.assertIn(t, existentes)

    def test_valid_tags_pass(self):
        for texto in ("default-setup,install", "update", "update-versioned", "all", "infrastructure-web, finishing"):
            self.assertEqual(run(texto)[0], 0, texto)

    def test_unknown_tag_stops_with_suggestion(self):
        rc, out = run("update_versioned")
        self.assertEqual(rc, 3)
        self.assertIn("'update-versioned'", out)
        rc, out = run("instal,update")
        self.assertEqual(rc, 3)
        self.assertIn("'install'", out)
        self.assertNotIn("'update' não existe", out)

    def test_validator_failure_does_not_block(self):
        rc, out = run("update", repo="/caminho/que/nao/existe")
        self.assertEqual(rc, 0)
        self.assertIn("Aviso", out)


if __name__ == "__main__":
    unittest.main()
