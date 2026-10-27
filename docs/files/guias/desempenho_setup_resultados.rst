Desempenho do setup — resultados
--------------------------------

Medições e verificações de equivalência feitas em 2026-10-02 para as branches
``release/2025.1.0.x-performance-test`` (base ``f065d7ce``) e ``release/2024.2.0.x-performance-test``
(base ``c22dea52``). Evidências (resumos de tempo por execução, ações de migração executadas e
comparações de estado): ``tests/sim/evidencias/``.

Onde foi medido
===============

**QA12 (servidor real)** — não foi possível executar o setup nesta entrega: as permissões do ambiente
de execução dos testes não permitiram o uso de ``sudo`` na QA12 nem a leitura dos tokens de setup do histórico
da máquina. Nenhuma alteração foi feita na QA12. Os únicos dados reais usados são os logs históricos de
``/etc/korp/ansible/logs`` (leitura sem privilégios):

========================  ================  ===============  ======================
Log da QA12               Duração           Cabeçalhos TASK  ok / changed / skipped
========================  ================  ===============  ======================
2026-08-26 11:29          ≈45 min           8534             5135 / 321 / 3736
2026-09-17 15:40          ≈47 min           8859             4973 / 240 / 4261
2026-09-21 14:36          ≈47 min           8808             5131 / 275 / 4044
========================  ================  ===============  ======================

**Ambiente isolado** (``tests/sim``) — host Ubuntu 22.04 com 4 CPUs e 16 GB, Docker 24.0.2, Compose 2.18.1,
Ansible do PPA (ansible-core 2.17.14), community.docker 5.3.0 — as mesmas versões da QA12 —, executando o
``setup.sh`` real de cada commit com Consul, Postgres, RabbitMQ, Redis e SQL Server reais, gateway simulado e
imagens de aplicativos falsas. Cada par (original × otimizado) parte do **mesmo snapshot** (host, ``/etc/korp``,
``/var/lib/docker`` e SQL Server).

Limitações (o que os números **não** incluem): download de imagens dos aplicativos, a role ``provisioning``,
latência de rede até um SQL Server remoto e a inicialização real dos serviços .NET. O custo por tarefa na
QA12 é maior que no ambiente isolado (o mesmo cenário de atualização 2024.2→2025.1 gera ~8.200 cabeçalhos
TASK aqui em ~10 min e ~8.800 na QA12 em ~47 min), então os segundos economizados aqui **não** devem ser
transpostos diretamente para a QA12 ou para clientes; o que se transpõe é a redução no número de tarefas e de
execuções de módulo, que é a causa do tempo.

Resultados — fase 1 (validação durante o desenvolvimento)
=========================================================

Tempo total do ``setup.sh`` (inclui inventory-playbook e os passos de rede simulados). "Estado final" compara
Consul KV (texto exato), tabelas OAuth, bancos SQL Server/Postgres, arquivos de ``/etc/korp``, crontab e
containers (nome, imagem, projeto/serviço Compose, config-hash).

