# Design: Ambiente de Qualidade por PRs

**Data:** 2026-07-14
**Status:** Requisitos fechados (MVP)
**Escopo:** roles novas no `KorpSetupLinux` + alteração nos templates do `viasoft.jenkins`

---

## Contexto

A Qualidade pega uma tarefa para testar. Uma tarefa tem 1..N PRs; um PR tem 1..N serviços — os repositórios são monorepos, com um job Jenkins por serviço. Hoje não há como montar um ambiente que combine esses PRs antes do merge.

```text
TAREFA (ex: DEVO-6592)
  └── PR (ex: korp.compras#123)
        └── serviço
              ├── container  → roda no Linux  (ex: korp.compras.core)
              └── delphi     → roda no Windows (ex: KorpCadastrosService)
```

A proposta: a Qualidade informa a lista de PRs de uma tarefa, e o ambiente é atualizado com os serviços afetados. **O entregável é único do ponto de vista da QA** — um só lugar para informar os PRs, um só ambiente resultante — mesmo que por baixo existam dois mecanismos de entrega, porque os serviços de uma tarefa podem ser de dois tipos:

| Tipo de serviço | Onde roda | Como é atualizado |
|---|---|---|
| **container** | Linux (VM de QA) | troca da tag da imagem no compose (Componentes 1–3) |
| **delphi** | Windows | entrega do binário do PR (Componente 4) |

A QA não escolhe nem separa por tipo: informa os PRs, e a ferramenta despacha cada serviço para o mecanismo certo, decidindo pelo **tipo declarado no relatório do Jenkins** (ver Componente 1). O "ambiente de QA" é, portanto, a VM Linux **mais** a máquina Windows associada.

Serão 5 VMs de qualidade Linux, idênticas, provisionadas com este repositório **como cliente final**; a topologia Windows é ponto em aberto (Componente 4).

### Divisão de responsabilidades

| Componente | Papel | Alterado? |
|---|---|---|
| `KorpSetupLinux` — base | Provisiona a VM Linux como cliente final (baseline) | **Não** |
| `KorpSetupLinux` — role de PRs | Aplica a lista de PRs: despacha container→Linux, delphi→Windows | **Sim** (entregável) |
| `KorpSetupLinux` — role de reset | Remove os PRs e volta ao baseline (Linux e Windows) | **Sim** (entregável) |
| `viasoft.jenkins` (templates v3) | Publica imagem do PR (container) e emite o relatório | **Sim** (ver Achado 1) |
| Jenkinsfile do Delphi **ERP** (outro repo) | Publica binário do PR (Windows) e emite o relatório | **Sim** (Componente 4) |
| Jenkinsfile do Delphi **Nuvem Fiscal** (outro repo) | Publica binário do PR (Windows) e emite o relatório | **Sim** (Componente 4) |

**Por que as roles vivem no `KorpSetupLinux`:** as convenções (caminho dos composes, nome do `.env`, derivação do project name do Compose, `version_without_build`) já existem aqui, e o repositório já provisiona a VM de QA. A orquestração da QA fica junto do que ela orquestra — inclusive o despacho para o Windows, mesmo que a entrega lá seja um mecanismo à parte.

**Por que o reset é uma role separada** da aplicação e da base: mantém o setup padrão (usado em cliente final) livre de qualquer lógica de PR.

---

## Fluxo alvo

```text
Dev abre PR
     │
     ▼
Jenkins (um job por serviço) ──▶ detecta alteração em <servico>/ ──▶ (sem alteração: encerra)
                                        │ com alteração
                                        ├──▶ push  korp/<servico>:<versao>.x-pr<N>
                                        └──▶ relatório  minio-interno.korp.com.br
                                                   prs/<N>/<servico>.json
                                                          │
Qualidade ──▶ VM ──▶ role de PRs (prs=123,456) ───────────┘
                          │
                          ├──▶ lê o relatório de cada PR  → serviços + tags
                          ├──▶ localiza o serviço nos composes renderizados
                          ├──▶ escreve override em pr-overrides/pr<N>/
                          └──▶ docker_compose_v2 (base + override)
                                        │
                                        ▼
                          container rodando :<versao>.x-pr<N>, label korp.pr=<N>

Qualidade ──▶ VM ──▶ role de reset ──▶ apaga pr-overrides/ + sobe só a base
```

---

## Estado da VM provisionada

O setup renderiza os composes e os deixa em disco:

| Caminho | Conteúdo |
|---|---|
| `/etc/korp/composes/<AppId>-compose.yml` | Serviços exclusivos / não versionados |
| `/etc/korp/composes/<versao>/<AppId>-compose.yml` | Serviços versionados (`versioned_compose_dir_path`) |
| `/etc/korp/composes/.env` | Env compartilhado (`docker_env_file_path`) |

Depois de renderizada, a linha de imagem é **literal** — o Jinja2 já foi resolvido:

```yaml
image: "korp/korp.compras.core:2025.1.0.x"
```

É essa string que a role reescreve. **`docker_image_suffix` não participa do desenho** — nesta camada ele já virou texto.

---

## Decisões

