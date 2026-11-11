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
   | `upload-logs <container> <upload_url> <upload_token> <arquivo_b2>` | zipa os logs json do container (incl. rotacionados) e envia ao B2 | job |
   | `upload-email-db <upload_url> <upload_token> <arquivo_b2>` | para o Viasoft.Email, zipa o `.db` com senha gerada no cliente, religa sempre, envia ao B2; a senha volta no resultado | job |
   | `salt-minion-restart` | reinicia o salt-minion (resgate para o salt sob demanda) | direto |
   | `status <job_id>` | estado do job (`running`/`ok`/`error`), código, final do log e resultado | direto |

   - Job: `systemd-run --unit korp-ops-<id> --collect` (ou `setsid` sem systemd), estado em
     `/var/lib/korp-ops/jobs/<id>/`; um job por operação+alvo de cada vez; limpeza após 7 dias.
   - Validação de todos os argumentos por regex antes de qualquer execução; subprocessos sem shell.
   - Upload só para `https://pod-*.backblaze.com/b2api/...` (não serve para mandar arquivo para
     outro lugar); o token vai no cabeçalho pela biblioteca do Python, fora da lista de processos.
3. sudoers: `zabbix ALL=(root) NOPASSWD: /usr/local/sbin/korp-ops` (validado com `visudo -c`).
4. Agente (`korp-default.conf`): `DenyKey` para metacaracteres de shell antes de
   `AllowKey=system.run[sudo -n /usr/local/sbin/korp-ops *,*]` e `DenyKey=system.run[*]` no fim.
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

- `roles/utils/tasks/zabbix_api/`: chamada genérica (token Bearer), resolução de host
  (`zabbix-agent_<tenant>`), execução do `korp-ops` e acompanhamento de job (status a cada 10 s
  até o limite da operação).
- `onpremise_backend` (`salt` padrão, `zabbix`, `auto`): em `auto` o AWX testa `korp-ops version`
  no host e usa o Zabbix se responder, senão o salt — permite rollout gradual.
- `create_link.yaml` dividido em preparar upload (B2) e gerar link, para servir aos dois backends.
- Inventário (`map_onpremise_tenants`): no Zabbix, clientes = hosts `zabbix-agent_*` do grupo dos
  clientes com agente ativo disponível; em `auto`, une com os minions do salt se o master
  estiver ligado.

## Rollout

1. Merge dos PRs (nada muda em produção).
2. Hardening de contas do Zabbix; criar usuário/papel/token do AWX e o script `korp-ops`
   (task do AWX); gravar `ZabbixApi` no Vault.
3. Atualizar o agente nos clientes (setup com tag `update`, ou rollout em massa pelo salt enquanto
   ele ainda está ligado), começando pelo qa-dev.
4. `onpremise_backend: auto` no AWX; acompanhar uma semana.
5. `onpremise_backend: zabbix`; tirar os monitores de salt do Uptime Kuma e a conta `uptime.kuma`;
   desligar salt-master e salt-api; ligar só quando necessário, com desligamento automático.

## Decisões minhas (sem confirmação do usuário)

- PSK compartilhada atual mantida (já em uso); PSK por host fica como melhoria futura.
- Um único script Zabbix genérico em vez de um por operação; a validação fina fica no `korp-ops`.
- Python 3 para o `korp-ops` (já presente nos clientes, usado pelo setup).
- Nome da branch: `DEVO-8135-zabbix-korp-ops` nos dois repositórios.
