#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');
const https = require('https');
const http = require('http');
const { parseArgs } = require('util');

const PORTAINER_DIR = path.resolve(__dirname, '..');
const DEFAULT_ENV_PATH = path.join(PORTAINER_DIR, '.env');
const DEFAULT_OUTPUT = path.join(__dirname, 'report.json');

const YEAR_VERSION_PATTERN = /^20\d{2}\.\d+\.\d+$/;
const VERSION_SUFFIX_PATTERN = /-(20\d{2}\.\d+\.\d+)$/;
const YEAR_TAG_PREFIX_PATTERN = /^20\d{2}\.\d+\.\d+/;
const APP_ID_PATTERN = /^[A-Z]{2,}[0-9][A-Z0-9_-]*$/;

const IGNORED_IMAGE_BASES = new Set(['korp.atualizacaosistema', 'viasoft.core.hybridproxy']);

const IGNORED_CONTAINER_NAMES = new Set([
  'Korp.AtualizacaoSistema',
  'Korp.Legacy.Frontend-router',
  'Viasoft.Loader',
  'Viasoft.Core.HybridProxy',
]);

const INFRA_CONTAINER_NAMES = new Set([
  'minio-server',
  'minio-server-new',
  'postgres',
  'rabbitmq',
  'nginx',
  'consul-server',
  'redis',
  'portainer',
  'watchtower',
  'pgweb',
]);

const LEGACY_TAG_PATTERNS = [
  /^[0-9]+\.[0-9]+(\.[0-9]+)?(\.x)?(-|$)/i,
];

const cli = require.main === module
  ? parseArgs({
      options: {
        url: { type: 'string', short: 'u' },
        username: { type: 'string' },
        password: { type: 'string' },
        endpoint: { type: 'string', default: '2' },
        scope: { type: 'string', default: '2024.2.0' },
        output: { type: 'string', default: DEFAULT_OUTPUT },
        'env-file': { type: 'string', default: DEFAULT_ENV_PATH },
        'include-stopped': { type: 'boolean', default: true },
        help: { type: 'boolean', short: 'h', default: false },
      },
    }).values
  : {};

function printHelp() {
  process.stdout.write(`Uso:
  node validate-legacy-services.js [opções]

Valida containers Korp/Viasoft via API Portainer e identifica serviços legados
fora das especificações de versionamento (global-context.md).

Opções:
  -u, --url <url>           URL do Portainer em HTTP (ex.: http://host:9011)
      --username <user>     Usuário Portainer
      --password <pass>     Senha Portainer
      --endpoint <id>       ID do endpoint Docker (padrão: 2)
      --scope <versão>      Versão alvo do ambiente — apenas informativo no relatório
      --output <arquivo>    Caminho do relatório JSON
      --env-file <arquivo>  Arquivo .env (padrão: scripts/portainer/.env)
      --include-stopped     Inclui containers parados (padrão: true)
  -h, --help                Exibe esta ajuda

Variáveis de ambiente em scripts/portainer/.env:
  PORTAINER_URL           URL base HTTP (ex.: http://servidor:9011)
  PORTAINER_USER, PORTAINER_PASSWORD, PORTAINER_ENDPOINT
`);
}

function resolvePortainerUrl(url) {
  let value = String(url || '').trim();
  if (!value) {
    return value;
  }

  if (!/^https?:\/\//i.test(value)) {
    value = `http://${value}`;
  }

  value = value.replace(/^https:\/\//i, 'http://');
  return value.replace(/\/+$/, '');
}

function loadEnvFile(filePath) {
  if (!fs.existsSync(filePath)) {
    return;
  }

  for (const line of fs.readFileSync(filePath, 'utf8').split('\n')) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith('#')) {
      continue;
    }

    const separatorIndex = trimmed.indexOf('=');
    if (separatorIndex === -1) {
      continue;
    }

    const key = trimmed.slice(0, separatorIndex).trim();
    const value = trimmed.slice(separatorIndex + 1).trim();
    if (!(key in process.env)) {
      process.env[key] = value;
    }
  }
}

