"""Acesso ao Consul de fora do servidor só com o tenant (Basic), pelo nginx na porta 8500.

Os serviços Delphi mandam 'Basic ' + base64(tenantId + ':' + tenantId). Os containers usam consul-server:8500 pela
rede docker e o setup usa a porta local do consul-server (127.0.0.1:18500), os dois sem autenticação.

Renderiza os templates como o módulo template do Ansible e, com Docker e uma imagem do nginx já baixada, sobe o nginx
com o consul.conf na frente de um Consul falso e faz as requisições.
"""
import base64
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
import yaml

from _loader import REPO

try:
    from ansible.plugins.filter.core import to_bool
except ImportError:  # sem Ansible: mesma regra do filtro bool
    def to_bool(a):
        return a if isinstance(a, bool) else str(a).lower() in ("yes", "on", "1", "true")

COMPOSE = "roles/infrastructure/templates/composes/infrastructure-compose.yml.j2"
CONSUL_CONF = "roles/infrastructure/templates/configs/nginx/conf.d/consul.conf.j2"
LOCAL = 18500
TENANT = "0f8fad5b-d9cb-469f-a165-70867728950e"


class Placeholder(jinja2.ChainableUndefined):
    def __str__(self):
        return "indefinida"


def env(strict=True):
    e = jinja2.Environment(undefined=jinja2.StrictUndefined if strict else Placeholder, trim_blocks=True,
                           keep_trailing_newline=True)
    e.filters["bool"] = to_bool
    return e


def render(relpath, variables, strict=True):
    with open(os.path.join(REPO, relpath)) as f:
        return env(strict).from_string(f.read()).render(**variables)


def portas(basic_auth):
    compose = yaml.safe_load(render(COMPOSE, {"korp_consul_basic_auth": basic_auth, "korp_consul_local_port": LOCAL,
                                              "reverse_proxy": {"external": False}, "https_port": "443",
                                              "certs": {"certbot_automated": {"certificate": False}}},
                                    strict=False))
    return ([str(p) for p in compose["services"]["nginx"]["ports"]],
            [str(p) for p in compose["services"]["consul-server"]["ports"]])


def basic(usuario, senha):
    return "Basic " + base64.b64encode(f"{usuario}:{senha}".encode()).decode()


class ComposePortsTest(unittest.TestCase):
    def test_com_autenticacao_a_8500_e_do_nginx(self):
        nginx, consul = portas(True)
        self.assertIn("8500:8500", nginx)
        # nenhuma porta do Consul fica aberta para fora: nem a HTTP, nem RPC/gossip (8300/8301) e DNS (8600), que
        # deixariam contornar o nginx
        self.assertEqual(consul, [f"127.0.0.1:{LOCAL}:8500"])

    def test_sem_autenticacao_volta_ao_de_antes_mais_a_porta_local(self):
        nginx, consul = portas(False)
        self.assertNotIn("8500:8500", nginx)
        self.assertEqual(consul, [f"127.0.0.1:{LOCAL}:8500", "8300:8300", "8301:8301/tcp", "8301:8301/udp",
                                  "8500:8500", "8600:8600/tcp", "8600:8600/udp"])


class InventarioTest(unittest.TestCase):
    """Valor salvo de consul.basic_auth: ligado por padrão; o parâmetro do setup.sh, quando passado, substitui."""

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(REPO, "inventory-playbook.yml")) as f:
            texto = f.read()
        cls.expr = re.search(r"'consul': \{\s*'basic_auth': (.*?)\n\s*\},", texto, re.S).group(1)

    def valor(self, parametro, salvo=None):
        inventario = {} if salvo is None else {"consul": {"basic_auth": salvo}}
        e = env(strict=False)
        return e.from_string("{{ (%s) | string }}" % self.expr).render(
            custom_setup_info={"consul_basic_auth": parametro}, shrink_inventory=inventario)

    def test_padrao_ligado_inclusive_em_instalacao_existente(self):
        self.assertEqual(self.valor(""), "True")

    def test_sem_parametro_mantem_o_salvo(self):
        self.assertEqual(self.valor("", salvo=False), "False")
        self.assertEqual(self.valor("", salvo=True), "True")

    def test_so_false_desliga(self):
        for parametro in ("false", "FALSE", "False"):
            with self.subTest(parametro=parametro):
                self.assertEqual(self.valor(parametro, salvo=True), "False")
        for parametro in ("true", "sim", "1"):
            with self.subTest(parametro=parametro):
                self.assertEqual(self.valor(parametro, salvo=False), "True")


class PlaybookTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(os.path.join(REPO, "main.yml")) as f:
            cls.play = yaml.safe_load(f)[0]

    def efetivo(self, basic_auth, tenant):
        expr = self.play["vars"]["korp_consul_basic_auth"]
        variaveis = {"tenant_id": tenant}
        if basic_auth is not None:
            variaveis["consul"] = {"basic_auth": basic_auth}
        return env(strict=False).from_string(expr).render(**variaveis)

    def test_sem_tenant_nao_ha_como_autenticar(self):
        self.assertEqual(self.efetivo(True, TENANT), "True")
        self.assertEqual(self.efetivo(None, TENANT), "True")
        self.assertEqual(self.efetivo(True, ""), "False")
        self.assertEqual(self.efetivo(False, TENANT), "False")

    def test_setup_usa_a_porta_detectada_em_todo_acesso_ao_consul(self):
        porta = "{{ korp_consul_port | default(8500) }}"
        # 127.0.0.1: a porta local só existe em IPv4 (localhost pode resolver primeiro para ::1)
        self.assertEqual(self.play["module_defaults"]["community.general.consul_kv"],
                         {"host": "127.0.0.1", "port": porta})
        lotes = 0
        for arquivo in glob.glob(os.path.join(REPO, "roles", "**", "*.y*ml"), recursive=True):
            with open(arquivo) as f:
                tarefas = yaml.safe_load(f)
            for tarefa in percorrer(tarefas):
                with self.subTest(arquivo=os.path.relpath(arquivo, REPO), tarefa=tarefa.get("name")):
                    # consul_kv segue o module_defaults: nenhuma tarefa fixa host ou porta
                    if isinstance(tarefa.get("community.general.consul_kv"), dict):
                        self.assertFalse({"host", "port"} & set(tarefa["community.general.consul_kv"]))
                    # módulo da role, fora do alcance do module_defaults: recebe a porta na chamada
                    if isinstance(tarefa.get("korp_consul_kv_batch"), dict):
                        lotes += 1
                        self.assertEqual(tarefa["korp_consul_kv_batch"].get("port"), porta)
                        self.assertEqual(tarefa["korp_consul_kv_batch"].get("host"), "127.0.0.1")
        self.assertGreater(lotes, 0)

    def test_nenhum_acesso_fixo_a_8500_do_servidor(self):
        permitidos = {"roles/infrastructure/files/scripts/carga_inicial_elt.sh"}  # só como alternativa
        for arquivo in glob.glob(os.path.join(REPO, "roles", "**", "*"), recursive=True):
            if not os.path.isfile(arquivo) or os.path.relpath(arquivo, REPO) in permitidos:
                continue
            with open(arquivo, errors="replace") as f:
                texto = f.read()
            with self.subTest(arquivo=os.path.relpath(arquivo, REPO)):
                self.assertIsNone(re.search(r"(localhost|127\.0\.0\.1):8500", texto))


def percorrer(no):
    if isinstance(no, list):
        for item in no:
            yield from percorrer(item)
    elif isinstance(no, dict):
        yield no
        for chave in ("block", "rescue", "always"):
            if chave in no:
                yield from percorrer(no[chave])


class ConsulConfTemplateTest(unittest.TestCase):
    def test_conf(self):
        conf = render(CONSUL_CONF, {})
        self.assertIn("listen 8500;", conf)
        self.assertIn("auth_basic_user_file /etc/nginx/conf.d/consul.htpasswd;", conf)
        self.assertIn('proxy_set_header Authorization "";', conf)
        self.assertIn("proxy_read_timeout 11m;", conf)
        # o htpasswd fica em conf.d mas não pode ser lido como configuração (include conf.d/*.conf)
        self.assertFalse("consul.htpasswd".endswith(".conf"))


def docker_nginx_image():
    try:
        p = subprocess.run(["docker", "images", "--format", "{{.Repository}}:{{.Tag}}", "nginx"],
                           capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    imagens = [i for i in p.stdout.split() if i != "nginx:<none>"] if p.returncode == 0 else []
    return imagens[0] if imagens else None


IMAGEM = docker_nginx_image()

# Consul falso: devolve o que recebeu, para ver o que o nginx repassa
CONSUL_FALSO = """server {
    listen 8500;
    location / {
        default_type text/plain;
        return 200 "auth=[$http_authorization] uri=$request_uri";
    }
}
"""


def docker(*args, check=True, timeout=120):
    p = subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout)
    if check and p.returncode != 0:
        raise AssertionError(p.stderr)
    return p


