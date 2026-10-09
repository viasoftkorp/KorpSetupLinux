#!/usr/bin/env python3
"""Executa o playbook principal do setup em segundo plano (modo `setup.sh progress=true`).

Iniciado pelo setup.sh com systemd-run (ou setsid, sem systemd), roda o ansible-playbook com o callback
korp_progress, grava a saída completa no mesmo log de sempre e fecha o arquivo de status com o resultado.

Uso:
  korp_setup_runner.py --status ARQ --log ARQ --run-id ID [--history ARQ] [--env-file ARQ]
                       [--callback-dir DIR] [--meta chave=valor ...] [--cleanup CAMINHO ...] -- comando...
"""
import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_json(path):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return {}


def write_json(path, data):
    tmp = f"{path}.{os.getpid()}.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, path)


def read_env_file(path):
    env = {}
    if not path or not os.path.exists(path):
        return env
    with open(path) as f:
        for line in f:
            line = line.rstrip("\n")
            if "=" in line and not line.startswith("#"):
                key, value = line.split("=", 1)
                env[key] = value
    return env


def last_run(history_path, tags):
    """Última execução bem-sucedida com as mesmas tags (para estimar o tempo restante)."""
    best = None
    try:
        with open(history_path) as f:
            for line in f:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if r.get("tags") == tags and r.get("rc") == 0:
                    best = r
    except OSError:
        pass
    return best and {"duration_s": best.get("duration_s"), "finished_at": best.get("finished_at")}


def log_tail(path, lines=20):
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - 16384))
            text = f.read().decode("utf-8", "replace")
        return "\n".join(text.splitlines()[-lines:])
    except OSError:
        return ""


def build_env(base, extra, callback_dir, status_path):
    env = dict(base)
    for key in [k for k in env if k.startswith("LC_")]:
        del env[key]
    env.update({"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "PYTHONUNBUFFERED": "1"})
    env.update(extra)
    enabled = [c for c in env.get("ANSIBLE_CALLBACKS_ENABLED", "").split(",") if c]
    env["ANSIBLE_CALLBACKS_ENABLED"] = ",".join(enabled + ([] if "korp_progress" in enabled else ["korp_progress"]))
    if callback_dir:
        paths = [p for p in env.get("ANSIBLE_CALLBACK_PLUGINS", "").split(":") if p]
        env["ANSIBLE_CALLBACK_PLUGINS"] = ":".join([callback_dir] + paths)
    env["KORP_PROGRESS_FILE"] = status_path
    return env


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--status", required=True)
    p.add_argument("--log", required=True)
    p.add_argument("--run-id", required=True)
    p.add_argument("--history")
    p.add_argument("--env-file")
    p.add_argument("--callback-dir")
    p.add_argument("--meta", action="append", default=[])
    p.add_argument("--cleanup", action="append", default=[])
    p.add_argument("command", nargs=argparse.REMAINDER)
    a = p.parse_args(argv)
    command = a.command[1:] if a.command[:1] == ["--"] else a.command
    if not command:
        p.error("comando ausente depois de --")

    meta = dict(m.split("=", 1) for m in a.meta if "=" in m)
    started = time.time()
    status = {"run_id": a.run_id, "state": "running", "started_at": now_iso(), "runner_pid": os.getpid(),
              "log": a.log, **meta}
    if a.history:
        status["last_run"] = last_run(a.history, meta.get("tags"))
    write_json(a.status, status)

    env = build_env(os.environ, read_env_file(a.env_file), a.callback_dir, a.status)
    rc, interrupted = 1, False
    child = None

    def stop(signum, _frame):
        nonlocal interrupted
        interrupted = True
        if child and child.poll() is None:
            child.send_signal(signum)
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGHUP, signal.SIG_IGN)

    try:
        with open(a.log, "ab", buffering=0) as log:
            child = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                     env=env)
            rc = child.wait()
    except OSError as e:
        with open(a.log, "a") as log:
            log.write(f"\n[korp_setup_runner] falha ao iniciar o playbook: {e}\n")
        rc = 127

    final = read_json(a.status) or status
    duration = int(time.time() - started)
    final.update({"rc": rc, "finished_at": now_iso(), "duration_s": duration,
                  "state": "success" if rc == 0 else "failed"})
    if interrupted:
        final["interrupted"] = True
    if rc != 0 and not final.get("error"):
        final["error"] = {"role": "", "task": "", "item": None, "at": final["finished_at"],
                          "message": "o playbook terminou com erro antes de registrar a tarefa que falhou; "
                                     "final do log:\n" + log_tail(a.log)}
    write_json(a.status, final)

    if a.history:
        try:
            with open(a.history, "a") as h:
                h.write(json.dumps({"run_id": a.run_id, "tags": meta.get("tags"), "branch": meta.get("branch"),
                                    "started_at": status["started_at"], "finished_at": final["finished_at"],
                                    "duration_s": duration, "rc": rc}) + "\n")
        except OSError:
            pass

    for path in a.cleanup:
        try:
            if os.path.isdir(path) and not os.path.islink(path):
                shutil.rmtree(path)
            elif os.path.lexists(path):
                os.remove(path)
        except OSError:
            pass
    return rc


if __name__ == "__main__":
    sys.exit(main())
