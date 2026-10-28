#!/usr/bin/python
# -*- coding: utf-8 -*-
from __future__ import absolute_import, division, print_function
__metaclass__ = type

DOCUMENTATION = r'''
module: korp_compose_obsoletos
short_description: Retira os composes que sobraram de uma reorganização das roles
description:
  - Cada setup só mexe no que é dele: a pasta da própria versão (compose_dir/<version>) e, se esta é a versão
    mais nova instalada no servidor (installed_apps_file, ignorando versões com lista vazia), a pasta de composes não
    versionados (compose_dir), que todas as versões compartilham. Numa instalação com 2024.2 e 2025.1, a 2024.2
    ainda gera arquivos que a 2025.1 dividiu: se as duas limpassem a pasta compartilhada, uma retiraria os
    composes da outra a cada setup. As pastas de outras versões ficam com os setups delas.
  - Um "*-compose.yml" é obsoleto quando (1) nenhuma role do repositório gera mais esse arquivo naquela pasta (não
    existe roles/*/templates/composes/<arquivo>.j2, ou roles/*/templates/composes/<versão>/<arquivo>.j2) e (2) todos
    os serviços dele estão definidos, com o mesmo nome de serviço ou de container, nos composes atuais da mesma pasta
    (os que alguma role gera). É o que sobra quando um compose é renomeado ou dividido; ele duplica serviços, e o
    qa-pr para em "Esperado um compose para ...; encontrados 2".
  - O obsoleto é movido para backup_root/<data-hora>/, com o mesmo caminho relativo; nada é apagado e nenhum
    container é parado ou recriado. Um arquivo que nenhuma role gera, mas com serviço que só existe nele, é mantido
    (é a única definição desse container) e vira aviso.
  - Uma pasta sem nenhum compose atual não é alterada.
options:
  compose_dir: {type: path, required: true}
  roles_dir: {type: path, required: true}
  backup_root: {type: path, required: true}
  version: {type: str, required: true}
  installed_apps_file: {type: path}
'''

import glob
import os
import re
import shutil
import time

from ansible.module_utils.basic import AnsibleModule

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False

VERSION_DIR = re.compile(r'^\d+\.\d+\.\d+$')


def gerados_pelo_repositorio(roles_dir, versao):
    """Nomes de compose que as roles geram na pasta da versão ('' = não versionados)."""
    partes = [roles_dir, '*', 'templates', 'composes'] + ([versao] if versao else []) + ['*.yml.j2']
    return {os.path.basename(p)[:-3] for p in glob.glob(os.path.join(*partes))}


def servicos(caminho):
    """Serviços do compose, ou None se o arquivo não puder ser lido."""
    try:
        with open(caminho) as f:
            conteudo = yaml.safe_load(f)
    except (IOError, OSError, yaml.YAMLError):
        return None
    if conteudo is None:
        return {}
    if not isinstance(conteudo, dict):
        return None
    return conteudo.get('services') or {}


def identidades(servico, config):
    ids = {('servico', servico)}
    if isinstance(config, dict) and config.get('container_name'):
        ids.add(('container', str(config['container_name'])))
    return ids


def _versao(texto):
    return tuple(int(n) for n in texto.split('.'))


def versao_mais_nova_instalada(installed_apps_file):
    """Maior versão com aplicativos em installed_apps.yml (None: sem arquivo ou sem versionados)."""
    if not installed_apps_file:
        return None
    try:
        with open(installed_apps_file) as f:
            versionados = (yaml.safe_load(f) or {}).get('versioned') or {}
    except (IOError, OSError, yaml.YAMLError, AttributeError):
        return None
    versoes = [str(v) for v, apps in versionados.items() if apps and VERSION_DIR.match(str(v))]
    return max(versoes, key=_versao) if versoes else None


def pastas(compose_dir, versao, mais_nova):
    """Pastas deste setup: a da versão e, se ela é a mais nova instalada, a não versionada."""
    if mais_nova is None or _versao(versao) >= _versao(mais_nova):
        yield '', compose_dir
    caminho = os.path.join(compose_dir, versao)
    if os.path.isdir(caminho) and not os.path.islink(caminho):
        yield versao, caminho


