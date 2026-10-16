"""Troca de certificado autoassinado/customizado para Let's Encrypt num servidor que já está no ar.

O ssl_conf passava a apontar para o certificado do certbot antes de ele existir: o nginx reiniciado não subia,
a porta 80 ficava fechada e a validação http-01 do certbot falhava (Connection refused). Agora o nginx continua
com o certificado anterior até o certbot.yml emitir o novo e gravar o ssl_conf definitivo.
"""
import os
import unittest

import jinja2
import yaml
from ansible.plugins.filter.core import FilterModule

from _loader import REPO

SSL_CONF = "roles/infrastructure/templates/configs/nginx/ssl_conf.j2"
ARQUIVOS = "roles/infrastructure/tasks/files_and_folders_setup.yml"
CERTBOT = "roles/infrastructure/tasks/certbot.yml"
LE = "ssl_certificate /etc/nginx/certs/letsencrypt/live/portal-local.korp.com.br/fullchain.pem;"
ANTERIOR = "ssl_certificate     /etc/nginx/certs/cert.crt;"
SENHA = "ssl_password_file   /etc/nginx/certs/cert.pass;"


def ssl_conf(certbot=False, self_signed=False, custom_pass=False, **facts):
    variables = {"http_use_secure_only_tls_protocols": True, "certbot_cert_name": "portal-local.korp.com.br",
                 "certs": {"certbot_automated": {"certificate": certbot}, "self_signed": {"certificate": self_signed},
                           "custom": {"certificate": not (certbot or self_signed), "has_pass_file": custom_pass}}}
    variables.update(facts)
    env = jinja2.Environment(undefined=jinja2.StrictUndefined, trim_blocks=True, keep_trailing_newline=True)
    env.filters.update(FilterModule().filters())
    with open(os.path.join(REPO, SSL_CONF)) as f:
        return env.from_string(f.read()).render(**variables)


def tarefas(relpath):
    with open(os.path.join(REPO, relpath)) as f:
        return yaml.safe_load(f)


def nomes(lista):
    saida = []
    for t in lista:
        saida.append(t.get("name"))
        saida.extend(nomes(t.get("block", [])))
    return saida


def tarefa(lista, nome):
    for t in lista:
        if t.get("name") == nome:
            return t
        achada = tarefa(t.get("block", []), nome)
        if achada:
            return achada
    return None


class SslConfTest(unittest.TestCase):
    def test_certbot_com_certificado_emitido(self):
        conf = ssl_conf(certbot=True)
        self.assertIn(LE, conf)
        self.assertNotIn("cert.crt", conf)
        self.assertEqual(conf, ssl_conf(certbot=True, nginx_ssl_conf_transicao=False))

    def test_troca_para_certbot_mantem_certificado_anterior(self):
        conf = ssl_conf(certbot=True, nginx_ssl_conf_transicao=True, nginx_ssl_conf_transicao_senha=True)
        self.assertIn(ANTERIOR, conf)
        self.assertIn("ssl_certificate_key /etc/nginx/certs/cert.key;", conf)
        self.assertIn(SENHA, conf)
        self.assertNotIn("letsencrypt", conf)

    def test_troca_para_certbot_sem_senha(self):
        conf = ssl_conf(certbot=True, nginx_ssl_conf_transicao=True, nginx_ssl_conf_transicao_senha=False)
        self.assertIn(ANTERIOR, conf)
        self.assertNotIn("cert.pass", conf)

    def test_fatos_como_texto(self):
        """Com o templating antigo do Ansible, o set_fact pode devolver 'False'/'True' como texto."""
        self.assertIn(LE, ssl_conf(certbot=True, nginx_ssl_conf_transicao="False"))
        self.assertIn(ANTERIOR, ssl_conf(certbot=True, nginx_ssl_conf_transicao="True",
                                         nginx_ssl_conf_transicao_senha="False"))

    def test_autoassinado_e_customizado_sem_mudanca(self):
        self.assertIn(SENHA, ssl_conf(self_signed=True, nginx_ssl_conf_transicao=True))
        self.assertIn(ANTERIOR, ssl_conf(custom_pass=False))
        self.assertNotIn("cert.pass", ssl_conf(custom_pass=False))
        self.assertIn(SENHA, ssl_conf(custom_pass=True))


class TarefasTest(unittest.TestCase):
    def test_verifica_certificados_antes_do_ssl_conf(self):
        lista = tarefas(ARQUIVOS)
        ordem = nomes(lista)
        stat = tarefa(lista, "Verificação dos certificados para o ssl_conf do nginx")
        self.assertIsNotNone(stat)
        caminhos = " ".join(stat["loop"])
        for arquivo in ("letsencrypt/live/{{ certbot_cert_name }}/fullchain.pem", "/cert.crt", "/cert.key", "/cert.pass"):
            self.assertIn(arquivo, caminhos)
        self.assertTrue(stat["ansible.builtin.stat"].get("follow"))
        self.assertLess(ordem.index("Verificação dos certificados para o ssl_conf do nginx"),
                        ordem.index("Configuração de ssl_conf do nginx"))
        self.assertLess(ordem.index("Definição do certificado do ssl_conf na troca para o Let's Encrypt"),
                        ordem.index("Configuração de ssl_conf do nginx"))

    def test_nginx_reinicia_com_acme_challenge(self):
        """O nginx precisa carregar o acme-challenge.conf (porta 80) antes do certbot validar."""
        lista = tarefas(ARQUIVOS)
        ordem = nomes(lista)
        self.assertLess(ordem.index("Configuração e transferência de arquivo 'acme-challenge'"),
                        ordem.index("Reinício do container nginx"))
        quando = tarefa(lista, "Reinício do container nginx")["when"]
        self.assertIn("nginx_ssl_conf_status is changed", quando)
        self.assertIn("nginx_acme_challenge_status is changed", quando)

    def test_certbot_grava_ssl_conf_definitivo_e_reinicia(self):
        lista = tarefas(CERTBOT)
        ordem = nomes(lista)
        fato = tarefa(lista, "Definição do ssl_conf com o certificado do Let's Encrypt")
        self.assertIs(fato["ansible.builtin.set_fact"]["nginx_ssl_conf_transicao"], False)
        conf = tarefa(lista, "Configuração de ssl_conf do nginx com o certificado do Let's Encrypt")
        self.assertEqual(conf["ansible.builtin.template"]["src"], "configs/nginx/ssl_conf.j2")
        self.assertLess(ordem.index("Criação de certificado pelo Certbot"),
                        ordem.index("Definição do ssl_conf com o certificado do Let's Encrypt"))
        self.assertLess(ordem.index("Configuração e transferência de arquivos de nginx"),
                        ordem.index("Reinício do container nginx com o certificado do Let's Encrypt"))
        # o ssl_conf é montado como arquivo: o template troca o inode e só um reinício do container enxerga o novo
        reinicio = tarefa(lista, "Reinício do container nginx com o certificado do Let's Encrypt")
        self.assertEqual(reinicio["ansible.builtin.import_tasks"], "nginx_restart.yml")
        self.assertEqual(reinicio["when"], "nginx_ssl_conf_certbot_status is changed")
        self.assertEqual(tarefa(lista, "Reload de nginx")["when"],
                         "nginx_files_status is changed and nginx_ssl_conf_certbot_status is not changed")


if __name__ == "__main__":
    unittest.main()
