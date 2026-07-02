#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');
const { spawnSync } = require('child_process');
const { parseArgs } = require('util');
const os = require('os');

const OUTPUT_PATH = path.join(__dirname, 'mapping.json');
const DEFAULT_SERVICES_FILE = path.join(__dirname, 'service-list');

const DEFAULT_RELEASE_BRANCHES = [
  'release/2023.4.0.x',
  'release/2024.2.0.x',
  'release/2024.1.0.x',
  'release/2025.1.0.x',
];

function escapeRegex(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function runGit(repoDir, args, { allowFailure = false, timeoutMs = 60000 } = {}) {
  const result = spawnSync('git', args, {
    cwd: repoDir,
    encoding: 'utf8',
    timeout: timeoutMs,
  });

  if (result.error) {
    throw result.error;
  }

  if (result.status !== 0 && !allowFailure) {
    const message = (result.stderr || result.stdout || '').trim();
    throw new Error(`git ${args.join(' ')} failed (${result.status}): ${message}`);
  }

  return {
    status: result.status ?? 1,
    stdout: result.stdout ?? '',
    stderr: result.stderr ?? '',
  };
}

function listBranches(repoDir) {
  const { stdout } = runGit(
    repoDir,
    [
      'for-each-ref',
      '--format=%(refname:short)',
      'refs/heads',
      'refs/remotes/origin',
    ],
    { timeoutMs: 30000 }
  );

  return stdout
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => line && !line.endsWith('/HEAD'));
}

function unique(values) {
  return [...new Set(values)];
}

function parseCsvOrRepeat(values) {
  if (!values) {
    return [];
  }

  const items = Array.isArray(values) ? values : [values];
  return items.flatMap((value) =>
    String(value)
      .split(',')
      .map((part) => part.trim())
      .filter(Boolean)
  );
}

function resolveTargetBranches(repoDir, branches, branchesRegex) {
  if (branches?.length && branchesRegex) {
    throw new Error('Use either --branches or --branches-regex, not both');
  }

  if (branches?.length) {
    return unique(parseCsvOrRepeat(branches));
  }

  if (branchesRegex) {
    const pattern = new RegExp(branchesRegex);
    return unique(listBranches(repoDir).filter((branch) => pattern.test(branch)));
  }

  return [...DEFAULT_RELEASE_BRANCHES];
}

function branchExists(repoDir, branch) {
  const { status } = runGit(repoDir, ['rev-parse', '--verify', '--quiet', branch], {
    allowFailure: true,
    timeoutMs: 15000,
  });
  return status === 0;
}

function resolveBranchRef(repoDir, branch) {
  if (branchExists(repoDir, branch)) {
    return branch;
  }

  const originRef = `origin/${branch}`;
  if (branchExists(repoDir, originRef)) {
    return originRef;
  }

  return null;
}

function chunkServicesForRegex(services, maxPatternLen = 6000) {
  const chunks = [];
  let current = [];
  let currentLen = 0;

  for (const service of services) {
    const escaped = escapeRegex(service);
    const projected = currentLen + escaped.length + (current.length ? 1 : 0);

    if (current.length && projected > maxPatternLen) {
      chunks.push(current);
      current = [];
      currentLen = 0;
    }

    current.push(service);
    currentLen = projected;
  }

  if (current.length) {
    chunks.push(current);
  }

  return chunks;
}

function branchToVersionTag(branch) {
  const match = String(branch).match(/(?:release\/)?(\d{4}\.\d+\.\d+)\.x$/);
  return match ? `${match[1]}.x` : null;
}

function resolveExtractedTag(tag, branch) {
  if (/^\{\{\s*version_without_build\s*\}\}$/.test(String(tag).trim())) {
    return branchToVersionTag(branch) ?? tag;
  }

  return tag;
}

