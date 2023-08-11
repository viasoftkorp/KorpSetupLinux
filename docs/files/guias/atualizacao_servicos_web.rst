.. Doc não é mais utilizado
    Atualizando versão do Korp
    --------------------------

    Para atualizar a versão do Korp, é necessário atualizar a versão dos serviços no servidor de aplicações Linux, Windows, e a versão da base.

    Esse tópico irá abordar a atualização desses 3 componentes.

    .. note:: 

        Assim como no servidor de aplicações Windows, no servidor Linux os serviços poder estar instalados em mais de uma versão ao mesmo tempo, dessa maneira, pode-se homologar uma nova versão, sem afetar o funcionamento do ambiente de produção.


    Atualizando o Servidor Linux
    ============================

    #. Acessar o `Portal da Korp`_ com o email administrador.

    #. Entrar no aplicativo 'Monitor de Licenças'.

    #. No menu da lateral esquerda, clicar em 'Configurações'.

    #. Em 'Configuração do servidor de aplicação Linux':

        - Selecionar a versão desejada, e clicar no botão ``Gerar comando para atualização de versão``.
        
        - O comando de instalação será copiado para a área de transferência.

    #. Conectar no servidor Linux(pelo virtualizador, ou ssh).

    #. Colar e executar o comando de atualização gerado no passo '4'.

    #. O Comando deve finalizar sua execução sem nenhum erro.


    Atualizando o Servidor Windows
    ==============================

    #. Acessar o `Portal da Korp`_ com o email administrador.

    #. Entrar no aplicativo 'Área do Cliente'.

    #. Fazer o download instaladores:

        - ``KorpSetup_Installer_<versão>.exe``
        
        - ``KorpRelease-<versão>.exe``.

    #. No servidor de Aplicação Windows, executar os instaladores baixados no passo anterior.

        -  Serviços: ``KorpSetup_Installer_<versão>.exe``.

        -  Korp: ``KorpRelease-<versão>.exe``

            .. -  Copiar o instalador ``KorpRelease-<versão>.exe`` para a pasta de homologaçào e executar. 
            .. -  Apos finalizar a instalação, conectar no Korp com um usuário administrador para atualização da base.

    #. Acessar o Korp da nova versão com um usuário administrador, e realizar a atualização da base.

    #. Após a atualização da base, :doc:`reiniciar os serviços no servidor Linux <./guia_portainer>` , nessa ordem, separadamente:

        -  Viasoft.Tenantmanagement

        -  Viasoft.Administration


    .. _Portal da Korp: https://portal.korp.com.br
