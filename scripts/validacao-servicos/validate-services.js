#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');

const REPO_ROOT = path.resolve(__dirname, '../..');
const ROLES_DIR = path.join(REPO_ROOT, 'roles');
const REPORT_PATH = path.join(__dirname, 'report.json');

const IMAGE_TAG_SUFFIX_PATTERN =
  /:\{\{ version_without_build \}\}\.x\{\{ docker_image_suffix \}\}$/;
const CONTAINER_NAME_SUFFIX = '-{{ version_without_build }}';
const ALLOWED_VERSION_FOLDERS = ['2025.1.0', '2024.2.0'];
const FRONTEND_STRATEGIC_ERROR =
  'Erro Estratégico: Serviços de Frontend não podem ser exclusivos. Mova este arquivo para as pastas de versão.';
const DOCKER_ACCOUNT_IMAGE_PREFIX = '{{ docker_account }}';
const FIXED_KORP_ACCOUNT_PREFIX = 'korp/';
const IGNORED_IMAGE_NAMES = ['korp.atualizacaosistema'];
const KORP_MANAGED_IMAGE_BASE_PATTERN = /^(korp\.|viasoft\.)/;
const YEAR_TAG_PREFIX_PATTERN = /^20\d{2}\.\d+\.\d+/;
const LEGACY_NUMERIC_TAG_PATTERN = /^[0-9]+\.[0-9]+(\.[0-9]+)?(\.x)?/i;

const FIXED_KORP_ACCOUNT_ERROR =
  "Chave 'image' usa prefixo fixo 'korp/' — use '{{ docker_account }}/'";

function getImageTag(image) {
  const value = String(image || '');
  const colonIndex = value.lastIndexOf(':');
  if (colonIndex === -1) {
    return '';
  }
  return value.slice(colonIndex + 1);
}

function usesFixedKorpAccount(image) {
  return String(image || '').startsWith(FIXED_KORP_ACCOUNT_PREFIX);
}

function isLegacyNumericImageTag(imageTag) {
  const tag = String(imageTag || '');
  if (!tag) {
    return false;
  }

  if (YEAR_TAG_PREFIX_PATTERN.test(tag)) {
    return false;
  }

  return LEGACY_NUMERIC_TAG_PATTERN.test(tag);
}

function isKorpManagedImage(image) {
  return KORP_MANAGED_IMAGE_BASE_PATTERN.test(getImageBaseName(image));
}

const FIXED_CONTAINER_NAME_IMAGE_BASES = new Set([
  'korp.legacy.frontend-router',
  'viasoft.loader',
]);

function getImageBaseName(image) {
  let name = String(image);

  const dockerAccountPrefix = `${DOCKER_ACCOUNT_IMAGE_PREFIX}/`;
  if (name.startsWith(dockerAccountPrefix)) {
    name = name.substring(dockerAccountPrefix.length);
  } else if (name.startsWith(FIXED_KORP_ACCOUNT_PREFIX)) {
    name = name.substring(FIXED_KORP_ACCOUNT_PREFIX.length);
  }

  const colonIndex = name.indexOf(':');
  if (colonIndex !== -1) {
    name = name.substring(0, colonIndex);
  }

  return name;
}

function isIgnoredImage(image) {
  return IGNORED_IMAGE_NAMES.includes(getImageBaseName(image));
}

function isEligibleForValidation(serviceConfig) {
  const image = serviceConfig?.image;
  if (image == null || image === '') {
    return false;
  }

  const imageStr = String(image);
  const hasDockerAccount = imageStr.startsWith(`${DOCKER_ACCOUNT_IMAGE_PREFIX}/`);
  const hasFixedKorpAccount = usesFixedKorpAccount(imageStr);

  if (!hasDockerAccount && !hasFixedKorpAccount) {
    return false;
  }

  if (isIgnoredImage(imageStr)) {
    return false;
  }

  if (hasFixedKorpAccount && !isKorpManagedImage(imageStr)) {
    return false;
  }

  return true;
}

