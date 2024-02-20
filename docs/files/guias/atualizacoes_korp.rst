Atualizando versão do Korp
--------------------------

    Para atualizar a versão do Korp, é necessário atualizar a versão dos serviços Korp, versão das bases e servidor de aplicações Linux.
    Esse tópico irá abordar a atualização desses 3 componentes.

Homologação
===========

#. Atualizando serviços Korp
    
    - Acessar a Área do Cliente e baixar a Atualização do serviços Delphi ``KorpSetup_Installer_****.*.exe``.
    - Instalar os serviços Korp ``KorpSetup_Installer_****.*.exe`` no servidor de Aplicação Windows.

#. Atualizando versão do Korp

    - Acessar a Área do Cliente e baixar a Atualização do Korp "KorpRelease-****.*.exe".
    - Executar a Atualização do Korp ``KorpRelease-****.*.exe`` na pasta de Homologação.
    - Conectar no Korp com um usuário administrador para atualizar a base.

#. Atualizando servidor de aplicações Linux
 
    - Abrir um chamado no Movidesk solicitando a atualização do Servidor Linux, informando a versão que deseja atualizar.

Produção
========

#. Atualizando versão do Korp
 
    - Executar a Atualização do Korp ``KorpRelease-****.*.exe`` na pasta de Produção.
    - Conectar no Korp com um usuário administrador para atualizar a base.

#. Reiniciando serviços WEB
 
    - Acessar o endereço ``http://<dns_frontend>:9011``
        
        - Usuário: admin - Senha: korp!4518
    
    - Reiniciar os containers
        
        - Viasoft.Tenantmanagement
        - Viasoft.Administration

