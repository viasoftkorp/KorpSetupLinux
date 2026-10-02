#!/bin/bash
# Orquestra o ambiente isolado de testes do setup (tests/sim/README.md). Nunca acessa servidores reais.
#
#   simctl.sh build                    imagens (host isolado, imagem falsa), certificados e coleção com stub
#   simctl.sh infra-up                 rede, SQL Server e gateway simulado (compartilhados)
#   simctl.sh mirror REPO_DIR          espelho git servido como https://github.com/viasoftkorp/KorpSetupLinux.git
#   simctl.sh host-up NAME             host Ubuntu 22.04 privilegiado com dockerd próprio (/etc/korp em volume próprio, como o disco dedicado dos servidores)
#   simctl.sh seed NAME                estado de servidor provisionado + inventário criptografado
#   simctl.sh pull-public NAME         baixa as imagens públicas usadas pelos composes
#   simctl.sh version VER              versão devolvida pelo token simulado (ex.: 2025.1.0)
#   SIM_REF=<ref> simctl.sh setup NAME LOG args...   executa o setup.sh do <ref> (log com tempos em .work/runs)
#   simctl.sh snapshot NAME SNAP | restore NAME SNAP  salva/restaura host + SQL Server
#   simctl.sh dump NAME OUT.json       estado final (Consul, SQL, Postgres, arquivos, containers)
#   simctl.sh compare INITIAL A B [--allow REGEX ...]
#   simctl.sh timing LOG               resumo de tempos
#   simctl.sh host-down NAME
set -euo pipefail
H=$(cd "$(dirname "$0")" && pwd)
W=$H/.work
NET=korpsim-net
SA_PW_FILE=$W/.sa_pw
IMG=korpsim-host:latest
HOSTS='--add-host korp-api.local:172.31.250.11 --add-host korp-cdn.local:172.31.250.11 --add-host korp.local:172.31.250.11 --add-host api.korp.local:172.31.250.11'
SKIP="-e ANSIBLE_SKIP_TAGS=provisioning -e ANSIBLE_COLLECTIONS_PATH=/simwork/collections:/usr/share/ansible/collections"
mkdir -p $W/runs $W/dumps
cmd=$1; shift
run_host() {  # NAME IMAGE
  docker run -d --name $1 --hostname $1 --privileged --cpus=${SIM_CPUS:-4} --memory=${SIM_MEM:-16g} --network $NET $HOSTS \
    -v $1-docker:/var/lib/docker -v $1-korp:/etc/korp -v $H:/sim:ro -v $W:/simwork --entrypoint /sim/sim-entry $2 sleep infinity >/dev/null
  for i in $(seq 1 60); do docker exec $1 docker info >/dev/null 2>&1 && break; sleep 1; done
}
wait_mssql() {
  for i in $(seq 1 90); do docker exec korpsim-mssql /opt/mssql-tools18/bin/sqlcmd -C -S localhost -U sa -P "$(cat $SA_PW_FILE)" -Q "select 1" >/dev/null 2>&1 && return; sleep 2; done
}
case $cmd in
build)
  docker build -t $IMG $H
  docker build -t korpsim-fake:latest $H/fake-image && docker save korpsim-fake:latest -o $W/korpsim-fake.tar
  rm -rf $W/collections && mkdir -p $W/collections/ansible_collections/community
  docker run --rm -v $W/collections:/out $IMG bash -c "cp -a /usr/lib/python3/dist-packages/ansible_collections/community/docker /out/ansible_collections/community/ && chown -R $(id -u):$(id -g) /out"
  cp $H/stubs/docker_login.py $W/collections/ansible_collections/community/docker/plugins/modules/docker_login.py
  chmod -R a+rX $W/collections
  mkdir -p $W/tls && cd $W/tls && if [ ! -f ca.crt ]; then
    openssl req -x509 -newkey rsa:2048 -nodes -keyout ca.key -out ca.crt -days 365 -subj "/CN=korpsim-ca" 2>/dev/null
    openssl req -newkey rsa:2048 -nodes -keyout gw.key -out gw.csr -subj "/CN=korp-api.local" 2>/dev/null
    printf "subjectAltName=DNS:korp-api.local,DNS:korp-cdn.local,DNS:korp.local,DNS:api.korp.local\n" > ext
    openssl x509 -req -in gw.csr -CA ca.crt -CAkey ca.key -CAcreateserial -out gw.crt -days 365 -extfile ext 2>/dev/null
  fi; echo built ;;
