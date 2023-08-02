Atualizando versão  do Korp
---------------------------

Os servidores do korp trabalham com uma ou mais versões instaladas simultaneamente, 
dessa maneira quando uma nova versão estiver em Homologação não tera impacto em Produção.  

Servidor Linux
==============

#. Acessar o `Portal da Korp`_ com o email administrador.

#. Aplicativo Monitor de Licenças, opção `Configurações`.

    - Configuração do servidor de aplicação Linux.

    - Selecione a versão e clique no botão `Gerar comando para atualização de versão`.
    
    - O comando de instalação será copiar para a área de transferência do Windows.  


#. Conectar no servidor Linux, executar o comando de atualização.


Servidor Windows
================


#. Acessar o `Portal da Korp`_ com o email administrador.

#. Aplicativo Área do Cliente.

    - Baixar os instaladores: ``KorpSetup_Installer_****.*.exe`` e ``KorpRelease-****.*.exe``.

#. Servidor de Aplicação Windows 

    -  Instalar: ``KorpSetup_Installer_****.*.exe``.

    -  Instalar: ``KorpRelease-****.*.exe``

        -  Copiar o instalador ``KorpRelease-****.*.exe`` para a pasta de homologaçào e executar. 
        -  Apos finalizar a instalação, conectar no Korp com um usuário administrador para atualização da base.

#. Após a atualização da base, reiniciar os seguintes serviços nessa ordem, separadamente:

        -  Viasoft.Tenantmanagement

        -  Viasoft.Administration


.. _Portal da Korp: https://portal.korp.com.br