#!/usr/bin/env python3
"""Compara o estado final de duas execuções (A, B) que partiram do mesmo estado INITIAL.

Uso: compare_dumps.py INITIAL A B [--allow REGEX ...]
Dados escritos pelos próprios containers abaixo dos diretórios de volume criados pelo setup
(profundidade > 2 em /etc/korp/dados-docker) são sempre ignorados. --allow acrescenta caminhos com
não-determinismo conhecido do código original (ex.: segredos gerados aleatoriamente no próprio run);
diferenças ignoradas são contadas e listadas separadamente.

Diferenças só são aceitas em segredos gerados aleatoriamente para KVs/clientes OAuth criados na
própria execução. Segredos que já existiam no INITIAL precisam continuar idênticos em A e B.
Saída: lista de diferenças; código 1 se houver alguma.
"""
import json
import re
import sys

SECRET = re.compile(r"^<secret:[0-9a-f]+>$")


def flat(obj, prefix=""):
    out = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.update(flat(v, "%s/%s" % (prefix, k)))
    elif isinstance(obj, list):
        out[prefix] = json.dumps(obj, sort_keys=True)
    else:
        out[prefix] = obj
    return out


ALWAYS_IGNORED = [r"^/files//etc/korp/dados-docker/[^/]+/[^/]+/.+"]


def main():
    args = sys.argv[1:]
    allow = [args[i + 1] for i, x in enumerate(args) if x == "--allow"]
    paths = [x for i, x in enumerate(args) if x != "--allow" and (i == 0 or args[i - 1] != "--allow")]
    initial, a, b = (json.load(open(p)) for p in paths[:3])
    ignore = [re.compile(r) for r in ALWAYS_IGNORED + allow]
    ignored = []
    problems = []
    init_keys = set(initial.get("consul_kv", {}))
    # 1) segredos pré-existentes preservados
    for key in init_keys:
        for name, dump in (("A", a), ("B", b)):
            before = flat(initial["consul_kv"][key])
            after = flat(dump.get("consul_kv", {}).get(key, {}))
            for path, value in before.items():
                if isinstance(value, str) and SECRET.match(value) and after.get(path) != value:
                    problems.append("%s: segredo pré-existente alterado em %s%s" % (name, key, path))
    init_clients = {r[0] for r in (initial.get("mssql", {}).get("oauth", {}).get("ClientSecrets") or [])}

    def normalize(dump):
        d = json.loads(json.dumps(dump))
        for key, entry in d.get("consul_kv", {}).items():
            if key not in init_keys:
                fl = json.dumps(entry)
                entry_s = re.sub(r"<secret:[0-9a-f]+>", "<secret:new>", fl)
                d["consul_kv"][key] = json.loads(entry_s)
        rows = d.get("mssql", {}).get("oauth", {}).get("ClientSecrets")
        if rows:
            d["mssql"]["oauth"]["ClientSecrets"] = sorted(
                [r[0], r[1], r[2] if r[0] in init_clients else "<secret:new>"] for r in rows)
        return flat(d)

    fa, fb = normalize(a), normalize(b)
    for path in sorted(set(fa) | set(fb)):
        if fa.get(path) != fb.get(path) and any(r.search(path) for r in ignore):
            ignored.append(path)
            continue
        if fa.get(path) != fb.get(path):
            problems.append("diferença em %s\n    A=%s\n    B=%s" % (path, str(fa.get(path))[:300], str(fb.get(path))[:300]))
    for p in problems:
        print(p)
    by_rule = {}
    for path in ignored:
        rule = next(r.pattern for r in ignore if r.search(path))
        by_rule[rule] = by_rule.get(rule, 0) + 1
    for rule, count in by_rule.items():
        print("ignorado (%d): %s" % (count, rule))
    print("RESULTADO: %s (%d diferenças)" % ("IGUAL" if not problems else "DIFERENTE", len(problems)))
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
