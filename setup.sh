#!/bin/bash

create_random_string() {
  local l=15
  [ -n "$1" ] && l=$1
  [ -n "$2" ] && l=$(shuf --random-source=/dev/urandom -i $1-$2 -n 1)
  tr -dc A-Za-z0-9 < /dev/urandom | head -c ${l} | xargs
}

# Leitura de parâmetros passados para o script
# parametros esperados:
#   token="<token>"             - OBRIGATÓRIO
#   disk="<sdx>"                - OBRIGATÓRIO durante instalação caso haja mais de um disco livre
#   branch_name="<branch_name>" - OPCIONAL, caso não sejá passado, receberá 'master'
#   gateway_url="<gateway_url>" - OPCIONAL, caso não sejá passado, receberá "https://gateway.korp.com.br"
#   custom_tags="<tag1,tag2>"   - OPCIONAL, caso não sejá passada, as tags "default-setup,install" serão usadas
#   apps="<apps1,apps2>"        - OPCIONAL
#     caso 'custom_tags' seja ['install', 'install-only', 'default-setup'], será utilizado para definir os aplicativos que serão instalados
#     caso 'custom_tags' seja ['remove-apps'], será utilizado para definir os aplicativos que serão desinstalados
#   remove_versioned=<bool>     - OBRIGATÓRIO caso 'custom_tags' seja ['remove-apps'] - padrão, false
#   remove_unversioned=<bool>   - OBRIGATÓRIO caso 'custom_tags' seja ['remove-apps'] - padrão, false
#   removed_version="2022.1.0"  - OBRIGATÓRIO caso 'custom_tags' seja ['remove-apps', 'uninstall-version']
#   skip_salt_test=<bool> - OPCIONAL, padrão false
#   should_update_rabbitmq=<bool> - OPCIONAL, padrão false
#
##### variaveis salvas no inventário:
#   db_suffix="<db_suffix>" - OPCIONAL, sufixo utilizado na criação dos bancos e nas ConnectionStrings do Consul KV
## Certificados
#   cert_type="<cert_type>"                         - OPCIONAL - pode ter os valores: [selfsigned, custom, certbot]
#   custom_cert_has_pass=false                      - OBRIGATÓRIO caso cert_type==custom - caso true, o diretório 'custom_cert_path' deve conter o arquivo cert.pass
#   custom_cert_path="<certs_path>"                 - OBRIGATÓRIO caso cert_type==custom - Diretório contendo os arquivos cert.crt, cert.key, cert.pass
#   certbot_email="<certbot_email>"   - OBRIGATÓRIO caso cert_type==certbot - Email em que o LetsEncrypt irá enviar notificações
## DNSs
#   dns_api="<dns.domain>"      - OPCIONAL
#   dns_cdn="<dns.domain>"      - OPCIONAL
#   dns_frontend="<dns.domain>" - OPCIONAL
## HTTPS
#   https_port="<port>" - OPCIONAL - porta usada para conectar ao portal local por https, padrão '443'
## Proxy reverso
#   external_reverse_proxy=<bool> - OPCIONAL - Habilita o proxy reverso para ser feito fora do servidor de Linux
## Porta Postgres
# expose_postgres=<bool> - OPCIONAL - Expõe banco para fora da rede docker (5432:5432) - padrão false

apps=""; docker_account=""; ansible_tags="";
gateway_url="https://gateway.korp.com.br"
branch_name="master";
remove_versioned=false; remove_unversioned=false; removed_version="";
docker_image_suffix="";
db_suffix="";
dns_api=""; dns_frontend=""; dns_cdn="";
https_port="";
cert_type=""; custom_cert_has_pass=""; custom_cert_path=""; certbot_email="";
skip_salt_test=false;

ini_file_path="./setup_config.ini"


