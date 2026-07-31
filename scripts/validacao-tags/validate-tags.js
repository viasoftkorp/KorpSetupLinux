#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');
const https = require('https');
const http = require('http');
const os = require('os');
const { parseArgs } = require('util');

const REPO_ROOT = path.resolve(__dirname, '../..');
const ROLES_DIR = path.join(REPO_ROOT, 'roles');
const DEFAULT_ENV_PATH = fs.existsSync(path.join(__dirname, '.env'))
  ? path.join(__dirname, '.env')
  : path.join(__dirname, '../.env');
const DEFAULT_OUTPUT = path.join(__dirname, 'report.json');

const DOCKER_ACCOUNT_IMAGE_PREFIX = '{{ docker_account }}';
const IGNORED_IMAGE_NAMES = new Set(['korp.atualizacaosistema']);

const VERSION_WINDOWS = ['2025.1.0', '2024.2.0'];
const YEAR_VERSION_RE = /^(\d{4}\.\d+\.\d+)\.(\d+)$/;
const LEGACY_VERSION_RE = /^(\d+)\.(\d+)\.(\d+)$/;
const UTILITY_SUFFIX_RE = /-(documentation|cli|worker)$/i;

const DOMAIN_ROLE_NAMES = new Set([
  'vendas',
  'logistica',
  'engenharia',
  'compras',
  'fiscal',
  'financeiro',
  'faturamento',
  'qualidade',
  'contabil',
  'projetos',
  'workflow',
  'estoque-posicao',
]);

const ROLE_PREFIX_TO_DOMAIN = [
  [/^VEN/i, 'vendas'],
  [/^LOG/i, 'logistica'],
  [/^COM/i, 'compras'],
  [/^FAT/i, 'faturamento'],
  [/^FIN/i, 'financeiro'],
  [/^QUA/i, 'qualidade'],
  [/^CON/i, 'contabil'],
  [/^PROJ/i, 'projetos'],
  [/^PES/i, 'pessoas'],
  [/^ERP/i, 'erp'],
  [/^APS$/i, 'producao'],
  [/^PRO\d/i, 'producao'],
  [/^APV$/i, 'approval'],
  [/^ASD/i, 'assinatura'],
  [/^BPMN/i, 'projetos'],
  [/^CDP/i, 'vendas'],
  [/^TRAC/i, 'vendas'],
  [/^FLOW/i, 'flow'],
  [/^MOB/i, 'mobile'],
  [/^RMA/i, 'rma'],
  [/^REL/i, 'relatorios'],
  [/^PCRG/i, 'producao'],
  [/^DEV/i, 'sdk'],
];

const SERVICE_TOKEN_TO_DOMAIN = {
  vendas: 'vendas',
  sales: 'vendas',
  engenharia: 'engenharia',
  logistica: 'logistica',
  logistics: 'logistica',
  compras: 'compras',
  fiscal: 'fiscal',
  financeiro: 'financeiro',
  financial: 'financeiro',
  faturamento: 'faturamento',
  qualidade: 'qualidade',
  quality: 'qualidade',
  contabil: 'contabil',
  contabilidade: 'contabil',
  accounting: 'contabil',
  projetos: 'projetos',
  projects: 'projetos',
  producao: 'producao',
  production: 'producao',
  estoque: 'estoque',
  pessoas: 'pessoas',
  person: 'pessoas',
  erp: 'erp',
  approval: 'approval',
  administration: 'infrastructure',
  authentication: 'infrastructure',
  authorization: 'infrastructure',
  notification: 'infrastructure',
  emailing: 'infrastructure',
  flow: 'flow',
  webhook: 'sdk',
  appbuilder: 'sdk',
  sdk: 'sdk',
  apprise: 'infrastructure',
  assinatura: 'assinatura',
  digital: 'assinatura',
  bpmn: 'projetos',
  ecommerce: 'vendas',
  crm: 'vendas',
  tracking: 'vendas',
  custeioproduto: 'vendas',
  commercialproposal: 'vendas',
  picking: 'logistica',
  wms: 'logistica',
  aps: 'producao',
  mobile: 'mobile',
  rma: 'rma',
  geolocation: 'infrastructure',
  loader: 'infrastructure',
  analytics: 'analytics',
  elt: 'analytics',
  solidworks: 'engenharia',
  configuracoes: 'infrastructure',
  campospadroes: 'infrastructure',
  cargainicial: 'infrastructure',
  objectstorage: 'infrastructure',
  object: 'infrastructure',
  storage: 'infrastructure',
};

const GENERIC_SERVICE_TOKENS = new Set([
  'api',
  'gateway',
  'core',
  'legacy',
  'frontend',
  'web',
  'service',
  'client',
  'proxy',
  'worker',
  'cli',
  'documentation',
]);

const { values: cli } = parseArgs({
  options: {
    output: { type: 'string', default: DEFAULT_OUTPUT },
    'env-file': { type: 'string', default: DEFAULT_ENV_PATH },
    workers: { type: 'string' },
    'dry-run': { type: 'boolean', default: false },
    'skip-jenkins': { type: 'boolean', default: false },
    'skip-github': { type: 'boolean', default: false },
    'skip-bitbucket': { type: 'boolean', default: false },
    'list-services': { type: 'boolean', default: false },
    help: { type: 'boolean', short: 'h', default: false },
  },
});

function printHelp() {
  process.stdout.write(`Uso:
  node validate-tags.js [opções]

Valida tags de release no GitHub (monorepo por domínio) cruzando com a última
tag de cada janela no Bitbucket, para todos os serviços descobertos em
roles/*/templates/composes do KorpSetupLinux.

Opções:
  --output <arquivo>     Relatório JSON (padrão: report.json)
  --env-file <arquivo>   Credenciais (padrão: scripts/.env)
  --workers <n>          Requisições paralelas (padrão: auto)
  --dry-run              Descobre serviços e monta esqueleto sem APIs remotas
  --skip-jenkins         Não filtra por Job Jenkins
  --skip-github          Não consulta tags no GitHub
  --skip-bitbucket       Não consulta tags no Bitbucket
  --list-services        Lista serviços descobertos e encerra
  -h, --help             Exibe esta ajuda

Variáveis de ambiente:
  GITHUB_TOKEN
  BITBUCKET_USERNAME + BITBUCKET_APP_PASSWORD | BITBUCKET_API_TOKEN
  ORG_NAME
  JENKINS_URL, JENKINS_USER, JENKINS_TOKEN
`);
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
    if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(key)) {
      continue;
    }

    let value = trimmed.slice(separatorIndex + 1).trim();
    if (
      (value.startsWith('"') && value.endsWith('"')) ||
      (value.startsWith("'") && value.endsWith("'"))
    ) {
      value = value.slice(1, -1);
    }

    // Arquivo .env tem prioridade sobre variáveis já exportadas no shell.
    process.env[key] = value;
  }
}

