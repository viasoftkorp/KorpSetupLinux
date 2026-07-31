#!/usr/bin/env node
'use strict';

/**
 * Cria tags no GitHub a partir de scripts/validacao-tags/report.json
 * (servicos_sem_tag_no_github), após revalidar Job no Jenkins.
 *
 * Uso:
 *   node create-tags-github.js --dry-run --all-services
 *   node create-tags-github.js --all-services
 *   node create-tags-github.js --dry-run --single-service=korp.api.gateway.vendas
 */

const fs = require('fs');
const path = require('path');
const https = require('https');
const http = require('http');
const { parseArgs } = require('util');

const REPO_ROOT = path.resolve(__dirname, '../..');
const DEFAULT_INPUT = path.join(REPO_ROOT, 'scripts/validacao-tags/report.json');
const DEFAULT_OUTPUT = path.join(__dirname, 'create-tags-report.json');
const DEFAULT_ENV_PATH = fs.existsSync(path.join(__dirname, '.env'))
  ? path.join(__dirname, '.env')
  : fs.existsSync(path.join(__dirname, '../validacao-tags/.env'))
    ? path.join(__dirname, '../validacao-tags/.env')
    : path.join(__dirname, '../.env');

const FALLBACK_VERSION = '2025.1.0.1';
const LEGACY_TARGET_WINDOW = '2025.1.0';

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
  producao: 'producao',
  production: 'producao',
  estoque: 'estoque',
  pessoas: 'pessoas',
  person: 'pessoas',
  erp: 'erp',
  approval: 'approval',
  mobile: 'mobile',
  rma: 'rma',
  sdk: 'sdk',
  ecommerce: 'vendas',
  analytics: 'analytics',
  elt: 'analytics',
  integration: 'infrastructure',
  solidworks: 'engenharia',
};

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

    process.env[key] = value;
  }
}

function isCoreService(serviceName) {
  const name = String(serviceName || '').toLowerCase();
  return name.startsWith('korp.') || name.startsWith('viasoft.');
}

function imageToJenkinsJob(imageName) {
  return String(imageName)
    .split('.')
    .map((part) =>
      part.replace(/(^|-)([a-z])/g, (_, separator, char) => `${separator}${char.toUpperCase()}`)
    )
    .join('.');
}

function buildJobCandidates(serviceName) {
  const lower = String(serviceName).toLowerCase();
  const candidates = [imageToJenkinsJob(lower)];

  const simpleTitleCase = lower
    .split('.')
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join('.');

  if (!candidates.includes(simpleTitleCase)) {
    candidates.push(simpleTitleCase);
  }
  if (!candidates.includes(lower)) {
    candidates.push(lower);
  }

  return candidates;
}

function inferDomainFromServiceName(serviceName) {
  const normalized = String(serviceName)
    .toLowerCase()
    .replace(/^(korp|viasoft|sdk)\./, '');
  const tokens = normalized.split(/[._-]+/).filter(Boolean);

  for (const token of tokens) {
    if (SERVICE_TOKEN_TO_DOMAIN[token]) {
      return SERVICE_TOKEN_TO_DOMAIN[token];
    }
  }

  return null;
}

function resolveGithubDomain(service) {
  const raw = String(service.dominio_github || '').toLowerCase().trim();

  if (KNOWN_GITHUB_DOMAINS.has(raw)) {
    return raw;
  }

  if (BITBUCKET_PROJECT_TO_GITHUB[raw]) {
    return BITBUCKET_PROJECT_TO_GITHUB[raw];
  }

  const inferred = inferDomainFromServiceName(service.servico_bitbucket);
  if (inferred) {
    return inferred;
  }

  return raw || 'desconhecido';
}

