Configurando o Ambiente
-----------------------

Configurando as entradas de DNS
###############################

Configurar os :doc:`3 DNSs utilizados pelo portal </files/visao_geral/dns>` para resolverem para o IP do servidor Linux

----

Disponibilizando a CA nas estações de trabalho
##############################################

O certificado deverá ser instalado em todas as estações de trabalho, ou seja, computadores que acessão o Korp ERP e korp WEB.

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

#. Acessar o endereço ``http://<dns_frontend>:8500/ui/dc1/kv/Viasoft.Email/edit``
#. Preencher as seguintes propriedades conforme o seu provedor de email

    :FromAddress: endereço de remetente do email de falha
    :SmtpHostName: hostname do provedor SMTP
    :SmtpPassWord: senha da conta SMTP
    :SmtpPort: porta do provedor SMTP
    :SmtpUserName: usuário da conta SMTP
    :Crypto: tipo de criptografia utilizado:

      - ``StartTLS``
      - ``SSLTLS``
      - ``None`` (nenhuma/não utilizar)

#. Reiniciar o serviço Viasoft.Email
#. Verificar que recebeu um e-mail na caixa de entrada da conta configurada no campo "FromAdress"
