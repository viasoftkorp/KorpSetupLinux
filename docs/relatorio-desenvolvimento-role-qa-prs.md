# Relatório de desenvolvimento — ambiente de QA com imagens de PR

- **Tarefa:** DEVO-6789
- **Branch:** `DEVO-6789-qa-prs-container`
- **Estado da entrega:** fase container Linux implementada, testada e publicada
- **Referência inicial:** `docs/superpowers/specs/2026-07-14-ambiente-qualidade-prs.md`
- **Data da consolidação:** 2026-07-30

## 1. Resumo executivo

Foi desenvolvido no `KorpSetupLinux` um fluxo operacional para aplicar imagens
de Pull Requests em uma máquina de qualidade sem alterar o provisionamento
normal usado em clientes.

A entrega é composta por:

- uma role de aplicação incremental, `qa_pr_apply`;
- uma role de reset global, `qa_pr_reset`;
- dois playbooks locais e independentes do `setup.sh`;
- um filter plugin Python compartilhado com a lógica determinística;
- o comando `qa-pr`, que simplifica instalação, diagnóstico, aplicação,
  consulta e reset;
- testes unitários, testes estruturais dos YAMLs, fixtures e documentação
  operacional.

O fluxo recebe links completos do GitHub, busca no MinIO os relatórios JSON
gerados pelo pipeline, encontra o serviço correspondente nos composes já
renderizados, resolve conflitos antes de qualquer mutação, cria um override
somente para o serviço afetado, seleciona a imagem no Harbor com fallback
controlado para o DockerHub e executa o Docker Compose de forma direcionada.

O reset valida todo o estado existente antes de apagar overrides e então
reaplica somente os composes base que estavam afetados.

O escopo entregue nesta branch é **somente `kind=container` em Linux**. O
mecanismo Delphi/Windows previsto como fase 2 na especificação inicial não foi
implementado.

## 2. Arquitetura entregue

```text
QA
 │
 └─ qa-pr apply <URL>
       │
       └─ pr-playbook.yml
            │
            └─ role qa_pr_apply
                 ├─ valida URLs e política
                 ├─ lê relatórios no MinIO por HTTPS anônimo
                 ├─ lê composes base e overrides existentes
                 ├─ monta alvos e ownerships
                 ├─ resolve todos os conflitos
                 ├─ grava/remove overrides
                 └─ aplica somente os serviços afetados

QA
 │
 └─ qa-pr reset
       │
       └─ pr-reset-playbook.yml
            │
            └─ role qa_pr_reset
                 ├─ lê e valida todos os overrides
                 ├─ valida a existência dos composes base
                 ├─ simula os composes em check mode
                 ├─ remove as raízes pr-overrides
                 └─ reaplica os composes base afetados
```

Não existe banco ou arquivo de estado adicional. O estado aplicado é
representado pelos próprios overrides em disco e pelas labels nos contêineres.

## 3. Como a role de aplicação funciona

### 3.1 Entrada

A entrada aceita uma URL ou uma lista de URLs completas:

```text
https://github.com/viasoftkorp/<repositorio>/pull/<numero>
```

O parser rejeita:

- número de PR sem URL;
- organização diferente de `viasoftkorp`;
- PR zero ou negativo;
- URL fora do formato esperado;
- entrada vazia.

Cada PR é transformado na identidade qualificada
`<repositorio>#<numero>`. Essa qualificação é necessária porque números de PR
são únicos apenas dentro de cada repositório.

### 3.2 Leitura dos relatórios

Para cada PR, a role lista anonimamente:

```text
https://minio-interno-api.korp.com.br/qa-prs/?list-type=2&prefix=prs/<repo>/<N>/
```

Depois lê cada objeto direto:

```text
prs/<repo>/<N>/<servico>.json
```

Decisões de segurança e consistência:

- apenas HTTPS com validação TLS;
- nenhuma credencial do MinIO na VM;
- nenhuma dependência de `mc`, AWS CLI, boto3 ou collection adicional;
- somente arquivos `.json` diretamente sob o prefixo são aceitos;
- listagens truncadas falham explicitamente, pois paginação ainda não foi
  implementada;
- a chave do objeto é codificada antes da leitura;
- o relatório é validado contra repositório, PR e nome do arquivo;
- nesta fase, somente `kind: container` é aceito;
- a imagem precisa ser `korp/<servico>` nos relatórios legados ou
  `harbor.korp.com.br/qa-prs/<servico>` nos relatórios novos;
- a tag é consumida do relatório, nunca reconstruída pela role.

