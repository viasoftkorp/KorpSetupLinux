# Desempenho do KorpSetupLinux — design

Data: 2026-10-02
Branches: `release/2025.1.0.x-performance-test` (base `f065d7ce`) e `release/2024.2.0.x-performance-test` (base `c22dea52`)
Status: decisões tomadas sob delegação explícita do responsável pela tarefa, sem etapa formal de aprovação;
submetidas a revisão de código independente. Este documento **não** passou por aprovação formal.

## 1. Objetivo

Reduzir de forma significativa o tempo de execução do setup (`setup.sh` → `bootstrap-playbook.yml` → `main.yml`),
principalmente em **manutenção/atualização** de servidores existentes e heterogêneos, sem perder funcionalidades,
segurança, idempotência, compatibilidade com estados legados nem a capacidade de manter as duas linhas de release.

Critérios de sucesso:

1. Mesmo estado final (Consul KV, clientes OAuth, bancos MSSQL/Postgres, diretórios, arquivos de compose,
   `installed_apps.yml`, containers/labels) que a versão original, para os mesmos cenários.
2. Os mesmos estados legados tratados pelo DEVO-7182 continuam tratados com as mesmas regras de segurança.
3. Redução mensurável do tempo nos cenários: instalação, atualização com mudança de versão, reexecução sem mudanças.
4. Possibilidade de desligar a otimização sem trocar de branch (`fast_path=false`).

## 2. Diagnóstico (evidências)

### 2.1 Execuções históricas reais da QA12 (logs `/etc/korp/ansible/logs`)

| Log | Duração (nome → mtime) | Cabeçalhos `TASK` | ok / skipped |
|---|---|---|---|
| 2026-08-26 11:29 | ≈45 min | 8534 | 5135 / 3736 |
| 2026-09-17 15:40 | ≈47 min | 8859 | 4973 / 4261 |
| 2026-09-21 14:36 | ≈47 min | 8808 | 5131 / 4044 |

Distribuição dos cabeçalhos (log de 2026-09-21): ~3.600 pertencem à reconciliação de compose
(`recover_partial`/`reconcile`/`cleanup_legacy`, ~30 tarefas por serviço de compose × 121 serviços) e ~2.900
ao cadastro de serviços (`add_service`: ~25 tarefas por serviço × 115 serviços). O restante é infraestrutura e cabeçalhos
de `include_role` pulados.

### 2.2 Custo por tarefa (micro-benchmark no ambiente isolado, mesmo toolchain da QA12)

Ubuntu 22.04, ansible-core 2.17.14, community.docker 5.3.0, Docker 24.0.2, `become_user: korp`, 4 CPUs:

| Operação | Custo médio |
|---|---|
| Execução de módulo (`docker_container_info`, `command`) | 0,09–0,25 s |
| `set_fact`/tarefa pulada | 1–10 ms |
| `pipelining=True` | ganho de ~7–10 % só nas execuções de módulo |

Conclusão: o tempo é dominado pela **quantidade de tarefas e execuções de módulo por serviço**, não pelo trabalho
útil (que, em regime estável, é quase todo "verificar e não mudar nada").

### 2.3 Onde está o trabalho redundante

* `reconciled_compose_up.yml`: para **cada** serviço de cada compose, três `include_tasks` (≈30 tarefas,
  5–6 execuções de `docker_container_info`/`docker ps`) mesmo quando todos os containers já estão canônicos
  (projeto/serviço corretos, sem backup, sem legado, sem parciais) — o caso comum após a primeira execução.
* `add_service.yml`: por serviço, 4–6 `include_role` dinâmicos, 3 chamadas ao Consul (`ensure_kv` lê e grava,
  `ensure_client` lê de novo), 1 módulo para SHA-256, 1–2 `mssql_script` (uma conexão nova por chamada),
  1 `docker exec` para Postgres.

## 3. Alternativas consideradas