infra-up)
  docker network inspect $NET >/dev/null 2>&1 || docker network create --subnet 172.31.250.0/24 $NET >/dev/null
  [ -f $SA_PW_FILE ] || (umask 077; echo "Sim$(openssl rand -hex 8)!a" > $SA_PW_FILE)
  if ! docker ps --format '{{.Names}}' | grep -qx korpsim-mssql; then
    docker rm -f korpsim-mssql >/dev/null 2>&1 || true
    docker run -d --name korpsim-mssql --network $NET --ip 172.31.250.10 -e ACCEPT_EULA=Y -e MSSQL_SA_PASSWORD="$(cat $SA_PW_FILE)" \
      -v korpsim-mssql-data:/var/opt/mssql --memory 3g mcr.microsoft.com/mssql/server:2022-latest >/dev/null
    wait_mssql
  fi
  docker exec -i korpsim-mssql /opt/mssql-tools18/bin/sqlcmd -C -S localhost -U sa -P "$(cat $SA_PW_FILE)" -b < $H/sql/auth_schema.sql >/dev/null
  if ! docker ps --format '{{.Names}}' | grep -qx korpsim-gw; then
    docker rm -f korpsim-gw >/dev/null 2>&1 || true
    docker run -d --name korpsim-gw --network $NET --ip 172.31.250.11 -v $H/gateway:/gw:ro -v $W/tls:/tls:ro \
      -e SIM_CERT=/tls/gw.crt -e SIM_KEY=/tls/gw.key -e SIM_LICENSED="${SIM_LICENSED:-}" python:3.12-slim python3 -u /gw/mock_gateway.py >/dev/null
  fi; echo infra-up ;;
version)
  docker exec korpsim-gw python3 -c "import urllib.request;print(urllib.request.urlopen('http://127.0.0.1:8080/__sim/version/$1').read().decode())" ;;
mirror)
  rm -rf $W/mirror.git; git clone -q --mirror "$1" $W/mirror.git; echo mirrored ;;
host-up)
  docker rm -f $1 >/dev/null 2>&1 || true; docker volume rm -f $1-docker $1-korp >/dev/null 2>&1 || true
  docker volume create $1-docker >/dev/null; docker volume create $1-korp >/dev/null; run_host $1 $IMG; echo host-up ;;
seed)
  N=$1
  docker exec $N /sim/sim-prepare.sh
  docker exec -e SA_PW="$(cat $SA_PW_FILE)" $N bash -c '
    set -e; mkdir -p /etc/korp/ansible/logs /etc/ansible
    [ -f /etc/korp/ansible/.vault_key ] || { tr -dc A-Za-z0-9 </dev/urandom | head -c 15 > /etc/korp/ansible/.vault_key; chmod 444 /etc/korp/ansible/.vault_key; }
    KP=$(tr -dc A-Za-z0-9 </dev/urandom | head -c 16)
    cat > /etc/korp/ansible/inventory.yml <<EOI
all:
  children:
    nodes:
      hosts:
        localhost:
          app_server: {address: 10.0.0.10}
          mssql: {address: 172.31.250.10, default_user: sa, default_password: "$SA_PW", korp_user: korp.services, korp_password: "$KP"}
          testing_mssql: {address: 172.31.250.10, default_user: sa, default_password: "$SA_PW", korp_user: korp.services, korp_password: "$KP"}
          certs:
            custom: {certificate: false, has_pass_file: false}
            self_signed: {certificate: true, passphrase: korp}
            certbot_automated: {certificate: false, email: ""}
            pfx_passphrase: korp
          dns: {api: korp-api.local, cdn: korp-cdn.local, frontend: korp.local, api_gateway: api.korp.local}
EOI
    printf "[defaults]\ninventory = /etc/korp/ansible/inventory.yml\n" > /etc/ansible/ansible.cfg
    ansible-vault encrypt /etc/korp/ansible/inventory.yml --vault-id /etc/korp/ansible/.vault_key >/dev/null
    chmod 644 /etc/korp/ansible/inventory.yml'
  echo seeded ;;
pull-public)
  N=$1; docker exec -e SIM_VERSIONS="${SIM_VERSIONS:-2024.2.0,2025.1.0}" $N bash -c 'rm -rf /tmp/simrepo && mkdir -p /tmp/simrepo
    for r in $(git -C /simwork/mirror.git for-each-ref --format="%(refname:short)" refs/heads/); do
      mkdir -p "/tmp/simrepo/$r" && git -C /simwork/mirror.git archive "$r" roles | tar -x -C "/tmp/simrepo/$r"; done
    python3 /sim/sim_tag_images.py public /tmp/simrepo "$SIM_VERSIONS" | while read i; do docker pull -q "$i" >/dev/null && echo "pulled $i" || echo "FAILED $i"; done' ;;