Após validar o relatório, a role consulta a mesma tag em
`harbor.korp.com.br/qa-prs/<servico>`. Quando o artefato existe, essa passa a
ser a imagem desejada. Um `404` aciona fallback para
`korp/<servico>:<tag>` no DockerHub apenas se o relatório também for legado.
Se um relatório novo declarar Harbor e o artefato estiver ausente, a execução
falha. Outros erros do Harbor também interrompem a execução; indisponibilidade
não é confundida com ausência de uma imagem legada.

Campos obrigatórios do relatório:

```json
{
  "kind": "container",
  "pr": 123,
  "repositorio": "compras",
  "branch": "DEVO-6789-ajuste",
  "servico": "korp.compras.core",
  "imagem": "korp/korp.compras.core",
  "tag": "2025.1.0.42-pr123",
  "versao": "2025.1.0",
  "commit": "abc1234",
  "build": 42
}
```

### 3.3 Descoberta do serviço

A role lê os arquivos `*-compose.yml` das duas raízes já configuradas:

- `compose_dir_path`;
- `versioned_compose_dir_path`.

As raízes são normalizadas sem barra final e deduplicadas. Isso evita tratar
`/etc/korp/composes` e `/etc/korp/composes/` como projetos diferentes.

Para cada relatório, a role procura a chave YAML cujo `image` tenha o mesmo
repositório informado no JSON. A localização precisa resultar em exatamente
um serviço:

- zero resultados: falha;
- mais de um resultado: falha;
- exatamente um: gera o alvo de aplicação.

A identidade técnica do alvo é:

```text
<project_src>|<compose_file>|<service_key>
```

Essa identidade evita falsos conflitos entre serviços diferentes do mesmo
compose.

### 3.4 Ownership e conflitos

Cada serviço aplicado recebe:

```yaml
labels:
  korp.pr: "123"
  korp.repositorio: "compras"
```

O ownership persistido é `compras#123`. Overrides legados que possuam apenas
`korp.pr` são tratados como ownership desconhecido `#123` e conflitam de forma
conservadora com qualquer PR qualificado.

As políticas disponíveis são:

| Política | Resultado |
|---|---|
| `ask` | Padrão. Pergunta `replace` ou `keep`; qualquer outra resposta aborta |
| `replace` | Transfere os serviços conflitantes para o PR novo |
| `keep` | Preserva o owner atual e ignora somente os alvos conflitantes |
| `fail` | Falha se existir conflito e não altera o ambiente |

No modo `ask`, os conflitos são recalculados após cada decisão. Isso é
necessário quando uma única execução contém vários candidatos para a mesma
identidade.

O preflight inteiro termina antes da primeira escrita ou execução de compose.
Em `abort` ou `fail`, o plano retorna `may_mutate: false` e a role para antes
de modificar arquivos ou contêineres.

### 3.5 Plano de mutação

Depois do preflight, o plugin produz um plano puro contendo:

- alvos que serão aplicados;
- alvos ignorados;
- serviços que devem sair de overrides anteriores;
- arquivos que devem ser escritos;
- arquivos esvaziados que devem ser removidos;
- execuções de compose necessárias.

O override é gravado em:

```text
<project_src>/pr-overrides/pr<N>/<compose_file>
```

Exemplo:

```yaml
services:
  viasoft-workflow-orchestrator:
    image: "korp/viasoft.workflow.orchestrator:2025.2.0.1-pr330"
    labels:
      korp.pr: "330"
      korp.repositorio: "sdk"
```

### 3.6 Aplicação pelo Docker Compose

A role usa `community.docker.docker_compose_v2` com:

- o mesmo `project_src` do compose base;
- o mesmo `docker_env_file_path` do ambiente;
- arquivo base mais override;
- somente as chaves YAML dos serviços afetados;
- `remove_orphans` desabilitado por padrão.

Aplicar apenas os serviços afetados é essencial. Se o compose inteiro fosse
executado com apenas o override novo, outro serviço do mesmo compose que já
estivesse usando uma imagem de PR poderia voltar ao baseline.

## 4. Como a role de reset funciona

O reset é global: remove todos os PRs ativos da máquina. Não existe reset
seletivo nesta versão.

Antes de excluir qualquer arquivo, a role:

1. normaliza e deduplica as duas raízes de compose;
2. encontra todos os arquivos dentro de `pr-overrides`;
3. lê e valida todos os YAMLs;
4. exige o caminho canônico
   `<project_src>/pr-overrides/pr<N>/<compose_file>`;