| # | Tema | Decisão |
|---|---|---|
| 1 | Convenção de tag | `korp/<servico>:<versao>.<build>-pr<N>` — encaixa no padrão atual `${BUILD_VERSION}${DOCKER_IMAGE_SUFFIX}` com suffix `-pr<N>`. Ex: `2025.1.0.42-pr123` |
| 2 | Rebuild | A cada push no PR; **tag imutável**. O ambiente fica pinado no build aplicado até a role ser re-executada |
| 2.1 | Tags publicadas em PR | **Só uma** (a `BUILD_VERSION`). A `<versao>.x-pr<N>` não é publicada |
| 3 | Modelo da lista | **Incremental** — soma ao que já está no ambiente |
| 4 | Baseline | Suffix vazio: `korp/korp.compras.core:2025.1.0.x` |
| 5 | Reset | Role dedicada: apaga os overrides e volta ao baseline |
| 6 | VMs | 5, idênticas inicialmente |
| 7 | Input da Qualidade | **Lista de PRs** (não a tarefa) |
| 8 | Onde mora o código | Roles novas no `KorpSetupLinux`, só para ambientes internos |
| 9 | Versão da tag no build | O Jenkins resolve |
| 10 | Forma de aplicar | **Arquivo de override**, uma pasta por PR |
| 11 | Resolução PR → serviços | **Relatório do Jenkins** no MinIO interno — sem credencial nas VMs |
| 12 | Endereço do relatório | MinIO interno, API S3: `https://minio-interno-api.korp.com.br` (**não** o Console — ver Componente 0) |
| 13 | Granularidade do relatório | Um arquivo por **(PR, serviço)** — sem race entre jobs concorrentes |
| 14 | Descoberta pela Qualidade | Label `korp.pr=<N>` no container, visível/filtrável no Portainer |
| 15 | PR mergeado | Fora de escopo — o reset resolve |
| 16 | Validação de versão (PR × VM) | Não valida |
| 17 | Estado do incremental | Não há — o ambiente é auto-descritivo pelo label |
| 18 | Dois PRs no mesmo serviço | Não detecta; o último aplicado vence |
| 19 | Guarda contra rodar em cliente | Não bloqueia |
| 20 | Alocação PR × VM | Ignorada |
| 21 | Baseline após reset | Pode se mover (puxa a `.x` mais recente) |
| 22 | Schema de banco sujo | Aceito |
| 23 | Plataforma no build de PR | **Somente `linux/amd64`** — as VMs de QA são AMD; ARM só encareceria o build |
| 24 | Leitura do bucket | **Anônima** na rede interna — mantém as VMs sem credencial e a role sem CLI (ver Componente 0) |
| 25 | Serviços Delphi | **Dentro do entregável**, como 2º mecanismo (Windows) despachado por `kind` — fase 2, não projeto à parte (ver Componente 4) |
| 26 | Famílias Delphi | **Duas**: Delphi do ERP e Delphi do Nuvem Fiscal — dois Jenkinsfiles distintos a alterar (ver Componente 4) |
| 27 | Escrita do Jenkins no MinIO | Reusa a `MINIO_INTERNO_KEY`; policy dela ganha `PutObject` em `arn:aws:s3:::qa-prs/prs/*` (ver Componente 0) |
| 28 | Upload do relatório em C#/frontend | Adicionar `aws`/`mc` às imagens de build; **frontend = `jnlp-frontend.Dockerfile.1.1.x`** (verificado, o `1.0.x` é obsoleto), csharp = `.1.0.5` (aws comentado). golang já tem. Só v3 (ver 1.3) |

---

## Componente 0 — MinIO interno (pré-requisito)

### Os dois endereços — não confundir

| Endereço | O que é | Uso |
|---|---|---|
| `https://minio-interno.korp.com.br` | **Console** (UI web) | Operação humana: criar bucket, policy, service account |
| `https://minio-interno-api.korp.com.br` | **API S3** (`MINIO_INTERNO_ADDRESS`) | Jenkins (escrita) e role (leitura) |

Ambos resolvem para `192.168.1.18` — é o mesmo host, separado por vhost no nginx.

> ⚠️ **O Console não atende S3.** Uma requisição S3 assinada contra ele retorna:
>
> ```xml
> <Error><Code>InvalidArgument</Code><Message>S3 API Requests must be made to API port.</Message></Error>
> ```
>
> Pior: requisições comuns caem na SPA do Console, que devolve **200 + HTML para qualquer caminho**, inclusive buckets inexistentes. Qualquer teste feito contra o Console dá falso positivo. Use sempre o host `-api`.

### O que foi verificado (2026-07-15)

| Fato | Verificação |
|---|---|
| `minio-interno-api.korp.com.br` → `192.168.1.18`, alcançável | `getent hosts` + `curl` |
| **É a API S3 de verdade** — devolve XML nativo (`AccessDenied`, "AWS authentication requires a valid Date or x-amz-date header") | requisição S3 assinada |
| `/minio/health/live` → 200 | `curl` |
| TLS **válido**, cadeia completa — GlobalSign `*.korp.com.br`, expira **10/mar/2027** | `curl` sem `-k` retorna 200 em **ambos** os hosts |
| Jenkins já possui `MINIO_INTERNO_{KEY,SECRET,REGION,ADDRESS}` | `golang_jenkinsfile:475-480` |
| Portas 9000/9001 não respondem da rede de desenvolvimento | `curl` timeout — o acesso é pelos vhosts em 443 |

**O `--no-verify-ssl` do `publishS3` é legado.** O certificado é válido e verificável nos dois hosts — a role não precisa desabilitar verificação de TLS, e o Jenkins também não precisaria.

