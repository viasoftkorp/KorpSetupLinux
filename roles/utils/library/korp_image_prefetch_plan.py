#!/usr/bin/python
# -*- coding: utf-8 -*-
from __future__ import absolute_import, division, print_function
__metaclass__ = type

DOCUMENTATION = r'''
module: korp_image_prefetch_plan
short_description: Lista as imagens dos composes que o setup vai subir, para o download antecipado
description:
  - Expande as dependências (meta/main.yml) das roles informadas, na ordem em que o Ansible as executa,
    e lê as linhas "image:" dos mesmos templates que roles/utils/tasks/apps/compose_setup.yml e as roles
    de infraestrutura renderizam (templates/composes/*.yml.j2 e templates/composes/<versão>/*.yml.j2).
  - Resolve apenas referências simples {{ variavel }} com as variáveis informadas e as de
    defaults/main.yml e vars/main.yml da própria role. Uma imagem que dependa de qualquer outra expressão
    é ignorada (fica em "unresolved"): o compose a baixa na hora, como sem o download antecipado.
  - Com installed_apps_file, acrescenta os aplicativos que a tag update vai atualizar, com a mesma regra
    de roles/utils/tasks/apps/update.yml e default/get_latest_installed_version.yml.
  - skip_templates: nomes de templates que o setup renderiza mas nunca sobe (ex.: pgweb-compose.yml.j2).
  - versioned_apps_file (tag update-versioned): acrescenta só o compose versionado
    roles/<AppId>/templates/composes/<versão>/<AppId>-compose.yml.j2 de cada AppId registrado na versão,
    sem dependências nem composes não versionados, como apps/update_versioned.yml e install_versioned_only.yml.
  - Não altera nada: só lê arquivos do repositório e a lista de imagens locais (docker image ls).
options:
  roles_dir: {type: path, required: true}
  roles: {type: list, elements: str, required: true}
  version: {type: str, required: true}
  variables: {type: dict, default: {}}
  installed_apps_file: {type: path}
  skip_templates: {type: list, elements: str, default: []}
  versioned_apps_file: {type: path}
  docker: {type: str, default: docker}
'''

import glob
import os
import re

from ansible.module_utils.basic import AnsibleModule

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False

IMAGE_LINE = re.compile(r'^\s*image:\s*(.+?)\s*$', re.M)
SIMPLE_VAR = re.compile(r'\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}')


def _load_yaml(path):
    try:
        with open(path) as f:
            return yaml.safe_load(f)
    except (IOError, OSError, yaml.YAMLError):
        return None


def role_dependencies(roles_dir, role):
    """Nomes das dependências declaradas em roles/<role>/meta/main.yml, na ordem."""
    meta = _load_yaml(os.path.join(roles_dir, role, 'meta', 'main.yml')) or {}
    deps = []
    for dep in (meta.get('dependencies') or []) if isinstance(meta, dict) else []:
        name = dep if isinstance(dep, str) else (dep.get('role') or dep.get('name')) if isinstance(dep, dict) else None
        if name:
            deps.append(str(name))
    return deps


def expand_roles(roles_dir, roles):
    """Roles na ordem de execução: dependências antes da role, cada role uma única vez."""
    order, seen, missing = [], set(), []

    def visit(role, stack):
        if role in seen or role in stack:
            return
        if not os.path.isdir(os.path.join(roles_dir, role)):
            if role not in missing:
                missing.append(role)
            return
        for dep in role_dependencies(roles_dir, role):
            visit(dep, stack | {role})
        seen.add(role)
        order.append(role)

    for role in roles:
        visit(str(role), frozenset())
    return order, missing


def role_variables(roles_dir, role):
    """Variáveis escalares de defaults/main.yml e vars/main.yml (vars tem precedência, como no Ansible)."""
    result = {}
    for part in ('defaults', 'vars'):
        data = _load_yaml(os.path.join(roles_dir, role, part, 'main.yml'))
        if isinstance(data, dict):
            result.update({k: v for k, v in data.items()
                           if isinstance(k, str) and isinstance(v, (str, int, float)) and not isinstance(v, bool)})
    return result


def compose_templates(roles_dir, role, version, skip=()):
    """Os templates de compose que o setup renderiza para a role, versionados primeiro (menos os de skip)."""
    base = os.path.join(roles_dir, role, 'templates', 'composes')
    versioned = sorted(glob.glob(os.path.join(base, version, '*.yml.j2')))
    unversioned = sorted(glob.glob(os.path.join(base, '*.yml.j2')))
    return [p for p in versioned + unversioned if os.path.basename(p) not in skip]


def image_values(text):
    values = []
    for raw in IMAGE_LINE.findall(text):
        value = raw.split(' #', 1)[0].strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in '"\'':
            value = value[1:-1]
        values.append(value)
    return values


def resolve(value, variables, depth=5):
    """Substitui {{ nome }} pelas variáveis; None se sobrar qualquer outra expressão ou variável indefinida."""
    for _ in range(depth):
        unknown = []

        def sub(match):
            name = match.group(1)
            if name not in variables or variables[name] is None:
                unknown.append(name)
                return match.group(0)
            return str(variables[name])

        new = SIMPLE_VAR.sub(sub, value)
        if unknown:
            return None
        if new == value:
            break
        value = new
    if '{{' in value or '{%' in value or '$' in value or not value or any(c.isspace() for c in value):
        return None
    return value