5. valida `services`, `image`, `korp.pr` e, quando presente,
   `korp.repositorio`;
6. impede dois owners para a mesma identidade;
7. deriva a lista única de composes base afetados;
8. confirma que cada compose base existe e é arquivo regular;
9. executa `docker_compose_v2` em `check_mode` para validar os composes.

Somente após esse preflight a role:

1. remove as duas raízes `pr-overrides`;
2. reaplica cada compose afetado usando apenas seu arquivo base.

Se nenhum override existir, nenhuma execução de compose é necessária.

Esse desenho evita o pior cenário do reset: apagar o estado de PR e descobrir
depois que o baseline está ausente ou inválido.

## 5. Comando operacional `qa-pr`

O script `qa-pr` foi adicionado depois da role para reduzir a quantidade de
parâmetros que a equipe de QA precisa conhecer.

Comandos:

```bash
qa-pr doctor
qa-pr apply <URL> [URL...] [--ask|--fail|--keep|--replace]
qa-pr status
qa-pr reset [--yes]
qa-pr install
```

Responsabilidades:

- `doctor`: valida Ansible, collection Docker, Docker Compose, inventário,
  vault, playbooks e conectividade com MinIO e Harbor;
- `apply`: valida as URLs e traduz as opções para o playbook;
- `status`: lista overrides e contêineres com label `korp.pr`;
- `reset`: exige confirmação `RESET`, salvo quando usado com `--yes`;
- `install`: cria o link `/usr/local/bin/qa-pr`;
- todas as execuções de playbook geram log em
  `~/.local/state/korp-qa-pr`.

Variáveis de ambiente disponíveis para manutenção e testes:

| Variável | Padrão |
|---|---|
| `QA_PR_REPO_DIR` | diretório real do script |
| `QA_PR_INVENTORY` | `/etc/korp/ansible/inventory.yml` |
| `QA_PR_VAULT_ID` | `/etc/korp/ansible/.vault_key` |
| `QA_PR_COMPOSE_ROOT` | `/etc/korp/composes` |
| `QA_PR_MINIO_API` | `https://minio-interno-api.korp.com.br` |
| `QA_PR_HARBOR_API` | `https://harbor.korp.com.br/api/v2.0` |
| `QA_PR_LOG_DIR` | `~/.local/state/korp-qa-pr` |
| `QA_PR_SUDO` | `sudo` |
| `QA_PR_INSTALL_PATH` | `/usr/local/bin/qa-pr` |

O fluxo continua podendo ser executado diretamente pelos playbooks. O CLI é
uma camada operacional e não duplica a lógica de negócio das roles.

## 6. Arquivos criados

### 6.1 Execução

| Arquivo | Responsabilidade |
|---|---|
| `qa-pr` | CLI operacional para a equipe de QA |
| `pr-playbook.yml` | Entrada Ansible da aplicação |
| `pr-reset-playbook.yml` | Entrada Ansible do reset |
| `ansible.cfg` | Descoberta do filter plugin compartilhado |
| `filter_plugins/qa_pr_filters.py` | Validação, descoberta, ownership, conflitos e plano de mutação |
| `roles/qa_pr_apply/defaults/main.yml` | Endpoint, bucket, organização, política e acumuladores |
| `roles/qa_pr_apply/tasks/main.yml` | Orquestração completa da aplicação |
| `roles/qa_pr_apply/tasks/load_pr.yml` | Listagem dos relatórios de um PR |
| `roles/qa_pr_apply/tasks/load_report.yml` | Leitura e validação de cada JSON |
| `roles/qa_pr_apply/tasks/read_compose.yml` | Descoberta e leitura dos composes base |
| `roles/qa_pr_apply/tasks/read_override.yml` | Descoberta e leitura dos overrides ativos |
| `roles/qa_pr_apply/tasks/prompt_conflict.yml` | Resolução interativa dos conflitos |
| `roles/qa_pr_apply/tasks/write_override.yml` | Escrita dos overrides calculados |
| `roles/qa_pr_apply/tasks/apply_compose.yml` | Aplicação dirigida aos serviços afetados |
| `roles/qa_pr_reset/tasks/main.yml` | Preflight, remoção e orquestração do reset |
| `roles/qa_pr_reset/tasks/read_override.yml` | Leitura do estado e descoberta dos composes afetados |
| `roles/qa_pr_reset/tasks/reset_compose.yml` | Reaplicação do compose base |

### 6.2 Testes

