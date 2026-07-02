# Contexto Global do Projeto - Integração API Portainer

Este arquivo fornece as diretrizes, configurações e restrições do ambiente para o desenvolvimento de scripts de automação. Sempre siga estas especificações ao gerar código.

---

## 🖥️ Detalhes do Ambiente

* **Plataforma:** Portainer CE
* **Versão do Portainer:** 2.9.1 *(Atenção: Esta versão NÃO possui API Tokens estáticos/X-API-Key nas configurações de usuário)*
* **Protocolo da API:** HTTP *(ex.: `http://servidor:9011`)*
* **ID do Endpoint/Ambiente Principal:** 2 *(Confirmado via API)*

---

## 🔐 Fluxo de Autenticação Obrigatório (JWT)

Como a versão do Portainer é a 2.9.1, os scripts **devem obrigatoriamente** seguir o fluxo de autenticação em duas etapas (OAuth/JWT), pois tokens estáticos de longa duração não estão disponíveis.

1. **Obter o Token:** Fazer uma requisição `POST` para `/api/auth` enviando `username` e `password`.
2. **Extrair o JWT:** Tratar o JSON de resposta para capturar a chave `jwt`.
3. **Autorizar Requisições:** Incluir o cabeçalho `Authorization: Bearer <TOKEN_JWT>` em todas as chamadas subsequentes para os endpoints.

---

## 🌐 Multi-Ambiente e DNS Dinâmico (Requisito Crítico)

O Portainer está implantado em múltiplos servidores, o que significa que o **DNS/URL de destino varia**.
* **Regra de Desenvolvimento:** Nenhum script deve ter a URL do Portainer fixa (hardcoded). 
* A URL/DNS deve ser obrigatoriamente um **atributo selecionável/dinâmico** na execução do script (via argumentos de linha de comando como `--url` ou `-u`, variáveis de ambiente, ou menu interativo de seleção).
* **Protocolo:** Use sempre **HTTP** nas requisições (ex.: `http://host:9011/api/auth`). Se a URL não informar protocolo, assuma `http://`.

---

## 🔐 Fluxo de Autenticação Obrigatório (JWT)

Como a versão do Portainer é a 2.9.1, os scripts **devem obrigatoriamente** seguir o fluxo de autenticação em duas etapas (OAuth/JWT), pois tokens estáticos de longa duração não estão disponíveis.

1. **Obter o Token:** Fazer uma requisição `POST` para `<DNS_SELECIONADO>/api/auth` enviando `username` e `password`.
2. **Extrair o JWT:** Tratar o JSON de resposta para capturar a chave `jwt`.
3. **Autorizar Requisições:** Incluir o cabeçalho `Authorization: Bearer <TOKEN_JWT>` em todas as chamadas subsequentes para os endpoints.

---

## 📍 Estrutura de Endpoints para Referência

Sempre construa as URLs baseando-se no ID do ambiente correto (`2`):

* **Autenticação:** `POST /api/auth`
* **Listar Ambientes:** `GET /api/endpoints`
* **Listar Containers:** `GET /api/endpoints/2/docker/containers/json?all=true`
* **Listar Imagens:** `GET /api/endpoints/2/docker/images/json`
* **Listar Volumes:** `GET /api/endpoints/2/docker/volumes`
* **Listar Redes:** `GET /api/endpoints/2/docker/networks`

---

## 🛠️ Diretrizes para Escrita de Scripts

Quando for solicitado o desenvolvimento de um script, adote as seguintes boas práticas:

1. **Segurança de Credenciais:** Nunca chumbe (hardcode) a URL, usuário e senha diretamente no código principal. Use variáveis de ambiente (`.env`) ou argumentos de linha de comando.
2. **Gerenciamento de Erros:** Sempre trate falhas de autenticação (ex: HTTP 401 ou 422) de forma clara antes de tentar consumir os recursos do Docker.
3. **Linguagens Preferenciais:** [Insira aqui as linguagens que você prefere usar, ex: Bash (Shell Script), Python ou Node.js].