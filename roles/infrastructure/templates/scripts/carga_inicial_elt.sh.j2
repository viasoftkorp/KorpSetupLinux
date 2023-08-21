#!/bin/bash


# Parametros aceitados:
#   environmentId=<GUID>


is_valid_guid() {
  local guid_pattern='^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}$'
  [[ "$1" =~ $guid_pattern ]]
}

environmentId=""

for ARGUMENT in "$@"
do
   KEY=$(echo $ARGUMENT | cut -f1 -d=)

   KEY_LENGTH=${#KEY}
   VALUE="${ARGUMENT:$KEY_LENGTH+1}"

   export "$KEY"="$VALUE"
done

consulUrl='http://localhost:8500'

LegacyEltServiceName='Korp.Legacy.ELT'
TenantManagementServiceName='Viasoft.TenantManagement'

if [ "$environmentId" == "" ]; then
  while true; do
    read -p "Digite o environmentId: " environmentId
    if is_valid_guid "$environmentId"; then
      break
    else
      echo "O valor inserido não é um GUID válido. Tente novamente."
    fi
  done
fi
if ! is_valid_guid "$environmentId" ; then
  echo "$(tput setaf 1)O valor de environmentId não é um GUID válido. Tente novamente.$(tput setaf 7)"
  exit 10
fi


# Leitura de propriedades consul
jsonRequestConsulGlobal=$(curl --silent --request GET \
  --url "$consulUrl/v1/kv/Global?raw=true")
TenantId=$(echo "$jsonRequestConsulGlobal" | jq -r '.OnPremiseLicensedTenants')
if [ -z "$TenantId" ]; then
  echo "$(tput setaf 1)ERRO: TenantId está vazio$(tput setaf 7)"
  exit 9
fi
gatewayUrl=$(echo "$jsonRequestConsulGlobal" | jq -r '.LegacyGateway')
if [ -z "$gatewayUrl" ]; then
  echo "$(tput setaf 1)ERRO: TenantId está vazio$(tput setaf 7)"
  exit 3
fi

jsonRequestConsulLegacyELT=$(curl --silent --request GET \
  --url "$consulUrl/v1/kv/$LegacyEltServiceName?raw=true")
LegacyEltSecret=$(echo "$jsonRequestConsulLegacyELT" | jq -r '.Authorization.Secret')
if [ -z "$LegacyEltSecret" ]; then
  echo "$(tput setaf 1)ERRO: LegacyEltSecret está vazio$(tput setaf 7)"
  exit 1
fi

jsonRequestConsulTenantManagement=$(curl --silent --request GET \
  --url "$consulUrl/v1/kv/$TenantManagementServiceName?raw=true")
TenantManagementSecret=$(echo "$jsonRequestConsulTenantManagement" | jq -r '.Authorization.Secret')
if [ -z "$TenantManagementSecret" ]; then
  echo "$(tput setaf 1)ERRO: TenantManagementSecret está vazio$(tput setaf 7)"
  exit 2
fi
#################

requestGatewayTokenUrl="$gatewayUrl/oauth/connect/token"

# Leitura de Token de serviços
jsonRequestTokenTenantManagement=$(curl --silent --request POST \
  --url $requestGatewayTokenUrl \
  --header 'Content-Type: application/x-www-form-urlencoded' \
  --data grant_type=client_credentials \
  --data client_id=$TenantManagementServiceName  \
  --data client_secret=$TenantManagementSecret)
TenantManagementAccessToken=$(echo "$jsonRequestTokenTenantManagement" | tr -d '\r\n' | jq -r '.access_token')
if [ -z "$TenantManagementAccessToken" ]; then
  echo "$(tput setaf 1)ERRO: TenantManagementAccessToken está vazio$(tput setaf 7)"
  exit 4
fi

jsonRequestTokenLegacyELT=$(curl --silent --request POST \
  --url $requestGatewayTokenUrl \
  --header 'Content-Type: application/x-www-form-urlencoded' \
  --data grant_type=client_credentials \
  --data client_id=$LegacyEltServiceName  \
  --data client_secret=$LegacyEltSecret)
LegacyEltAccessToken=$(echo "$jsonRequestTokenLegacyELT" | tr -d '\r\n' | jq -r '.access_token' | tr -d '[:space:]')
if [ -z "$LegacyEltAccessToken" ]; then
  echo "$(tput setaf 1)ERRO: LegacyEltAccessToken está vazio$(tput setaf 7)"
  exit 5
fi
#################

echo "Leitura de environments"
returnJsonRequestTenantManagement=$(curl --silent --location --request GET \
  --url "$gatewayUrl/TenantManagement/environments?TenantIds=$TenantId&MaxResultCount=50" \
  --header "Authorization: Bearer  $TenantManagementAccessToken" )

if [ -z "$returnJsonRequestTenantManagement" ]; then
  echo "$(tput setaf 1)ERRO: returnJsonRequestTenantManagement está vazio$(tput setaf 7)"
  exit 6
fi

echo "Definição de 'DatabaseName' e 'DatabaseVersion'"
match_found=false
while read -r item; do
  id=$(jq -r '.id' <<< "$item")
  if [ "$id" == "$environmentId" ]; then
    match_found=true
    DatabaseName=$(jq -r '.databaseName' <<< "$item")
    DatabaseVersion=$(jq -r '.desktopDatabaseVersion' <<< "$item")
    break
  fi
done <<< "$(echo "$returnJsonRequestTenantManagement" | jq -c '.items[]')"


if [ "$match_found" = true ]; then
  echo "environmentId encontrado na requisição ao serviço do Viasoft.TenantManagement."
  echo "DatabaseName: $DatabaseName"
  echo "DatabaseVersion: $DatabaseVersion"
else
  echo "$(tput setaf 1)EnvironmentId não encontrado no JSON.$(tput setaf 7)"
  exit 7
fi

echo "Iniciando a carga de dados"
status_code=$(curl -X POST -o /dev/null --silent  --write-out '%{http_code}\n' \
  --url "$gatewayUrl/$DatabaseVersion/ELT/carga-inicial" \
  --header "TenantId: $TenantId" \
  --header "DatabaseName: $DatabaseName" \
  --header "EnvironmentId: $environmentId" \
  --header "Authorization: Bearer $LegacyEltAccessToken" )

if [ "$status_code" != "200" ];
then
    echo "$(tput setaf 1)Erro na requisição para o Legacy ELT. Status Code: $status_code.$(tput setaf 7)"
    exit 8
else
  echo "$(tput setaf 2)Carga de dados feita com sucesso. $(tput setaf 7)"
fi
