# COMI-1 - VEN17_W (Regras de Comissão Web) no SetupLinux

Aprovado no chat em 26/10/2026. Referências: roles VEN27 (dependências e composes de frontend) e FIS24_W (backend legado sem banco próprio, ERPK-6365).

Role `roles/VEN17_W` com três peças: `Korp.Vendas.Comissao.Core`, `Korp.Vendas.Comissao.Gateway` e frontend `korp.vendas.comissao-frontend`.

- `meta/main.yml`: mesmas dependências da VEN27 do SetupLinux e a própria VEN27.
- `vars/main.yml`: os dois serviços sem propriedades; banco legado SQL Server, sem `db:`.
- `templates/composes/VEN17_W-compose.yml.j2`: core e gateway com `{{ docker_account }}`, `ON_PREMISE_MODE=true`, `restart: unless-stopped`, hosts padrão e `api_gateway` opcional.
- `templates/composes/2025.1.0` e `2025.2.0`: frontend `VEN17_W-<versão>`.
- `templates/consul_kv/korp.vendas.comissao.{core,gateway}.json.j2`: `Authorization.Secret`, `Provisioning.EnableSchemaProvisioning=false` e `EnableEnvironmentDependentConnectionString=true`.

Imagens Docker consideradas disponíveis. Branch COMI-1-master; cherry-pick para release fica com o usuário. iac fora do escopo.
