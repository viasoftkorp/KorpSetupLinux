#!/usr/bin/env python3
"""Conta ações de migração/limpeza efetivamente executadas (não puladas) num log do setup."""
import re, sys
from collections import Counter
WATCH = ['Parada do container legado', 'Renomeação temporária', 'Inicialização isolada', 'Remoção do backup validado',
         'Recuperação do nome canônico', 'Remoção do container legado substituído', 'Remoção da recriação parcial',
         'Restauração do nome original', 'Reinício do container restaurado', 'Remoção de backup de migração já concluída',
         'Falha controlada']
c = Counter(); cur = None
for raw in open(sys.argv[1], errors='replace'):
    t = re.sub(r'\x1b\[[0-9;]*m', '', re.sub(r'^\[[0-9.]+\] ', '', raw.rstrip('\n')))
    m = re.match(r'TASK \[(?:utils : )?(.*)\]', t)
    if m:
        cur = next((w for w in WATCH if m.group(1).startswith(w)), None); continue
    if cur and re.match(r'(changed|ok|fatal):', t):
        c[(cur, t.split(':')[0])] += 1
for (task, st), n in sorted(c.items()):
    print('%4d %-8s %s' % (n, st, task))
print('total:', sum(c.values()))
