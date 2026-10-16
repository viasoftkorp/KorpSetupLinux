"""KV Global depois de uma troca de domínio (ex.: autoassinado -> Let's Encrypt com domínios novos).

O setup só acrescentava chaves novas ao KV Global e sobrescrevia o RuntimeEnvironment: as URLs ficavam com o
domínio antigo (LegacyGateway, CdnUrl...) ou com um valor editado à mão (Authentication.Authority no domínio do
api-gateway, cujo fabio não tem a rota do discovery: os serviços em Go encerravam ao subir).
Renderiza global.json.j2 como o Ansible e aplica o merge de ensure_kv.yml com as chaves de main.yml.
"""
import json
import os
import unittest

import jinja2
import yaml

from _loader import REPO, load, load_module_utils

GLOBAL = "roles/infrastructure/templates/consul_kv/global.json.j2"
TAREFAS = "roles/infrastructure/tasks/main.yml"
URLS = ["LegacyGateway", "CORS", "FrontendUrl", "CdnUrl", "PublicGatewayUrl", "Authentication.Authority"]

ANTIGO = {"api": "korp-api.local", "cdn": "korp-cdn.local", "frontend": "korp.local", "api_gateway": "korp-api-gateway.local"}
NOVO = {"api": "portal-api.cliente.com.br", "cdn": "portal-cdn.cliente.com.br", "frontend": "portal.cliente.com.br",
        "api_gateway": "portal-api-gateway.cliente.com.br"}


class Placeholder(jinja2.ChainableUndefined):
    def __str__(self):
        return "indefinida"


def endpoints(dns):
    return {"gateway_url": f"https://{dns['api']}", "cdn_url": f"https://{dns['cdn']}",
            "frontend_url": f"https://{dns['frontend']}", "api_gateway_url": f"https://{dns['api_gateway']}"}


def render_global(dns, **extra):
    variables = {"dns": dns, "frontend": {"endpoints": endpoints(dns)}, "gateway_url": "https://gateway.korp.com.br",
                 "services_secrets": {"Global": {"MinioConfigGateway": {"EndPoint": "minio", "useSSL": "false"}}}}
    variables.update(extra)
    env = jinja2.Environment(undefined=Placeholder, trim_blocks=True, keep_trailing_newline=True)
    with open(os.path.join(REPO, GLOBAL)) as f:
        return json.loads(env.from_string(f.read()).render(**variables))


def chaves_sobrescritas():
    with open(os.path.join(REPO, TAREFAS)) as f:
        tarefa = next(t for t in yaml.safe_load(f) if t.get("name") == "Garantia de kv no consul para Global")
    return tarefa["vars"]["keys_to_overwrite"]


def valor(kv, caminho):
    for chave in caminho.split("."):
        kv = kv[chave]
    return kv


class CorsTest(unittest.TestCase):
    def setUp(self):
        self.cors = load("filter_plugins/korp_global_kv.py", "korp_global_kv").korp_global_cors

    def kv(self, cors, frontend="https://korp.local"):
        return {"CORS": cors, "FrontendUrl": frontend}

    def test_troca_de_dominio_substitui_a_origem_antiga(self):
        self.assertEqual(self.cors(self.kv("https://korp.local"), "https://portal.cliente.com.br"),
                         "https://portal.cliente.com.br")

    def test_mantem_origens_cadastradas_a_mao(self):
        self.assertEqual(self.cors(self.kv("https://korp.local, https://extra.cliente.com.br"),
                                   "https://portal.cliente.com.br"),
                         "https://portal.cliente.com.br,https://extra.cliente.com.br")

    def test_sem_troca_de_dominio_devolve_o_valor_atual(self):
        atual = "https://portal.cliente.com.br , https://extra.cliente.com.br"
        self.assertEqual(self.cors(self.kv(atual, "https://portal.cliente.com.br"), "https://portal.cliente.com.br"),
                         atual)

    def test_frontend_ausente_entra_primeiro(self):
        self.assertEqual(self.cors(self.kv("https://extra.cliente.com.br", "https://outro.local"),
                                   "https://portal.cliente.com.br"),
                         "https://portal.cliente.com.br,https://extra.cliente.com.br")

    def test_cors_vazio_ou_ausente(self):
        for kv in ({"CORS": "", "FrontendUrl": "https://korp.local"}, {}):
            self.assertEqual(self.cors(kv, "https://portal.cliente.com.br"), "https://portal.cliente.com.br")

    def test_sem_duplicar_quando_novo_e_antigo_ja_estao_cadastrados(self):
        self.assertEqual(self.cors(self.kv("https://korp.local,https://portal.cliente.com.br"),
                                   "https://portal.cliente.com.br"),
                         "https://portal.cliente.com.br")

    def test_curinga_fica_como_esta(self):
        self.assertEqual(self.cors(self.kv("*"), "https://portal.cliente.com.br"), "*")