function parseScalarValue(raw) {
  const trimmed = raw.trim();
  if (!trimmed) {
    return null;
  }

  if (
    (trimmed.startsWith('"') && trimmed.endsWith('"')) ||
    (trimmed.startsWith("'") && trimmed.endsWith("'"))
  ) {
    return trimmed.slice(1, -1);
  }

  return trimmed;
}

function parseServiceKeyLine(line) {
  const match = line.match(/^(\s*)(.+?):\s*$/);
  if (!match) {
    return null;
  }

  let key = match[2].trim();
  if (
    (key.startsWith('"') && key.endsWith('"')) ||
    (key.startsWith("'") && key.endsWith("'"))
  ) {
    key = key.slice(1, -1);
  }

  return key;
}

function extractFieldFromBlock(blockLines, fieldName) {
  const pattern = new RegExp(`^\\s+${fieldName}:\\s*(.*)$`);

  for (const line of blockLines) {
    const match = line.match(pattern);
    if (match) {
      return parseScalarValue(match[1]);
    }
  }

  return null;
}

function extractServicesFromCompose(content) {
  const lines = content.replace(/\{%[\s\S]*?%\}/g, '').split('\n');

  let servicesLineIndex = -1;
  for (let i = 0; i < lines.length; i += 1) {
    if (/^services:\s*$/.test(lines[i])) {
      servicesLineIndex = i;
      break;
    }
  }

  if (servicesLineIndex === -1) {
    return {};
  }

  const servicesIndent = lines[servicesLineIndex].match(/^(\s*)/)[1].length;

  let serviceIndent = null;
  for (let i = servicesLineIndex + 1; i < lines.length; i += 1) {
    const line = lines[i];
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith('#')) {
      continue;
    }

    const indent = line.match(/^(\s*)/)[1].length;
    if (indent <= servicesIndent) {
      break;
    }

    if (trimmed.endsWith(':') && !trimmed.startsWith('-')) {
      serviceIndent = indent;
      break;
    }
  }

  if (serviceIndent == null) {
    return {};
  }

  const propertyIndent = serviceIndent + 2;
  const services = {};
  let currentServiceName = null;
  let currentBlock = [];

  function flushService() {
    if (currentServiceName == null) {
      return;
    }

    services[currentServiceName] = {
      image: extractFieldFromBlock(currentBlock, 'image'),
      container_name: extractFieldFromBlock(currentBlock, 'container_name'),
    };
  }

  for (let i = servicesLineIndex + 1; i < lines.length; i += 1) {
    const line = lines[i];
    const trimmed = line.trim();

    if (!trimmed || trimmed.startsWith('#')) {
      continue;
    }

    const indent = line.match(/^(\s*)/)[1].length;
    if (indent <= servicesIndent) {
      break;
    }

    if (indent === serviceIndent && trimmed.endsWith(':') && !trimmed.startsWith('-')) {
      const serviceKey = parseServiceKeyLine(line);
      if (serviceKey != null) {
        flushService();
        currentServiceName = serviceKey;
        currentBlock = [];
        continue;
      }
    }

    if (currentServiceName != null && indent >= propertyIndent) {
      currentBlock.push(line);
    }
  }

  flushService();
  return services;
}

function getImageBaseName(image) {
  let name = String(image);
  const accountPrefix = `${DOCKER_ACCOUNT_IMAGE_PREFIX}/`;

  if (name.startsWith(accountPrefix)) {
    name = name.substring(accountPrefix.length);
  }

  const colonIndex = name.indexOf(':');
  if (colonIndex !== -1) {
    name = name.substring(0, colonIndex);
  }

  return name.toLowerCase();
}

function isEligibleImage(image) {
  if (image == null || image === '') {
    return false;
  }

  const imageStr = String(image);
  if (!imageStr.startsWith(DOCKER_ACCOUNT_IMAGE_PREFIX)) {
    return false;
  }

  const baseName = getImageBaseName(imageStr);
  if (IGNORED_IMAGE_NAMES.has(baseName)) {
    return false;
  }

  return /^(korp|viasoft|sdk)\./i.test(baseName);
}

function imageToJenkinsJob(imageName) {
  return imageName
    .split('.')
    .map((part) => part.replace(/(^|-)([a-z])/g, (_, separator, char) => `${separator}${char.toUpperCase()}`))
    .join('.');
}

function classifyTipoServico(serviceName) {
  const name = serviceName.toLowerCase();
  if (name.endsWith('-frontend') || /(^|[.-])frontend([.-]|$)/.test(name)) {
    return 'frontend';
  }
  if (UTILITY_SUFFIX_RE.test(name)) {
    return 'outros';
  }
  return 'backend';
}

function githubTagPrefix(serviceName, tipoServico) {
  const name = serviceName.toLowerCase();
  if (name.endsWith('-frontend') || name.includes('frontend')) {
    return `${name}-`;
  }
  if (tipoServico === 'frontend') {
    return `${name}-frontend-`;
  }
  return `${name}-`;
}

/** Chaves curtas de projeto Bitbucket → monorepo GitHub */
const BITBUCKET_PROJECT_TO_GITHUB = {
  ac: 'contabil',
  bil: 'faturamento',
  en: 'engenharia',
  erp: 'erp',
  fa: 'financeiro',
  in: 'infrastructure',
  log: 'logistica',
  mc: 'mobile',
  pow: 'analytics',
  prod: 'producao',
  pur: 'compras',
  qa: 'qualidade',
  qm: 'qualidade',
  sal: 'vendas',
  sdk: 'sdk',
  tm: 'fiscal',
};

