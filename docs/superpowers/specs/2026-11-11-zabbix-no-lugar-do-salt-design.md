# Zabbix no lugar do salt para as operações do AWX (DEVO-8135)

## Intenção

Chamado de segurança: "SALT — deixar o salt desligado e somente ligar ele quando utilizar".
Hoje o salt-master precisa ficar ligado 24 h porque o AWX depende dele para operar os servidores
onpremise (logs, atualização de serviço, lista de serviços, carga ELT, banco do Viasoft.Email e
inventário). O objetivo é tirar o AWX do salt, usando o agente Zabbix que já roda em todos os
clientes, para que o salt-master fique desligado e só seja ligado para operações pontuais
(rollouts grandes).

Ganho de segurança além de desligar o salt: no salt, quem manda o comando tem root em todos os
clientes (`cmd.run`). No desenho novo, o servidor do cliente só aceita um script nosso
(`korp-ops`), com um catálogo fechado de operações e argumentos validados.

## Objetivos

- Os workflows do AWX que hoje usam salt passam a funcionar pelo Zabbix, com o mesmo survey e o
  mesmo resultado para quem usa.
- O cliente executa apenas `sudo -n /usr/local/sbin/korp-ops <operação> <args>`; nenhum shell
  livre, nenhuma chave nossa no servidor do cliente.
- Operações longas (atualização, ELT, uploads) não dependem do tempo limite do Zabbix: rodam em
  segundo plano no cliente e o AWX acompanha o status.
- O merge dos PRs não muda nada em produção sozinho: o AWX continua no salt até a troca ser ligada
  (`onpremise_backend`), e o agente só aceita comandos depois de atualizado pelo setup.

## Não objetivos

- Remover o salt dos clientes (continua instalado para uso pontual).
- Trocar o FRP / acesso SQL onpremise (só usa o salt para extrair o tenant da string do survey,
  sem falar com o salt-master).
- Monitoramento: templates, triggers e dashboards do Zabbix não mudam.

## Anti-objetivos (seria falha mesmo funcionando)

- Qualquer conta do Zabbix conseguir rodar comando arbitrário nos clientes.
- O AWX precisar de Super admin no Zabbix.
- Workflows quebrarem para clientes ainda não migrados durante o rollout.

## Situação levantada (11/11/2026)

- Servidor Zabbix 7.0.5 (container no monitoring). Comandos remotos em agente ativo existem
  desde o 7.0: o comando vai junto com a configuração de checks ativos e o agente devolve o
  resultado; o tempo limite do script precisa ser maior que o intervalo de atualização do agente
  (RefreshActiveChecks, padrão 5 s na 7.0).
- Clientes: Ubuntu 22.04 e agente 2 em 6.x; nenhum com comandos remotos liberados.
- O agente já usa PSK compartilhada (`services_secrets.Others.Zabbix.PSK`), e o autorregistro
  aceita só PSK.
- No Zabbix, quem tem papel Super admin pode criar/editar scripts globais e executá-los em
  qualquer host; por isso a revisão de contas é pré-requisito (o levantamento detalhado fica fora
  do repositório).
- O setup roda `zabbix_setup.yml` nas tags `provisioning`, `default-setup` e `update`.

## Validado em laboratório (Zabbix 7.0.5 em Docker, cliente Ubuntu 22.04)

- O `zabbix_setup.yml` novo atualiza um cliente com a configuração de hoje (agente 6.2.9) para o
  7.0.32; o host reconecta com a PSK compartilhada, sem intervenção no servidor.
- `script.execute` com `{MANUALINPUT}` executa o `korp-ops` no agente ativo e devolve a saída.
  O servidor recusa entradas que não casam com a regex do script.
- Script executado no agente: o servidor só aceita `timeout` de 30 s, e o que vale de fato é o
  `Timeout` do servidor. Com o padrão (3 s), quase toda chamada termina em "timeout while
  retrieving result". Com `Timeout=30` no servidor, comandos de até ~25 s funcionam (o agente
  leva até ~5 s para buscar o comando). O `Timeout` do agente não interfere.
  **Pré-requisito de produção: `Timeout=30` no zabbix-server.**