if test -f $ini_file_path;
then
    apps=$(sed -nr "/^\[OPTIONS\]/ { :l /^apps[ ]*=/ { s/.*=[ ]*//; p; q;}; n; b l;}" $ini_file_path)
    docker_account=$(sed -nr "/^\[OPTIONS\]/ { :l /^docker_account[ ]*=/ { s/.*=[ ]*//; p; q;}; n; b l;}" $ini_file_path)  
    docker_image_suffix=$(sed -nr "/^\[OPTIONS\]/ { :l /^docker_image_suffix[ ]*=/ { s/.*=[ ]*//; p; q;}; n; b l;}" $ini_file_path)  
    dns_api=$(sed -nr "/^\[OPTIONS\]/ { :l /^dns_api[ ]*=/ { s/.*=[ ]*//; p; q;}; n; b l;}" $ini_file_path)
    dns_frontend=$(sed -nr "/^\[OPTIONS\]/ { :l /^dns_frontend[ ]*=/ { s/.*=[ ]*//; p; q;}; n; b l;}" $ini_file_path)
    dns_cdn=$(sed -nr "/^\[OPTIONS\]/ { :l /^dns_cdn[ ]*=/ { s/.*=[ ]*//; p; q;}; n; b l;}" $ini_file_path)

    db_suffix=$(sed -nr "/^\[OPTIONS\]/ { :l /^db_suffix[ ]*=/ { s/.*=[ ]*//; p; q;}; n; b l;}" $ini_file_path)
    custom_cert=$(sed -nr "/^\[OPTIONS\]/ { :l /^custom_cert[ ]*=/ { s/.*=[ ]*//; p; q;}; n; b l;}" $ini_file_path)
    custom_cert_has_pass=$(sed -nr "/^\[OPTIONS\]/ { :l /^custom_cert_has_pass[ ]*=/ { s/.*=[ ]*//; p; q;}; n; b l;}" $ini_file_path)
    custom_cert_path=$(sed -nr "/^\[OPTIONS\]/ { :l /^custom_cert_path[ ]*=/ { s/.*=[ ]*//; p; q;}; n; b l;}" $ini_file_path)

    echo "$(tput setaf 3)Os seguintes apps foram encontrados no aquivo de configuração:$(tput setaf 7)"
    echo "$apps"

else
    echo "$(tput setaf 3)Arquivo de configuração não encontrado($ini_file_path), isso quer dizer que o setup irá instalar apenas os apps padrões.$(tput setaf 7)"
    echo "$(tput setaf 3)Para gerar o arquivo de configuração siga os passos em: <link>$(tput setaf 7)"
    read -e -p "Precione 'enter' para continuar sem o arquivo de configuração, ou digite 'n' para sair: " resp
    if [ "$resp" != "" ]; then
      exit 0
    fi
fi
    