def plano(compose_dir, roles_dir, versao, mais_nova=None):
    """(obsoletos, mantidos, ilegiveis): obsoletos [{arquivo, servicos}], mantidos [{arquivo, so_nele}]."""
    obsoletos, mantidos, ilegiveis = [], [], []
    for versao, pasta in pastas(compose_dir, versao, mais_nova):
        gerados = gerados_pelo_repositorio(roles_dir, versao)
        arquivos = sorted(p for p in glob.glob(os.path.join(pasta, '*-compose.yml')) if os.path.isfile(p))
        atuais = [p for p in arquivos if os.path.basename(p) in gerados]
        orfaos = [p for p in arquivos if os.path.basename(p) not in gerados]
        if not atuais or not orfaos:
            continue
        definidos = set()
        for p in atuais:
            for servico, config in (servicos(p) or {}).items():
                definidos |= identidades(servico, config)
        for p in orfaos:
            proprios = servicos(p)
            if proprios is None:
                ilegiveis.append(p)
                continue
            so_nele = sorted(s for s, c in proprios.items() if not identidades(s, c) & definidos)
            if so_nele:
                mantidos.append({'arquivo': p, 'so_nele': so_nele})
            else:
                obsoletos.append({'arquivo': p, 'servicos': sorted(proprios)})
    return obsoletos, mantidos, ilegiveis


def retirar(obsoletos, compose_dir, backup_root, agora=None):
    destino = os.path.join(backup_root, time.strftime('%Y%m%d-%H%M%S', time.localtime(agora)))
    linhas = []
    for item in obsoletos:
        relativo = os.path.relpath(item['arquivo'], compose_dir)
        backup = os.path.join(destino, relativo)
        if not os.path.isdir(os.path.dirname(backup)):
            os.makedirs(os.path.dirname(backup))
        shutil.move(item['arquivo'], backup)
        item['backup'] = backup
        linhas.append('%s (serviços: %s)\n  desfazer: mv %s %s\n'
                      % (item['arquivo'], ', '.join(item['servicos']) or '-', backup, item['arquivo']))
    if obsoletos:
        with open(os.path.join(destino, 'LEIAME.txt'), 'a') as f:
            f.write('Composes retirados pelo setup em %s: nenhuma role os gera mais e todos os serviços deles\n'
                    'estão definidos nos composes atuais da mesma pasta. Nenhum container foi parado.\n\n'
                    % time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(agora)))
            f.writelines(linhas)
    return destino


def main():
    module = AnsibleModule(
        argument_spec=dict(
            compose_dir=dict(type='path', required=True),
            roles_dir=dict(type='path', required=True),
            backup_root=dict(type='path', required=True),
            version=dict(type='str', required=True),
            installed_apps_file=dict(type='path'),
        ),
        supports_check_mode=True,
    )
    if not HAS_YAML:
        module.fail_json(msg='PyYAML é necessário')
    p = module.params
    if not VERSION_DIR.match(p['version']):
        module.fail_json(msg='version inválida: %s' % p['version'])
    obsoletos, mantidos, ilegiveis = plano(p['compose_dir'], p['roles_dir'], p['version'],
                                           versao_mais_nova_instalada(p['installed_apps_file']))
    for item in mantidos:
        module.warn('%s não é gerado pelo setup desta versão, mas é a única definição de %s: mantido. Se ele '
                    'sobrou de uma reorganização, sai sozinho depois que o aplicativo que agora define esses '
                    'serviços for instalado.' % (item['arquivo'], ', '.join(item['so_nele'])))
    for arquivo in ilegiveis:
        module.warn('%s não é gerado pelo setup desta versão e não pôde ser lido: mantido.' % arquivo)
    backup_dir = None
    if obsoletos and not module.check_mode:
        try:
            backup_dir = retirar(obsoletos, p['compose_dir'], p['backup_root'])
        except (IOError, OSError) as e:
            module.fail_json(msg='Falha ao mover compose obsoleto para o backup: %s' % e, moved=obsoletos)
    module.exit_json(changed=bool(obsoletos), moved=obsoletos, kept=mantidos, unreadable=ilegiveis,
                     backup_dir=backup_dir)


if __name__ == '__main__':
    main()
