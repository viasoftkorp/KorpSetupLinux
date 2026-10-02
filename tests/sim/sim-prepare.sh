#!/bin/bash
# Executado DENTRO do host isolado, como root: deixa o host no estado de um servidor já provisionado
# (o que roles/provisioning faria), antes do primeiro setup.sh.
set -euo pipefail
mkdir -p /etc/korp && chown korp:root /etc/korp
# CA do gateway/portal simulados (nos servidores reais: certificado do nginx local)
cp /simwork/tls/ca.crt /usr/local/share/ca-certificates/korpsim-ca.crt && update-ca-certificates >/dev/null
docker load -i /simwork/korpsim-fake.tar >/dev/null
docker network inspect servicos >/dev/null 2>&1 || docker network create --subnet 172.18.0.0/16 --ip-range 172.18.0.0/17 servicos >/dev/null
# o git clone do setup.sh é servido pelo espelho local (sem acesso ao GitHub)
sudo -u deployer git config --global url."/simwork/mirror.git".insteadOf "https://github.com/viasoftkorp/KorpSetupLinux.git"
git config --system --add safe.directory '*'
cp /sim/setup_config.ini /home/deployer/setup_config.ini && chown deployer /home/deployer/setup_config.ini
mkdir -p /etc/korp/configs /etc/korp/certs && chown korp:root /etc/korp/configs /etc/korp/certs
# provisioning cria dados-docker/apprise com o módulo file (pais com o mesmo dono/modo)
mkdir -p /etc/korp/dados-docker/apprise && chown www-data:www-data /etc/korp/dados-docker /etc/korp/dados-docker/apprise \
  && chmod 770 /etc/korp/dados-docker /etc/korp/dados-docker/apprise
echo prepared
