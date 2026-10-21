# Host isolado para testes do setup: mesmas versões da QA12 (2026-10):
# Ubuntu 22.04, Docker 24.0.2, Compose 2.18.1, Ansible do PPA oficial (ansible-core 2.17), community.docker 5.3.0.
FROM ubuntu:22.04
ENV DEBIAN_FRONTEND=noninteractive LC_ALL=C.UTF-8 LANG=C.UTF-8
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl gnupg software-properties-common \
      sudo git python3-pip iproute2 procps jq less vim-tiny locales acl cron logrotate openssl tzdata netcat-openbsd \
      iputils-ping rsync libpq-dev build-essential python3-dev freetds-dev \
 && install -m 0755 -d /etc/apt/keyrings && curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg \
 && echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu jammy stable" > /etc/apt/sources.list.d/docker.list \
 && apt-get update && apt-get install -y --no-install-recommends docker-ce=5:24.0.2-1~ubuntu.22.04~jammy \
      docker-ce-cli=5:24.0.2-1~ubuntu.22.04~jammy containerd.io docker-compose-plugin=2.18.1-1~ubuntu.22.04~jammy \
 && add-apt-repository --yes --update ppa:ansible/ansible && apt-get install -y ansible \
 && rm -rf /var/lib/apt/lists/*
# O que provisioning/infrastructure instalam num servidor real (bibliotecas Python usadas pelos módulos)
RUN pip3 install --no-cache-dir passlib psycopg2 'cryptography>=3.0' docker==7.0.0 python-consul requests pymssql \
 && ansible-galaxy collection install 'community.docker:==5.3.0' -p /usr/lib/python3/dist-packages/ansible_collections --force
# "deployer" = pessoa que executa o setup.sh (sudo); "korp" = usuário de serviço criado pelo provisioning
RUN useradd -m -s /bin/bash deployer && usermod -aG sudo deployer \
 && echo 'deployer ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/deployer && chmod 0440 /etc/sudoers.d/deployer \
 && useradd -r -m -s /bin/bash -g root -G sudo,www-data,docker korp
CMD ["sleep", "infinity"]
