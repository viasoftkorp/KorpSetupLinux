# Temporal Role — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Criar a role Ansible `temporal` que provisiona o Temporal.io (PostgreSQL + ElasticSearch) com dois namespaces (`prod` e `hmlg`), configura a UI com nginx+basic_auth e registra as credenciais de endereço no KV Global do Consul.

**Architecture:** Role standalone com compose principal (Temporal + ES, iniciado pela role) e compose de UI (nginx + temporal-ui, apenas configurado). Usuário PostgreSQL dedicado criado no PostgreSQL compartilhado existente. Senhas geradas no `inventory-playbook.yml` e armazenadas no inventário Ansible Vault encriptado.

**Tech Stack:** Ansible, Docker Compose v2, `temporalio/auto-setup:1.31.0`, Elasticsearch 7.17.27, `community.general.htpasswd`, `community.docker.docker_compose_v2`

**Spec:** `docs/superpowers/specs/2026-05-27-temporal-role-design.md`

---

## Mapa de arquivos

| Ação | Arquivo |
|---|---|
| Criar | `roles/temporal/vars/main.yml` |
| Criar | `roles/temporal/files/configs/dynamicconfig/development-sql.yaml` |
| Criar | `roles/temporal/files/configs/nginx/nginx.conf` |
| Criar | `roles/temporal/templates/consul_kv/global.json.j2` |
| Criar | `roles/temporal/templates/composes/temporal-compose.yml.j2` |
| Criar | `roles/temporal/templates/composes/temporal-ui-compose.yml.j2` |
| Criar | `roles/temporal/tasks/main.yml` |
| Modificar | `inventory-playbook.yml` (adicionar bloco `temporal` no combine) |
| Modificar | `main.yml` (adicionar role `temporal`) |

---

## Task 1: Scaffold da estrutura de diretórios

**Files:**
- Criar: `roles/temporal/` (estrutura de diretórios)

- [ ] **Criar a árvore de diretórios da role**

```bash
mkdir -p roles/temporal/tasks
mkdir -p roles/temporal/vars
mkdir -p roles/temporal/templates/composes
mkdir -p roles/temporal/templates/consul_kv
mkdir -p roles/temporal/files/configs/dynamicconfig
mkdir -p roles/temporal/files/configs/nginx
```

- [ ] **Verificar estrutura criada**

```bash
find roles/temporal -type d
```

Resultado esperado:
```
roles/temporal
roles/temporal/tasks
roles/temporal/vars
roles/temporal/templates
roles/temporal/templates/composes
roles/temporal/templates/consul_kv
roles/temporal/files
roles/temporal/files/configs
roles/temporal/files/configs/dynamicconfig
roles/temporal/files/configs/nginx
```

- [ ] **Commit**

```bash
git add roles/temporal/
git commit -m "feat(temporal): scaffold role directory structure"
```

---

## Task 2: `vars/main.yml`

**Files:**
- Criar: `roles/temporal/vars/main.yml`

- [ ] **Criar o arquivo de variáveis**

Conteúdo de `roles/temporal/vars/main.yml`:

```yaml
temporal_version: "1.31.0"
temporal_admintools_version: "1.31.0"
temporal_ui_version: "2.49.1"
temporal_elasticsearch_version: "7.17.27"
temporal_nginx_version: "1.29.4"
temporal_namespaces:
  - prod
  - hmlg
temporal_postgres_user: "temporal"
```

- [ ] **Lint**

```bash
ansible-lint roles/temporal/vars/main.yml
```

Resultado esperado: sem erros.

- [ ] **Commit**

```bash
git add roles/temporal/vars/main.yml
git commit -m "feat(temporal): add role vars with image versions and namespaces"
```

---

## Task 3: Arquivos de configuração estáticos

**Files:**
- Criar: `roles/temporal/files/configs/dynamicconfig/development-sql.yaml`
- Criar: `roles/temporal/files/configs/nginx/nginx.conf`

