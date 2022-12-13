Homologando o servidor Linux
----------------------------

Após a implantação do servidor Linux, é necessário fazer sua homologação, ou seja, garantir que o sistema está funcionando normalmente antes de ser utilizado em produção.  

Após o período de homologação, é feita então a migração do servidor de Aplicações Windows para o servidor de Aplicações Linux.  

.. warning::

   - O objetivo dessa homologação **não** é validar os processos de negócio da nova versão instalada. Esses testes tem como intuito somente testar os componentes instalados no Linux. 

   - É necessário seguir todos os passos do tutorial :doc:`/files/tutoriais/configuracao_ambiente` antes de dar sequência na homologação.

----

Homologando o portal local
##########################

É importante lembrar que as permissões do Korp ERP não se aplicam ao ambiente WEB, portanto para o primeiro acesso terá que utilizar o login do usuário raiz do licenciamento do e-mail.

Para confirmar o login desse usuário, pode-se acessar o https://portal.com.com.br, pelo aplicativo de Admin.

Para a homologação do portal local, deve-se fazer o uso dos aplicativos licenciados.

Caso ainda não esteja ambientado com portal assista o vídeo abaixo que abordara entre outros assuntos, como autorizar usuários a terem acessos aos aplicativos (min 02:30).

.. note:: 
  
    No video é abordado o gerenciamento de autorizações e permissões no Portal Nuvem, nesse caso faça as alterações pelo Portal Local.
    O gerenciamento de usuários contudo, ainda é feito pelo `Portal Nuvem <https://portal.korp.com.br>`_.

.. raw:: html

    <iframe width="560" height="315" src="https://player.vimeo.com/video/569973315" frameborder="0" allowfullscreen></iframe>


----

Homologando o Korp
##################

#.  Nas estações de trabalho, realizar as seguintes alterações no arquivo ``config.json``
  
    - Alterar a propriedade ``GatewayIp`` para o IP do servidor LINUX.
    - Alterar a propriedade ``GatewayPort`` para a ``9999``.

#. Verificar que é possível realizar o login

#. Verificar que as notícias na tela inicial aparecem corretamente

#. Configurar os parâmetros de servidor de e-mail (não esqueça de realizar o logout e login após altera-los):
  
    - Localizar o parâmetro da seção Internet e chave BackgroundEmail

        - Trocar o seu valor para True

    - Localizar o parâmetro da seção REST e chave Email

        - Trocar o seu valor para http://IP-SERVIDOR-LINUX:9999/. Exemplo: http://192.168.1.52:9999/

#. Realizar envio de email pelo Korp, e verificar que o email é recebido corretamente
