"""Equivalência entre as tarefas originais e os filtros do fast path, executando o Ansible de verdade.

Para cada caso, um playbook roda as tarefas originais (default/get_latest_installed_version.yml,
services/gather_info_tasks.yml, apps/ensure_mapping_tasks.yml) e os filtros korp_latest_installed_version,
korp_service_lists e korp_apps_mapping com as mesmas entradas, e grava os facts dos dois lados.
Precisa de ansible-playbook (como o host do setup); sem ele, os testes são pulados.
"""
import json
import os
import shutil
import subprocess
import tempfile
import textwrap
import unittest

from _loader import REPO

PLAYBOOK = r"""
- hosts: localhost
  connection: local
  gather_facts: false
  vars:
    korp_setup_fast_path: false
  tasks:
    - name: Casos
      ansible.builtin.include_tasks: case.yml
      loop: "{{ cases }}"
      loop_control:
        loop_var: case

    - name: Resultado
      ansible.builtin.copy:
        dest: "{{ out }}"
        content: "{{ results | default([]) | to_json }}"
"""

CASE = r"""
- name: installed_apps.yml do caso
  ansible.builtin.copy:
    dest: "{{ config_dir_path }}/installed_apps.yml"
    content: "{{ case.installed_apps }}"

- name: Tarefas originais da última versão instalada
  ansible.builtin.include_role:
    name: utils
    tasks_from: default/get_latest_installed_version

- name: Fatos originais
  ansible.builtin.set_fact:
    orig_latest: {temp_apps_map: "{{ temp_apps_map }}", latest_installed_version: "{{ latest_installed_version }}",
                  has_versioned_apps: "{{ has_versioned_apps }}"}

- name: Serviços do caso
  ansible.builtin.set_fact:
    services: "{{ case.services }}"
    id: "{{ case.id }}"

- name: Tarefas originais de gather_info
  ansible.builtin.include_role:
    name: utils
    tasks_from: services/gather_info_tasks.yml

- name: Fatos originais de gather_info
  ansible.builtin.set_fact:
    orig_info: {exclusive: "{{ exclusive_services_list }}", unversioned: "{{ unversioned_services_list }}",
                has_versioned: "{{ has_versioned_services }}", has_unversioned: "{{ has_unversioned_services }}",
                has_exclusive: "{{ has_exclusive_services }}"}

- name: Tarefas originais de ensure_mapping
  ansible.builtin.include_role:
    name: utils
    tasks_from: apps/ensure_mapping_tasks.yml
  when: has_versioned_services or not has_exclusive_services

- name: Resultados do caso
  vars:
    korp_versioned: >-
      {{ (playbook_dir ~ '/roles/' ~ id ~ '/templates/composes/' ~ version_without_build ~ '/' ~ id
          ~ '-compose.yml.j2') | korp_path_stat }}
    korp_unversioned: "{{ (playbook_dir ~ '/roles/' ~ id ~ '/templates/composes/' ~ id ~ '-compose.yml.j2') | korp_path_stat }}"
    korp_lists: >-
      {{ ((lookup('ansible.builtin.template', korp_unversioned.stat.path) | from_yaml).services
          if korp_unversioned.stat.exists else {}) | korp_service_lists(services) }}
  ansible.builtin.set_fact:
    results: >-
      {{ results | default([]) + [{
           'name': case.name,
           'orig_latest': orig_latest,
           'fast_latest': lookup('file', config_dir_path ~ '/installed_apps.yml') | from_yaml
                          | korp_latest_installed_version,
           'orig_info': orig_info,
           'fast_info': {'exclusive': korp_lists.exclusive, 'unversioned': korp_lists.unversioned,
                         'has_versioned': korp_versioned.stat.exists,
                         'has_unversioned': korp_lists.unversioned | length > 0,
                         'has_exclusive': korp_lists.exclusive | length > 0},
           'orig_map': apps_map if (has_versioned_services or not has_exclusive_services) else None,
           'fast_map': (lookup('file', config_dir_path ~ '/installed_apps.yml') | from_yaml
                        | korp_apps_mapping(id, version_without_build, has_unversioned_services | bool,
                                            (has_versioned_services or has_exclusive_services) | bool))
                       if (has_versioned_services or not has_exclusive_services) else None}] }}
"""

COMPOSE_UNVERSIONED = """\
services:
  shared:
    container_name: Korp.Shared
    image: "acct/korp.shared:2025.1.0.x"
  exclusive:
    container_name: Korp.Exclusive-2025.1.0
    image: "acct/korp.exclusive:2025.1.0.1"
  other-exclusive:
    container_name: Korp.Other-2025.1.0
    image: "acct/korp.other:2025.1.0.7.x"
"""

