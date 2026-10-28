"""Desafio do Let's Encrypt nos servidores HTTPS e nas portas HTTP do proxy reverso externo do nginx.

O acme-challenge.conf só atende /.well-known/acme-challenge/ na porta 80. Atrás de um proxy que repassa ao servidor
em HTTPS (ex.: Azure Front Door), a validação chegava na 443, ia para o fabio (404) e a renovação falhava toda
noite até o certificado vencer. Renderiza os templates de conf.d como o módulo template do Ansible e, com Docker e
uma imagem do nginx já baixada, sobe o nginx com eles e faz as requisições.
"""
import glob
import os
import re
import shutil
import subprocess
import tempfile
import time
import unittest
import uuid

import jinja2

from _loader import REPO

NGINX = "roles/infrastructure/templates/configs/nginx"
SERVIDORES = {"korp": "frontend", "korp-api": "api", "korp-cdn": "cdn", "korp-api-gateway": "dns_api_gateway"}
PORTS = {"api": "9875", "cdn": "9876", "frontend": "9877", "dns_api_gateway": "9878"}
DNS = {"api": "korp-api.local", "cdn": "korp-cdn.local", "frontend": "korp.local", "api_gateway": "api.korp.local"}
DESAFIO = "/.well-known/acme-challenge/"


def variaveis(certbot, external):
    return {"certs": {"certbot_automated": {"certificate": certbot}}, "dns": DNS,
            "reverse_proxy": {"external": external, "use_local_for_containers": True, "http_ports": dict(PORTS)}}


def render(relpath, variables):
    env = jinja2.Environment(undefined=jinja2.StrictUndefined, trim_blocks=True, keep_trailing_newline=True)
    with open(os.path.join(REPO, relpath)) as f:
        return env.from_string(f.read()).render(**variables)


def blocos_server(conf):
    """Texto de cada bloco 'server { ... }' de primeiro nível."""
    blocos, profundidade, inicio = [], 0, None
    for m in re.finditer(r"server\s*\{|\{|\}", conf):
        if m.group(0) == "}":
            profundidade -= 1
            if profundidade == 0:
                blocos.append(conf[inicio:m.end()])
        else:
            if profundidade == 0:
                inicio = m.start()
            profundidade += 1
    return blocos


class AcmeChallengeTemplateTest(unittest.TestCase):
    def test_certbot_atende_o_desafio_em_todo_servidor(self):
        for external in (True, False):
            for nome in SERVIDORES:
                with self.subTest(servidor=nome, external=external):
                    blocos = blocos_server(render(f"{NGINX}/conf.d/{nome}.conf.j2", variaveis(True, external)))
                    self.assertEqual(len(blocos), 2 if external else 1)
                    for bloco in blocos:
                        self.assertIn("location ^~ " + DESAFIO + " {\n        root /letsencrypt/;", bloco)

    def test_sem_certbot_nada_muda(self):
        for nome in SERVIDORES:
            with self.subTest(servidor=nome):
                self.assertNotIn("acme-challenge", render(f"{NGINX}/conf.d/{nome}.conf.j2", variaveis(False, True)))


