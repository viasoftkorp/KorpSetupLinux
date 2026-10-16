#!/usr/bin/env python3
"""Valida as tags de custom_tags do setup.sh contra as tags que existem nos playbooks e roles do repositório.

Uma tag inexistente não é erro para o Ansible: ele roda só as tarefas 'always' e termina com sucesso, sem
fazer o que se pediu (ex.: 'update_versioned' no lugar de 'update-versioned').

Uso: korp_setup_tags.py REPO "tag1,tag2"
Sai com 0 se todas as tags existem e com 3 (e uma mensagem com sugestões) se alguma não existe. Um erro do
próprio validador só gera um aviso (saída 0), para não impedir o setup.
"""
import difflib
import os
import sys

TAGS_ESPECIAIS = {"all", "always", "never", "tagged", "untagged"}
IGNORAR_DIRS = {".git", "tests", "docs", "templates", "files"}
SAIDA_TAG_INEXISTENTE = 3


def _coleta(no, saida):
    if isinstance(no, dict):
        for chave, valor in no.items():
            if chave == "tags":
                valores = valor if isinstance(valor, list) else [valor]
                for v in valores:
                    if isinstance(v, str) and "{{" not in v:
                        saida.update(p.strip() for p in v.split(",") if p.strip())
            else:
                _coleta(valor, saida)
    elif isinstance(no, list):
        for item in no:
            _coleta(item, saida)


def tags_do_repositorio(repo):
    import yaml
    tags = set()
    for raiz, dirs, arquivos in os.walk(repo):
        dirs[:] = [d for d in dirs if d not in IGNORAR_DIRS]
        for nome in arquivos:
            if not nome.endswith((".yml", ".yaml")):
                continue
            try:
                with open(os.path.join(raiz, nome)) as f:
                    _coleta(yaml.safe_load(f), tags)
            except Exception:
                continue
    return tags


def tags_pedidas(texto):
    return [t.strip() for t in texto.split(",") if t.strip()]


def inexistentes(pedidas, existentes):
    validas = existentes | TAGS_ESPECIAIS
    return [t for t in pedidas if t not in validas]


def sugestao(tag, existentes):
    candidata = tag.replace("_", "-").lower()
    if candidata in existentes:
        return candidata
    proximas = difflib.get_close_matches(candidata, sorted(existentes), n=1, cutoff=0.6)
    return proximas[0] if proximas else None


def main(argv):
    if len(argv) != 3:
        print("uso: korp_setup_tags.py REPO 'tag1,tag2'", file=sys.stderr)
        return 0
    try:
        existentes = tags_do_repositorio(argv[1])
        if not existentes:
            raise RuntimeError("nenhuma tag encontrada no repositório")
        erradas = inexistentes(tags_pedidas(argv[2]), existentes)
    except Exception as e:  # o validador não pode impedir o setup
        print(f"Aviso: não foi possível validar custom_tags ({e}); seguindo sem validar.", file=sys.stderr)
        return 0
    if not erradas:
        return 0
    for tag in erradas:
        s = sugestao(tag, existentes)
        print(f"A tag '{tag}' não existe no setup" + (f"; você quis dizer '{s}'?" if s else "."))
    print("Com uma tag inexistente o Ansible só executaria as tarefas 'always' e terminaria sem fazer nada.")
    return SAIDA_TAG_INEXISTENTE


if __name__ == "__main__":
    sys.exit(main(sys.argv))
