# Salt sob demanda (DEVO-8135)

O salt-master fica desligado e só é ligado para operações pontuais. O AWX opera os clientes onpremise pelo Zabbix
(script `korp-ops` no agente 7.0), sem depender do salt. Desenho e validações:
`docs/superpowers/specs/2026-11-11-zabbix-no-lugar-do-salt-design.md`.

Levantamento de 16/11/2026: job cache do salt das últimas 24 h, `external_auth` do master e AWX.

## Onde está e quem usa

- Servidor `monitoring` (`ssh monitoring`, Ubuntu 22.04, salt 3007.7, sem salt-minion local).
- Serviços:
  - `salt-master`, nas portas 4505 e 4506.
  - `salt-api` (rest_cherrypy na porta 8112), publicado pelo container `nginx` em `salt-api-monitoring.korp.com.br`, com lista
    de IPs em `/opt/dados-docker/nginx/conf.d/salt-api.conf`.

| Quem usa | Para quê | Com o salt desligado |
|---|---|---|
| AWX (usuário `awx` na salt-api) | Workflows onpremise: 157 atualização de serviço, 163 logs, 224 banco do e-mail, 58 carga de dados, 156 mapeamento de serviços; agendamento "Mapeamento de Tenants" | Com `onpremise_backend: zabbix`, tudo vai pelo Zabbix. Cliente sem `korp-ops` fica sem operação pelo AWX. |
| Viasoft.Vault.Manager no OKE (usuário `vault_manager`) | Cadastro do minion no setup do cliente (`/vault/manager/server-deploy/salt/register` e `/test`): põe o tenant no autosign e faz `test.ping` | Com o KorpSetupLinux #635, o setup avisa e segue. O minion do cliente fica sem cadastro (ver "Chaves pendentes"). |
| Uptime Kuma (usuário `uptime.kuma`) | `test.ping` em todos os minions a cada ~5 min | Alerta de fora do ar se não for pausado |
| Pessoas (`sudo salt ...` no monitoring; usuário `juliano.viana` na salt-api) | Consultas e comandos pontuais | Ligar antes de usar |
| cron do root: `0 8 * * 6 systemctl restart salt-master` | Restart semanal (sábado, 08:00 UTC) | **Tirar**: o `restart` religa o master desligado |

## Pré-requisitos (uma vez, antes do primeiro desligamento)

1. **Merges** (feitos em 19/11/2026): awx #240 e KorpSetupLinux #635 (`master`), #640 (`release/2025.1.0.x`) e #641
   (`release/2024.2.0.x`).
   - Sem o #240, o AWX não tem o caminho pelo Zabbix.
   - Sem os outros, o setup do cliente, inclusive atualização, para no cadastro do minion: com a salt-api desligada, o
     Vault Manager responde 500 em `/vault/manager/server-deploy/salt/register`.
   - `release/2024.1.0.x` e `release/2023.4.0.x` não receberam a mudança. Um setup nelas com o salt desligado para no
     cadastro: ligar o salt para esse setup.
2. **Zabbix e Vault.** Já estão prontos:
   - segredo `ZabbixApi` no Vault, gravado em 12/11/2026;
   - script `korp-ops` no Zabbix;
   - `Timeout=30` no zabbix-server;
   - usuário de API `awx`.
3. **AWX.** Em AWX → Inventories → `Korp Inventory` (id 2) → Variables, a variável `onpremise_backend` escolhe o caminho
   (`zabbix` desde 19/11/2026).
   - `salt` (ou sem a variável): tudo pelo salt.
   - `auto`: o Zabbix quando o `korp-ops` responde e o salt nos demais clientes.
   - `zabbix`: tudo pelo Zabbix. O "Mapeamento de Tenants" (a cada 4 h) monta a lista dos surveys com os hosts
     disponíveis no Zabbix.
   - Os workflows não pedem variáveis no lançamento, então a troca é sempre no inventário.
4. **Avisar a equipe** que usa o salt pela linha de comando.

## Desligar

1. **Uptime Kuma:** pausar o monitor que usa a salt-api (usuário `uptime.kuma`). Pausar em vez de apagar, para reativar se
   voltar atrás.
2. **AWX:** em `Korp Inventory` → Variables, trocar para `onpremise_backend: zabbix`.
3. **No monitoring:**
   ```bash
   sudo crontab -e                                   # comentar a linha "systemctl restart salt-master"
   # minions que respondem agora, para comparar quando o salt voltar
   sudo salt-run --out=yaml manage.up | sudo tee /root/salt-minions-up-$(date +%F).yaml > /dev/null
   sudo systemctl disable --now salt-api salt-master
   systemctl is-active salt-master salt-api          # inactive / inactive
   sudo ss -ltnp | grep -E ':(4505|4506|8112) '      # sem saída
   ```
4. **Conferir:** rodar "Mapeamento de serviços ativos em cliente onpremise" num cliente migrado (lista abaixo). O log
   deve mostrar "operação pelo zabbix".