function extractBuildNumber(versionTag) {
  if (!versionTag || versionTag === 'Não encontrada' || versionTag === 'Não consultado') {
    return null;
  }

  const cleaned = String(versionTag).replace(/^v/i, '');
  // Aceita tanto "2025.1.0.10" quanto tags com prefixo de serviço
  const match = cleaned.match(/(\d+\.\d+\.\d+\.\d+|\d+\.\d+\.\d+)(?:$)/);
  if (!match) {
    return null;
  }

  const parts = match[1].split('.');
  const build = Number.parseInt(parts[parts.length - 1], 10);
  return Number.isNaN(build) ? null : build;
}

function extractWindowBase(versionTag) {
  if (!versionTag || versionTag === 'Não encontrada') {
    return null;
  }

  const cleaned = String(versionTag).replace(/^v/i, '');
  const year = cleaned.match(/(\d{4}\.\d+\.\d+)\.\d+/);
  if (year) {
    return year[1];
  }

  return null;
}

function versionToReleaseBranch(version) {
  const windowBase = extractWindowBase(version) || LEGACY_TARGET_WINDOW;
  return `release/${windowBase}.x`;
}

/**
 * Calcula as tags GitHub a criar para um serviço do relatório.
 * @returns {string[]} tags no formato servico-versao
 */
function calculateTagsForService(service) {
  const serviceName = String(service.servico_bitbucket || '').toLowerCase();
  const ref = service.referencia_bitbucket || {};

  if (service.categoria === 'nao-versionados') {
    const absolute = ref.ultima_tag_absoluta;
    const build = extractBuildNumber(absolute);
    const nextBuild = build == null ? 1 : build + 1;
    return [`${serviceName}-${LEGACY_TARGET_WINDOW}.${nextBuild}`];
  }

  const planned = [];
  for (const [key, value] of Object.entries(ref)) {
    if (!key.startsWith('janela_')) {
      continue;
    }
    if (!value || value === 'Não encontrada' || value === 'Não consultado') {
      continue;
    }

    const windowBase = extractWindowBase(value) || key.replace(/^janela_/, '').replace(/\.x$/, '');
    const build = extractBuildNumber(value);
    if (build == null) {
      continue;
    }

    planned.push(`${serviceName}-${windowBase}.${build + 1}`);
  }

  if (planned.length === 0) {
    return [`${serviceName}-${FALLBACK_VERSION}`];
  }

  return planned;
}

function filterEligibleServices(services, { singleService = null } = {}) {
  let list = Array.isArray(services) ? services : [];

  list = list.filter((item) => item && item.tem_tag_github === false);
  list = list.filter((item) => isCoreService(item.servico_bitbucket));

  if (singleService) {
    const target = String(singleService).toLowerCase();
    list = list.filter((item) => String(item.servico_bitbucket).toLowerCase() === target);
  }

  return list;
}

function httpRequest(urlString, { method = 'GET', headers = {}, body = null, timeoutMs = 45000 } = {}) {
  return new Promise((resolve, reject) => {
    const url = new URL(urlString);
    const transport = url.protocol === 'https:' ? https : http;
    const payload = body == null ? null : Buffer.from(body);

    const request = transport.request(
      url,
      {
        method,
        headers: {
          ...headers,
          ...(payload ? { 'Content-Length': payload.length } : {}),
        },
        timeout: timeoutMs,
      },
      (response) => {
        let data = '';
        response.on('data', (chunk) => {
          data += chunk;
        });
        response.on('end', () => {
          resolve({
            status: response.statusCode ?? 0,
            headers: response.headers,
            body: data,
          });
        });
      }
    );

    request.on('timeout', () => {
      request.destroy(new Error(`Timeout ao consultar ${urlString}`));
    });
    request.on('error', reject);

    if (payload) {
      request.write(payload);
    }
    request.end();
  });
}

function basicAuth(user, password) {
  return `Basic ${Buffer.from(`${user}:${password}`).toString('base64')}`;
}

function createLogger({ debug = false } = {}) {
  return {
    info(message) {
      process.stdout.write(`${message}\n`);
    },
    debug(message) {
      if (debug) {
        process.stderr.write(`[debug] ${message}\n`);
      }
    },
    warn(message) {
      process.stderr.write(`${message}\n`);
    },
  };
}

