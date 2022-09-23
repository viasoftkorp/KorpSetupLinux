echo "$(tput setaf 2)Atualizando containers...$(tput setaf 7)"

sudo docker run --rm -v /var/run/docker.sock:/var/run/docker.sock containrrr/watchtower --run-once --cleanup
if [ $? != 0 ]
then
    echo "$(tput setaf 1)Erro durante atualização de containers.$(tput setaf 7)"
    exit 01
fi

echo "$(tput setaf 2)Containers atualizados$(tput setaf 7)"