.. list-table::
   :header-rows: 1

   * - Cenário (snapshot inicial)
     - Original
     - Otimizado
     - Redução
     - Estado final
     - Ações de migração (orig/otim)
   * - S3: atualização 2024.2→2025.1 (2024.2 instalado)
     - 606,6 s
     - 201,1 s
     - −67 %
     - igual¹
     - 0 / 0
   * - S4: reexecução 2025.1 sem mudanças
     - 591,3 s
     - 160,7 s
     - −73 %
     - igual
     - 0 / 0
   * - S5a: 1ª atualização sobre legado 2025.1 (instalado com o código anterior ao DEVO-5167)
     - 605,9 s
     - 241,6 s
     - −60 %
     - igual¹
     - 9 / 9
   * - S5b: atualização 2025.1 sobre legado 2024.2 (anterior ao DEVO-5167)
     - 740,0 s
     - 251,8 s
     - −66 %
     - igual¹
     - 5 / 5
   * - S6: estados construídos E/F/A/C (parcial, backup, identidade conflitante, legado)
     - 559,9 s
     - 176,7 s
     - −68 %
     - igual
     - 9 / 9
   * - S7: ``install-only`` de app novo (VEN27 + dependências)
     - 407,0 s
     - 130,0 s
     - −68 %
     - igual
     - —
   * - S8: ``uninstall-version 2024.2.0`` (código não alterado)
     - 24,5 s
     - 23,0 s
     - —
     - igual
     - —
   * - S10: branch otimizada com ``fast_path=false``
     - 591,3 s
     - 593,3 s
     - —
     - igual
     - —
   * - 2024.2 — reexecução sem mudanças
     - 423,7 s
     - 109,1 s
     - −74 %
     - igual
     - 0 / 0
   * - 2024.2 — 1ª atualização sobre legado 2024.2
     - 590,4 s
     - 212,8 s
     - −64 %
     - igual
     - 9 / 9
   * - 2024.2 — instalação nova
     - 622,0 s
     - 169,8 s
     - −73 %
     - igual²
     - 0 / 0

¹ Exceto valores sabidamente aleatórios do código original: htpasswd do Temporal UI (salt aleatório) e segredos
``temporal.*`` gerados pelo ``inventory-playbook`` na primeira execução 2025.1. Duas execuções do **código original**
a partir do mesmo snapshot diferem exatamente nesses itens (verificação de repetibilidade).

² Numa instalação nova, o ``inventory-playbook`` gera senhas aleatórias (Redis, RabbitMQ, Postgres, MinIO, …);
o dump substitui esses valores por ``<inventory>``. Restam apenas os config-hash dos containers ``postgres``,
``minio-server`` e ``minio-server-new`` (o ambiente deles contém essas senhas).

Falha e recuperação (S9):

* **Interrupção**: a execução otimizada foi encerrada à força no meio (``kill -9`` aos 37 s); a reexecução terminou
  com sucesso e o estado final é **igual** ao de uma execução original completa.
* **Volta para o código original**: executar a branch de release original sobre o estado produzido pela
  otimizada não fez nenhuma migração e não alterou nada (estado igual).
* **Falha injetada** (KV corrompido no Consul): original e otimizada falham no KV daquele serviço (a otimizada mais
  cedo, com mensagem que nomeia a chave); após remover a chave e reexecutar, os estados finais são iguais (exceto
  o novo segredo aleatório da chave removida, regenerado nos dois — e, nos dois, o cliente OAuth antigo é mantido,
  comportamento pré-existente).
* Nessas execuções, o ``setup.sh`` da 2025.1 original terminava com código 0 mesmo com o playbook falhando ou
  interrompido; corrigido na branch de desempenho (``PIPESTATUS``, como na 2024.2).

Resultados — fase 2 (medição final, commits finais)
===================================================

Executada com o ambiente isolado **do próprio repositório** (``tests/sim``, montado do zero) e os commits finais das
duas branches (``54c8a646`` na 2025.1 e ``d44e8824`` na 2024.2, com as correções da revisão final). Durante esta fase a
máquina de testes foi reiniciada e passou a ter menos memória (27 GB) e carga de desktop concorrente, por isso os
tempos absolutos são maiores que os da fase 1; cada par original × otimizado rodou em sequência, a partir do mesmo
snapshot, nas mesmas condições. Evidências: ``tests/sim/evidencias/2026-10-02-final``.

