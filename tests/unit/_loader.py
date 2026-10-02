"""Carrega módulos/filtros do repositório por caminho (sem instalar nada)."""
import importlib.util
import os
import sys

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def load(relpath, name):
    path = os.path.join(REPO, relpath)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_module_utils():
    """Registra roles/utils/module_utils/* como ansible.module_utils.* (como o Ansible faz)."""
    return load("roles/utils/module_utils/korp_kv_merge.py", "ansible.module_utils.korp_kv_merge")
