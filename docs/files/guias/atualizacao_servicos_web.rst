
Atualizando versão do Korp
--------------------------

Para atualizar a versão do Korp, é necessário atualizar a versão dos serviços no servidor de aplicações Linux, Windows, e a versão da base.

Esse tópico irá abordar a atualização desses 3 componentes.

.. note:: 

    Assim como no servidor de aplicações Windows, no servidor Linux os serviços poder estar instalados em mais de uma versão ao mesmo tempo, dessa maneira, pode-se homologar uma nova versão, sem afetar o funcionamento do ambiente de produção.


Servidor Linux
==============

#. Acessar o `Portal da Korp`_ com o email administrador.

    - Aplicativo 'Monitor de Licenças'.

    - No menu da lateral esquerda, clicar em 'Configurações'.

    - Em 'Configuração do servidor de aplicação Linux' - Selecionar a versão desejada, e clicar no botão ``Gerar comando para atualização de versão``.
    
.. note::
    ATENÇÃO: O comando de instalação será copiado para a área de transferência.

#. Conectar no servidor Linux pelo (virtualizador ou ssh).

    -  Colar e executar o comando de atualização gerado no passo '4'.

    - O Comando deve finalizar sua execução sem nenhum erro.


Servidor Windows
================


Atualizando serviços Korp
`````````````````````````

#. Portal da Korp

    - Acessar a Área do Cliente e baixar a Atualização do serviços Korp ``KorpSetup_Installer_****.*.exe``.
    - Instalar os serviços Korp ``KorpSetup_Installer_****.*.exe`` no servidor de Aplicação Windows.


Atualizando versão do Korp - Homologação
`````````````````````````````````````````

#. Portal da Korp

    - Acessar a Área do Cliente e baixar a Atualização do Korp "KorpRelease-****.*.exe".
    - Executar a Atualização do Korp ``KorpRelease-****.*.exe`` na pasta de Homologação.
    - Conectar no Korp com um usuário administrador para atualizar a base.

#. Serviços WEB
 
    - Acessar o endereço ``http://<dns_frontend>:9011``
        
        - Usuário: admin - Senha: korp!4518
    
    - Reiniciar os containers
        
        - Viasoft.Tenantmanagement
        - Viasoft.Administration

Atualizando versão do Korp - Produção
`````````````````````````````````````````

#. Portal da Korp

    - Executar a Atualização do Korp ``KorpRelease-****.*.exe`` na pasta de Produção.
    - Conectar no Korp com um usuário administrador para atualizar a base.

#. Serviços WEB
 
    - Acessar o endereço ``http://<dns_frontend>:9011``
        
        - Usuário: admin - Senha: korp!4518
    
    - Reiniciar os containers
        
        - Viasoft.Tenantmanagement
        - Viasoft.Administration

.. _Portal da Korp: https://portal.korp.com.br
