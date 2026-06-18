# SPEC: map-service-tags

## Objetivo
Mapear tags de imagem Docker de múltiplos serviços em branches de release do repositório `KorpSetupLinux`, sem alterar o working tree (`git checkout` proibido).

## Entradas
- `--repo` (obrigatório): caminho do repositório Git local
- `--services`: um ou mais nomes de serviço (CSV ou flag repetida)
- `--services-file`: arquivo com um serviço por linha (padrão: `service-list` neste diretório)
- `--branches`: branches alvo (CSV ou flag repetida)
- `--branches-regex`: regex para selecionar branches locais e `origin/*`
- `--workers`: threads paralelas para varredura por branch (padrão: auto)

Branches padrão quando nenhum filtro é informado:
- `release/2023.4.0.x`
- `release/2024.2.0.x`
- `release/2024.1.0.x`
- `release/2025.1.0.x`

## Processamento
Para cada branch, localizar linhas que correspondam estritamente ao template:

```yaml
image: "{{ docker_account }}/SERVICE:TAG{{ docker_image_suffix }}"
```

Extrair apenas `TAG` por serviço. Primeira ocorrência encontrada prevalece.

## Saída
Arquivo `mapping.json` neste diretório (`__dirname`):

```json
{
  "viasoft.loader": {
    "release/2025.1.0.x": "1.0.x"
  }
}
```

Serviços ausentes em uma branch são omitidos silenciosamente.

## Execução

```bash
cd scripts/mapeamento-tags
node map-service-tags.js --repo ../..
```
