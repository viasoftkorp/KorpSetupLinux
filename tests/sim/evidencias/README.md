# Evidências das medições de desempenho (2026-10-02)

Geradas pelo ambiente isolado (`tests/sim`) — nenhum dado de servidor real ou de cliente.
Análise e tabelas: `docs/files/guias/desempenho_setup_resultados.rst`.

- `2026-10-02-fase1/`: validação durante o desenvolvimento (ambiente isolado da sessão de trabalho, mesmos scripts).
- `2026-10-02-final/`: medição final com o `tests/sim` do repositório e os commits finais das duas branches.

Por execução:

- `<execução>.timing.json`: tempo total, duração de cada play, número de tarefas, PLAY RECAP, tarefas mais lentas
  (`timing_report.py --json`).
- `<execução>.actions.txt`: ações de migração/limpeza de containers efetivamente executadas (`count_actions.py`).

Por par original × otimizado:

- `<cenário>.compare.txt`: saída de `compare_dumps.py` (comando usado na 1ª linha); `RESULTADO: IGUAL` significa
  o mesmo estado final (Consul, OAuth, bancos, arquivos, containers), exceto os itens listados como `ignorado`.

Os dumps completos e os logs não são versionados (contêm valores gerados pelo ambiente, como senhas de teste).
