# SPEC: script-fix-services.md (Automação de Correção Automática)

## 1. Contexto & Objetivo
Criar o script `fix-services.js` (localizado dentro de `scripts/validacao-servicos/`). O objetivo deste script é ler o arquivo `report.json` gerado pelo validador, filtrar os serviços listados no nó de falhas (`invalid_services`) e aplicar as correções textuais diretamente nos arquivos `.yml.j2` correspondentes de forma cirúrgica.

**Premissa de Segurança:** O script deve realizar modificações em arquivos apenas se souber exatamente como corrigir o erro mapeado. Caso contrário, deve ignorar e alertar.

---

## 2. Pilha Tecnológica & Abordagem Técnica
- **Ambiente:** Node.js (ES6+).
- **Módulos Nativos:** `fs`, `path`.
- **Estratégia de Mutação:** Como os arquivos são templates Jinja2 e o parser de YAML pode remontar o arquivo alterando o espaçamento original ou quebrando tags complexas do Ansible, a abordagem recomendada para a correção é **manipulação de strings/Regex** diretamente no conteúdo original do arquivo, ou carregamento via parser YAML garantindo a preservação estrita do formato.
  - *Abordagem recomendada:* Ler o arquivo como texto (`fs.readFileSync`), localizar o bloco do `service_name` alvo, e aplicar as correções de linha por linha.

---

## 3. Abordagem de Caminhos de Arquivos (Pathing)
Como o script de correção roda a partir de `scripts/normalizacao-servicos/`, ele deve localizar o relatório de validação subindo um nível e apontando para a pasta vizinha:
- **Caminho do Report:** `path.join(__dirname, '../validacao-servicos/report.json')`

Os caminhos contidos dentro do JSON no campo `file_path` (ex: `roles/ADS01/...`) são relativos à **raiz do repositório**. Portanto, ao abrir os arquivos para correção, o script deve resolver o caminho a partir da raiz do projeto:
- **Resolução da Raiz:** `path.join(__dirname, '../../', item.file_path)`

---

## 4. Matriz de Correção Automática (Mapeamento de Erros)

O script deve ler os arrays de erros de cada item inválido e aplicar a respectiva correção:

### Cenário A: Erros em Serviços Não Exclusivos (Nas pastas de versão)
1. **Erro de Nome do Serviço (Chave Primária):**
   - *Se o erro for:* `"O nome do serviço (chave-primária) deveria terminar com '-{versao_com_hifens}'"`
   - *Ação:* Substituir a chave antiga do serviço no YAML pela nova chave corrigida com hifens.
2. **Erro de Container Name:**
   - *Se o erro for:* Contém falha no sufixo do `container_name`.
   - *Ação:* Localizar a linha `container_name:` do serviço alvo e alterar o valor final para `"[Prefixo]-{version_folder}"` (com pontos).
3. **Erro de Imagem:**
   - *Ação:* Garantir que a tag da imagem termine estritamente com `:{version_folder}.x{{ docker_image_suffix }}`.

### Cenário B: Erros Estratégicos de Frontend (Na raiz de composes)
- *Se o erro for:* `"Erro Estratégico: Serviços de Frontend não podem ser exclusivos..."`
- *Ação:* O script deve **mover** o arquivo `.yml.j2` da raiz para dentro da pasta da versão correspondente (criar a pasta `2025.1.0` ou `2024.2.0` se não existirem dentro da role). 
  - *Nota:* Como na raiz ele usava tags dinâmicas, ao mover para a pasta de versão, o script de correção deve ajustar a `image`, `container_name` e a chave do serviço para o padrão estático da pasta destino!

---

## 5. Remoção de `unversioned: true` em `vars/main.yml`
Para roles versionadas, o script remove a flag legada `unversioned: true` dos arquivos `roles/{role}/vars/main.yml`.

- **Escopo:** apenas entradas sob o bloco `services:`.
- **Preservação:** o nível `version:` deve permanecer no YAML, mesmo vazio.
- **Exceção:** entradas em `delphi_services:` **não** sofrem remoção de `unversioned: true`.

---

## 6. Fluxo de Execução do Script
1. Validar se o arquivo `report.json` existe no diretório. Se não, abortar.
2. Ler e fazer o parse do `report.json`.
3. Percorrer `results.exclusive.invalid_services` e aplicar as correções/migrações.
4. Percorrer `results.non_exclusive.invalid_services` e aplicar as correções textuais.
5. Imprimir no console um sumário de quantos serviços foram corrigidos com sucesso.

---