- [ ] **Criar `development-sql.yaml`**

Conteúdo de `roles/temporal/files/configs/dynamicconfig/development-sql.yaml`:

```yaml
limit.maxIDLength:
  - value: 255
    constraints: {}
system.forceSearchAttributesCacheRefreshOnRead:
  - value: false # Dev setup only. Please don't turn this on in production.
    constraints: {}
```

- [ ] **Criar `nginx.conf`**

Conteúdo de `roles/temporal/files/configs/nginx/nginx.conf`:

```nginx
events {}

http {
    server {
        listen 80;

        auth_basic "Area Restrita";
        auth_basic_user_file /etc/nginx/.htpasswd;

        location / {
            proxy_pass http://temporal-ui:8080;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
        }
    }
}
```

- [ ] **Commit**

```bash
git add roles/temporal/files/
git commit -m "feat(temporal): add static config files (dynamicconfig, nginx)"
```

---

## Task 4: Template Consul KV

**Files:**
- Criar: `roles/temporal/templates/consul_kv/global.json.j2`

- [ ] **Criar `global.json.j2`**

Conteúdo de `roles/temporal/templates/consul_kv/global.json.j2`:

```json
{
  "Temporal": {
    "Hmlg": {
      "Address": "temporal:7233",
      "Namespace": "hmlg"
    },
    "Prd": {
      "Address": "temporal:7233",
      "Namespace": "prd"
    }
  }
}
```

> Este template contém apenas a seção `Temporal`. O módulo `consul_kv.py` faz merge com o KV Global existente (que contém Serilog, ServiceBus, etc.), substituindo somente a chave `Temporal`. Ambos os namespaces apontam para `temporal:7233` — o mesmo servidor, com namespace diferente.

- [ ] **Commit**

```bash
git add roles/temporal/templates/consul_kv/global.json.j2
git commit -m "feat(temporal): add consul KV template for Global Temporal config"
```

---

## Task 5: Template do compose principal

**Files:**
- Criar: `roles/temporal/templates/composes/temporal-compose.yml.j2`

- [ ] **Criar `temporal-compose.yml.j2`**

Conteúdo de `roles/temporal/templates/composes/temporal-compose.yml.j2`:

```yaml
networks:
  servicos:
    external:
      name: servicos

services:
  temporal-elasticsearch:
    image: elasticsearch:{{ temporal_elasticsearch_version }}
    container_name: temporal-elasticsearch
    environment:
      - cluster.routing.allocation.disk.threshold_enabled=true
      - cluster.routing.allocation.disk.watermark.low=512mb
      - cluster.routing.allocation.disk.watermark.high=256mb
      - cluster.routing.allocation.disk.watermark.flood_stage=128mb
      - discovery.type=single-node
      - ES_JAVA_OPTS=-Xms256m -Xmx256m
      - xpack.security.enabled=false
    volumes:
      - {{ dados_docker_dir_path }}/temporal-elasticsearch:/usr/share/elasticsearch/data
    networks:
      - servicos
    expose:
      - 9200
    healthcheck:
      test: ["CMD-SHELL", "curl -f http://localhost:9200/_cluster/health?wait_for_status=yellow&timeout=1s || exit 1"]
      interval: 5s
      timeout: 5s
      retries: 60
      start_period: 30s

  temporal:
    container_name: temporal
    image: temporalio/auto-setup:{{ temporal_version }}
    restart: always
    depends_on:
      temporal-elasticsearch:
        condition: service_healthy
    environment:
      - DB=postgres12
      - DB_PORT=5432
      - POSTGRES_USER={{ temporal_postgres_user }}
      - POSTGRES_PWD={{ temporal.postgres_password }}
      - POSTGRES_SEEDS={{ postgres_container_name }}
      - DYNAMIC_CONFIG_FILE_PATH=config/dynamicconfig/development-sql.yaml
      - ENABLE_ES=true
      - ES_SEEDS=temporal-elasticsearch
      - ES_VERSION=v7
      - TEMPORAL_ADDRESS=temporal:7233
      - TEMPORAL_CLI_ADDRESS=temporal:7233
    networks:
      - servicos
    expose:
      - 7233
    volumes:
      - {{ config_dir_path }}/temporalio/dynamicconfig:/etc/temporal/config/dynamicconfig

  temporal-admin-tools:
    container_name: temporal-admin-tools
    image: temporalio/admin-tools:{{ temporal_admintools_version }}
    restart: always
    depends_on:
      - temporal
    environment:
      - TEMPORAL_ADDRESS=temporal:7233
      - TEMPORAL_CLI_ADDRESS=temporal:7233
    networks:
      - servicos
    stdin_open: true
    tty: true
```