function resolveConfigs() {
  const githubToken = process.env.GITHUB_TOKEN || '';
  const org = process.env.ORG_NAME || '';
  const jenkinsUrl = (process.env.JENKINS_URL || '').replace(/\/$/, '');
  const jenkinsUser = process.env.JENKINS_USER || '';
  const jenkinsToken = process.env.JENKINS_TOKEN || '';

  if (!githubToken || !org) {
    throw new Error('Configure GITHUB_TOKEN e ORG_NAME no .env');
  }
  if (!jenkinsUrl || !jenkinsUser || !jenkinsToken) {
    throw new Error('Configure JENKINS_URL, JENKINS_USER e JENKINS_TOKEN no .env');
  }

  return {
    github: { token: githubToken, org },
    jenkins: { url: jenkinsUrl, user: jenkinsUser, token: jenkinsToken },
  };
}

async function githubRequest(githubConfig, urlPath, { method = 'GET', body = null } = {}) {
  const url = urlPath.startsWith('http')
    ? urlPath
    : `https://api.github.com${urlPath}`;

  const authHeaders = [`Bearer ${githubConfig.token}`, `token ${githubConfig.token}`];
  let last = null;

  for (const authorization of authHeaders) {
    const response = await httpRequest(url, {
      method,
      body,
      headers: {
        Authorization: authorization,
        Accept: 'application/vnd.github+json',
        'User-Agent': 'korp-criacao-tags-github',
        'X-GitHub-Api-Version': '2022-11-28',
        ...(body ? { 'Content-Type': 'application/json' } : {}),
      },
    });
    last = response;
    if (response.status !== 401) {
      return response;
    }
  }

  return last;
}

async function jenkinsJobExists(jenkinsConfig, serviceName, { logger, deps }) {
  const candidates = buildJobCandidates(serviceName);
  const requestFn = deps.httpRequest || httpRequest;

  for (const jobName of candidates) {
    const url = `${jenkinsConfig.url}/job/${encodeURIComponent(jobName)}/api/json`;
    logger.debug(`Jenkins GET ${url}`);

    try {
      const { status, body } = await requestFn(url, {
        headers: {
          Authorization: basicAuth(jenkinsConfig.user, jenkinsConfig.token),
        },
      });
      logger.debug(`Jenkins ${jobName} → HTTP ${status} ${body?.slice?.(0, 120) || ''}`);

      if (status === 200) {
        return { exists: true, jobName };
      }
      if (status === 404) {
        continue;
      }
    } catch (error) {
      logger.debug(`Jenkins erro ${jobName}: ${error.message}`);
    }
  }

  return { exists: false, jobName: candidates[0] };
}

async function fetchBranchSha(githubConfig, dominio, branch, { logger, deps }) {
  const requestFn = deps.githubRequest || githubRequest;
  const urlPath = `/repos/${encodeURIComponent(githubConfig.org)}/${encodeURIComponent(dominio)}/branches/${encodeURIComponent(branch)}`;
  logger.debug(`GitHub GET ${urlPath}`);

  const { status, body } = await requestFn(githubConfig, urlPath);
  logger.debug(`GitHub branch ${dominio}/${branch} → HTTP ${status}`);

  if (status === 404) {
    return { ok: false, sha: null, error: 'branch_not_found' };
  }
  if (status !== 200) {
    return { ok: false, sha: null, error: `HTTP ${status}: ${body.slice(0, 200)}` };
  }

  try {
    const parsed = JSON.parse(body);
    const sha = parsed?.commit?.sha;
    if (!sha) {
      return { ok: false, sha: null, error: 'sha_ausente' };
    }
    return { ok: true, sha, error: null };
  } catch (error) {
    return { ok: false, sha: null, error: error.message };
  }
}

