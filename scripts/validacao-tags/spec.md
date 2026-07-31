1. Objetivo Geral
O objetivo deste script em JavaScript (Node.js) é validar a existência de tags de lançamentos dos serviços da organização no GitHub, cruzando os dados com as últimas tags disponíveis no Bitbucket. Caso uma tag esperada não exista no GitHub, o script deve reportar a ausência em um formato JSON estruturado, incluindo qual é a última tag que aquele serviço possui no Bitbucket para referência.

2. Contexto, APIs e Autenticação
Linguagem: JavaScript (Node.js - versão LTS).

Dependências sugeridas: @octokit/rest (para GitHub API) ou apenas axios/fetch nativo para ambas as APIs.

Autenticação: O script deve ler as credenciais de variáveis de ambiente (.env):

GITHUB_TOKEN: Personal Access Token (PAT) com escopo de leitura de repositórios.

BITBUCKET_USERNAME e BITBUCKET_APP_PASSWORD: Para autenticação básica na API do Bitbucket.

ORG_NAME: Nome da organização/workspace em ambas as plataformas.

JENKINS_URL: URL base do servidor Jenkins.

JENKINS_USER: Usuário de integração do Jenkins.

JENKINS_TOKEN: API Token do usuário do Jenkins.

## 2.2. Filtro de Escopo (Job Ativo no Jenkins)
Antes de validar tags no GitHub e consultar histórico no Bitbucket, o script deve verificar se o serviço possui um **Job correspondente e ativo no Jenkins**.

* **Requisição:** `GET ${JENKINS_URL}/job/[NOME_DO_SERVICO]/api/json` com autenticação básica.
* **Status 200:** O Job existe. O serviço entra no fluxo de validação (GitHub + Bitbucket).
* **Status 404:** O Job não existe (serviço legado ou inativo). O serviço **não** é validado e **não** entra em `servicos`, `servicos_sem_tag_no_github` nem `servicos_com_janelas_ausentes`.
* **Demais status / erro de rede:** O serviço é tratado como indisponível no Jenkins e também fica fora da validação.

Serviços excluídos por este filtro são listados em `servicos_sem_job_jenkins`, com `motivo` `jenkins_404` ou `jenkins_erro`.

## 2.1. Mapeamento de Estrutura (GitHub Monorepo vs. Bitbucket Multi-repo)
O script deve compreender a diferença de arquitetura entre as duas plataformas:
* **No GitHub (Destino):** A organização utiliza **Monorepos por Domínio**. O nome do repositório é o domínio (ex: `vendas`). Os serviços individuais são pastas dentro dele. As tags de release pertencem ao repositório do domínio.
* **No BitBucket (Origem):** A organização utiliza **Projetos por Domínio** contendo múltiplos repositórios separados para cada serviço. O nome do projeto é o domínio (ex: `vendas`) e cada serviço é um repositório real (ex: `korp.api.gateway.vendas`).

3. Regras de Negócio e Classificação de Serviços
Os serviços da organização são classificados em duas categorias baseadas no seu padrão de versionamento. O script deve aplicar lógicas distintas para cada uma:

3.1. Serviços Versionados (Modelo por Ano)
Padrão de Versão: ANO.RELEASE.PATCH.x (Ex: 2025.1.0.x).

Matriz de Versões Alvo: Para cada serviço desta categoria, o script deve obrigatoriamente validar a existência das últimas tags das seguintes janelas de versão no GitHub:

2025.1.0.x

2024.2.0.x

2024.1.0.x

2023.4.0.x

Regra de Fallback: Se o serviço não possuir histórico de alguma dessas versões específicas no Bitbucket/GitHub, o script deve ignorar silenciosamente a versão inexistente e prosseguir a validação para as demais da lista.

3.2. Serviços Não-Versionados (Modelo Legado)
Padrão de Versão: DIGITO.PATCH.x (Ex: 1.0.x, 1.1.x).

Regra de Validação: Para estes serviços, o script não busca por janelas de anos. Ele deve apenas descobrir qual é a última tag absoluta gerada no Bitbucket

