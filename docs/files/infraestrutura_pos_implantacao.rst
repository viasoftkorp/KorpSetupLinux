Infraestrutura pós implantação
------------------------------

A Infraestrutura interna é altera após a implantação e migração do servidor Linux. Essa pagina irá explica a estrutura antes e depois.

Infraestrutura pré implantação
==============================

Esse tópico aborda o ambiente de clientes que já tem o Korp antes da implantação do servidor Linux. Ou seja, apenas com o servidor aplicações Windows.

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

    Apenas as bases do cliente, sedo geralmente duas, uma de homologação, e uma de produção.


Infraestrutura após a implantação
=================================