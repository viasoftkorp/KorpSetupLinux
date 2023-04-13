Disponibilizando o Portal local externamente (na internet)
----------------------------------------------------------

Para disponibilizar o portal local em rede externa são necessários alguns procedimentos que serão descritos nesse tutorial.

É importante lembrar que os requisitos especificados nessa página são de responsabilidade do cliente.

----

Requisitos
==========

Abaixo estão as premissas para o Portal funcionar publicado na internet:

- DNS

- Certificado

- NAT (direcionamento das requisições externas para a rede interna)


É importante ressaltar que o Portal **não** poderá ser acessado diretamente pelo IP externo da empresa.

Após os requisitos estiverem cumpridos, o cliente deverá copiar os arquivos de certificado para o servidor Linux.

----

DNS
###

O ambiente do portal web interno é acionado por três DNS, e portanto para acessar o ambiente externamente será necessário o registro deles.
O cliente poderá escolher os nomes que quiser, desde que sejam três distintos.

A sugestão de DNS da Korp para utilização é:

    - ``portal.<domínio>``
    - ``portal-api.<domínio>``
    - ``portal-cdn.<domínio>``

Por exemplo, caso o domínio fosse ``.empresa.com.br``, os DNS ficariam:

    - ``portal.empresa.com.br``
    - ``portal-api.empresa.com.br``
    - ``portal-cdn.empresa.com.br``

Os três DNS devem resolver para o IP externo da empresa.

Certificado
###########

O ambiente do portal web utiliza HTTPS (http sobre SSL) e portanto precisa de um certificado digital para funcionar.
O certificado digital deverá ser comprado ou gerado manualmente via certificadoras `gratuitas`_.

O certificado digital deverá atender aos três DNS definidos pelo cliente.

NAT
###

O cliente deverá configurar o direcionamento da rede externa para o servidor de aplicação Linux.
As requisições chegarão na porta 443 e deverão ser encaminhadas para o servidor Linux na porta 443.

.. _gratuitas: https://letsencrypt.org/