| Arquivo | Cobertura principal |
|---|---|
| `tests/unit/test_qa_pr_filters.py` | Contratos, conflitos, ownership e planos puros |
| `tests/unit/test_qa_pr_role_yaml.py` | Estrutura, ordem e segurança da aplicação |
| `tests/unit/test_qa_pr_reset_role_yaml.py` | Estrutura e preflight seguro do reset |
| `tests/unit/test_qa_pr_cli.py` | Tradução do CLI, validação, confirmação, status e doctor |
| `tests/fixtures/qa_prs/listing.xml` | Resposta ListObjectsV2 |
| `tests/fixtures/qa_prs/korp.compras.core.json` | Contrato de relatório container |
| `tests/fixtures/qa_prs/base-compose.yml` | Compose base de teste |
| `tests/fixtures/qa_prs/existing-override.yml` | Override ativo de teste |

### 6.3 Documentação e registros de engenharia

| Arquivo | Finalidade |
|---|---|
| `docs/ambiente-qualidade-prs.md` | Guia operacional |
| `docs/superpowers/specs/2026-07-14-ambiente-qualidade-prs.md` | Especificação inicial |
| `docs/superpowers/plans/2026-07-28-ambiente-qualidade-prs-container.md` | Plano da fase container |
| `docs/superpowers/specs/2026-07-29-qa-prs-final-review-hardening-design.md` | Decisões do hardening |
| `docs/superpowers/plans/2026-07-29-qa-prs-final-review-hardening.md` | Plano do hardening |

## 7. Arquivos existentes modificados

| Arquivo | Alteração |
|---|---|
| `.ansible-lint` | Contexto mínimo para lint das novas roles e exceção documentada de prefixo compartilhado |
| `.gitignore` | Ignora worktrees locais e normaliza final do arquivo |
| `readme.md` | Adiciona link para o guia operacional |

O `setup.sh` e o `main.yml` **não foram alterados**. Essa separação é
intencional para que a lógica de PR não faça parte do provisionamento normal
de servidores e clientes.

## 8. Principais escolhas técnicas

### Roles separadas de aplicação e reset

Mantêm responsabilidades claras e permitem restaurar o ambiente sem
reprovisionar a VM inteira.

### Filter plugin Python para lógica determinística

Parsing, validações, conflitos e geração do plano foram concentrados em
funções puras. Isso reduz lógica complexa em Jinja/YAML e permite testes
rápidos sem Docker ou MinIO reais.

O plugin foi movido da role de aplicação para `filter_plugins/` na raiz para
que aplicação e reset usem exatamente a mesma validação.

### Estado em overrides, sem banco auxiliar

Evita sincronização entre um arquivo de controle e o estado real. Os
overrides são fonte de verdade, enquanto as labels tornam o estado visível no
Docker e no Portainer.

### Preflight antes de mutação

Todas as entradas, relatórios, composes, overrides e decisões são validados
antes de escrever ou remover arquivos. Esse princípio foi aplicado tanto na
aplicação quanto no reset.

### Aplicação incremental por serviço

O uso de `services` no Compose permite que PRs de serviços diferentes
coexistam, inclusive quando pertencem ao mesmo arquivo de compose.

### Mesmo `project_src` e nenhum `remove_orphans`

Preserva o nome do projeto Compose existente e impede que a execução de um PR
remova contêineres de outros aplicativos.

### Imagem e tag vindas do relatório

A role não tenta descobrir `BUILD_NUMBER` nem montar a tag. O pipeline é a
fonte da verdade e cada novo build gera uma tag imutável.

### Leitura anônima do MinIO

Mantém credenciais fora das VMs de QA e evita dependências novas no setup.
A escrita dos relatórios continua sendo responsabilidade autenticada do
pipeline Jenkins.

## 9. Comparação com a documentação inicial

### 9.1 Itens seguidos

| Requisito inicial | Situação |
|---|---|
| Links completos de PR como entrada | Implementado |
| Identidade qualificada por repositório e número | Implementado |
| Relatórios em `prs/<repo>/<N>/<servico>.json` | Implementado |
| Leitura anônima do endpoint S3 interno | Implementado |
| Harbor como origem preferencial e DockerHub para legado | Implementado posteriormente |
| HTTPS com validação de certificado | Implementado |
| Sem `mc`, AWS CLI, boto3 ou nova collection para leitura | Implementado |
| Tag recebida do relatório | Implementado |
| Descoberta nos composes renderizados | Implementado |
| Modelo incremental | Implementado |
| Override dentro do `project_src` e separado por PR | Implementado |
| Label `korp.pr` | Implementado |
| Conflitos `ask`, `replace`, `keep` e `fail` | Implementado |
| Todos os conflitos resolvidos antes da mutação | Implementado |
| Aplicação apenas dos serviços afetados | Implementado |
| Mesmo `project_src` do setup | Implementado |
| Não usar `remove_orphans` | Implementado |
| Reset dedicado | Implementado |
| Reset reaplica somente composes afetados | Implementado |
| Não integrar ao `setup.sh` ou `main.yml` | Implementado |
| Não validar versão PR × VM no MVP | Mantido como risco aceito |
| Não bloquear automaticamente cliente final | Mantido como risco aceito e documentado |