const KNOWN_GITHUB_DOMAINS = new Set([
  'vendas',
  'logistica',
  'engenharia',
  'compras',
  'fiscal',
  'financeiro',
  'faturamento',
  'qualidade',
  'contabil',
  'projetos',
  'erp',
  'sdk',
  'rma',
  'mobile',
  'producao',
  'infrastructure',
  'approval',
  'flow',
  'analytics',
  'assinatura',
  'pessoas',
  'estoque',
  'workflow',
  'relatorios',
]);

function inferDomainFromServiceName(serviceName) {
  const normalized = serviceName.toLowerCase().replace(/^(korp|viasoft|sdk)\./, '');
  const tokens = normalized.split(/[._-]+/).filter(Boolean);

  for (const token of tokens) {
    if (GENERIC_SERVICE_TOKENS.has(token)) {
      continue;
    }
    if (SERVICE_TOKEN_TO_DOMAIN[token]) {
      return SERVICE_TOKEN_TO_DOMAIN[token];
    }
  }

  // Fallback: tokens genéricos só se não houver domínio mais específico
  for (const token of tokens) {
    if (token === 'gateway') {
      return 'engenharia';
    }
  }

  return null;
}

/**
 * Converte chave de projeto Bitbucket / chute local no nome real do monorepo GitHub.
 * Ex.: "en" → "engenharia", "sal" → "vendas".
 */
function normalizeGithubDomain(candidate, service) {
  const raw = String(candidate || '').toLowerCase().trim();

  if (KNOWN_GITHUB_DOMAINS.has(raw)) {
    return raw;
  }

  if (BITBUCKET_PROJECT_TO_GITHUB[raw]) {
    return BITBUCKET_PROJECT_TO_GITHUB[raw];
  }

  const fromService = inferDomainFromServiceName(service?.servico_bitbucket || '');
  if (fromService) {
    return fromService;
  }

  const fromGuess = String(service?.dominio_github || '').toLowerCase().trim();
  if (KNOWN_GITHUB_DOMAINS.has(fromGuess)) {
    return fromGuess;
  }
  if (BITBUCKET_PROJECT_TO_GITHUB[fromGuess]) {
    return BITBUCKET_PROJECT_TO_GITHUB[fromGuess];
  }

  return raw || fromGuess || 'desconhecido';
}

const ROLE_NAME_TO_DOMAIN = {
  'campos-padroes': 'infrastructure',
  'carga-inicial': 'infrastructure',
  'object-storage': 'infrastructure',
  'analytics-local': 'analytics',
  'api-gateway': 'engenharia',
  'integration-ecommerce': 'vendas',
  'indexador-moedas': 'financeiro',
  apprise: 'infrastructure',
  temporal: 'infrastructure',
  svix: 'infrastructure',
  geolocation: 'infrastructure',
  solidworks: 'engenharia',
  workflow: 'workflow',
};

function inferDomainFromRole(roleName) {
  const lower = roleName.toLowerCase();
  if (ROLE_NAME_TO_DOMAIN[lower]) {
    return ROLE_NAME_TO_DOMAIN[lower];
  }

  if (DOMAIN_ROLE_NAMES.has(lower)) {
    return lower === 'estoque-posicao' ? 'estoque' : lower;
  }

  for (const [pattern, domain] of ROLE_PREFIX_TO_DOMAIN) {
    if (pattern.test(roleName)) {
      return domain;
    }
  }

  if (lower.startsWith('infrastructure')) {
    return 'infrastructure';
  }

  return null;
}

function listRoleDirectories() {
  if (!fs.existsSync(ROLES_DIR)) {
    return [];
  }

  return fs
    .readdirSync(ROLES_DIR, { withFileTypes: true })
    .filter((entry) => entry.isDirectory())
    .map((entry) => entry.name)
    .sort();
}

function walkComposeFiles(roleName) {
  const composesDir = path.join(ROLES_DIR, roleName, 'templates', 'composes');
  if (!fs.existsSync(composesDir)) {
    return [];
  }

  const files = [];

  function visitDir(currentDir) {
    for (const entry of fs.readdirSync(currentDir, { withFileTypes: true })) {
      const fullPath = path.join(currentDir, entry.name);
      if (entry.isDirectory()) {
        visitDir(fullPath);
        continue;
      }

      if (!entry.isFile() || !entry.name.endsWith('.yml.j2')) {
        continue;
      }

      const relativeInsideComposes = path.relative(composesDir, fullPath);
      const parts = relativeInsideComposes.split(path.sep);
      const versionFolder =
        parts.length > 1 && /^\d{4}\.\d+\.\d+$/.test(parts[0]) ? parts[0] : null;

      files.push({
        role: roleName,
        filePath: fullPath,
        relativePath: path.relative(REPO_ROOT, fullPath).split(path.sep).join('/'),
        versionFolder,
        exclusive: versionFolder == null,
      });
    }
  }

  visitDir(composesDir);
  return files;
}

function discoverServicesFromRoles() {
  const byImage = new Map();

  for (const role of listRoleDirectories()) {
    const domainFromRole = inferDomainFromRole(role);

    for (const composeFile of walkComposeFiles(role)) {
      const content = fs.readFileSync(composeFile.filePath, 'utf8');
      const services = extractServicesFromCompose(content);

      for (const [serviceKey, serviceConfig] of Object.entries(services)) {
        if (!isEligibleImage(serviceConfig.image)) {
          continue;
        }

        const image = getImageBaseName(serviceConfig.image);
        const tipoServico = classifyTipoServico(image);
        const domainGuess =
          inferDomainFromServiceName(image) || domainFromRole || 'desconhecido';

        if (!byImage.has(image)) {
          byImage.set(image, {
            servico_bitbucket: image,
            jenkins_job: imageToJenkinsJob(image),
            tipo_servico: tipoServico,
            dominio_github: domainGuess,
            roles: new Set(),
            files: new Set(),
            service_keys: new Set(),
            compose_versions: new Set(),
            exclusive_compose: false,
            versioned_compose: false,
          });
        }

        const entry = byImage.get(image);
        entry.roles.add(role);
        entry.files.add(composeFile.relativePath);
        entry.service_keys.add(serviceKey);

        if (composeFile.versionFolder) {
          entry.compose_versions.add(composeFile.versionFolder);
          entry.versioned_compose = true;
        } else {
          entry.exclusive_compose = true;
        }

        if (entry.dominio_github === 'desconhecido' && domainGuess !== 'desconhecido') {
          entry.dominio_github = domainGuess;
        }
      }
    }
  }

  return [...byImage.values()]
    .map((entry) => ({
      ...entry,
      roles: [...entry.roles].sort(),
      files: [...entry.files].sort(),
      service_keys: [...entry.service_keys].sort(),
      compose_versions: [...entry.compose_versions].sort(),
      // Exclusivo puro: só aparece na raiz dos composes, sem pasta de versão.
      exclusive_only: entry.exclusive_compose && !entry.versioned_compose,
    }))
    .sort((a, b) => a.servico_bitbucket.localeCompare(b.servico_bitbucket));
}

