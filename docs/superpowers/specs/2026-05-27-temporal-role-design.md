# Design: Role Temporal — KorpSetupLinux

**Data:** 2026-05-27  
**Status:** Aprovado

---

## Contexto

O setup provisionador do servidor Linux (KorpSetupLinux) precisa incluir o Temporal.io como orquestrador de workflows para o ERP Korp. O setup já provisiona PostgreSQL e todos os serviços rodam na mesma rede Docker (`servicos`).

---

## Decisões

| Decisão | Escolha |
|---|---|
| Imagem Temporal | `temporalio/auto-setup` (alinhado com temporal-example) |
| PostgreSQL | Compartilhado (existente), usuário PostgreSQL dedicado `temporal` |
| ElasticSearch | Container dedicado `temporal-elasticsearch` no compose da role |
| Namespaces | Dois namespaces (`prod` e `hmlg`) no mesmo servidor Temporal |
| Porta gRPC (7233) | Apenas `expose` — interno à rede `servicos` |
| Porta nginx UI | `18801:80` |
| Secrets | Ansible Vault — inventário local (`temporal.postgres_password`, `temporal.nginx_password`) |

---

## Estrutura da Role

```
roles/temporal/
├── tasks/
│   └── main.yml
├── templates/
│   ├── composes/
│   │   ├── temporal-compose.yml.j2       # Temporal + ES (iniciado pela role)
│   │   └── temporal-ui-compose.yml.j2    # UI + nginx (só configurado, não iniciado)
│   └── consul_kv/
│       └── global.json.j2                # Seção Temporal do KV Global
├── files/
│   └── configs/
│       ├── dynamicconfig/
│       │   └── development-sql.yaml      # Config dinâmica Temporal
│       └── nginx/
│           └── nginx.conf                # Config nginx proxy UI
└── vars/
    └── main.yml                          # Versões de imagens e namespaces
```

### Destinos no servidor

| Arquivo | Destino |
|---|---|
| `temporal-compose.yml.j2` | `{{ compose_dir_path }}/temporal-compose.yml` |
| `temporal-ui-compose.yml.j2` | `{{ compose_dir_path }}/temporal-ui-compose.yml` |
| `development-sql.yaml` | `{{ config_dir_path }}/temporalio/dynamicconfig/development-sql.yaml` |
| `nginx.conf` | `{{ config_dir_path }}/temporalio/nginx/nginx.conf` |
| `.htpasswd` (do vault) | `{{ config_dir_path }}/temporalio/nginx/basic_auth_temporal_ui` |
| Volume ES | `{{ dados_docker_dir_path }}/temporal-elasticsearch/` |

---

## Variáveis

### `vars/main.yml` (não sensível, versionado)

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

O usuário PostgreSQL é estático (`temporal`) e não sensível — fica em `vars/main.yml`.

### Ansible Vault — inventário encriptado (`/etc/korp/ansible/inventory.yml`)

Mesmo mecanismo usado por todas as outras senhas do setup (ex: `postgres.korp_password`, `redis.password`). As variáveis ficam na seção `temporal` do inventário, geradas automaticamente no `inventory-playbook.yml` se não existirem.

| Variável de inventário | Geração | Descrição |
|---|---|---|
| `temporal.postgres_password` | `lookup('community.general.random_string', length=16, special=False)` | Senha do usuário PostgreSQL `temporal` |
| `temporal.nginx_password` | `lookup('community.general.random_string', length=16, special=False)` | Senha do usuário `admin` para a UI nginx (plain text; a role gera o htpasswd) |

O arquivo `.htpasswd` **não** é armazenado no inventário — a role gera ele on-the-fly via módulo `community.general.htpasswd` a partir de `temporal.nginx_password`.

### Adição ao `inventory-playbook.yml`

No bloco `Definição dos valores de inventário` (task que constrói `shrink_inventory`), adicionar a chave `temporal`:

```yaml
'temporal': {
  'postgres_password': shrink_inventory.temporal.postgres_password | default(lookup('community.general.random_string', length=16, special=False)),
  'nginx_password': shrink_inventory.temporal.nginx_password | default(lookup('community.general.random_string', length=16, special=False))
}
```

---

## Sequência de Tasks (`tasks/main.yml`)