- O `AllowKey` precisa casar com os dois parâmetros da chave (`system.run[<comando>,*]`).
  O filtro do agente sozinho não impede que um script editado no servidor rode outros comandos
  como o usuário `zabbix`; os `DenyKey` de metacaracteres reduzem isso, mas não são uma barreira
  completa. A proteção real é: validação da entrada no script, contas do Zabbix endurecidas,
  usuário `zabbix` sem privilégios (fora do grupo docker) e sudo só para o `korp-ops`.
- Jobs: atualização de 40 s acompanhada por `status` até o fim; segundo job igual recusado;
  ELT, `upload-logs` e `upload-email-db` com upload real no `korp-onpremise-logs`.

## Validado em produção (12/11/2026)

- Zabbix: papel "AWX API", grupo "AWX", usuário `awx` com token e script `korp-ops` criados; `Timeout=30` no
  zabbix-server (`ZBX_TIMEOUT=30` no compose do monitoring). Pelo token do AWX, o `korp-ops version` num agente 6.2
  agora espera os 30 s e falha ("timeout while retrieving result"), então o `auto` leva ~30 s a mais por workflow
  em cliente ainda não atualizado antes de seguir pelo salt.
- qa-dev: a primeira atualização instalou o `zabbix-release` 7.0, mas o agente ficou no 6.2.9 sem erro. O
  `zabbix.list` é conffile do `zabbix-release`, e o `add-apt-repository` que o `setup.sh` roda para o PPA do Ansible
  reescreve todos os `.list` (o comentário `#deb` vira `# deb`); com o padrão do módulo apt (`force-confdef,force-confold`)
  o dpkg mantém o repositório 6.2 e grava o novo em `zabbix.list.dpkg-dist`. Reproduzido no cliente do laboratório
  (mesmo md5 da qa-dev depois do `add-apt-repository`). Correção: `dpkg_options: force-confnew` na instalação do
  `zabbix-release` e falha do setup se o agente instalado não for o 7.0. Na qa-dev, que já tinha o `zabbix-release`
  7.0, o `zabbix.list` foi trocado à mão pelo `.dpkg-dist`; depois disso o setup instalou o 7.0.32.
- Com o token do AWX: `version`, `services` e `logs` na qa-dev pelo Zabbix; entrada com `;` recusada pelo servidor;
  `select_backend.yaml` em `auto` escolhe o Zabbix na qa-dev e o salt na QA1 (agente 6.2).
