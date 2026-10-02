#!/usr/bin/env python3
"""Resumo de tempo de uma execução registrada por pty_run.py.

Uso: timing_report.py LOG [--top N] [--json]
Mostra: tempo total, tempo até o playbook principal, tempo de cada PLAY, número de cabeçalhos TASK,
resultado do PLAY RECAP e as N tarefas mais lentas (tempo entre o cabeçalho da tarefa e o próximo).
"""
import json
import re
import sys
from collections import defaultdict

LINE = re.compile(r"^\[(\d+\.\d+)\] (.*)$")
ANSI = re.compile(r"\x1b\[[0-9;]*m")


def parse(path):
    events = []
    for raw in open(path, errors="replace"):
        m = LINE.match(raw.rstrip("\n"))
        if m:
            events.append((float(m.group(1)), ANSI.sub("", m.group(2))))
    return events


def main():
    path = sys.argv[1]
    top = int(sys.argv[sys.argv.index("--top") + 1]) if "--top" in sys.argv else 15
    ev = parse(path)
    total = ev[-1][0] if ev else 0.0
    plays, tasks, recap = [], [], []
    for i, (t, text) in enumerate(ev):
        if text.startswith("PLAY [") and "RECAP" not in text:
            plays.append([text.split("]")[0][6:], t, None])
        elif text.startswith("TASK ["):
            tasks.append((t, text[6:].split("]")[0]))
        elif text.startswith("localhost") and "ok=" in text:
            recap.append(re.sub(r"\s+", " ", text))
    for i, p in enumerate(plays):
        p[2] = (plays[i + 1][1] if i + 1 < len(plays) else total) - p[1]
    durations = []
    for i, (t, name) in enumerate(tasks):
        end = tasks[i + 1][0] if i + 1 < len(tasks) else total
        durations.append((end - t, name))
    by_name = defaultdict(lambda: [0, 0.0])
    for d, name in durations:
        key = re.sub(r" (de|para|do|da|dos|das) .*$", "", name)
        by_name[key][0] += 1
        by_name[key][1] += d
    rc = [text for _, text in ev if text.startswith("END rc=")]
    report = {
        "log": path,
        "total_s": round(total, 1),
        "rc": rc[-1] if rc else None,
        "plays": [{"name": n, "start_s": round(s, 1), "duration_s": round(d, 1)} for n, s, d in plays],
        "task_headers": len(tasks),
        "recap": recap,
        "slowest_tasks": [{"s": round(d, 2), "task": n} for d, n in sorted(durations, reverse=True)[:top]],
        "by_task_name": [{"task": k, "count": c, "s": round(s, 1)}
                         for k, (c, s) in sorted(by_name.items(), key=lambda kv: -kv[1][1])[:top]],
    }
    if "--json" in sys.argv:
        print(json.dumps(report, indent=1, ensure_ascii=False))
        return
    print("log: %s\ntotal: %.1f s (%s)\ntask headers: %d" % (path, total, report["rc"], len(tasks)))
    for p in report["plays"]:
        print("  PLAY %-35s start %7.1f s  duration %7.1f s" % (p["name"][:35], p["start_s"], p["duration_s"]))
    for r in recap:
        print("  " + r)
    print("slowest tasks:")
    for x in report["slowest_tasks"]:
        print("  %7.2f s  %s" % (x["s"], x["task"][:110]))
    print("by task name (count, total s):")
    for x in report["by_task_name"]:
        print("  %5d %8.1f s  %s" % (x["count"], x["s"], x["task"][:100]))


if __name__ == "__main__":
    main()
