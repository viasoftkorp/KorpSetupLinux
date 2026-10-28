"""Containers que o watchtower atualiza: também os parados e os em loop de reinício.

Sem --include-restarting, um container preso reiniciando por causa de uma imagem com defeito ficava de fora da
atualização da noite e só saía do loop quando alguém rodava o setup, mesmo depois de publicada a imagem corrigida.
"""
import os
import unittest

import jinja2
import yaml

from _loader import REPO


class Placeholder(jinja2.ChainableUndefined):
    def __str__(self):
        return "indefinida"


class WatchtowerCommandTest(unittest.TestCase):
    def test_inclui_parados_e_reiniciando(self):
        env = jinja2.Environment(undefined=Placeholder, trim_blocks=True)
        with open(os.path.join(REPO, "roles/infrastructure/templates/composes/infrastructure-compose.yml.j2")) as f:
            compose = yaml.safe_load(env.from_string(f.read()).render())
        flags = compose["services"]["watchtower"]["command"].split()
        for flag in ("--include-stopped", "--include-restarting", "--revive-stopped", "--cleanup"):
            self.assertIn(flag, flags)


if __name__ == "__main__":
    unittest.main()