| Alternativa | Ganho esperado | Risco/Custo | Decisão |
|---|---|---|---|
| A. Só configuração (pipelining, Mitogen) | 10 % (pipelining); 2–4× (Mitogen) | Mitogen é plugin de estratégia de terceiros, acoplado à versão do ansible-core, baixado em runtime (cadeia de suprimentos), depuração difícil; não reduz o número de tarefas | Rejeitada |
| B. Reduzir tarefas mantendo Ansible e o modelo de dados das roles (fast path com fallback) | ~10× menos tarefas no app layer | Médio; mitigado com fallback para o código original, testes unitários e comparação de estado final | **Escolhida** |
| C. Reescrever o setup em outra linguagem | Alto | Muito alto: quebra o fluxo da equipe, recria toda a lógica | Rejeitada |
| D. Pull paralelo de imagens | Depende da rede do cliente | Sem como medir (QA12 inacessível, ambiente isolado usa imagens locais) | Não implementada; registrada como oportunidade |

## 4. Design escolhido

### 4.1 Reconciliação de compose: classificação somente-leitura + fallback (D1)

Novo módulo `roles/utils/library/korp_compose_state.py` (somente leitura). Em uma única execução:

1. roda o **mesmo** `docker compose ... config --format json` do código original;
2. lista os nomes de todos os containers (`docker ps --all --format {{.Names}}`) e inspeciona apenas os
   containers-alvo existentes;
3. decide, por serviço, se o código original **faria alguma coisa** (ação ou asserção):

| Fase | Condição que exige o caminho original |
|---|---|
| antes do `up` | alvo ausente **e** existe `^[0-9a-f]{12}_<alvo>$` (recover) |
| antes do `up` | existe `<alvo>-legacy-compose-migration` (backup) |
| antes do `up` | alvo existe com label de projeto ≠ projeto esperado ou serviço ≠ chave do serviço |
| depois do `up` | `legacy_container_name(alvo, versão)` ≠ alvo **e** o legado existe (cleanup) |
| depois do `up` | existe parcial `^[0-9a-f]{12}_<alvo>$` (cleanup de parciais) |

Se qualquer serviço do arquivo de compose exigir, os **loops originais** (`recover_partial_compose_service.yml`,
`reconcile_compose_service.yml`, `cleanup_legacy_compose_service.yml`) rodam para **todos** os serviços daquela
chamada, exatamente como antes. Caso contrário, são pulados — nesses casos todas as tarefas originais seriam
leituras sem efeito. O `docker_compose_v2` (up) continua idêntico.

Propriedade de segurança: a classificação é um **superconjunto** dos casos em que o código original age ou
falha; um falso positivo apenas custa tempo. Os estados legados A, B, C, E e F do levantamento histórico
continuam sendo tratados pelo mesmo código, com as mesmas validações (labels, imagem, volumes anônimos,
saúde, rollback).

### 4.2 Cadastro de serviços em lote por role (D2)

`add_service.yml` continua sendo chamado pelas roles com o mesmo padrão documentado no `readme.md`
(`with_dict: "{{ services }}"` + `loop_control.extended`). Nenhuma role muda.

Na **primeira** iteração (`ansible_loop.first`), quando o fast path está ligado, é incluído
`services/add_services_batch.yml`, que processa todos os serviços de `ansible_loop.allitems` (na mesma ordem):

1. **Validação/normalização** (`korp_service_plan`, filtro Python puro): mesmos padrões de `vars_validation.yml`
   (`kv_skip`, `oauth_client.skip`, `db.name`, sufixo de banco) e mesma mensagem de erro; atualiza o fact
   `services` como antes. Segredos gerados com a mesma expressão (`10000 | random | to_uuid | upper`).
