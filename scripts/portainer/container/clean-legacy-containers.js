#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');
const { execFileSync } = require('child_process');
const { parseArgs } = require('util');

const CONTAINER_DIR = path.resolve(__dirname);
const PORTAINER_DIR = path.resolve(__dirname, '..');
const DEFAULT_ENV_PATH = path.join(PORTAINER_DIR, '.env');
const DEFAULT_REPORT = path.join(
  PORTAINER_DIR,
  'validacao-servicos/report.json'
);
const DEFAULT_OUTPUT = path.join(CONTAINER_DIR, 'cleanup-report.json');

function loadLegacyValidator() {
  return require('../validacao-servicos/validate-legacy-services');
}

const STATUS = {
  DRY_RUN: 'dry_run',
  REMOVED: 'removed',
  ALREADY_ABSENT: 'already_absent',
  SKIPPED: 'skipped',
  FAILED: 'failed',
};

const { values: cli } = parseArgs({
  options: {
    report: { type: 'string', default: DEFAULT_REPORT },
    output: { type: 'string', default: DEFAULT_OUTPUT },
    mode: { type: 'string', default: 'migration' },
    service: { type: 'string', short: 's' },
    all: { type: 'boolean', default: false },
    list: { type: 'boolean', default: false },
    url: { type: 'string', short: 'u' },
    username: { type: 'string' },
    password: { type: 'string' },
    endpoint: { type: 'string', default: '2' },
    'env-file': { type: 'string', default: DEFAULT_ENV_PATH },
    'dry-run': { type: 'boolean', default: false },
    execute: { type: 'boolean', default: false },
    apply: { type: 'boolean', short: 'a', default: false },
    'local-docker': { type: 'boolean', default: false },
    'skip-version-check': { type: 'boolean', default: false },
    help: { type: 'boolean', short: 'h', default: false },
  },
});

function resolveExecutionMode() {
  const wantsApply = Boolean(cli.execute || cli.apply);
  const wantsDryRun = Boolean(cli['dry-run']);

  if (wantsApply && wantsDryRun) {
    throw new Error('Opções conflitantes: use --dry-run ou --execute/--apply, não ambos.');
  }

  return wantsApply;
}

function printHelp() {
  process.stdout.write(`Uso:
  node clean-legacy-containers.js [opções]

Remove containers legados reportados por validate-legacy-services.js.

Princípios:
  - Dry-run por padrão (nenhuma alteração no ambiente)
  - Idempotente: container já ausente é sucesso (pode reexecutar à vontade)

Modo de execução (padrão: dry-run):
  (sem flag)              Simula — lista o que seria removido
  --dry-run               Explícito — igual ao padrão, nenhuma alteração
  --execute, --apply, -a  Alteração real — remove containers de fato

Escopo do alvo:
  --service, -s <nome>   Apenas um serviço (nome do container ou base_name do relatório)
  --all                  Todos os elegíveis do modo (padrão quando --service não é informado)
  --list                 Lista serviços elegíveis e sai (dry-run implícito)

Modos (--mode):
  migration     Legados com par versionado em migration_pairs (padrão, mais seguro)
  all-legacy    Todos os containers em legacy_containers do relatório

Opções:
      --report <arquivo>      Relatório JSON do validate-legacy-services.js
      --output <arquivo>      Relatório desta execução (cleanup-report.json)
      --dry-run               Apenas simula (padrão quando --execute/--apply ausentes)
      --execute               Aplica a remoção de fato
      --apply, -a             Alias de --execute — aplica a remoção de fato
      --local-docker          Usa 'docker rm -f' local em vez da API Portainer
  -u, --url <url>             URL do Portainer
      --username <user>       Usuário Portainer
      --password <pass>       Senha Portainer
      --endpoint <id>         ID do endpoint Docker (padrão: 2)
      --env-file <arquivo>    .env do Portainer
      --skip-version-check    Não exige container versionado (modo migration)
  -h, --help                  Exibe esta ajuda

Exemplos:
  node scripts/portainer/container/clean-legacy-containers.js --list
  node scripts/portainer/container/clean-legacy-containers.js --service ADM01
  node scripts/portainer/container/clean-legacy-containers.js --service ADM01 --dry-run
  node scripts/portainer/container/clean-legacy-containers.js --service ADM01 --apply
  node scripts/portainer/container/clean-legacy-containers.js --service ADM01 --execute
  node scripts/portainer/container/clean-legacy-containers.js --all --apply
  node scripts/portainer/container/clean-legacy-containers.js --all --mode all-legacy --execute
`);
}