- [ ] **Lint**

```bash
ansible-lint roles/temporal/templates/composes/temporal-compose.yml.j2
```

Resultado esperado: sem erros de sintaxe Ansible (warnings sobre Jinja2 em YAML são esperados).

- [ ] **Commit**

```bash
git add roles/temporal/templates/composes/temporal-compose.yml.j2
git commit -m "feat(temporal): add main compose template (temporal + elasticsearch)"
```

---

## Task 6: Template do compose de UI

**Files:**
- Criar: `roles/temporal/templates/composes/temporal-ui-compose.yml.j2`

- [ ] **Criar `temporal-ui-compose.yml.j2`**

Conteúdo de `roles/temporal/templates/composes/temporal-ui-compose.yml.j2`:

```yaml
# Este compose NÃO é iniciado pela role temporal.
# Para subir a UI (após o Temporal estar saudável):
#   docker compose -f {{ compose_dir_path }}/temporal-ui-compose.yml up -d
networks:
  servicos:
    external:
      name: servicos

services:
  temporal-ui:
    container_name: temporal-ui
    image: temporalio/ui:{{ temporal_ui_version }}
    restart: always
    environment:
      - TEMPORAL_ADDRESS=temporal:7233
      - TEMPORAL_CORS_ORIGINS=http://localhost:3000
    networks:
      - servicos
    expose:
      - 8080

  nginx-temporal:
    container_name: nginx-temporal
    image: nginx:{{ temporal_nginx_version }}
    restart: always
    ports:
      - "18801:80"
    volumes:
      - {{ config_dir_path }}/temporalio/nginx/nginx.conf:/etc/nginx/nginx.conf
      - {{ config_dir_path }}/temporalio/nginx/basic_auth_temporal_ui:/etc/nginx/.htpasswd
    networks:
      - servicos
    depends_on:
      - temporal-ui
```

- [ ] **Commit**

```bash
git add roles/temporal/templates/composes/temporal-ui-compose.yml.j2
git commit -m "feat(temporal): add UI compose template (temporal-ui + nginx basic auth)"
```

---

## Task 7: `tasks/main.yml`

**Files:**
- Criar: `roles/temporal/tasks/main.yml`

- [ ] **Criar `tasks/main.yml`**

Conteúdo de `roles/temporal/tasks/main.yml`:

```yaml
- name: Instalação de dependência bcrypt para htpasswd
  ansible.builtin.pip:
    name: bcrypt

- name: Criação de usuário PostgreSQL para Temporal
  ansible.builtin.shell: |
    docker exec -i "{{ postgres_container_name }}" psql -U postgres -c \
    "DO \$\$ BEGIN \
      IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{{ temporal_postgres_user }}') \
      THEN EXECUTE 'CREATE USER \"{{ temporal_postgres_user }}\" WITH PASSWORD ''{{ temporal.postgres_password }}'' LOGIN CREATEDB;'; \
    END IF; \
    END \$\$;"

- name: Criação de diretórios de dados e configuração do Temporal
  ansible.builtin.file:
    path: "{{ item }}"
    state: directory
    mode: '0755'
    owner: "{{ linux_korp.user }}"
    group: root
  loop:
    - "{{ dados_docker_dir_path }}/temporal-elasticsearch"
    - "{{ config_dir_path }}/temporalio/dynamicconfig"
    - "{{ config_dir_path }}/temporalio/nginx"

- name: Cópia de dynamicconfig do Temporal
  ansible.builtin.copy:
    src: configs/dynamicconfig/development-sql.yaml
    dest: "{{ config_dir_path }}/temporalio/dynamicconfig/development-sql.yaml"
    owner: "{{ linux_korp.user }}"
    group: root
    mode: '0644'

- name: Cópia de configuração nginx para Temporal UI
  ansible.builtin.copy:
    src: configs/nginx/nginx.conf
    dest: "{{ config_dir_path }}/temporalio/nginx/nginx.conf"
    owner: "{{ linux_korp.user }}"
    group: root
    mode: '0644'

- name: Geração de htpasswd para Temporal UI
  community.general.htpasswd:
    path: "{{ config_dir_path }}/temporalio/nginx/basic_auth_temporal_ui"
    name: admin
    password: "{{ temporal.nginx_password }}"
    crypt_scheme: bcrypt

- name: Configuração de permissões do htpasswd
  ansible.builtin.file:
    path: "{{ config_dir_path }}/temporalio/nginx/basic_auth_temporal_ui"
    owner: "{{ linux_korp.user }}"
    group: root
    mode: '0640'

- name: Configuração e transferência de composes do Temporal
  ansible.builtin.template:
    dest: "{{ compose_dir_path }}/{{ item[:-3] | basename }}"
    src: "composes/{{ item | basename }}"
    owner: "{{ linux_korp.user }}"
    group: root
    mode: '0644'
  loop: "{{ lookup('fileglob', 'templates/composes/*', wantlist=True) | select('search', '.yml.j2') }}"

- name: Criação e inicialização do Temporal
  community.docker.docker_compose_v2:
    project_src: "{{ compose_dir_path }}/"
    env_files: ["{{ docker_env_file_path }}"]
    files:
      - temporal-compose.yml

- name: Aguardar Temporal estar saudável
  ansible.builtin.command: >
    docker exec temporal-admin-tools
    temporal operator cluster health --address temporal:7233
  register: temporal_health
  retries: 30
  delay: 10
  until: temporal_health.rc == 0

- name: Criação de namespaces do Temporal
  ansible.builtin.shell: |
    docker exec temporal-admin-tools \
    temporal operator namespace describe -n {{ item }} --address temporal:7233 \
    || docker exec temporal-admin-tools \
    temporal operator namespace create -n {{ item }} --address temporal:7233
  loop: "{{ temporal_namespaces }}"

- name: Garantia de kv no consul para Temporal (Global)
  ansible.builtin.include_role:
    name: utils
    tasks_from: consul_kv/ensure_kv
  vars:
    service_name: Global
    keys_to_overwrite: ["Temporal"]
```

- [ ] **Lint**

```bash
ansible-lint roles/temporal/tasks/main.yml
```

Resultado esperado: sem erros. Warnings sobre `ansible.builtin.shell` (use `command` instead) podem aparecer na task de namespace — são aceitáveis pois precisamos do `||` (operador shell).

- [ ] **Syntax check**

```bash
ansible-playbook --syntax-check main.yml
```

Resultado esperado: `playbook: main.yml` sem erros.

- [ ] **Commit**

```bash
git add roles/temporal/tasks/main.yml
git commit -m "feat(temporal): add role tasks (postgres user, dirs, configs, compose, namespaces, consul kv)"
```

---

## Task 8: Atualizar `inventory-playbook.yml`

**Files:**
- Modificar: `inventory-playbook.yml` (linhas 587–588)

> O bloco `shrink_inventory` (task "Definição dos valores de inventário") constrói o inventário com senhas geradas na primeira execução. Adicionar o bloco `temporal` após a chave `watchtower_cron` (linha 587), antes do fechamento do combine.