async function createGithubTag(githubConfig, dominio, tagName, sha, { dryRun, logger, deps }) {
  if (dryRun) {
    logger.info(`[DRY-RUN] Criaria tag ${tagName} em ${dominio} @ ${sha.slice(0, 7)}`);
    return { ok: true, dryRun: true, status: 0 };
  }

  const requestFn = deps.githubRequest || githubRequest;
  const urlPath = `/repos/${encodeURIComponent(githubConfig.org)}/${encodeURIComponent(dominio)}/git/refs`;
  const payload = JSON.stringify({
    ref: `refs/tags/${tagName}`,
    sha,
  });

  logger.debug(`GitHub POST ${urlPath} body=${payload}`);
  const { status, body } = await requestFn(githubConfig, urlPath, {
    method: 'POST',
    body: payload,
  });
  logger.debug(`GitHub create tag → HTTP ${status} ${body.slice(0, 200)}`);

  if (status === 201) {
    return { ok: true, dryRun: false, status };
  }

  if (status === 422) {
    return {
      ok: false,
      dryRun: false,
      status,
      error: 'tag_ja_existe_ou_invalida',
      detail: body.slice(0, 300),
    };
  }

  return {
    ok: false,
    dryRun: false,
    status,
    error: `HTTP ${status}`,
    detail: body.slice(0, 300),
  };
}

async function processService(service, configs, options) {
  const { dryRun, logger, deps } = options;
  const serviceName = String(service.servico_bitbucket).toLowerCase();
  const dominio = resolveGithubDomain(service);
  const tags = calculateTagsForService(service);

  const jenkins = await jenkinsJobExists(configs.jenkins, serviceName, { logger, deps });
  if (!jenkins.exists) {
    logger.info(`[IGNORADO] Serviço ${serviceName} não possui Job no Jenkins.`);
    return {
      status: 'ignorado',
      motivo: 'jenkins_404',
      dominio_github: dominio,
      dominio_original: service.dominio_github,
      servico_bitbucket: serviceName,
      tags_planejadas: tags,
    };
  }

  const criadas = [];
  const erros = [];

  for (const tagName of tags) {
    const version = tagName.slice(serviceName.length + 1);
    const branch = versionToReleaseBranch(version);

    const branchInfo = await fetchBranchSha(configs.github, dominio, branch, { logger, deps });
    if (!branchInfo.ok) {
      const message = `[ERRO] Branch ${branch} não encontrada para o serviço ${serviceName} (domínio ${dominio})`;
      logger.warn(message);
      erros.push({ tag: tagName, branch, error: branchInfo.error || 'branch_not_found' });
      continue;
    }

    const created = await createGithubTag(configs.github, dominio, tagName, branchInfo.sha, {
      dryRun,
      logger,
      deps,
    });

    if (created.ok) {
      criadas.push({
        tag: tagName,
        branch,
        sha: branchInfo.sha,
        dry_run: Boolean(created.dryRun),
      });
      if (!created.dryRun) {
        logger.info(`[OK] Tag criada: ${tagName} → ${dominio} (${branch})`);
      }
    } else {
      erros.push({
        tag: tagName,
        branch,
        error: created.error,
        detail: created.detail,
      });
      logger.warn(`[ERRO] Falha ao criar ${tagName}: ${created.error}`);
    }
  }

  return {
    status: erros.length && !criadas.length ? 'erro' : 'processado',
    dominio_github: dominio,
    dominio_original: service.dominio_github,
    servico_bitbucket: serviceName,
    jenkins_job: jenkins.jobName,
    tags_planejadas: tags,
    tags_criadas: criadas,
    erros,
  };
}

function printHelp() {
  process.stdout.write(`Uso:
  node create-tags-github.js --dry-run --all-services
  node create-tags-github.js --all-services
  node create-tags-github.js --dry-run --single-service=<nome>

Opções:
  --input <arquivo>     Relatório do validador (padrão: scripts/validacao-tags/report.json)
  --output <arquivo>    Relatório de saída (padrão: create-tags-report.json)
  --env-file <arquivo>  Credenciais (.env)
  --dry-run             Calcula e consulta APIs, mas não cria tags
  --debug               Logs verbosos
  --all-services        Processa todos de servicos_sem_tag_no_github
  --single-service=NOME Processa apenas um serviço
  -h, --help
`);
}

