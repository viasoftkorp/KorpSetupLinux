#!/usr/bin/env node
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');

const {
  isCoreService,
  calculateTagsForService,
  filterEligibleServices,
  resolveGithubDomain,
  versionToReleaseBranch,
  runCreateTags,
} = require('./create-tags-github.js');

describe('isCoreService / filtro de prefixo', () => {
  it('aceita korp. e viasoft.', () => {
    assert.equal(isCoreService('korp.api.gateway.vendas'), true);
    assert.equal(isCoreService('viasoft.vendas.core'), true);
  });

  it('rejeita prefixos externos', () => {
    assert.equal(isCoreService('external.tool-integration'), false);
    assert.equal(isCoreService('sdk.app-builder-parcel'), false);
  });
});

describe('calculateTagsForService', () => {
  it('incrementa build de serviço não-versionado para 2025.1.0.x', () => {
    const tags = calculateTagsForService({
      servico_bitbucket: 'korp.suporte-cli',
      categoria: 'nao-versionados',
      referencia_bitbucket: { ultima_tag_absoluta: '1.5.12' },
    });
    assert.deepEqual(tags, ['korp.suporte-cli-2025.1.0.13']);
  });

  it('usa fallback 2025.1.0.1 sem histórico no Bitbucket', () => {
    const tags = calculateTagsForService({
      servico_bitbucket: 'korp.compras.core',
      categoria: 'nao-versionados',
      referencia_bitbucket: { ultima_tag_absoluta: 'Não encontrada' },
    });
    assert.deepEqual(tags, ['korp.compras.core-2025.1.0.1']);
  });

  it('gera uma tag por janela versionada com build+1', () => {
    const tags = calculateTagsForService({
      servico_bitbucket: 'viasoft.financeiro-api',
      categoria: 'versionados',
      referencia_bitbucket: {
        'janela_2025.1.0.x': '2025.1.0.4',
        'janela_2024.2.0.x': '2024.2.0.80',
        'janela_2024.1.0.x': 'Não encontrada',
      },
    });
    assert.deepEqual(tags.sort(), [
      'viasoft.financeiro-api-2024.2.0.81',
      'viasoft.financeiro-api-2025.1.0.5',
    ]);
  });

  it('preserva sufixo frontend no nome da tag', () => {
    const tags = calculateTagsForService({
      servico_bitbucket: 'viasoft.sales.crm.core-frontend',
      categoria: 'versionados',
      referencia_bitbucket: {
        'janela_2025.1.0.x': '2025.1.0.10',
      },
    });
    assert.deepEqual(tags, ['viasoft.sales.crm.core-frontend-2025.1.0.11']);
  });
});

describe('resolveGithubDomain', () => {
  it('mapeia chave curta do Bitbucket para monorepo GitHub', () => {
    assert.equal(
      resolveGithubDomain({
        dominio_github: 'sal',
        servico_bitbucket: 'korp.api.gateway.vendas',
      }),
      'vendas'
    );
    assert.equal(
      resolveGithubDomain({
        dominio_github: 'log',
        servico_bitbucket: 'korp.api.gateway.logistica',
      }),
      'logistica'
    );
  });

  it('mantém domínio GitHub já resolvido', () => {
    assert.equal(
      resolveGithubDomain({
        dominio_github: 'sdk',
        servico_bitbucket: 'korp.appbuilder',
      }),
      'sdk'
    );
  });
});

describe('versionToReleaseBranch', () => {
  it('mapeia versão para branch release', () => {
    assert.equal(versionToReleaseBranch('2025.1.0.11'), 'release/2025.1.0.x');
    assert.equal(versionToReleaseBranch('2024.2.0.81'), 'release/2024.2.0.x');
  });
});

describe('filterEligibleServices', () => {
  it('ignora serviços fora do escopo korp./viasoft.', () => {
    const filtered = filterEligibleServices([
      {
        servico_bitbucket: 'external.tool-integration',
        tem_tag_github: false,
      },
      {
        servico_bitbucket: 'korp.api.gateway.vendas',
        tem_tag_github: false,
      },
      {
        servico_bitbucket: 'viasoft.vendas.core',
        tem_tag_github: true,
      },
    ]);

    assert.equal(filtered.length, 1);
    assert.equal(filtered[0].servico_bitbucket, 'korp.api.gateway.vendas');
  });
});

