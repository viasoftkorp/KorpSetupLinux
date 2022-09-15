#!/bin/bash

gateway_url="https://gateway.korp.com.br"

create_random_string() {
  local l=15
  [ -n "$1" ] && l=$1
  [ -n "$2" ] && l=$(shuf --random-source=/dev/urandom -i $1-$2 -n 1)
  tr -dc A-Za-z0-9 < /dev/urandom | head -c ${l} | xargs
}

# Leitura de parâmetros passados para o script
# parametros esperados:
#   token="<token>" - OBRIGATÓRIO
#   disk="<sdx>"
#   gateway_url="<gateway_url>"


apps=""
ini_file_path="./setup_config.ini"

if test -f $ini_file_path; 
then
    apps=$(sed -nr "/^\[OPTIONS\]/ { :l /^apps[ ]*=/ { s/.*=[ ]*//; p; q;}; n; b l;}" $ini_file_path)

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

if [ "$apps" == "" ]; then
    apps="default-setup"
else
    apps="default-setup,$apps"
fi


for ARGUMENT in "$@"
do
   KEY=$(echo $ARGUMENT | cut -f1 -d=)

   KEY_LENGTH=${#KEY}
   VALUE="${ARGUMENT:$KEY_LENGTH+1}"

   export "$KEY"="$VALUE"
done


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


# Atualização de repositório, instalação de dependencias, isntalação de ansible

echo Instalando Ansible

# caso o comando falhe, checar 'https://askubuntu.com/questions/1123177/sudo-add-apt-repository-hangs'
sudo add-apt-repository --yes --update ppa:ansible/ansible
if [ $? != 0 ]
then
    echo "$(tput setaf 1)Erro 'sudo add-apt-repository --yes --update ppa:ansible/ansibl'.$(tput setaf 7)"
    exit 12
fi
sudo apt install ansible --yes
if [ $? != 0 ]
then
    echo "$(tput setaf 1)Erro 'sudo apt install ansible --yes'.$(tput setaf 7)"
    exit 13
fi

# Configuração de disco segundário, que será mondado em /etc/korp

if [ "$disk" != "" ];
then
    ansible-pull -U https://github.com/viasoftkorp/KorpSetupLinux.git disk-playbook.yml --limit localhost --extra-vars "korp_disk=$disk"
    if [ $? != 0 ]
    then
        echo "$(tput setaf 1)Erro durante a execução do playbook 'disk-playbook.yml'.$(tput setaf 7)"
        exit 07
    fi
else
    ansible-pull -U https://github.com/viasoftkorp/KorpSetupLinux.git disk-playbook.yml --limit localhost
    if [ $? != 0 ]
    then
        echo "$(tput setaf 1)Erro durante a execução do playbook 'disk-playbook.yml'.$(tput setaf 7)"
        exit 07
    fi
fi


# Validação do arquivo de inventário para saber se o setup está sendo rodado pela primeira vez, ou não

is_first_install=False

if ! sudo test -f /etc/korp/ansible/inventory.yml ;
then
    is_first_install=True
fi


# Caso seja a primeira instalação, irá gerar os arquivos/configurações nocessários(as)

if [ $is_first_install = True ];
then

    # Cria e diretórios que serão usados depois
    sudo mkdir -p /etc/korp/ansible/

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

""" | sudo tee /etc/korp/ansible/inventory.yml > /dev/null

    sudo chmod 644 /etc/korp/ansible/inventory.yml

    echo """
[defaults]
inventory = /etc/korp/ansible/inventory.yml
""" | sudo tee /etc/ansible/ansible.cfg > /dev/null

    # Criação de senha aleatória usada pelo ansible-vault
    echo $(create_random_string) | sudo tee /etc/korp/ansible/.vault_key > /dev/null
    sudo chown root:root /etc/korp/ansible/.vault_key

    # Encripta 'inventory.yml' com ansible-vault
    sudo ansible-vault encrypt /etc/korp/ansible/inventory.yml --vault-id /etc/korp/ansible/.vault_key

    # Corrige a permição dos arquivos
    sudo chmod 644 /etc/korp/ansible/inventory.yml
    sudo chmod 444 /etc/korp/ansible/.vault_key
fi


# Execução de playbook bootstrap-playbook.yml
ansible-pull -U https://github.com/viasoftkorp/KorpSetupLinux.git bootstrap-playbook.yml --limit localhost --vault-id /etc/korp/ansible/.vault_key --extra-vars='{"token": "'$token'", "gateway_url":"'$gateway_url'", "apps":['$apps']}' -C TD-978
if [ $? != 0 ]
then
    echo "$(tput setaf 1)Erro durante a execução do playbook 'main.yml'.$(tput setaf 7)"
    exit 11
fi
