Proxy Reverso
-------------

No servidor linux há um proxy reverso sendo operado pelo servidor HTTP Nginx, com o objetivo de direcionar as requisições para os serviços adequados. As requisições são roteadas conforme os três DNS utilizados pelo portal.

Por padrão, esse proxy reverso também é responsável pela aplicação do SSL nos DNSs.

Caso o cliente deseje, e sua infraestrutura interna permita, a aplicação do SSL nos DNSs pode ser feita por um proxy do próprio cliente, direcionando as chamadas http (sem ssl) para o servidor Linux.

O proxy reverso deve fazer o direcionamento dos três DNSs pra os seguintes endereços:


 - ``https://korp.local`` -> ``http://<IP_Servidor_Linux>:9877``
 - ``korp-api.local`` -> ``IP-Linuxlinux:9875``
 - ``korp-cdn.local`` -> ``IP-Linuxlinux:9876``

.. note::

    Note que o certificado e validado pelo proxy reverso do cliente tendo direcionado sem SSL para o servidor Linux

.. raw::


----