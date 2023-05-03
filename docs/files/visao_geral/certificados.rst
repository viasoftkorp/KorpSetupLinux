Certificados
------------

O portal local suporta 3 modalidades de certificados:

    - AutoAssinado

    - Customizado

    - Automatizado com Let's Encrypt

O certificado será utilizado para certificar os :doc:`3 DNSs utilizados pelo portal <./dns>`

Por padrão o certificado AutoAssinado é utilizado, mas isso pode ser customizado durante a instalação do ambiente

----

    Características dos certificado:

+--------------------------------+------------------------------------------+-------------------------------------------------------------------------------------------------------------+---------------------------------------------------------------------------------+
| Tipo                           | Requisitos                               | Características                                                                                             | Contras                                                                         |
+================================+==========================================+=============================================================================================================+=================================================================================+
| AutoAssinado                   | - Nenhum                                 | - Certificadora raiz está no próprio servidor Linux.                                                        | - Certificado raiz deve ser importada manualmente em todas as estações, ou em AD|
|                                |                                          |                                                                                                             |                                                                                 |
|                                |                                          | - Certificado renovado automaticamente a cada 12 meses                                                      |                                                                                 |
+--------------------------------+------------------------------------------+-------------------------------------------------------------------------------------------------------------+---------------------------------------------------------------------------------+
| Customizado                    | - Domínio próprio                        | - Cliente deve prover os arquivos de certificado (certificado, chave e senha)                               | - O Certificado deve ser comprado                                               |
|                                |                                          |                                                                                                             |                                                                                 |
|                                | - IP externo fixo                        | - Renovação do certificado é de responsabilidade do cliente                                                 | - Certificado deve ser manualmente atualizado quando expirar                    |
|                                |                                          |                                                                                                             |                                                                                 |
|                                | - Certificado próprio                    |                                                                                                             |                                                                                 |
+--------------------------------+------------------------------------------+-------------------------------------------------------------------------------------------------------------+---------------------------------------------------------------------------------+
| Automatizado com Let's Encrypt | - Domínio próprio                        | - Certificado gerado com a certificadora Let's Encrypt                                                      | - Nenhum                                                                        |
|                                |                                          |                                                                                                             |                                                                                 |
|                                | - IP externo fixo                        | - Certificado renovado automaticamente a cada 3 meses                                                       |                                                                                 |
|                                |                                          |                                                                                                             |                                                                                 |
|                                | - Email para cadastro no Let's Encrypt   |                                                                                                             |                                                                                 |
+--------------------------------+------------------------------------------+-------------------------------------------------------------------------------------------------------------+---------------------------------------------------------------------------------+

----


Certificado AutoAssinado
========================

O certificado AutoAssinado é o utilizado por padrão.

Nessa modalidade, é criada uma entidade certificadora no próprio servidor linux, que irá provisionar os certificados para os DNSs do portal.

Esse certificado tem validade de 12 meses, e será renovado automaticamente.

Como a entidade certificadora raiz está no próprio servidor linux o seu certificado (ca-cert.crt) deve ser identificado como um certificado válido por todas as estações de trabalho que irão utilizar o Korp, ou o portal local.

Importando o certificado AutoAssinado
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Após a instalação do ambiente, o certificado da CA pode ser obtido copiando o arquivo ``ca-cert.crt`` que está disponível na ``home`` do usuário que foi disponibilizado para instalação no servidor Linux.

Há duas opções disponíveis para a importação da CA:

    - O cliente tem AD e disponibiliza a CA via política
 
    - O cliente importa manualmente em cada estação de trabalho a CA via o comando ``certutil.exe -addstore root C:\temp\ca-cert.crt``

.. note:: 
  
    Após importar a CA, é necessário fechar completamente o navegador e recarregar a página caso a mesma abra sozinha novamente.


Certificado Customizado
=======================

Para utilizar o certificado customizado, é necessário:

    - IP externo fixo

    - 3 DNSs apontando para o IP externo da empresa

    - Direcionamento interno dos DNSs, nas portas 80 e 443, para o servidor Linux

    - Arquivos de certificado válido para os 3 DNSs do portal local

        - Arquivo contendo o certificado (cert.crt)

        - Arquivo chave do certificado (cert.key)

        - Arquivo contendo senha do certificado, caso exista (cert.pass)

.. warning::

    Certificados tem um tempo de expiração, antes do certificado expirar ele deve ser renovado.

    **Nessa modalidade, a responsabilidade desse processo é do cliente.**

Renovando o certificado
~~~~~~~~~~~~~~~~~~~~~~~

#. Copiar o arquivo ``cert.crt`` para o diretório ``/etc/korp/certs/certs``

#. Executar o script ``/etc/korp/scripts/cert_renew.sh``

#. Garantir que o script rodou com sucesso

#. Testar o acesso ao portal local


Certificado Automatizado com Let's Encrypt
==========================================

Nessa modalidade, o certificado é gerando utilizando a certificadora `Let's Encrypt`_, por meio da ferramenta `Certbot`_.

O certificado gerado é validado pelo desafio ``http-01``, e tem validade de 3 meses.

É necessário um email para gerar o certificado por meio do Let's Encrypt, esse email será utilizado para enviar notificações sobre o certificado.

O renovação do certificado é feita automaticamente quando necessário.

Para utilizar o certificado automatizado, é necessário:

    - IP externo fixo

    - 3 DNSs apontando para o IP externo da empresa

    - Direcionamento interno dos DNSs, nas portas 80 e 443, para o servidor Linux


.. _Let's Encrypt: https://letsencrypt.org
.. _`Certbot`: https://certbot.eff.org