setup)
  N=$1; LOG=$2; shift 2
  docker exec -u deployer -w /home/deployer -e SIM_REF="${SIM_REF}" $N bash -c 'git -C /simwork/mirror.git show "${SIM_REF}:setup.sh" > /tmp/setup.sh'
  docker exec -e SIM_REF="${SIM_REF}" $N bash -c 'rm -rf /tmp/simrepo && mkdir -p /tmp/simrepo && git -C /simwork/mirror.git archive "${SIM_REF}" roles | tar -x -C /tmp/simrepo'
  docker exec -e SIM_VERSIONS="${SIM_VERSIONS:-2024.2.0,2025.1.0}" $N bash -c 'python3 /sim/sim_tag_images.py templates /tmp/simrepo "$SIM_VERSIONS"'
  docker exec -d $N bash -c 'pkill -f "[s]im_tag_images.py watch"; exec python3 /sim/sim_tag_images.py watch'
  set +e
  docker exec -u deployer -w /home/deployer -e ANSIBLE_FORCE_COLOR=0 $SKIP ${SIM_ENV:-} $N \
    python3 /sim/pty_run.py /simwork/runs/$LOG -- bash /tmp/setup.sh gateway_url=http://korpsim-gw:8080 "$@"
  rc=$?; docker exec $N pkill -f "[s]im_tag_images.py watch" || true; echo "setup rc=$rc"; exit $rc ;;
snapshot)
  N=$1; S=$2
  docker exec $N bash -c 'pkill -f "[s]im_tag_images" || true; pkill dockerd; for i in $(seq 1 60); do pgrep dockerd >/dev/null || break; sleep 1; done'
  docker commit $N korpsim-snap:$S >/dev/null
  docker volume rm -f korpsim-snapvol-$S >/dev/null 2>&1 || true; docker volume create korpsim-snapvol-$S >/dev/null
  docker run --rm -v $N-docker:/from -v korpsim-snapvol-$S:/to busybox:1.36-musl sh -c 'cp -a /from/. /to/'
  docker volume rm -f korpsim-snapkorp-$S >/dev/null 2>&1 || true; docker volume create korpsim-snapkorp-$S >/dev/null
  docker run --rm -v $N-korp:/from -v korpsim-snapkorp-$S:/to busybox:1.36-musl sh -c 'cp -a /from/. /to/'
  docker stop korpsim-mssql >/dev/null; docker volume rm -f korpsim-mssqlsnap-$S >/dev/null 2>&1 || true; docker volume create korpsim-mssqlsnap-$S >/dev/null
  docker run --rm -v korpsim-mssql-data:/from -v korpsim-mssqlsnap-$S:/to busybox:1.36-musl sh -c 'cp -a /from/. /to/'
  docker start korpsim-mssql >/dev/null; wait_mssql
  docker exec $N bash -c '(dockerd > /var/log/dockerd.log 2>&1 &); for i in $(seq 1 60); do docker info >/dev/null 2>&1 && break; sleep 1; done'
  echo snapshot $S ;;
restore)
  N=$1; S=$2
  docker rm -f $N >/dev/null 2>&1 || true
  docker volume rm -f $N-docker >/dev/null 2>&1 || true; docker volume create $N-docker >/dev/null
  docker run --rm -v korpsim-snapvol-$S:/from -v $N-docker:/to busybox:1.36-musl sh -c 'cp -a /from/. /to/'
  docker volume rm -f $N-korp >/dev/null 2>&1 || true; docker volume create $N-korp >/dev/null
  docker run --rm -v korpsim-snapkorp-$S:/from -v $N-korp:/to busybox:1.36-musl sh -c 'cp -a /from/. /to/'
  docker stop korpsim-mssql >/dev/null
  docker run --rm -v korpsim-mssqlsnap-$S:/from -v korpsim-mssql-data:/to busybox:1.36-musl sh -c 'rm -rf /to/* && cp -a /from/. /to/'
  docker start korpsim-mssql >/dev/null; wait_mssql
  run_host $N korpsim-snap:$S; echo restored $S ;;
dump)
  N=$1; OUT=$2; docker cp $SA_PW_FILE $N:/tmp/.sa_pw >/dev/null
  docker exec $N python3 /sim/state_dump.py /tmp/state.json --mssql-host 172.31.250.10 --mssql-password-file /tmp/.sa_pw
  docker exec $N rm -f /tmp/.sa_pw; docker cp $N:/tmp/state.json "$OUT" >/dev/null; echo "dump $OUT" ;;
compare)
  python3 $H/compare_dumps.py "$@" ;;
timing)
  python3 $H/timing_report.py "$@" ;;
host-down)
  docker rm -f $1 >/dev/null 2>&1 || true; docker volume rm -f $1-docker $1-korp >/dev/null 2>&1 || true; echo down ;;
*)
  sed -n '2,17p' "$0"; exit 1 ;;
esac
