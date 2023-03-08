Especificações do servidor Linux
--------------------------------

Essa pagina irá abordar os requisitos de hardware e software necessários para instalação dos serviços da Korp no servidor Linux.

Requisitos mínimos
==================

Abaixo estão os requisitos mínimos do servidor, sendo que estes poderá ser necessário maior capacidade da máquina dependendo do volume de dados, e dos aplicativos licenciados.

* Linux Ubuntu Server versão 22.04 (sem interface gráfica) (`link para download da iso`_)

* 4GB de memória RAM

* Disco de boot no tamanho de 30GB

* Disco de dados no tamanho de 10GB (O disco de dados não deve conter partição ou mountpoint, visto que esses serão criados automaticamente durante a configuração do servidor)

* 2 cores de processamento.

Para garantir quais as especificações recomendas em cada caso, é necessário consultar a equipe de implantação.

.. warning::

  * Nome de Usuário e Servidor Linux NÃO pode ser KORP.

  * Servidor Linux deve estar configurado com IP fixo.

  * Nenhuma máquina na rede pode ter o nome ``korp``, visto que isso irá causar problemas na resolução do dns ``korp.local``

.. _link para download da iso: https://releases.ubuntu.com/22.04.1/ubuntu-22.04.1-live-server-amd64.iso?_ga=2.86747416.1489760255.1670338166-1583241791.1655810833