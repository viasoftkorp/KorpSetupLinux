1. Objetivo Geral
O objetivo deste script em JavaScript (Node.js) é ler o arquivo de diagnóstico gerado pelo validador ([`relatorio-tags.json`](../../relatorio-tags.json) na raiz do repositório, produzido por [`scripts/validacao-github/validate-tags.js`](../validacao-github/validate-tags.js)), identificar os serviços remanescentes sem tag no GitHub, verificar se eles possuem uma esteira ativa no Jenkins e, em caso positivo, realizar a criação automatizada da tag correspondente no Monorepo do GitHub.

2. Contexto, APIs e Autenticação
Linguagem: JavaScript (Node.js - versão LTS).

Módulos Permitidos: Módulos nativos (fs, path) e bibliotecas de requisição HTTP (axios ou fetch nativo).

Fontes de Entrada: Arquivo `relatorio-tags.json` na raiz do repositório (gerado pelo script `validate-tags.js`).

Autenticação e Variáveis de Ambiente (`.env` em `scripts/validacao-github/.env` ou na raiz do repo):

GITHUB_TOKEN: PAT com permissão de escrita (contents: write) nos repositórios.

ORG_NAME: Nome da organização no GitHub.

JENKINS_URL: URL base do servidor Jenkins.

JENKINS_USER: Usuário de integração do Jenkins.

JENKINS_TOKEN: API Token do usuário do Jenkins.

3. Regras de Entrada e Filtros de Escopo
O script deve processar apenas os serviços que atendam a todos os critérios abaixo:

Origem: Estar listado em `servicos_sem_tag_no_github` no `relatorio-tags.json` (`tem_tag_github: false`).

Filtro de Escopo Core: O nome do serviço (`servico_bitbucket`) deve começar estritamente com `korp.` ou `viasoft.`.

Filtro Ativo (Jenkins): O serviço deve obrigatoriamente possuir um Job correspondente e ativo no Jenkins. Se o Jenkins retornar 404 para o Job, o serviço deve ser ignorado.

### 3.0. Formato do relatório de entrada

O script lê o array `servicos_sem_tag_no_github` de `relatorio-tags.json`. Cada entrada contém, entre outros:

* `dominio_github` — monorepo de destino no GitHub
* `servico_bitbucket` — slug do serviço
* `categoria` — `versionados` ou `nao-versionados`
* `tipo_servico` — `backend`, `frontend` ou `outros`
* `tem_tag_github` — deve ser `false`
* `referencia_bitbucket` — últimas tags no Bitbucket (janelas ou `ultima_tag_absoluta`)

Formato completo documentado em [`scripts/validacao-github/specs.md`](../validacao-github/specs.md) seção 5.

### Exemplo de uso

```bash
# 1. Gerar diagnóstico
node scripts/validacao-github/validate-tags.js > relatorio-tags.json

# 2. Simular criação de tags
node scripts/criacao-tags-github/create-tags-github.js --dry-run --all-services

# 3. Criar tags de fato
node scripts/criacao-tags-github/create-tags-github.js --all-services
```

4. Fluxo de Execução
O script [`create-tags-github.js`](create-tags-github.js) deve seguir rigorosamente a seguinte esteira:

Passo 1: Leitura do Diagnóstico
Ler o arquivo `relatorio-tags.json` da raiz do projeto (override via `--input`).

Filtrar o array `servicos_sem_tag_no_github`, isolando aqueles cujo `servico_bitbucket` começa com `korp.` ou `viasoft.`.

Passo 2: Validação de Atividade no Jenkins
Para cada serviço elegível:

Disparar uma requisição para a API do Jenkins: GET ${JENKINS_URL}/job/[NOME_DO_SERVICO]/api/json.

Decisão:

Status 200: O Job existe. Prosseguir para o Passo 3.

Status 404: O Job não existe (serviço possivelmente legado ou inativo). Exibir log [IGNORADO] Serviço ${servico} não possui Job no Jenkins. e avançar para o próximo serviço da lista.

### Passo 3: Cálculo de Versão (Incremento de Build) e Criação da Tag no GitHub

Para cada serviço aprovado pelo Jenkins, o script deve calcular o nome exato da(s) tag(s) a ser(em) criada(s) utilizando a regra de incremento baseado no histórico coletado do Bitbucket:

#### 3.1. Regra para Serviços NÃO-VERSIONADOS (Legados)
* **Padrão de Destino:** Sempre migrarão para a versão fixa de ano `2025.1.0.[BUILD]`.
* **Cálculo do Build:** O script deve isolar o número do último build absoluto encontrado no Bitbucket (ex: em `1.0.2`, o build é `2`) e somar `+1` (ficando `3`).
* **Fallback sem histórico:** Se não houver tag no Bitbucket (`ultima_tag_absoluta: "Não encontrada"`), a tag criada no GitHub será `{servico}-2025.1.0.1`.
* **Exemplo de Transformação:**
  * Última tag absoluta no Bitbucket: `Korp.API.Gateway-Documentation-1.0.2`
  * Tag gerada no GitHub: `Korp.API.Gateway-Documentation-2025.1.0.3`