function getImageBase(image) {
  let name = String(image || '');

  const slashIndex = name.lastIndexOf('/');
  if (slashIndex !== -1) {
    name = name.slice(slashIndex + 1);
  }

  const colonIndex = name.indexOf(':');
  if (colonIndex !== -1) {
    name = name.slice(0, colonIndex);
  }

  return name.toLowerCase();
}

function getImageTag(image) {
  const value = String(image || '');
  const colonIndex = value.lastIndexOf(':');
  if (colonIndex === -1) {
    return '';
  }
  return value.slice(colonIndex + 1);
}

function normalizeContainerName(names) {
  const raw = Array.isArray(names) && names.length > 0 ? names[0] : '';
  return String(raw).replace(/^\//, '');
}

function isYearBasedVersion(version) {
  return YEAR_VERSION_PATTERN.test(String(version || ''));
}

function extractVersionSuffix(containerName) {
  const match = String(containerName).match(VERSION_SUFFIX_PATTERN);
  return match ? match[1] : null;
}

function getBaseNameWithoutVersion(containerName) {
  return String(containerName).replace(VERSION_SUFFIX_PATTERN, '');
}

function isIgnoredService(containerName, image) {
  if (IGNORED_CONTAINER_NAMES.has(containerName)) {
    return true;
  }

  if (INFRA_CONTAINER_NAMES.has(containerName)) {
    return true;
  }

  return IGNORED_IMAGE_BASES.has(getImageBase(image));
}

function isKorpService(containerName, image) {
  const imageValue = String(image || '');

  if (imageValue.startsWith('korp/')) {
    return true;
  }

  if (/^(Korp\.|Viasoft\.)/.test(containerName)) {
    return true;
  }

  if (APP_ID_PATTERN.test(containerName)) {
    return true;
  }

  if (/^(login|portal)$/i.test(containerName)) {
    return true;
  }

  return false;
}

function isLegacyImageTag(imageTag) {
  const tag = String(imageTag || '');
  if (!tag) {
    return false;
  }

  if (YEAR_TAG_PREFIX_PATTERN.test(tag)) {
    return false;
  }

  return LEGACY_TAG_PATTERNS.some((pattern) => pattern.test(tag));
}

function imageMatchesVersion(image, version) {
  if (!version || !isYearBasedVersion(version)) {
    return false;
  }
  return String(image).includes(`:${version}.`) || String(image).includes(`:${version}-`);
}

function classifyContainer(container) {
  const containerName = normalizeContainerName(container.Names);
  const image = container.Image || '';
  const state = container.State || 'unknown';

  if (!isKorpService(containerName, image) || isIgnoredService(containerName, image)) {
    return null;
  }

  const version = extractVersionSuffix(containerName);
  const imageTag = getImageTag(image);
  const issues = [];
  const isVersioned = version != null && isYearBasedVersion(version);

  if (!isVersioned) {
    issues.push({
      code: 'LEGACY_UNVERSIONED',
      message:
        'Container sem sufixo de versão no padrão ano (ex.: -2024.1.0, -2024.2.0, -2025.1.0).',
    });
  }

  if (isLegacyImageTag(imageTag)) {
    issues.push({
      code: 'LEGACY_IMAGE_TAG',
      message: `Tag de imagem legada '${imageTag}' (esperado padrão 20XX.X.X, ex.: 2024.2.0.x-hmlg).`,
    });
  } else if (isVersioned && !imageMatchesVersion(image, version)) {
    issues.push({
      code: 'LEGACY_IMAGE_MISMATCH',
      message: `Imagem '${image}' não corresponde à versão do container '${version}'.`,
    });
  }

  if (issues.length === 0) {
    return null;
  }

  return {
    container_name: containerName,
    image,
    state,
    version_suffix: version,
    base_name: getBaseNameWithoutVersion(containerName),
    issues,
  };
}

function portainerRequest(baseUrl, method, requestPath, jwt, body) {
  return new Promise((resolve, reject) => {
    const url = new URL(`${resolvePortainerUrl(baseUrl)}${requestPath}`);
    const transport = url.protocol === 'https:' ? https : http;
    const payload = body == null ? null : JSON.stringify(body);

    const request = transport.request(
      url,
      {
        method,
        headers: {
          ...(jwt ? { Authorization: `Bearer ${jwt}` } : {}),
          ...(payload
            ? {
                'Content-Type': 'application/json',
                'Content-Length': Buffer.byteLength(payload),
              }
            : {}),
        },
        timeout: 30000,
      },
      (response) => {
        let responseBody = '';
        response.on('data', (chunk) => {
          responseBody += chunk;
        });
        response.on('end', () => {
          resolve({
            status: response.statusCode ?? 0,
            body: responseBody,
          });
        });
      }
    );

    request.on('timeout', () => {
      request.destroy(new Error(`Timeout ao consultar ${url.toString()}`));
    });
    request.on('error', reject);

    if (payload) {
      request.write(payload);
    }
    request.end();
  });
}

async function authenticate(baseUrl, username, password) {
  const { status, body } = await portainerRequest(baseUrl, 'POST', '/api/auth', null, {
    Username: username,
    Password: password,
  });

  if (status === 401 || status === 422) {
    throw new Error(`Falha de autenticação no Portainer (HTTP ${status}). Verifique usuário e senha.`);
  }

  if (status !== 200) {
    throw new Error(`Falha ao autenticar no Portainer (HTTP ${status}): ${body}`);
  }

  let parsed;
  try {
    parsed = JSON.parse(body);
  } catch (error) {
    throw new Error('Resposta de autenticação inválida (JSON esperado).');
  }

  if (!parsed.jwt) {
    throw new Error('Token JWT não retornado pela API /api/auth.');
  }

  return parsed.jwt;
}

async function listContainers(baseUrl, jwt, endpointId, includeStopped) {
  const allFlag = includeStopped ? 'true' : 'false';
  const requestPath = `/api/endpoints/${endpointId}/docker/containers/json?all=${allFlag}`;
  const { status, body } = await portainerRequest(baseUrl, 'GET', requestPath, jwt);

  if (status === 401) {
    throw new Error('Token JWT expirado ou inválido (HTTP 401).');
  }

  if (status !== 200) {
    throw new Error(`Falha ao listar containers (HTTP ${status}): ${body}`);
  }

  return JSON.parse(body);
}

function detectMigrationPairs(korpContainers) {
  const byBase = new Map();

  for (const item of korpContainers) {
    const version = extractVersionSuffix(item.container_name);
    const base = getBaseNameWithoutVersion(item.container_name);

    if (!byBase.has(base)) {
      byBase.set(base, { unversioned: [], versioned: [] });
    }

    if (version && isYearBasedVersion(version)) {
      byBase.get(base).versioned.push(item.container_name);
    } else if (!version) {
      byBase.get(base).unversioned.push(item.container_name);
    }
  }

  const pairs = [];
  for (const [baseName, group] of byBase.entries()) {
    if (group.unversioned.length > 0 && group.versioned.length > 0) {
      pairs.push({
        base_name: baseName,
        legacy_containers: group.unversioned,
        versioned_containers: group.versioned,
        recommendation: `Remover legados: docker rm -f ${group.unversioned.join(' ')}`,
      });
    }
  }

  return pairs.sort((a, b) => a.base_name.localeCompare(b.base_name));
}

function buildReport(containers, scopeVersion, portainerMeta) {
  const legacyContainers = [];
  const scanned = [];
  const korpContainers = [];

  for (const container of containers) {
    const containerName = normalizeContainerName(container.Names);
    const image = container.Image || '';

    if (!isKorpService(containerName, image)) {
      continue;
    }

    const entry = {
      container_name: containerName,
      image,
      state: container.State || 'unknown',
      ignored: isIgnoredService(containerName, image),
      version_suffix: extractVersionSuffix(containerName),
    };

    scanned.push(entry);

    if (!entry.ignored) {
      korpContainers.push(entry);
    }

    const classified = classifyContainer(container);
    if (classified) {
      legacyContainers.push(classified);
    }
  }

  const issueCounts = {};
  for (const item of legacyContainers) {
    for (const issue of item.issues) {
      issueCounts[issue.code] = (issueCounts[issue.code] || 0) + 1;
    }
  }

  const migrationPairs = detectMigrationPairs(korpContainers);

  return {
    summary: {
      portainer_url: portainerMeta.url,
      endpoint_id: portainerMeta.endpointId,
      scope_version: scopeVersion,
      valid_version_pattern: '20XX.X.X (ex.: 2024.1.0, 2024.2.0, 2025.1.0)',
      total_containers: containers.length,
      korp_containers_scanned: korpContainers.length,
      legacy_containers: legacyContainers.length,
      migration_pairs: migrationPairs.length,
      issue_counts: issueCounts,
    },
    migration_pairs: migrationPairs,
    legacy_containers: legacyContainers.sort((a, b) =>
      a.container_name.localeCompare(b.container_name)
    ),
    scanned_containers: scanned.sort((a, b) => a.container_name.localeCompare(b.container_name)),
  };
}

function printSummary(report) {
  const { summary, legacy_containers: legacyContainers, migration_pairs: migrationPairs } = report;

  process.stdout.write('\n=== Validação de serviços legados (Portainer) ===\n');
  process.stdout.write(`Escopo: ${summary.scope_version}\n`);
  process.stdout.write(`Containers Korp analisados: ${summary.korp_containers_scanned}\n`);
  process.stdout.write(`Legados encontrados: ${summary.legacy_containers}\n`);
  process.stdout.write(`Pares legado+versionado: ${summary.migration_pairs}\n\n`);

  if (legacyContainers.length === 0) {
    process.stdout.write('Nenhum serviço legado encontrado.\n');
    return;
  }

  process.stdout.write('--- Serviços legados ---\n');
  for (const item of legacyContainers) {
    const codes = item.issues.map((issue) => issue.code).join(', ');
    process.stdout.write(`${item.container_name}\t${item.image}\t[${codes}]\n`);
  }

  if (migrationPairs.length > 0) {
    process.stdout.write('\n--- Candidatos a remoção manual ---\n');
    for (const pair of migrationPairs) {
      process.stdout.write(`${pair.base_name}: ${pair.legacy_containers.join(', ')}\n`);
      process.stdout.write(`  ${pair.recommendation}\n`);
    }
  }
}

async function main() {
  if (cli.help) {
    printHelp();
    return;
  }

  loadEnvFile(cli['env-file']);

  const baseUrl = resolvePortainerUrl(cli.url || process.env.PORTAINER_URL);
  const username = cli.username || process.env.PORTAINER_USER;
  const password = cli.password || process.env.PORTAINER_PASSWORD;
  const endpointId = cli.endpoint || process.env.PORTAINER_ENDPOINT || '2';
  const scopeVersion = cli.scope;

  if (!baseUrl) {
    throw new Error('URL do Portainer não informada. Use --url ou PORTAINER_URL no .env.');
  }

  if (!username || !password) {
    throw new Error(
      'Credenciais não informadas. Use --username/--password ou PORTAINER_USER/PORTAINER_PASSWORD.'
    );
  }

  const jwt = await authenticate(baseUrl, username, password);
  const containers = await listContainers(baseUrl, jwt, endpointId, cli['include-stopped']);

  const report = buildReport(containers, scopeVersion, {
    url: baseUrl,
    endpointId,
  });

  fs.writeFileSync(cli.output, `${JSON.stringify(report, null, 2)}\n`, 'utf8');
  printSummary(report);
  process.stderr.write(`\nRelatório salvo em ${cli.output}\n`);
}

if (require.main === module) {
  main().catch((error) => {
    process.stderr.write(`Erro: ${error.message}\n`);
    process.exit(1);
  });
}

module.exports = {
  classifyContainer,
  isKorpService,
  isIgnoredService,
  isYearBasedVersion,
  isLegacyImageTag,
  buildReport,
  authenticate,
  listContainers,
  portainerRequest,
  resolvePortainerUrl,
  loadEnvFile,
  normalizeContainerName,
  IGNORED_CONTAINER_NAMES,
  INFRA_CONTAINER_NAMES,
};
