Backups
-------

.. warning::
    **A garantia dos Backups é de responsabilidade do cliente**


Servidor Linux
==============

Todos os dados utilizados pelo Korp estão armazenados no disco de dados, montado em ``/etc/korp``, incluindo os bancos de dados. Dessa forma, ao realizar o backup desse disco, a integridade e segurança das informações já estarão asseguradas, sem a necessidade de interromper nenhum serviço.
 
O backup do disco de dados garante a proteção das informações essenciais. No entanto, recomendamos também a criação de um backup do disco onde o sistema operacional está instalado, para facilitar a restauração da máquina, caso necessário.


SQL Server
==========

É necessário backup de todos os bancos usados pelo korp. Isso incluí todas as bases do clientes(produção e homologação), e os bancos com o prefixos ``Viasoft``. 