def normalize(image):
    """Nome como 'docker image ls' mostra: sem o registro padrão (docker.io/, library/) e, sem tag, ':latest'.

    Referências por digest ficam como estão.
    """
    if '@' in image:
        return image
    for prefix in ('docker.io/', 'index.docker.io/'):
        if image.startswith(prefix):
            image = image[len(prefix):]
            break
    if image.startswith('library/') and image.count('/') == 1:
        image = image[len('library/'):]
    last = image.rsplit('/', 1)[-1]
    return image if ':' in last else image + ':latest'


def _version_key(value):
    return [int(p) if p.isdigit() else p for p in re.split(r'[.\-]', str(value))]


def _version_lt(a, b):
    try:
        return _version_key(a) < _version_key(b)
    except TypeError:
        return str(a) < str(b)


def update_apps(installed_apps, version):
    """AppIds que a tag update instala (update.yml): não versionados + os da última versão instalada.

    Como em get_latest_installed_version.yml com is_updating: se a maior versão registrada for a própria
    versão do setup, usa a maior entre as demais. Calcular isto antes da infraestrutura dá o mesmo
    resultado de update.yml, porque o que é registrado no caminho é só a própria versão do setup.
    """
    data = installed_apps if isinstance(installed_apps, dict) else {}
    unversioned = list(data.get('unversioned') or [])
    versioned = data.get('versioned')
    if not isinstance(versioned, dict):
        apps = unversioned
    else:
        latest = '0.0.0'
        for key in versioned:
            if _version_lt(latest, key):
                latest = key
        if str(latest) == str(version):
            latest = '0.0.0'
            for key in versioned:
                if _version_lt(latest, key) and str(key) != str(version):
                    latest = key
        apps = unversioned + list(versioned.get(latest) or [])
    unique = []
    for app in apps:
        if app not in unique:
            unique.append(app)
    return [str(a) for a in unique]


def versioned_only_apps(installed_apps, version):
    """AppIds de apps/update_versioned.yml: versioned[versão] (sem duplicados), na ordem."""
    data = installed_apps if isinstance(installed_apps, dict) else {}
    versioned = data.get('versioned') or {}
    apps = []
    for app in (versioned.get(version) or []) if isinstance(versioned, dict) else []:
        if str(app) not in apps:
            apps.append(str(app))
    return apps


def versioned_only_templates(roles_dir, app, version):
    path = os.path.join(roles_dir, app, 'templates', 'composes', version, app + '-compose.yml.j2')
    return [path] if os.path.isfile(path) else []


def plan(roles_dir, roles, version, variables, local_images, skip_templates=(), versioned_apps=()):
    expanded, missing_roles = expand_roles(roles_dir, roles)
    images, unresolved = [], []
    work = [(role, compose_templates(roles_dir, role, version, skip_templates)) for role in expanded]
    work += [(app, versioned_only_templates(roles_dir, app, version)) for app in versioned_apps]
    for role, templates in work:
        context = dict(role_variables(roles_dir, role))
        context.update(variables or {})
        for path in templates:
            try:
                with open(path) as f:
                    text = f.read()
            except (IOError, OSError):
                continue
            for value in image_values(text):
                image = resolve(value, context)
                if image is None:
                    unresolved.append({'role': role, 'file': os.path.relpath(path, roles_dir), 'value': value})
                    continue
                image = normalize(image)
                if image not in images:
                    images.append(image)
    missing = [i for i in images if i not in local_images]
    return {'roles': expanded, 'missing_roles': missing_roles, 'images': images,
            'missing': missing, 'unresolved': unresolved}


def local_image_names(module, docker):
    rc, out, err = module.run_command([docker, 'image', 'ls', '--format', '{{.Repository}}:{{.Tag}}'])
    if rc != 0:
        module.fail_json(msg='Falha ao listar as imagens locais: %s' % (err or out).strip())
    return set(line.strip() for line in out.splitlines() if line.strip() and not line.endswith(':<none>'))


def main():
    module = AnsibleModule(
        argument_spec=dict(
            roles_dir=dict(type='path', required=True),
            roles=dict(type='list', elements='str', required=True),
            version=dict(type='str', required=True),
            variables=dict(type='dict', default={}),
            installed_apps_file=dict(type='path'),
            skip_templates=dict(type='list', elements='str', default=[]),
            versioned_apps_file=dict(type='path'),
            docker=dict(type='str', default='docker'),
        ),
        supports_check_mode=True,
    )
    if not HAS_YAML:
        module.fail_json(msg='PyYAML é necessário')
    p = module.params
    roles = list(p['roles'])
    if p['installed_apps_file']:
        roles += update_apps(_load_yaml(p['installed_apps_file']), p['version'])
    versioned_apps = versioned_only_apps(_load_yaml(p['versioned_apps_file']), p['version']) if p['versioned_apps_file'] else []
    result = plan(p['roles_dir'], roles, p['version'], p['variables'], local_image_names(module, p['docker']),
                  set(p['skip_templates']), versioned_apps)
    result['versioned_apps'] = versioned_apps
    module.exit_json(changed=False, **result)


if __name__ == '__main__':
    main()