async function runCreateTags(options) {
  const {
    inputPath,
    outputPath,
    dryRun = false,
    debug = false,
    allServices = false,
    singleService = null,
    deps = {},
    skipEnvLoad = false,
    envPath = DEFAULT_ENV_PATH,
  } = options;

  if (!allServices && !singleService) {
    throw new Error(
      'Informe --all-services ou --single-service=<nome>. Use --dry-run para simular.'
    );
  }

  if (!skipEnvLoad) {
    loadEnvFile(envPath);
  }

  const logger = createLogger({ debug });
  const readFile = deps.readFileSync || ((p) => fs.readFileSync(p, 'utf8'));

  if (!fs.existsSync(inputPath) && !deps.readFileSync) {
    throw new Error(`Arquivo de entrada não encontrado: ${inputPath}`);
  }

  const report = JSON.parse(readFile(inputPath));
  const source = report.servicos_sem_tag_no_github || [];
  const eligible = filterEligibleServices(source, { singleService });

  logger.info(
    `Entrada: ${source.length} sem tag | elegíveis (korp./viasoft.): ${eligible.length}` +
      (dryRun ? ' | DRY-RUN' : '')
  );

  const configs = deps.configs || resolveConfigs();
  const results = [];
  const ignorados = [];
  const processados = [];

  for (const service of eligible) {
    const result = await processService(service, configs, { dryRun, logger, deps });
    results.push(result);
    if (result.status === 'ignorado') {
      ignorados.push(result);
    } else {
      processados.push(result);
    }
  }

  const output = {
    timestamp: new Date().toISOString(),
    dry_run: dryRun,
    input: inputPath,
    resumo: {
      total_entrada_sem_tag: source.length,
      total_elegiveis: eligible.length,
      processados: processados.length,
      ignorados_jenkins: ignorados.length,
      tags_criadas: processados.reduce(
        (sum, item) => sum + (item.tags_criadas?.length || 0),
        0
      ),
      erros: processados.reduce((sum, item) => sum + (item.erros?.length || 0), 0),
    },
    servicos_processados: processados,
    servicos_ignorados: ignorados,
  };

  const writeFile = deps.writeFileSync || ((p, content) => fs.writeFileSync(p, content, 'utf8'));
  writeFile(outputPath, `${JSON.stringify(output, null, 2)}\n`);
  logger.info(`Relatório salvo em ${outputPath}`);

  return output;
}

async function main() {
  const { values: cli } = parseArgs({
    options: {
      input: { type: 'string', default: DEFAULT_INPUT },
      output: { type: 'string', default: DEFAULT_OUTPUT },
      'env-file': { type: 'string', default: DEFAULT_ENV_PATH },
      'dry-run': { type: 'boolean', default: false },
      debug: { type: 'boolean', default: false },
      'all-services': { type: 'boolean', default: false },
      'single-service': { type: 'string' },
      help: { type: 'boolean', short: 'h', default: false },
    },
  });

  if (cli.help) {
    printHelp();
    return;
  }

  const output = await runCreateTags({
    inputPath: path.resolve(cli.input),
    outputPath: path.resolve(cli.output),
    envPath: path.resolve(cli['env-file']),
    dryRun: cli['dry-run'],
    debug: cli.debug,
    allServices: cli['all-services'],
    singleService: cli['single-service'] || null,
  });

  if (output.resumo.erros > 0) {
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
  isCoreService,
  calculateTagsForService,
  filterEligibleServices,
  resolveGithubDomain,
  versionToReleaseBranch,
  extractBuildNumber,
  runCreateTags,
  BITBUCKET_PROJECT_TO_GITHUB,
  FALLBACK_VERSION,
};
