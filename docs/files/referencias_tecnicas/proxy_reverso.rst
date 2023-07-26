Proxy Reverso
-------------

No servidor linux há um proxy reverso sendo operado pelo servidor HTTP Nginx, com o objetivo de direcionar as requisições para os serviços adequados. As requisições são roteadas conforme os três DNS utilizados pelo portal.

Por padrão, esse proxy reverso também é responsável pela aplicação do SSL nos DNSs.

Caso o cliente deseje, e sua infraestrutura interna permita, a aplicação do SSL nos DNSs pode ser feita por um proxy do próprio cliente, direcionando as chamadas http (sem ssl) para o servidor Linux.