**Enquanto estiver desligado:**
- Os minions dos clientes tentam reconectar sozinhos, sem efeito no cliente.
- O setup de cliente novo avisa que não cadastrou o minion e segue.
- O AWX opera só os clientes com `korp-ops`.

## Ligar quando precisar

```bash
ssh monitoring
sudo systemctl start salt-master salt-api
# desligamento automático (ajuste o tempo)
sudo systemd-run --unit=salt-desligamento --on-active=4h /bin/systemctl stop salt-api salt-master
systemctl list-timers salt-desligamento.timer
```

- **Prorrogar:** `sudo systemctl stop salt-desligamento.timer` e rodar o `systemd-run` de novo com o novo tempo.
- **Desligar antes do fim:** `sudo systemctl stop salt-api salt-master salt-desligamento.timer`.
- **Se o `systemd-run` disser que a unidade já existe:** `sudo systemctl stop salt-desligamento.timer` e
  `sudo systemctl reset-failed salt-desligamento.service`.

O `start` não reativa o serviço no boot. Se o monitoring reiniciar, o salt continua desligado.

### Minions que não voltaram

O esperado é que os minions voltem sozinhos, mesmo depois de dias com o master desligado:
- o minion tenta reconectar sem limite de tentativas;
- quando o master volta, ele tem uma chave AES nova, e o minion se autentica de novo na primeira mensagem (o mesmo que
  acontece no restart).

Para conferir, alguns minutos depois de ligar:

```bash
sudo salt-run manage.down        # minions aceitos que não responderam (inclui os que já estavam fora antes)
# só os que respondiam antes do desligamento (arquivo do passo "Desligar")
sudo salt-run --out=yaml manage.up | sudo diff /root/salt-minions-up-<data>.yaml - | grep '^<'
```

Para os que não voltarem:
- **Cliente migrado (tem `korp-ops`):** reiniciar o salt-minion pelo Zabbix, com
  `korp_ops <tenant> salt-minion-restart` (ver "Operar um cliente pelo Zabbix").
- **Cliente sem `korp-ops`:** alguém com acesso ao servidor roda `sudo systemctl restart salt-minion`.

### Usar

**Linha de comando**, sempre com o tenant completo ou com um glob:

```bash
sudo salt -C 'G@tenant:<tenant_id>' test.ping
sudo salt -C 'G@tenant:<tenant_id>' cmd.run 'docker ps --format "{{.Names}}" | head' shell=/bin/bash
```

**AWX num cliente sem `korp-ops`:** trocar temporariamente para `onpremise_backend: auto` no `Korp Inventory`. O AWX
passa a usar o Zabbix nos migrados e o salt nos demais. Ao terminar, voltar para `zabbix`.

### Chaves pendentes

Setups feitos com o salt desligado não cadastram o minion, e a chave dele aparece como pendente quando o master liga:

```bash
sudo salt-key -l pre
```

Para aceitar, há dois caminhos:
- rodar o setup de novo com o salt ligado (o Vault Manager cadastra);
- depois de confirmar qual máquina é, rodar `sudo salt-key -a <tenant_id>`.

Não aceitar chave de um id que já está aceito: é uma segunda máquina com o mesmo tenant (caso DEDINI e BrasilPack). As
recusadas ficam em `/etc/salt/pki/master/minions_denied/`.

## Voltar atrás (salt ligado 24 h)

```bash
sudo systemctl enable --now salt-master salt-api
sudo crontab -e                                   # descomentar o restart semanal
```

Depois, reativar o monitor no Uptime Kuma e trocar para `onpremise_backend: salt` no `Korp Inventory` (ou apagar a
variável).

## Operar um cliente pelo Zabbix (korp-ops)

O token é o do usuário de API do AWX (`ZabbixApi.Token` no Vault). Ele só pode `host.get`, `script.get` e
`script.execute` nos hosts de `Korp Clients`. Rodar no monitoring (endereço interno, como no Vault):

```bash
export ZBX_URL=http://127.0.0.1:8080/api_jsonrpc.php
read -rs ZBX_TOKEN && export ZBX_TOKEN                # cola o token sem ir para o histórico

korp_ops() {  # korp_ops <tenant_id> <operação> [argumentos...]
  python3 - "$@" <<'PY'
import json, os, sys, urllib.request
def call(method, params):
    body = json.dumps({"jsonrpc": "2.0", "method": method, "params": params, "id": 1}).encode()
    req = urllib.request.Request(os.environ["ZBX_URL"], body, {"Content-Type": "application/json-rpc",
                                                               "Authorization": "Bearer " + os.environ["ZBX_TOKEN"]})
    out = json.load(urllib.request.urlopen(req, timeout=60))
    if "error" in out:
        sys.exit(f"erro do Zabbix: {out['error'].get('data') or out['error']}")
    return out["result"]
tenant, manualinput = sys.argv[1], " ".join(sys.argv[2:])
hosts = call("host.get", {"output": ["hostid"], "filter": {"host": [f"zabbix-agent_{tenant}"]}})
if not hosts:
    sys.exit(f"host zabbix-agent_{tenant} não encontrado no Zabbix")
script = call("script.get", {"output": ["scriptid"], "filter": {"name": "korp-ops"}})
print(call("script.execute", {"scriptid": script[0]["scriptid"], "hostid": hosts[0]["hostid"],
                              "manualinput": manualinput})["value"])
PY
}

korp_ops <tenant_id> version                 # {"ok": true, "op": "version", "version": "1"}
korp_ops <tenant_id> salt-minion-restart     # {"ok": true, ..., "salt_minion": "active"}
korp_ops <tenant_id> services
korp_ops <tenant_id> logs <container> 200
```