function buildExtractRegex(servicesChunk) {
  const alt = servicesChunk.map(escapeRegex).join('|');
  return new RegExp(
    `image:\\s*(['"])\\s*(?:\\{\\{\\s*docker_account\\s*\\}\\}|[^/\\s'"]+)\\s*/` +
      `(?<service>${alt}):` +
      `(?<tag>\\{\\{\\s*version_without_build\\s*\\}\\}|[^'"\\{\\s.]+)` +
      `\\.x\\s*` +
      `\\{\\{\\s*docker_image_suffix\\s*\\}\\}\\s*\\1`
  );
}

function parseGitGrepOutput(output) {
  const hits = [];
  let currentPath = null;
  const fullLinePattern = /^(?<path>.*):(?<line>\d+):(?<content>.*)$/;
  const headingMatchPattern = /^(?<line>\d+):(?<content>.*)$/;

  for (const raw of output.split('\n')) {
    if (!raw) {
      continue;
    }

    if (raw.endsWith(':') && !fullLinePattern.test(raw.slice(0, -1))) {
      currentPath = raw.slice(0, -1);
      continue;
    }

    const fullMatch = raw.match(fullLinePattern);
    if (fullMatch) {
      hits.push({
        path: fullMatch.groups.path,
        lineNo: Number(fullMatch.groups.line),
        line: fullMatch.groups.content,
      });
      continue;
    }

    if (!currentPath) {
      continue;
    }

    const headingMatch = raw.match(headingMatchPattern);
    if (!headingMatch) {
      continue;
    }

    hits.push({
      path: currentPath,
      lineNo: Number(headingMatch.groups.line),
      line: headingMatch.groups.content,
    });
  }

  return hits;
}

function grepBranchForServices(repoDir, branchRef, services, branchName, timeoutMs = 120000) {
  const found = new Map();

  for (const servicesChunk of chunkServicesForRegex(services)) {
    const extractRegex = buildExtractRegex(servicesChunk);
    const grepArgs = [
      'grep',
      '-n',
      '--no-color',
      '--no-heading',
      '--no-break',
      '-F',
      ...servicesChunk.flatMap((service) => ['-e', service]),
      branchRef,
    ];

    const { status, stdout, stderr } = runGit(repoDir, grepArgs, {
      allowFailure: true,
      timeoutMs,
    });

    if (status === 1) {
      continue;
    }

    if (status !== 0) {
      throw new Error(`git grep failed on ${branchRef}: ${stderr.trim()}`);
    }

    for (const hit of parseGitGrepOutput(stdout)) {
      const match = hit.line.match(extractRegex);
      if (!match?.groups) {
        continue;
      }

      const { service, tag } = match.groups;
      if (!found.has(service)) {
        found.set(service, resolveExtractedTag(tag, branchName));
      }
    }
  }

  return Object.fromEntries(found);
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

function resolveMaxWorkers(requestedWorkers, branchCount) {
  if (requestedWorkers != null) {
    return requestedWorkers;
  }

  const cpuCount = os.cpus().length || 4;
  return Math.min(32, cpuCount * 4, Math.max(4, branchCount));
}

async function getServicesTags(repoDir, services, branches, maxWorkers) {
  const servicesNorm = unique(services.map((service) => service.trim()).filter(Boolean));
  const branchesNorm = unique(branches.map((branch) => branch.trim()).filter(Boolean));

  const perService = Object.fromEntries(servicesNorm.map((service) => [service, {}]));

  if (!servicesNorm.length || !branchesNorm.length) {
    return perService;
  }

  const resolved = branchesNorm
    .map((branch) => {
      const ref = resolveBranchRef(repoDir, branch);
      return ref ? { branch, ref } : null;
    })
    .filter(Boolean);

  if (!resolved.length) {
    return perService;
  }

  const workers = resolveMaxWorkers(maxWorkers, resolved.length);

  await runWithConcurrency(resolved, async ({ branch, ref }) => {
    const branchHits = grepBranchForServices(repoDir, ref, servicesNorm, branch);
    for (const [service, tag] of Object.entries(branchHits)) {
      perService[service][branch] = tag;
    }
  }, workers);

  return perService;
}

function readServicesFile(filePath) {
  if (!fs.existsSync(filePath)) {
    throw new Error(`Services file not found: ${filePath}`);
  }

  return fs
    .readFileSync(filePath, 'utf8')
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => line && !line.startsWith('#'));
}

