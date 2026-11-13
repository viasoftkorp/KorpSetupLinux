#!/bin/bash
# Migra o agente Zabbix de um cliente onpremise já instalado para o 7.0 com o korp-ops (DEVO-8135), sem rodar o setup.
#
# Instala o mesmo que roles/provisioning/tasks/zabbix_setup.yml acrescentou: zabbix-release 7.0, zabbix-agent2 7.0,
# /usr/local/sbin/korp-ops, /etc/sudoers.d/korp-ops e /etc/zabbix/zabbix_agent2.d/korp-ops.conf, e a PSK legível só por
# root e pelo agente. Não usa o token do cliente: mantém o korp-default.conf e a PSK como estão. Faz backup em
# /root/backup-zabbix-korp-ops-<data>.
#
# Uso (root): migrar-agente.sh <ref do KorpSetupLinux, de preferência o commit>
# Pelo salt:  salt -G 'tenant:<id>' cmd.script salt://migrar-agente.sh args='<commit>' timeout=600
set -euo pipefail
export LC_ALL=C.UTF-8 DEBIAN_FRONTEND=noninteractive

REF=${1:-}
[[ $REF =~ ^[A-Za-z0-9._/-]+$ ]] || { echo "uso: migrar-agente.sh <ref do KorpSetupLinux>"; exit 2; }
RAW="https://raw.githubusercontent.com/viasoftkorp/KorpSetupLinux/$REF"
ZBX_LIST=/etc/apt/sources.list.d/zabbix.list
CONF_DIR=/etc/zabbix/zabbix_agent2.d
SUDOERS_LINE='zabbix ALL=(root) NOPASSWD: /usr/local/sbin/korp-ops'
APT=(apt-get -y -qq -o DPkg::Lock::Timeout=300)

fail() { echo "ERRO: $*"; exit 1; }

[[ $EUID -eq 0 ]] || fail "rode como root"
[[ -f $CONF_DIR/korp-default.conf ]] || fail "$CONF_DIR/korp-default.conf não existe (cliente sem o setup da Korp?)"
# shellcheck disable=SC1091
. /etc/os-release
[[ $ID == ubuntu ]] || fail "só Ubuntu (encontrado: $ID $VERSION_ID)"
echo "antes: $(zabbix_agent2 -V | head -1)"

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
backup=/root/backup-zabbix-korp-ops-$(date +%Y%m%d-%H%M%S)
mkdir -p "$backup"
cp -a /etc/zabbix "$backup/etc-zabbix"
cp -a "$ZBX_LIST" "$backup/" 2>/dev/null || true
dpkg -l | grep -i zabbix > "$backup/dpkg-zabbix.txt" || true
for f in /usr/local/sbin/korp-ops /etc/sudoers.d/korp-ops; do
  [[ -e $f ]] && cp -a "$f" "$backup/"
done
echo "backup: $backup"

# Os arquivos vêm do mesmo commit do setup
curl -fsSL --retry 3 -o "$work/korp-ops" "$RAW/roles/provisioning/files/scripts/korp-ops"
curl -fsSL --retry 3 -o "$work/korp-ops.conf" "$RAW/roles/provisioning/files/configs/zabbix-korp-ops.conf"
python3 -c 'import ast, sys; ast.parse(open(sys.argv[1]).read())' "$work/korp-ops" || fail "korp-ops baixado não é Python válido"
grep -qxF 'AllowKey=system.run[sudo -n /usr/local/sbin/korp-ops *,*]' "$work/korp-ops.conf" || fail "korp-ops.conf baixado inválido"

# Repositório 7.0. O zabbix.list é conffile do zabbix-release e o add-apt-repository do setup.sh o reescreve: só com
# force-confnew o dpkg troca o repositório (ver zabbix_setup.yml). O apt-get não faz downgrade de um zabbix-release mais novo.
deb="zabbix-release_7.0-2+ubuntu${VERSION_ID}_all.deb"
curl -fsSL --retry 3 -o "$work/$deb" "https://repo.zabbix.com/zabbix/7.0/ubuntu/pool/main/z/zabbix-release/${deb/+/%2B}"
"${APT[@]}" -o Dpkg::Options::=--force-confnew install "$work/$deb"
if ! grep -q '^deb .*/zabbix/7\.0/' "$ZBX_LIST"; then
  # zabbix-release 7.0 já instalado com o zabbix.list antigo (o novo ficou em .dpkg-dist): reinstala o arquivo do pacote
  rm -f "$ZBX_LIST"
  "${APT[@]}" -o Dpkg::Options::=--force-confmiss install --reinstall "$work/$deb"
fi
grep -q '^deb .*/zabbix/7\.0/' "$ZBX_LIST" || fail "$ZBX_LIST não aponta para o 7.0"

# Atualiza só o repositório do Zabbix (outros repositórios com problema não interrompem a migração)
"${APT[@]}" update -o Dir::Etc::sourcelist="$ZBX_LIST" -o Dir::Etc::sourceparts=- -o APT::Get::List-Cleanup=0
"${APT[@]}" -o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold install zabbix-agent2
version=$(zabbix_agent2 -V | head -1)
[[ $version =~ \(Zabbix\)\ 7\.0\. ]] || fail "zabbix-agent2 instalado não é o 7.0: $version"

install -o root -g root -m 0755 "$work/korp-ops" /usr/local/sbin/korp-ops
printf '%s\n' "$SUDOERS_LINE" > "$work/sudoers"
visudo -cf "$work/sudoers" > /dev/null || fail "sudoers inválido"
install -o root -g root -m 0440 "$work/sudoers" /etc/sudoers.d/korp-ops
install -o root -g root -m 0644 "$work/korp-ops.conf" /etc/zabbix/zabbix_agent2.d/korp-ops.conf
# Clientes migrados antes do arquivo próprio (qa-dev e QA1) têm as mesmas regras no fim do korp-default.conf
if grep -qF 'AllowKey=system.run[sudo -n /usr/local/sbin/korp-ops' "$CONF_DIR/korp-default.conf"; then
  grep -vxFf "$CONF_DIR/korp-ops.conf" "$CONF_DIR/korp-default.conf" > "$work/korp-default.conf" || true
  cat "$work/korp-default.conf" > "$CONF_DIR/korp-default.conf"
fi
# Mesma permissão do setup para a PSK (era 0444 nos setups antigos)
psk=$(sed -n 's/^TLSPSKFile=//p' "$CONF_DIR/korp-default.conf" | tail -1)
if [[ -n $psk && -f $psk ]]; then
  stat -c '%U:%G %a %n' "$psk" > "$backup/psk-permissao.txt"
  chown root:zabbix "$psk"
  chmod 0440 "$psk"
fi
zabbix_agent2 -T -c /etc/zabbix/zabbix_agent2.conf > /dev/null || fail "configuração do agente inválida (backup em $backup)"

if [[ -d /run/systemd/system ]]; then
  systemctl restart zabbix-agent2
else
  service zabbix-agent2 restart
fi
for _ in $(seq 30); do
  pgrep -x zabbix_agent2 > /dev/null && break
  sleep 1
done
pgrep -x zabbix_agent2 > /dev/null || fail "zabbix-agent2 não voltou (backup em $backup)"

result=$(sudo -u zabbix sudo -n /usr/local/sbin/korp-ops version)
[[ $result == *'"ok": true'* ]] || fail "korp-ops não respondeu pelo usuário zabbix: $result"
echo "depois: $version; korp-ops: $result"
