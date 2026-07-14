#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');

const REPORT_PATH = path.join(__dirname, '../validacao-servicos/report.json');
const REPO_ROOT = path.resolve(__dirname, '../..');
const ALLOWED_VERSION_FOLDERS = ['2025.2.0', '2025.1.0', '2024.2.0'];

const UNVERSIONED_SERVICE_EXCEPTIONS = new Set([
  'Korp.AtualizacaoSistema',
  'Korp.Legacy.Frontend-router',
  'Viasoft.Loader',
]);

const FRONTEND_STRATEGIC_ERROR =
  'Erro Estratégico: Serviços de Frontend não podem ser exclusivos. Mova este arquivo para as pastas de versão.';

const NON_EXCLUSIVE_IMAGE_TAG_SUFFIX_PATTERN =
  /:(?:\{\{\s*version_without_build\s*\}\}|[^"'\s]+)\.x\{\{\s*docker_image_suffix\s*\}\}$/;

function replaceNonExclusiveImageTagSuffix(value, versionFolder) {
  const expectedSuffix = `:${versionFolder}.x{{ docker_image_suffix }}`;
  let normalized = value.replace(/^korp\//, '{{ docker_account }}/');

  if (normalized.endsWith(expectedSuffix)) {
    return normalized === value ? null : normalized;
  }

  if (!NON_EXCLUSIVE_IMAGE_TAG_SUFFIX_PATTERN.test(normalized)) {
    return normalized === value ? null : normalized;
  }

  const updated = normalized.replace(NON_EXCLUSIVE_IMAGE_TAG_SUFFIX_PATTERN, expectedSuffix);
  return updated === value ? null : updated;
}

function versionToHyphen(version) {
  return version.replace(/\./g, '-');
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

function replaceServiceKeyLine(line, oldName, newName) {
  const match = line.match(/^(\s*)(.+?):\s*$/);
  if (!match || parseServiceKeyLine(line) !== oldName) {
    return line;
  }

  const rawKey = match[2].trim();
  if (
    (rawKey.startsWith('"') && rawKey.endsWith('"')) ||
    (rawKey.startsWith("'") && rawKey.endsWith("'"))
  ) {
    const quote = rawKey[0];
    return `${match[1]}${quote}${newName}${quote}:`;
  }

  return `${match[1]}${newName}:`;
}

function locateServicesSection(lines) {
  const servicesLineIndex = lines.findIndex((line) => /^services:\s*$/.test(line));
  if (servicesLineIndex === -1) {
    return null;
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
    return null;
  }

  return { servicesLineIndex, servicesIndent, serviceIndent };
}

function locateServiceBlock(lines, serviceName) {
  const section = locateServicesSection(lines);
  if (!section) {
    return null;
  }

  const { servicesLineIndex, servicesIndent, serviceIndent } = section;

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
      const key = parseServiceKeyLine(line);
      if (key !== serviceName) {
        continue;
      }

      let end = i;
      for (let j = i + 1; j < lines.length; j += 1) {
        const nextLine = lines[j];
        const nextTrimmed = nextLine.trim();
        if (!nextTrimmed || nextTrimmed.startsWith('#')) {
          end = j;
          continue;
        }

        const nextIndent = nextLine.match(/^(\s*)/)[1].length;
        if (nextIndent <= servicesIndent) {
          break;
        }

        if (nextIndent === serviceIndent && nextTrimmed.endsWith(':') && !nextTrimmed.startsWith('-')) {
          break;
        }

        end = j;
      }

      return { start: i, end, serviceIndent };
    }
  }

  return null;
}

function extractComposePreamble(lines) {
  const section = locateServicesSection(lines);
  if (!section) {
    return null;
  }

  return lines.slice(0, section.servicesLineIndex + 1);
}

function removeServiceBlock(lines, block) {
  const next = [...lines.slice(0, block.start), ...lines.slice(block.end + 1)];

  while (next[block.start - 1] === '' && block.start > 0) {
    next.splice(block.start - 1, 1);
  }

  return next;
}

function fixLineInBlock(blockLines, fieldName, transform) {
  const pattern = new RegExp(`^(\\s+${fieldName}:\\s*)(.+)$`);
  let changed = false;

  const updated = blockLines.map((line) => {
    const match = line.match(pattern);
    if (!match) {
      return line;
    }

    const currentValue = parseScalarValue(match[2]);
    const newValue = transform(currentValue, line);
    if (newValue == null || newValue === currentValue) {
      return line;
    }

    changed = true;
    return `${match[1]}"${newValue}"`;
  });

  return { lines: updated, changed };
}

function fixExclusiveImageLine(line) {
  const match = line.match(/^(\s+image:\s*)(.+)$/);
  if (!match) {
    return { line, changed: false };
  }

  const raw = match[2].trim();
  const value =
    (raw.startsWith('"') && raw.endsWith('"')) || (raw.startsWith("'") && raw.endsWith("'"))
      ? raw.slice(1, -1)
      : raw;

  let fixed = value.replace(/^korp\//, '{{ docker_account }}/');
  fixed = fixed.replace(
    /:(?!\{\{\s*version_without_build\s*\}\})[^"'\s]+\.x\{\{\s*docker_image_suffix\s*\}\}/,
    ':{{ version_without_build }}.x{{ docker_image_suffix }}'
  );

  if (fixed === value) {
    return { line, changed: false };
  }

  return {
    line: `${match[1]}"${fixed}"`,
    changed: true,
  };
}

function fixExclusiveContainerNameLine(line) {
  const match = line.match(/^(\s+container_name:\s*)(.+)$/);
  if (!match) {
    return { line, changed: false };
  }

  const value = parseScalarValue(match[2]);
  const suffix = '-{{ version_without_build }}';
  if (value.endsWith(suffix)) {
    return { line, changed: false };
  }

  return {
    line: `${match[1]}"${value}${suffix}"`,
    changed: true,
  };
}

function fixNonExclusiveServiceKey(serviceName, versionFolder) {
  const wrongSuffix = `-${versionFolder}`;
  const expectedSuffix = `-${versionToHyphen(versionFolder)}`;

  if (serviceName.endsWith(expectedSuffix)) {
    return null;
  }

  if (serviceName.endsWith(wrongSuffix)) {
    return serviceName.slice(0, -wrongSuffix.length) + expectedSuffix;
  }

  return null;
}

function transformFrontendBlockForVersion(blockLines, serviceName, versionFolder) {
  const versionHyphen = versionToHyphen(versionFolder);
  const newServiceName = `${serviceName}-${versionHyphen}`;
  const newContainerName = `${serviceName}-${versionFolder}`;

  return blockLines.map((line, index) => {
    if (index === 0) {
      return replaceServiceKeyLine(line, serviceName, newServiceName);
    }

    if (/^\s+image:/.test(line)) {
      const currentValue = parseScalarValue(line.replace(/^\s+image:\s*/, ''));
      const updatedValue = replaceNonExclusiveImageTagSuffix(currentValue, versionFolder);
      if (updatedValue != null && updatedValue !== currentValue) {
        const indent = line.match(/^(\s+)/)[1];
        return `${indent}image: "${updatedValue}"`;
      }
    }

    if (/^\s+container_name:/.test(line)) {
      const indent = line.match(/^(\s+)/)[1];
      return `${indent}container_name: "${newContainerName}"`;
    }

    if (/^\s+restart:/.test(line)) {
      return line.replace(/^\s+restart:.*/, '    restart: unless-stopped');
    }

    return line;
  });
}

function isFrontendStrategicError(errors) {
  return errors.some((error) => error.includes(FRONTEND_STRATEGIC_ERROR.slice(0, 30)));
}

function isServiceNameError(errors) {
  return errors.some((error) => error.startsWith('O nome do serviço deveria terminar com'));
}

function isNonExclusiveContainerNameError(errors) {
  return errors.some((error) => error.startsWith('O container_name deveria terminar com'));
}

function isNonExclusiveImageError(errors) {
  return errors.some((error) => error.startsWith("Chave 'image'"));
}

function isExclusiveContainerNameError(errors) {
  return errors.some((error) =>
    error.includes("Chave 'container_name' não possui o sufixo -{{ version_without_build }}")
  );
}

function isExclusiveImageError(errors) {
  return errors.some((error) => error.startsWith("Chave 'image'"));
}

function loadReport() {
  if (!fs.existsSync(REPORT_PATH)) {
    throw new Error(`Arquivo report.json não encontrado em ${REPORT_PATH}`);
  }

  return JSON.parse(fs.readFileSync(REPORT_PATH, 'utf8'));
}

function resolveRepoPath(relativePath) {
  return path.join(REPO_ROOT, relativePath);
}

function isServiceKeyLine(line, serviceIndent) {
  if (!line?.trim() || line.trim().startsWith('#')) {
    return false;
  }

  const indent = line.match(/^(\s*)/)[1].length;
  const trimmed = line.trim();

  return (
    indent === serviceIndent &&
    trimmed.endsWith(':') &&
    !trimmed.startsWith('-') &&
    parseServiceKeyLine(line) != null
  );
}

function listServiceStartIndices(lines) {
  const section = locateServicesSection(lines);
  if (!section) {
    return [];
  }

  const { servicesLineIndex, servicesIndent, serviceIndent } = section;
  const serviceStarts = [];

  for (let i = servicesLineIndex + 1; i < lines.length; i += 1) {
    const line = lines[i];
    if (!line.trim()) {
      continue;
    }

    const indent = line.match(/^(\s*)/)[1].length;
    if (indent <= servicesIndent) {
      break;
    }

    if (isServiceKeyLine(line, serviceIndent)) {
      serviceStarts.push(i);
    }
  }

  return serviceStarts;
}

function ensureBlankLinesBetweenServices(lines) {
  const serviceStarts = listServiceStartIndices(lines);
  if (serviceStarts.length < 2) {
    return lines;
  }

  const result = [...lines];

  for (let index = serviceStarts.length - 1; index >= 1; index -= 1) {
    const currStart = serviceStarts[index];
    const prevStart = serviceStarts[index - 1];

    let blankCount = 0;
    for (let lineIndex = currStart - 1; lineIndex > prevStart; lineIndex -= 1) {
      if (result[lineIndex].trim() === '') {
        blankCount += 1;
      }
    }

    if (blankCount === 0) {
      result.splice(currStart, 0, '');
      continue;
    }

    if (blankCount > 1) {
      let removed = 0;
      for (let lineIndex = currStart - 1; lineIndex > prevStart && removed < blankCount - 1; lineIndex -= 1) {
        if (result[lineIndex].trim() === '') {
          result.splice(lineIndex, 1);
          removed += 1;
        }
      }
    }
  }

  return result;
}

function writeFileLines(filePath, lines) {
  const normalized = ensureBlankLinesBetweenServices(lines);
  fs.writeFileSync(filePath, `${normalized.join('\n')}\n`, 'utf8');
}

function appendServiceToCompose(content, serviceBlockLines) {
  const lines = content.replace(/\n?$/, '').split('\n');

  if (lines.length === 0) {
    return ensureBlankLinesBetweenServices(serviceBlockLines).join('\n');
  }

  const needsLeadingBlank = lines[lines.length - 1].trim() !== '';
  const merged = needsLeadingBlank
    ? [...lines, '', ...serviceBlockLines]
    : [...lines.slice(0, -1), ...serviceBlockLines, ''];

  return ensureBlankLinesBetweenServices(merged).join('\n');
}

function migrateFrontendService(sourcePath, serviceName, summary) {
  const absolutePath = resolveRepoPath(sourcePath);
  if (!fs.existsSync(absolutePath)) {
    summary.skipped.push({ file_path: sourcePath, service_name: serviceName, reason: 'Arquivo não encontrado' });
    return;
  }

  let lines = fs.readFileSync(absolutePath, 'utf8').split('\n');
  const block = locateServiceBlock(lines, serviceName);
  if (!block) {
    summary.skipped.push({
      file_path: sourcePath,
      service_name: serviceName,
      reason: 'Bloco do serviço não localizado',
    });
    return;
  }

  const blockLines = lines.slice(block.start, block.end + 1);
  const preamble = extractComposePreamble(lines);
  if (!preamble) {
    summary.skipped.push({
      file_path: sourcePath,
      service_name: serviceName,
      reason: "Seção 'services' não localizada",
    });
    return;
  }

  const composeBaseName = path.basename(absolutePath);
  const composesDir = path.dirname(absolutePath);

  for (const versionFolder of ALLOWED_VERSION_FOLDERS) {
    const versionDir = path.join(composesDir, versionFolder);
    const versionFilePath = path.join(versionDir, composeBaseName);
    const transformedBlock = transformFrontendBlockForVersion(
      blockLines,
      serviceName,
      versionFolder
    );

    fs.mkdirSync(versionDir, { recursive: true });

    if (fs.existsSync(versionFilePath)) {
      const existing = fs.readFileSync(versionFilePath, 'utf8');
      const existingLines = existing.split('\n');
      const newServiceName = `${serviceName}-${versionToHyphen(versionFolder)}`;

      if (locateServiceBlock(existingLines, newServiceName)) {
        summary.skipped.push({
          file_path: path.relative(REPO_ROOT, versionFilePath),
          service_name: newServiceName,
          reason: 'Serviço já existe na pasta de versão',
        });
        continue;
      }

      writeFileLines(versionFilePath, appendServiceToCompose(existing, transformedBlock).split('\n'));
    } else {
      writeFileLines(versionFilePath, [...preamble, ...transformedBlock]);
    }

    summary.corrected.push({
      action: 'frontend_migrated',
      from: sourcePath,
      to: path.relative(REPO_ROOT, versionFilePath),
      service_name: serviceName,
    });
  }

  lines = removeServiceBlock(lines, block);
  writeFileLines(absolutePath, lines);
}

function applyInPlaceFixes(filePath, items, summary) {
  const absolutePath = resolveRepoPath(filePath);
  if (!fs.existsSync(absolutePath)) {
    for (const item of items) {
      summary.skipped.push({
        file_path: filePath,
        service_name: item.details?.service_name,
        reason: 'Arquivo não encontrado',
      });
    }
    return;
  }

  let lines = fs.readFileSync(absolutePath, 'utf8').split('\n');
  let fileChanged = false;

  for (const item of items) {
    const serviceName = item.details?.service_name;
    if (!serviceName) {
      summary.skipped.push({ file_path: filePath, reason: 'service_name ausente no report' });
      continue;
    }

    const block = locateServiceBlock(lines, serviceName);
    if (!block) {
      summary.skipped.push({
        file_path: filePath,
        service_name: serviceName,
        reason: 'Bloco do serviço não localizado',
      });
      continue;
    }

    let blockLines = lines.slice(block.start, block.end + 1);
    let blockChanged = false;

    if (isServiceNameError(item.errors) && item.version_folder) {
      const newServiceName = fixNonExclusiveServiceKey(serviceName, item.version_folder);
      if (newServiceName) {
        blockLines[0] = replaceServiceKeyLine(blockLines[0], serviceName, newServiceName);
        blockChanged = true;
      } else {
        summary.skipped.push({
          file_path: filePath,
          service_name: serviceName,
          reason: 'Correção automática do nome do serviço não aplicável',
        });
      }
    }

    if (isNonExclusiveImageError(item.errors) && item.version_folder) {
      const imageFix = fixLineInBlock(blockLines, 'image', (value) =>
        replaceNonExclusiveImageTagSuffix(value, item.version_folder)
      );
      blockLines = imageFix.lines;
      blockChanged = blockChanged || imageFix.changed;
    }

    if (isNonExclusiveContainerNameError(item.errors) && item.version_folder) {
      const containerFix = fixLineInBlock(blockLines, 'container_name', (value) => {
        const expectedSuffix = `-${item.version_folder}`;
        if (value.endsWith(expectedSuffix)) {
          return null;
        }

        const prefix = value.replace(/-\d+(?:\.\d+)*$/, '').replace(/-\d+(?:-\d+)*$/, '');
        if (prefix && prefix !== value) {
          return `${prefix}${expectedSuffix}`;
        }

        const base = value.split('-')[0];
        return `${base}${expectedSuffix}`;
      });
      blockLines = containerFix.lines;
      blockChanged = blockChanged || containerFix.changed;
    }

    if (isExclusiveImageError(item.errors)) {
      blockLines = blockLines.map((line) => {
        if (!/^\s+image:/.test(line)) {
          return line;
        }
        const result = fixExclusiveImageLine(line);
        if (result.changed) {
          blockChanged = true;
        }
        return result.line;
      });
    }

    if (isExclusiveContainerNameError(item.errors)) {
      blockLines = blockLines.map((line) => {
        if (!/^\s+container_name:/.test(line)) {
          return line;
        }
        const result = fixExclusiveContainerNameLine(line);
        if (result.changed) {
          blockChanged = true;
        }
        return result.line;
      });
    }

    if (blockChanged) {
      lines = [...lines.slice(0, block.start), ...blockLines, ...lines.slice(block.end + 1)];
      fileChanged = true;
      summary.corrected.push({
        action: 'in_place_fix',
        file_path: filePath,
        service_name: serviceName,
      });
    } else if (!isFrontendStrategicError(item.errors)) {
      summary.skipped.push({
        file_path: filePath,
        service_name: serviceName,
        reason: 'Nenhuma correção automática aplicável',
      });
    }
  }

  if (fileChanged) {
    writeFileLines(absolutePath, lines);
  }
}

function groupByFile(items) {
  const groups = new Map();

  for (const item of items) {
    if (!groups.has(item.file_path)) {
      groups.set(item.file_path, []);
    }
    groups.get(item.file_path).push(item);
  }

  return groups;
}

function roleHasVersionedComposes(roleName) {
  const composesDir = path.join(REPO_ROOT, 'roles', roleName, 'templates', 'composes');
  if (!fs.existsSync(composesDir)) {
    return false;
  }

  const entries = fs.readdirSync(composesDir, { withFileTypes: true });

  if (entries.some((entry) => entry.isFile() && entry.name.endsWith('.yml.j2'))) {
    return true;
  }

  return ALLOWED_VERSION_FOLDERS.some((versionFolder) => {
    const versionDir = path.join(composesDir, versionFolder);
    if (!fs.existsSync(versionDir)) {
      return false;
    }

    return fs
      .readdirSync(versionDir, { withFileTypes: true })
      .some((entry) => entry.isFile() && entry.name.endsWith('.yml.j2'));
  });
}

function listVersionedRoles() {
  const rolesDir = path.join(REPO_ROOT, 'roles');
  if (!fs.existsSync(rolesDir)) {
    return [];
  }

  return fs
    .readdirSync(rolesDir, { withFileTypes: true })
    .filter((entry) => entry.isDirectory())
    .map((entry) => entry.name)
    .filter(roleHasVersionedComposes)
    .sort();
}

function removeUnversionedTrueFromVars(content) {
  let currentSection = null;
  let currentService = null;

  return content
    .split('\n')
    .filter((line) => {
      if (/^services:\s*$/.test(line)) {
        currentSection = 'services';
        currentService = null;
        return true;
      }

      if (/^delphi_services:\s*$/.test(line)) {
        currentSection = 'delphi_services';
        currentService = null;
        return true;
      }

      if (/^[A-Za-z_][\w-]*:\s*$/.test(line)) {
        currentSection = null;
        currentService = null;
      }

      if (currentSection === 'services') {
        const serviceMatch = line.match(/^  (\S.*?):\s*$/);
        if (serviceMatch) {
          currentService = parseScalarValue(serviceMatch[1]);
        }
      }

      if (/^\s+unversioned:\s*true\s*$/.test(line)) {
        if (currentSection !== 'services') {
          return true;
        }

        return UNVERSIONED_SERVICE_EXCEPTIONS.has(currentService);
      }

      return true;
    })
    .join('\n');
}

function listRoleVarsYamlFiles(roleName) {
  const varsDir = path.join(REPO_ROOT, 'roles', roleName, 'vars');
  if (!fs.existsSync(varsDir)) {
    return [];
  }

  return fs
    .readdirSync(varsDir, { withFileTypes: true })
    .filter((entry) => entry.isFile() && entry.name.endsWith('.yml'))
    .map((entry) => path.join(varsDir, entry.name))
    .sort();
}

function removeLegacyUnversionedFlags(summary) {
  for (const role of listVersionedRoles()) {
    for (const varsPath of listRoleVarsYamlFiles(role)) {
      const original = fs.readFileSync(varsPath, 'utf8');
      if (!/^\s+unversioned:\s*true\s*$/m.test(original)) {
        continue;
      }

      const updated = removeUnversionedTrueFromVars(original);
      if (updated === original) {
        continue;
      }

      fs.writeFileSync(varsPath, updated.endsWith('\n') ? updated : `${updated}\n`, 'utf8');

      const relativePath = path.relative(REPO_ROOT, varsPath);
      const removedCount =
        (original.match(/^\s+unversioned:\s*true\s*$/gm) ?? []).length -
        (updated.match(/^\s+unversioned:\s*true\s*$/gm) ?? []).length;

      summary.corrected.push({
        action: 'unversioned_flag_removed',
        file_path: relativePath,
        role,
        removed_count: removedCount,
      });
    }
  }
}

function runFixes() {
  const report = loadReport();
  const summary = {
    corrected: [],
    skipped: [],
  };

  const exclusiveInvalid = report.results?.exclusive?.invalid_services ?? [];
  const nonExclusiveInvalid = report.results?.non_exclusive?.invalid_services ?? [];

  const frontendItems = exclusiveInvalid.filter((item) => isFrontendStrategicError(item.errors));
  const exclusiveInPlaceItems = exclusiveInvalid.filter(
    (item) => !isFrontendStrategicError(item.errors)
  );

  for (const [filePath, items] of groupByFile(nonExclusiveInvalid)) {
    applyInPlaceFixes(filePath, items, summary);
  }

  for (const [filePath, items] of groupByFile(exclusiveInPlaceItems)) {
    applyInPlaceFixes(filePath, items, summary);
  }

  for (const item of frontendItems) {
    migrateFrontendService(item.file_path, item.details.service_name, summary);
  }

  removeLegacyUnversionedFlags(summary);

  return summary;
}

function printSummary(summary) {
  const correctedCount = summary.corrected.length;
  const skippedCount = summary.skipped.length;

  process.stderr.write('\n=== Sumário de Correções ===\n');
  process.stderr.write(`Corrigidos com sucesso: ${correctedCount}\n`);
  process.stderr.write(`Ignorados/alertas: ${skippedCount}\n`);

  if (summary.corrected.length) {
    process.stderr.write('\nCorreções aplicadas:\n');
    for (const entry of summary.corrected) {
      if (entry.action === 'frontend_migrated') {
        process.stderr.write(
          `  [frontend] ${entry.service_name}: ${entry.from} -> ${entry.to}\n`
        );
      } else if (entry.action === 'unversioned_flag_removed') {
        process.stderr.write(
          `  [unversioned] ${entry.role}: removido(s) ${entry.removed_count} flag(s) em ${entry.file_path}\n`
        );
      } else {
        process.stderr.write(`  [fix] ${entry.service_name} em ${entry.file_path}\n`);
      }
    }
  }

  if (summary.skipped.length) {
    process.stderr.write('\nItens ignorados:\n');
    for (const entry of summary.skipped) {
      const service = entry.service_name ? ` (${entry.service_name})` : '';
      process.stderr.write(`  ${entry.file_path}${service}: ${entry.reason}\n`);
    }
  }
}

function main() {
  const summary = runFixes();
  printSummary(summary);
}

if (require.main === module) {
  try {
    main();
  } catch (error) {
    process.stderr.write(`${error.message}\n`);
    process.exitCode = 1;
  }
}

module.exports = {
  runFixes,
  locateServiceBlock,
  fixNonExclusiveServiceKey,
  transformFrontendBlockForVersion,
  ensureBlankLinesBetweenServices,
  listRoleVarsYamlFiles,
  removeLegacyUnversionedFlags,
  removeUnversionedTrueFromVars,
  replaceNonExclusiveImageTagSuffix,
  roleHasVersionedComposes,
};