function resolveMaxWorkers(requestedWorkers, itemCount) {
  if (requestedWorkers != null) {
    const parsed = Number.parseInt(String(requestedWorkers), 10);
    if (!Number.isNaN(parsed) && parsed > 0) {
      return parsed;
    }
  }

  const cpuCount = os.cpus().length || 4;
  return Math.min(12, Math.max(3, Math.min(itemCount, cpuCount * 2)));
}

function httpRequest(urlString, { method = 'GET', headers = {}, timeoutMs = 45000 } = {}) {
  return new Promise((resolve, reject) => {
    const url = new URL(urlString);
    const transport = url.protocol === 'https:' ? https : http;

    const request = transport.request(
      url,
      {
        method,
        headers,
        timeout: timeoutMs,
      },
      (response) => {
        let body = '';
        response.on('data', (chunk) => {
          body += chunk;
        });
        response.on('end', () => {
          resolve({
            status: response.statusCode ?? 0,
            headers: response.headers,
            body,
          });
        });
      }
    );

    request.on('timeout', () => {
      request.destroy(new Error(`Timeout ao consultar ${urlString}`));
    });
    request.on('error', reject);
    request.end();
  });
}

async function runWithConcurrency(items, worker, maxWorkers) {
  const results = new Array(items.length);
  let nextIndex = 0;

  async function workerLoop() {
    while (nextIndex < items.length) {
      const index = nextIndex;
      nextIndex += 1;
      results[index] = await worker(items[index], index);
    }
  }

  const workers = Array.from({ length: Math.min(maxWorkers, Math.max(items.length, 1)) }, () =>
    workerLoop()
  );
  await Promise.all(workers);
  return results;
}

function resolveJenkinsConfig() {
  const url = (process.env.JENKINS_URL || '').replace(/\/$/, '');
  const user = process.env.JENKINS_USER || '';
  const token = process.env.JENKINS_TOKEN || '';

  if (!url || !user || !token) {
    throw new Error(
      'Configure JENKINS_URL, JENKINS_USER e JENKINS_TOKEN no ambiente ou no arquivo .env'
    );
  }

  return { url, user, token };
}

function resolveGitHubConfig() {
  const token = process.env.GITHUB_TOKEN || '';
  const org = process.env.ORG_NAME || process.env.GITHUB_ORG || '';

  if (!token || !org) {
    throw new Error('Configure GITHUB_TOKEN e ORG_NAME no ambiente ou no arquivo .env');
  }

  return { token, org };
}

function resolveBitbucketConfig() {
  const username = process.env.BITBUCKET_USERNAME || '';
  const password =
    process.env.BITBUCKET_API_TOKEN ||
    process.env.BITBUCKET_APP_PASSWORD ||
    process.env.BITBUCKET_TOKEN ||
    '';
  const workspace = process.env.ORG_NAME || process.env.BITBUCKET_WORKSPACE || '';

  if (!username || !password || !workspace) {
    throw new Error(
      'Configure BITBUCKET_USERNAME, BITBUCKET_APP_PASSWORD|BITBUCKET_API_TOKEN e ORG_NAME'
    );
  }

  return { username, password, workspace };
}

function basicAuthHeader(user, password) {
  return `Basic ${Buffer.from(`${user}:${password}`).toString('base64')}`;
}

async function jenkinsJobStatus(jenkinsConfig, jobName) {
  const url = `${jenkinsConfig.url}/job/${encodeURIComponent(jobName)}/api/json?tree=jobs[name]`;
  try {
    const { status, body } = await httpRequest(url, {
      headers: {
        Authorization: basicAuthHeader(jenkinsConfig.user, jenkinsConfig.token),
      },
    });

    if (status === 200) {
      let branches = [];
      try {
        const parsed = JSON.parse(body);
        branches = (parsed.jobs || []).map((job) => decodeURIComponent(job.name));
      } catch {
        branches = [];
      }
      return { ok: true, motivo: null, branches };
    }
    if (status === 404) {
      return { ok: false, motivo: 'jenkins_404', branches: [] };
    }
    return { ok: false, motivo: 'jenkins_erro', detalhe: `HTTP ${status}`, branches: [] };
  } catch (error) {
    return { ok: false, motivo: 'jenkins_erro', detalhe: error.message, branches: [] };
  }
}

/**
 * Converte branches Jenkins release/YYYY.N.0.x nas janelas alvo do validador.
 * Só janelas presentes em VERSION_WINDOWS são consideradas.
 * Retorna [] se nenhuma release das janelas alvo existir no Job.
 */
function windowsFromJenkinsBranches(branches, versionWindows = VERSION_WINDOWS) {
  const found = new Set();

  for (const branch of branches || []) {
    const match = String(branch).match(/(?:^|\/)release\/(\d{4}\.\d+\.\d+)\.x$/i);
    if (!match) {
      continue;
    }
    if (versionWindows.includes(match[1])) {
      found.add(match[1]);
    }
  }

  return versionWindows.filter((windowBase) => found.has(windowBase));
}

/**
 * Define quais janelas o serviço realmente deve ter tag no GitHub.
 *
 * - Frontends / versionados em pasta de compose: interseção Jenkins ∩ pastas.
 * - Exclusivos (só raiz do compose): não herdam releases do sibling -frontend.
 *   Usam janelas do Bitbucket ∩ Jenkins; sem histórico por ano, só a mais recente no Jenkins.
 */
