#!/bin/bash

create_random_string() {
  local l=15
  [ -n "$1" ] && l=$1
  [ -n "$2" ] && l=$(shuf --random-source=/dev/urandom -i $1-$2 -n 1)
  tr -dc A-Za-z0-9 < /dev/urandom | head -c ${l} | xargs
}


# Válida se o script está sendo rodado como root
if [ $(/usr/bin/id -u) -ne 0 ]; then
    echo "$(tput setaf 3)Por favor, execute o scrip como administrador.$(tput setaf 7)"
    exit 01
fi


is_first_install=False


# Confirma que o script tem o tenant  - NÃO valida a GUID
if ! test -f /etc/korp/tenant  && [ $# = 0 ] ;
then
    echo "$(tput setaf 1)Setup sendo executado pela primeira vez, porém o tenant não foi passado.$(tput setaf 7)"
    exit 02
else
    if test -f /etc/korp/tenant;
    then
        if [ $# = 1 ];
        then
            if [ "$(cat /etc/korp/tenant)" != "$1" ];
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
        sudo echo $1 > /etc/korp/tenant
        sudo chmod 0444 /etc/korp/tenant
    fi
fi
tenant=$(cat /etc/korp/tenant)


# Atualização de repositório, instalação de dependencias, isntalação de ansible
echo Instalando Ansible

sudo apt-get install python3
sudo apt install python3-pip
sudo python3 -m pip install ansible


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


    # Criação de senhas aleatórios para o usuário do mssql, postgres e do linux
    mssql_korp_pass="$(create_random_string)"
    postgres_korp_pass="$(create_random_string)"
    linux_korp_pass="$(create_random_string)"


    # Cria arquivo 'ansible-vars.json' com base nas respostas das perguntas anteriores, e nas senhas geradas
    echo """
all:
  children:
    nodes:
      hosts:
        localhost:
          linux_korp:
            user: korp
            password: $linux_korp_pass
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
