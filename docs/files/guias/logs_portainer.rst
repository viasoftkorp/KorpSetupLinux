Gerenciamento de serviços do Servidor Linux
-------------------------------------------

O gerenciamento dos serviços Korp que rodam no servidor Linux pode ser feito por meio da ferramente `portainer`.

Seu acesso pode ser feito por meio do endereço ``http://korp.local:9011``

As credenciais de acesso são:

    - usuário: ``admin``
    - senha: ``korp!4518``


Leitura de logs
===============

#. Acessar o 'Portainer' pelo endereço http://korp.local:9011

#.	Preencher as credenciais

#.	Acessar o ambiente "local"

#.	Acessar o tópico "Containers"

#.	Na caixa de pesquisa, digitar o nome do serviço desejado

#. Clicar no nome do serviço

#. Clicar em ``Logs``

Interagindo com os logs
#######################

- ``Auto-refresh logs`` Quando habilitado, os logs irão ser atualizados em tempo real

- ``Search``: Filtro por texto

- ``Lines``: A quantidade de linhas do log que serão mostradas na tela


Reinicio de Serviços
====================


Como reiniciar um serviço no servidor LINUX
1.	Acessar o endereço http://korp.local:9011
2.	Preencher as credenciais
a.	usuário: admin
b.	senha: korp!4518
3.	Acessar o ambiente "local"
4.	Acessar o tópico "Containers"
5.	Na caixa de pesquisa, digitar o nome do serviço desejado
6.	Selecionar o serviço pelo checkbox na sua linha
7.	Clicar no botão "Restart"

