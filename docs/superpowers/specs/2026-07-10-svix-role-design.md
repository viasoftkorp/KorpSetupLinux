# Design: Role Svix — KorpSetupLinux

**Data:** 2026-07-10  
**Status:** Aprovado  
**Escopo:** apenas `KorpSetupLinux` (`infrastructure-setup-dev` é referência, não recebe as mudanças)

---

## Contexto

O app DEV05 (Korp.Webhook) depende do Svix Server para entrega de webhooks. A configuração inicial colocava Redis + Svix + webhook no mesmo compose do DEV05, com imagem `latest`, porta publicada, secrets reutilizando `authorization_secret` e whitelist com subnet Docker hardcoded (`172.17`).

Feedback da call (Kewin / Amos) e decisão de design: extrair Svix para uma **role dedicada**, no mesmo padrão da role `temporal` (compose próprio, secrets no inventário/vault, dependência via `meta/main.yml`).

---

## Decisões

| Decisão | Escolha |
|---|---|
| Estrutura | Role `svix` separada; DEV05 depende dela |
| Compose Svix | `svix-compose.yml` próprio (redis_svix + svix), iniciado pela role |
| Compose DEV05 | Apenas `korp-webhook` (+ frontends versionados existentes) |
| Imagem Svix | `svix/svix-server:v1.84` (versão usada na nuvem) |
| Porta 8071 | Sem `ports:` — apenas rede Docker `servicos` |
| PostgreSQL | Compartilhado; DB `Svix` (+ `db_suffix` se houver) via `utils/create_db/postgres` (user `postgres.korp_user`) |
| Redis | Container dedicado `redis_svix` no compose da role |
| Secrets | Ansible Vault / inventário: `svix.jwt_secret`, `svix.main_secret` |
| Whitelist | Substituir `172.17.0.0/16` por `{{ docker_servicos_network_ip_address_start \| default('172.18') }}.0.0/16`; manter `127.0.0.1/32` e `192.168.0.0/16` |
| BaseUrl webhook | `http://svix:8071/` (nome do container na rede `servicos`) |
| Gatilho | `roles/DEV05/meta/main.yml` → `dependencies: [svix]` (igual `compras` → `temporal`) |

---

## Estrutura da Role

```
roles/svix/
├── tasks/
│   └── main.yml
├── templates/
│   └── composes/
│       └── svix-compose.yml.j2
├── vars/
│   └── main.yml
└── meta/
    └── main.yml              # sem dependencies

roles/DEV05/
├── meta/
│   └── main.yml              # dependencies: [svix]
├── tasks/
│   └── main.yml              # só add_service (sem create_db do Svix)
├── vars/
│   └── main.yml              # só Korp.Webhook (sem svix_db_name / volume redis)
├── templates/
│   ├── composes/
│   │   ├── DEV05-compose.yml.j2          # só korp-webhook
│   │   ├── 2025.1.0/...
│   │   └── 2025.2.0/...
│   └── consul_kv/
│       └── korp.webhook.json.j2
```

### Destinos no servidor

| Arquivo | Destino |
|---|---|
| `svix-compose.yml.j2` | `{{ compose_dir_path }}/svix-compose.yml` |
| Volume Redis | `{{ dados_docker_dir_path }}/svix_redis/` |

---

## Variáveis

### `roles/svix/vars/main.yml` (não sensível, versionado)

```yaml
svix_image: "svix/svix-server:v1.84"
svix_redis_image: "docker.io/redis:7-alpine"
svix_port: "8071"
svix_db_name: "Svix"
```

O sufixo de banco segue o mesmo padrão de `vars_validation.yml`: se `db_suffix != ""`, a role faz `set_fact` de `svix_db_name` para `Svix{{ db_suffix_divider }}{{ db_suffix }}` antes do `create_db` e do template do compose.

### Ansible Vault — inventário encriptado (`/etc/korp/ansible/inventory.yml`)

Mesmo mecanismo de `temporal.postgres_password` / demais senhas do setup. Geradas automaticamente no `inventory-playbook.yml` se não existirem.

| Variável de inventário | Geração | Descrição |
|---|---|---|
| `svix.jwt_secret` | `lookup('community.general.random_string', length=32, special=False)` | `SVIX_JWT_SECRET` e `Svix.Secret` no Consul KV do webhook |
| `svix.main_secret` | `lookup('community.general.random_string', length=32, special=False)` | `SVIX_MAIN_SECRET` (criptografia interna do Svix) |

Regras: mínimo 32 caracteres; apenas letras e números (`special=False`).

### Adição ao `inventory-playbook.yml`