.. list-table::
   :header-rows: 1

   * - Cenário (snapshot inicial)
     - Original
     - Otimizado
     - Redução
     - Estado final
   * - M2: atualização 2024.2→2025.1 (2024.2 instalado)
     - 857,8 s
     - 278,9 s
     - −67 %
     - igual¹
   * - M3: reexecução 2025.1 sem mudanças
     - 1017,6 s
     - 243,2 s
     - −76 %
     - igual
   * - M4: reexecução 2024.2 sem mudanças (branch 2024.2)
     - 580,9 s
     - 144,2 s
     - −75 %
     - igual
   * - M7: branch otimizada com ``fast_path=false`` (mesmo estado do M3)
     - 1017,6 s
     - 947,1 s
     - —
     - igual (mesmas 196 alterações relatadas)

Número de tarefas Ansible (cabeçalhos ``TASK``) por execução: M2 8.183 → 2.333, M3 8.177 →
2.327, M4 6.228 → 1.683 (−71 % a −73 %).

Cenários da fase 1 não repetidos na fase 2 (instalação nova, estados legados e construídos, ``install-only``,
``uninstall-version``, falha/recuperação): o código que eles exercitam — classificação da reconciliação e caminho em
lote — não mudou na revisão final além de mensagens de erro, validação de ``volumes_directories``, verificação de
``service_name`` e a fonte única do comando Postgres (exercitada em M2–M4 e, no caminho original, em M7).
A instalação nova da 2025.1 não foi medida isoladamente (a da 2024.2 foi, na fase 1).

Fluxos de aplicativos versionados (SD-40916)
============================================

