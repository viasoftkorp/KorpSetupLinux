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
#   token="<token>" - OBRIGATÓRIO#  
#   disk="<sdx>"
#   gateway_url="<gateway_url>"
#   install_apps="<apps1,apps2>"
#   run_bootstrap=false - ira rodar o main.yml e não bootstrap-playbook.yml   (padrão true)
#   custom_tags="<tag1,tag2>" - OPCIONAL, caso não sejá passada, as tags "default-setup,install" serão usadas


apps=""; docker_account=""; ansible_tags=""; dns_api=""; dns_frontend=""; dns_cdn="";
run_bootstrap="True"
ini_file_path="./setup_config.ini"

if test -f $ini_file_path;
then
    docker_account=$(sed -nr "/^\[OPTIONS\]/ { :l /^docker_account[ ]*=/ { s/.*=[ ]*//; p; q;}; n; b l;}" $ini_file_path)
    dns_api=$(sed -nr "/^\[OPTIONS\]/ { :l /^dns_api[ ]*=/ { s/.*=[ ]*//; p; q;}; n; b l;}" $ini_file_path)
    dns_frontend=$(sed -nr "/^\[OPTIONS\]/ { :l /^dns_frontend[ ]*=/ { s/.*=[ ]*//; p; q;}; n; b l;}" $ini_file_path)
    dns_cdn=$(sed -nr "/^\[OPTIONS\]/ { :l /^dns_cdn[ ]*=/ { s/.*=[ ]*//; p; q;}; n; b l;}" $ini_file_path)

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

if [ "$install_apps" == "" ];
then   
   apps=$(sed -nr "/^\[OPTIONS\]/ { :l /^apps[ ]*=/ { s/.*=[ ]*//; p; q;}; n; b l;}" $ini_file_path)
else      
   apps=$install_apps
fi

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

if ! sudo test -f /etc/korp/ansible/inventory.yml ;
then
    # Cria e diretórios que serão usados depois
    sudo mkdir -p /etc/korp/ansible/
     # Criação de senha aleatória usada pelo ansible-vault
    echo $(create_random_string) | sudo tee /etc/korp/ansible/.vault_key > /dev/null
    sudo chown root:root /etc/korp/ansible/.vault_key  
    #cria permissao para vault_key  
    sudo chmod 444 /etc/korp/ansible/.vault_key  
    #cria inventory.yml  
    touch /etc/korp/ansible/inventory.yml 
    # Corrige a permição dos arquivos
    sudo chmod 644 /etc/korp/ansible/inventory.yml
    echo """  
    [defaults]
    inventory = /etc/korp/ansible/inventory.yml
    """ | sudo tee /etc/ansible/ansible.cfg > /dev/null
  # Encripta 'inventory.yml' com ansible-vault
  
sudo ansible-vault encrypt /etc/korp/ansible/inventory.yml --vault-id /etc/korp/ansible/.vault_key
fi
# Instalando o playbook em logo em seguida executa-lo para iniciar interacao de shell 
wget -P /tmp  https://raw.githubusercontent.com/viasoftkorp/KorpSetupLinux/DEVOPS-80/inventory-playbook.yml

ansible-playbook /tmp/inventory-playbook.yml  --vault-id /etc/korp/ansible/.vault_key 

#playbook após executado necessario fazer encriptacao 
sudo ansible-vault encrypt /etc/korp/ansible/inventory.yml --vault-id /etc/korp/ansible/.vault_key

# verificação caso não deseja que rode o bootstrap-playbook.yml
playbook_name=""
if [ ${run_bootstrap^^} == "FALSE" ];
then
    playbook_name="main.yml" 
else
    playbook_name="bootstrap-playbook.yml"  
fi

ansible-pull -U https://github.com/viasoftkorp/KorpSetupLinux.git $playbook_name \
  --limit localhost \
  --vault-id /etc/korp/ansible/.vault_key \
  --tags=$ansible_tags \
  --extra-vars='{
    "token": "'$token'",
    "gateway_url": "'$gateway_url'",
    "customs": {
      "docker_account": "'$docker_account'",
      "frontend": {
        "dns": {
          "api": "'$dns_api'",
          "frontend": "'$dns_frontend'",
          "cdn": "'$dns_cdn'"
        }
      }
    },
    "apps":['$apps']
  }' -C DEVOPS-80

if [ $? != 0 ]
then
    echo "$(tput setaf 1)Erro durante a execução do playbook 'main.yml'.$(tput setaf 7)"
    exit 11
fi