Testado em 16/11/2026 com `version` na qa-dev. A chamada leva até ~5 s, o tempo do agente buscar o comando.

Se der "timeout while retrieving result", o cliente não tem o agente 7.0 com `korp-ops` ou está fora do ar.

## Situação dos clientes (16/11/2026)

### Com `korp-ops` (operam pelo Zabbix)

Agente 7.0.32, migrados em 12 e 13/11/2026: 47 clientes, mais qa-dev, QA1 e QA2.

ALLBRANDS, AllParts, ARAMEPAR, ATI_BRASIL, Azeheb, BASE_PADRAO, BR7, CCM, CONVICTA, CPE_DO_BRASIL, DENTAL-MED-SUL,
DENTAL_PRIME, GEHFER, INPRELL, KONDUSTEC, KSS, LAM, LAMIEX, LATAL, Leclair, Marini, MARTIACO, MBOSCHMETALMECANICA, MECAT,
METALCANA, METALESP, METALKRAFT, METALURGICA_REIS, MINERACAO_ITAPERUCU, NOVA_ITA_EIRELIEPP, NOVATECHICOTES, PHD,
PRESSOTTO, RADDEC, SELECTAS, SISMATEC_IND_COMEQUIPAMENTOS_HOSPITALARES, STALKER_ENGENHARIA, STATOMAT, TAMPAFLEX,
TECTRONICS_SISTEMAS_ELETRONICOS, THERMOGEL, TORBER, Towers_Parts, TREFIX, Truck_Center, VEUTE_DISTRIBUIDORACOMERCIO,
VIASOFT.

GEHFER está sem dados no Zabbix desde a noite de 15/11, e o salt também não responde: o servidor parece fora do ar.

### Sem `korp-ops` (precisam do salt para o AWX)

| Cliente | Situação |
|---|---|
| AMAZING, INOBRAM, ORIGINAL, PALMASOLA, BUBAMASTER | Agente 6.2.9 funcionando no Zabbix; salt-minion não responde. Precisa de alguém no servidor (`systemctl restart salt-minion`) e então `scripts/migracao-zabbix/migrar-agente.sh` pelo salt. |
| DEDINI, BrasilPack | Duas máquinas no mesmo host do Zabbix (DEDINI: srvl071 e srvl072; BrasilPack: korpservices e VM004 da Azure). Deixado para depois. |
| ISBBRASIL, KABEL | Salt responde, mas o nosso `zabbix-agent2` está parado e roda o agente clássico do próprio cliente (na ISBBRASIL envia para `zabbix.columbiati.com`). Subir o nosso disputa a porta 10050; combinar com o cliente. |
| CERAMICA_STRUFALDI, CompLaser, RPD, SMART_CENTER, TECNOFILME, FIBRACEM | Sem dados no Zabbix e salt sem resposta (a FIBRACEM nunca teve a chave aceita). Servidor desligado ou cliente inativo. |

### Servidores internos

**Com `korp-ops`:** QA3, QA4, QA6, QA7, QA8, QA9, QA10, QA11 e QA12, migrados por SSH em 16/11/2026 (agente 7.0.32,
conferidos pelo Zabbix). No Zabbix, a QA7 aparece como "QA" e a QA8 e a QA9 aparecem sem nome amigável
(`zabbix-agent_8349ad41…` e `zabbix-agent_21ee58dd…`).

- **qa4-linux:** o `Hostname` do `korp-default.conf` estava com o tenant da QA12 (454caa6a), por isso dividia o host
  QA_12. O `inventory.yml` dela tem o tenant 4dfef57e. O `Hostname` foi alinhado com o inventário, que é o que o setup
  geraria, e ela voltou para o host "QA4". Backup em `/root/backup-zabbix-hostname-20261116-200720`.
- **QA12:** o Docker está parado e desabilitado desde 11/11/2026, por isso `korp-ops services` responde com erro.

**Sem `korp-ops`:**

- **QA5:** agente 6.2.9. Ficou de fora porque lá só valem checagens de leitura ou setups versionados; precisa de ok
  explícito.
- **Korp-SUPORTE-PRD:** agente 6.2.4, fora do salt (chave pendente e recusada). Só por SSH, com senha.
- **Sem dados no Zabbix e salt sem resposta:** Korp-QA-PRD, QA_AUXILIAR, QA_AUXILIAR_ATI, QA_HMLG, QA_HMLG_ANTERIOR e
  Ambiente_Ansible_DEV.
