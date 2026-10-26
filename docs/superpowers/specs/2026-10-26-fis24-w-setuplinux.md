# ERPK-6365 - FIS24_W no SetupLinux

Proposta aprovada no chat em 26/10/2026, baseada no PR viasoftkorp/KorpSetupLinux#460 e na reuniao ERPK-6330.vtt (01:00 a 01:04).

Criar roles/FIS24_W com um unico backend Korp.Contabilidade.AutomatizacaoOperacaoContabil. Sem frontend, gateway dedicado, banco novo ou dependencias de outras roles. Usar os helpers existentes para Consul, OAuth, Compose e registro do aplicativo. Nao alterar a lista de apps instalados por padrao.

Arquivos: meta/main.yml com dependencies: []; tasks/main.yml com utils/services/add_service e id FIS24_W; vars/main.yml com services/Korp.Contabilidade.AutomatizacaoOperacaoContabil sem propriedades; templates/composes/FIS24_W-compose.yml.j2 com um container e imagem parametrizada por version_without_build e docker_image_suffix; templates/consul_kv/korp.contabilidade.automatizacaooperacaocontabil.json.j2 com Authorization.Secret, Provisioning.EnableSchemaProvisioning=false e EnableEnvironmentDependentConnectionString=true, conforme PR de referencia.

Compose: rede externa servicos, hosts padrao, restart unless-stopped, ON_PREMISE_MODE=true, USE_SERVERGC, URL_CONSUL=http://consul-server:8500, CERT_FILE_PATH e volume padrao de certificados. Nome da imagem korp.contabilidade.automatizacaooperacaocontabil. Nome do container Korp.Contabilidade.AutomatizacaoOperacaoContabil-{{ version_without_build }}.

Cache omitido do template: o servico assume habilitado/60 segundos. Nao adicionar valores locais, credenciais fixas, parametros Delphi ou conexoes de banco. Considerar que a imagem Docker existira, conforme usuario.

Trabalhar somente no branch ERPK-6365-master. Usuario fara cherry-pick para release. Sem commit, push, PR, deploy ou instalacao de servicos neste trabalho.
