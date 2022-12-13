Configurando o Ambiente
-----------------------

Configurando as entradas de DNS
###############################

Configurar os seguintes DNSs para resolverem os endereços indicados:

  - korp.local deve resolver para o servidor LINUX
  - korp-api.local deve resolver para o servidor LINUX
  - korp-cdn.local deve resolver para o servidor LINUX

----

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

Configurando o envio de e-mail de falha
#######################################

Essa configuração serve para avisar o usuário caso haja um problema com o envio do seu email. Para configurar:

#. Acessar o endereço http://korp.local:8500/ui/dc1/kv/Viasoft.Email/edit
#. Preencher as seguintes propriedades conforme o seu provedor de email

    :FromAddress: endereço de remetente do email de falha
    :SmtpHostName: hostname do provedor SMTP
    :SmtpPassWord: senha da conta SMTP
    :SmtpPort: porta do provedor SMTP
    :SmtpUserName: usuário da conta SMTP

#. Reiniciar o serviço Viasoft.Email
#. Verificar que recebeu um e-mail na caixa de entrada da conta configurada no campo "FromAdress"
