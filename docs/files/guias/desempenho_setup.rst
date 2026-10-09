Desempenho do setup
-------------------

Este guia descreve as otimizações de desempenho do setup Linux (``setup.sh``), como elas preservam o
comportamento anterior, como executá-las, como desligá-las e como recuperar um servidor.

Design e plano completos: ``docs/desempenho/2026-10-02-desempenho-setup-design.md`` e
``docs/desempenho/2026-10-02-desempenho-setup-plano.md``. Medições e evidências:
:doc:`desempenho_setup_resultados`.

Diagnóstico
===========

Uma atualização típica executava cerca de 8.800 tarefas Ansible (logs reais da QA12: 45–47 minutos).
Quase todo o tempo vinha de verificações repetidas **por serviço**, que em regime normal não alteram nada:

* **Reconciliação de compose** (DEVO-7182): para cada serviço de cada arquivo de compose, ~30 tarefas e
  5–6 inspeções Docker (``docker_container_info``/``docker ps``), mesmo com todos os containers já corretos.
* **Cadastro de serviços** (``add_service``): por serviço, 4–6 ``include_role``, 3 chamadas ao Consul,
  1 módulo de hash, 1–2 conexões novas ao SQL Server e 1 ``docker exec`` no Postgres.

O custo de cada tarefa (≈0,1–0,3 s no ambiente isolado, maior em servidores reais) multiplicado pelo
número de serviços explica o tempo total. O trabalho útil (``docker compose up``, templates, bancos) é uma
fração pequena.

O que mudou
===========