## 3.3. Regra de Validação Cruzada (GitHub x Bitbucket)
* **Bitbucket (Referência de Última Tag):** O script acessará o Bitbucket para ler os repositórios de cada projeto (domínio) e descobrir qual é o número exato da última tag gerada (seguindo as regras de Versionados e Não-Versionados descritas nas seções 3.1 e 3.2).
* **GitHub (Validação de Existência):** O script **NÃO** deve comparar se a tag exata do Bitbucket existe no GitHub. A validação no GitHub consiste estritamente em verificar se o repositório do domínio (Monorepo) possui **pelo menos 1 tag cadastrada** que corresponda ao escopo do serviço/janela esperada. Se o repositório do domínio tiver tags válidas, ele é considerado aprovado.

* **Contexto de Migração:** Este script roda pós-migração do Bitbucket para o GitHub. No GitHub, todos os serviços foram consolidados em Monorepos por Domínio e passaram a ser **obrigatoriamente versionados**.
* **Padrão de Tag no GitHub:** No repositório de domínio do GitHub, as tags seguem o formato estrito: `[NOME_DO_SERVICO]-[VERSAO]` (Ex: `viasoft.vendas.core-2025.1.0.4`).
* **Critério de Validação:** Para validar um serviço, o script deve listar as tags do repositório do domínio no GitHub e verificar se existe **pelo menos uma tag** cujo nome comece com o prefixo do serviço (ex: `viasoft.vendas.core-`). Se houver ao menos uma ocorrência, o serviço está validado no GitHub.

* **Tratamento Especial para Frontend:** Os serviços que correspondem a aplicações frontend possuem a string `-frontend` anexada ao final do seu nome antes do hífen da versão. 
* **Regra de Nomenclatura de Tag:**
  * **Serviço Comum/Backend:** `[NOME_DO_SERVICO]-[VERSAO]` (Ex: `viasoft.vendas.core-2025.1.0.4`)
  * **Serviço Frontend:** `[NOME_DO_SERVICO]-frontend-[VERSAO]` (Ex: `viasoft.vendas.custeioproduto-frontend-2025.1.0.7`)

* Como o fluxo parte do GitHub, o script garante que o serviço existe na nova casa. A validação agora consiste em verificar se as versões históricas importantes mapeadas no Bitbucket possuem uma tag correspondente no GitHub.
* Se o Bitbucket apontar que a última tag da janela `2025.1.0.x` era a `2025.1.0.11` e no GitHub não houver nenhuma tag para esse serviço contendo a versão `2025.1.0`, o serviço gera um alerta de inconsistência no JSON.

### 3.4. Categoria Especial (Serviços Utilitários / Outros)
* **Critério de Entrada:** Serviços cujo nome termina com sufixo utilitário conhecido (`-Documentation`, `-CLI`, `-Worker`, case-insensitive), mas **não** com `-frontend`.
* **Comportamento do Script:** Este serviço **não deve** ser descartado ou ignorado. O script deve executar exatamente as mesmas ações de busca e validação de tags no GitHub e Bitbucket que aplicaria a um serviço de backend comum, apenas isolando-o sob esta nova classificação no relatório.
* **Descoberta via Bitbucket:** Serviços existentes no Bitbucket (ex: `korp.api.gateway-documentation`) que ainda não possuem tag no GitHub devem aparecer no relatório com `tem_tag_github: false`, complementando a descoberta inicial feita pelas tags do GitHub.
* **Campo no JSON:** O relatório expõe essa classificação no campo `tipo_servico`, com valores `"backend"`, `"frontend"` ou `"outros"`.

### Passo 4: Validação no GitHub
1. Para cada domínio/serviço analisado, o script deve listar as tags do repositório do domínio no GitHub (`GET /repos/{org}/{domínio}/tags`).
2. **Critério de Falha:** Se a lista de tags retornada pelo GitHub para aquele repositório de domínio estiver completamente vazia (ou não possuir nenhuma tag correspondente ao padrão do serviço), o serviço é marcado como inconsistente.
3. Se o GitHub possuir pelo menos uma tag, o serviço está validado. O script apenas anexa a última tag encontrada no Bitbucket no relatório final para fins de consulta e auditoria.

