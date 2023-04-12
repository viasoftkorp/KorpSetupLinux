Disponibilizando o portal local Externamente
--------------------------------------------



Para disponibilizar o portal local em rede externa são necessários alguns procedimentos, que serão descritos nesse tutorial.

É importante reforçar que essa configuração não é de responsabilidade da korp, mas sim do cliente.


.. Requisitos
.. ==========

..  - domínio resolvendo para a rede do 

Disponibilização de DNSs
========================

O ambiente do portal web é acionado por três DNSs.
Para acessar o ambiente externamente, faz-se também necessário três DNSs, porém externos.

**Assim como no ambiente local, os DNSs devem ser criados em cima de um certificado.**

O padrão de DNS sugerido é:

    - ``portal.<domínio>``
    - ``portal-api.<domínio>``
    - ``portal-cdn.<domínio>``

Por exemplo, caso o domínio fosse ``.empresa.com.br``, os DNSs ficariam:

    - ``portal.empresa.com.br``
    - ``portal-api.empresa.com.br``
    - ``portal-cdn.empresa.com.br``

Os três DNS devem resolver para o IP externo privado da empresa.


Resolução interna dos DNSs
==========================

Deve haver um direcionamento no firewall da rede, direcionando os 3 DNSs do passo anterior para o servidor de aplicações Linux.

Para configuração de proxy reverso, será utilizado o software Nginx

Configuração Nginx
##################

#. Acesse o servidor de aplicações Linux

#. Acesse o diretório ``/etc/korp/certs``

#. Crie a pasta ``external-portal``

#. Adicione os arquivos de certificado ``cert.crt`` e ``cert.key`` na pasta ``external-portal``

    - Caso seu certificado tenha o arquivo ``.pass``, adicione também nessa pasta com o nome ``cert.pass``

#. Crie um arquivo com o nome ``external-portal.conf`` no diretório ``/etc/korp/configs/nginx/conf.d/``

    O arquivo deverá ter a seguinte estrutura:

    .. code-block:: 
        
        server {

            server_name portal.<domínio>;

            listen  443 ssl;

            # Caminho para os arquivos de certificado dentro do container do nginx
            # O caminho '/etc/nginx/certs/' é equivalente à '/etc/korp/certs/' no servidor
            ssl_certificate     /etc/nginx/certs/external-portal/cert.crt;
            ssl_certificate_key /etc/nginx/certs/external-portal/cert.key;
            # caso seu certificado tenha um arquivo de senha, remover o comentário da linha abaixo
            # ssl_password_file   /etc/nginx/certs/external-portal/cert.pass;

            location / {
                proxy_set_header X-Real-IP $remote_addr;
                proxy_set_header X-Forwarded-For $remote_addr;
                proxy_set_header Host $host;
                proxy_pass https://korp.local;
            }
        }

        server {

            server_name portal-api.<domínio>;

            listen  443 ssl;

            # Caminho para os arquivos de certificado dentro do container do nginx
            # O caminho '/etc/nginx/certs/' é equivalente à '/etc/korp/certs/' no servidor
            ssl_certificate     /etc/nginx/certs/external-portal/cert.crt;
            ssl_certificate_key /etc/nginx/certs/external-portal/cert.key;
            # caso seu certificado tenha um arquivo de senha, remover o comentário da linha abaixo
            # ssl_password_file   /etc/nginx/certs/external-portal/cert.pass;

            location / {
                proxy_set_header X-Real-IP $remote_addr;
                proxy_set_header X-Forwarded-For $remote_addr;
                proxy_set_header Host $host;
                proxy_pass https://korp-api.local;
            }
        }

        server {

            server_name portal-cdn.<domínio>;

            listen  443 ssl;

            # Caminho para os arquivos de certificado dentro do container do nginx
            # O caminho '/etc/nginx/certs/' é equivalente à '/etc/korp/certs/' no servidor
            ssl_certificate     /etc/nginx/certs/external-portal/cert.crt;
            ssl_certificate_key /etc/nginx/certs/external-portal/cert.key;
            # caso seu certificado tenha um arquivo de senha, remover o comentário da linha abaixo
            # ssl_password_file   /etc/nginx/certs/external-portal/cert.pass;

            location / {
                proxy_set_header X-Real-IP $remote_addr;
                proxy_set_header X-Forwarded-For $remote_addr;
                proxy_set_header Host $host;
                proxy_pass https://korp-cdn.local;
            }
        }

    - Substitua ``<domínio>`` pelo seu domínio

    - Casso seu certificado tenha um arquivo de senha ``.pass``, remova os 3 comentários indicados.

#. Reinicie o container de nome ``nginx``

    - :doc:`Como reiniciar serviços </files/guias/guia_portainer>`
