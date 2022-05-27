#clone repo

# Válida se o script está sendo rodado como root
if [ $(/usr/bin/id -u) -ne 0 ]; then
    echo "Por favor, execute o scrip como administrador"
    exit 01
fi

# Atualização de repositório, instalação de dependencias, isntalação de ansible
echo Instalando Ansible

# sudo apt update
# sudo apt install software-properties-common
# # Testar add-apt-repository
# sudo add-apt-repository --yes --update ppa:ansible/ansible
# sudo apt install ansible -y

echo "\n-----------------------\n"
echo "Para continuar a instalação, digite as seguintes informações sobre o servidor SQL Server:"
echo "IP de acesso: "
read sql_ip
echo "Usuário com permissões administrativas: "
read sql_user
echo "Senha do usuário: "
read sql_pass
echo "\nAgora, digite as seguintes informações sobre o servidor Linux"
echo "Usuário com permissões administrativas: "
read linux_user
echo "Senha do usuário: "
read linux_pass
# TODO IP do servicor

# cria arquivo 'ansible-vars.json' com base nas respostas das perguntas anteriores
printf """
all:
  children:
    ungrouped:
      hosts:
        192.168.1.107:
          mssql:
            address: $sql_ip
            user: $sql_user
            password: $sql_pass
          linux:
            user: $linux_user
            password: $linux_pass
"""> ansible-inventory.yml

# sudo ansible-playbook provisioning_playbook.yml --inventory-file ansible-inventory.yml
sudo ansible-pull -U https://github.com/viasoftkorp/KorpSetupLinux.git --inventory-file ansible-inventory.yml provisioning_playbook.yml


