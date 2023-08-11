Disponibilizando atualização do Korp no servidor Linux
------------------------------------------------------

Esse tutorial também pode ser visualizado pelo vídeo `Disponibilizando atualização do Korp no servidor Linux`_,

#. Edite os arquivos conforme o necessário(o mesmo procedimento que já é feito hoje no servidor Windows).

#. Copiar os arquivos editados para o servidor Linux.

    - Utilize uma ferramenta de cópia de arquivos por SSH qualquer, nós recomendamos o uso de `Filezila`_, mas qualquer ferramenta pode ser utilizada.

    ..
        Explicar como conectar no servidor com filezila.

    - Copiar os arquivos ``Octopus.inf`` e ``OctopusUpdate.exe`` para a home do usuário.
    
    - Conectar por SSH no servidor Linux, e executar o seguinte comando para transferir os arquivos da home do usuário, para o diretório ``/etc/korp/atualizacao-sistema/``:

        .. code-block:: bash

            sudo cp Octopus.inf /etc/korp/atualizacao-sistema/ &&  sudo cp OctopusUpdate.exe /etc/korp/atualizacao-sistema/

    .. warning:: 

        **Linux é Case Sensitive.**

        Ou seja ``Octopus.inf`` é diferente de ``octopus.INF``

        Os arquivos **DEVEM** ter exatamente os seguintes nomes:

            - ``Octopus.inf``
            - ``OctopusUpdate.exe``

    - Para validar que os aquivos estão no lugar certo, o seguinte comando pode ser utilizado:

        .. code-block:: bash

            sudo ls /etc/korp/atualizacao-sistema/

        Os dois arquivos copiados devem aparecer como retorno do comando.

.. _Disponibilizando atualização do Korp no servidor Linux: https://vimeo.com/766215305/a44f763c1a
.. _Filezila: https://filezilla-project.org/download.php#close