function sortMapping(mapping) {
  const sorted = {};
  for (const service of Object.keys(mapping).sort()) {
    const branchMap = mapping[service];
    sorted[service] = Object.fromEntries(
      Object.keys(branchMap)
        .sort()
        .map((branch) => [branch, branchMap[branch]])
    );
  }
  return sorted;
}

function writeMappingOutput(mapping) {
  fs.writeFileSync(
    OUTPUT_PATH,
    `${JSON.stringify(sortMapping(mapping), null, 2)}\n`,
    'utf8'
  );
}

function resolveServices(options) {
  const services = [];

  services.push(...parseCsvOrRepeat(options.services));

  if (options.servicesFile) {
    services.push(...readServicesFile(path.resolve(options.servicesFile)));
  } else if (!services.length && fs.existsSync(DEFAULT_SERVICES_FILE)) {
    services.push(...readServicesFile(DEFAULT_SERVICES_FILE));
  }

  const normalized = unique(services.map((service) => service.trim()).filter(Boolean));
  if (!normalized.length) {
    throw new Error(
      'No services provided. Use --services, --services-file, or create scripts/mapeamento-tags/service-list'
    );
  }

  return normalized;
}

function printUsage() {
  process.stderr.write(`Usage:
  node map-service-tags.js --repo <path> [--services <name[,name]>] [--services-file <path>]
                           [--branches <branch[,branch]>] [--branches-regex <regex>] [--workers <n>]

Output: ${OUTPUT_PATH}
`);
}

async function main(argv = process.argv.slice(2)) {
  let options;

  try {
    ({ values: options } = parseArgs({
      args: argv,
      options: {
        repo: { type: 'string' },
        services: { type: 'string', multiple: true },
        'services-file': { type: 'string' },
        branches: { type: 'string', multiple: true },
        'branches-regex': { type: 'string' },
        workers: { type: 'string' },
        help: { type: 'boolean', short: 'h' },
      },
      allowPositionals: false,
    }));
  } catch (error) {
    printUsage();
    throw error;
  }

  if (options.help) {
    printUsage();
    return 0;
  }

  if (!options.repo) {
    printUsage();
    throw new Error('--repo is required');
  }

  const repoDir = path.resolve(options.repo);
  if (!fs.existsSync(repoDir)) {
    throw new Error(`Repo path does not exist: ${repoDir}`);
  }

  const services = resolveServices(options);
  const branches = resolveTargetBranches(
    repoDir,
    options.branches,
    options['branches-regex']
  );
  const workers = options.workers != null ? Number(options.workers) : undefined;

  if (workers != null && (!Number.isInteger(workers) || workers < 1)) {
    throw new Error('--workers must be a positive integer');
  }

  const mapping = await getServicesTags(repoDir, services, branches, workers);
  writeMappingOutput(mapping);
  process.stderr.write(`Mapeamento gerado em ${OUTPUT_PATH}\n`);
  return 0;
}

if (require.main === module) {
  main()
    .then((code) => {
      process.exitCode = code;
    })
    .catch((error) => {
      process.stderr.write(`${error.message}\n`);
      process.exitCode = 1;
    });
}

module.exports = {
  DEFAULT_RELEASE_BRANCHES,
  branchToVersionTag,
  buildExtractRegex,
  getServicesTags,
  grepBranchForServices,
  parseGitGrepOutput,
  resolveExtractedTag,
  resolveTargetBranches,
  sortMapping,
};
