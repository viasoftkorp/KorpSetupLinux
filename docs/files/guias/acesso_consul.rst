Acesso ao Consul
----------------

O Consul guarda a configuração dos serviços (KVs, inclusive conexões com os bancos). Para que a rede do cliente não
leia nem altere esses dados, o acesso ao Consul **de fora do servidor** exige o tenant do servidor como usuário e
senha (autenticação Basic).

Quem acessa e como
==================

.. list-table::
   :header-rows: 1

   * - Quem
     - Endereço
     - Autenticação
   * - Serviços Delphi (servidor de aplicação Windows) e a UI do Consul no navegador
     - ``http://<servidor>:8500`` (nginx, que repassa ao Consul)
     - tenant como usuário e como senha
   * - Serviços web (containers)
     - ``http://consul-server:8500``, pela rede docker
     - nenhuma
   * - Setup e suporte, no próprio servidor
     - ``http://127.0.0.1:18500`` (porta local do ``consul-server``)
     - nenhuma

Os serviços Delphi já enviam a credencial: ``'Basic ' + base64(tenantId + ':' + tenantId)``.

O ``consul-server`` não publica mais nenhuma porta para fora do servidor: nem a HTTP (8500), nem as de RPC e gossip
(8300 e 8301), por onde outra máquina poderia entrar no cluster e contornar o nginx, nem a de DNS (8600).

Na UI do Consul pelo navegador, informe o tenant do servidor nos dois campos. Ele está no inventário
(``tenant_id``). No próprio servidor, a UI também abre sem senha em ``http://127.0.0.1:18500/ui`` (por exemplo, com
um túnel SSH: ``ssh -L 18500:127.0.0.1:18500 <usuário>@<servidor>``).

Recusas
=======

Só as requisições recusadas (401) vão para o log do nginx, com o IP de origem, para não encher o log com as
consultas que os serviços fazem o tempo todo::

    docker logs nginx 2>&1 | grep ' 401 '

Desligar
========

Ligado por padrão, inclusive nas instalações existentes, na primeira atualização do setup. Para desligar num
servidor (a 8500 volta a ser do Consul, sem autenticação, como antes)::

    ./setup.sh ... consul_basic_auth=false

O valor fica salvo no inventário (``consul.basic_auth``) e vale para as próximas execuções; para religar, passe
``consul_basic_auth=true``. Sem ``tenant_id`` no inventário não há como autenticar, e a 8500 fica como antes.

Na troca (ligar ou desligar), o setup para o container que hoje tem a 8500 (``consul-server`` ou ``nginx``) logo
antes de recriar os dois, para que o novo dono consiga a porta: a 8500 fica cerca de 15 segundos fora do ar. Como o
``consul-server`` é recriado, o compose recria junto os containers que dependem dele (``fabio``, ``rabbitmq`` e
``redis``), como em qualquer atualização da imagem do Consul. Os setups seguintes, sem troca, não param nem recriam
nada.