@unittest.skipUnless(IMAGEM, "Docker ou imagem do nginx indisponível")
class ConsulNginxTest(unittest.TestCase):
    """nginx de verdade com o consul.conf renderizado e um Consul falso na rede docker."""

    @classmethod
    def setUpClass(cls):
        cls.id = uuid.uuid4().hex[:8]
        cls.rede = "korp-teste-consul-" + cls.id
        cls.nginx = "korp-teste-consul-nginx-" + cls.id
        cls.falso = "korp-teste-consul-falso-" + cls.id
        cls.dir = tempfile.mkdtemp()
        os.chmod(cls.dir, 0o755)
        conf_d = os.path.join(cls.dir, "conf.d")
        os.makedirs(conf_d)
        with open(os.path.join(conf_d, "consul.conf"), "w") as f:
            f.write(render(CONSUL_CONF, {}))
        # mesmo formato do community.general.htpasswd (apr_md5_crypt)
        hash_ = subprocess.run(["openssl", "passwd", "-apr1", TENANT], capture_output=True, text=True,
                               check=True, timeout=30).stdout.strip()
        with open(os.path.join(conf_d, "consul.htpasswd"), "w") as f:
            f.write(f"{TENANT}:{hash_}\n")
        falso_d = os.path.join(cls.dir, "falso")
        os.makedirs(falso_d)
        with open(os.path.join(falso_d, "default.conf"), "w") as f:
            f.write(CONSUL_FALSO)
        for raiz, dirs, arquivos in os.walk(cls.dir):
            for n in dirs:
                os.chmod(os.path.join(raiz, n), 0o755)
            for n in arquivos:
                os.chmod(os.path.join(raiz, n), 0o644)
        docker("network", "create", cls.rede)
        # o nginx sobe antes do Consul existir (resolver do docker a cada requisição)
        docker("run", "-d", "--name", cls.nginx, "--network", cls.rede, "-v", f"{conf_d}:/etc/nginx/conf.d:ro",
               IMAGEM)

    @classmethod
    def tearDownClass(cls):
        docker("rm", "-f", cls.nginx, cls.falso, check=False, timeout=60)
        docker("network", "rm", cls.rede, check=False, timeout=60)
        shutil.rmtree(cls.dir, True)

    def subir_consul_falso(self):
        if docker("ps", "-q", "--filter", f"name={self.falso}").stdout.strip():
            return
        docker("run", "-d", "--name", self.falso, "--network", self.rede, "--network-alias", "consul-server",
               "-v", f"{self.dir}/falso:/etc/nginx/conf.d:ro", IMAGEM)

    def pedir(self, caminho, autorizacao=None, esperar=None):
        """Código HTTP, cabeçalhos e corpo, de dentro do container do nginx."""
        comando = ["exec", self.nginx, "curl", "-s", "-i", "-o", "-", "-w", "\n%{http_code}"]
        if autorizacao:
            comando += ["-H", f"Authorization: {autorizacao}"]
        comando.append(f"http://127.0.0.1:8500{caminho}")
        for _ in range(30):
            p = docker(*comando, check=False, timeout=30)
            if p.returncode == 0:
                resposta, _, codigo = p.stdout.rpartition("\n")
                if esperar is None or codigo == esperar:
                    return codigo, resposta
            time.sleep(1)  # nginx ou Consul falso ainda subindo
        self.fail(f"sem resposta esperada de {caminho}: {p.stdout} {p.stderr}")

    def test_1_nginx_no_ar_sem_consul(self):
        self.assertEqual(docker("exec", self.nginx, "nginx", "-t", check=False).returncode, 0)
        self.assertEqual(self.pedir("/v1/kv/Global", basic(TENANT, TENANT), esperar="502")[0], "502")

    def test_2_tenant_do_servidor_passa_e_a_credencial_nao_chega_ao_consul(self):
        self.subir_consul_falso()
        codigo, resposta = self.pedir("/v1/kv/Global?raw=true&index=12&wait=5m", basic(TENANT, TENANT), esperar="200")
        self.assertEqual(codigo, "200")
        self.assertTrue(resposta.endswith("auth=[] uri=/v1/kv/Global?raw=true&index=12&wait=5m"), resposta)

    def test_3_sem_credencial_ou_outra_e_recusado(self):
        self.subir_consul_falso()
        codigo, resposta = self.pedir("/v1/kv/Global")
        self.assertEqual(codigo, "401")
        self.assertIn('WWW-Authenticate: Basic realm="Consul"', resposta)
        outro = "11111111-2222-3333-4444-555555555555"
        for autorizacao in (basic(outro, outro), basic(TENANT, outro), basic(TENANT.upper(), TENANT.upper()),
                            "Bearer " + TENANT):
            with self.subTest(autorizacao=autorizacao):
                self.assertEqual(self.pedir("/v1/kv/Global", autorizacao)[0], "401")
        self.assertEqual(self.pedir("/ui/", basic(TENANT, TENANT), esperar="200")[0], "200")

    def test_4_so_as_recusas_vao_para_o_log(self):
        self.subir_consul_falso()
        self.pedir("/v1/kv/log-aceito", basic(TENANT, TENANT), esperar="200")
        self.pedir("/v1/kv/log-recusado")
        log = ""
        for _ in range(10):
            p = docker("logs", self.nginx, check=False)
            log = p.stdout + p.stderr
            if "log-recusado" in log:
                break
            time.sleep(1)
        self.assertIn("log-recusado", log)
        self.assertNotIn("log-aceito", log)


if __name__ == "__main__":
    unittest.main()