No bloco `Definição dos valores de inventário` (construção de `shrink_inventory`), adicionar a chave `svix` ao lado de `temporal`:

```yaml
'svix': {
  'jwt_secret': shrink_inventory.svix.jwt_secret | default(lookup('community.general.random_string', length=32, special=False)),
  'main_secret': shrink_inventory.svix.main_secret | default(lookup('community.general.random_string', length=32, special=False))
}
```

---

## Sequência de Tasks (`roles/svix/tasks/main.yml`)

1. **Garantir diretório de volume Redis** — `{{ dados_docker_dir_path }}/svix_redis`
2. **Aplicar `db_suffix`** — se `db_suffix != ""`, `svix_db_name = Svix{{ db_suffix_divider }}{{ db_suffix }}`
3. **Criar database PostgreSQL** — `include_role: utils tasks_from: create_db/postgres` com `db_name: "{{ svix_db_name }}"`
4. **Template `svix-compose.yml.j2`** → `{{ compose_dir_path }}/svix-compose.yml`
5. **Subir compose** — `community.docker.docker_compose_v2` com `files: [svix-compose.yml]`

---

## Compose Svix (`svix-compose.yml.j2`)

Serviços:

- **redis_svix** — Redis 7 alpine, volume persistente, healthcheck `redis-cli ping`, rede `servicos`
- **svix** — depende de `redis_svix` healthy; sem `ports:`; rede `servicos`

Environment do `svix`:

| Variável | Valor |
|---|---|
| `SVIX_DB_DSN` | `postgres://{{ postgres.korp_user }}:{{ postgres.korp_password }}@{{ postgres.address }}:5432/{{ svix_db_name }}` |
| `SVIX_REDIS_DSN` | `redis://redis_svix:6379` |
| `SVIX_WHITELIST_SUBNETS` | `["127.0.0.1/32","{{ docker_servicos_network_ip_address_start \| default('172.18') }}.0.0/16","192.168.0.0/16"]` |
| `SVIX_JWT_SECRET` | `{{ svix.jwt_secret }}` |
| `SVIX_MAIN_SECRET` | `{{ svix.main_secret }}` |
| `SVIX_WHITELABEL_HEADERS` | `true` |
| `SVIX_LOG_LEVEL` | `info` |
| `SVIX_PORT` | `{{ svix_port }}` |

---

## Mudanças no DEV05

### `meta/main.yml` (novo)

```yaml
dependencies:
  - role: svix
```

### `tasks/main.yml`

Remover a task `Criação de bancos de dados para SVIX` (passa a ser responsabilidade da role `svix`). Manter apenas `add_service` do Korp.Webhook.

### `vars/main.yml`

Remover `svix_db_name` e o volume `svix_redis` de `volumes_directories` do Korp.Webhook (volume criado pela role `svix`).

### `DEV05-compose.yml.j2`

Remover serviços `redis_svix` e `svix`. Manter apenas `korp-webhook` no padrão PRO09:

- `image: "{{ docker_account }}/korp.webhook:{{ version_without_build }}.x{{ docker_image_suffix }}"`
- `restart: unless-stopped`
- env: `ON_PREMISE_MODE`, `USE_SERVERGC`, `URL_CONSUL`, `CERT_FILE_PATH`
- volumes de certificados

Sem `depends_on: svix` no compose do webhook: a ordem fica garantida pela dependency Ansible (role `svix` sobe antes).

### `korp.webhook.json.j2`

```json
"Svix": {
  "Secret": "{{ svix.jwt_secret }}",
  "BaseUrl": "http://svix:8071/"
}
```

---

## Fora de escopo

- Alterações em `infrastructure-setup-dev`
- Usuário PostgreSQL dedicado para Svix (usa `korp.services`, diferente do Temporal)
- Exposição pública / reverse proxy da porta 8071
- Migração de secrets já existentes em ambientes que usaram `authorization_secret` (primeira instalação / reinstalação assume secrets novos do inventário)

---

## Critérios de aceite

1. Role `svix` sobe Redis + Svix `v1.84` sem publicar porta.
2. Secrets `svix.jwt_secret` e `svix.main_secret` são gerados no inventário (32 chars, sem especiais) e referenciados no compose e no Consul KV.
3. Whitelist usa `docker_servicos_network_ip_address_start`.
4. Instalação de DEV05 dispara a role `svix` via dependency.
5. Compose DEV05 contém apenas o webhook (e frontends versionados).
6. DB `Svix` (com `db_suffix` quando aplicável) é criado pela role `svix` via `create_db/postgres`.