- [ ] **Localizar o ponto de inserção** — confirmar linha 587

```bash
grep -n "watchtower_cron" inventory-playbook.yml
```

Resultado esperado: linha próxima a `587`.

- [ ] **Adicionar bloco `temporal` ao combine**

Localizar o trecho (linhas ~587–588):

```yaml
            'watchtower_cron': shrink_inventory.watchtower_cron | default ('0 0 3 * * *')
          }, recursive=True) }}"
```

Substituir por:

```yaml
            'watchtower_cron': shrink_inventory.watchtower_cron | default ('0 0 3 * * *'),
            'temporal': {
              'postgres_password': shrink_inventory.temporal.postgres_password | default(lookup('community.general.random_string', length=16, special=False)),
              'nginx_password': shrink_inventory.temporal.nginx_password | default(lookup('community.general.random_string', length=16, special=False))
            }
          }, recursive=True) }}"
```

- [ ] **Syntax check do playbook de inventário**

```bash
ansible-playbook --syntax-check inventory-playbook.yml
```

Resultado esperado: sem erros de sintaxe.

- [ ] **Commit**

```bash
git add inventory-playbook.yml
git commit -m "feat(temporal): add temporal passwords to inventory-playbook"
```

---

## Task 9: Adicionar role `temporal` ao `main.yml`

**Files:**
- Modificar: `main.yml`

> A role `temporal` deve rodar após `infrastructure` (PostgreSQL e Consul já precisam estar up) e antes de `finishing`. Adicionar com tag própria `temporal` e também nas tags `default-setup` e `install`.

- [ ] **Localizar ponto de inserção** — após `infrastructure-desktop`, antes de `Instalação de apps padrões`

```bash
grep -n "infrastructure-desktop\|apps padrões" main.yml
```

- [ ] **Adicionar bloco da role temporal**

Localizar o trecho em `main.yml`:

```yaml
        - name: Infrastructure-desktop
          ansible.builtin.import_role:
            name: infrastructure-desktop
          tags:
            - infrastructure-desktop
            - default-setup
            - update
            - install

        - name: Instalação de apps padrões
```

Substituir por:

```yaml
        - name: Infrastructure-desktop
          ansible.builtin.import_role:
            name: infrastructure-desktop
          tags:
            - infrastructure-desktop
            - default-setup
            - update
            - install

        - name: Temporal
          ansible.builtin.import_role:
            name: temporal
          tags:
            - temporal
            - default-setup
            - install

        - name: Instalação de apps padrões
```

- [ ] **Syntax check**

```bash
ansible-playbook --syntax-check main.yml
```

Resultado esperado: `playbook: main.yml` sem erros.

- [ ] **Lint geral**

```bash
ansible-lint main.yml
```

Resultado esperado: sem erros novos introduzidos pela mudança.

- [ ] **Commit**

```bash
git add main.yml
git commit -m "feat(temporal): register temporal role in main playbook"
```

---

## Verificação final

- [ ] **Lint completo da role**

```bash
ansible-lint roles/temporal/
```

Resultado esperado: sem erros. Warnings sobre `shell` são aceitáveis na task de namespace criação.

- [ ] **Syntax check final**

```bash
ansible-playbook --syntax-check main.yml
ansible-playbook --syntax-check inventory-playbook.yml
```

Resultado esperado: ambos sem erros.

- [ ] **Verificar que todos os arquivos da role estão presentes**

```bash
find roles/temporal -type f | sort
```

Resultado esperado:
```
roles/temporal/files/configs/dynamicconfig/development-sql.yaml
roles/temporal/files/configs/nginx/nginx.conf
roles/temporal/tasks/main.yml
roles/temporal/templates/composes/temporal-compose.yml.j2
roles/temporal/templates/composes/temporal-ui-compose.yml.j2
roles/temporal/templates/consul_kv/global.json.j2
roles/temporal/vars/main.yml
```