function validateImageField(image, errors, { suffixPattern, suffixLabel }) {
  if (image == null || image === '') {
    errors.push("Chave 'image' ausente ou vazia");
    return;
  }

  const imageStr = String(image);

  if (usesFixedKorpAccount(imageStr)) {
    errors.push(FIXED_KORP_ACCOUNT_ERROR);
  }

  if (!suffixPattern.test(imageStr)) {
    errors.push(`Chave 'image' não termina com o padrão ${suffixLabel}`);
  }

  const imageTag = getImageTag(imageStr);
  if (isLegacyNumericImageTag(imageTag)) {
    errors.push(
      `Chave 'image' usa tag legada '${imageTag}' — use padrão ano (ex.: {{ version_without_build }}.x ou 2025.1.0.x)`
    );
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
    return { services: null, parseError: null };
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
    return { services: {}, parseError: null };
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
  return { services, parseError: null };
}

function getImageNameWithoutTag(image) {
  const imageStr = String(image);
  const colonIndex = imageStr.indexOf(':');
  if (colonIndex === -1) {
    return imageStr;
  }
  return imageStr.substring(0, colonIndex);
}

function isFrontendImage(image) {
  return getImageNameWithoutTag(image).endsWith('-frontend');
}

function versionToHyphen(version) {
  return version.replace(/\./g, '-');
}

function buildNonExclusiveImagePattern(version) {
  const escapedVersion = version.replace(/\./g, '\\.');
  return new RegExp(`:${escapedVersion}\\.x\\{\\{ docker_image_suffix \\}\\}$`);
}

function buildServiceDetails(serviceName, serviceConfig) {
  return {
    service_name: serviceName ?? null,
    image: serviceConfig?.image ?? null,
    container_name: serviceConfig?.container_name ?? null,
  };
}

function emptyServiceDetails() {
  return {
    service_name: null,
    image: null,
    container_name: null,
  };
}

function validateExclusiveService(serviceName, serviceConfig) {
  const image = serviceConfig?.image ?? null;
  const containerName = serviceConfig?.container_name ?? null;
  const details = buildServiceDetails(serviceName, serviceConfig);

  if (image != null && isFrontendImage(image)) {
    return {
      is_valid: false,
      errors: [FRONTEND_STRATEGIC_ERROR],
      details,
    };
  }

  const errors = [];

  validateImageField(image, errors, {
    suffixPattern: IMAGE_TAG_SUFFIX_PATTERN,
    suffixLabel: ':{{ version_without_build }}.x{{ docker_image_suffix }}',
  });

  const imageBaseName = image != null ? getImageBaseName(image) : null;
  const hasFixedContainerName =
    imageBaseName != null && FIXED_CONTAINER_NAME_IMAGE_BASES.has(imageBaseName);

  if (containerName == null || containerName === '') {
    errors.push("Chave 'container_name' ausente ou vazia");
  } else if (!hasFixedContainerName && !String(containerName).endsWith(CONTAINER_NAME_SUFFIX)) {
    errors.push("Chave 'container_name' não possui o sufixo -{{ version_without_build }}");
  }

  return {
    is_valid: errors.length === 0,
    errors,
    details,
  };
}

function validateNonExclusiveService(serviceName, serviceConfig, versionFolder) {
  const image = serviceConfig?.image ?? null;
  const containerName = serviceConfig?.container_name ?? null;
  const details = buildServiceDetails(serviceName, serviceConfig);
  const errors = [];

  const expectedServiceSuffix = `-${versionToHyphen(versionFolder)}`;
  if (!serviceName.endsWith(expectedServiceSuffix)) {
    errors.push(
      `O nome do serviço deveria terminar com '${expectedServiceSuffix}' mas foi encontrado '${serviceName}'`
    );
  }

  const imagePattern = buildNonExclusiveImagePattern(versionFolder);
  const expectedImageSuffix = `:${versionFolder}.x{{ docker_image_suffix }}`;

  validateImageField(image, errors, {
    suffixPattern: imagePattern,
    suffixLabel: expectedImageSuffix,
  });

  const expectedContainerSuffix = `-${versionFolder}`;
  if (containerName == null || containerName === '') {
    errors.push("Chave 'container_name' ausente ou vazia");
  } else if (!String(containerName).endsWith(expectedContainerSuffix)) {
    errors.push(
      `O container_name deveria terminar com '${expectedContainerSuffix}' mas foi encontrado '${containerName}'`
    );
  }

  return {
    is_valid: errors.length === 0,
    errors,
    details,
  };
}

function parseComposeFile(filePath) {
  const rawContent = fs.readFileSync(filePath, 'utf8');

  try {
    const { services, parseError } = extractServicesFromCompose(rawContent);
    if (parseError) {
      return { doc: null, parseError };
    }

    return { doc: { services }, parseError: null };
  } catch (error) {
    return { doc: null, parseError: error.message };
  }
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

function listExclusiveComposeFiles(roleName) {
  const composesDir = path.join(ROLES_DIR, roleName, 'templates', 'composes');

  if (!fs.existsSync(composesDir)) {
    return [];
  }

  return fs
    .readdirSync(composesDir, { withFileTypes: true })
    .filter((entry) => entry.isFile() && entry.name.endsWith('.yml.j2'))
    .map((entry) => path.join(composesDir, entry.name))
    .sort();
}

function listNonExclusiveComposeFiles(roleName) {
  const composesDir = path.join(ROLES_DIR, roleName, 'templates', 'composes');

  if (!fs.existsSync(composesDir)) {
    return [];
  }

  const files = [];

  for (const versionFolder of ALLOWED_VERSION_FOLDERS) {
    const versionDir = path.join(composesDir, versionFolder);
    if (!fs.existsSync(versionDir)) {
      continue;
    }

    for (const fileEntry of fs.readdirSync(versionDir, { withFileTypes: true })) {
      if (fileEntry.isFile() && fileEntry.name.endsWith('.yml.j2')) {
        files.push({
          filePath: path.join(versionDir, fileEntry.name),
          versionFolder,
        });
      }
    }
  }

  return files.sort((a, b) => {
    const pathCompare = a.filePath.localeCompare(b.filePath);
    if (pathCompare !== 0) {
      return pathCompare;
    }
    return a.versionFolder.localeCompare(b.versionFolder);
  });
}

function toRelativePath(absolutePath) {
  return path.relative(REPO_ROOT, absolutePath).split(path.sep).join('/');
}

function buildExclusiveEntry(role, relativePath, validation) {
  const base = {
    role,
    file_path: relativePath,
  };

  if (validation.is_valid) {
    return {
      ...base,
      details: validation.details,
    };
  }

  return {
    ...base,
    errors: validation.errors,
    details: validation.details,
  };
}

function buildNonExclusiveEntry(role, relativePath, versionFolder, validation) {
  const base = {
    role,
    version_folder: versionFolder,
    file_path: relativePath,
  };

  if (validation.is_valid) {
    return {
      ...base,
      details: validation.details,
    };
  }

  return {
    ...base,
    errors: validation.errors,
    details: validation.details,
  };
}

function scanExclusiveServices(roles) {
  const invalidServices = [];
  const validServices = [];

  for (const role of roles) {
    for (const filePath of listExclusiveComposeFiles(role)) {
      const relativePath = toRelativePath(filePath);
      const { doc, parseError } = parseComposeFile(filePath);

      if (parseError) {
        invalidServices.push({
          role,
          file_path: relativePath,
          errors: [`Falha ao interpretar YAML: ${parseError}`],
          details: emptyServiceDetails(),
        });
        continue;
      }

      const services = doc?.services;
      if (!services || typeof services !== 'object') {
        invalidServices.push({
          role,
          file_path: relativePath,
          errors: ["Bloco 'services' ausente ou inválido no compose"],
          details: emptyServiceDetails(),
        });
        continue;
      }

      for (const [serviceName, serviceConfig] of Object.entries(services)) {
        if (!isEligibleForValidation(serviceConfig)) {
          continue;
        }

        const validation = validateExclusiveService(serviceName, serviceConfig);
        const entry = buildExclusiveEntry(role, relativePath, validation);

        if (validation.is_valid) {
          validServices.push(entry);
        } else {
          invalidServices.push(entry);
        }
      }
    }
  }

  return { invalidServices, validServices };
}

function scanNonExclusiveServices(roles) {
  const invalidServices = [];
  const validServices = [];

  for (const role of roles) {
    for (const { filePath, versionFolder } of listNonExclusiveComposeFiles(role)) {
      const relativePath = toRelativePath(filePath);
      const { doc, parseError } = parseComposeFile(filePath);

      if (parseError) {
        invalidServices.push({
          role,
          version_folder: versionFolder,
          file_path: relativePath,
          errors: [`Falha ao interpretar YAML: ${parseError}`],
          details: emptyServiceDetails(),
        });
        continue;
      }

      const services = doc?.services;
      if (!services || typeof services !== 'object') {
        invalidServices.push({
          role,
          version_folder: versionFolder,
          file_path: relativePath,
          errors: ["Bloco 'services' ausente ou inválido no compose"],
          details: emptyServiceDetails(),
        });
        continue;
      }

      for (const [serviceName, serviceConfig] of Object.entries(services)) {
        if (!isEligibleForValidation(serviceConfig)) {
          continue;
        }

        const validation = validateNonExclusiveService(
          serviceName,
          serviceConfig,
          versionFolder
        );
        const entry = buildNonExclusiveEntry(role, relativePath, versionFolder, validation);

        if (validation.is_valid) {
          validServices.push(entry);
        } else {
          invalidServices.push(entry);
        }
      }
    }
  }

  return { invalidServices, validServices };
}

function scanServices() {
  const roles = listRoleDirectories();
  const exclusive = scanExclusiveServices(roles);
  const nonExclusive = scanNonExclusiveServices(roles);

  return {
    summary: {
      total_roles_scanned: roles.length,
      exclusive_services: {
        total_found: exclusive.validServices.length + exclusive.invalidServices.length,
        valid: exclusive.validServices.length,
        invalid: exclusive.invalidServices.length,
      },
      non_exclusive_services: {
        total_found: nonExclusive.validServices.length + nonExclusive.invalidServices.length,
        valid: nonExclusive.validServices.length,
        invalid: nonExclusive.invalidServices.length,
      },
    },
    results: {
      exclusive: {
        invalid_services: exclusive.invalidServices,
        valid_services: exclusive.validServices,
      },
      non_exclusive: {
        invalid_services: nonExclusive.invalidServices,
        valid_services: nonExclusive.validServices,
      },
    },
  };
}

function main() {
  const report = scanServices();
  fs.writeFileSync(REPORT_PATH, `${JSON.stringify(report, null, 2)}\n`, 'utf8');
  process.stderr.write(`Relatório gerado em ${REPORT_PATH}\n`);
}

if (require.main === module) {
  main();
}

module.exports = {
  extractServicesFromCompose,
  getImageBaseName,
  getImageTag,
  isIgnoredImage,
  isEligibleForValidation,
  usesFixedKorpAccount,
  isLegacyNumericImageTag,
  isKorpManagedImage,
  validateExclusiveService,
  validateNonExclusiveService,
  validateImageField,
  scanServices,
  FIXED_KORP_ACCOUNT_ERROR,
  DOCKER_ACCOUNT_IMAGE_PREFIX,
  FIXED_KORP_ACCOUNT_PREFIX,
};
