#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');
const https = require('https');
const http = require('http');
const { parseArgs } = require('util');
const os = require('os');

const REPO_ROOT = path.resolve(__dirname, '../..');
const ROLES_DIR = path.join(REPO_ROOT, 'roles');
const DEFAULT_ENV_PATH = path.join(REPO_ROOT, '.env');
const DEFAULT_OUTPUT = path.join(__dirname, 'report.json');

const DOCKER_ACCOUNT_IMAGE_PREFIX = '{{ docker_account }}';
const IGNORED_IMAGE_NAMES = new Set(['korp.atualizacaosistema', 'viasoft.core.hybridproxy']);

const { values: cli } = parseArgs({
  options: {
    branch: { type: 'string', default: 'release/2024.2.0.x' },
    scope: { type: 'string', default: '2024.2.0' },
    workers: { type: 'string' },
    output: { type: 'string', default: DEFAULT_OUTPUT },
    'env-file': { type: 'string', default: DEFAULT_ENV_PATH },
    'list-jobs': { type: 'boolean', default: false },
    help: { type: 'boolean', short: 'h', default: false },
  },
});

function printHelp() {
  process.stdout.write(`Uso:
  node check-jenkins-branches.js [opções]

Opções:
  --branch <nome>     Branch Jenkins alvo (padrão: release/2024.2.0.x)
  --scope <valor>     2024.2.0 | all (padrão: 2024.2.0)
  --workers <n>       Consultas paralelas ao Jenkins (padrão: auto)
  --output <arquivo>  Caminho do relatório JSON
  --env-file <arquivo> Arquivo com JENKINS_URL, JENKINS_USER e JENKINS_TOKEN
  --list-jobs         Lista jobs Jenkins e encerra
  -h, --help          Exibe esta ajuda

Variáveis de ambiente (ou .env):
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
    const value = trimmed.slice(separatorIndex + 1).trim();
    if (!(key in process.env)) {
      process.env[key] = value;
    }
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

  return name;
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
  return !IGNORED_IMAGE_NAMES.has(baseName);
}

function imageToJenkinsJob(imageName) {
  return imageName
    .split('.')
    .map((part) => part.replace(/(^|-)([a-z])/g, (_, separator, char) => `${separator}${char.toUpperCase()}`))
    .join('.');
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

function walkComposeFiles(roleName, scope) {
  const composesDir = path.join(ROLES_DIR, roleName, 'templates', 'composes');
  if (!fs.existsSync(composesDir)) {
    return [];
  }

  const files = [];

  function visitDir(currentDir, versionFolder) {
    for (const entry of fs.readdirSync(currentDir, { withFileTypes: true })) {
      const fullPath = path.join(currentDir, entry.name);
      if (entry.isDirectory()) {
        visitDir(fullPath, entry.name);
        continue;
      }

      if (!entry.isFile() || !entry.name.endsWith('.yml.j2')) {
        continue;
      }

      const relativeInsideComposes = path.relative(composesDir, fullPath);
      const isVersionedSubfolder = relativeInsideComposes.includes(path.sep);
      const detectedVersion = isVersionedSubfolder
        ? relativeInsideComposes.split(path.sep)[0]
        : null;

      if (scope !== 'all') {
        if (detectedVersion != null && detectedVersion !== scope) {
          continue;
        }
        if (detectedVersion == null && isVersionedSubfolder) {
          continue;
        }
      }

      files.push({
        role: roleName,
        filePath: fullPath,
        relativePath: path.relative(REPO_ROOT, fullPath).split(path.sep).join('/'),
        versionFolder: detectedVersion,
      });
    }
  }

  visitDir(composesDir, null);
  return files;
}

function collectRoleServices(scope) {
  const servicesByImage = new Map();

  for (const role of listRoleDirectories()) {
    for (const composeFile of walkComposeFiles(role, scope)) {
      const content = fs.readFileSync(composeFile.filePath, 'utf8');
      const services = extractServicesFromCompose(content);

      for (const [serviceName, serviceConfig] of Object.entries(services)) {
        if (!isEligibleImage(serviceConfig.image)) {
          continue;
        }

        const image = getImageBaseName(serviceConfig.image);
        const jenkinsJob = imageToJenkinsJob(image);

        if (!servicesByImage.has(image)) {
          servicesByImage.set(image, {
            image,
            jenkins_job: jenkinsJob,
            roles: new Set(),
            files: new Set(),
            service_keys: new Set(),
            container_names: new Set(),
          });
        }

        const entry = servicesByImage.get(image);
        entry.roles.add(composeFile.role);
        entry.files.add(composeFile.relativePath);
        entry.service_keys.add(serviceName);
        if (serviceConfig.container_name) {
          entry.container_names.add(serviceConfig.container_name);
        }
      }
    }
  }

  return [...servicesByImage.values()]
    .map((entry) => ({
      image: entry.image,
      jenkins_job: entry.jenkins_job,
      roles: [...entry.roles].sort(),
      files: [...entry.files].sort(),
      service_keys: [...entry.service_keys].sort(),
      container_names: [...entry.container_names].sort(),
    }))
    .sort((a, b) => a.image.localeCompare(b.image));
}

function resolveMaxWorkers(requestedWorkers, itemCount) {
  if (requestedWorkers != null) {
    const parsed = Number.parseInt(String(requestedWorkers), 10);
    if (!Number.isNaN(parsed) && parsed > 0) {
      return parsed;
    }
  }

  const cpuCount = os.cpus().length || 4;
  return Math.min(20, Math.max(4, cpuCount * 2, Math.min(itemCount, 10)));
}

function jenkinsRequest(urlString, { user, token, timeoutMs = 30000 }) {
  return new Promise((resolve, reject) => {
    const url = new URL(urlString);
    const transport = url.protocol === 'https:' ? https : http;
    const auth = Buffer.from(`${user}:${token}`).toString('base64');

    const request = transport.get(
      url,
      {
        headers: {
          Authorization: `Basic ${auth}`,
        },
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
            body,
          });
        });
      }
    );

    request.on('timeout', () => {
      request.destroy(new Error(`Timeout ao consultar ${urlString}`));
    });
    request.on('error', reject);
  });
}

async function fetchJenkinsJobs(jenkinsConfig) {
  const { status, body } = await jenkinsRequest(
    `${jenkinsConfig.url}/api/json?tree=jobs[name]`,
    jenkinsConfig
  );

  if (status !== 200) {
    throw new Error(`Falha ao listar jobs Jenkins (HTTP ${status})`);
  }

  const parsed = JSON.parse(body);
  return new Set((parsed.jobs || []).map((job) => job.name));
}

async function fetchJobBranches(jenkinsConfig, jobName, cache) {
  if (cache.has(jobName)) {
    return cache.get(jobName);
  }

  const { status, body } = await jenkinsRequest(
    `${jenkinsConfig.url}/job/${encodeURIComponent(jobName)}/api/json?tree=jobs[name]`,
    jenkinsConfig
  );

  let result;
  if (status === 404) {
    result = { exists: false, branches: [] };
  } else if (status !== 200) {
    result = { exists: false, branches: [], error: `HTTP ${status}` };
  } else {
    const parsed = JSON.parse(body);
    const branches = (parsed.jobs || []).map((job) => decodeURIComponent(job.name));
    result = { exists: true, branches };
  }

  cache.set(jobName, result);
  return result;
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

  const workers = Array.from({ length: Math.min(maxWorkers, items.length) }, () => workerLoop());
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

function buildJobCandidates(service, knownJobs) {
  const candidates = [service.jenkins_job];

  const simpleTitleCase = service.image
    .split('.')
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join('.');

  if (!candidates.includes(simpleTitleCase)) {
    candidates.push(simpleTitleCase);
  }

  const lowerImageJob = service.image;
  if (!candidates.includes(lowerImageJob)) {
    candidates.push(lowerImageJob);
  }

  if (knownJobs) {
    const fuzzy = [...knownJobs].find((job) => job.toLowerCase() === service.image.toLowerCase());
    if (fuzzy && !candidates.includes(fuzzy)) {
      candidates.push(fuzzy);
    }
  }

  return candidates;
}

function normalizeBranchName(branch) {
  return branch.startsWith('release/') ? branch : `release/${branch}`;
}

async function checkServices(services, targetBranch, jenkinsConfig, workers) {
  const branchCache = new Map();
  const knownJobs = await fetchJenkinsJobs(jenkinsConfig);
  const maxWorkers = resolveMaxWorkers(workers, services.length);

  return runWithConcurrency(services, async (service) => {
    const candidates = buildJobCandidates(service, knownJobs);
    const resolvedJob = findKnownJob(knownJobs, candidates);
    const jobName = resolvedJob ?? service.jenkins_job;
    const jobInfo = await fetchJobBranches(jenkinsConfig, jobName, branchCache);

    const hasBranch = jobInfo.branches.includes(targetBranch);
    let status;
    if (!jobInfo.exists) {
      status = 'job_not_found';
    } else if (hasBranch) {
      status = 'ok';
    } else {
      status = 'branch_missing';
    }

    return {
      ...service,
      jenkins_job: jobName,
      jenkins_job_candidates: candidates,
      status,
      has_branch: hasBranch,
      jenkins_branches: jobInfo.branches.filter((branch) => branch.includes('release/')),
      error: jobInfo.error ?? null,
    };
  }, maxWorkers);
}

function buildSummary(results, targetBranch, scope) {
  const missingBranch = results.filter((item) => item.status === 'branch_missing');
  const missingJob = results.filter((item) => item.status === 'job_not_found');
  const ok = results.filter((item) => item.status === 'ok');

  return {
    target_branch: targetBranch,
    scope,
    total_services: results.length,
    with_branch: ok.length,
    missing_branch: missingBranch.length,
    job_not_found: missingJob.length,
  };
}

function printConsoleReport(report) {
  const { summary, missing_branch, job_not_found } = report;

  process.stdout.write(`\nBranch alvo: ${summary.target_branch}\n`);
  process.stdout.write(`Escopo: ${summary.scope}\n`);
  process.stdout.write(`Total de imagens: ${summary.total_services}\n`);
  process.stdout.write(`Com branch: ${summary.with_branch}\n`);
  process.stdout.write(`Sem branch: ${summary.missing_branch}\n`);
  process.stdout.write(`Job não encontrado: ${summary.job_not_found}\n`);

  if (missing_branch.length > 0) {
    process.stdout.write('\n=== Sem branch no Jenkins ===\n');
    for (const item of missing_branch) {
      process.stdout.write(`- ${item.image} (job: ${item.jenkins_job}) [${item.roles.join(', ')}]\n`);
    }
  }

  if (job_not_found.length > 0) {
    process.stdout.write('\n=== Job Jenkins não encontrado ===\n');
    for (const item of job_not_found) {
      process.stdout.write(`- ${item.image} (esperado: ${item.jenkins_job}) [${item.roles.join(', ')}]\n`);
    }
  }

  process.stdout.write('\n');
}

async function main() {
  if (cli.help) {
    printHelp();
    return;
  }

  loadEnvFile(cli['env-file']);
  const jenkinsConfig = resolveJenkinsConfig();

  if (cli['list-jobs']) {
    const jobs = [...(await fetchJenkinsJobs(jenkinsConfig))].sort();
    process.stdout.write(`${jobs.join('\n')}\n`);
    return;
  }

  const scope = cli.scope === 'all' ? 'all' : cli.scope;
  const targetBranch = normalizeBranchName(cli.branch);
  const services = collectRoleServices(scope);

  if (!services.length) {
    throw new Error(`Nenhum serviço elegível encontrado para o escopo "${scope}"`);
  }

  process.stderr.write(
    `Consultando Jenkins para ${services.length} imagens (branch ${targetBranch})...\n`
  );

  const results = await checkServices(services, targetBranch, jenkinsConfig, cli.workers);
  const missing_branch = results
    .filter((item) => item.status === 'branch_missing')
    .sort((a, b) => a.image.localeCompare(b.image));
  const job_not_found = results
    .filter((item) => item.status === 'job_not_found')
    .sort((a, b) => a.image.localeCompare(b.image));
  const ok = results.filter((item) => item.status === 'ok').sort((a, b) => a.image.localeCompare(b.image));

  const report = {
    generated_at: new Date().toISOString(),
    summary: buildSummary(results, targetBranch, scope),
    missing_branch,
    job_not_found,
    ok,
    all_results: results.sort((a, b) => a.image.localeCompare(b.image)),
  };

  fs.writeFileSync(cli.output, `${JSON.stringify(report, null, 2)}\n`, 'utf8');
  printConsoleReport(report);
  process.stderr.write(`Relatório salvo em ${cli.output}\n`);

  if (missing_branch.length > 0 || job_not_found.length > 0) {
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
  collectRoleServices,
  imageToJenkinsJob,
  normalizeBranchName,
};
