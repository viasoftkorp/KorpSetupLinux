"""Retirada genérica de composes que sobraram de uma reorganização das roles (korp_compose_obsoletos).

Caso real: na 2025.1 o logistica-compose.yml da raiz foi dividido em logistica-saldo, produto, ajuste-estoque e
inventario. Nenhuma role gera mais o arquivo antigo, ele ficava nos servidores duplicando serviços e o qa-pr parava
em "Esperado um compose para ...; encontrados 2". Onde ajuste-estoque e inventario ainda não estavam instalados, o
arquivo antigo era a única definição dos dois *.Background e não podia sair.
"""
import json
import os
import shutil
import subprocess
import tempfile
import textwrap
import unittest

import yaml

from _loader import REPO, load

mod = load("roles/utils/library/korp_compose_obsoletos.py", "korp_compose_obsoletos")


def write(path, text=""):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(textwrap.dedent(text))


def compose(**servicos):
    """Compose com os serviços informados: nome=container_name (ou None, sem container_name)."""
    return yaml.safe_dump({"services": {s: ({"image": "x/" + s} if c is None else {"image": "x/" + s,
                                                                                  "container_name": c})
                                        for s, c in servicos.items()}})


class Fixture(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)
        self.roles = os.path.join(self.dir, "roles")
        self.composes = os.path.join(self.dir, "composes")
        self.backup = os.path.join(self.dir, "backups")
        # roles do repositório: o que cada uma gera hoje
        for role in ("logistica-saldo", "produto", "ajuste-estoque", "inventario", "wms"):
            write(f"{self.roles}/{role}/templates/composes/{role}-compose.yml.j2")
        write(f"{self.roles}/LOG103/templates/composes/2025.1.0/LOG103-compose.yml.j2")
        write(f"{self.roles}/wms/templates/composes/2025.1.0/wms-compose.yml.j2")

    def servidor(self, relpath, conteudo):
        write(os.path.join(self.composes, relpath), conteudo)

    def logistica_dividida(self, com_ajuste_e_inventario=True):
        self.servidor("logistica-saldo-compose.yml", compose(**{"korp-logistica-saldo": "Saldo-2025.1.0"}))
        self.servidor("produto-compose.yml", compose(**{"korp-logistica-produto": "Produto-2025.1.0"}))
        if com_ajuste_e_inventario:
            self.servidor("ajuste-estoque-compose.yml", compose(**{"ajuste-background": "AjusteEstoque.Background"}))
            self.servidor("inventario-compose.yml", compose(**{"inventario-background": "Inventario.Background"}))
        self.servidor("logistica-compose.yml", compose(**{
            "korp-logistica-saldo": "Saldo-2025.1.0", "korp-logistica-produto": "Produto-2025.1.0",
            "ajuste-background": "AjusteEstoque.Background", "inventario-background": "Inventario.Background"}))

    def plano(self, versao="2025.1.0", mais_nova=None):
        return mod.plano(self.composes, self.roles, versao, mais_nova)


