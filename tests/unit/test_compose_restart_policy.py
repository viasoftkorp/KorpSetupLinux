"""Todo serviço dos composes do setup declara 'restart'.

Sem 'restart', o Docker não sobe o container de novo depois de um reboot ou de um restart do daemon: o container
fica parado até o próximo setup. Era o caso de temporal-elasticsearch (o temporal, com 'restart: always', voltava
sem o Elasticsearch) e de svix/redis_svix.
"""
import glob
import os
import unittest

import jinja2
import yaml

from _loader import REPO


class Placeholder(jinja2.ChainableUndefined):
    def __str__(self):
        return "indefinida"


class ComposeRestartPolicyTest(unittest.TestCase):
    def test_todo_servico_declara_restart(self):
        env = jinja2.Environment(undefined=Placeholder, trim_blocks=True)
        templates = sorted(glob.glob(os.path.join(REPO, "roles", "*", "templates", "composes", "**", "*.j2"),
                                     recursive=True))
        self.assertGreater(len(templates), 0)
        sem_restart = []
        for caminho in templates:
            with open(caminho) as f:
                compose = yaml.safe_load(env.from_string(f.read()).render())
            for servico, config in compose["services"].items():
                if "restart" not in config:
                    sem_restart.append("%s: %s" % (os.path.relpath(caminho, REPO), servico))
        self.assertEqual(sem_restart, [])


if __name__ == "__main__":
    unittest.main()