function resolveExpectedWindows(service, bitbucketVersions = [], versionWindows = VERSION_WINDOWS) {
  const jenkinsWindowsRaw = windowsFromJenkinsBranches(
    service.jenkins_branches || [],
    versionWindows
  );
  const jenkinsWindows =
    jenkinsWindowsRaw.length > 0 ? jenkinsWindowsRaw : [...versionWindows];

  const composeWindows = (service.compose_versions || []).filter((version) =>
    versionWindows.includes(version)
  );

  if (composeWindows.length > 0 && !service.exclusive_only) {
    const intersect = jenkinsWindows.filter((windowBase) =>
      composeWindows.includes(windowBase)
    );
    return intersect.length > 0 ? intersect : composeWindows;
  }

  // Serviço exclusivo (ou sem pastas de versão): não exigir janelas só porque
  // o Job Jenkins compartilhado tem release do frontend.
  const bbWindows = versionWindows.filter(
    (windowBase) => pickLatestForWindow(bitbucketVersions, windowBase) != null
  );

  if (bbWindows.length > 0) {
    const intersect = jenkinsWindows.filter((windowBase) => bbWindows.includes(windowBase));
    return intersect.length > 0 ? intersect : bbWindows;
  }

  const newestJenkins = versionWindows.find((windowBase) =>
    jenkinsWindows.includes(windowBase)
  );
  return newestJenkins ? [newestJenkins] : [...versionWindows];
}

function buildWindowReference(versions, { expectedWindows = null, markNotApplicable = false } = {}) {
  const referencia = {};
  for (const windowBase of VERSION_WINDOWS) {
    const key = `janela_${windowBase}.x`;
    const latest = pickLatestForWindow(versions, windowBase);
    if (latest) {
      referencia[key] = latest;
      continue;
    }

    const isExpected =
      expectedWindows == null || expectedWindows.includes(windowBase);
    if (markNotApplicable && !isExpected) {
      referencia[key] = 'Não aplicável';
    } else {
      referencia[key] = 'Não encontrada';
    }
  }
  return referencia;
}

async function fetchJenkinsJobs(jenkinsConfig) {
  const { status, body } = await httpRequest(
    `${jenkinsConfig.url}/api/json?tree=jobs[name]`,
    {
      headers: {
        Authorization: basicAuthHeader(jenkinsConfig.user, jenkinsConfig.token),
      },
    }
  );

  if (status !== 200) {
    throw new Error(`Falha ao listar jobs Jenkins (HTTP ${status})`);
  }

  const parsed = JSON.parse(body);
  return new Set((parsed.jobs || []).map((job) => job.name));
}

function findKnownJob(knownJobs, candidates) {
  for (const candidate of candidates) {
    if (knownJobs.has(candidate)) {
      return candidate;
    }
  }

  const jobsByLowerCase = new Map([...knownJobs].map((job) => [job.toLowerCase(), job]));
  for (const candidate of candidates) {
    const match = jobsByLowerCase.get(candidate.toLowerCase());
    if (match) {
      return match;
    }
  }

  return null;
}

function buildJobCandidates(service) {
  const candidates = [service.jenkins_job];

  const simpleTitleCase = service.servico_bitbucket
    .split('.')
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join('.');

  if (!candidates.includes(simpleTitleCase)) {
    candidates.push(simpleTitleCase);
  }

  if (!candidates.includes(service.servico_bitbucket)) {
    candidates.push(service.servico_bitbucket);
  }

  return candidates;
}

async function filterByJenkins(services, jenkinsConfig, workers) {
  const knownJobs = await fetchJenkinsJobs(jenkinsConfig);
  const maxWorkers = resolveMaxWorkers(workers, services.length);
  const analyzed = [];
  const semJob = [];

  await runWithConcurrency(
    services,
    async (service) => {
      const candidates = buildJobCandidates(service);
      const resolvedJob = findKnownJob(knownJobs, candidates);
      const jobName = resolvedJob ?? service.jenkins_job;
      const status = await jenkinsJobStatus(jenkinsConfig, jobName);

      if (status.ok) {
        analyzed.push({
          ...service,
          jenkins_job: jobName,
          jenkins_branches: (status.branches || []).filter((branch) =>
            /release\//i.test(branch)
          ),
        });
      } else {
        semJob.push({
          dominio_github: service.dominio_github,
          servico_bitbucket: service.servico_bitbucket,
          tipo_servico: service.tipo_servico,
          motivo: status.motivo,
          ...(status.detalhe ? { detalhe: status.detalhe } : {}),
        });
      }
    },
    maxWorkers
  );

  analyzed.sort((a, b) => a.servico_bitbucket.localeCompare(b.servico_bitbucket));
  semJob.sort((a, b) => a.servico_bitbucket.localeCompare(b.servico_bitbucket));
  return { analyzed, semJob };
}

function parseLinkHeader(linkHeader) {
  if (!linkHeader) {
    return {};
  }

  const links = {};
  for (const part of String(linkHeader).split(',')) {
    const match = part.match(/<([^>]+)>;\s*rel="([^"]+)"/);
    if (match) {
      links[match[2]] = match[1];
    }
  }
  return links;
}

async function fetchGitHubTags(githubConfig, repo, cache) {
  const cacheKey = repo.toLowerCase();
  if (cache.has(cacheKey)) {
    return cache.get(cacheKey);
  }

  const tags = [];
  let url = `https://api.github.com/repos/${encodeURIComponent(githubConfig.org)}/${encodeURIComponent(repo)}/tags?per_page=100`;

  while (url) {
    const { status, body, headers } = await httpRequest(url, {
      headers: {
        Authorization: `Bearer ${githubConfig.token}`,
        Accept: 'application/vnd.github+json',
        'User-Agent': 'korp-validacao-tags',
      },
    });

    if (status === 404) {
      cache.set(cacheKey, { exists: false, tags: [], error: null });
      return cache.get(cacheKey);
    }

    if (status === 401 || status === 403) {
      throw new Error(`GitHub autenticacao/autorizacao falhou (HTTP ${status}) para ${repo}`);
    }

    if (status !== 200) {
      cache.set(cacheKey, {
        exists: false,
        tags: [],
        error: `HTTP ${status}: ${body.slice(0, 200)}`,
      });
      return cache.get(cacheKey);
    }

    const page = JSON.parse(body);
    for (const item of page) {
      if (item?.name) {
        tags.push(item.name);
      }
    }

    const links = parseLinkHeader(headers.link);
    url = links.next || null;
  }

  cache.set(cacheKey, { exists: true, tags, error: null });
  return cache.get(cacheKey);
}