Fast path da reconciliação de compose
    O módulo somente-leitura ``korp_compose_state`` executa o mesmo ``docker compose config`` e, com um
    único ``docker ps`` e um ``docker inspect``, verifica se algum serviço do compose está num estado que
    exige ação: container parcial ``<12hex>_<nome>``, backup ``<nome>-legacy-compose-migration``,
    container com projeto/serviço Compose diferente do esperado, ou container legado sem sufixo de versão.
    Se houver qualquer um, os **mesmos loops de antes** rodam para todos os serviços daquele compose
    (com todas as validações e o rollback do DEVO-7182). Se não houver, os loops nem são incluídos — neles
    só haveria leituras. Os motivos aparecem no log (tarefas "Serviços que exigem reconciliação de
    identidade" e "Containers legados ou parciais a remover").

Cadastro de serviços em lote
    Na primeira iteração do loop de ``add_service.yml`` todos os serviços da role são processados de uma
    vez, na mesma ordem e com os mesmos templates: validação e valores padrão das variáveis, KVs no Consul
    (módulo ``korp_consul_kv_batch``, com a mesma regra de merge do ``consul_kv.py``), clientes OAuth e
    bancos SQL Server (um ``mssql_script`` com lotes ``GO`` para cada) e bancos Postgres (um ``shell``).

Checagem de templates de compose
    ``gather_info`` verifica a existência dos templates no próprio host (os plays usam
    ``connection: local``) em vez de executar o módulo ``stat``.

Menos tarefas por aplicativo
    Cálculos que eram feitos em várias tarefas, algumas com loop item a item, viram uma tarefa com um filtro
    (``filter_plugins/korp_setup_batch.py``): a última versão instalada no início de cada role
    (``korp_latest_installed_version``), as listas e versões de ``gather_info`` (``korp_service_lists``) e o
    ``apps_map`` de ``ensure_mapping`` (``korp_apps_mapping``; roles só com serviços exclusivos mantêm as
    tarefas originais). As tarefas originais ficam em ``*_tasks.yml`` e são usadas com ``fast_path=false``;
    ``tests/unit/test_korp_fast_path_equivalence.py`` executa as duas versões no Ansible e compara os facts.

Instalação do docker no provisioning
    As dependências e os pacotes do docker são instalados em duas chamadas do ``apt`` (uma lista cada), em vez
    de um loop em que cada pacote fazia o seu próprio ``apt update`` (10 atualizações viram 2). Os pacotes
    instalados são os mesmos; com ``fast_path=false`` os loops originais continuam.

O que **não** mudou: roles de aplicativos e seus ``vars/main.yml``, templates (compose, KV, SQL),
infraestrutura, provisioning, ``update``/``remove-apps``/``uninstall-version``, formato do
``installed_apps.yml``, nomes de projeto Compose e as regras de segurança do DEVO-7182. A forma de adicionar
serviços e aplicativos descrita no ``readme.md`` continua a mesma.

Compatibilidade
===============

* Servidores em qualquer estado tratado pelo DEVO-7182 (projetos/serviços antigos, containers sem sufixo,
  parciais, backups de migração interrompida) disparam o caminho original para o compose afetado. Não é
  necessária nenhuma preparação manual; a primeira execução sobre um servidor antigo faz as mesmas migrações
  que o código anterior faria.
* Estados que o código anterior não tratava (projetos de versões antigas, órfãos sem relação de nome,
  arquivos de compose obsoletos) continuam sem tratamento.
* Diferença conhecida, apenas em falhas: o cadastro em lote agrupa as etapas (KVs de todos os serviços da
  role, depois clientes OAuth, depois bancos) e valida as variáveis antes de qualquer escrita. Se a execução
  falhar no meio, o estado parcial pode ser diferente do que o código anterior deixaria; uma nova execução
  converge para o mesmo estado final, pois todas as operações são idempotentes.

Execução
========

Nenhum parâmetro novo é obrigatório: use o comando de sempre, com ``branch_name`` apontando para a branch que
contém as otimizações (durante a homologação, ``release/2025.1.0.x-performance-test`` ou
``release/2024.2.0.x-performance-test``; depois do merge, a própria branch de release). Exemplo de atualização::

    export branch_name=<branch>; curl -s -S https://raw.githubusercontent.com/viasoftkorp/KorpSetupLinux/$branch_name/setup.sh > /tmp/setup.sh && bash /tmp/setup.sh gateway_url=https://gateway.korp.com.br branch_name=$branch_name custom_tags=update token=<token>

Para medir o tempo de cada tarefa, exporte antes ``ANSIBLE_CALLBACKS_ENABLED=ansible.posix.profile_tasks``
(o resumo vai para o log em ``/etc/korp/ansible/logs``) e use ``time bash /tmp/setup.sh ...`` para o total.

Na 2025.1, o ``setup.sh`` voltou a terminar com código 11 quando o playbook principal falha (como na 2024.2);
antes, o código era o do ``tee`` e falhas terminavam com 0.

Acompanhamento em segundo plano
===============================

Com ``progress=true`` (opcional; sem ele nada muda), o ``setup.sh`` faz em primeiro plano o que pode pedir
alguma resposta (instalação do Ansible, clone, inventário e perguntas de DNS) e dispara o playbook principal em
segundo plano: com ``systemd-run`` (serviço ``korp-setup``) ou, onde não há systemd, com ``setsid``. A execução
continua mesmo que a sessão SSH caia. A sessão mostra a etapa, o app atual (X de N), a tarefa, o tempo decorrido
(com estimativa pela última execução com as mesmas tags) e os contadores; em caso de falha, mostra o app, a tarefa
e a mensagem de erro, e o ``setup.sh`` termina com código 11, como hoje.

- ``Ctrl+C`` fecha só a tela; para voltar: ``sudo korp-setup-acompanhar``.
- O log completo continua em ``/etc/korp/ansible/logs``, no mesmo formato. O andamento fica em
  ``/etc/korp/ansible/progress/status.json`` e o histórico das execuções em ``history.jsonl`` (acesso só do root).
- Enquanto um setup roda em segundo plano, um novo ``setup.sh`` é recusado (código 15).
- As variáveis ``ANSIBLE_*`` de quem executa (por exemplo ``ANSIBLE_CALLBACKS_ENABLED``) são repassadas ao playbook.
- Componentes: ``callback_plugins/korp_progress.py`` (grava o andamento e nunca interrompe o setup),
  ``scripts/acompanhamento/korp_setup_runner.py`` (executa o playbook, fecha o resultado e limpa
  ``/tmp/KorpSetupLinux``) e ``scripts/acompanhamento/korp-setup-acompanhar`` (a tela).

Instalação do Ansible
=====================

O ``setup.sh`` não chama mais o ``add-apt-repository`` quando o PPA do Ansible já está configurado: esse comando
consulta ``api.launchpad.net`` e falhava em servidores sem acesso a ele. Nesse caso, só atualiza a lista de
pacotes. Sem o PPA, tenta adicioná-lo até 3 vezes. Se a rede falhar mas o servidor já tiver git e ansible-core 2.17
ou mais novo, o setup segue com um aviso; abaixo disso (a community.docker que o setup instala exige 2.17), para com
uma mensagem que mostra a versão encontrada e os endereços a liberar (códigos 12 e 13, como antes).

Pipelining do Ansible
=====================

Opcional: ``pipelining=true``. O Ansible passa cada módulo pela entrada do ``sudo`` em vez de criar, ajustar
permissões (ACL para o usuário korp) e apagar um arquivo temporário por tarefa: menos processos por módulo, o
que pesa em servidores com CPU lenta. ``copy`` e ``template`` continuam transferindo arquivos como antes, e
tarefas que não suportam pipelining voltam sozinhas ao modo normal. Se o sudoers tiver ``Defaults
requiretty`` (toda tarefa com become falharia), o ``setup.sh`` avisa e segue sem pipelining. ``use_pty``, o
padrão do Ubuntu 22.04, é compatível.

Desligando as otimizações
=========================

Acrescente ``fast_path=false`` ao comando. As tarefas individuais por serviço (``add_service_individual.yml``)
voltam a ser executadas, ``gather_info`` volta a usar o módulo ``stat`` e os loops de reconciliação de compose
rodam para todos os serviços, como antes. Diferenças que permanecem e não alteram containers: a resolução do
compose é feita pelo módulo ``korp_compose_state`` (o mesmo ``docker compose config``, mais um
``docker ps``/``docker container inspect`` de leitura) e há outra leitura (``docker ps``) depois do ``up``.

Recuperação
===========

As otimizações não criam estado novo no servidor: Consul, SQL Server, Postgres, arquivos em ``/etc/korp`` e
containers ficam iguais aos produzidos pelo código anterior. Para voltar:

#. Reexecute o setup com a branch de release original (``branch_name=release/2025.1.0.x`` ou
   ``release/2024.2.0.x``) e os mesmos parâmetros; ou