As tags ``update-versioned`` e ``install-versioned-only`` (SD-40916, PRs #591–#593) foram incorporadas às branches de
desempenho junto com um ajuste: no ``install-versioned-only``, um AppId que ainda não está registrado em nenhuma versão
tem os serviços do compose versionado (container ``<serviço>-<versão>``) cadastrados pelo fluxo normal de
``services/add_service`` — KV, cliente OAuth, bancos e diretórios de volume, sem compose nem registro. AppIds já
registrados continuam sem nenhuma alteração de KV (os KVs são compartilhados entre versões). Dependências da role e
serviços não versionados ou exclusivos seguem fora destes fluxos, como no PR. Os dois fluxos usam o
``reconciled_compose_up`` otimizado e, no cadastro, o lote.

Validação no ambiente isolado, a partir de um servidor com 2024.2 e 2025.1 instaladas (evidências:
``tests/sim/evidencias/2026-10-02-sd40916``). Referência: o código original com o PR (na 2025.1, a release atual com o
PR mesclado — o PR #593 parte de um commit anterior da release, com outro compose do LOG102).

.. list-table::
   :header-rows: 1

   * - Linha / token
     - Cenário
     - Referência
     - Desempenho
     - Estado final
   * - 2024.2
     - ``update-versioned``
     - 58,8 s
     - 25,1 s
     - igual
   * - 2024.2
     - ``install-versioned-only`` LOG102,LOG103 (já registrados)
     - 36,7 s
     - 18,0 s
     - igual
   * - 2024.2
     - ``install-versioned-only`` PRO09,RMA01_W (nunca instalados) — ``fast_path=false`` × padrão
     - 32,7 s
     - 20,5 s
     - igual
   * - 2024.2
     - ``install-only`` PRO09,RMA01_W (fluxo normal, regressão do cadastro)
     - 51,6 s
     - 27,3 s
     - igual
   * - 2025.1
     - ``update-versioned``
     - 63,4 s
     - 25,4 s
     - igual
   * - 2025.1
     - ``install-versioned-only`` LOG102 (já registrado; só frontend no compose versionado)
     - 15,0 s
     - 15,1 s
     - igual
   * - 2025.1
     - ``install-versioned-only`` engenharia,RMA01_W,PCRG001 (nunca instalados)
     - 41,8 s
     - 28,8 s
     - igual
   * - 2025.1
     - ``install-only`` engenharia,RMA01_W,PCRG001 (fluxo normal, regressão do cadastro)
     - 53,8 s
     - 27,0 s
     - igual

No caso de AppId nunca instalado, os KVs criados para os serviços versionados têm o mesmo conteúdo que uma instalação
normal do mesmo app produziria, exceto ``Authorization.Secret`` (aleatório a cada instalação). Sem o ajuste, o PR
subia esses containers sem KV.

Validação pendente num servidor real (QA12)
===========================================

Comandos para quem tem acesso à QA12 (substitua ``<token-2025.1>``; para a linha 2024.2 use o token da versão
2024.2 e as branches ``release/2024.2.0.x``/``release/2024.2.0.x-performance-test``). Faça o backup descrito em
:doc:`desempenho_setup` antes. Cada execução abaixo é uma atualização completa (``custom_tags=update``), como as
dos logs históricos.

#. Linha de base (código original), com tempo por tarefa e total::

    export ANSIBLE_CALLBACKS_ENABLED=ansible.posix.profile_tasks
    export branch_name=release/2025.1.0.x; curl -s -S https://raw.githubusercontent.com/viasoftkorp/KorpSetupLinux/$branch_name/setup.sh > /tmp/setup.sh && time bash /tmp/setup.sh gateway_url=https://gateway.korp.com.br branch_name=$branch_name custom_tags=update token=<token-2025.1> skip_salt_test=true should_update_rabbitmq=true

#. Estado após a linha de base::

    sudo docker exec consul-server consul kv export | sudo tee /root/kv-orig.json >/dev/null
    sudo docker ps -a --format '{{.Names}} {{.Image}} {{.Label "com.docker.compose.project"}}' | sort | sudo tee /root/containers-orig.txt >/dev/null

#. Mesma atualização com as otimizações::

    export branch_name=release/2025.1.0.x-performance-test; curl -s -S https://raw.githubusercontent.com/viasoftkorp/KorpSetupLinux/$branch_name/setup.sh > /tmp/setup.sh && time bash /tmp/setup.sh gateway_url=https://gateway.korp.com.br branch_name=$branch_name custom_tags=update token=<token-2025.1> skip_salt_test=true should_update_rabbitmq=true

#. Estado após a execução otimizada e comparação (não deve haver diferenças)::

    sudo docker exec consul-server consul kv export | sudo tee /root/kv-opt.json >/dev/null
    sudo docker ps -a --format '{{.Names}} {{.Image}} {{.Label "com.docker.compose.project"}}' | sort | sudo tee /root/containers-opt.txt >/dev/null
    sudo diff /root/kv-orig.json /root/kv-opt.json && sudo diff /root/containers-orig.txt /root/containers-opt.txt && echo IGUAL

O tempo total aparece na saída do ``time``; o resumo do ``profile_tasks`` fica no log mais recente de
``/etc/korp/ansible/logs``. Os arquivos em ``/root`` contêm segredos: apague-os ao final. Para voltar ao estado
anterior, basta reexecutar o comando da linha de base (seção "Recuperação" de :doc:`desempenho_setup`).

Reprodução
==========

``tests/sim/README.md``. Exemplo (do diretório ``tests/sim``)::

    ./simctl.sh build && ./simctl.sh infra-up && ./simctl.sh mirror ../..
    ./simctl.sh host-up sim1 && ./simctl.sh seed sim1 && ./simctl.sh pull-public sim1 && ./simctl.sh snapshot sim1 seeded
    # instala 2024.2 com o código original e guarda o snapshot
    ./simctl.sh version 2024.2.0
    SIM_REF=release/2024.2.0.x ./simctl.sh setup sim1 inst24.log branch_name=release/2024.2.0.x token=simtoken skip_salt_test=true should_update_rabbitmq=true apps=vendas,ERP,fiscal
    ./simctl.sh snapshot sim1 inst24
    # par original × otimizado da atualização para 2025.1
    scenarios/run_pair.sh upgrade inst24 2025.1.0 release/2025.1.0.x release/2025.1.0.x-performance-test custom_tags=update

(``mirror`` publica as branches locais do clone indicado; as refs usadas precisam existir nele.)