function loadReport(reportPath) {
  if (!fs.existsSync(reportPath)) {
    throw new Error(`Relatório não encontrado: ${reportPath}`);
  }

  const report = JSON.parse(fs.readFileSync(reportPath, 'utf8'));

  if (!Array.isArray(report.legacy_containers) || !Array.isArray(report.migration_pairs)) {
    throw new Error(
      'Relatório inválido: execute validate-legacy-services.js antes deste script.'
    );
  }

  return report;
}

function collectMigrationTargets(report) {
  const targets = new Map();

  for (const pair of report.migration_pairs) {
    for (const legacyName of pair.legacy_containers || []) {
      targets.set(legacyName, {
        container_name: legacyName,
        base_name: pair.base_name,
        versioned_containers: pair.versioned_containers || [],
        source: 'migration_pairs',
      });
    }
  }

  return targets;
}

function collectAllLegacyTargets(report) {
  const targets = new Map();

  for (const item of report.legacy_containers) {
    targets.set(item.container_name, {
      container_name: item.container_name,
      base_name: item.base_name,
      versioned_containers: [],
      source: 'legacy_containers',
      issues: item.issues || [],
      image: item.image,
      state: item.state,
    });
  }

  return targets;
}

function resolveModeTargets(report, mode) {
  if (mode === 'all-legacy') {
    return collectAllLegacyTargets(report);
  }
  return collectMigrationTargets(report);
}

function normalizeServiceKey(value) {
  return String(value || '').trim();
}

function matchesService(target, serviceName) {
  const needle = normalizeServiceKey(serviceName);
  return (
    target.container_name === needle ||
    target.base_name === needle ||
    target.container_name.toLowerCase() === needle.toLowerCase() ||
    target.base_name.toLowerCase() === needle.toLowerCase()
  );
}

function filterTargetsByService(targets, serviceName) {
  const filtered = new Map();

  for (const [name, target] of targets.entries()) {
    if (matchesService(target, serviceName)) {
      filtered.set(name, target);
    }
  }

  if (filtered.size === 0) {
    const available = [...targets.values()]
      .map((item) => item.container_name)
      .sort()
      .join(', ');
    throw new Error(
      `Serviço '${serviceName}' não encontrado no relatório (modo atual). Disponíveis: ${available}`
    );
  }

  return filtered;
}

function resolveScope(targets) {
  const service = normalizeServiceKey(cli.service);

  if (cli.list) {
    return { targets, scope: 'list' };
  }

  if (service) {
    return {
      targets: filterTargetsByService(targets, service),
      scope: 'service',
      service,
    };
  }

  if (cli.all || targets.size > 0) {
    return { targets, scope: 'all' };
  }

  return { targets, scope: 'all' };
}

function isProtectedContainer(containerName) {
  const { IGNORED_CONTAINER_NAMES, INFRA_CONTAINER_NAMES } = loadLegacyValidator();
  return (
    IGNORED_CONTAINER_NAMES.has(containerName) || INFRA_CONTAINER_NAMES.has(containerName)
  );
}

function indexContainersByName(containers) {
  const { normalizeContainerName } = loadLegacyValidator();
  const byName = new Map();

  for (const container of containers) {
    byName.set(normalizeContainerName(container.Names), container);
  }

  return byName;
}

function evaluateTarget(target, containersByName, mode, skipVersionCheck) {
  const { isIgnoredService } = loadLegacyValidator();
  const legacy = containersByName.get(target.container_name);

  if (!legacy) {
    return {
      action: 'none',
      status: STATUS.ALREADY_ABSENT,
      message: 'Container já ausente — nenhuma ação necessária (idempotente)',
      container: null,
    };
  }

  if (isProtectedContainer(target.container_name)) {
    return {
      action: 'skip',
      status: STATUS.SKIPPED,
      message: 'Container protegido (infra ou exceção)',
      container: legacy,
    };
  }

  if (isIgnoredService(target.container_name, legacy.Image || '')) {
    return {
      action: 'skip',
      status: STATUS.SKIPPED,
      message: 'Container ignorado pelas regras de validação',
      container: legacy,
    };
  }

  if (
    mode === 'migration' &&
    !skipVersionCheck &&
    target.versioned_containers.length > 0
  ) {
    const presentVersioned = target.versioned_containers.filter((name) =>
      containersByName.has(name)
    );

    if (presentVersioned.length === 0) {
      return {
        action: 'skip',
        status: STATUS.SKIPPED,
        message: `Sem container versionado ativo: ${target.versioned_containers.join(', ')}`,
        container: legacy,
      };
    }
  }

  return {
    action: 'remove',
    status: null,
    message: null,
    container: legacy,
  };
}