### 9.2 Evoluções em relação ao desenho inicial

| Evolução | Motivo |
|---|---|
| Harbor preferencial com fallback por `404` | Consumir novos builds internos sem perder imagens produzidas antes da migração |
| Label `korp.repositorio` além de `korp.pr` | Evitar confundir PRs com mesmo número em repositórios diferentes |
| Ownership legado conservador | Não assumir incorretamente o repositório de overrides antigos |
| Plugin compartilhado na raiz | Aplicação e reset usam a mesma validação |
| Validação completa do reset antes da deleção | Evitar remover overrides quando o baseline está inválido |
| Validação do compose base em `check_mode` | Detectar erro antes de apagar o estado atual |
| Normalização das raízes de compose | Corrigir duplicidade causada por barra final |
| CLI `qa-pr` | Simplificar o fluxo para a equipe de QA |
| Logs operacionais por execução | Facilitar diagnóstico e manutenção |

### 9.3 Itens não implementados nesta branch

| Item da especificação | Situação atual |
|---|---|
| Despacho de `kind: delphi` para Windows | Não implementado; o parser rejeita explicitamente |
| Reset de binários Delphi no Windows | Não implementado |
| Alterações nos Jenkinsfiles para build/publicação | Não pertencem a esta branch do `KorpSetupLinux`; a role consome os JSONs já publicados |
| Configuração/policy do bucket MinIO | Pré-requisito externo; não alterada neste repositório |
| Paginação ListObjectsV2 | Não implementada; listagem truncada falha de forma explícita |
| Reset seletivo por PR | Não previsto no MVP; reset atual é global |
| Atualização automática após novo push | Não implementada; é necessário reaplicar o link |
| Reset automático após merge/fechamento | Não implementado |
| Guarda automática contra cliente final | Deliberadamente não implementada no MVP |
| Validação de compatibilidade da versão | Deliberadamente não implementada no MVP |
| Alocação/reserva de VM por testador | Não implementada |
| Reversão de migration/schema | Fora do alcance do Compose |
| PRs que alteram apenas pacotes NuGet/npm | Continuam limitados pelo pipeline de pacotes |
| Retenção de tags de PR no Harbor e DockerHub | Não definida |

O maior desvio do entregável completo descrito inicialmente é o Delphi. O
plano executado restringiu explicitamente esta entrega à fase container
Linux; portanto, a solução atual não é ainda o despachante unificado
container + Delphi imaginado no documento original.

## 10. Testes e validação realizados

Na branch:

- 73 testes unitários e estruturais aprovados;
- `bash -n qa-pr` aprovado;
- syntax check dos dois playbooks aprovado;
- `ansible-lint` aprovado com perfil `production`, sem falhas ou avisos;
- `git diff --check` aprovado.

Validação real executada na máquina QA1:

1. instalação global do `qa-pr`;
2. `qa-pr doctor`;
3. confirmação de ambiente inicialmente sem overrides;
4. aplicação do PR `sdk#330`;
5. confirmação do override, da imagem de PR e das labels;
6. reset do ambiente;
7. confirmação de ausência de overrides e labels de PR;
8. confirmação da imagem base, contêiner `running` e zero reinicializações.

Foram observados dois avisos do ambiente, sem falha funcional:

- descoberta automática do interpretador Python pelo Ansible;
- aviso de containers órfãos do Compose, esperado porque vários composes
  compartilham o mesmo projeto. Nenhum órfão é removido.

## 11. Manutenção

### 11.1 Onde alterar cada comportamento

