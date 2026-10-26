# FIS24_W SetupLinux Implementation Plan

> For agentic workers: use superpowers:executing-plans.

**Goal:** disponibilizar instalacao do motor contabil no SetupLinux.
**Architecture:** role FIS24_W reutilizando utils/services/add_service, com um backend e sem banco proprio.
**Tech Stack:** Ansible, YAML, Jinja2, Docker Compose; servico hospedado em C#.
**Spec:** docs/superpowers/specs/2026-10-26-fis24-w-setuplinux.md

## Restricoes
Somente branch atual; release por cherry-pick do usuario. Sem deploy, commit ou mudancas no framework do setup. Imagem considerada disponivel. IA/main.md consultado em C:/contabilidade, sem orientacao especifica para Ansible.

## Execucao
- [x] Criar os cinco arquivos da role conforme spec.
- [x] Renderizar Compose para 2025.1.0 e 2025.2.0, com/sem DNS opcional, sufixo vazio e de desenvolvimento; validar imagem, hosts, rede, volumes e ausencia de frontend/gateway/db.
- [x] Renderizar JSON com secret ficticio e validar propriedades; verificar tasks, vars e meta em YAML.
- [x] Revisao independente, diff e status; registrar limites da verificacao.

## Review Focus
Consistencia entre AppId, servico, imagem e nome do template; compatibilidade com os helpers existentes; nenhuma dependencia de service_vars.db; DNS opcional indefinido/vazio/preenchido; sufixos e versoes substituidos corretamente.

Nao criar testes que apenas repitam o template; usar verificacao temporaria de renderizacao e estrutura. Nao executar playbooks de instalacao para validar sintaxe, pois alterariam infraestrutura.

## Resultado
Validacao temporaria com Jinja2 StrictUndefined e PyYAML: 12 combinacoes aprovadas (2025.1.0/2025.2.0, sufixo vazio/-dev, DNS opcional ausente/vazio/preenchido). Imagem, container, rede, hosts, volumes e URL Consul conferidos. JSON renderizado com secret ficticio e parseado; meta, vars e tasks validados, incluindo lookup do dicionario services. Sem trailing whitespace nos cinco arquivos.

Revisao independente somente leitura sem achados relevantes: null em vars e normalizado por vars_validation; helpers mantem Consul/OAuth sem criar banco; Compose generico reconhecido como exclusivo pela tag; caminhos e identificadores consistentes. git diff --check sem erros.

Limites: ansible-playbook e Docker indisponiveis neste ambiente; nao foi executado syntax-check nativo do Ansible, docker compose config, instalacao, autenticacao real ou chamada ao servico. A verificacao cobre renderizacao e estrutura, nao deploy. Usuario assume existencia da imagem e fara cherry-pick para release. Sem commit/push.