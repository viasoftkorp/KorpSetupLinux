Infraestrutura pós implantação
------------------------------

A Infraestrutura interna é altera após a implantação e migração do servidor Linux. Essa pagina irá explica a estrutura antes e depois.

Infraestrutura pré implantação
==============================

Esse tópico aborda o ambiente de clientes que fazem uso do Korp antes da implantação do servidor Linux, apenas com o servidor aplicações Windows.

.. image:: ../images/infraestrutura_pre_implantacao.png
    :width: 600

A cima esta um diagrama exemplificando o fluxo de comunicação entre o Korp e os os serviços instalados no servidor Windows.

- Configuração do Korp

    No config.json do Korp, é definindo a propriedade ``GatewayIp`` com o IP do servidor Windows, e ``GatewayPort`` com '1504', ou seja, a porta do gateway do servidor Windows.

- Serviços da Korp rodando no servidor Windows

    Entre os serviços Instalados no servidor Windows estão:

        - ``ViasoftKorpLicenseServer`` (Servidor de Licenças)
        - ``ViasoftKorpGateway`` (Gateway)
        - ``ViasoftKorpAuditTrail``
        - ``ViasoftKorpSystemUpdate``
        - ``ViasoftKorpNotification``
        - ``ViasoftKorpStorageServer``
        - ``ViasoftKorpObjectStorage``
        - ``ViasoftKorpConsul``
        - ``ViasoftKorpReportingStimulsoft``

        - ``KorpCadastrosServices``
        - ``KorpDataServerServices``
        - ``KorpFaturamentoEmissaoNotaFiscalLegacyServices``
        - ``KorpFaturamentoEmissaoNotaFiscalServices``
        - ``KorpFinanceiroEmailCobrancaServices``
        - ``KorpLogisticaServices``
        - ``KorpVendasServices``

- Bancos de Dado do SQL Server

    Os únicos bascos utilizados pelo Korp são as bases do cliente, sedo geralmente duas, uma de homologação, e uma de produção.


Infraestrutura após a implantação
=================================

Esse tópico aborda o ambiente do cliente após a implantação e migração do servidor de aplicações Linux.

.. image:: ../images/infraestrutura_pos_implantacao.png
    :width: 600

O diagrama a cima exemplificando o fluxo de comunicação entre o Korp, o servidor de aplicações Linux, e o servidor de Aplicações Windows.

- Configuração do Korp

    No config.json do Korp, é definindo a propriedade ``GatewayIp`` com o IP do servidor Linux, e ``GatewayPort`` com '9999', ou seja, a porta do gateway do servidor Linux.


- Serviços da Korp rodando no servidor Windows

    Entre os serviços Instalados no servidor Windows estão:

        - ``ViasoftKorpLicenseServer`` (Servidor de Licenças)
        - ``ViasoftKorpGateway`` (Gateway)

        - ``KorpCadastrosServices``
        - ``KorpDataServerServices``
        - ``KorpFaturamentoEmissaoNotaFiscalLegacyServices``
        - ``KorpFaturamentoEmissaoNotaFiscalServices``
        - ``KorpFinanceiroEmailCobrancaServices``
        - ``KorpLogisticaServices``
        - ``KorpVendasServices``

- Serviços da Korp rodando no servidor Linux

    Entre os serviços Instalados no servidor Linux estão:

        - ``fabio`` (Gateway)
        - ``Viasoft.Audittrail.Client``
        - ``Viasoft.SystemUpdate``
        - ``Viasoft.Notification``
        - ``Viasoft.ObjectStorage.Client``
        - ``Viasoft.Reporting.Stimulsoft``
        - ``Korp.Legacy.Authentication``
        - ``Viasoft.Email``

.. note::
    Uma parte dos serviços que antes estavam no servidor de aplicações Windows, são agora migrados para o servidor de aplicações Linux.

        De forma geral, todos os serviços ``ViasoftKorp*`` são migrados para o servidor Linux, com exceção de ``ViasoftKorpLicenseServer`` e ``ViasoftKorpGateway``
    
    No Servidor Linux, além 