**Não é possível descobrir anonimamente se um bucket existe.** O MinIO responde `AccessDenied` tanto para bucket privado existente quanto para inexistente (não vaza existência a chamador não autenticado) — verificado com nome de controle aleatório. Conferir a existência exige o Console ou credencial.

### Região: `us-east-1`

Valor de `MINIO_INTERNO_REGION` no Jenkins — **o default do MinIO**, coerente com o `compose-mionio.yml` não definir `MINIO_SITE_REGION`. O servidor está sem região configurada.

**O servidor não valida região.** O `s3_version_updater_service.go:95` usa `sa-east-1` (`config.WithRegion("sa-east-1")`) e o Jenkins usa `us-east-1`, contra o **mesmo** MinIO, e ambos funcionam. Ou seja, `mc mb --region` aqui é decorativo — e o `sa-east-1` do Go é ruído, não uma configuração a respeitar.

Duas notas para quem mexer nisso depois:

- **No MinIO região é do deployment, não do bucket** (`MINIO_SITE_REGION`, antes `MINIO_REGION_NAME`) — não existe "a região deste bucket" como na AWS.
- **A região só importa no caminho de escrita** (Jenkins, que assina SigV4). A role lê anonimamente, sem assinatura — para ela, região é irrelevante.
- Sondar região anonimamente **não funciona**: o MinIO valida o access key antes da região, então assinaturas com `xx-regiao-falsa-1`, `sa-east-1` e `us-east-1` devolvem todas o mesmo `InvalidAccessKeyId`.

### Checklist

| # | Item | Situação |
|---|---|---|
| 1 | Endpoint da API S3 | ✅ `https://minio-interno-api.korp.com.br`, verificado |
| 2 | Bucket | ✅ `qa-prs` criado |
| 3 | Leitura anônima | ✅ **Aplicada e verificada** (ver abaixo) |
| 4 | Lifecycle de expiração | ✅ Regra `expira-relatorios-pr-60d` — 60 dias sobre `prs/`, aplicada e lida de volta |
| 5 | Escrita do Jenkins | ⬜ **Policy da `MINIO_INTERNO_KEY` precisa de 1 linha** — hoje só tem `PutObject` em `cdn-korp*`, não no `qa-prs` (ver abaixo) |
| 6 | Região | ✅ `us-east-1` (`MINIO_INTERNO_REGION` no Jenkins) — o default do MinIO |