async function removeViaPortainer(baseUrl, jwt, endpointId, containerId) {
  const { portainerRequest } = loadLegacyValidator();
  const requestPath = `/api/endpoints/${endpointId}/docker/containers/${containerId}?force=true`;
  const { status, body } = await portainerRequest(baseUrl, 'DELETE', requestPath, jwt);

  if (status === 404) {
    return { removed: false, alreadyAbsent: true };
  }

  if (status !== 204 && status !== 200) {
    throw new Error(`Falha ao remover container (HTTP ${status}): ${body}`);
  }

  return { removed: true, alreadyAbsent: false };
}

function removeViaDocker(containerName) {
  try {
    execFileSync('docker', ['rm', '-f', containerName], {
      encoding: 'utf8',
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    return { removed: true, alreadyAbsent: false };
  } catch (error) {
    const stderr = error.stderr ? String(error.stderr).trim() : error.message;
    if (/No such container/i.test(stderr)) {
      return { removed: false, alreadyAbsent: true };
    }
    throw new Error(`docker rm -f ${containerName} falhou: ${stderr}`);
  }
}

async function listDockerContainers() {
  const output = execFileSync(
    'docker',
    ['ps', '-a', '--format', '{{.Names}}\t{{.Image}}\t{{.State}}'],
    { encoding: 'utf8' }
  );

  return output
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const [name, image, state] = line.split('\t');
      return { Names: [name], Image: image, State: state, Id: name };
    });
}

async function loadRuntimeContainers() {
  const {
    authenticate,
    listContainers,
    resolvePortainerUrl,
    loadEnvFile,
  } = loadLegacyValidator();

  if (cli['local-docker']) {
    return { containersByName: indexContainersByName(await listDockerContainers()), portainerContext: null };
  }

  loadEnvFile(cli['env-file']);

  const baseUrl = resolvePortainerUrl(cli.url || process.env.PORTAINER_URL);
  const username = cli.username || process.env.PORTAINER_USER;
  const password = cli.password || process.env.PORTAINER_PASSWORD;
  const endpointId = cli.endpoint || process.env.PORTAINER_ENDPOINT || '2';

  if (!baseUrl) {
    throw new Error('URL do Portainer não informada. Use --url ou PORTAINER_URL no .env.');
  }

  if (!username || !password) {
    throw new Error(
      'Credenciais não informadas. Use --username/--password ou PORTAINER_USER/PORTAINER_PASSWORD.'
    );
  }

  const jwt = await authenticate(baseUrl, username, password);
  const containers = await listContainers(baseUrl, jwt, endpointId, true);

  return {
    containersByName: indexContainersByName(containers),
    portainerContext: { baseUrl, jwt, endpointId },
  };
}

function printTargetList(targets, mode, dryRun) {
  process.stdout.write('\n=== Serviços elegíveis para limpeza ===\n');
  process.stdout.write(`Modo: ${mode}\n`);
  process.stdout.write(`Dry-run: ${dryRun ? 'sim (padrão)' : 'não (--execute / --apply)'}\n\n`);

  for (const target of [...targets.values()].sort((a, b) =>
    a.container_name.localeCompare(b.container_name)
  )) {
    process.stdout.write(`- ${target.container_name}`);
    if (target.base_name && target.base_name !== target.container_name) {
      process.stdout.write(` (base: ${target.base_name})`);
    }
    if (target.versioned_containers?.length) {
      process.stdout.write(` → versionados: ${target.versioned_containers.join(', ')}`);
    }
    process.stdout.write('\n');
  }

  process.stdout.write(`\nTotal: ${targets.size}\n`);
  process.stdout.write('Use --service <nome> para um serviço ou --all para todos.\n');
}

function buildCleanupReport(report, options, results) {
  const countByStatus = Object.values(STATUS).reduce((acc, status) => {
    acc[status] = results.filter((item) => item.status === status).length;
    return acc;
  }, {});

  return {
    summary: {
      source_report: report.summary?.portainer_url ?? null,
      scope_version: report.summary?.scope_version ?? null,
      mode: options.mode,
      scope: options.scope,
      service: options.service ?? null,
      execute: options.execute,
      dry_run: !options.execute,
      targets: results.length,
      ...countByStatus,
      idempotent_noop: countByStatus[STATUS.ALREADY_ABSENT],
    },
    results: results.sort((a, b) => a.container_name.localeCompare(b.container_name)),
  };
}

