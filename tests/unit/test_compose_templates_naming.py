"""Nome dos templates de compose das roles de aplicativo.

services/gather_info.yml (e install_versioned_only.yml) só procura 'roles/<id>/templates/composes/<id>-compose.yml.j2'
e '.../composes/<versão>/<id>-compose.yml.j2'. Um template com outro nome nunca é gravado nem iniciado: foi assim
que, ao trocar 'logistica' por 'logistica-saldo', Korp.Logistic.Tracking e Korp.Logistica.SaldoProdutos deixaram
de ser instalados (o compose versionado continuou 'logistica-compose.yml.j2').
"""
import glob
import os
import unittest

import yaml

from _loader import REPO

# infrastructure-web grava os próprios composes (todos os templates de composes/)
FORA = {"infrastructure-web"}


def ids_de_add_service(role):
    ids = set()
    for tasks in glob.glob(os.path.join(REPO, "roles", role, "tasks", "*.yml")):
        with open(tasks) as f:
            conteudo = yaml.safe_load(f) or []
        for task in conteudo:
            inc = task.get("ansible.builtin.include_role") or task.get("include_role") or {}
            if inc.get("tasks_from") == "services/add_service":
                ids.add((task.get("vars") or {}).get("id"))
    return ids


class ComposeTemplatesNamingTest(unittest.TestCase):
    def test_templates_tem_o_nome_do_id_da_role(self):
        erros = []
        for role in sorted(os.listdir(os.path.join(REPO, "roles"))):
            # só as roles que cadastram serviços com o próprio nome como id (o caso de todo aplicativo)
            if role not in ids_de_add_service(role) or role in FORA:
                continue
            composes = os.path.join(REPO, "roles", role, "templates", "composes")
            for t in glob.glob(os.path.join(composes, "*.j2")) + glob.glob(os.path.join(composes, "*", "*.j2")):
                if os.path.basename(t) != role + "-compose.yml.j2":
                    erros.append(os.path.relpath(t, REPO))
        self.assertEqual(erros, [])

    def test_logistica_saldo_tem_tracking_e_saldoprodutos_versionados(self):
        caminho = os.path.join(REPO, "roles/logistica-saldo/templates/composes/2025.1.0/logistica-saldo-compose.yml.j2")
        with open(caminho) as f:
            conteudo = f.read()
        self.assertIn('container_name: "Korp.Logistic.Tracking-2025.1.0"', conteudo)
        self.assertIn('container_name: "Korp.Logistica.SaldoProdutos-2025.1.0"', conteudo)


if __name__ == "__main__":
    unittest.main()