**Policy da `MINIO_INTERNO_KEY` — delta necessário.** A chave que o Jenkins já usa **não** alcança o `qa-prs` (confirmado: policy atual só cobre `cdn-korp-development/*`, `cdn-korp-hmlg/*`, `cdn-korp/*`). Adicionar `arn:aws:s3:::qa-prs/prs/*` à mesma statement de `s3:PutObject`:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["s3:PutObject"],
      "Resource": [
        "arn:aws:s3:::cdn-korp-development/*",
        "arn:aws:s3:::cdn-korp-hmlg/*",
        "arn:aws:s3:::cdn-korp/*",
        "arn:aws:s3:::qa-prs/prs/*"
      ]
    }
  ]
}
```

Escopo `qa-prs/prs/*` (não `qa-prs/*`): a chave só escreve no prefixo dos relatórios. `PutObject` sobrescreve chave existente, então cobre o rebuild a cada push sem precisar de mais nada. É uma policy de **usuário/service account** no MinIO (aplicada no Console/`mc`), não a bucket policy do Componente 0.

A bucket policy está versionada em `iac`, `local-infrastructure/ECS01/minio/qa-prs-bucket-policy.json`.

### Verificação do bucket (2026-07-15)

Executado contra `https://minio-interno-api.korp.com.br/qa-prs`:

| Teste | Resultado |
|---|---|
| Listar `?list-type=2&prefix=prs/` | ✅ `ListBucketResult` |
| Listar `?list-type=2&prefix=prs/123/` (sub-prefixo) | ✅ `ListBucketResult` |
| Listar sem prefixo | ✅ `ListBucketResult` |
| `PUT` anônimo | ✅ `403 AccessDenied` — anônimo não escreve |
| `GET` fora de `prs/` | ✅ `403 AccessDenied` — escopo respeitado |
| `GET` dentro de `prs/` (objeto inexistente) | ✅ `404 NoSuchKey` — autorizado, bucket vazio |

O par `403` fora / `404` dentro é o que prova o escopo da policy.

⚠️ **Não aplicar a policy pela aba *Anonymous* / *Add Access Rule* do Console.** Ela gera condição `s3:prefix` amarrada ao prefixo digitado, o que autorizaria listar `prs/` mas **não** `prs/123/` — a role quebraria só na listagem, de forma silenciosa. Use a policy custom (`Summary` → *Access Policy* → Custom), que é a versionada no `iac` e não tem condição de prefixo no `ListBucket`.

**Onde aplicar/versionar:** o MinIO interno pertence ao repo `iac` (GitHub `viasoftkorp/iac`), em `local-infrastructure/ECS01/` — `compose-mionio.yml` (o deploy) e `nginx/conf/minio-interno.conf` (os dois vhosts). É lá que a policy do bucket deve ser versionada, se versionada. Segredo não entra no repo, seguindo a convenção que o `compose-mionio.yml` já adota (`MINIO_ROOT_USER=` vazio).

### Por que leitura anônima (e por que autenticada foi descartada)

A decisão 11 escolheu o relatório em vez da API do Jenkins justamente para **não haver credencial nas VMs**. A tentativa de exigir leitura autenticada trouxe dois custos que a anônima não tem:

**1. Assinar SigV4.** `ansible.builtin.uri` não assina. As saídas seriam `mc` em container ou instalar `amazon.aws` + boto3 — e a instalação de collection mora no `setup.sh` (`setup.sh:236` instala só `community.docker`; não existe `requirements.yml`), que é a base que decidimos não tocar.

**2. Entregar a credencial.** Exigiria um KV novo no Vault (ex: `kv/vault-manager/credentials/minio-qa-prs`, seguindo `.../salt-api` e `.../zabbix-api`) **e** um endpoint novo no `ServerDeployController` do `viasoft.vault.manager` — mudança num terceiro repositório, fora do escopo.

> ⚠️ Se algum dia se revisitar a opção autenticada: **não** entregar a credencial via `secrets/{token}` / KV `kv/server-deploy/services/consul-secrets`. É o atalho tentador e vaza — `ManageSecrets.GetConsulSecrets(Guid tenant)` **ignora o tenant** no path (`ManageSecrets.cs:110`): é um KV compartilhado, entregue a **todo** servidor provisionado, inclusive cliente final.

Com leitura anônima, nada disso existe: a role dispensa credencial **e** CLI.

### Como a role lê o bucket

```yaml
- ansible.builtin.uri:                                    # listar os serviços do PR
    url: "https://minio-interno-api.korp.com.br/qa-prs/?list-type=2&prefix=prs/123/"
    return_content: true

- ansible.builtin.uri:                                    # ler um relatório
    url: "https://minio-interno-api.korp.com.br/qa-prs/prs/123/korp.compras.core.json"
    return_content: true
```

Sem `mc`, sem `aws`, sem boto3, sem collection nova, sem tocar no `setup.sh`. A listagem devolve XML (ListObjectsV2 não tem saída JSON) — o parse é detalhe de implementação da role.

**O que fica exposto na rede interna:** repositório, branch, ticket, serviço, imagem, tag, commit e build. Nenhum segredo.

O item 4 cobre só o acúmulo dos **relatórios**. O acúmulo de **tags no DockerHub** (decisão 1, tag imutável) é risco separado e segue sem dono.

---

## Componente 1 — Jenkins

### 1.1 Publicar imagem em PR

Hoje o publish é pulado em PR nos três templates (Achado 1). É preciso liberá-lo para PR com `DOCKER_IMAGE_SUFFIX = "-pr${env.CHANGE_ID}"`, reusando a montagem de tag que já existe — mas publicando **só a segunda** das duas tags:

```groovy
def tags = "-t ${docker_account_name}/${repository_name}:${publish_version}.x${docker_image_suffix} "   // NÃO em PR
tags = tags + "-t ${docker_account_name}/${repository_name}:${build_version}${docker_image_suffix} "    // a tag do PR
```

Com `build_version = 2025.1.0.42` e `docker_image_suffix = -pr123`, sai `korp/korp.compras.core:2025.1.0.42-pr123` — sem inventar formato novo.

**O Jenkins precisa resolver `BUILD_VERSION` em PR.** Hoje ela só é resolvida em `IS_DEV` (a partir do `version.yaml`) e parametrizada em `IS_PRD`/`IS_HMLG`; em PR não há resolução. O `IS_DEV` é o precedente exato a copiar:

```groovy
BUILD_VERSION = "${PUBLISH_VERSION}.${env.BUILD_NUMBER}"
```

**Por que a tag imutável e não a `.x-pr<N>` mutável:** com a tag mutável, um novo push no PR não muda o conteúdo do override — o Compose compara a config desejada com a do container, não vê diferença e **não recria**. Seria preciso `pull: always` mais recreate forçado, e a Qualidade não teria sinal visível de ter pego (ou não) o commit novo. Com a tag imutável, a tag muda → o override muda → o Compose recria e puxa naturalmente. De quebra, `docker ps` passa a dizer exatamente qual build está rodando.

**`BUILD_NUMBER` é por job**, e cada serviço é um job: o PR 123 tocando dois serviços gera `korp.compras.core:2025.1.0.42-pr123` e `korp.compras.frontend:2025.1.0.17-pr123`. O relatório por (PR, serviço) absorve isso naturalmente — só não existe "o build 42 do PR 123" como conceito global.

### 1.2 Build de PR é amd64-only

As VMs de QA são AMD, então ARM em PR só custaria tempo. Basta **forçar `PUBLISH_PLATFORM_ARM = false` quando `IS_PR`** — a lógica de plataforma já existente nos três templates passa a produzir só `--platform linux/amd64`:

```groovy
def platforms = '--platform linux/amd64'
if (publish_platform_arm) { platforms = platforms + ',linux/arm64' }
```

O ganho não é uniforme entre as stacks:

| Template | O que deixa de acontecer em PR |
|---|---|
| `golang` | O push multi-arch **e** o cross-compile `arm64` do stage Build (`buildForPlatform("arm64", "CC=aarch64-linux-gnu-gcc ...")`, linha 361) — que hoje roda mesmo em PR |
| `csharp` | O push multi-arch (`publishDockerImage`, linha 398) |
| `frontend` | O push multi-arch da aplicação e das parcels, e a criação do builder buildx (`createDockerBuildx` só cria quando ARM está ligado) |

O caminho `arm=false` **já é exercitado hoje** pelos jobs configurados sem ARM — inclusive no frontend, onde o `docker buildx build --push` roda sem builder dedicado. Não é caminho novo.

**Consequência aceita:** a imagem de PR não roda em host ARM. Como ela só existe para as VMs de QA, não há impacto.

### 1.3 Emitir o relatório

Após o push, cada job escreve **seu próprio arquivo** no bucket do MinIO interno (endpoint da API — ver Componente 0):

```text
prs/<N>/<servico>.json
```

O nome do arquivo é o **nome do repositório da imagem** (`korp.compras.core`, `sdk.flow-parcel`), não o nome do serviço no Jenkins — é ele que a role vai casar contra os composes.

Um arquivo por (PR, serviço): cada job escreve só o seu, então não há coordenação nem race entre jobs concorrentes do mesmo PR. Um job de frontend pode emitir **vários** arquivos — um do app e um por parcel (ver 1.4) — e continua sendo dono exclusivo de todos eles. A role descobre os serviços do PR listando `prs/<N>/` (`ListObjects`). Cada build **sobrescreve** o arquivo do seu serviço, então o relatório sempre aponta para o build mais recente.

Com a tag imutável (decisão 1), **o relatório deixa de ser conveniência e vira obrigatório**: o `BUILD_NUMBER` é inadivinhável, então não há como montar a tag na mão — o relatório é a única fonte da verdade.

Conteúdo proposto (serviço **container**):

```json
{
  "kind": "container",
  "pr": 123,
  "repositorio": "viasoftkorp/korp.compras",
  "branch": "DEVO-6592-ajuste-x",
  "ticket": "DEVO-6592",
  "servico": "korp.compras.core",
  "imagem": "korp/korp.compras.core",
  "tag": "2025.1.0.42-pr123",
  "versao": "2025.1.0",
  "commit": "abc1234",
  "build": 42
}
```

`repositorio`, `ticket` e `versao` não são consumidos pela role no MVP, mas tornam o relatório legível e destravam a evolução "informar a tarefa" (Achado 4) sem mudar o contrato.

**O campo `kind` é a camada de abstração que unifica o entregável.** A ferramenta da QA lê o relatório e despacha pelo `kind`: `container` → mecanismo Linux (troca de tag no compose); `delphi` → mecanismo Windows (Componente 4). O relatório de um Delphi carrega, no lugar de `imagem`/`tag`, o que o Windows precisa para buscar o binário (ex: caminho no share SMB) — formato a definir no Componente 4. Assim a QA informa uma lista única de PRs e a distinção container/Windows fica invisível para ela.

**Só o golang tem ferramenta de upload hoje — decisão: adicionar `aws`/`mc` às imagens.** O `publishS3(..., "minio-internal", ...)` existe **apenas** no `golang_jenkinsfile` (verificado: `csharp` e `frontend` não têm nenhuma referência a `publishS3`/`aws`/`mc`/`minio`). A escrita no bucket é **autenticada** (SigV4), e os jobs C# e frontend não têm com o que assinar.

**Decidido:** incluir `aws`/`mc` nas imagens de build C#/frontend e reusar a lógica do `publishS3` do golang. Vale extrair o upload como **função/estágio compartilhado** entre os três templates, não copiar três vezes. (Alternativa descartada: helper `curl`+SigV4, que evitaria mexer nas imagens.)

**Qual Dockerfile mexer — verificado (2026-07-16).** As imagens vivem no repo `iac` (GitHub `viasoftkorp/iac`), em `korp-iac/Docker/jenkins/` (uma pasta `korp-iac` **dentro** do repo `iac` — não confundir com o clone standalone `korp-iac`), versionadas por sufixo que casa com a `jnlpImageTag` do Jenkinsfile de cada serviço. Levantei a `jnlpImageTag` real em **137 Jenkinsfiles frontend** e **376 csharp**, nos branches `master`, `release/2025.1.0.x` e `release/2024.2.0.x` de logistica, vendas, producao, faturamento, projetos, sdk e compras:

| Stack | Tag viva | Dockerfile a alterar | aws hoje | Ação |
|---|---|---|---|---|
| **frontend** | `1.1.x` (117 explícitos; 0 em `1.0.x`) | `frontend/jnlp-frontend.Dockerfile.1.1.x` | ❌ | adicionar aws/mc |
| **csharp** | `1.0.5` (36) + `1.0.7` (5) | `jnlp-csharp.Dockerfile.1.0.5` **e** `.1.0.7` | comentado nas duas | descomentar aws nas duas |
| **golang** | default (nenhum fixa) | `jnlp-golang.Dockerfile` | ✅ | nenhuma |

> ⚠️ **Armadilha do obsoleto:** a `jnlp-frontend.Dockerfile.1.0.x` **tem** aws, mas é a versão **morta** — nenhum serviço usa `1.0.x`. Concluir pela presença de aws no `1.0.x` levaria a não mexer no frontend, o que estaria errado. A tag viva é `1.1.x`, que **não** tem aws.

**Pendências do csharp — comparação `1.0.5` × `1.0.7` verificada no DockerHub (2026-07-16).** Comparei os configs das imagens publicadas `korp/jnlp-csharp-build:1.0.5` e `:1.0.7` pela API pública do registry (sem baixar, lendo o histórico de layers):

- As duas são **quase idênticas** — 30 layers, 10 layers-base comuns, `ENV` igual. A **única** diferença é a versão do .NET SDK: `1.0.5` = `dotnet-sdk-10.0` (sem pin, build dez/2025); `1.0.7` = `dotnet-sdk-10.0=10.0.301` (pinada, build jul/2026, a mais nova).
- **Nenhuma das duas tem aws** — confirma que a imagem csharp precisa de aws de qualquer forma.

Mapeamento Dockerfile ↔ tag — os Dockerfiles vivem no repo **`iac`** (GitHub `viasoftkorp/iac`), em `korp-iac/Docker/jenkins/`:

| Dockerfile | .NET | Corresponde a | aws |
|---|---|---|---|
| `jnlp-csharp.Dockerfile.1.0.5` | `dotnet-sdk-10.0` (sem pin) | DockerHub `1.0.5` (36 serviços) | comentado |
| `jnlp-csharp.Dockerfile.1.0.7` | `dotnet-sdk-10.0=10.0.301` | DockerHub `1.0.7` (5 serviços) | comentado |
| `jnlp-csharp.Dockerfile` (sem sufixo) | `dotnet-sdk-6.0` | legada — **nem** 1.0.5 **nem** 1.0.7 | — |

As **duas tags vivas** (`.1.0.5` e `.1.0.7`) têm Dockerfile próprio, ambos com o bloco aws **comentado** — verificado. O `10.0.301` pinado no `.1.0.7` bate exatamente com a imagem publicada, confirmando que é a fonte dela.

**Ação csharp:** descomentar o bloco aws nas **duas** Dockerfiles (`.1.0.5` e `.1.0.7`), já que ambas as tags estão em uso (36 + 5 serviços). A sem-sufixo (dotnet 6) é legada e não entra.

### 1.4 Parcels de frontend

**Parcels são containers comuns**, e isso foi verificado no setup — `roles/DEV04/templates/composes/DEV04-compose.yml.j2:36`:

```yaml
  SDK-APP-BUILDER:
    image: "{{ docker_account }}/sdk.app-builder-parcel:{{ version_without_build }}.x{{ docker_image_suffix }}"
    container_name: "SDK.APP-BUILDER-{{ version_without_build }}"
```

Existem exatamente **3** em todo o setup: `sdk.app-builder-parcel` e `sdk.app-renderer-parcel` (role `DEV04`) e `sdk.flow-parcel` (role `FLOW01`). Todos com a forma de um serviço qualquer, na raiz de `composes/` (versionados exclusivos) — logo `project_src: {{ compose_dir_path }}/`.

**Impacto na role: nenhum.** O passo 1 casa pelo nome da imagem, e a imagem de uma parcel é só `korp/sdk.flow-parcel` — encontrada como qualquer outra, sem categoria nem `if` novo.

**Impacto no Jenkins:** o stage de parcels também está atrás de `if(!IS_PR)` (`frontend_jenkinsfile:483`) — mesmo bloqueio do Achado 1. Precisa ser liberado em PR e emitir o relatório de cada parcel (`publishParcelsDocker`), com `imagem: korp/<parcelid>-parcel`. Como a parcel é publicada pelo mesmo job do app, ela compartilha o `BUILD_NUMBER` — app e parcels de um mesmo PR saem com a mesma tag.

---

## Componente 2 — Role de aplicação de PRs

Entrada: lista de PRs (ex: `prs=123,456`).

Para cada PR, para cada serviço do relatório:

1. **Localizar o serviço.** Varrer os composes renderizados (`/etc/korp/composes/*.yml` e `/etc/korp/composes/<versao>/*.yml`) procurando a chave de serviço cujo `image:` case com `korp/<servico>:`. Isso devolve de uma vez o arquivo, o `<AppId>`, o `project_src` correto e a chave YAML do serviço — sem precisar de tabela de mapeamento.
2. **Escrever o override** em `pr-overrides/pr<N>/<AppId>-compose.yml`:

```yaml
services:
  korp-compras-core-2025-1-0:          # a chave do compose base, não o container_name
    image: "korp/korp.compras.core:2025.1.0.42-pr123"
    labels:
      korp.pr: "123"
```

A tag vem do relatório — a role não a monta. Como ela muda a cada build, o override muda junto, e o Compose recria o container sem precisar de política de pull.

3. **Subir**, reusando a invocação do setup:

```yaml
- community.docker.docker_compose_v2:
    project_src: "{{ compose_dir_path }}/"           # idêntico a compose_setup.yml
    env_files: ["{{ docker_env_file_path }}"]
    files:
      - "{{ id }}-compose.yml"                       # base renderizada
      - "pr-overrides/pr123/{{ id }}-compose.yml"    # override
```

### Por que essa invocação e não outra

O ponto delicado era subir o container sem o Compose tratar os containers dos outros apps como órfãos — `project_name` **nunca** é definido em nenhuma role, então o nome do projeto vem do basename do `project_src`, e todos os apps não versionados de `/etc/korp/composes/` compartilham o mesmo projeto. Usando o **mesmo `project_src`**, o project name é idêntico por construção — nada a descobrir ou fixar.

| Restrição | Motivo |
|---|---|
| Overrides moram **dentro** de `/etc/korp/composes/` | `files` é relativo a `project_src`; caminho externo obrigaria a mudar `project_src` e, com ele, o project name |
| A role **não pode** ligar `remove_orphans` | O default `false` é o que impede o setup de derrubar os outros apps hoje |
| Serviço versionado usa `project_src: {{ versioned_compose_dir_path }}/` | É outro projeto Compose; o override vai na pasta da versão |

---

## Componente 3 — Role de reset

1. Apagar `pr-overrides/`.
2. Subir os composes afetados só com o `files` base — o Compose compara a config desejada com a do container e recria a partir da imagem baseline.

Apagar a pasta é necessário: sem isso, um override velho de `pr123` sobrevive em disco e, na próxima aplicação daquele PR, o resultado passa a depender do que sobrou.

Reprovisionar a VM inteira como cliente final continua sendo um reset válido e equivalente — mas é mais lento e desnecessário para o caso comum.

O reset precisa cobrir **também** os serviços Delphi entregues no Windows (Componente 4) — reverter binário no Windows é diferente de recriar container, e o mecanismo depende de como o Delphi é entregue lá. Ver Componente 4.

---

## Componente 4 — Serviços Delphi (Windows)

Delphi faz parte **do mesmo entregável** (a QA não separa por tipo), mas por um mecanismo de entrega diferente, porque **Delphi não roda no Linux — roda no Windows**. É o segundo destino do despacho por `kind` (Componente 1).

### Dois tipos de Delphi = dois Jenkinsfiles a alterar

Delphi não é um bloco único: são **duas famílias**, buildadas por **Jenkinsfiles diferentes, em lugares diferentes**. Cada uma precisa da mesma alteração (publicar binário de PR + emitir relatório com `kind: delphi`) — ou seja, o "Achado 1" do Delphi acontece **duas vezes**.

| Família | O que é | Jenkinsfile |
|---|---|---|
| **Delphi do ERP** | Serviços `Korp*` do ERP. É a família registrada neste repositório em `roles/infrastructure-desktop/vars/main.yml` (`delphi_services`: `KorpCadastrosService`, `KorpFaturamentoEmissaoNotaFiscalService`, `KorpFiscalReinfService`, `KorpTributosService`, …) | Repositório A (a confirmar) |
| **Delphi do Nuvem Fiscal** | Serviços Delphi do Nuvem Fiscal. **Não** aparecem neste repositório | Repositório B (a confirmar) |

Implicações:

- São **dois** conjuntos de alterações no CI, possivelmente com convenções de build/artefato distintas — confirmar cada um separadamente.
- O relatório é o que uniformiza: ambos escrevem `kind: delphi` no mesmo bucket, e a role de QA os trata igual, independentemente de qual Jenkinsfile os produziu. A diferença fica contida no CI.
- Se as duas famílias tiverem formatos de artefato diferentes (caminho SMB, nome, layout), o campo do relatório que aponta o binário precisa ser genérico o bastante para cobrir as duas — a definir junto do formato do relatório Delphi.

### O que muda em relação ao mecanismo Linux

Nada do caminho container se aplica: não é container na VM, não há compose nem linha `image:` para sobrescrever, não há imagem DockerHub nem tag `-pr<N>`. Coerente com o setup atual — no `infrastructure-desktop`, `delphi_services` é adicionado com `skip_compose: true` (`roles/infrastructure-desktop/tasks/main.yml:36`) e os nomes (ex: `KorpCadastrosService` — `vars/main.yml:50`) **não aparecem em nenhum compose**. O que o Linux faz por eles é só registro (Consul KV, oauth); o executável vive no Windows.

### Ponto de partida — precedente que já roda em produção

Os templates v3 já publicam **binário Windows de PR**, que é quase certamente a forma do artefato Delphi:

- `golang_jenkinsfile:150` — `SHOULD_PUBLISH_WINDOWS_BINARY = PUBLISH_WINDOWS_BINARY_ON_PR`
- `golang_jenkinsfile:148` — `DEST_FOLDER_NAME = ticket_name.toUpperCase()` (pasta por ticket, ex: `DEVO-6592`)
- `golang_jenkinsfile:429` — `publishWindowsBinary(...)` envia o `.exe` por **`smbclient`** a um share interno

Ou seja, "PR → binário Windows numa pasta por ticket via SMB" já é padrão. O Delphi provavelmente reusa isso, e a role despacha o serviço `kind: delphi` para entregar/apontar esse binário na máquina Windows de QA.

### Bloqueios — precisam ser resolvidos antes de iniciar o Componente 4

Delphi entra como **fase 2 deste projeto** (não como projeto à parte). Nenhum destes bloqueia a fase 1 (container); todos bloqueiam o início do desenvolvimento do Delphi:

| # | Bloqueio | Por que bloqueia |
|---|---|---|
| B1 | **Repositórios dos dois Jenkinsfiles não identificados** (Delphi ERP e Delphi Nuvem Fiscal) | Sem saber onde estão, não há o que alterar. É o equivalente ao Achado 1, duas vezes. |
| B2 | **Convenção de build/tag/artefato de PR de cada Jenkinsfile** | Cada um pode publicar o binário de forma diferente (caminho, nome, layout); define o que a role vai buscar. |
| B3 | **Topologia Windows do ambiente de QA** — existe uma máquina Windows por ambiente? Quantas? Como se relaciona com as 5 VMs Linux? | Sem saber o alvo, não há como entregar nem orquestrar. |
| B4 | **Alcançabilidade e forma de entrega** — a máquina Windows é acessível pela orquestração (WinRM/SMB/outro)? Como o Delphi é atualizado nela **hoje** (baseline)? | Define o mecanismo de entrega e se dá para reusar o mesmo playbook. |
| B5 | **Mecanismo de reset no Windows** — reverter um binário ao baseline não é recriar container | O reset (Componente 3) precisa cobrir Windows; depende de B3/B4. |
| B6 | **Formato do relatório `kind: delphi`** — quais campos apontam o binário no lugar de `imagem`/`tag`, cobrindo as duas famílias | É o contrato entre os Jenkinsfiles Delphi e a role; sem ele o despacho não sabe o que fazer. |
| B7 | **Ferramenta de input** — confirmar que é o mesmo fluxo "informar PRs", sem uma segunda ferramenta para o Windows | É o objetivo do entregável único; se divergir, muda o desenho da role. |

O despacho por `kind` (Componente 1) já deixa o encaixe pronto: quando B1–B7 forem resolvidos, o Componente 4 se conecta sem mexer no mecanismo Linux.

---

## Achados

### Achado 1 — Hoje o PR não publica imagem (bloqueia a premissa)

| Template | Linha | Trecho |
|---|---|---|
| `csharp_jenkinsfile` | 329 | `if (! IS_PR) { ... } else { echo "skipping deploy..." }` |
| `frontend_jenkinsfile` | 394 | `if (!IS_PR) { ... } else { echo "SKIPPING DEPLOY" }` |
| `golang_jenkinsfile` | 313 | `if (! IS_PR) { ... }` |

O PR hoje só faz restore/build/tests. Liberar o publish nos três é pré-requisito de todo o resto.

### Achado 2 — O Jenkins já sabe quais serviços um PR afeta

Bloco presente nos três templates (`csharp:225`, `frontend:292`, `golang:234`):

```groovy
if (env.CHANGE_ID) {
    def base = sh(script: "git merge-base HEAD origin/${env.CHANGE_TARGET}", ...)
    def changedFiles = sh(script: "git diff --name-only ${base} HEAD", ...)
    def hasChanges = changedFiles.any { it.startsWith("${REPOSITORY_NAME}/") }
    if (!hasChanges) { echo "Nenhuma alteração em ${servicePath}. Finalizando."; return }
}
```

Um job por serviço, cada um filtrando o próprio diretório: o conjunto de jobs que efetivamente buildam num PR **já é** a lista de serviços afetados. É por isso que o relatório sai de graça — quem escreve é o job que buildou, e ele só chega lá se tinha alteração.

### Achado 3 — `-pr<N>` não identifica um PR globalmente

Número de PR é único **por repositório**: `korp.compras#123` e `korp.vendas#123` coexistem e geram a mesma tag `2025.1.0.x-pr123` — em imagens diferentes, então não há colisão no DockerHub. Mas o relatório em `prs/<N>/` **junta os dois** na mesma pasta, e aplicar `123` aplicaria serviços dos dois PRs. Risco aceito no MVP (ver decisão 16); o campo `repositorio` no relatório deixa o diagnóstico óbvio se acontecer.

### Achado 4 — O ticket já é extraído da branch

`golang_jenkinsfile:418` — `extract_ticket_name` extrai `[A-Za-z]+-[0-9]+` (ex: `DEVO-6592`) de `env.CHANGE_BRANCH`, e já é usado em produção para publicar binário Windows de PR em pasta nomeada pelo ticket (`PUBLISH_WINDOWS_BINARY_ON_PR`). Não é usado no MVP (decisão 7), mas é o caminho pronto para "informar a tarefa em vez dos PRs".

### Achado 5 — Pacotes (NuGet/npm) não são publicados em PR

`SHOULD_GENERATE_PACKAGES` só é true em `IS_HMLG`/`IS_DEV`; o `Publish Packages` do frontend roda só `if (IS_DEV || IS_PRD)`. Um PR que altera uma **lib** não gera pacote, e os serviços que a consomem seguem compilando contra a versão antiga — a imagem do PR não reflete a mudança da lib.

---

## Fora de escopo do MVP (riscos aceitos)

| Item | Consequência aceita |
|---|---|
| PR mergeado/fechado | O container segue rodando o build aplicado até o reset |
| Proliferação de tags no DockerHub | Tag imutável (decisão 1): cada push de cada PR cria uma tag permanente, e as camadas antigas deixam de ser coletadas. Sem política de retenção nesta versão |
| Novo push não chega sozinho ao ambiente | O ambiente fica pinado no build aplicado; pegar o commit novo exige re-executar a role |
| Validação de versão (PR × VM) | PR de `release/2024.2.0.x` numa VM 2025.1.0 não encontra serviço — falha ou no-op, sem mensagem dedicada |
| Colisão de nº de PR entre repositórios | Aplicar `123` pode trazer serviços de outro repositório (Achado 3) |
| Dois PRs no mesmo serviço | O último vence, em silêncio |
| Execução em cliente final | Sem trava |
| Alocação PR × VM | Dois testadores podem colidir na mesma VM |
| Schema de banco sujo após reset | Migration de PR não desfaz |
| PRs de libs/pacotes | Não testáveis pelo ambiente (Achado 5) |

---

## Pontos em aberto (implementação)

- **Como a role é acionada.** O repositório já tem playbooks auxiliares na raiz (`disk-playbook.yml`, `self_signed_renew-playbook.yml`). Seguir essa convenção — `ansible-playbook pr-playbook.yml -e "prs=123,456"` — mantém o `setup.sh` (base, usado em cliente) intocado; adicionar parâmetro ao `setup.sh` o contaminaria.
- **MinIO:** ver checklist do Componente 0.
- **Nome das roles** e dos playbooks.