async function fetchBitbucketTags(bitbucketConfig, repoSlug, cache) {
  const cacheKey = repoSlug.toLowerCase();
  if (cache.has(cacheKey)) {
    return cache.get(cacheKey);
  }

  const tags = [];
  let projectKey = null;
  let url =
    `https://api.bitbucket.org/2.0/repositories/${encodeURIComponent(bitbucketConfig.workspace)}/` +
    `${encodeURIComponent(repoSlug)}/refs/tags?pagelen=100`;

  while (url) {
    const { status, body } = await httpRequest(url, {
      headers: {
        Authorization: basicAuthHeader(bitbucketConfig.username, bitbucketConfig.password),
        Accept: 'application/json',
      },
    });

    if (status === 404) {
      cache.set(cacheKey, { exists: false, tags: [], projectKey: null, error: null });
      return cache.get(cacheKey);
    }

    if (status === 401 || status === 403) {
      throw new Error(`Bitbucket autenticacao/autorizacao falhou (HTTP ${status}) para ${repoSlug}`);
    }

    if (status !== 200) {
      let message = `HTTP ${status}`;
      try {
        const parsedError = JSON.parse(body);
        message = parsedError?.error?.message || message;
      } catch {
        // ignore
      }
      cache.set(cacheKey, {
        exists: false,
        tags: [],
        projectKey: null,
        error: message,
      });
      return cache.get(cacheKey);
    }

    const parsed = JSON.parse(body);
    for (const item of parsed.values || []) {
      if (item?.name) {
        tags.push(item.name);
      }
    }
    url = parsed.next || null;
  }

  const repoMeta = await httpRequest(
    `https://api.bitbucket.org/2.0/repositories/${encodeURIComponent(bitbucketConfig.workspace)}/${encodeURIComponent(repoSlug)}`,
    {
      headers: {
        Authorization: basicAuthHeader(bitbucketConfig.username, bitbucketConfig.password),
        Accept: 'application/json',
      },
    }
  );

  if (repoMeta.status === 200) {
    try {
      const meta = JSON.parse(repoMeta.body);
      projectKey = meta?.project?.key ? String(meta.project.key).toLowerCase() : null;
    } catch {
      projectKey = null;
    }
  }

  cache.set(cacheKey, { exists: true, tags, projectKey, error: null });
  return cache.get(cacheKey);
}

function stripTagPrefix(tagName) {
  return String(tagName).replace(/^v/i, '');
}

/**
 * Extrai a versão de uma tag GitHub no formato `{servico}-{versao}`.
 * Exige que, após o prefixo do serviço, venha imediatamente a versão numérica —
 * evita falso positivo de backend casando tag de frontend
 * (`servico-frontend-2025.1.0.1` não vale para `servico-`).
 */
function extractVersionFromGithubTag(tagName, prefix) {
  const tag = String(tagName);
  const normalizedPrefix = String(prefix);

  if (tag.length <= normalizedPrefix.length) {
    return null;
  }

  if (tag.slice(0, normalizedPrefix.length).toLowerCase() !== normalizedPrefix.toLowerCase()) {
    return null;
  }

  const versionPart = stripTagPrefix(tag.slice(normalizedPrefix.length));
  if (!/^\d+\.\d+\.\d+/.test(versionPart)) {
    return null;
  }

  return versionPart;
}

function tagBelongsToService(tagName, prefix) {
  return extractVersionFromGithubTag(tagName, prefix) != null;
}

function collectServiceVersions(tagNames, { githubPrefix = null } = {}) {
  const versions = [];

  for (const tag of tagNames) {
    let version = null;
    if (githubPrefix) {
      version = extractVersionFromGithubTag(tag, githubPrefix);
    } else {
      version = stripTagPrefix(tag);
    }

    if (!version) {
      continue;
    }

    versions.push(version);
  }

  return versions;
}

function compareVersionParts(aParts, bParts) {
  const len = Math.max(aParts.length, bParts.length);
  for (let i = 0; i < len; i += 1) {
    const a = aParts[i] ?? 0;
    const b = bParts[i] ?? 0;
    if (a !== b) {
      return a - b;
    }
  }
  return 0;
}

function parseComparableVersion(version) {
  const year = version.match(YEAR_VERSION_RE);
  if (year) {
    return {
      kind: 'year',
      window: year[1],
      parts: [...year[1].split('.').map(Number), Number(year[2])],
      raw: version,
    };
  }

  const legacy = version.match(LEGACY_VERSION_RE);
  if (legacy) {
    return {
      kind: 'legacy',
      window: null,
      parts: legacy.slice(1).map(Number),
      raw: version,
    };
  }

  return null;
}

function pickLatestVersion(versions) {
  let best = null;
  for (const version of versions) {
    const parsed = parseComparableVersion(version);
    if (!parsed) {
      continue;
    }
    if (!best || compareVersionParts(parsed.parts, best.parts) > 0) {
      best = parsed;
    }
  }
  return best ? best.raw : null;
}

function pickLatestForWindow(versions, windowBase) {
  const matching = versions.filter((version) => {
    const parsed = parseComparableVersion(version);
    return parsed?.kind === 'year' && parsed.window === windowBase;
  });
  return pickLatestVersion(matching);
}

function detectCategoria(versions) {
  const hasYear = versions.some((version) => parseComparableVersion(version)?.kind === 'year');
  return hasYear ? 'versionados' : 'nao-versionados';
}

function buildAbsoluteReference(versions) {
  return {
    ultima_tag_absoluta: pickLatestVersion(versions) || 'Não encontrada',
  };
}

