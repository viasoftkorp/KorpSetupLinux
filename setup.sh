#!/bin/bash

create_random_string() {
  local l=15
  [ -n "$1" ] && l=$1
  [ -n "$2" ] && l=$(shuf --random-source=/dev/urandom -i $1-$2 -n 1)
  tr -dc A-Za-z0-9 < /dev/urandom | head -c ${l} | xargs
}

# Leitura de parâmetros passados para o script
# parametros esperados:
#   tenant="<tenant-id>"
#   disk="<sdx>"

for ARGUMENT in "$@"
do
   KEY=$(echo $ARGUMENT | cut -f1 -d=)

   KEY_LENGTH=${#KEY}
   VALUE="${ARGUMENT:$KEY_LENGTH+1}"

   export "$KEY"="$VALUE"
done


# Válida se o script está sendo rodado como root
if [ $(/usr/bin/id -u) -ne 0 ]; then
    echo "$(tput setaf 3)Por favor, execute o scrip como administrador.$(tput setaf 7)"
    exit 01
fi


# Atualização de repositório, instalação de dependencias, isntalação de ansible
echo Instalando Ansible

sudo apt-get install python3 --yes
sudo apt install python3-pip --yes
sudo python3 -m pip install ansible


is_first_install=False


# Configuração de disco segundário, que será mondado em /etc/korp

if [ "$disk" != "" ];
then
  sudo ansible-pull -U https://github.com/viasoftkorp/KorpSetupLinux.git disk-playbook.yml --limit localhost --extra-vars "korp_disk=$disk"
  if [ $? != 0 ]
  then
    exit 07
  fi
else
  sudo ansible-pull -U https://github.com/viasoftkorp/KorpSetupLinux.git disk-playbook.yml --limit localhost
  if [ $? != 0 ]
  then
    exit 07
  fi
fi


# Confirma que o script tem o tenant  - NÃO valida a GUID
if ! test -f /etc/korp/tenant  && [ "$tenant" == "" ] ;
then
    echo "$(tput setaf 1)Setup sendo executado pela primeira vez, porém o tenant não foi passado.$(tput setaf 7)"
    exit 02
else
    if test -f /etc/korp/tenant;
    then
        if [ "$tenant" ];
        then
            if [ "$(cat /etc/korp/tenant)" != "$tenant" ];
            then
                echo ""
                echo "$(tput setaf 1)O setup já foi rodado uma vez com outro tenant. Por favor vefique o tenant e tente novamente.$(tput setaf 7)"
                exit 03
            fi
        fi
    else
        is_first_install=True
        sudo sudo mkdir -p /etc/korp/
        sudo chmod 0774 /etc/korp/
        sudo echo "$tenant" > /etc/korp/tenant
        sudo chmod 0444 /etc/korp/tenant
    fi
fi
tenant=$(cat /etc/korp/tenant)


# Caso seja a primeira instalação, irá os arquivos/configurações nocessários(as)
if [ $is_first_install = True ];
then

    # Cria e configuração de diretórios que serão usados depois
    sudo mkdir -p /etc/ansible/hosts/
    sudo chmod 0774 /etc/ansible/

    echo -e "\n-----------------------\n"
    echo "Para continuar a instalação, digite as seguintes informações sobre o servidor SQL Server:"
    read -e -p "IP de acesso: " sql_ip
    read -e -p "Usuário com permissões administrativas: " sql_user
    read -e -p "Senha do usuário: " sql_pass
    read -p "Agora, informe o IP do Servidor de aplicações (ou pressione enter para usar '$sql_ip'): " application_server_address
    application_server_address=${application_server_address:-$sql_ip}


    # Criação de senhas aleatórios para o usuário do mssql, postgres e do linux
    mssql_korp_pass="$(create_random_string)"
    postgres_korp_pass="$(create_random_string)"
    linux_korp_pass="$(create_random_string)"
    rabbitmq_korp_pass="$(create_random_string)"
    redis_pass="$(create_random_string)"
    minio_access_key="$(create_random_string)"
    minio_secret_key="$(create_random_string)"


    # Cria arquivo 'ansible-vars.json' com base nas respostas das perguntas anteriores, e nas senhas geradas
    echo """
all:
  children:
    nodes:
      hosts:
        localhost:
          app_server:
            address: $application_server_address
          linux_korp:
            user: korp
            password: $linux_korp_pass
          self_signed_cert:
            passphrase: korp
          mssql:
            address: $sql_ip
            default_user: $sql_user
            default_password: $sql_pass
            korp_user: korp.services
            korp_password: $mssql_korp_pass
          postgres:
            address: 127.0.0.1
            default_user: postgres
            default_password: postgres
            korp_user: korp.services
            korp_password: $postgres_korp_pass
          rabbitmq:
            korp_user: korp.services
            korp_password: $rabbitmq_korp_pass
          redis:
            password: $redis_pass
          minio:
            access_key: $minio_access_key
            secret_key: $minio_secret_key
          general:
            introspection_secret: $(cat /proc/sys/kernel/random/uuid)

""" > /etc/ansible/ansible-inventory.yml

echo """
[defaults]
inventory = /etc/ansible/ansible-inventory.yml

""" > /etc/ansible/ansible.cfg


    # Criação de senha aleatória usada pelo ansible-vault
    sudo echo $(create_random_string) > /etc/ansible/.vault_key
    sudo chown root:root /etc/ansible/.vault_key
    sudo chmod 400 /etc/ansible/.vault_key


    # Encripta 'ansible-inventory.yml' com ansible-vault
    sudo ansible-vault encrypt /etc/ansible/ansible-inventory.yml --vault-id /etc/ansible/.vault_key
fi


# '--limit localhost' é necessário pois 'ansible-pull' dará um erro de host não especificato com isso
sudo ansible-pull -U https://github.com/viasoftkorp/KorpSetupLinux.git main.yml --limit localhost --vault-id /etc/ansible/.vault_key
