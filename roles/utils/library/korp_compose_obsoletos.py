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
  - Na pasta da versão também vale um container (mesmo container_name) dos composes atuais da pasta compartilhada,
    quando ela também é deste setup: é o serviço que saiu do compose versionado para o compartilhado (ex.:
    Korp.Legacy.Authentication, que saiu de <versão>/infrastructure-desktop-compose.yml). Só o nome do container:
    o mesmo nome de serviço em outra pasta é outro projeto compose, logo outro container.
  - O obsoleto é movido para backup_root/<data-hora>/, com o mesmo caminho relativo; nada é apagado e nenhum
    container é parado ou recriado por isso (o único que sai é a cópia antiga de exclusivo, abaixo). Um arquivo
    que nenhuma role gera, mas com serviço que só existe nele, é mantido (é a única definição desse container) e
    vira aviso.
  - Uma pasta sem nenhum compose atual não é alterada.
  - Cópias antigas de serviços exclusivos (só quando a pasta compartilhada é deste setup): serviço exclusivo é o
    que existe uma vez só por servidor, num compose atual da pasta compartilhada, com container_name
    "<Base>-<versão>" e imagem "<versão>.x" (ex.: Korp.Legacy.Authentication-2025.1.0). Um container
    "<Base>-<versão anterior>", rodando ou parado, em qualquer projeto compose ou sem projeto, é a cópia que ficou
    de antes (ex.: Korp.Legacy.Authentication-2024.2.0 no projeto 202420, do antigo
    2024.2.0/infrastructure-desktop-compose.yml; no layout antigo, login-2024.2.0 no próprio projeto "composes"):
    as duas se registram na mesma rota do Fabio e revezam as requisições. Se o container desta versão está
    rodando, a cópia antiga é parada e removida (parada com restart=no já voltou a rodar depois de um reboot; o
    docker inspect dela fica no backup) e o compose dela vai para o backup quando nenhuma role o gera e todos os
    serviços dele são cópias antigas de exclusivos; senão o arquivo fica e vira aviso. Versões mais novas e
    containers versionados que convivem (ex.: VEN27-2024.2.0, de um compose versionado) não são tocados.
  - Custo no caso comum: um "docker ps --all" (só quando a pasta compartilhada é deste setup e há exclusivos);
    stop/rm/inspect só quando há o que retirar.
options:
  compose_dir: {type: path, required: true}
  roles_dir: {type: path, required: true}
  backup_root: {type: path, required: true}
  version: {type: str, required: true}
  installed_apps_file: {type: path}
