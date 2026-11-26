# Salt sob demanda

O `salt-master` fica desligado e só é ligado quando alguém precisa dele. No dia a dia, o AWX opera os servidores
onpremise pelo Zabbix, com o script `korp-ops` (agente Zabbix 7.0).

Os comandos abaixo rodam no servidor do salt-master.

## Ligar

```bash
sudo systemctl start salt-master salt-api      # a salt-api só é necessária para quem usa a API
# desligamento automático (ajuste o tempo)
sudo systemd-run --unit=salt-desligamento --on-active=2h /bin/systemctl stop salt-api salt-master
systemctl list-timers salt-desligamento.timer
```

- **Prorrogar:** `sudo systemctl stop salt-desligamento.timer` e rodar o `systemd-run` de novo com o novo tempo.
- **Se o `systemd-run` disser que a unidade já existe:** `sudo systemctl stop salt-desligamento.timer` e
  `sudo systemctl reset-failed salt-desligamento.service`.
- Os minions reconectam sozinhos em poucos minutos. `sudo salt-run manage.down` lista os que ainda não responderam.

## Usar

Sempre com o tenant completo:

```bash
sudo salt -C 'G@tenant:<tenant_id>' test.ping
sudo salt -C 'G@tenant:<tenant_id>' cmd.run 'docker ps --format "{{.Names}}"' shell=/bin/bash
```

Para o AWX usar o salt enquanto ele estiver ligado, troque `onpremise_backend` para `auto` nas variáveis do inventário: o
AWX passa a usar o salt nos servidores sem `korp-ops`. Ao terminar, volte para `zabbix`.

## Desligar

```bash
sudo systemctl stop salt-api salt-master salt-desligamento.timer
systemctl is-active salt-master salt-api       # inactive / inactive
```

Os serviços ficam desabilitados no boot. Não use `systemctl enable` nem `systemctl restart salt-master` (nem em cron):
os dois deixam o salt ligado de vez.

## Minion que não responde

Pelo Zabbix, nos servidores com `korp-ops`:

1. Em **Monitoramento → Hosts**, filtre pelo host (`zabbix-agent_<nome>`).
2. Clique no nome do host e, em **Scripts**, escolha **korp-ops**.
3. Troque a operação `version` por `salt-minion-restart` e execute. A resposta esperada é
   `{"ok": true, "op": "salt-minion-restart", "salt_minion": "active"}`.
4. Uns 15 s depois, confira com `sudo salt <tenant_id> test.ping`.

Se o Zabbix responder `timeout while retrieving result for remote command`, o servidor não tem o agente 7.0 com
`korp-ops`. Nesse caso, alguém com acesso ao servidor roda `sudo systemctl restart salt-minion`.

## Chaves pendentes

Um setup feito com o salt desligado não cadastra o minion. A chave dele aparece como pendente quando o master liga:

```bash
sudo salt-key -l pre
```

Para aceitar, rode o setup de novo com o salt ligado ou, depois de confirmar qual máquina é, `sudo salt-key -a <tenant_id>`.
Não aceite a chave de um id que já está aceito: é outra máquina com o mesmo tenant.

## Operações do `korp-ops`

Pelo menu **Scripts → korp-ops** do host no Zabbix, ou pelo AWX:

| Operação | O que faz |
|---|---|
| `version` | Confere se o `korp-ops` responde |
| `services` | Containers rodando, com versão e commit |
| `logs <container> [linhas]` | Últimas linhas do log (padrão 200) |
| `labels <container>` | Versão e commit de um container |
| `salt-minion-restart` | Reinicia o salt-minion |
| `restart <container>` | Reinicia um container, em segundo plano |
| `update <container>` | Atualiza um container para a imagem mais nova, em segundo plano |
| `status <job_id>` | Andamento de `restart` e `update` |

Peça no máximo 200 linhas de log: uma resposta grande (cerca de 280 KB) derruba o zabbix-server 7.0.5.