for ARGUMENT in "$@"
do
   KEY=$(echo $ARGUMENT | cut -f1 -d=)

   KEY_LENGTH=${#KEY}
   VALUE="${ARGUMENT:$KEY_LENGTH+1}"

   export "$KEY"="$VALUE"
done

if [ "$custom_tags" == "" ];
then   
   ansible_tags="default-setup,install"
else      
   ansible_tags=$custom_tags
fi

# Validação de gateway_url
if [ "$gateway_url" == "" ];
then
    gateway_url = "https://gateway.korp.com.br"
else
   gateway_url=${gateway_url%/}
fi

# Validação de token

if [ "$token" == "" ];
then
    echo "$(tput setaf 1)O token não foi passado como parâmetro. Utilize 'token=\"<token>\".$(tput setaf 7)"
    exit 08
else
    status_code=$(curl -X GET -o /dev/null --silent "$gateway_url/TenantManagement/server-deploy/token/$token" --write-out '%{http_code}\n')
    
    if [ "$status_code" != "200" ];
    then
        echo "$(tput setaf 1)O token passado não é válido. Status Code: $status_code.$(tput setaf 7)"
        exit 09
    fi
fi

# Atualização de repositório, instalação de dependencias, instalação de ansible e git
echo Instalando Ansible e Git

# caso o comando falhe, checar 'https://askubuntu.com/questions/1123177/sudo-add-apt-repository-hangs'
sudo add-apt-repository --yes --update ppa:ansible/ansible
if [ $? != 0 ]
then
    echo "$(tput setaf 1)Erro 'sudo add-apt-repository --yes --update ppa:ansible/ansible'.$(tput setaf 7)"
    exit 12
fi
sudo apt install git ansible --yes
if [ $? != 0 ]
then
    echo "$(tput setaf 1)Erro 'sudo apt install ansible --yes'.$(tput setaf 7)"
    exit 13
fi

sudo rm -rf /tmp/KorpSetupLinux

git clone -b $branch_name --depth=1 --single-branch https://github.com/viasoftkorp/KorpSetupLinux.git /tmp/KorpSetupLinux

# Configuração de disco segundário, que será mondado em /etc/korp

if [ "$disk" != "" ];
then
    ansible-playbook /tmp/KorpSetupLinux/disk-playbook.yml --limit localhost --extra-vars "korp_disk=$disk"
    if [ $? != 0 ]
    then
        echo "$(tput setaf 1)Erro durante a execução do playbook 'disk-playbook.yml'.$(tput setaf 7)"
        exit 07
    fi
else
    ansible-playbook /tmp/KorpSetupLinux/disk-playbook.yml --limit localhost
    if [ $? != 0 ]
    then
        echo "$(tput setaf 1)Erro durante a execução do playbook 'disk-playbook.yml'.$(tput setaf 7)"
        exit 07
    fi
fi

# Entrará nesse 'if' caso o arquivo de inventário não exista
if ! sudo test -f /etc/korp/ansible/inventory.yml;
then
    # Cria e diretórios que serão usados depois
    sudo mkdir -p /etc/korp/ansible/
    # Criação de senha aleatória usada pelo ansible-vault
    echo $(create_random_string) | sudo tee /etc/korp/ansible/.vault_key > /dev/null
    sudo chown root:root /etc/korp/ansible/.vault_key  
    # Altera a permissão de .vault_key
    sudo chmod 444 /etc/korp/ansible/.vault_key
    # Cria inventory.yml
    sudo touch /etc/korp/ansible/inventory.yml 
    # Corrige a permição dos arquivos
    sudo chmod 644 /etc/korp/ansible/inventory.yml
    # Configuração de '/etc/ansible/ansible.cfg' para apontar o inventário para '/etc/korp/ansible/inventory.yml'
    echo """  
    [defaults]
    inventory = /etc/korp/ansible/inventory.yml
    """ | sudo tee /etc/ansible/ansible.cfg > /dev/null
    # Encripta 'inventory.yml' com ansible-vault
    sudo ansible-vault encrypt /etc/korp/ansible/inventory.yml --vault-id /etc/korp/ansible/.vault_key
    sudo chmod 644 /etc/korp/ansible/inventory.yml
fi

ansible-playbook /tmp/KorpSetupLinux/inventory-playbook.yml --vault-id /etc/korp/ansible/.vault_key \
  -v \
  --extra-vars='{
    "token": "'$token'",
    "gateway_url": "'$gateway_url'",
    "db_suffix": "'$db_suffix'",
    "custom_setup_info": {
      "cert": {
        "cert_type": "'$cert_type'",
        "custom_cert_has_pass": "'$custom_cert_has_pass'",
        "custom_cert_path": "'$custom_cert_path'",
        "certbot_email": "'$certbot_email'"
      },
      "dns": {
        "api": "'$dns_api'",
        "frontend": "'$dns_frontend'",
        "cdn": "'$dns_cdn'"
      },
      "https_port": "'$https_port'",
      "external_reverse_proxy": "'$external_reverse_proxy'",
      "use_servergc": "'$use_servergc'",
      "expose_postgres": "'$expose_postgres'"
    }
  }'

if [ $? != 0 ]
then
    echo "$(tput setaf 1)Erro durante a execução do playbook 'inventory-playbook.yml'.$(tput setaf 7)"
    exit 14
fi

# Encripta 'inventory.yml' com ansible-vault visto que essa operação não pode ser feita no playbook
sudo ansible-vault encrypt /etc/korp/ansible/inventory.yml --vault-id /etc/korp/ansible/.vault_key
sudo chmod 644 /etc/korp/ansible/inventory.yml

# fixado para evitar problema do docker (https://github.com/ansible-collections/community.docker/blob/main/CHANGELOG.md#v3103)
sudo ansible-galaxy collection install 'community.docker:>=3.10.3' -p /usr/lib/python3/dist-packages/ansible_collections --force

ansible-playbook /tmp/KorpSetupLinux/bootstrap-playbook.yml \
  $(sudo -nv 2> /dev/null; if [ $? -eq 1 ]; then echo "-K"; fi;) \
  --limit localhost \
  --vault-id /etc/korp/ansible/.vault_key \
  --tags=$ansible_tags \
  -v \
  --extra-vars='{
    "token": "'$token'",
    "gateway_url": "'$gateway_url'",
    "customs": {
      "docker_account": "'$docker_account'",
      "docker_image_suffix": "'$docker_image_suffix'",
      "remove_versioned": '$remove_versioned',
      "remove_unversioned": '$remove_unversioned'
    },
    "apps":['$apps'],
    "removed_version": "'$removed_version'",
    "skip_salt_test": '$skip_salt_test',
    "should_update_rabbitmq": '$should_update_rabbitmq'
  }'

if [ $? != 0 ]
then
    echo "$(tput setaf 1)Erro durante a execução do playbook 'main.yml'.$(tput setaf 7)"
    exit 11
fi

sudo rm -rf /tmp/KorpSetupLinux
