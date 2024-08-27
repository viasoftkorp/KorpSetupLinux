Objectstorage servidor Linux
---------------------------------------------

Esta pagina aborda o passo a passo para manter ou remover as imagem nos Cadastro de Produto no ambiente de homologação.


Mantendo imagem do Cadastro de Produto no ambiente de Homologação
====================================================================

Após restaurar a base de homologação, executar os seguintes passos. 

Servidor Linux:
```````````````
        #. Conectar no servidor Linux.

                .. code-block:: bash

			        IP: ***.***.***.*** - Usuário: ***** - Senha: *****

        #. Conectar com o usuário root.
		
                .. code-block:: bash
                    
                    sudo su

        #. Verificar tamanho da pasta PRD.

                .. code-block:: bash
                    
                    du -sh /etc/korp/dados-docker/minio-server/<Tenant_Id>/<BASE_PRD>/ | sort -hr

        #. Remover arquivos da pasta BASE_HMLG.	

                .. code-block:: bash
                    
                    rm -rf /etc/korp/dados-docker/minio-server/<Tenant_Id>/<BASE_HMLG>/*

        #. Verificar se á espaço no disco de dados.

                .. code-block:: bash
                    
                    df -h

        #. Copiar os arquivos da BASE_PRD para BASE_HMLG

                .. code-block:: bash

                    cp -r /etc/korp/dados-docker/minio-server/<Tenant_Id>/<BASE_PRD>/* /etc/korp/dados-docker/minio-server/<Tenant_Id>/<BASE_HMLG>/


.. note::
    ATENÇÃO: Trocar <Tenant_Id> pelo tenant da empresa, <BASE_PRD> pelo nome da base de produção e <BASE_HMLG> pelo nome da base de homologação.

Servidor Windows
````````````````

		- Executar script no SQLServer

                .. code-block:: SQL

					USE [@@BASE_HMLG]
					UPDATE objectstorage_files SET database_name = '@@BASE_HMLG'

.. note::
    ATENÇÃO: trocar onde está @@BASE_HMLG pelo nome da base de dados de homologação


----

Remover imagem do Cadastro de Produto do ambiente de Homologação
===================================================================

Após restaurar a base de homologação, executar os seguintes passos. 

Servidor Linux:
```````````````
        #. Conectar no servidor Linux.

                .. code-block:: bash

			        IP: ***.***.***.*** - Usuário: ***** - Senha: *****

        #. Conectar com o usuário root.
		
                .. code-block:: bash
                    
                    sudo su

        #. Remover arquivos da pasta BASE_HMLG.	

                .. code-block:: bash
                    
                    rm -rf /etc/korp/dados-docker/minio-server/<Tenant_Id>/<BASE_HMLG>/*

Servidor Windows
````````````````

		- Executar script no SQLServer

                .. code-block:: SQL
            
                    USE [@@BASE_HMLG]
                    UPDATE objectstorage_files SET database_name = '@@BASE_HMLG'
                    DELETE FROM ESTOQUE_IMAGEM

.. note::
    ATENÇÃO: trocar onde está @@BASE_HMLG pelo nome da base de dados de homologação
