# SPEC: script-validate-services-step1.md

## 1. Contexto & Objetivo
Criar a primeira camada de validação do script `validate-services.js` (localizado em `scripts/validacao-servicos/`). O script deve escanear as `roles` do projeto `KorpSetupLinux`, identificar os **Serviços Versionados Exclusivos** (arquivos `.yml.j2` localizados diretamente na raiz da pasta `templates/composes/`) e validar se a estrutura inicial do bloco Docker Compose atende estritamente às regras de negócio de nomenclatura e imagem.

**Importante:** O script deve ser estritamente de **leitura (Read-Only)**. Ele não deve modificar nenhum arquivo. O resultado final deve ser retornado no formato **JSON**.

---

## 2. Pilha Tecnológica & Dependências
- **Ambiente:** Node.js (ES6+).
- **Módulos Nativos:** `fs`, `path` (sem dependências npm).
- **Extração de serviços:** Parser textual focado no bloco `services:` — extrai apenas `image` e `container_name` de cada serviço, ignorando o restante do YAML (âncoras, Jinja2, etc.).
  - *Estratégia Jinja2:* Blocos `{% ... %}` são removidos antes da varredura. Chaves dinâmicas (ex: `{{ rabbitmq_container_name }}`) são suportadas na leitura do nome do serviço.

---

## 3. Regra de Elegibilidade Base (Aplicada a Todos os Passos)
Antes de processar qualquer serviço encontrado dentro de um arquivo `.yml.j2`, o script deve checar o campo `image`:

- **Critério de Inclusão:** O serviço **SÓ** será considerado para validação se o valor do campo `image` iniciar estritamente com a string `"{{ docker_account }}"`.
- **Comportamento para Não Elegíveis:** Se o campo `image` começar com qualquer outra coisa (ex: `nginx:latest`, `redis:alpine`), o script deve ignorar o serviço silenciosamente. Ele **NÃO** deve contabilizá-lo no `summary` e **NÃO** deve adicioná-lo nem em `valid_services` e nem em `invalid_services`.

---

## 4. Critérios de Validação Versionados Exclusivos
Para cada arquivo `.yml.j2` na raiz de `composes/`, isole o serviço e aplique os seguintes testes baseados em Regex (tratando os valores como strings puras):

### A. Validação da Imagem
- **Regra:** A string do campo `image` deve terminar obrigatoriamente com o padrão de tag do Jinja2: `:{{ version_without_build }}.x{{ docker_image_suffix }}`.
- **O que ignorar:** Ignore todo o texto que vem antes do caractere `:` (o nome da conta docker e o nome do repositório/imagem).
- **Exemplo Válido:** `{{ docker_account }}/viasoft.digital.assign-frontend:{{ version_without_build }}.x{{ docker_image_suffix }}`

### B. Validação do Container Name
- **Regra:** A string do campo `container_name` deve terminar obrigatoriamente com o sufixo: `-{{ version_without_build }}`.
- **O que ignorar:** Ignore o prefixo do nome do container.
- **Exemplo Válido:** `ADS01-{{ version_without_build }}`

> **Nota:** O nome do serviço (chave primária do YAML), bem como `restart`, `environment`, `networks` ou `volumes`, devem ser completamente ignorados nesta validação.

---

## 5. Critérios de Validação: Regra Estratégica de Frontend(Versionados Não Exclusivos)
Esta regra é prioritária e atua de forma transversal sobre a localização dos arquivos de interface:

1. **Identificação:** Um serviço é classificado como Frontend se o valor do campo `image` (antes da tag/dois-pontos) contiver o sufixo `-frontend` (ex: `viasoft.digital.assign-frontend`).
2. **Validação de Localização (Bloqueio Exclusivo):** Se um serviço de Frontend for detectado em um arquivo `.yml.j2` localizado na **raiz** da pasta `composes/`, ele deve ser marcado imediatamente como **INVÁLIDO**.
   - *Erro esperado no JSON:* `"Erro Estratégico: Serviços de Frontend não podem ser exclusivos. Mova este arquivo para as pastas de versão."`

---

## 6. Critérios de Validação: Serviços Versionados Não Exclusivos (Nas Pastas de Versão)
Para arquivos localizados dentro de subpastas de versão física, o script deve extrair dinamicamente o nome da pasta (chamemos de `{X}`, ex: `2025.1.0`) e aplicar **3 validações estritas**:

1. **Validação do Nome do Serviço (Chave Primária do YAML):** A chave do serviço deve terminar obrigatoriamente com a versão da pasta convertida com hifens.
   - **Formato esperado:** `-[Versão com Hifens]` (Ex: Se a pasta é `2025.1.0`, o serviço deve terminar com `-2025-1-0`).
   - *Nota de Engenharia:* Use `X.replace(/\./g, '-')` no Node para gerar a string de validação.

