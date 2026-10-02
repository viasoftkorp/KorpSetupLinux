# Ambiente isolado de testes do setup (`tests/sim`)

Reproduz, numa máquina de desenvolvimento com Docker, um servidor Linux Korp para executar o **ponto de
entrada real** (`setup.sh` → `bootstrap-playbook.yml` → `main.yml`) de qualquer commit, medir o tempo e
comparar o estado final entre duas versões do código. Não acessa nenhum servidor real nem o gateway da Korp.

## O que é real e o que é simulado

| Componente | No ambiente isolado |
|---|---|
| SO / ferramentas | Ubuntu 22.04, Docker 24.0.2, Compose 2.18.1, Ansible do PPA oficial (ansible-core 2.17), community.docker 5.3.0 — mesmas versões da QA12 |
| `setup.sh`, playbooks, roles | **reais**, do commit testado (clonado de um espelho local em vez do GitHub) |
| Consul, Postgres, RabbitMQ, Redis, nginx, fabio | **reais** (imagens públicas, criadas pela role `infrastructure`) |
| SQL Server | **real** (`mcr.microsoft.com/mssql/server:2022-latest`), com as tabelas do IdentityServer que o `Viasoft.Authentication` criaria |
| Gateway da Korp (`gateway_url`) e portal local (`/oauth/...`) | **simulados** (`gateway/mock_gateway.py`) |
| Imagens privadas dos aplicativos | **simuladas**: uma imagem mínima que só fica em execução (`fake-image/`) é marcada com cada nome/tag usado nos composes |
| `docker_login` | **stub** (`stubs/docker_login.py`, só no ambiente isolado): não há credenciais reais |
| `add-apt-repository` e `ansible-galaxy collection install` do `setup.sh` | **shims** (`shims/`): apenas rede externa (Launchpad/Galaxy), idênticos nas duas versões; a coleção community.docker 5.3.0 é fixada pelo ambiente |
| role `provisioning` | **não executada** (`ANSIBLE_SKIP_TAGS=provisioning`): instala pacotes do SO, salt e zabbix e depende de systemd; o host já sai com o estado que ela produziria |

Consequências: os tempos medidos aqui **não incluem** download de imagens dos aplicativos, provisioning,
latência de rede até um SQL Server remoto nem tempo de inicialização real dos serviços .NET. Medem o
trabalho de orquestração do setup (tarefas Ansible, Consul, SQL, Docker/Compose), que é onde o
otimização atua.

## Pré-requisitos

Docker com suporte a containers privilegiados, ~25 GB livres, acesso à internet (Docker Hub, PPA do Ansible,
Ansible Galaxy) e `git`.

## Uso

```bash
cd tests/sim
./simctl.sh build                      # imagens do host isolado e da imagem falsa, certificados, coleção com stub
./simctl.sh infra-up                   # rede, SQL Server e gateway simulado
./simctl.sh mirror ../..               # espelho git local servido como github.com/viasoftkorp/KorpSetupLinux
./simctl.sh host-up sim1 && ./simctl.sh seed sim1 && ./simctl.sh pull-public sim1
./simctl.sh snapshot sim1 seeded       # estado "servidor provisionado, sem setup"

# instalação 2024.2 com o código original (ref/branch presente no espelho)
./simctl.sh version 2024.2.0
SIM_REF=<ref> ./simctl.sh setup sim1 s1-orig.log branch_name=<ref> token=simtoken \
    skip_salt_test=true should_update_rabbitmq=true apps=vendas,ERP,fiscal
./simctl.sh timing .work/runs/s1-orig.log
./simctl.sh dump sim1 .work/dumps/s1-orig.json
```

Comparar original × otimizado a partir do mesmo estado:

```bash
./simctl.sh restore sim1 <snapshot>; ./simctl.sh dump sim1 .work/dumps/initial.json
SIM_REF=<original> ./simctl.sh setup sim1 a.log branch_name=<original> token=simtoken custom_tags=update ...
./simctl.sh dump sim1 .work/dumps/a.json
./simctl.sh restore sim1 <snapshot>
SIM_REF=<otimizado> ./simctl.sh setup sim1 b.log branch_name=<otimizado> token=simtoken custom_tags=update ...
./simctl.sh dump sim1 .work/dumps/b.json
./simctl.sh compare .work/dumps/initial.json .work/dumps/a.json .work/dumps/b.json
```

`compare` aceita diferenças apenas em segredos gerados aleatoriamente para KVs/clientes criados na própria
execução e exige que segredos pré-existentes continuem idênticos.