'''

import glob
import json
import os
import re
import shlex
import shutil
import time

from ansible.module_utils.basic import AnsibleModule

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False

VERSION_DIR = re.compile(r'^\d+\.\d+\.\d+$')
# container de serviço exclusivo: <Base>-<versão> (o nome do container leva a versão do setup que o criou)
EXCLUSIVO = re.compile(r'^(?P<base>.+)-(?P<versao>\d+\.\d+\.\d+)$')
# estados do docker em que não há o que parar antes do rm
PARADOS = ('created', 'exited', 'dead')
# um "docker ps --all" com o que é preciso para decidir e para desfazer (rótulos do docker compose)
CAMPOS_PS = (('nome', '{{.Names}}'), ('estado', '{{.State}}'),
             ('projeto', '{{.Label "com.docker.compose.project"}}'),
             ('servico', '{{.Label "com.docker.compose.service"}}'),
             ('dir', '{{.Label "com.docker.compose.project.working_dir"}}'),
             ('arquivos', '{{.Label "com.docker.compose.project.config_files"}}'),
             ('env', '{{.Label "com.docker.compose.project.environment_file"}}'))
FORMATO_PS = '\t'.join(f for _, f in CAMPOS_PS)


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


def base_exclusiva(config, versao):
    """Base do container de um serviço exclusivo desta versão (container_name "<Base>-<versão>" e imagem com tag
    "<versão>.<...>", como a regra de exclusivos de services/gather_info), ou None."""
    if not isinstance(config, dict):
        return None
    m = EXCLUSIVO.match(str(config.get('container_name') or ''))
    if not m or m.group('versao') != versao:
        return None
    ultimo = str(config.get('image') or '').rsplit('/', 1)[-1]
    tag = ultimo.rsplit(':', 1)[1] if ':' in ultimo else ''
    return m.group('base') if tag.startswith(versao + '.') else None


def plano(compose_dir, roles_dir, versao, mais_nova=None):
    """(obsoletos, mantidos, ilegiveis): obsoletos [{arquivo, servicos}], mantidos [{arquivo, so_nele}]."""
    return plano_completo(compose_dir, roles_dir, versao, mais_nova)[:3]


def plano_completo(compose_dir, roles_dir, versao, mais_nova=None):
    """plano() e também os exclusivos desta versão na pasta compartilhada, se ela é deste setup ({base: container};
    vazio se não é), lidos na mesma passada pelos composes."""
    obsoletos, mantidos, ilegiveis = [], [], []
    versao_setup = versao
    exclusivos = {}
    # containers dos composes atuais da pasta compartilhada, se ela é deste setup (pastas() a devolve primeiro)
    compartilhados = set()
    for versao, pasta in pastas(compose_dir, versao, mais_nova):
        gerados = gerados_pelo_repositorio(roles_dir, versao)
        arquivos = sorted(p for p in glob.glob(os.path.join(pasta, '*-compose.yml')) if os.path.isfile(p))
        atuais = [p for p in arquivos if os.path.basename(p) in gerados]
        orfaos = [p for p in arquivos if os.path.basename(p) not in gerados]
        definidos = set()
        for p in atuais:
            for servico, config in (servicos(p) or {}).items():
                definidos |= identidades(servico, config)
                base = None if versao else base_exclusiva(config, versao_setup)
                if base:
                    exclusivos[base] = config['container_name']
        if not versao:
            compartilhados = {i for i in definidos if i[0] == 'container'}
        else:
            definidos |= compartilhados
        if not atuais or not orfaos:
            continue
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
    return obsoletos, mantidos, ilegiveis, exclusivos


def pasta_backup(backup_root, agora=None):
    return os.path.join(backup_root, time.strftime('%Y%m%d-%H%M%S', time.localtime(agora)))


def retirar(obsoletos, compose_dir, backup_root, agora=None):
    """Move cada obsoleto para o backup e registra no LEIAME.txt logo depois de cada um: se um mover falha no
    meio, os que já foram têm o comando para desfazer e só eles ganham 'backup'."""
    destino = pasta_backup(backup_root, agora)
    leiame = os.path.join(destino, 'LEIAME.txt')
    for item in obsoletos:
        relativo = os.path.relpath(item['arquivo'], compose_dir)
        backup = os.path.join(destino, relativo)
        if not os.path.isdir(os.path.dirname(backup)):
            os.makedirs(os.path.dirname(backup))
        if not os.path.exists(leiame):
            with open(leiame, 'a') as f:
                f.write('Composes retirados pelo setup em %s: nenhuma role os gera mais e todos os serviços deles\n'
                        'estão definidos nos composes atuais da mesma pasta (ou, pelo nome do container, da pasta\n'
                        'compartilhada). Nenhum container foi parado.\n\n'
                        % time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(agora)))
        shutil.move(item['arquivo'], backup)
        item['backup'] = backup
        with open(leiame, 'a') as f:
            f.write('%s (serviços: %s)\n  desfazer: mv %s %s\n'
                    % (item['arquivo'], ', '.join(item['servicos']) or '-', backup, item['arquivo']))
    return destino


def ler_containers(texto):
    """Saída de "docker ps --all --format FORMATO_PS" -> [{nome, estado, projeto, servico, dir, arquivos, env}]."""
    containers = []
    for linha in texto.splitlines():
        if not linha.strip():
            continue
        valores = (linha.split('\t') + [''] * len(CAMPOS_PS))[:len(CAMPOS_PS)]
        c = dict(zip([k for k, _ in CAMPOS_PS], valores))
        # nomes de link legados (ex.: "a,b/alias") não são o nome do container
        c['nome'] = next((n for n in c['nome'].split(',') if '/' not in n), c['nome'])
        c['arquivos'] = [a for a in c['arquivos'].split(',') if a]
        containers.append(c)
    return containers


def copia_antiga(nome, exclusivos, versao):
    """Base do exclusivo, se o container é a cópia de uma versão anterior dele; senão None."""
    m = EXCLUSIVO.match(str(nome or ''))
    if m and m.group('base') in exclusivos and _versao(m.group('versao')) < _versao(versao):
        return m.group('base')
    return None


def plano_exclusivos(exclusivos, containers, versao):
    """(retirar, avisos): cópias de versões anteriores dos exclusivos desta versão, rodando ou paradas, em qualquer
    projeto compose (no layout antigo elas ficavam no próprio projeto compartilhado, com outro nome de serviço) ou
    sem projeto. Só sai a cópia cujo substituto desta versão está rodando."""
    estados = dict((c['nome'], c['estado']) for c in containers)
    retirar, avisos = [], []
    for c in containers:
        base = copia_antiga(c['nome'], exclusivos, versao)
        if not base:
            continue
        atual = exclusivos[base]
        if estados.get(atual) != 'running':
            avisos.append('%s não foi retirado: %s, que o substitui, não está rodando (%s).'
                          % (c['nome'], atual, estados.get(atual) or 'não existe'))
        else:
            retirar.append(dict(c, atual=atual))
    return retirar, avisos


def composes_das_copias(retirar, compose_dir, roles_dir, exclusivos, versao):
    """(mover, mantidos): os composes de onde vieram as cópias retiradas. Vai para o backup o arquivo dentro de
    compose_dir que nenhuma role gera naquela pasta e cujos serviços são todos cópias antigas de exclusivos;
    mantidos [{arquivo, motivo}]."""
    raiz = os.path.realpath(compose_dir)
    mover, mantidos = [], []
    for arquivo in sorted(set(a for c in retirar for a in c['arquivos'])):
        if not os.path.isfile(arquivo):
            continue
        pasta = os.path.relpath(os.path.dirname(os.path.realpath(arquivo)), raiz)
        if pasta == os.pardir or pasta.startswith(os.pardir + os.sep):
            mantidos.append({'arquivo': arquivo, 'motivo': 'fora de %s' % compose_dir})
            continue
        versao_pasta = '' if pasta == os.curdir else pasta
        proprios = servicos(arquivo)
        copias = sorted(s for s, cfg in (proprios or {}).items()
                        if copia_antiga(cfg.get('container_name') if isinstance(cfg, dict) else None,
                                        exclusivos, versao))
        if os.path.basename(arquivo) in gerados_pelo_repositorio(roles_dir, versao_pasta):
            # compose atual: é do setup (ex.: o compartilhado, que o layout antigo usava junto com o da versão);
            # só avisa se ele ainda define a cópia, porque o setup daquela versão a recriaria
            if copias:
                mantidos.append({'arquivo': arquivo, 'motivo': 'o setup da versão %s gera esse arquivo com %s'
                                 % (versao_pasta or 'compartilhada', ', '.join(copias))})
            continue
        if proprios is None:
            mantidos.append({'arquivo': arquivo, 'motivo': 'não pôde ser lido'})
            continue
        outros = sorted(set(proprios) - set(copias))
        if outros:
            mantidos.append({'arquivo': arquivo, 'motivo': 'também define %s' % ', '.join(outros)})
        else:
            mover.append({'arquivo': arquivo, 'servicos': sorted(proprios)})
    return mover, mantidos


def comando_desfazer(c, movidos):
    """Comando que recria a cópia retirada (com o compose de volta ao lugar, se ele foi para o backup)."""
    if not c['projeto'] or not c['arquivos']:
        return 'container sem docker compose: recrie a partir de containers/%s.json' % c['nome']
    passos = ['mv %s %s' % (shlex.quote(movidos[a]), shlex.quote(a)) for a in c['arquivos'] if a in movidos]
    up = ['docker', 'compose', '-p', c['projeto']]
    if c['dir']:
        up += ['--project-directory', c['dir']]
    for env in [e for e in c['env'].split(',') if e]:
        up += ['--env-file', env]
    for a in c['arquivos']:
        up += ['-f', a]
    up += ['up', '-d', '--no-deps'] + ([c['servico']] if c['servico'] else [])
    passos.append(' '.join(shlex.quote(p) for p in up))
    return ' && '.join(passos)


def retirar_exclusivos(run, docker, retirar, mover, compose_dir, backup_root, versao, agora=None):
    """Para e remove as cópias antigas e move os composes delas para backup_root/<data-hora>/ (a mesma pasta dos
    composes obsoletos), com o docker inspect de cada cópia em containers/<nome>.json e o comando para desfazer no
    LEIAME.txt, gravado a cada passo. Uma falha do docker num container não impede os outros, e o compose de onde
    ele veio fica no lugar. Devolve (retirados, falhas, movidos {arquivo: backup}, destino)."""
    destino = pasta_backup(backup_root, agora)
    pasta_containers = os.path.join(destino, 'containers')
    if not os.path.isdir(pasta_containers):
        os.makedirs(pasta_containers)
    leiame = os.path.join(destino, 'LEIAME.txt')
    with open(leiame, 'a') as f:
        f.write('Containers de versões anteriores retirados pelo setup %s em %s: são cópias de serviços que\n'
                'existem uma vez só por servidor (compose compartilhado) e que revezavam a mesma rota com o\n'
                'container desta versão, que estava rodando. Cada cópia foi parada e removida (o docker\n'
                'inspect dela está em containers/). Se recriar uma cópia, o próximo setup desta versão a retira\n'
                'de novo.\n\n'
                % (versao, time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(agora))))
    # registro de cada cópia antes de parar: um inspect em lote (com nome ausente, o docker devolve os demais)
    _, saida, _ = run([docker, 'container', 'inspect'] + [c['nome'] for c in retirar])
    try:
        registros = json.loads(saida or '[]')
    except ValueError:
        registros = []
    for registro in registros:
        nome = str(registro.get('Name') or '').lstrip('/')
        if nome:
            with open(os.path.join(pasta_containers, nome + '.json'), 'w') as f:
                json.dump(registro, f, indent=2)
    retirados, falhas = [], []
    for c in retirar:
        # parado não basta: restart=no não segurou uma cópia depois de um reboot; o container sai
        rc, out, err = (0, '', '') if c['estado'] in PARADOS else run([docker, 'stop', c['nome']])
        if rc == 0:
            rc, out, err = run([docker, 'rm', c['nome']])
        if rc != 0:
            falhas.append({'container': c['nome'], 'erro': (err or out or '').strip()})
            continue
        retirados.append(c)
        with open(leiame, 'a') as f:
            f.write('%s (projeto %s) parado e removido; substituído por %s\n  recriar: %s\n'
                    % (c['nome'], c['projeto'] or '-', c['atual'], comando_desfazer(c, {})))
    com_falha = set(a for c in retirar if c['nome'] in set(f['container'] for f in falhas) for a in c['arquivos'])
    movidos = {}
    for item in mover:
        if item['arquivo'] in com_falha:
            continue
        backup = os.path.join(destino, os.path.relpath(item['arquivo'], compose_dir))
        if not os.path.isdir(os.path.dirname(backup)):
            os.makedirs(os.path.dirname(backup))
        shutil.move(item['arquivo'], backup)
        movidos[item['arquivo']] = backup
        item['backup'] = backup
        with open(leiame, 'a') as f:
            f.write('%s movido para o backup (serviços: %s)\n  antes de recriar: mv %s %s\n'
                    % (item['arquivo'], ', '.join(item['servicos']), backup, item['arquivo']))
    for c in retirados:
        c['desfazer'] = comando_desfazer(c, movidos)
    return retirados, falhas, movidos, destino


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
    agora = time.time()
    obsoletos, mantidos, ilegiveis, exclusivos = plano_completo(
        p['compose_dir'], p['roles_dir'], p['version'], versao_mais_nova_instalada(p['installed_apps_file']))
    for item in mantidos:
        module.warn('%s não é gerado pelo setup desta versão, mas é a única definição de %s: mantido. Se ele '
                    'sobrou de uma reorganização, sai sozinho depois que o aplicativo que agora define esses '
                    'serviços for instalado.' % (item['arquivo'], ', '.join(item['so_nele'])))
    for arquivo in ilegiveis:
        module.warn('%s não é gerado pelo setup desta versão e não pôde ser lido: mantido.' % arquivo)
    backup_dir = None
    resumo = []
    if obsoletos and not module.check_mode:
        try:
            backup_dir = retirar(obsoletos, p['compose_dir'], p['backup_root'], agora)
        except (IOError, OSError) as e:
            movidos = [o for o in obsoletos if 'backup' in o]
            module.fail_json(msg='Falha ao mover compose obsoleto para o backup: %s (%d de %d movidos; desfazer: '
                                 'LEIAME.txt em %s)' % (e, len(movidos), len(obsoletos), p['backup_root']),
                             moved=movidos, not_moved=[o['arquivo'] for o in obsoletos if 'backup' not in o])
        resumo.append('%s movido(s) para %s (desfazer: veja LEIAME.txt na pasta)'
                      % (', '.join(o['arquivo'] for o in obsoletos), backup_dir))

    # Cópias antigas de serviços exclusivos: só há exclusivos se a pasta compartilhada é deste setup. No caso comum
    # (nada a retirar) o custo é este "docker ps --all"; stop/rm/inspect só quando há cópia.
    copias, removidos = [], []
    docker = module.get_bin_path('docker') if exclusivos else None
    if exclusivos and not docker:
        module.warn('docker não encontrado: cópias antigas de serviços exclusivos não verificadas.')
    if docker:
        rc, out, err = module.run_command([docker, 'ps', '--all', '--format', FORMATO_PS])
        if rc != 0:
            module.warn('docker ps falhou (%s): cópias antigas de serviços exclusivos não verificadas.'
                        % (err or out).strip())
        else:
            copias, avisos = plano_exclusivos(exclusivos, ler_containers(out), p['version'])
            for aviso in avisos:
                module.warn(aviso)
    if copias:
        mover, mantidos_copias = composes_das_copias(copias, p['compose_dir'], p['roles_dir'], exclusivos,
                                                     p['version'])
        for item in mantidos_copias:
            module.warn('%s, de onde vinha %s, fica (%s): um "docker compose up" dele recriaria a cópia.'
                        % (item['arquivo'], ', '.join(c['nome'] for c in copias if item['arquivo'] in c['arquivos']),
                           item['motivo']))
        if not module.check_mode:
            try:
                removidos, falhas, movidos, destino = retirar_exclusivos(
                    module.run_command, docker, copias, mover, p['compose_dir'], p['backup_root'], p['version'],
                    agora)
            except (IOError, OSError) as e:
                module.fail_json(msg='Falha ao retirar cópias antigas de serviços exclusivos: %s (desfazer: '
                                     'LEIAME.txt em %s)' % (e, pasta_backup(p['backup_root'], agora)))
            for falha in falhas:
                module.warn('%s não foi retirado: %s' % (falha['container'], falha['erro']))
            for c in removidos:
                resumo.append('%s (projeto %s) parado e removido: duplicava %s, que está rodando. Desfazer: %s'
                              % (c['nome'], c['projeto'] or '-', c['atual'], c['desfazer']))
            for arquivo in sorted(movidos):
                resumo.append('%s movido para %s' % (arquivo, movidos[arquivo]))
            backup_dir = backup_dir or destino
    module.exit_json(changed=bool(obsoletos) or bool(copias if module.check_mode else removidos),
                     moved=obsoletos, kept=mantidos, unreadable=ilegiveis, backup_dir=backup_dir,
                     old_exclusive=[dict((k, c.get(k)) for k in ('nome', 'estado', 'projeto', 'atual', 'desfazer'))
                                    for c in (copias if module.check_mode else removidos)],
                     summary=resumo)


if __name__ == '__main__':
    main()