function printSummary(cleanupReport) {
  const { summary, results } = cleanupReport;

  process.stdout.write('\n=== Limpeza de containers legados ===\n');
  process.stdout.write(`Modo: ${summary.mode}\n`);
  process.stdout.write(
    `Escopo: ${summary.scope}${summary.service ? ` (${summary.service})` : ''}\n`
  );
  process.stdout.write(
    `Execução: ${summary.execute ? 'REAL (--execute / --apply)' : 'DRY-RUN (nenhuma alteração)'}\n`
  );
  process.stdout.write(`Alvos: ${summary.targets}\n`);
  process.stdout.write(`Removidos: ${summary.removed}\n`);
  process.stdout.write(`Simulados: ${summary.dry_run}\n`);
  process.stdout.write(`Já ausentes (idempotente): ${summary.already_absent}\n`);
  process.stdout.write(`Ignorados: ${summary.skipped}\n`);
  process.stdout.write(`Falhas: ${summary.failed}\n\n`);

  for (const item of results) {
    const label = {
      [STATUS.DRY_RUN]: 'SIMULADO',
      [STATUS.REMOVED]: 'REMOVIDO',
      [STATUS.ALREADY_ABSENT]: 'JÁ AUSENTE',
      [STATUS.SKIPPED]: 'IGNORADO',
      [STATUS.FAILED]: 'FALHA',
    }[item.status];

    process.stdout.write(`${label}\t${item.container_name}`);
    if (item.versioned_containers?.length) {
      process.stdout.write(`\t(versionados: ${item.versioned_containers.join(', ')})`);
    }
    if (item.message) {
      process.stdout.write(`\t— ${item.message}`);
    }
    process.stdout.write('\n');
  }
}

async function processTarget(target, containersByName, portainerContext, mode, execute) {
  const evaluation = evaluateTarget(
    target,
    containersByName,
    mode,
    cli['skip-version-check']
  );

  const result = {
    container_name: target.container_name,
    base_name: target.base_name,
    versioned_containers: target.versioned_containers || [],
    source: target.source,
    image: evaluation.container?.Image || target.image || null,
    state: evaluation.container?.State || target.state || null,
    status: evaluation.status,
    message: evaluation.message,
    changed: false,
  };

  if (evaluation.action === 'none') {
    return result;
  }

  if (evaluation.action === 'skip') {
    return result;
  }

  if (!execute) {
    result.status = STATUS.DRY_RUN;
    result.message = cli['local-docker']
      ? 'Seria removido com: docker rm -f'
      : 'Seria removido via Portainer API';
    return result;
  }

  try {
    let removal;

    if (cli['local-docker']) {
      removal = removeViaDocker(target.container_name);
    } else {
      removal = await removeViaPortainer(
        portainerContext.baseUrl,
        portainerContext.jwt,
        portainerContext.endpointId,
        evaluation.container.Id
      );
    }

    if (removal.alreadyAbsent) {
      result.status = STATUS.ALREADY_ABSENT;
      result.message = 'Container já ausente — nenhuma ação necessária (idempotente)';
      result.changed = false;
      return result;
    }

    result.status = STATUS.REMOVED;
    result.message = cli['local-docker']
      ? 'Removido via docker rm -f'
      : 'Removido via Portainer API';
    result.changed = true;
    return result;
  } catch (error) {
    result.status = STATUS.FAILED;
    result.message = error.message;
    result.changed = false;
    return result;
  }
}

async function main() {
  if (cli.help) {
    printHelp();
    return;
  }

  const mode = String(cli.mode || 'migration').toLowerCase();
  if (mode !== 'migration' && mode !== 'all-legacy') {
    throw new Error(`Modo inválido: ${cli.mode}. Use migration ou all-legacy.`);
  }

  const execute = resolveExecutionMode();

  const report = loadReport(path.resolve(cli.report));
  const modeTargets = resolveModeTargets(report, mode);

  if (modeTargets.size === 0) {
    process.stdout.write('Nenhum container legado elegível no relatório para o modo selecionado.\n');
    return;
  }

  const { targets, scope, service } = resolveScope(modeTargets);

  if (cli.list) {
    printTargetList(targets, mode, !execute);
    return;
  }

  const { containersByName, portainerContext } = await loadRuntimeContainers();

  const results = [];
  for (const target of [...targets.values()].sort((a, b) =>
    a.container_name.localeCompare(b.container_name)
  )) {
    results.push(await processTarget(target, containersByName, portainerContext, mode, execute));
  }

  const cleanupReport = buildCleanupReport(report, {
    mode,
    scope,
    service,
    execute,
  }, results);

  fs.writeFileSync(cli.output, `${JSON.stringify(cleanupReport, null, 2)}\n`, 'utf8');
  printSummary(cleanupReport);
  process.stderr.write(`\nRelatório salvo em ${cli.output}\n`);

  if (cleanupReport.summary.failed > 0) {
    process.exit(1);
  }
}

if (require.main === module) {
  main().catch((error) => {
    process.stderr.write(`Erro: ${error.message}\n`);
    process.exit(1);
  });
}

module.exports = {
  collectMigrationTargets,
  collectAllLegacyTargets,
  resolveModeTargets,
  filterTargetsByService,
  evaluateTarget,
  loadReport,
  resolveExecutionMode,
  STATUS,
};