APPS = {
    "vazio": "unversioned: []\nversioned:\n",
    "sem_versionados_none": "unversioned:\n  - u1\nversioned: null\n",
    "versionados_vazios": "unversioned: []\nversioned: {}\n",
    "duas_versoes": "unversioned: [u1, A]\nversioned:\n  2024.2.0: [A, B]\n  2025.1.0: [B]\n",
    "fora_de_ordem": "unversioned: []\nversioned:\n  2025.1.0: [A]\n  2024.10.0: [C]\n  2024.9.0: [D]\n",
    "dezena": "unversioned: []\nversioned:\n  2024.9.0: [D]\n  2024.10.0: [C]\n",
    "chave_vazia_mais_nova": "unversioned: [A]\nversioned:\n  2025.1.0: [B]\n  2025.2.0: []\n",
    "lista_nula": "unversioned:\nversioned:\n  2025.1.0:\n",
}

SERVICES = {
    "A": {  # versionado + não versionado
        "Korp.A": {"version": {"unversioned": True}},
        "Korp.A.Worker": {"version": None},
        "Korp.A.Api": {"version": {"unversioned": False}},
        "Korp.A.Other": {"version": {}},
        "Korp.A.Last": {"version": {"unversioned": "yes"}},
    },
    "B": {"Korp.B": {"version": None}},   # só versionado
    "C": {"Korp.C": {"version": {"unversioned": True}}},   # só não versionado, sem exclusivo
    "E": {"Korp.E": {"version": None}},   # só exclusivo (mantém as tarefas originais)
}


def ansible_available():
    try:
        return subprocess.run(["ansible-playbook", "--version"], capture_output=True, stdin=subprocess.DEVNULL,
                              timeout=60).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


@unittest.skipUnless(ansible_available(), "ansible-playbook indisponível")
class FastPathEquivalenceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        d = cls.dir
        os.makedirs(f"{d}/config")
        os.makedirs(f"{d}/roles")
        os.symlink(os.path.join(REPO, "roles", "utils"), f"{d}/roles/utils")
        layout = {
            "A": {"composes/2025.1.0/A-compose.yml.j2": "services: {}\n",
                  "composes/A-compose.yml.j2": COMPOSE_UNVERSIONED},
            "B": {"composes/2025.1.0/B-compose.yml.j2": "services: {}\n"},
            "C": {"composes/C-compose.yml.j2": "services:\n  c:\n    container_name: Korp.C\n"
                                               "    image: \"acct/korp.c:2025.1.0.x\"\n"},
            "E": {"composes/E-compose.yml.j2": "services:\n  e:\n    container_name: Korp.E-2025.1.0\n"
                                               "    image: \"acct/korp.e:2025.1.0.3\"\n"},
        }
        for role, files in layout.items():
            for rel, text in files.items():
                path = f"{d}/roles/{role}/templates/{rel}"
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w") as f:
                    f.write(text)
        cases = []
        for app_id in SERVICES:
            for name, text in APPS.items():
                cases.append({"name": f"{app_id}/{name}", "id": app_id, "services": SERVICES[app_id],
                              "installed_apps": text})
        with open(f"{d}/play.yml", "w") as f:
            f.write(textwrap.dedent(PLAYBOOK))
        with open(f"{d}/case.yml", "w") as f:
            f.write(textwrap.dedent(CASE))
        extra = {"cases": cases, "out": f"{d}/out.json", "config_dir_path": f"{d}/config",
                 "version_without_build": "2025.1.0"}
        with open(f"{d}/extra.json", "w") as f:
            json.dump(extra, f)
        env = dict(os.environ, ANSIBLE_FILTER_PLUGINS=os.path.join(REPO, "filter_plugins"),
                   ANSIBLE_LIBRARY=os.path.join(REPO, "roles", "utils", "library"),
                   ANSIBLE_ROLES_PATH=f"{d}/roles", ANSIBLE_LOCALHOST_WARNING="false",
                   ANSIBLE_INVENTORY_UNPARSED_WARNING="false", ANSIBLE_NOCOLOR="1",
                   ANSIBLE_RETRY_FILES_ENABLED="false", HOME=d)
        cls.proc = subprocess.run(["ansible-playbook", "-i", "localhost,", "play.yml", "-e", f"@{d}/extra.json"],
                                  cwd=d, env=env, capture_output=True, text=True, stdin=subprocess.DEVNULL,
                                  timeout=600)
        cls.results = None
        if cls.proc.returncode == 0:
            with open(f"{d}/out.json") as f:
                cls.results = json.load(f)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def setUp(self):
        self.assertEqual(self.proc.returncode, 0, self.proc.stdout[-3000:] + self.proc.stderr[-2000:])
        self.assertEqual(len(self.results), len(SERVICES) * len(APPS))

    def test_latest_installed_version(self):
        for r in self.results:
            with self.subTest(case=r["name"]):
                self.assertEqual(r["fast_latest"], r["orig_latest"])

    def test_gather_info(self):
        seen_exclusive = False
        for r in self.results:
            with self.subTest(case=r["name"]):
                self.assertEqual(r["fast_info"], r["orig_info"])
                seen_exclusive = seen_exclusive or r["orig_info"]["has_exclusive"]
        self.assertTrue(seen_exclusive)

    def test_ensure_mapping(self):
        compared = 0
        for r in self.results:
            with self.subTest(case=r["name"]):
                self.assertEqual(r["fast_map"], r["orig_map"])
                compared += r["orig_map"] is not None
        self.assertGreater(compared, 0)


if __name__ == "__main__":
    unittest.main()
