Virada do servidor Windows para o Servidor Linux
------------------------------------------------

Apos a homologação do servidor Linux, e garantia de seu funcionamento, o cliente deve contatar a equipe de implantação informando o desejo de fazer a virada dos servidores.

O procedimento de virada consistem e migrar os serviços ``Viasoft`` do servidor de aplicações Windows para o servidor de aplicações Linux.

.. warning::

    Durante o processo de virada, alguns serviços utilizados pelo Korp serão migrados para o servidor Linux, fazendo com que o Korp não funcione.

Pré requisitos da virada
========================

- Homologação da versão que será usada

- Alterar config.json em todas as estações do Korp

- Importar certificado em todas as estações que iram usar o portal web

- Configurar os DNSs


Responsabilidades do cliente durante a virada
=============================================

- Atualização da base do Korp

    Caso a base usada pelo Korp já estava na versão que sera usada, nenhuma ação precisa ser tomada


Responsabilidades da Korp durante a virada
===========================================

Após a base do Korp estar na versão correta, a equipe de implantação irá migrar os serviços Viasoft do servidor Windows para o Linux, e realizar as configurações necessárias


Responsabilidades do cliente após a virada
==========================================

- Permitir/alterar o direcionamento do DNS para o servidor Linux.

    Atualmente deverá ter um direcionamento do endereço de entrada para o servidor Window na porta 1504, esse direcionamento será alterado para o servidor Linux na porta 9999.

    Testando a alteração:

        Acessar https://portal.korp.com.br, e alterar/criar algum usuário.

        As alterações devem ser vistas no portal local.

- Testar as estações do Korp, conforme o uso da empresa.
