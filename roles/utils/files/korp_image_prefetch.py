#!/usr/bin/env python3
"""Download antecipado de imagens Docker em segundo plano (setup.sh prefetch=true).

  korp_image_prefetch.py start --status ARQUIVO [--parallel N] [--deadline SEGUNDOS] -- IMAGEM...
      Encerra um download antecipado anterior que ainda esteja rodando, inicia um novo em um processo
      desacoplado e retorna logo (imprime {"pid": ...}). Baixa até N imagens por vez, na ordem dada,
      pulando as que já existirem. Uma falha só fica registrada: o compose baixa a imagem na hora.
  korp_image_prefetch.py stop --status ARQUIVO
      Encerra o download em andamento, se houver, e imprime o resumo em JSON. Sempre retorna 0.

O status (JSON, gravado de forma atômica) tem só nomes de imagens, tempos e erros do docker pull.
"""
import argparse
import datetime
import json
import os
import signal
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

MARKER = "korp_image_prefetch"


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def read_status(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def write_status(path, data):
    tmp = "%s.%d.tmp" % (path, os.getpid())
    with open(tmp, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.chmod(tmp, 0o644)
    os.replace(tmp, path)


def is_prefetch_process(pid):
    """True se o PID existe e é um download antecipado (protege contra PID reutilizado)."""
    try:
        with open("/proc/%d/cmdline" % int(pid), "rb") as f:
            cmdline = f.read().decode("utf-8", "replace")
    except (OSError, ValueError, TypeError):
        return False
    return MARKER in cmdline and "\0run\0" in cmdline + "\0"


class Prefetch:
    def __init__(self, status_path, images, parallel, deadline, docker):
        self.status_path = status_path
        self.images = images
        self.parallel = max(1, parallel)
        self.deadline = time.monotonic() + deadline
        self.docker = docker
        # RLock: o tratamento de SIGTERM roda na thread principal e pode chegar enquanto ela grava o status
        self.lock = threading.RLock()
        self.stopping = threading.Event()
        self.children = set()
        self.started = time.monotonic()
        self.status = {
            "pid": os.getpid(), "state": "running", "started_at": now(), "updated_at": now(),
            "parallel": self.parallel, "total": len(images), "pending": len(images),
            "active": [], "pulled": [], "present": [], "failed": [], "seconds": {},
        }

    def save(self):
        self.status["updated_at"] = now()
        self.status["elapsed_s"] = round(time.monotonic() - self.started, 1)
        write_status(self.status_path, self.status)

    def present(self, image):
        return subprocess.run([self.docker, "image", "inspect", "--format", "{{.Id}}", image],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0

    def pull(self, image):
        if self.stopping.is_set():
            return
        with self.lock:
            self.status["pending"] -= 1
            self.status["active"].append(image)
            self.save()
        began = time.monotonic()
        outcome, error = "present", None
        try:
            if not self.present(image):
                proc = subprocess.Popen([self.docker, "pull", "--quiet", image], stdout=subprocess.DEVNULL,
                                        stderr=subprocess.PIPE)
                with self.lock:
                    self.children.add(proc)
                try:
                    _, err = proc.communicate(timeout=max(1.0, self.deadline - time.monotonic()))
                except subprocess.TimeoutExpired:
                    proc.kill()
                    _, err = proc.communicate()
                    self.stopping.set()
                    with self.lock:
                        self.status["state"] = "timeout"
                with self.lock:
                    self.children.discard(proc)
                if proc.returncode == 0:
                    outcome = "pulled"
                elif self.stopping.is_set():
                    outcome = "cancelled"
                else:
                    outcome = "failed"
                    error = (err or b"").decode("utf-8", "replace").strip()[-300:]
        except OSError as exc:
            outcome, error = "failed", str(exc)
        with self.lock:
            self.status["active"].remove(image)
            self.status["seconds"][image] = round(time.monotonic() - began, 1)
            if outcome == "pulled":
                self.status["pulled"].append(image)
            elif outcome == "present":
                self.status["present"].append(image)
            elif outcome == "failed":
                self.status["failed"].append({"image": image, "error": error})
            self.save()

    def stop(self, *_):
        self.stopping.set()
        with self.lock:
            if self.status["state"] == "running":
                self.status["state"] = "cancelled"
            for proc in list(self.children):
                try:
                    proc.terminate()
                except OSError:
                    pass
            self.save()

    def run(self):
        signal.signal(signal.SIGTERM, self.stop)
        signal.signal(signal.SIGINT, self.stop)
        signal.signal(signal.SIGHUP, signal.SIG_IGN)
        with self.lock:
            self.save()
        with ThreadPoolExecutor(max_workers=self.parallel) as pool:
            for image in self.images:
                pool.submit(self.pull, image)
        with self.lock:
            if self.status["state"] == "running":
                self.status["state"] = "done"
            self.status["pending"] = 0 if self.status["state"] == "done" else self.status["pending"]
            self.status["finished_at"] = now()
            self.save()
        return 0


def summary(status, stopped):
    if not status:
        return {"state": "absent"}
    return {
        "state": status.get("state"), "stopped": stopped, "total": status.get("total"),
        "pulled": len(status.get("pulled") or []), "present": len(status.get("present") or []),
        "failed": status.get("failed") or [], "pending": status.get("pending"),
        "active": status.get("active") or [], "elapsed_s": status.get("elapsed_s"),
    }


def stop(status_path, wait=15.0):
    status = read_status(status_path)
    stopped = False
    pid = (status or {}).get("pid")
    if status and status.get("state") == "running" and pid and is_prefetch_process(pid):
        stopped = True
        try:
            os.kill(int(pid), signal.SIGTERM)
        except OSError:
            pass
        limit = time.monotonic() + wait
        while time.monotonic() < limit and is_prefetch_process(pid):
            time.sleep(0.2)
        if is_prefetch_process(pid):
            try:
                os.killpg(int(pid), signal.SIGKILL)
            except OSError:
                pass
        status = read_status(status_path) or status
    return summary(status, stopped)


def start(args):
    stop(args.status)
    os.makedirs(os.path.dirname(os.path.abspath(args.status)), exist_ok=True)
    argv = [sys.executable, os.path.abspath(__file__), "run", "--status", os.path.abspath(args.status),
            "--parallel", str(args.parallel), "--deadline", str(args.deadline), "--docker", args.docker,
            "--"] + args.images
    read_fd, write_fd = os.pipe()
    child = os.fork()
    if child > 0:
        os.close(write_fd)
        with os.fdopen(read_fd) as r:
            pid = r.read().strip()
        os.waitpid(child, 0)
        print(json.dumps({"pid": int(pid) if pid.isdigit() else None, "images": len(args.images)}))
        return 0 if pid.isdigit() else 1
    # filho: nova sessão e segundo fork, para não ficar preso ao processo do Ansible
    try:
        os.close(read_fd)
        os.setsid()
        if os.fork() > 0:
            os._exit(0)
        # grupo de processos próprio (com os docker pull filhos): o stop pode encerrar todos de uma vez
        os.setpgid(0, 0)
        devnull = os.open(os.devnull, os.O_RDWR)
        for fd in (0, 1, 2):
            os.dup2(devnull, fd)
        os.chdir("/")
        os.write(write_fd, str(os.getpid()).encode())
        os.close(write_fd)
        os.execv(sys.executable, argv)
    finally:
        os._exit(1)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Download antecipado de imagens Docker")
    parser.add_argument("command", choices=["start", "stop", "run"])
    parser.add_argument("--status", required=True)
    parser.add_argument("--parallel", type=int, default=3)
    parser.add_argument("--deadline", type=float, default=6 * 3600)
    parser.add_argument("--docker", default="docker")
    argv = list(sys.argv[1:] if argv is None else argv)
    images = argv[argv.index("--") + 1:] if "--" in argv else []
    args = parser.parse_args(argv[:argv.index("--")] if "--" in argv else argv)
    args.images = images
    if args.command == "stop":
        print(json.dumps(stop(args.status), ensure_ascii=False))
        return 0
    if args.command == "start":
        return start(args)
    return Prefetch(args.status, args.images, args.parallel, args.deadline, args.docker).run()


if __name__ == "__main__":
    sys.exit(main())