#### 3.2. Regra para Serviços VERSIONADOS (Matriz de Anos)
* **Multiplicidade de Tags:** Se o serviço possuir histórico mapeado em mais de uma janela da matriz (`2025.1.0.x`, `2024.2.0.x`, `2024.1.0.x`, `2023.4.0.x`), o script **gerará uma tag no GitHub para cada janela existente**.
* **Cálculo do Build:** Para cada janela identificada, o script pegará o último build registrado no Bitbucket para aquela versão específica e somará `+1`.
* **Fallback sem histórico:** Se nenhuma janela tiver tag no Bitbucket, a tag criada no GitHub será `{servico}-2025.1.0.1`.
* **Exemplo de Transformação (Múltiplas tags geradas para o mesmo serviço):**
  * *Histórico Bitbucket:*
    * Janela 2025.1.0.x -> `korp.api.gateway.vendas-2025.1.0.10`
    * Janela 2024.2.0.x -> `korp.api.gateway.vendas-2024.2.0.10`
    * Janela 2024.1.0.x -> `korp.api.gateway.vendas-2024.1.0.10`
  * *Tags Criadas no GitHub:*
    * `korp.api.gateway.vendas-2025.1.0.11`
    * `korp.api.gateway.vendas-2024.2.0.11`
    * `korp.api.gateway.vendas-2024.1.0.11`

#### 3.3. Execução do Push no GitHub
Para cada tag calculada acima, o script fará as seguintes chamadas à API do GitHub:
1. Buscar o SHA do commit mais recente da branch principal do Monorepo do domínio (`GET /repos/{org}/{dominio}/branches/main`).
2. Criar a referência da tag (`POST /repos/{org}/{dominio}/git/refs`) apontando para esse SHA.

* **Captura Universal de Nomes (Filtro por Prefixo):** O script deve aceitar qualquer serviço cujo nome inicie estritamente com `korp.` ou `viasoft.`. 
* **Tratamento Genérico de Sufixos:** O script não deve tentar adivinhar se o sufixo é apenas `frontend` ou `Documentation`. A lógica de parsing deve tratar o nome do serviço como uma estrutura única até chegar ao hífen da versão.
  * **Estrutura Regex de Casamento:** `^(korp\..+|viasoft\..+?)(?:-(\d+\.\d+\.\d+\.\d+)|-(\d+\.\d+\.\d+))?$`
  * Isso garante que, se o serviço se chamar `viasoft.vendas.mobile-cli`, o script entenda que o nome completo do serviço para busca e criação de tags é `viasoft.vendas.mobile-cli`.

#### 3.4. Algoritmo de Montagem da Tag no GitHub (Sufixo Preservado)
Independentemente de o serviço terminar com `-frontend`, `-Documentation` ou qualquer outro sufixo, o script deve montar o nome da tag seguindo a fórmula:

`[NOME_COMPLETO_DO_SERVICO]-[NOVA_VERSAO_CALCULADA]`

**Exemplos Práticos com Qualquer Sufixo:**
* **Caso 1 (Sufixo Customizado - Não Versionado):**
  * Nome vindo do Bitbucket: `Korp.API.Gateway-Documentation` (Última tag: `1.0.2`)
  * Tag Gerada no GitHub: `Korp.API.Gateway-Documentation-2025.1.0.3`
* **Caso 2 (Sufixo Frontend - Versionado):**
  * Nome vindo do Bitbucket: `viasoft.sales.crm.core-frontend` (Última tag da janela 2025: `2025.1.0.10`)
  * Tag Gerada no GitHub: `viasoft.sales.crm.core-frontend-2025.1.0.11`
* **Caso 3 (Sufixo de Microsserviço - Versionado):**
  * Nome vindo do Bitbucket: `korp.vendas.notificacoes-worker` (Última tag da janela 2024.2: `2024.2.0.5`)
  * Tag Gerada no GitHub: `korp.vendas.notificacoes-worker-2024.2.0.6`

Caso o serviço não tenha uma tag no bitbucket para se basear a tag criada no github deve ser 2025.1.0.1

#### 3.5. Resolução Dinâmica de Branch Alvo (Mapeamento de Release)
O script **NÃO** deve utilizar a branch `main` como alvo genérico. O commit de origem da tag deve ser extraído da branch de release correspondente à versão que está sendo gerada:

