Homologação do servidor Linux
-----------------------------

Após a implantação do servidor Linux, é necessário fazer sua homologação, ou seja, garantir que o sistema está funcionando normalmente antes de ser utilizado em produção.

Após o período de homologação, é feita então a migração do servidor de Aplicações Windows para o servidor de Aplicações Linux.

Assim que tiver os tópicos de DNS e CA configurados corretamente, já é possível acessar o ambiente pelo endereço Portal Local utilizando as mesmas credenciais do Korp. 

É importante lembrar que as permissões do Korp ERP não se aplicam ao ambiente WEB, portanto para o primeiro acesso terá que utilizar o usuário raiz do licenciamento o e-mail. O login desse usuário pode ser confirmado pelo aplicativo de Admin do Portal. 

Especificações de DNS
=====================

 - korp.local deve resolver para o servidor LINUX
 - korp-api.local deve resolver para o servidor LINUX
 - korp-cdn.local deve resolver para o servidor LINUX

Disponibilizando a CA nas estações de trabalho
==============================================

O certificado da CA está no servidor LINUX, mas deixarei um link de comodidade aqui para vocês pegarem ele  

O certificado da CA pode ser obtido copiando o arquivo ca-cert.crt que está disponível na home do servidor Linux do usuário que foi disponibilizado para instalação. 

São duas opções disponíveis para a importação da CA:

 - O cliente tem AD e disponibiliza a CA via política
 
 - O cliente importa manualmente em cada estação de trabalho a CA via o comando ‘certutil.exe -addstore root C:\temp\ca-cert.cr’

Importante: Após importar a CA, é necessário fechar completamente o navegador e recarregar a página caso a mesma abra sozinha novamente.

Configurando o envio de e-mail de falha
=======================================

Essa configuração serve para avisar o usuário caso haja um problema com o envio do seu email. Para configurar:

1. Acessar o endereço http://korp.local:8500/ui/dc1/kv/Viasoft.Email/edit

2. Preencher as seguintes propriedades conforme o seu provedor de email
 
  - FromAddress - endereço de remetente do email de falha
  - SmtpHostName - hostname do provedor SMTP
  - SmtpPassWord   - senha da conta SMTP
  - SmtpPort             - porta do provedor SMTP
  - SmtpUserName - usuário da conta SMTP

3. Reiniciar o serviço Viasoft.Email

4. Verificar que recebeu um e-mail na caixa de entrada da conta configurada no campo "FromAdress"

Como homologar o novo servidor pelo Korp:
=========================================

1.  Nas estações de trabalho, realizar as seguintes alterações no arquivo ``config.json``
  
  - Alterar a propriedade "GatewayIp" para o IP do servidor LINUX.
  - Alterar a propriedade "GatewayPort" para a "9999".

2. Verificar que é possível realizar o login

3. Verificar que as notícias na tela inicial aparecam corretamente

4. Configurar os parâmetros de servidor de e-mail (não esqueça de realizar o logout e login após altera-los):
  
  - Localizar o parâmetro da seção Internet e chave BackgroundEmail
    - Trocar o seu valor para True
  - Localizar o parâmetro da seção REST e chave Email
    - Trocar o seu valor para http://IP-SERVIDOR-LINUX:9999/. Exemplo: http://192.168.1.52:9999/

4. Realizar envio de email pelo Korp, e verificar que o email é recebido corretamente

A responsabilidade da validação e garantia do funcionamento do novo ambiente fica de responsabilidade do cliente
================================================================================================================
 
Após a leitura e compreensão, por gentileza encaminhe um email confirmando o entendimento de todos os tópicos abordados.

Quais queres dúvidas, estamos à disposição. 