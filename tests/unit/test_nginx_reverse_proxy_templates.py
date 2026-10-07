"""Proxy reverso externo: servidores HTTP do nginx e portas publicadas do container nginx.

Renderiza os templates como o módulo template do Ansible (trim_blocks, variável indefinida = erro).
No compose, só reverse_proxy, dns e https_port importam; as demais variáveis viram um texto fixo.
"""
import os
import unittest

import jinja2
import yaml

from _loader import REPO


class Placeholder(jinja2.ChainableUndefined):
    def __str__(self):
        return "indefinida"

NGINX = "roles/infrastructure/templates/configs/nginx/conf.d"
COMPOSE = "roles/infrastructure/templates/composes/infrastructure-compose.yml.j2"
PORTS = {"api": "9875", "cdn": "9876", "frontend": "9877", "dns_api_gateway": "9878"}
DNS = {"api": "korp-api.local", "cdn": "korp-cdn.local", "frontend": "korp.local", "api_gateway": "api.korp.local"}


def render(relpath, variables, strict=True):
    env = jinja2.Environment(
        undefined=jinja2.StrictUndefined if strict else Placeholder,
        trim_blocks=True, keep_trailing_newline=True)
    with open(os.path.join(REPO, relpath)) as f:
        return env.from_string(f.read()).render(**variables)


def reverse_proxy(external, http_ports=None):
    return {"external": external, "use_local_for_containers": True,
            "http_ports": dict(PORTS if http_ports is None else http_ports)}


def nginx_ports(external, dns=DNS, http_ports=None):
    rendered = render(COMPOSE, {"reverse_proxy": reverse_proxy(external, http_ports), "dns": dns,
                                "https_port": "443", "certs": {"certbot_automated": {"certificate": False}}},
                      strict=False)
    return [str(p) for p in yaml.safe_load(rendered)["services"]["nginx"]["ports"]]


class ApiGatewayServerTest(unittest.TestCase):
    def conf(self, external, http_ports=None):
        return render(f"{NGINX}/korp-api-gateway.conf.j2",
                      {"reverse_proxy": reverse_proxy(external, http_ports), "dns": DNS})

    def test_external_listens_on_inventory_port(self):
        conf = self.conf(True)
        self.assertIn("listen 9878;", conf)
        self.assertIn("include /etc/nginx/conf.d/korp-api-gateway.locations;", conf)
        self.assertIn("server_name api.korp.local;", conf)

    def test_external_custom_port(self):
        self.assertIn("listen 19878;", self.conf(True, dict(PORTS, dns_api_gateway="19878")))

    def test_external_inventory_without_port_uses_default(self):
        ports = {k: v for k, v in PORTS.items() if k != "dns_api_gateway"}
        self.assertIn("listen 9878;", self.conf(True, ports))

    def test_without_external_only_ssl_server(self):
        for external in (False, ""):
            conf = self.conf(external)
            self.assertNotIn("listen", conf)
            self.assertIn("server_name api.korp.local;", conf)

    def test_other_servers_unchanged(self):
        for name, key in (("korp", "frontend"), ("korp-api", "api"), ("korp-cdn", "cdn")):
            conf = render(f"{NGINX}/{name}.conf.j2", {"reverse_proxy": reverse_proxy(True), "dns": DNS})
            self.assertIn(f"listen {PORTS[key]};", conf)


class NginxPublishedPortsTest(unittest.TestCase):
    def test_external_with_api_gateway_publishes_its_port(self):
        self.assertEqual(nginx_ports(True), ["80:80", "443:443", "9875:9875", "9876:9876", "9877:9877", "9878:9878"])

    def test_external_without_api_gateway_dns(self):
        for api_gateway in ("", None):
            dns = dict(DNS, api_gateway=api_gateway)
            self.assertEqual(nginx_ports(True, dns), ["80:80", "443:443", "9875:9875", "9876:9876", "9877:9877"])
        dns = {k: v for k, v in DNS.items() if k != "api_gateway"}
        self.assertEqual(nginx_ports(True, dns), ["80:80", "443:443", "9875:9875", "9876:9876", "9877:9877"])

    def test_without_external_only_80_and_https(self):
        for external in (False, ""):
            self.assertEqual(nginx_ports(external), ["80:80", "443:443"])


if __name__ == "__main__":
    unittest.main()