#. mantenha a branch de desempenho e use ``fast_path=false``.

Se uma execução for interrompida (falha de rede, SQL Server indisponível, etc.), corrija a causa e execute
o setup novamente: as etapas são idempotentes e os estados intermediários de migração de containers são
tratados pelo mesmo código do DEVO-7182 (backup ``*-legacy-compose-migration`` é restaurado ou removido com
segurança).

Antes de testar num servidor, guarde o estado atual. **O backup contém segredos** (``.env`` dos composes e
todos os KVs do Consul, com senhas de banco e segredos OAuth): mantenha-o restrito ao root e apague-o depois::

    sudo sh -c 'umask 077 && mkdir -p /root/backup-setup && cd /root/backup-setup \
      && cp -a /etc/korp/configs/installed_apps.yml /etc/korp/composes . \
      && docker exec consul-server consul kv export > consul-kv.json \
      && docker ps -a --format "{{.Names}} {{.Image}} {{.Label \"com.docker.compose.project\"}}" > containers.txt'

Para mantenedores
=================

* O padrão para adicionar serviços e aplicativos (``readme.md``) não mudou. ``add_service.yml`` continua sendo
  chamado pelas roles com ``with_dict: "{{ services }}"``, ``service_name: "{{ item.key }}"`` e
  ``loop_control.extended: true`` — o lote usa ``ansible_loop.allitems`` e valida que ``service_name`` é a chave
  do item.
* A lógica por serviço existe em dois caminhos: o original (``vars_validation.yml``, ``consul_kv/ensure_kv.yml``,
  ``oauth_client/*``, ``create_db/*``, ``ensure_volume_folder.yml``) e o lote (``add_services_batch.yml``,
  filtros em ``filter_plugins/korp_setup_batch.py`` e o módulo ``korp_consul_kv_batch``). Toda alteração num deles
  precisa ser feita no outro; os arquivos originais têm um aviso. A regra de merge de KV e o comando de criação de
  banco Postgres têm uma única fonte (``module_utils/korp_kv_merge.py`` e
  ``templates/queries/create_db_postgres.sh.j2``).
* ``consul_kv_template_dir`` (opcional, padrão ``consul_kv``) existe nos dois caminhos do cadastro de KV: usado pelo
  ``install-versioned-only`` (SD-40916), que cadastra serviços fora da role do app.
* Ao alterar a reconciliação de compose (``recover_partial``/``reconcile``/``cleanup_*``), revise as condições de
  ``korp_compose_state.classify``: elas precisam cobrir todo caso em que essas tarefas agem ou falham.
* Depois de qualquer mudança: ``bash tests/run_unit_tests.sh`` e, no ambiente isolado, um par original × otimizado
  e uma execução com ``fast_path=false`` (``tests/sim/scenarios/run_pair.sh``).

Ambiente isolado de testes
==========================

``tests/sim`` reproduz um servidor (mesmas versões de Ubuntu, Docker, Compose e Ansible da QA12) para
executar o ``setup.sh`` real de qualquer commit, medir o tempo e comparar o estado final entre versões.
Veja ``tests/sim/README.md``. Testes unitários: ``bash tests/run_unit_tests.sh`` (Python 3 com
ansible-core).
