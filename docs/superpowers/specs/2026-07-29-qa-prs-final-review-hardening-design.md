# Hardening final do ambiente de PRs

## Objetivo

Corrigir os riscos transversais encontrados na revisão final sem alterar a
interface operacional, os caminhos canônicos ou o escopo container-only do
MVP. Este documento prevalece sobre a especificação e o plano anteriores
apenas nos pontos explicitamente corrigidos abaixo.

## Identidade de ownership

- A identidade de uma PR é sempre `<repositorio>#<N>`, não apenas o número.
- Overrides novos persistem as labels `korp.pr: "<N>"` e
  `korp.repositorio: "<repositorio>"`.
- O caminho permanece
  `<project_src>/pr-overrides/pr<N>/<compose_file>`; o repositório não entra
  no nome do diretório.
- Refresh sem conflito exige igualdade de `pr_key`, portanto PRs de
  repositórios diferentes com o mesmo número conflitam normalmente.
- Override legado sem `korp.repositorio` recebe ownership desconhecido
  `#<N>` e conflita conservadoramente com qualquer PR repo-qualified. O
  operador escolhe `replace`, `keep` ou aborta conforme a política.
- `replace` grava o novo metadata repo-qualified; `keep` preserva o owner
  atual.

## Preflight seguro do reset

Antes de remover qualquer raiz `pr-overrides`, a role de reset deve:

1. descobrir e ler todos os arquivos regulares das duas raízes;
2. converter cada conteúdo YAML e falhar em conteúdo inválido;
3. exigir caminho direto e canônico
   `<project_src>/pr-overrides/pr<N>/<compose_file>`;
4. validar `services` não vazio, configurações de serviço, `image`,
   `korp.pr`, correspondência do número com o caminho e, quando presente,
   `korp.repositorio`;
5. derivar execuções únicas por `project_src + compose_file`;
6. exigir que cada compose base exista e seja arquivo regular;
7. validar cada compose base com o mesmo `project_src`, env file e arquivo
   usados no reset, por `community.docker.docker_compose_v2` em
   `check_mode: true`.

Qualquer falha encerra o play antes da primeira deleção. Somente depois de
todo o preflight as duas raízes são removidas e os composes base afetados são
reaplicados.

## Plugin compartilhado

- O plugin deixa de ser privado da role `qa_pr_apply` e passa a existir
  somente em `filter_plugins/qa_pr_filters.py`, na raiz do projeto.
- Os playbooks `pr-playbook.yml` e `pr-reset-playbook.yml`, executados pela
  raiz do projeto, carregam a mesma implementação de filtros.
- Não haverá cópia, wrapper ou import entre roles; isso evita divergência
  entre validação de aplicação e de reset.
- Os testes Python passam a importar o plugin pelo caminho compartilhado.
- O aceite inclui uma execução Ansible focada que prove que
  `qa_pr_reset` resolve `qa_pr_index_active_overrides` sem carregar
  `qa_pr_apply`.

## MinIO e documentação

- A listagem aceita somente chaves diretas no formato
  `prs/<repositorio>/<N>/<servico>.json`; descendentes como
  `prs/<repositorio>/<N>/subdir/x.json` são rejeitados.
- A chave usada na URL do objeto passa pelo filtro `urlencode`, preservando
  a chave exata e codificando caracteres inseguros.
- O guia operacional declara explicitamente que os playbooks não possuem
  trava automática contra execução em ambiente de cliente final.
- Efeitos de inicialização de serviços continuam documentados separadamente.

## Escopo deliberadamente preservado

- Apenas `kind=container`.
- MinIO anônimo, TLS e endpoint/bucket já definidos.
- Políticas `ask`, `replace`, `keep` e `fail`.
- Nenhuma integração com `setup.sh`, `main.yml` ou Delphi.
- Nenhum `remove_orphans`.
- A exceção global existente de `var-naming[no-role-prefix]` permanece como
  observação não bloqueante desta entrega; substituí-la por dezenas de
  suppressions inline não faz parte deste hardening de segurança.

## Testes e aceite

- Regressão para duas PRs de repositórios diferentes com o mesmo número.
- Regressão para refresh repo-qualified e override legado conservador.
- Regressão para persistência e leitura de `korp.repositorio`.
- Regressão para chave MinIO direta versus chave aninhada.
- Contratos YAML comprovando parse/validação e Compose check mode antes da
  deleção.
- Regressões para caminho/conteúdo de override inválidos e compose base não
  regular.
- Suíte unitária completa, dois syntax-checks e lint literal devem sair zero.

