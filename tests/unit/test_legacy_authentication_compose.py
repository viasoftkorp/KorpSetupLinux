"""Korp.Legacy.Authentication no compose compartilhado do infrastructure-desktop (DEVO-7740).

Ele ficava num compose versionado por versão (roles/infrastructure-desktop/templates/composes/<versão>/), sozinho.
Os dois (2024.2 e 2025.1) se registram no fabio com a mesma rota, então a versão não separava nada. Agora há um só,
o da versão do setup, no compose compartilhado, como no infrastructure-setup-dev.

Nos servidores que já têm o container, o setup troca de projeto compose com a migração de reconciled_compose_up.yml
(container com o mesmo nome em outro projeto): ela só aceita como antecessor um container com o mesmo nome, a mesma
imagem sem a tag e sem volume anônimo.
"""
import glob
import os
import unittest

import jinja2
import yaml

from _loader import REPO, load

batch = load("filter_plugins/korp_setup_batch.py", "korp_setup_batch")

ROLE = os.path.join(REPO, "roles", "infrastructure-desktop")
COMPARTILHADO = os.path.join(ROLE, "templates", "composes", "infrastructure-desktop-compose.yml.j2")
VERSOES = ("2024.2.0", "2025.1.0", "2025.2.0")


def renderizar(versao):
    env = jinja2.Environment(undefined=jinja2.StrictUndefined, trim_blocks=True)
    with open(COMPARTILHADO) as f:
        texto = env.from_string(f.read()).render(
            version_without_build=versao, docker_account="korp", docker_image_suffix="",
            containers_cert_path="/etc/korp/certs/ca.crt", certs_directory="/etc/korp/certs",
            dados_docker_dir_path="/etc/korp/dados-docker", korp_dir_path="/etc/korp",
            dns={"api": "api.local", "frontend": "frontend.local", "cdn": "cdn.local", "api_gateway": ""})
    return yaml.safe_load(texto)["services"]


class LegacyAuthenticationComposeTest(unittest.TestCase):
    def test_sem_compose_versionado(self):
        self.assertEqual(glob.glob(os.path.join(ROLE, "templates", "composes", "*", "*")), [])

    def test_no_compose_compartilhado_com_a_versao_do_setup(self):
        for versao in VERSOES:
            with self.subTest(versao=versao):
                servico = renderizar(versao)["korp-legacy-authentication"]
                # mesmo nome e mesma imagem (sem a tag) do container do compose versionado: é o que a migração
                # de projeto compose exige para tratar o container existente como antecessor
                self.assertEqual(servico["container_name"], "Korp.Legacy.Authentication-" + versao)
                self.assertEqual(servico["image"], "korp/korp.legacy.authentication:%s.x" % versao)
                self.assertEqual(servico["restart"], "always")
                self.assertEqual(servico["networks"], ["servicos"])
                self.assertEqual(servico["environment"], [
                    "ON_PREMISE_MODE=true", "USE_SERVERGC=$USE_SERVERGC", "URL_CONSUL=http://consul-server:8500",
                    "CERT_FILE_PATH=/etc/korp/certs/ca.crt"])
                self.assertEqual(servico["volumes"], ["/etc/korp/certs/:/etc/korp/certs/"])
                self.assertNotIn("dns_opt", servico)  # retirado de todos os composes no DEVO-6592

    def test_um_container_por_versao_no_compose_compartilhado(self):
        nomes = [s["container_name"] for s in renderizar("2025.1.0").values()]
        self.assertEqual(nomes.count("Korp.Legacy.Authentication-2025.1.0"), 1)
        self.assertEqual(len(nomes), len(set(nomes)))

    def test_exclusivo_da_versao(self):
        # tag <versão>.x: o gather_info classifica como exclusivo, então o compose compartilhado é gravado e
        # iniciado (compose_setup.yml) mesmo sem compose versionado na role
        with open(os.path.join(ROLE, "vars", "main.yml")) as f:
            servicos_da_role = yaml.safe_load(f)["services"]
        listas = batch.korp_service_lists(renderizar("2025.1.0"), servicos_da_role)
        self.assertIn("Korp.Legacy.Authentication-2025.1.0", listas["exclusive"])
        self.assertNotIn("Korp.Legacy.Authentication", listas["unversioned"])


if __name__ == "__main__":
    unittest.main()
