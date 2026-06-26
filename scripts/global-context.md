# SPEC: Automação de Validação e Correção de Docker Composes (IaC)

## 1. Contexto Geral
O projeto consiste em um repositório de Infraestrutura como Código (IaC) baseado em Ansible (`KorpSetupLinux`), responsável por implantar e gerenciar os containers Docker nos ambientes de produção dos clientes. 

O objetivo é criar uma ferramenta de automação utilizando **Node.js (JavaScript)** que varra a estrutura de diretórios das `roles`, valide a consistência dos arquivos de Docker Compose e aplique correções automáticas baseadas em regras de negócio predefinidas.

---

## 2. Pilha Tecnológica & Premissas
- **Ambiente de Execução:** Node.js (LTS recomendado).
- **Linguagem:** JavaScript (ES6+).
- **Extensão dos Arquivos Alvo:** Estritamente `.yml.j2` (Templates Jinja2 do Ansible).
- **Dependências Permitidas:** `fs` (nativo), `path` (nativo), e uma biblioteca de YAML (ex: `yaml` ou `js-yaml`).
  - *Nota de Engenharia:* Como os arquivos possuem sintaxe Jinja2 (ex: `{{ docker_account }}`), o script precisará tratar ou ignorar essas marcas de interpolação antes de realizar o parsing do YAML para evitar quebras de sintaxe.
- **Escopo Inicial de Versões:** Focar estritamente nas versões atualmente em produção:
  - `2025.1.0`
  - `2024.2.0`

---

## 3. Regras de Negócio e Conceitos de Serviço
A automação deve diferenciar e validar dois tipos cruciais de serviços contidos em `roles/[NOME_DA_ROLE]/templates/composes`:

### A. Serviços Versionados Exclusivos
* **Definição:** Apenas **1 container** do serviço roda por ambiente.
* **Localização no Projeto:** Na raiz da pasta de composes da role:
  `roles/{nome_da_role}/templates/composes/*.yml.j2`
* **Padrão Técnico de Exemplo (`roles/APS/templates/composes`):**
  - **Imagem:** Usa tags dinâmicas via Jinja2: `{{ version_without_build }}.x{{ docker_image_suffix }}`
  - **Container Name:** Dinâmico: `...-{{ version_without_build }}`
  - **Restart:** `no`

### B. Serviços Versionados Não Exclusivos
* **Definição:** **Múltiplas versões** do mesmo serviço rodam simultaneamente no mesmo ambiente.
* **Localização no Projeto:** Dentro de subpastas nomeadas com a versão correspondente:
  `roles/{nome_da_role}/templates/composes/2025.1.0/*.yml.j2`
  `roles/{nome_da_role}/templates/composes/2024.2.0/*.yml.j2`
* **Padrão Técnico de Exemplo (`roles/CON21_W/.../2025.1.0`):**
  - **Imagem:** Tag estática com a versão física: `2025.1.0.x{{ docker_image_suffix }}`
  - **Container Name:** Estático com a versão física: `CON21_W-2025.1.0`
  - **Restart:** `unless-stopped`

---

## 4. Mapeamento da Árvore de Diretórios Alvo (Escopo da Automação)
O script deve focar a varredura principalmente dentro do diretório `roles/` e seus subdiretórios de templates.

```text
KorpSetupLinux/
├── roles/
│   ├── APS/
│   │   └── templates/
│   │       └── composes/
│   │           └── [servico-exclusivo].yml.j2  <-- Versionado Exclusivo
│   ├── CON21_W/
│   │   └── templates/
│   │       └── composes/
│   │           ├── 2024.2.0/
│   │           │   └── [servico].yml.j2        <-- Versionado Não Exclusivo
│   │           └── 2025.1.0/
│   │               └── [servico].yml.j2        <-- Versionado Não Exclusivo
└── scripts/
    └── validacao-servicos/                     <-- Onde o script Node residirá
```

## 5. Decisões Estratégicas de Arquitetura
- **Regra de Frontend:** Todo e qualquer serviço cujo nome de imagem termine com o sufixo `-frontend` (ex: `viasoft.digital.assign-frontend`) **NÃO PODE** ser um Serviço Versionado Exclusivo. 
- **Obrigatoriedade:** Serviços de frontend devem residir estritamente dentro das pastas de versão física (`2024.2.0/` ou `2025.1.0/`), seguindo a regra de Versionados Não Exclusivos.

## 6. Remoção de Tags Legadas (Unversioned)
- **Regra de Compose:** Nenhum Serviço Versionado (Exclusivo ou Não Exclusivo) pode conter a flag `unversioned: true` em seus arquivos de variáveis da role (`roles/[NOME_DA_ROLE]/vars/*.yml`).
- **Preservação do bloco `version:`:** Ao remover `unversioned: true`, o nível `version:` **deve ser mantido** no YAML, mesmo que fique vazio. Exemplo correto após a correção:

```yaml
    version:

```

- **Proibido:** Remover a chave `version:` junto com a flag legada.
- **Exceção `delphi_services:`:** Entradas sob o bloco `delphi_services:` **não** devem sofrer remoção de `unversioned: true`. A limpeza da tag legada aplica-se **apenas** ao bloco `services:`.
- **Exceção por serviço:** Entradas em `services:` com as chaves abaixo **mantêm** `unversioned: true` (equivalente à lista de imagens completamente ignoradas no validador):
  - `Korp.AtualizacaoSistema` (`korp.atualizacaosistema` — tag fixa `1.0.x`, container name fixo)
- **Exceção parcial (container name fixo):** Os serviços abaixo usam imagem dinâmica `{{ version_without_build }}.x{{ docker_image_suffix }}`, mas **não** alteram `container_name` nem chave YAML do compose:
  - `Korp.Legacy.Frontend-router` (`korp.legacy.frontend-router`)
  - `Viasoft.Loader` (`viasoft.loader`)