2. **Validação da Imagem:** A string do campo `image` deve terminar obrigatoriamente com a versão estática travada (com pontos) e a tag do sufixo: `:{X}.x{{ docker_image_suffix }}` (Ex: `:2025.1.0.x{{ docker_image_suffix }}`).

3. **Validação do Container Name:** O campo `container_name` deve terminar exatamente com o hífen e a versão estática com pontos: `-{X}` (Ex: `-2025.1.0`).

---

## 7. Contrato de Saída (JSON Schema Esperado)
O script deve gerar um arquivo chamado `report.json` no mesmo diretório (`__dirname`) contendo a seguinte estrutura.

> **Nota:** Cada entrada em `valid_services` ou `invalid_services` representa **um serviço individual** dentro de um compose. Arquivos com múltiplos serviços geram múltiplas entradas. O campo `details.service_name` identifica a chave YAML do serviço validado, facilitando a leitura do relatório.

```json
{
  "summary": {
    "total_roles_scanned": 86,
    "exclusive_services": {
      "total_found": 12,
      "valid": 11,
      "invalid": 1
    },
    "non_exclusive_services": {
      "total_found": 24,
      "valid": 22,
      "invalid": 2
    }
  },
  "results": {
    "exclusive": {
      "invalid_services": [
        {
          "role": "ADS01",
          "file_path": "roles/ADS01/templates/composes/ads01.yml.j2",
          "errors": [
            "Erro Estratégico: Serviços de Frontend não podem ser exclusivos. Mova este arquivo para as pastas de versão."
          ],
          "details": {
            "service_name": "ADS01",
            "image": "{{ docker_account }}/viasoft.digital.assign-frontend:{{ version_without_build }}.x{{ docker_image_suffix }}",
            "container_name": "ADS01-{{ version_without_build }}"
          }
        }
      ],
      "valid_services": [
        {
          "role": "APS",
          "file_path": "roles/APS/templates/composes/APS-compose.yml.j2",
          "details": {
            "service_name": "viasoft-production-aps-distribution",
            "image": "{{ docker_account }}/viasoft.production.aps.distribution:{{ version_without_build }}.x{{ docker_image_suffix }}",
            "container_name": "Viasoft.Production.APS.Distribution-{{ version_without_build }}"
          }
        }
      ]
    },
    "non_exclusive": {
      "invalid_services": [
        {
          "role": "LOG102",
          "version_folder": "2025.1.0",
          "file_path": "roles/LOG102/templates/composes/2025.1.0/LOG102-compose.yml.j2",
          "errors": [
            "O nome do serviço deveria terminar com '-2025-1-0' mas foi encontrado 'korp-logistic-picking-analisedeestoque-2025.1.0'"
          ],
          "details": {
            "service_name": "korp-logistic-picking-analisedeestoque-2025.1.0",
            "image": "{{ docker_account }}/korp.logistica.picking.analisedeestoque:2025.1.0.x{{ docker_image_suffix }}",
            "container_name": "Korp.Logistica.Picking.AnaliseDeEstoque-2025.1.0"
          }
        }
      ],
      "valid_services": [
        {
          "role": "LOG102",
          "version_folder": "2025.1.0",
          "file_path": "roles/LOG102/templates/composes/2025.1.0/LOG102-compose.yml.j2",
          "details": {
            "service_name": "LOG102-2025-1-0",
            "image": "{{ docker_account }}/korp.logistica.picking-frontend:2025.1.0.x{{ docker_image_suffix }}",
            "container_name": "LOG102-2025.1.0"
          }
        }
      ]
    }
  }
}
```

## 8. Configuração da Lista de Exclusão (Ignored List)
O script deve possuir um Array estático contendo os nomes bases das imagens que devem ser **completamente ignoradas** na validação (mesmo que comecem com `{{ docker_account }}`).

A checagem deve ser feita baseando-se no corpo do nome da imagem (removendo o prefixo da conta e a tag de versão).

**Imagens completamente ignoradas:**
1. `korp.atualizacaosistema`

## 9. Exceção Parcial: Container Name Fixo
Serviços cujo `container_name` e chave YAML **não** variam com a versão, mas cuja **imagem** segue o padrão dinâmico `{{ version_without_build }}.x{{ docker_image_suffix }}`:

| Imagem base | `container_name` fixo |
|-------------|----------------------|
| `korp.legacy.frontend-router` | `Korp.Legacy.Frontend-router` |
| `viasoft.loader` | `Viasoft.Loader` |

**Regras de validação para esses serviços:**
- **Imagem:** deve terminar com `:{{ version_without_build }}.x{{ docker_image_suffix }}` (mesma regra dos exclusivos).
- **Container name:** **não** exige sufixo `-{{ version_without_build }}`; basta estar presente e não vazio.
- **Nome do serviço (chave YAML):** fora do escopo da validação (permanece fixo, ex.: `korp-legacy-frontend-router`, `viasoft-loader`).

---