function evaluateService({
  service,
  githubTags,
  bitbucketTags,
  dominioResolvido,
  janelasEsperadas = null,
}) {
  const prefix = githubTagPrefix(service.servico_bitbucket, service.tipo_servico);
  const githubVersions = collectServiceVersions(githubTags, { githubPrefix: prefix });
  const bitbucketVersions = collectServiceVersions(bitbucketTags);

  const expectedWindows = (
    Array.isArray(janelasEsperadas) && janelasEsperadas.length > 0
      ? janelasEsperadas
      : resolveExpectedWindows(service, bitbucketVersions)
  ).filter((windowBase) => VERSION_WINDOWS.includes(windowBase));

  const effectiveExpected =
    expectedWindows.length > 0 ? expectedWindows : [...VERSION_WINDOWS];

  // Categoria segue o histórico do Bitbucket (ou GitHub se BB vazio).
  const categoriaSource = bitbucketVersions.length ? bitbucketVersions : githubVersions;
  const categoria = detectCategoria(categoriaSource);
  const temTagGithub = githubVersions.length > 0;

  const referenciaGithub = buildWindowReference(githubVersions, {
    expectedWindows: effectiveExpected,
    markNotApplicable: true,
  });

  let referenciaBitbucket;
  if (categoria === 'versionados') {
    referenciaBitbucket = buildWindowReference(bitbucketVersions, {
      expectedWindows: effectiveExpected,
      markNotApplicable: true,
    });
  } else {
    referenciaBitbucket = {
      ...buildAbsoluteReference(bitbucketVersions),
      ...buildWindowReference(bitbucketVersions, {
        expectedWindows: effectiveExpected,
        markNotApplicable: true,
      }),
    };
  }

  const janelasAusentes = [];
  for (const windowBase of effectiveExpected) {
    const key = `janela_${windowBase}.x`;
    if (referenciaGithub[key] === 'Não encontrada') {
      janelasAusentes.push(`${windowBase}.x`);
    }
  }

  let consistente = true;
  let statusGithub = null;

  if (!temTagGithub) {
    consistente = false;
    statusGithub = 'Nenhuma tag encontrada no repositório do domínio';
  } else if (janelasAusentes.length) {
    consistente = false;
    statusGithub = `Janela(s) ausente(s) no GitHub: ${janelasAusentes.join(', ')}`;
  }

  const result = {
    dominio_github: dominioResolvido,
    servico_bitbucket: service.servico_bitbucket,
    categoria,
    tipo_servico: service.tipo_servico,
    tem_tag_github: temTagGithub,
    exclusive_only: Boolean(service.exclusive_only),
    compose_versions: service.compose_versions || [],
    janelas_esperadas: effectiveExpected.map((windowBase) => `${windowBase}.x`),
    referencia_bitbucket: referenciaBitbucket,
    referencia_github: referenciaGithub,
    consistente,
  };

  if (statusGithub) {
    result.status_github = statusGithub;
  }
  if (janelasAusentes.length) {
    result.janelas_ausentes = janelasAusentes;
  }

  return result;
}

async function listGitHubOrgRepos(githubConfig) {
  const repos = [];
  let page = 1;

  while (true) {
    const url =
      `https://api.github.com/orgs/${encodeURIComponent(githubConfig.org)}/repos` +
      `?per_page=100&page=${page}&type=all`;
    const { status, body } = await httpRequest(url, {
      headers: {
        Authorization: `Bearer ${githubConfig.token}`,
        Accept: 'application/vnd.github+json',
        'User-Agent': 'korp-validacao-tags',
      },
    });

    if (status !== 200) {
      throw new Error(`Falha ao listar repositórios GitHub (HTTP ${status}): ${body.slice(0, 200)}`);
    }

    const batch = JSON.parse(body);
    if (!Array.isArray(batch) || batch.length === 0) {
      break;
    }

    for (const repo of batch) {
      if (repo?.name) {
        repos.push(repo.name);
      }
    }

    if (batch.length < 100) {
      break;
    }
    page += 1;
  }

  return repos;
}

async function resolveDomainForService(service, {
  bitbucketConfig,
  githubConfig,
  bitbucketCache,
  githubTagCache,
  githubRepos,
  skipBitbucket,
  skipGithub,
}) {
  let bitbucket = bitbucketCache.get(service.servico_bitbucket.toLowerCase()) || null;
  let candidate = service.dominio_github;

  if (!skipBitbucket && bitbucketConfig) {
    bitbucket = await fetchBitbucketTags(
      bitbucketConfig,
      service.servico_bitbucket,
      bitbucketCache
    );
    if (bitbucket.projectKey) {
      // Nunca usar a chave curta do Bitbucket (ex: "en") como nome do repo GitHub.
      candidate = bitbucket.projectKey;
    }
  }

  const dominioNormalizado = normalizeGithubDomain(candidate, service);

  if (!skipGithub && githubConfig) {
    const prefix = githubTagPrefix(service.servico_bitbucket, service.tipo_servico);
    const preferred = [
      dominioNormalizado,
      normalizeGithubDomain(service.dominio_github, service),
      inferDomainFromServiceName(service.servico_bitbucket),
      service.dominio_github,
    ].filter(Boolean);

    const orderedRepos = [
      ...new Set([
        ...preferred,
        ...(githubRepos || []),
      ]),
    ];

    for (const repo of orderedRepos) {
      if (repo === 'KorpSetupLinux' || /docs|documentation|scoop|continue/i.test(repo)) {
        continue;
      }

      const gh = await fetchGitHubTags(githubConfig, repo, githubTagCache);
      if (!gh.exists) {
        continue;
      }

      const hasServiceTag = gh.tags.some((tag) => tagBelongsToService(tag, prefix));
      if (hasServiceTag) {
        return {
          dominio: repo.toLowerCase(),
          bitbucket,
        };
      }
    }
  }

  return {
    dominio: dominioNormalizado,
    bitbucket,
  };
}

function buildReport({
  discovered,
  analyzed,
  semJob,
  servicos,
}) {
  const inconsistentes = servicos.filter((item) => !item.consistente);
  const semTag = inconsistentes.filter((item) => !item.tem_tag_github);
  const comJanelasAusentes = inconsistentes.filter(
    (item) => Array.isArray(item.janelas_ausentes) && item.janelas_ausentes.length > 0
  );

  return {
    timestamp: new Date().toISOString(),
    resumo: {
      total_descobertos: discovered.length,
      total_analisados: analyzed.length,
      sem_job_jenkins: semJob.length,
      consistentes: servicos.filter((item) => item.consistente).length,
      inconsistentes: inconsistentes.length,
      com_tag_github: servicos.filter((item) => item.tem_tag_github).length,
      sem_tag_github: servicos.filter((item) => !item.tem_tag_github).length,
      com_janelas_ausentes: comJanelasAusentes.length,
    },
    servicos,
    servicos_sem_tag_no_github: semTag,
    servicos_com_janelas_ausentes: comJanelasAusentes,
    servicos_sem_job_jenkins: semJob,
  };
}