class PlanoTest(Fixture):
    def test_arquivo_dividido_e_obsoleto(self):
        self.logistica_dividida()
        obsoletos, mantidos, ilegiveis = self.plano()
        self.assertEqual([o["arquivo"] for o in obsoletos], [os.path.join(self.composes, "logistica-compose.yml")])
        self.assertEqual(obsoletos[0]["servicos"], ["ajuste-background", "inventario-background",
                                                    "korp-logistica-produto", "korp-logistica-saldo"])
        self.assertEqual((mantidos, ilegiveis), ([], []))

    def test_unica_definicao_de_um_servico_fica(self):
        self.logistica_dividida(com_ajuste_e_inventario=False)
        obsoletos, mantidos, _ = self.plano()
        self.assertEqual(obsoletos, [])
        self.assertEqual(mantidos, [{"arquivo": os.path.join(self.composes, "logistica-compose.yml"),
                                     "so_nele": ["ajuste-background", "inventario-background"]}])

    def test_mesmo_container_com_outro_nome_de_servico_conta_como_definido(self):
        self.servidor("produto-compose.yml", compose(**{"produto-core": "Produto-2025.1.0"}))
        self.servidor("logistica-compose.yml", compose(**{"korp-logistica-produto": "Produto-2025.1.0"}))
        self.assertEqual(len(self.plano()[0]), 1)

    def test_orfaos_que_se_cobrem_entre_si_ficam(self):
        # só um compose atual conta como definição: dois órfãos iguais não justificam retirar nenhum
        self.servidor("wms-compose.yml", compose(outro=None))
        self.servidor("antigo-a-compose.yml", compose(svc="Svc"))
        self.servidor("antigo-b-compose.yml", compose(svc="Svc"))
        obsoletos, mantidos, _ = self.plano()
        self.assertEqual(obsoletos, [])
        self.assertEqual(len(mantidos), 2)

    def test_pasta_de_versao(self):
        self.servidor("2025.1.0/wms-compose.yml", compose(conferenciasaida="ConferenciaSaida-2025.1.0"))
        self.servidor("2025.1.0/LOG103-compose.yml", compose(log103="LOG103-2025.1.0"))
        self.servidor("2025.1.0/LOG103-antigo-compose.yml", compose(conferenciasaida="ConferenciaSaida-2025.1.0"))
        obsoletos, _, _ = self.plano()
        self.assertEqual([o["arquivo"] for o in obsoletos],
                         [os.path.join(self.composes, "2025.1.0", "LOG103-antigo-compose.yml")])

    def test_compose_atual_duplicado_nao_e_mexido(self):
        # LOG103 e wms ainda são gerados: a duplicidade entre os dois não é desta regra
        self.servidor("2025.1.0/wms-compose.yml", compose(conferenciasaida="ConferenciaSaida-2025.1.0"))
        self.servidor("2025.1.0/LOG103-compose.yml", compose(conferenciasaida="ConferenciaSaida-2025.1.0"))
        self.assertEqual(self.plano(), ([], [], []))

    def test_pasta_de_outra_versao_fica_com_o_setup_dela(self):
        for versao in ("2024.2.0", "2025.2.0"):
            self.servidor(f"{versao}/wms-compose.yml", compose(svc="Svc"))
            self.servidor(f"{versao}/velho-compose.yml", compose(svc="Svc"))
        write(f"{self.roles}/wms/templates/composes/2024.2.0/wms-compose.yml.j2")
        write(f"{self.roles}/wms/templates/composes/2025.2.0/wms-compose.yml.j2")
        self.assertEqual(self.plano(), ([], [], []))
        self.assertEqual([o["arquivo"] for o in self.plano("2024.2.0")[0]],
                         [os.path.join(self.composes, "2024.2.0", "velho-compose.yml")])

    def test_pasta_compartilhada_so_com_a_versao_mais_nova(self):
        # 2024.2 e 2025.1 no mesmo servidor: a 2024.2 ainda gera o logistica-compose.yml que a 2025.1 dividiu
        self.logistica_dividida()
        self.assertEqual(self.plano("2024.2.0", mais_nova="2025.1.0"), ([], [], []))
        self.assertEqual(len(self.plano("2025.1.0", mais_nova="2025.1.0")[0]), 1)
        self.assertEqual(len(self.plano("2025.1.0", mais_nova="2024.2.0")[0]), 1)

    def test_pastas_que_nao_sao_de_versao_sao_ignoradas(self):
        self.servidor("wms-compose.yml", compose(svc="Svc"))
        self.servidor("pr-overrides/pr1/logistica-compose.yml", compose(svc="Svc"))
        self.assertEqual(self.plano(), ([], [], []))

    def test_arquivo_ilegivel_fica(self):
        self.servidor("wms-compose.yml", compose(svc="Svc"))
        self.servidor("antigo-compose.yml", "services: [\n")
        self.assertEqual(self.plano(), ([], [], [os.path.join(self.composes, "antigo-compose.yml")]))

    def test_outros_arquivos_da_pasta_sao_ignorados(self):
        self.servidor("wms-compose.yml", compose(svc="Svc"))
        self.servidor(".env", "A=1\n")
        self.servidor("antigo-compose.yml.bak", compose(svc="Svc"))
        self.assertEqual(self.plano(), ([], [], []))


class VersaoMaisNovaTest(Fixture):
    def instalados(self, texto):
        write(os.path.join(self.dir, "installed_apps.yml"), texto)
        return mod.versao_mais_nova_instalada(os.path.join(self.dir, "installed_apps.yml"))

    def test_maior_versao_com_aplicativos(self):
        self.assertEqual(self.instalados("""\
            unversioned: [base]
            versioned:
              2024.2.0: [ERP]
              2025.1.0: [ERP, LOG103]
              2023.1.0: [ERP]
            """), "2025.1.0")

    def test_versao_com_lista_vazia_nao_conta(self):
        # chave vazia que sobrou de um piloto (ex.: 2025.2.0: []) não faz a 2025.1 perder a pasta compartilhada
        self.assertEqual(self.instalados("versioned:\n  2025.1.0: [ERP]\n  2025.2.0: []\n"), "2025.1.0")

    def test_sem_versionados_ou_sem_arquivo(self):
        self.assertIsNone(self.instalados("unversioned: [base]\nversioned:\n"))
        self.assertIsNone(mod.versao_mais_nova_instalada(os.path.join(self.dir, "nao-existe.yml")))
        self.assertIsNone(mod.versao_mais_nova_instalada(None))

    def test_compara_numeros_nao_texto(self):
        self.assertEqual(self.instalados("versioned:\n  2025.10.0: [A]\n  2025.9.0: [B]\n"), "2025.10.0")