- AWX de produção (projeto temporário com a branch do awx #240): serviços, logs no terminal, atualização e logs por
  e-mail na qa-dev pelo Zabbix. A atualização falhou primeiro com "Exec format error": o `containers_update.sh` do
  setup não tem shebang; o `korp-ops` passou a rodar os scripts com `/bin/bash`, como o salt.
- QA1 (13/11/2026, 2025.1, agente 6.2.9 com o `zabbix.list` alterado segundo o `dpkg --verify`): a atualização só do
  agente com esta branch instalou o 7.0.32 de primeira (`force-confnew`, o antigo ficou em `zabbix.list.dpkg-old`);
  a configuração só ganhou as linhas `AllowKey`/`DenyKey`; `version` e `services` pela API e o fluxo de serviços pelo
  AWX funcionaram. O container do e-mail lá é `Viasoft.Email-2025.1.0` (nome que o setup cria), e o salt e o
  `korp-ops` paravam só `Viasoft.Email`; o `korp-ops` passou a parar e religar os dois formatos de nome.

## Desenho

### Cliente (KorpSetupLinux)

1. Agente Zabbix 2 na 7.0 (`zabbix-release_7.0-2+ubuntu22.04`, `zabbix-agent2` em `latest`).
2. `/usr/local/sbin/korp-ops` (Python 3, só biblioteca padrão, root:root 0755) com o catálogo:

   | Operação | O que faz | Modo |
   |---|---|---|
   | `version` | versão do korp-ops | direto |
   | `logs <container> [linhas]` | `docker logs --tail` (padrão 200, máx. 2000) | direto |
   | `services` | `nome;commit;versão` de cada container (igual ao `get_names_and_labels.sh`) | direto |
   | `labels <container>` | `commit versão` do container | direto |
   | `restart <container>` | `docker restart` | job |
   | `update <container>` | `/etc/korp/scripts/containers_update.sh <container>` | job |
   | `elt <environmentId>` | `/etc/korp/scripts/carga_inicial_elt.sh environmentId=<id>` | job |
   | `upload-logs <container> <upload_url> <upload_token> <arquivo_b2>` | zipa os logs json do container (incl. rotacionados) e envia ao B2 (`arquivo_b2` em `temp/`) | job |
   | `upload-email-db <tenant> <upload_url> <upload_token> <arquivo_b2>` | para o container do Viasoft.Email (`Viasoft.Email` ou `Viasoft.Email-<versão>`, como o setup cria), zipa o `.db` com senha gerada no cliente, religa sempre, envia ao B2 (`arquivo_b2` em `dbs/`, como no salt desde o awx #242); a senha volta no resultado | job |
   | `salt-minion-restart` | reinicia o salt-minion (resgate para o salt sob demanda) | direto |
   | `status <job_id>` | estado do job (`running`/`ok`/`error`), código, final do log e resultado | direto |

   - Job: `systemd-run --unit korp-ops-<id> --collect` (ou `setsid` sem systemd), estado em
     `/var/lib/korp-ops/jobs/<id>/`; um job por operação+alvo de cada vez; limpeza após 7 dias.
   - Validação de todos os argumentos por regex antes de qualquer execução; subprocessos sem shell.
   - Upload só para `https://pod-*.backblaze.com/b2api/...` (não serve para mandar arquivo para
     outro lugar); o token vai no cabeçalho pela biblioteca do Python, fora da lista de processos.
3. sudoers: `zabbix ALL=(root) NOPASSWD: /usr/local/sbin/korp-ops` (validado com `visudo -c`).
4. Agente (`/etc/zabbix/zabbix_agent2.d/korp-ops.conf`, de `files/configs/zabbix-korp-ops.conf`): `DenyKey` para
   metacaracteres de shell antes de `AllowKey=system.run[sudo -n /usr/local/sbin/korp-ops *,*]` e
   `DenyKey=system.run[*]` no fim. Fica fora do `korp-default.conf` porque os setups das releases sem este PR
   reescrevem o `korp-default.conf`; o template dele não muda.
5. O cadastro no salt deixa de ser fatal no setup (com o master desligado o setup não pode parar).

### Servidor Zabbix

- Um script global `korp-ops`: tipo Script, executa no agente, escopo "ação manual de host",
  comando `sudo -n /usr/local/sbin/korp-ops {MANUALINPUT}`, entrada manual tipo texto com regex
  `^[a-z-]+( [A-Za-z0-9._:/=+-]+)*$`, restrito a um grupo de usuários do AWX e ao grupo de hosts
  dos clientes. Criado/atualizado de forma idempotente por uma task do AWX.
- Usuário de API do AWX com papel próprio (não Super admin): API em lista de permissões
  (`host.get`, `script.get`, `script.execute`), leitura no grupo de hosts dos clientes, token.
- Pré-requisito de segurança antes de ligar: revisar contas e papéis do Zabbix (Super admin só
  para a equipe, com MFA; contas de serviço com o mínimo necessário).
- `Timeout=30` no zabbix-server (ver laboratório). Efeito colateral: verificações passivas e SNMP
  de hosts que não respondem passam a esperar até 30 s antes de desistir.
- Usuário `zabbix` sem acesso ao docker nos clientes onde os comandos remotos forem ligados.

### AWX

Implementado no repositório awx (branch `DEVO-8135-zabbix-korp-ops`):

- `roles/utils/tasks/zabbix_api/`: chamada genérica (JSON-RPC com token Bearer), execução do `korp-ops` no host
  `zabbix-agent_<tenant>` com a mesma validação do script do Zabbix, acompanhamento de job (status a cada 10 s até o
  limite da operação) e escolha do backend.
- `onpremise_backend` (`salt` padrão, `zabbix`, `auto`): definido nas variáveis do inventário `Korp Inventory` ou como
  variável extra (não no grupo `onpremise`, cujas variáveis o mapeamento regrava). Em `auto` o AWX testa
  `korp-ops version` no host e usa o Zabbix se responder, senão o salt — permite rollout gradual.
- `create_link.yaml` dividido em preparar upload (B2) e gerar link, usados pelos dois backends.
- Inventário (`map_onpremise_tenants`): no Zabbix, clientes = hosts `zabbix-agent_*` visíveis ao AWX com agente ativo
  disponível; em `auto`, une com os minions do salt e segue só com o Zabbix se a salt-api estiver desligada.
- Script `korp-ops` no Zabbix criado/atualizado pela tag `zabbix_korp_ops_script` (só roda quando pedida), com o token de
  um Super admin informado na execução (`zabbix_admin_token`); esse token não fica no Vault.

Validado no laboratório com um usuário de API restrito (papel tipo User, sem acesso à interface, API em lista de
permissões `host.get`, `script.get`, `script.execute` e a ação "Execute scripts"; grupo de usuários sem acesso ao
frontend, com leitura em `Korp Clients`): todos os workflows pelo Zabbix (serviços, logs no terminal, atualização com
job de 40 s, ELT, logs e banco do Viasoft.Email por e-mail com upload real no B2 e senha conferida), modo `auto` nos
dois sentidos e mapeamento de clientes (portal e API do AWX simulados). Qualquer outra chamada desse token é recusada ("No permissions to call").
Atenção: esse usuário também pode executar outros scripts de ação manual liberados para todos os grupos de usuários
(por padrão Ping e Traceroute, que rodam no servidor); os que rodam no agente precisam ficar restritos a outros grupos.

## Rollout

1. Merge dos PRs (nada muda em produção).
2. Hardening de contas do Zabbix (pendente); criar papel, grupo, usuário e token do AWX (feito); gravar `ZabbixApi` (`Address`, `Token`)
   no Vault (pendente); criar o script `korp-ops` com a tag `zabbix_korp_ops_script` do AWX (feito).
3. Atualizar o agente nos clientes, começando pelo qa-dev (feito em 12/11/2026) e pela QA1 (feito em 13/11/2026).
   Em massa, pelo salt enquanto ele ainda está ligado, com `scripts/migracao-zabbix/migrar-agente.sh <commit>`
   (`salt -G 'tenant:<id>' cmd.script salt://migrar-agente.sh args='<commit>'`), em lotes: não precisa do token do
   cliente, mantém `korp-default.conf` e PSK, instala o mesmo que o `zabbix_setup.yml` acrescentou e faz backup em
   `/root/backup-zabbix-korp-ops-<data>`. Validado no laboratório (13/11/2026): cliente 6.2.9 com o `zabbix.list`
   alterado passou para o 7.0.32 em 21 s e respondeu ao `korp-ops` pelo servidor; repetir no mesmo cliente funciona,
   tira as regras antigas do `korp-default.conf` (qa-dev e QA1) e corrige o `zabbix.list` 6.2 com o `zabbix-release`
   7.0 já instalado (caso da qa-dev).
4. `onpremise_backend: auto` nas variáveis do inventário `Korp Inventory`; acompanhar uma semana.
5. `onpremise_backend: zabbix`; tirar os monitores de salt do Uptime Kuma e a conta `uptime.kuma`;
   desligar salt-master e salt-api; ligar só quando necessário, com desligamento automático.

## Decisões minhas (sem confirmação do usuário)

- PSK compartilhada atual mantida (já em uso); PSK por host fica como melhoria futura.
- Um único script Zabbix genérico em vez de um por operação; a validação fina fica no `korp-ops`.
- Python 3 para o `korp-ops` (já presente nos clientes, usado pelo setup).
- Nome da branch: `DEVO-8135-zabbix-korp-ops` nos dois repositórios.