describe('runCreateTags integração com mocks', () => {
  const baseReport = {
    servicos_sem_tag_no_github: [
      {
        dominio_github: 'sal',
        servico_bitbucket: 'korp.ok.service',
        categoria: 'versionados',
        tem_tag_github: false,
        referencia_bitbucket: {
          'janela_2025.1.0.x': '2025.1.0.2',
        },
      },
      {
        dominio_github: 'sal',
        servico_bitbucket: 'korp.missing.job',
        categoria: 'nao-versionados',
        tem_tag_github: false,
        referencia_bitbucket: {
          ultima_tag_absoluta: '1.0.2',
        },
      },
      {
        dominio_github: 'sal',
        servico_bitbucket: 'external.tool-integration',
        categoria: 'versionados',
        tem_tag_github: false,
        referencia_bitbucket: {
          'janela_2025.1.0.x': '2025.1.0.1',
        },
      },
    ],
  };

  it('dry-run não chama POST de criação de refs', async () => {
    const githubCalls = [];
    const written = [];

    const output = await runCreateTags({
      inputPath: 'fake-report.json',
      outputPath: 'fake-out.json',
      dryRun: true,
      allServices: true,
      skipEnvLoad: true,
      deps: {
        configs: {
          github: { token: 'x', org: 'viasoftkorp' },
          jenkins: { url: 'https://jenkins.test', user: 'u', token: 't' },
        },
        readFileSync: () => JSON.stringify(baseReport),
        writeFileSync: (p, content) => written.push({ p, content }),
        httpRequest: async (url) => {
          if (url.includes('/job/Korp.Ok.Service')) {
            return { status: 200, body: '{}' };
          }
          if (url.includes('/job/Korp.Missing.Job')) {
            return { status: 404, body: '' };
          }
          return { status: 404, body: '' };
        },
        githubRequest: async (_cfg, urlPath, options = {}) => {
          githubCalls.push({ urlPath, method: options.method || 'GET' });
          if ((options.method || 'GET') === 'POST') {
            return { status: 201, body: '{}' };
          }
          return {
            status: 200,
            body: JSON.stringify({ commit: { sha: 'abc123sha' } }),
          };
        },
      },
    });

    assert.equal(
      githubCalls.some((call) => call.method === 'POST'),
      false,
      'POST de criação não deve ocorrer em dry-run'
    );
    assert.equal(output.dry_run, true);
    assert.equal(output.servicos_ignorados.length, 1);
    assert.equal(output.servicos_ignorados[0].servico_bitbucket, 'korp.missing.job');
    assert.equal(output.servicos_processados.length, 1);
    assert.equal(output.servicos_processados[0].tags_criadas[0].tag, 'korp.ok.service-2025.1.0.3');
    assert.equal(output.servicos_processados[0].dominio_github, 'vendas');
    assert.ok(written.length === 1);
  });

  it('filtra Jenkins 404 vs 200 no relatório final', async () => {
    const output = await runCreateTags({
      inputPath: 'fake-report.json',
      outputPath: 'fake-out.json',
      dryRun: true,
      allServices: true,
      skipEnvLoad: true,
      deps: {
        configs: {
          github: { token: 'x', org: 'viasoftkorp' },
          jenkins: { url: 'https://jenkins.test', user: 'u', token: 't' },
        },
        readFileSync: () => JSON.stringify(baseReport),
        writeFileSync: () => {},
        httpRequest: async (url) => {
          if (url.includes('Korp.Ok.Service')) {
            return { status: 200, body: '{}' };
          }
          return { status: 404, body: '' };
        },
        githubRequest: async () => ({
          status: 200,
          body: JSON.stringify({ commit: { sha: 'sha' } }),
        }),
      },
    });

    assert.equal(output.servicos_ignorados.length, 1);
    assert.equal(output.servicos_ignorados[0].motivo, 'jenkins_404');
    assert.equal(output.servicos_processados.length, 1);
    assert.equal(output.servicos_processados[0].servico_bitbucket, 'korp.ok.service');
  });
});
