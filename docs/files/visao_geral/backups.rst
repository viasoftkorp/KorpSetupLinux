Backups
-------

.. warning::
    **A garantia dos Backups é de responsabilidade do cliente**


Servidor Linux
==============

O dados usados pelas aplicações da korp, estão todos no disco de dados, montado em ``/etc/korp``

Apenas o backup do disco de dados, já garante segurança dos dados. Porém recomendamos também um backup do disco em que o sistema operacional está instalado, para maior facilidade em caso de necessidade de restauração da maquina.


SQL Server
==========

É necessário backup de todos os bancos usados pelo korp. Isso incluí todas as bases do clientes(produção e homologação), e os bancos com o prefixos ``Viasoft``. 