class RetirarTest(Fixture):
    def test_move_para_o_backup_com_leiame(self):
        self.logistica_dividida()
        self.servidor("2025.1.0/wms-compose.yml", compose(c="C"))
        self.servidor("2025.1.0/velho-compose.yml", compose(c="C"))
        antes = {}
        for rel in ("logistica-compose.yml", "2025.1.0/velho-compose.yml"):
            with open(os.path.join(self.composes, rel)) as f:
                antes[rel] = f.read()
        obsoletos, _, _ = self.plano()
        destino = mod.retirar(obsoletos, self.composes, self.backup, agora=0)
        for rel, conteudo in antes.items():
            self.assertFalse(os.path.exists(os.path.join(self.composes, rel)))
            with open(os.path.join(destino, rel)) as f:
                self.assertEqual(f.read(), conteudo)
        with open(os.path.join(destino, "LEIAME.txt")) as f:
            leiame = f.read()
        self.assertIn("desfazer: mv %s %s" % (os.path.join(destino, "logistica-compose.yml"),
                                             os.path.join(self.composes, "logistica-compose.yml")), leiame)
        # os atuais continuam
        for rel in ("logistica-saldo-compose.yml", "produto-compose.yml", "2025.1.0/wms-compose.yml"):
            self.assertTrue(os.path.exists(os.path.join(self.composes, rel)))
        self.assertEqual(self.plano(), ([], [], []))


def ansible_available():
    try:
        return subprocess.run(["ansible-playbook", "--version"], capture_output=True, stdin=subprocess.DEVNULL,
                              timeout=60).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


@unittest.skipUnless(ansible_available(), "ansible-playbook indisponível")
class TarefaAnsibleTest(Fixture):
    """roles/utils/tasks/default/obsolete_composes.yml de verdade (sem become, num diretório temporário)."""

    def run_play(self, *extra_args):
        play = os.path.join(self.dir, "play.yml")
        tarefas = os.path.join(REPO, "roles/utils/tasks/default/obsolete_composes.yml")
        with open(play, "w") as f:
            yaml.safe_dump([{"hosts": "localhost", "connection": "local", "gather_facts": False,
                             "tasks": [{"ansible.builtin.include_tasks": tarefas}]}], f)
        variaveis = {"compose_dir_path": self.composes, "korp_dir_path": self.dir, "config_dir_path": self.dir,
                     "version_without_build": "2025.1.0", "ansible_become": False}
        env = dict(os.environ, ANSIBLE_NOCOLOR="1", ANSIBLE_LOCALHOST_WARNING="false", HOME=self.dir,
                   ANSIBLE_INVENTORY_UNPARSED_WARNING="false", ANSIBLE_RETRY_FILES_ENABLED="false",
                   ANSIBLE_LIBRARY=os.path.join(REPO, "roles/utils/library"))
        # playbook_dir aponta para self.dir: as roles do teste ficam em self.dir/roles
        p = subprocess.run(["ansible-playbook", "-i", "localhost,", play, "-e", json.dumps(variaveis)] +
                           list(extra_args), cwd=self.dir, env=env, capture_output=True, text=True,
                           stdin=subprocess.DEVNULL, timeout=300)
        return p.returncode, p.stdout + p.stderr

    def test_retira_e_avisa(self):
        self.logistica_dividida()
        self.servidor("2025.1.0/wms-compose.yml", compose(c="C"))
        self.servidor("2025.1.0/velho-compose.yml", compose(so_nele="SoNele"))
        rc, out = self.run_play()
        self.assertEqual(rc, 0, out)
        self.assertFalse(os.path.exists(os.path.join(self.composes, "logistica-compose.yml")))
        self.assertTrue(os.path.exists(os.path.join(self.composes, "2025.1.0", "velho-compose.yml")))
        self.assertIn("movido(s) para", out)
        self.assertIn("é a única definição de so_nele", " ".join(out.split()))
        rc, out = self.run_play()
        self.assertEqual(rc, 0, out)
        self.assertIn("changed=0", out)

    def test_check_mode_nao_move(self):
        self.logistica_dividida()
        rc, out = self.run_play("--check")
        self.assertEqual(rc, 0, out)
        self.assertTrue(os.path.exists(os.path.join(self.composes, "logistica-compose.yml")))
        self.assertFalse(os.path.exists(self.backup))


if __name__ == "__main__":
    unittest.main()
