Homologação do servidor Linux
-----------------------------

Após a implantação do servidor Linux, é necessário fazer sua homologação, ou seja, garantir que o sistema está funcionando normalmente antes de ser utilizado em produção.

Após o período de homologação, é feita então a migração do servidor de Aplicações Windows para o servidor de Aplicações Linux.

Homologação do portal WEB
=========================

O acesso do portal web local pode ser feito pelo endereço: https://korp.local.

Porém, antes de poder fazer o acesso, os seguintes passos precisam ser feitos:

Configuração de DNS
###################

Configurar os seguintes DNSs para resolverem os edereços indicados:

  - korp.local deve resolver para o servidor LINUX
  - korp-api.local deve resolver para o servidor LINUX
  - korp-cdn.local deve resolver para o servidor LINUX


Disponibilizando a CA nas estações de trabalho
##############################################

Disponibilizar um certificado para as estação que irão utilizar o portal Local.

O certificado da CA pode ser obtido copiando o arquivo ``ca-cert.crt`` que está disponível na ``home`` do usuário que foi disponibilizado para instalação no servidor Linux.

Há duas opções disponíveis para a importação da CA:

 - O cliente tem AD e disponibiliza a CA via política
 
 - O cliente importa manualmente em cada estação de trabalho a CA via o comando ``certutil.exe -addstore root C:\temp\ca-cert.crt``

.. note:: 
  
  Após importar a CA, é necessário fechar completamente o navegador e recarregar a página caso a mesma abra sozinha novamente.

----

Acesso ao portal local
######################

Assim que os tópicos de DNS e CA estiverem configurados corretamente, já é possível acessar o ambiente pelo endereço https://korp.local.

É importante lembrar que as permissões do Korp ERP não se aplicam ao ambiente WEB, portanto para o primeiro acesso terá que utilizar o login do usuário raiz do licenciamento o e-mail.

Para confirmar o login desse usuário, pode-se acessar o https://portal.com.com.br, pelo aplicativo de Admin.

Homologando o portal local
##########################

Para a homologação do portal local, deve-se fazer o uso dos aplicativos licensidos.

----

Homologação do Korp
===================

#.  Nas estações de trabalho, realizar as seguintes alterações no arquivo ``config.json``
  
  - Alterar a propriedade ``GatewayIp`` para o IP do servidor LINUX.
  - Alterar a propriedade ``GatewayPort`` para a ``9999``.

#. Verificar que é possível realizar o login

#. Verificar que as notícias na tela inicial aparecam corretamente

#. Configurar os parâmetros de servidor de e-mail (não esqueça de realizar o logout e login após altera-los):
  
  - Localizar o parâmetro da seção Internet e chave BackgroundEmail

    - Trocar o seu valor para True

  - Localizar o parâmetro da seção REST e chave Email

    - Trocar o seu valor para http://IP-SERVIDOR-LINUX:9999/. Exemplo: http://192.168.1.52:9999/

#. Realizar envio de email pelo Korp, e verificar que o email é recebido corretamente


----

Outros tópicos que devem ser feitos durante a homolocação
=========================================================

Configurando o envio de e-mail de falha
#######################################

Essa configuração serve para avisar o usuário caso haja um problema com o envio do seu email. Para configurar:

#. Acessar o endereço http://korp.local:8500/ui/dc1/kv/Viasoft.Email/edit

#. Preencher as seguintes propriedades conforme o seu provedor de email
 
  - FromAddress - endereço de remetente do email de falha
  - SmtpHostName - hostname do provedor SMTP
  - SmtpPassWord - senha da conta SMTP
  - SmtpPort - porta do provedor SMTP
  - SmtpUserName - usuário da conta SMTP

#. Reiniciar o serviço Viasoft.Email

#. Verificar que recebeu um e-mail na caixa de entrada da conta configurada no campo "FromAdress"


----

.. note::
  
  A responsabilidade da validação e garantia do funcionamento do novo ambiente fica de responsabilidade do cliente