1. Para cada serviço mapeado, o script deve buscar todas as tags do seu respectivo repositório de domínio no GitHub (`GET /repos/{org}/{dominio}/tags`).
2. O script deve filtrar a lista de tags recebida, procurando por qualquer registro que comece com o nome exato do serviço do Bitbucket seguido de um hífen (ex: `nome_do_servico-`).
3. **Critério de Falha:** Se após a filtragem não for encontrada **nenhuma tag** correspondente àquele serviço no GitHub, o serviço é marcado como "Não Migrado/Sem Tag".

3. Para cada serviço, o script deve gerar dinamicamente o prefixo de busca da tag:
   * **Se o serviço for classificado como frontend** (seja por configuração ou se o nome do repositório no Bitbucket já terminar com `-frontend` ou conter `frontend`): o prefixo de busca no GitHub deve ser `[NOME_DO_SERVICO]-frontend-`.
   * **Caso contrário (Backend/Outros):** o prefixo de busca deve ser apenas `[NOME_DO_SERVICO]-`.
4. **Critério de Falha:** O script filtrará as tags do Monorepo do GitHub usando esse prefixo dinâmico. Se nenhuma tag correspondente for encontrada, o serviço será marcado como inconsistente no JSON de saída.

### Passo 2: Mapeamento do Tipo de Serviço e Identificação de Frontend
Para cada serviço válido identificado nas tags do GitHub (aqueles que passam no filtro `korp.*` ou `viasoft.*`):
1. O script identifica se é um serviço de **Frontend** apenas para controle de log e relatório (verificando a presença do sufixo `-frontend` no nome).
2. **Mapeamento Direto:** O nome do serviço extraído da tag do GitHub será usado **exatamente igual** para consultar o repositório correspondente no Bitbucket, já que ambos mantêm o sufixo `-frontend`.

1. Utilizando o nome exato do serviço obtido no GitHub, o script faz a chamada à API do Bitbucket dentro do projeto/domínio correspondente.
2. O script descobre se o repositório no Bitbucket segue o modelo *Versionado* (padrão de anos) ou *Não-Versionado* (legado).
3. Coleta a última tag gerada no Bitbucket para aquele repositório exato e confronta com as tags existentes no GitHub para validar se o histórico esperado está presente na nova casa.

5. Atualização na Seção 5 (Formato do JSON de Saída)
O JSON de saída lista apenas os serviços **com Job no Jenkins** em `servicos` e separa as inconsistências por tipo. Serviços sem Job no Jenkins ficam isolados em `servicos_sem_job_jenkins` e não entram nas contagens de inconsistência.

Cada serviço validado inclui `referencia_bitbucket` (últimas tags no Bitbucket) e `referencia_github` (últimas tags no GitHub), seguindo a mesma lógica de versionados vs. não-versionados.

Para serviços **versionados**, ambas as referências trazem as janelas `2025.1.0.x`, `2024.2.0.x`, `2024.1.0.x` e `2023.4.0.x`. Para **não-versionados**, apenas `ultima_tag_absoluta`.

