# Ambiente de qualidade com imagens de PRs

Este fluxo aplica, em um servidor de qualidade já configurado, as imagens publicadas pelos pipelines de PR. Ele é operacional e separado do setup normal: `setup.sh` e `main.yml` não executam estes playbooks.

## Pré-requisitos

- execute no checkout do KorpSetupLinux usado pelo servidor;
- garanta que o inventário e as variáveis usuais, inclusive `linux_korp`, estejam disponíveis;
- garanta acesso ao Docker e aos diretórios de compose configurados;
- valide que o host resolve e confia no certificado de `https://minio-interno-api.korp.com.br`.
- valide acesso ao registry e à API de `https://harbor.korp.com.br`.

> Atenção: `qa_pr_minio_api` deve apontar para o host da API do MinIO, não para a interface web/console. O playbook faz leituras HTTPS anônimas nesse endpoint e valida o certificado TLS.

## Fluxo recomendado para o QA

Instale o atalho uma vez, a partir do checkout do KorpSetupLinux:

```bash
./qa-pr install
qa-pr doctor
```

No uso diário:

```bash
# Aplicar ou atualizar uma imagem de PR
qa-pr apply https://github.com/viasoftkorp/repositorio/pull/123

# Conferir overrides e contêineres ativos
qa-pr status

# Remover todos os PRs e voltar aos composes base
qa-pr reset
```

Em um conflito, o modo padrão pergunta se deve `replace`, `keep` ou `abort`.
Também é possível decidir previamente com `--replace`, `--keep` ou `--fail`.
Os logs ficam em `~/.local/state/korp-qa-pr`.

## Aplicar PRs

Informe URLs completas de PRs da organização `viasoftkorp`. Para uma lista CSV:

```bash
ansible-playbook pr-playbook.yml -e "prs=https://github.com/viasoftkorp/repositorio-a/pull/123,https://github.com/viasoftkorp/repositorio-b/pull/456"
```

Para uma lista JSON:

```bash
ansible-playbook pr-playbook.yml -e '{"prs":["https://github.com/viasoftkorp/repositorio-a/pull/123","https://github.com/viasoftkorp/repositorio-b/pull/456"]}'
```

O playbook consulta os relatórios JSON no bucket `qa-prs`, localiza o serviço pelo repositório da imagem nos composes base e cria um override somente para o serviço alvo. Para cada relatório, consulta primeiro a tag em `harbor.korp.com.br/qa-prs/<serviço>`. Se a API do Harbor responder `404`, usa como fallback a imagem `korp/<serviço>` informada no relatório, preservando builds anteriores à adoção do Harbor. Erros de acesso ao Harbor não acionam fallback: a execução falha para não mascarar indisponibilidade do registry.

O contêiner aplicado recebe as labels `korp.pr` com o número e `korp.repositorio` com o repositório; juntas, elas formam o ownership `<repositorio>#<N>` exibido no preflight.

### Conflitos

Há conflito quando outro ownership já controla a mesma identidade de serviço: diretório do projeto, arquivo de compose e chave do serviço. PRs de repositórios diferentes com o mesmo número conflitam. Não há conflito ao reaplicar o mesmo `<repositorio>#<N>`, nem quando PRs afetam serviços diferentes, ainda que estejam no mesmo compose.

A política padrão é `ask`:

```bash
ansible-playbook pr-playbook.yml -e "prs=https://github.com/viasoftkorp/repositorio-a/pull/123"
```

Para cada conflito, responda `replace`, `keep` ou `abort`. Uma resposta vazia ou inválida equivale a `abort`.

Em automações, defina a política sem interação:

```bash
ansible-playbook pr-playbook.yml -e "prs=https://github.com/viasoftkorp/repositorio-a/pull/123" -e "pr_conflict_policy=replace"
```

As políticas são:

- `ask`: pergunta como resolver cada conflito antes de alterar o ambiente;
- `replace`: remove o serviço do override do PR atual e aplica o serviço do PR solicitado;
- `keep`: mantém o proprietário atual e ignora somente o alvo conflitante; alvos sem conflito continuam;
- `fail`: falha se existir qualquer conflito.

Todo o preflight termina antes da primeira gravação ou execução de compose. Portanto, `abort` em `ask` e conflito com `fail` encerram a aplicação inteira sem mutar overrides ou contêineres. Sem conflito, o alvo é aplicado normalmente em qualquer política válida.

### Atualizar após um novo push

O ambiente não acompanha novos commits automaticamente. Depois que o pipeline publicar o relatório e a imagem de um novo push, execute novamente o mesmo comando com o mesmo link. Como o número do PR não mudou, isso é um refresh, não um conflito, e o serviço é reaplicado com a imagem indicada pelo relatório mais recente.

## Resetar o ambiente

```bash
ansible-playbook pr-reset-playbook.yml
```

O reset descobre os composes afetados, confirma que cada compose base ainda existe, remove as duas raízes de `pr-overrides` e reaplica integralmente cada compose base afetado. Isso remove todos os overrides de PR; não há reset seletivo por PR. Se não houver overrides, não há compose para reaplicar.

## Riscos aceitos no MVP

- Divergência de versão: o fluxo não garante que a versão declarada pelo relatório do PR corresponda à versão base instalada no ambiente.
- Não há trava automática contra executar estes playbooks privilegiados em ambiente de cliente final; confirme o host antes da execução.
- A aplicação pode inicializar serviços e executar seus efeitos de startup.
- Schema sujo: migrações, dados e outras alterações persistidas fora do compose não são revertidas pela troca de imagem nem pelo reset.
- Sem refresh automático: cada novo push exige aguardar a publicação e reaplicar manualmente o PR.