function printConsoleSummary(report) {
  const { resumo } = report;
  process.stdout.write('\n=== Validação de Tags ===\n');
  process.stdout.write(`Descobertos: ${resumo.total_descobertos}\n`);
  process.stdout.write(`Analisados (com Job Jenkins): ${resumo.total_analisados}\n`);
  process.stdout.write(`Sem Job Jenkins: ${resumo.sem_job_jenkins}\n`);
  process.stdout.write(`Consistentes: ${resumo.consistentes}\n`);
  process.stdout.write(`Inconsistentes: ${resumo.inconsistentes}\n`);
  process.stdout.write(`Sem tag no GitHub: ${resumo.sem_tag_github}\n`);
  process.stdout.write(`Com janelas ausentes: ${resumo.com_janelas_ausentes}\n\n`);
}

async function main() {
  if (cli.help) {
    printHelp();
    return;
  }

  loadEnvFile(cli['env-file']);

  const discovered = discoverServicesFromRoles();
  process.stderr.write(
    `Descobertos ${discovered.length} serviços elegíveis em roles/*/templates/composes\n`
  );

  if (cli['list-services']) {
    for (const service of discovered) {
      process.stdout.write(
        `${service.servico_bitbucket}\t${service.tipo_servico}\t${service.dominio_github}\t[${service.roles.join(',')}]\n`
      );
    }
    return;
  }

  let analyzed = discovered;
  let semJob = [];

  if (!cli['skip-jenkins'] && !cli['dry-run']) {
    process.stderr.write('Filtrando serviços com Job ativo no Jenkins...\n');
    const jenkinsConfig = resolveJenkinsConfig();
    const filtered = await filterByJenkins(discovered, jenkinsConfig, cli.workers);
    analyzed = filtered.analyzed;
    semJob = filtered.semJob;
    process.stderr.write(
      `Jenkins: ${analyzed.length} com job, ${semJob.length} sem job/erro\n`
    );
  } else if (cli['dry-run'] || cli['skip-jenkins']) {
    process.stderr.write('Filtro Jenkins ignorado (--dry-run/--skip-jenkins)\n');
  }

  if (cli['dry-run']) {
    const skeleton = analyzed.map((service) => ({
      dominio_github: service.dominio_github,
      servico_bitbucket: service.servico_bitbucket,
      categoria: 'versionados',
      tipo_servico: service.tipo_servico,
      tem_tag_github: false,
      referencia_bitbucket: Object.fromEntries(
        VERSION_WINDOWS.map((windowBase) => [`janela_${windowBase}.x`, 'Não consultado'])
      ),
      referencia_github: Object.fromEntries(
        VERSION_WINDOWS.map((windowBase) => [`janela_${windowBase}.x`, 'Não consultado'])
      ),
      consistente: false,
      status_github: 'dry-run',
      roles: service.roles,
    }));

    const report = buildReport({
      discovered,
      analyzed,
      semJob,
      servicos: skeleton,
    });
    fs.writeFileSync(cli.output, `${JSON.stringify(report, null, 2)}\n`, 'utf8');
    printConsoleSummary(report);
    process.stderr.write(`Relatório (dry-run) salvo em ${cli.output}\n`);
    return;
  }

  const skipGithub = cli['skip-github'];
  const skipBitbucket = cli['skip-bitbucket'];
  const githubConfig = skipGithub ? null : resolveGitHubConfig();
  const bitbucketConfig = skipBitbucket ? null : resolveBitbucketConfig();

  const bitbucketCache = new Map();
  const githubTagCache = new Map();
  let githubRepos = [];

  if (!skipGithub) {
    process.stderr.write('Listando repositórios da organização no GitHub...\n');
    try {
      githubRepos = await listGitHubOrgRepos(githubConfig);
      process.stderr.write(`GitHub: ${githubRepos.length} repositórios\n`);
    } catch (error) {
      process.stderr.write(`Aviso: falha ao listar repos GitHub (${error.message})\n`);
      githubRepos = [];
    }
  }

  const maxWorkers = resolveMaxWorkers(cli.workers, analyzed.length);
  process.stderr.write(`Validando tags de ${analyzed.length} serviços...\n`);

  const servicos = await runWithConcurrency(
    analyzed,
    async (service) => {
      const resolved = await resolveDomainForService(service, {
        bitbucketConfig,
        githubConfig,
        bitbucketCache,
        githubTagCache,
        githubRepos,
        skipBitbucket,
        skipGithub,
      });

      let bitbucketTags = [];
      if (!skipBitbucket) {
        const bb =
          resolved.bitbucket ||
          (await fetchBitbucketTags(
            bitbucketConfig,
            service.servico_bitbucket,
            bitbucketCache
          ));
        bitbucketTags = bb.tags || [];
      }

      let githubTags = [];
      if (!skipGithub) {
        const gh = await fetchGitHubTags(
          githubConfig,
          resolved.dominio,
          githubTagCache
        );
        githubTags = gh.tags || [];
      }

      return evaluateService({
        service,
        githubTags,
        bitbucketTags,
        dominioResolvido: resolved.dominio,
      });
    },
    maxWorkers
  );

  servicos.sort((a, b) => a.servico_bitbucket.localeCompare(b.servico_bitbucket));

  const report = buildReport({
    discovered,
    analyzed,
    semJob,
    servicos,
  });

  fs.writeFileSync(cli.output, `${JSON.stringify(report, null, 2)}\n`, 'utf8');
  printConsoleSummary(report);
  process.stderr.write(`Relatório salvo em ${cli.output}\n`);

  if (report.resumo.inconsistentes > 0) {
    process.exitCode = 1;
  }
}

if (require.main === module) {
  main().catch((error) => {
    process.stderr.write(`Erro: ${error.message}\n`);
    process.exit(1);
  });
}

module.exports = {
  discoverServicesFromRoles,
  classifyTipoServico,
  githubTagPrefix,
  evaluateService,
  detectCategoria,
  normalizeGithubDomain,
  inferDomainFromServiceName,
  extractVersionFromGithubTag,
  tagBelongsToService,
  windowsFromJenkinsBranches,
  resolveExpectedWindows,
  VERSION_WINDOWS,
  BITBUCKET_PROJECT_TO_GITHUB,
};