{
  "timestamp": "2026-06-15T10:25:00Z",
  "resumo": {
    "total_descobertos": 342,
    "total_analisados": 296,
    "sem_job_jenkins": 46,
    "consistentes": 243,
    "inconsistentes": 53,
    "com_tag_github": 250,
    "sem_tag_github": 8,
    "com_janelas_ausentes": 45
  },
  "servicos": [
    {
      "dominio_github": "vendas",
      "servico_bitbucket": "korp.sales.tracking",
      "categoria": "versionados",
      "tipo_servico": "backend",
      "tem_tag_github": true,
      "referencia_bitbucket": {
        "janela_2025.1.0.x": "2025.1.0.42",
        "janela_2024.2.0.x": "2024.2.0.115",
        "janela_2024.1.0.x": "Não encontrada",
        "janela_2023.4.0.x": "2023.4.0.5"
      },
      "referencia_github": {
        "janela_2025.1.0.x": "2025.1.0.38",
        "janela_2024.2.0.x": "2024.2.0.110",
        "janela_2024.1.0.x": "Não encontrada",
        "janela_2023.4.0.x": "2023.4.0.5"
      },
      "consistente": true
    },
    {
      "dominio_github": "vendas",
      "servico_bitbucket": "viasoft.vendas.custeioproduto-frontend",
      "categoria": "versionados",
      "tipo_servico": "frontend",
      "tem_tag_github": true,
      "referencia_bitbucket": {
        "janela_2025.1.0.x": "2025.1.0.7",
        "janela_2024.2.0.x": "2024.2.0.20",
        "janela_2024.1.0.x": "Não encontrada",
        "janela_2023.4.0.x": "Não encontrada"
      },
      "referencia_github": {
        "janela_2025.1.0.x": "2025.1.0.7",
        "janela_2024.2.0.x": "2024.2.0.18",
        "janela_2024.1.0.x": "Não encontrada",
        "janela_2023.4.0.x": "Não encontrada"
      },
      "consistente": true
    },
    {
      "dominio_github": "engenharia",
      "servico_bitbucket": "korp.api.gateway-Documentation",
      "categoria": "versionados",
      "tipo_servico": "outros",
      "tem_tag_github": true,
      "referencia_bitbucket": {
        "janela_2025.1.0.x": "2025.1.0.4",
        "janela_2024.2.0.x": "2024.2.0.8",
        "janela_2024.1.0.x": "2024.1.0.2",
        "janela_2023.4.0.x": "Não encontrada"
      },
      "referencia_github": {
        "janela_2025.1.0.x": "2025.1.0.4",
        "janela_2024.2.0.x": "2024.2.0.8",
        "janela_2024.1.0.x": "Não encontrada",
        "janela_2023.4.0.x": "Não encontrada"
      },
      "consistente": false,
      "status_github": "Janela(s) ausente(s) no GitHub: 2024.1.0.x",
      "janelas_ausentes": ["2024.1.0.x"]
    },
    {
      "dominio_github": "vendas",
      "servico_bitbucket": "korp.legacy-vendas-api",
      "categoria": "nao-versionados",
      "tipo_servico": "backend",
      "tem_tag_github": false,
      "referencia_bitbucket": {
        "ultima_tag_absoluta": "1.1.28"
      },
      "referencia_github": {
        "ultima_tag_absoluta": "Não encontrada"
      },
      "consistente": false,
      "status_github": "Nenhuma tag encontrada no repositório do domínio"
    }
  ],
  "servicos_sem_tag_no_github": [
    {
      "dominio_github": "vendas",
      "servico_bitbucket": "korp.legacy-vendas-api",
      "categoria": "nao-versionados",
      "tipo_servico": "backend",
      "tem_tag_github": false,
      "referencia_bitbucket": {
        "ultima_tag_absoluta": "1.1.28"
      },
      "referencia_github": {
        "ultima_tag_absoluta": "Não encontrada"
      },
      "consistente": false,
      "status_github": "Nenhuma tag encontrada no repositório do domínio"
    }
  ],
  "servicos_com_janelas_ausentes": [
    {
      "dominio_github": "engenharia",
      "servico_bitbucket": "korp.api.gateway-Documentation",
      "categoria": "versionados",
      "tipo_servico": "outros",
      "tem_tag_github": true,
      "referencia_bitbucket": {
        "janela_2025.1.0.x": "2025.1.0.4",
        "janela_2024.2.0.x": "2024.2.0.8",
        "janela_2024.1.0.x": "2024.1.0.2",
        "janela_2023.4.0.x": "Não encontrada"
      },
      "referencia_github": {
        "janela_2025.1.0.x": "2025.1.0.4",
        "janela_2024.2.0.x": "2024.2.0.8",
        "janela_2024.1.0.x": "Não encontrada",
        "janela_2023.4.0.x": "Não encontrada"
      },
      "consistente": false,
      "status_github": "Janela(s) ausente(s) no GitHub: 2024.1.0.x",
      "janelas_ausentes": ["2024.1.0.x"]
    }
  ],
  "servicos_sem_job_jenkins": [
    {
      "dominio_github": "sdk",
      "servico_bitbucket": "viasoft.core",
      "tipo_servico": "backend",
      "motivo": "jenkins_404"
    }
  ]
}