| Necessidade | Arquivo principal |
|---|---|
| Endpoint, bucket, organização ou política padrão | `roles/qa_pr_apply/defaults/main.yml` |
| Contrato e validação do JSON | `filter_plugins/qa_pr_filters.py`, função `load_report` |
| Formato das URLs | `normalize_pr_links` |
| Parsing/listagem do MinIO | `parse_minio_listing` e `tasks/load_pr.yml` |
| Descoberta de imagem nos composes | `build_targets` |
| Formato e validação dos overrides | `index_active_overrides` |
| Semântica dos conflitos | `detect_conflicts` e `resolve_application` |
| Ordem da aplicação | `roles/qa_pr_apply/tasks/main.yml` |
| Execução do Compose | `tasks/apply_compose.yml` |
| Segurança do reset | `roles/qa_pr_reset/tasks/main.yml` |
| Experiência do QA | `qa-pr` |

### 11.2 Invariantes que devem ser preservados

Ao fazer manutenção, não quebrar:

- validação completa antes da primeira mutação;
- ownership por `<repositorio>#<N>`;
- caminho canônico direto de override;
- exatamente um compose base por imagem;
- mesmo `project_src` do setup;
- execução limitada por `services`;
- ausência de `remove_orphans`;
- leitura anônima e TLS validado;
- imagem/tag sempre vindas do relatório;
- reset validado antes da deleção;
- independência de `setup.sh` e `main.yml`.

### 11.3 Comandos de validação

Executar em um ambiente Python com Ansible Core, PyYAML,
`community.docker` e `ansible-lint`:

```bash
python3 -m unittest discover -s tests/unit -v
bash -n qa-pr
ansible-playbook --syntax-check pr-playbook.yml
ansible-playbook --syntax-check pr-reset-playbook.yml
ansible-lint \
  pr-playbook.yml \
  pr-reset-playbook.yml \
  roles/qa_pr_apply \
  roles/qa_pr_reset
git diff --check
```

Antes de validar na máquina de QA:

```bash
qa-pr doctor
qa-pr status
```

Depois de qualquer teste que aplique imagem:

```bash
qa-pr reset
qa-pr status
```

### 11.4 Diagnóstico

- logs do CLI: `~/.local/state/korp-qa-pr`;
- estado persistido: `<project_src>/pr-overrides/`;
- estado visível no Docker: labels `korp.pr` e `korp.repositorio`;
- relatório fonte: `qa-prs/prs/<repo>/<N>/<servico>.json`;
- compose base: arquivo identificado pelo repositório da imagem.

Não editar overrides manualmente. O reset valida formato, caminho, labels e
ownership; um arquivo manual inválido fará o fluxo falhar por segurança.

## 12. Próximos passos recomendados

### Prioridade alta

1. Instalar e validar o `qa-pr` nas demais máquinas de QA.
2. Confirmar cobertura de geração dos JSONs em todas as stacks e versões de
   Jenkins usadas pelos serviços que serão testados.
3. Criar uma trava explícita de ambiente interno/QA antes da execução
   privilegiada.
4. Validar compatibilidade entre a versão informada no relatório e a versão
   base da VM, com mensagem clara para o operador.

### Prioridade média

5. Implementar paginação do ListObjectsV2.
6. Avaliar reset seletivo por ownership, mantendo o reset global como opção.
7. Melhorar a apresentação de `qa-pr status`, incluindo commit, branch e
   build do relatório.
8. Automatizar refresh após novo build e limpeza após merge, caso a operação
   manual se torne frequente.
9. Adicionar testes de integração automatizados com MinIO e Docker Compose
   descartáveis.

### Fases futuras

10. Resolver os bloqueios do Delphi e implementar o destino Windows para
    `kind: delphi`.
11. Definir o contrato do relatório Delphi e seu mecanismo de reset.
12. Definir retenção das tags imutáveis de PR no Harbor e DockerHub.
13. Tratar PRs de bibliotecas/pacotes e estratégia de rollback de schema.
14. Criar reserva ou identificação de uso das VMs para reduzir colisão entre
    testadores.

## 13. Conclusão

A fase container entregue segue os pilares da especificação inicial:
relatórios no MinIO, entrada por links completos, aplicação incremental,
overrides por PR, conflitos resolvidos antes de mutação, Compose dirigido por
serviço e reset separado do provisionamento.

Durante o desenvolvimento, a implementação foi endurecida principalmente em
ownership qualificado, validação do reset, compartilhamento do plugin e
normalização das raízes de compose. O CLI foi acrescentado para transformar
os playbooks em um fluxo simples para a equipe de QA.

O fluxo container está operacional e foi validado em uma máquina real. Para
atender integralmente a visão original do ambiente unificado, ainda faltam a
fase Delphi/Windows e as automações externas listadas nos próximos passos.
