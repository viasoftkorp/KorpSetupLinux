Gerenciando serviços no Servidor Linux
--------------------------------------

O gerenciamento dos serviços Korp que rodam no servidor Linux pode ser feito por meio da ferramente **Portainer**.

Seu acesso pode ser feito por meio do endereço ``http://<dns_frontend>:9011``

As credenciais de acesso são:

    - usuário: ``admin``
    - senha: ``korp!4518``


----

Visualizando logs
=================

#. Acessar o Portainer
#. Preencher as credenciais
#. Acessar o ambiente "local"
#. Acessar o tópico "Containers"
#. Na caixa de pesquisa, digitar o nome do serviço desejado
#. Clicar no nome do serviço
#. Clicar em ``Logs``

**Interagindo com os logs**

    - ``Auto-refresh logs``: Quando habilitado, os logs irão ser atualizados em tempo real.

    - ``Search``: Filtro por texto.

    - ``Lines``: A quantidade de linhas do log que serão mostradas na tela.

    - ``Download Logs``: Irá baixar logs em um arquivo

----

Reiniciando um serviço
======================

#. Acessar o Portainer
#. Preencher as credenciais
#. Acessar o ambiente "local"
#. Acessar o tópico "Containers"
#. Na caixa de pesquisa, digitar o nome do serviço desejado
#. Selecionar o serviço pelo checkbox na sua linha
#. Clicar no botão "Restart"
