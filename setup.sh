#clone repo


# Válida se o script está sendo rodado como root
if [ $(/usr/bin/id -u) -ne 0 ]; then
    echo "Por favor, execute o scrip como administrador"
    exit 01
fi

echo Instalando Ansible

sudo apt update
sudo apt install software-properties-common
sudo add-apt-repository --yes --update ppa:ansible/ansible
sudo apt install ansible -y