class GlobalKvDnsChangeTest(unittest.TestCase):
    def setUp(self):
        self.merge = load_module_utils().merge_kv
        self.cors = load("filter_plugins/korp_global_kv.py", "korp_global_kv").korp_global_cors
        self.chaves = chaves_sobrescritas()

    def kv_atual(self):
        atual = render_global(ANTIGO)
        atual["Authentication"]["Authority"] = f"https://{ANTIGO['api_gateway']}/oauth"  # editado à mão
        atual["Authentication"]["IntrospectionSecret"] = "segredo-atual"
        atual["MinioConfig"]["AccessKeyID"] = "chave-atual"
        atual["CORS"] = "https://korp.local,https://extra.cliente.com.br"
        return atual

    def aplica(self, atual, dns):
        novo = render_global(dns, korp_global_cors=self.cors(atual, endpoints(dns)["frontend_url"]))
        return novo, self.merge(json.loads(json.dumps(atual)), novo, self.chaves)

    def test_chaves_de_url_sao_sobrescritas(self):
        self.assertIn("RuntimeEnvironment", self.chaves)
        for chave in URLS:
            self.assertIn(chave, self.chaves)

    def test_troca_de_dominio_atualiza_as_urls(self):
        novo, resultado = self.aplica(self.kv_atual(), NOVO)
        for chave in ["LegacyGateway", "FrontendUrl", "CdnUrl", "PublicGatewayUrl", "Authentication.Authority"]:
            self.assertEqual(valor(resultado, chave), valor(novo, chave), chave)
        self.assertEqual(resultado["Authentication"]["Authority"], "https://portal-api.cliente.com.br/oauth")
        self.assertEqual(resultado["CORS"], "https://portal.cliente.com.br,https://extra.cliente.com.br")
        self.assertNotIn(".local", json.dumps({c: valor(resultado, c) for c in URLS}))

    def test_troca_de_dominio_mantem_os_demais_valores(self):
        _, resultado = self.aplica(self.kv_atual(), NOVO)
        self.assertEqual(resultado["Authentication"]["IntrospectionSecret"], "segredo-atual")
        self.assertEqual(resultado["MinioConfig"]["AccessKeyID"], "chave-atual")

    def test_mesmo_dominio_corrige_authority_editada_a_mao(self):
        _, resultado = self.aplica(self.kv_atual(), ANTIGO)
        self.assertEqual(resultado["Authentication"]["Authority"], "https://korp-api.local/oauth")
        self.assertEqual(resultado["CORS"], "https://korp.local,https://extra.cliente.com.br")

    def test_kv_ja_correto_nao_muda(self):
        atual = render_global(NOVO)
        _, resultado = self.aplica(atual, NOVO)
        self.assertEqual(resultado, atual)

    def test_kv_inexistente_usa_o_frontend(self):
        self.assertEqual(render_global(NOVO)["CORS"], "https://portal.cliente.com.br")


if __name__ == "__main__":
    unittest.main()
