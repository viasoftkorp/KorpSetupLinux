Endereços utilizados pelo servidor Linux
----------------------------------------

Endereços de saída utilizados pelo servidor Linux na porta 443
==============================================================

    - ``api-erp.korp.com.br``
    - ``api-web.korp.com.br``
    - ``gateway.korp.com.br``
    - ``minio-api.korp.com.br``
    - ``production.cloudflare.docker.com``
    - ``registry-1.docker.io``
    - ``hub.docker.com``
    - ``login.docker.com``
    - ``cdn.auth0.com``
    - ``auth.docker.io``

..
    lista do docker pega de https://docs.docker.com/desktop/allow-list/


Endereços de entrada
====================


Quando o IP fixo do cliente tiver sido configurado para receber chamadas da nuvem da Korp, os seguintes endereços farão requisições para a rede do cliente na porta ``9999``

    .. Quando o ``Endereço de entrada`` estiver configurado no licenciamento do cliente, os seguintes endereços farão requisições para a rede do cliente na porta ``9999``

    - ``168.138.251.22``
    - ``152.67.48.227``
    - ``152.67.49.65``
    - ``150.230.73.114``

As chamadas vindas desses IPs, na porta ``9999`` devem ser redirecionadas para o IP do servidor Linux, na porta ``9999``