def docker_nginx_image():
    try:
        p = subprocess.run(["docker", "images", "--format", "{{.Repository}}:{{.Tag}}", "nginx"],
                           capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    imagens = [i for i in p.stdout.split() if i != "nginx:<none>"] if p.returncode == 0 else []
    return imagens[0] if imagens else None


IMAGEM = docker_nginx_image()


@unittest.skipUnless(IMAGEM, "Docker ou imagem do nginx indisponível")
class AcmeChallengeNginxTest(unittest.TestCase):
    """nginx de verdade com os arquivos renderizados (proxy reverso externo e certbot)."""

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        os.chmod(cls.dir, 0o755)
        conf_d = os.path.join(cls.dir, "conf.d")
        os.makedirs(conf_d)
        v = variaveis(True, True)
        for j2 in glob.glob(os.path.join(REPO, NGINX, "conf.d", "*.j2")):
            nome = os.path.basename(j2)[:-3]
            with open(os.path.join(conf_d, nome), "w") as f:
                f.write(render(os.path.relpath(j2, REPO), v))
        with open(os.path.join(cls.dir, "default_conf"), "w") as f:
            f.write(render(f"{NGINX}/default_conf.j2", v))
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1", "-subj", "/CN=teste",
                        "-keyout", os.path.join(cls.dir, "cert.key"), "-out", os.path.join(cls.dir, "cert.crt")],
                       check=True, capture_output=True, timeout=60)
        with open(os.path.join(cls.dir, "ssl_conf"), "w") as f:
            f.write("listen 443 ssl;\nssl_certificate /etc/nginx/certs/cert.crt;\n"
                    "ssl_certificate_key /etc/nginx/certs/cert.key;\n")
        desafio = os.path.join(cls.dir, "letsencrypt", DESAFIO.strip("/"))
        os.makedirs(desafio)
        # 'notification' testa o ^~: sem ele, o 'location ~ notification' do korp-api tomaria a requisição
        for token in ("token-teste", "notification-teste"):
            with open(os.path.join(desafio, token), "w") as f:
                f.write("conteudo-" + token)
        for raiz, dirs, arquivos in os.walk(cls.dir):
            for n in dirs:
                os.chmod(os.path.join(raiz, n), 0o755)
            for n in arquivos:
                os.chmod(os.path.join(raiz, n), 0o644)

        # os nomes dos upstreams precisam resolver para o nginx subir
        hosts = set()
        for arquivo in glob.glob(os.path.join(conf_d, "*")):
            with open(arquivo) as f:
                conf = f.read()
            hosts.update(re.findall(r"^\s*server ([A-Za-z][\w.-]*):\d+;", conf, re.M))
            hosts.update(h for h in re.findall(r"proxy_pass http://([A-Za-z][\w.-]*)(?::\d+)?;", conf)
                         if not h.endswith("_upstream"))
        cls.nome = "korp-teste-acme-" + uuid.uuid4().hex[:8]
        comando = ["docker", "run", "-d", "--name", cls.nome,
                   "-v", f"{cls.dir}/default_conf:/etc/nginx/default_conf:ro",
                   "-v", f"{cls.dir}/ssl_conf:/etc/nginx/ssl_conf:ro",
                   "-v", f"{conf_d}:/etc/nginx/conf.d:ro",
                   "-v", f"{cls.dir}:/etc/nginx/certs:ro",
                   "-v", f"{cls.dir}/letsencrypt:/letsencrypt:ro"]
        for h in sorted(hosts):
            comando += ["--add-host", f"{h}:127.0.0.1"]
        p = subprocess.run(comando + [IMAGEM], capture_output=True, text=True, timeout=120)
        if p.returncode != 0:
            shutil.rmtree(cls.dir, True)
            raise AssertionError(p.stderr)

    @classmethod
    def tearDownClass(cls):
        subprocess.run(["docker", "rm", "-f", cls.nome], capture_output=True, timeout=60)
        shutil.rmtree(cls.dir, True)

    def pedir(self, url, host):
        """Código HTTP e corpo, de dentro do container (sem publicar portas)."""
        comando = ["docker", "exec", self.nome, "curl", "-sk", "-H", f"Host: {host}", "-w", "\n%{http_code}", url]
        for _ in range(30):
            p = subprocess.run(comando, capture_output=True, text=True, timeout=30)
            if p.returncode == 0:
                corpo, _, codigo = p.stdout.rpartition("\n")
                return codigo, corpo
            time.sleep(1)  # nginx ainda subindo
        self.fail(f"sem resposta de {url}: {p.stderr}")

    def test_configuracao_valida(self):
        p = subprocess.run(["docker", "exec", self.nome, "nginx", "-t"], capture_output=True, text=True, timeout=60)
        self.assertEqual(p.returncode, 0, p.stderr)

    def test_desafio_nos_servidores_https(self):
        for nome, chave in SERVIDORES.items():
            host = DNS["api_gateway" if chave == "dns_api_gateway" else chave]
            for token in ("token-teste", "notification-teste"):
                with self.subTest(host=host, token=token):
                    self.assertEqual(self.pedir(f"https://127.0.0.1{DESAFIO}{token}", host),
                                     ("200", "conteudo-" + token))

    def test_desafio_nas_portas_do_proxy_externo(self):
        for chave, porta in PORTS.items():
            with self.subTest(porta=porta):
                self.assertEqual(self.pedir(f"http://127.0.0.1:{porta}{DESAFIO}token-teste", "qualquer"),
                                 ("200", "conteudo-token-teste"))

    def test_token_inexistente_nao_vai_para_os_servicos(self):
        # 404 do próprio nginx; sem o location, iria para o fabio (aqui inexistente: 502)
        self.assertEqual(self.pedir(f"https://127.0.0.1{DESAFIO}nao-existe", DNS["frontend"])[0], "404")


if __name__ == "__main__":
    unittest.main()