1. **Criar usuário PostgreSQL** — `docker exec {{ postgres_container_name }} psql -U postgres` cria o user `{{ temporal_postgres_user }}` com `CREATEDB` e senha `{{ temporal.postgres_password }}` (idempotente via `DO $$ BEGIN IF NOT EXISTS ...`)
2. **Criar diretórios de dados e config**:
   - `{{ dados_docker_dir_path }}/temporal-elasticsearch/`
   - `{{ config_dir_path }}/temporalio/dynamicconfig/`
   - `{{ config_dir_path }}/temporalio/nginx/`
3. **Copiar `development-sql.yaml`** — `ansible.builtin.copy` para `{{ config_dir_path }}/temporalio/dynamicconfig/`
4. **Copiar `nginx.conf`** — `ansible.builtin.copy` para `{{ config_dir_path }}/temporalio/nginx/`
5. **Gerar `.htpasswd`** — `community.general.htpasswd` com `name: admin`, `password: {{ temporal.nginx_password }}`, `crypt_scheme: bcrypt`, destino `{{ config_dir_path }}/temporalio/nginx/basic_auth_temporal_ui` (idempotente — módulo só altera se senha mudou)
6. **Template `temporal-compose.yml.j2`** → `{{ compose_dir_path }}/temporal-compose.yml`
7. **Template `temporal-ui-compose.yml.j2`** → `{{ compose_dir_path }}/temporal-ui-compose.yml` *(apenas configura, não sobe)*
8. **Subir `temporal-compose.yml`** — `community.docker.docker_compose_v2`
9. **Aguardar Temporal healthy** — `ansible.builtin.command: docker exec temporal-admin-tools temporal operator cluster health --address temporal:7233` com retries
10. **Criar namespaces** — loop sobre `temporal_namespaces`, `docker exec temporal-admin-tools temporal operator namespace create -n {{ item }} --address temporal:7233` (idempotente: checa com `describe` antes de criar)
11. **Atualizar KV Global do Consul** — `include_role: utils tasks_from: consul_kv/ensure_kv` com `service_name: Global` e `keys_to_overwrite: ["Temporal"]`

---

## Compose Principal (`temporal-compose.yml.j2`)

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

---

## Compose UI (`temporal-ui-compose.yml.j2`)

Apenas configurado pela role. Para subir (após Temporal estar rodando): `docker compose -f temporal-ui-compose.yml up -d`.

Não inclui `depends_on: temporal` — o container `temporal` está em outro compose file, e o Docker Compose não suporta dependências cross-file. O operador deve garantir que o Temporal esteja saudável antes de subir a UI.

```yaml
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

---

## Consul KV (`templates/consul_kv/global.json.j2`)

Contém apenas a seção `Temporal`. O módulo `consul_kv.py` faz merge com o KV Global existente, substituindo somente a chave `Temporal`.

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

---

## Nginx Config (`files/configs/nginx/nginx.conf`)

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

---

## Integração com `main.yml`

A role `temporal` deve ser adicionada ao `main.yml` com tags adequadas (após `infrastructure`, pois depende do PostgreSQL e Consul):

```yaml
- name: Temporal
  ansible.builtin.import_role:
    name: temporal
  tags:
    - temporal
    - default-setup
    - install
```

---

## Notas de Implementação

- O `temporal-ui-compose.yml` **não é iniciado** pela role — é apenas colocado em `compose_dir_path` para uso manual.
- O usuário PostgreSQL `temporal` precisa ter `CREATEDB` para que `auto-setup` consiga criar os databases `temporal` e `temporal_visibility`.
- A idempotência do namespace é garantida checando `temporal operator namespace describe` antes de criar.
- O ES não é exposto externamente (apenas `expose: 9200`).
- O `.htpasswd` é gerado pela role via `community.general.htpasswd` (bcrypt) a partir de `temporal.nginx_password` — não precisa ser pré-gerado externamente.
- As senhas (`temporal.postgres_password` e `temporal.nginx_password`) são geradas automaticamente no `inventory-playbook.yml` na primeira execução e ficam no inventário encriptado pelo Ansible Vault em `/etc/korp/ansible/inventory.yml`.
- O módulo `passlib` (necessário para `community.general.htpasswd` com bcrypt) já é instalado no `provisioning` role — sem dependência nova.