1. **Mapeamento de Regra:**
   * Para tags calculadas como `2025.1.0.[BUILD]` (tanto de serviços versionados quanto de legados convertidos) ➡️ a branch alvo será `release/2025.1.0.x`.
   * Para tags calculadas como `2024.2.0.[BUILD]` ➡️ a branch alvo será `release/2024.2.0.x`.
   * Para tags calculadas como `2024.1.0.[BUILD]` ➡️ a branch alvo será `release/2024.1.0.x`.
   * Para tags calculadas como `2023.4.0.[BUILD]` ➡️ a branch alvo será `release/2023.4.0.x`.

2. **Algoritmo de Execução da API do GitHub:**
   Para cada tag a ser criada, o script deve seguir a seguinte ordem de chamadas:
   * **Passo A:** Buscar o SHA do commit mais recente da branch de release específica (ex: `GET /repos/{org}/{dominio}/branches/release/2025.1.0.x`).
   * **Passo B:** Criar a referência da tag (`POST /repos/{org}/{dominio}/git/refs`) passando o nome completo da tag calculado e o SHA obtido no Passo A.
   * *Tratamento de Exceção:* Se a branch de release esperada não existir no repositório do GitHub (retornar 404), o script deve registrar um log de erro `[ERRO] Branch release/XXXX.X.X.x não encontrada para o serviço X` e pular a criação daquela tag específica, avançando para as próximas.

## 6. Modos de Execução e Parâmetros (CLI Flags)

O script deve ser executado aceitando obrigatoriamente as seguintes configurações de controle:

* `--dry-run`: **(Modo Padrão de Segurança)** Quando ativo, o script executa todo o fluxo lógico, consultas às APIs e cálculos de versão, mas **NÃO** faz o POST de criação da tag no GitHub. Ele deve apenas exibir no console o que *seria* feito.
* `--debug`: Ativa logs detalhados (verbose). Deve exibir as URLs exatas chamadas, as respostas brutas das APIs (GitHub, Bitbucket, Jenkins) e as decisões de Regex passo a passo.
* `--single-service=[NOME_DO_SERVICO]`: Ignora o processamento em lote. O script vai focar a validação e remediação estritamente no serviço passado por parâmetro (ex: `--single-service=viasoft.vendas.custeioproduto-frontend`).
* `--all-services`: Executa o processamento em lote para todos os serviços inconsistentes listados no JSON de entrada que passem pelos filtros core (`korp.` / `viasoft.`).

> **Trava de Segurança:** Se o script for executado sem `--single-service` ou `--all-services`, deve abortar informando os parâmetros obrigatórios.

## 7. Arquitetura de Testes (Abordagem TDD)

Os testes automatizados devem ser escritos em [`create-tags-github.test.js`](create-tags-github.test.js) utilizando `node:test` e `node:assert` (nativos do Node.js) **antes** da implementação do script final.

### 7.1. Regra Fundamental do TDD neste Cenário
* **Proibição de Requisições Reais:** Sob nenhuma circunstância os testes unitários devem fazer chamadas de rede reais para o Jenkins, GitHub ou Bitbucket.
* **Mocks de API:** Todas as respostas das APIs externas e a leitura do arquivo `relatorio-tags.json` devem ser simuladas (*mockadas*) nos arquivos de teste.

### 7.2. Casos de Teste Obrigatórios a serem Implementados:

1.  **Teste de Isolamento (Dry-Run):**
    * *Cenário:* Script executado com a flag `--dry-run`.
    * *Resultado Esperado:* O mock do axios/fetch do GitHub para criação de refs (`POST`) **nunca** deve ser chamado. Os logs devem indicar simulação.
2.  **Teste de Incremento Não-Versionado (Build + 1):**
    * *Cenário:* Entrada com serviço `korp.suporte-cli` e tag no Bitbucket `1.5.12`.
    * *Resultado Esperado:* A função de cálculo deve retornar exatamente a tag `korp.suporte-cli-2025.1.0.13`.
3.  **Teste de Múltiplas Tags para Versionados:**
    * *Cenário:* Entrada com serviço `viasoft.financeiro-api` possuindo as janelas 2025 (build 4) e 2024.2 (build 80) no Bitbucket.
    * *Resultado Esperado:* O script deve planejar/gerar exatamente duas tags: `...-2025.1.0.5` e `...-2024.2.0.81`.
4.  **Teste do Filtro do Jenkins (404 vs 200):**
    * *Cenário:* Mock do Jenkins retorna 404 para um serviço e 200 para outro.
    * *Resultado Esperado:* O serviço com 404 deve ser listado em `servicos_ignorados` no JSON final, e o com 200 deve seguir para criação.
5.  **Teste de Escopo de Prefixo:**
    * *Cenário:* O JSON de entrada contém por erro um serviço chamado `external.tool-integration`.
    * *Resultado Esperado:* O script deve ignorar o serviço imediatamente por não iniciar com `korp.` ou `viasoft.`.