2. **KV**: templates renderizados no controlador (mesmos arquivos `consul_kv/<serviço>.json.j2`, com
   `service_vars`/`secret`/`service_name` passados por `template_vars`); um único módulo
   `korp_consul_kv_batch` faz, por chave e na mesma ordem: leitura, merge com **a mesma função** de
   `consul_kv.py` (movida para `module_utils/korp_kv_merge.py`), escrita somente se o texto mudou
   (como `community.general.consul_kv`), criação com `cas=0`, formatação idêntica a `to_nice_json(indent=2)`.
   O "vazamento" do fact `custom_kv_overwrite` entre serviços/roles é reproduzido (comportamento existente
   do qual chamadas posteriores, como o KV do `Viasoft.ELT`, dependem).
3. **OAuth**: lê o `Authorization.Secret` final do Consul (como `ensure_client`), SHA-256/base64 por filtro,
   renderiza o **mesmo** `add_oauth_client.sql.j2` por serviço e executa **um** `mssql_script` com lotes `GO`.
4. **Bancos**: MSSQL — mesmo `create_db_mssql.j2` por banco, em um `mssql_script`; Postgres — o mesmo comando
   por banco, em um `shell` com `set -e`.
5. **Diretórios de volume**: `stat` + criação somente se ausente (mesma semântica de `ensure_volume_folder.yml`).

As iterações seguintes do loop não executam nada além dos cabeçalhos pulados. `compose_and_mapping`
continua na última iteração, inalterado.

Diferença conhecida (somente em falha): o original intercala KV→OAuth→banco por serviço; o lote faz
KV de todos → OAuth de todos → bancos de todos. Em caso de falha no meio, o estado parcial é diferente,
mas a reexecução converge para o mesmo estado final (todas as operações são idempotentes). Falhas de
validação de variáveis agora ocorrem **antes** de qualquer escrita (fail-fast).

### 4.3 Chave de desligamento (D3)

`korp_setup_fast_path` (padrão `true`, em `roles/utils/defaults/main.yml`). `setup.sh fast_path=false` repassa o
valor; com `false` todas as tarefas originais são executadas exatamente como antes. Não exige troca de
branch nem preparação manual.

### 4.4 O que não muda

Infraestrutura, provisioning, ordem das roles, dependências `meta`, templates de compose/KV/SQL, formato do
`installed_apps.yml`, `update.yml`, `remove.yml`, `uninstall-version.yml`, rótulos/nomes de projeto,
transições de imagem permitidas, bugs latentes documentados (B1–B13 no levantamento) — preservados de propósito.

## 5. Compatibilidade

* Estados legados (A–N do levantamento histórico): A/B/C/E/F disparam o caminho original; G/H/I/J/K/L/M/N não eram
  tratados e continuam idênticos (nenhum código novo age sobre eles).
* Primeira execução sobre servidores antigos (antes de DEVO-5167/DEVO-7182): mesma lógica do original; o fast path só
  pula etapas cuja execução original seria sem efeito.
* As duas releases recebem a mesma infraestrutura de código (os arquivos de reconciliação são idênticos byte a byte
  nas duas linhas); diferenças entre releases (roles, temporal/svix, logística, setup.sh) não são tocadas.

## 6. Verificação

1. Testes unitários (stdlib `unittest`) para filtros, merge de KV, classificação de compose e módulo de KV (com Consul
   falso), incluindo comparação com a implementação original.
2. Ambiente isolado (`tests/sim`): host Ubuntu 22.04 com Docker 24.0.2/Compose 2.18.1/Ansible 2.17.14, Consul/Postgres reais
   (via role de infraestrutura), MSSQL real, gateway simulado, imagens de aplicação falsas. Mesmo ponto de entrada
   (`setup.sh` do commit testado). Cenários: instalação 2024.2; atualização 2024.2→2025.1; reexecução; estados
   legados reais produzidos pelos commits históricos (`repro/devo-7182*-old`) e estados construídos (parciais, backup).
3. Comparação de estado final original × otimizado a partir do mesmo snapshot (KV, tabelas OAuth, bancos,
   arquivos, containers), mascarando apenas segredos aleatórios de serviços novos.
4. QA12 real: bloqueada nesta sessão por permissões do ambiente de execução (ver relatório); comandos prontos
   documentados.
