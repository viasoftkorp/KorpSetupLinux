# Validação de serviços legados via Portainer

Script Node.js que consulta a API do Portainer e identifica containers Korp/Viasoft **inválidos** segundo as regras de `scripts/global-context.md`.

## Definição de legado vs versionado

| Tipo | Critério | Exemplo |
|------|----------|---------|
| **Versionado válido** | Sufixo `-20XX.X.X` no nome **e** tag de imagem no padrão ano | `REL01-2024.2.0`, `Korp.Logistica.Picking-2024.1.0` |
| **Legado (inválido)** | Sem sufixo de versão ano | `REL01`, `login`, `portal` |
| **Legado (inválido)** | Tag de imagem numérica antiga | `1.0.x`, `2.0.x`, `3.0.x` |
| **Exceção total** | Container e tag fixos | `Korp.AtualizacaoSistema` (`1.0.x`) |
| **Exceção parcial** | `container_name` fixo, imagem versionada (`20XX.X.X.x`) | `Korp.Legacy.Frontend-router`, `Viasoft.Loader` |
| **Ignorado** | Infra de terceiros | `nginx`, `postgres`, `rabbitmq`, `consul-server`, etc. |

> **Importante:** `2024.1.0` é um serviço **versionado válido**, mesmo que não seja a versão alvo do ambiente. Só é legado quem **não** segue o padrão ano ou usa tags antigas.

## Pré-requisitos

- Node.js LTS
- Portainer CE 2.9.1 (autenticação JWT via `/api/auth`)
- Credenciais com acesso ao endpoint Docker (padrão: ID `2`)

## Configuração

Variáveis em `scripts/portainer/.env` (ou via argumentos CLI):

```env
PORTAINER_URL=http://servidor:9011
PORTAINER_USER=admin
PORTAINER_PASSWORD=sua_senha
PORTAINER_ENDPOINT=2
```

## Uso

```bash
node scripts/portainer/validacao-servicos/validate-legacy-services.js \
  --url http://servidor:9011 \
  --username admin \
  --password sua_senha \
  --endpoint 2 \
  --scope 2024.2.0 \
  --output scripts/portainer/validacao-servicos/report.json
```

O parâmetro `--scope` é **apenas informativo** no relatório (versão alvo do ambiente). Não marca `2024.1.0` como legado.

## Códigos de issue

| Código | Descrição |
|--------|-----------|
| `LEGACY_UNVERSIONED` | Container sem sufixo `-20XX.X.X` |
| `LEGACY_IMAGE_TAG` | Tag legada (`1.0.x`, `2.0.x`, `3.0.x`, etc.) |
| `LEGACY_IMAGE_MISMATCH` | Nome versionado, mas imagem com versão diferente |

## Saída

Gera `report.json` com:

- `summary` — totais e contagem por tipo de issue
- `legacy_containers` — containers inválidos
- `migration_pairs` — legado sem versão coexistindo com versionado (candidatos a `docker rm -f`)
- `scanned_containers` — todos os containers Korp analisados

## Fluxo de autenticação

Conforme `scripts/portainer/global-context.md`:

1. `POST /api/auth` com `Username` e `Password`
2. Extrair `jwt` da resposta
3. `GET /api/endpoints/{id}/docker/containers/json?all=true` com `Authorization: Bearer {jwt}`
