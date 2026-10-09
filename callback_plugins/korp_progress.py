"""Callback de notificação que grava o andamento do setup num arquivo de status (JSON).

Usado pelo modo de acompanhamento (`setup.sh progress=true`): o playbook roda em segundo plano e
`korp-setup-acompanhar` lê este arquivo. Não altera a saída padrão do Ansible (o log continua igual).

Habilitação (feita por scripts/acompanhamento/korp_setup_runner.py):
  ANSIBLE_CALLBACKS_ENABLED=korp_progress
  KORP_PROGRESS_FILE=<arquivo de status>   (sem esta variável o callback não faz nada)

Regra principal: este callback nunca pode interromper o setup. Toda falha interna é ignorada.
"""
import json
import os
import time
from datetime import datetime, timezone

from ansible.plugins.callback import CallbackBase

DOCUMENTATION = """
    name: korp_progress
    type: notification
    short_description: grava o andamento do setup Korp num arquivo de status
    description:
      - Arquivo indicado por KORP_PROGRESS_FILE, lido por korp-setup-acompanhar.
    requirements:
      - habilitar via ANSIBLE_CALLBACKS_ENABLED=korp_progress
"""

APP_LOOP_VAR = "app_name"
WRITE_INTERVAL = 0.5
MAX_TEXT = 1500
ROLE_PHASES = {
    "provisioning": "Provisionamento",
    "infrastructure": "Infraestrutura",
    "infrastructure-web": "Infraestrutura web",
    "infrastructure-desktop": "Infraestrutura desktop",
    "finishing": "Finalização",
}
PLAY_PHASES = {"Setup de provisioning": "Provisionamento"}
# avisos esperados em toda execução (vários arquivos de compose no mesmo projeto): não aparecem na tela
EXPECTED_WARNINGS = ("Found orphan containers", "network.external.name is deprecated",
                     "is using the discovered Python interpreter")


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def tail(text, limit=MAX_TEXT):
    text = str(text).strip()
    return text if len(text) <= limit else "..." + text[-limit:]


def error_text(res):
    """Mensagem curta de uma falha do Ansible, sem expor saídas marcadas com no_log."""
    if not isinstance(res, dict):
        return tail(res)
    if res.get("_ansible_no_log") or res.get("censored"):
        return "(detalhes ocultos: tarefa com no_log)"
    msg = res.get("msg")
    if isinstance(msg, dict):  # tarefa "Falha do playbook" repassa o resultado original
        return error_text(msg)
    parts = [str(msg)] if msg else []
    for key in ("stderr", "module_stderr"):
        if res.get(key):
            parts.append(tail(res[key], 600))
    if not parts and res.get("stdout"):
        parts.append(tail(res["stdout"], 600))
    if not parts and res.get("exception"):
        parts.append(str(res["exception"]).strip().splitlines()[-1])
    if not parts and isinstance(res.get("results"), list):
        failed = [r for r in res["results"] if isinstance(r, dict) and r.get("failed")]
        if failed:
            return error_text(failed[0])
    return tail(" | ".join(parts) or "falha sem mensagem")


def role_name(role):
    try:
        return role.get_name() if role is not None else ""
    except Exception:
        return ""


def task_label(task):
    """Nome da tarefa sem o prefixo do papel (Task.get_name() já devolve "papel : nome")."""
    if task is None:
        return ""
    name = getattr(task, "name", None)
    return str(name if name else task.get_name()).strip()


def role_ancestors(role, limit=50):
    """O próprio papel e seus pais (dependências meta e include_role guardam o papel de origem)."""
    seen, queue, out = set(), [role], []
    while queue and len(out) < limit:
        r = queue.pop(0)
        if r is None or id(r) in seen:
            continue
        seen.add(id(r))
        out.append(r)
        queue.extend(getattr(r, "_parents", None) or [])
    return out


class ProgressState:
    """Estado do andamento, independente do Ansible (testável sem executar playbooks)."""

    def __init__(self, base=None):
        self.data = dict(base or {})
        self.data.setdefault("state", "running")
        self.data.setdefault("started_at", now_iso())
        self.data["phase"] = self.data.get("phase") or "Preparação"
        self.data["counts"] = {"tasks": 0, "ok": 0, "changed": 0, "skipped": 0, "failed": 0, "ignored": 0}
        self.data["apps"] = None
        self.data["warnings"] = {"count": 0, "last": []}
        self.data["error"] = None
        self._batch_task = None
        self._batch_label = None
        self._last_ran = None

    # eventos -----------------------------------------------------------------
    def play(self, name):
        self.data["play"] = name
        if name in PLAY_PHASES:
            self.data["phase"] = PLAY_PHASES[name]

    def include(self, task_uuid, task_name, loop_var, item):
        if loop_var != APP_LOOP_VAR or not item:
            return
        if task_uuid != self._batch_task:
            self._batch_task = task_uuid
            self._batch_label = "Apps padrão" if "padr" in (task_name or "").lower() else "Aplicativos"
            self.data["apps"] = {"label": self._batch_label, "items": [], "index": -1, "current": None,
                                 "dependency": None}
        items = self.data["apps"]["items"]
        if item not in items:
            items.append(item)

    def task(self, role, names, task_name):
        """role: nome do papel da tarefa; names: nomes do papel e dos ancestrais (mais próximo primeiro)."""
        c = self.data["counts"]
        c["tasks"] += 1
        self.data["task"] = f"{role} : {task_name}" if role else task_name
        if role in ROLE_PHASES:
            self.data["phase"] = ROLE_PHASES[role]
        apps = self.data.get("apps")
        if not apps:
            return
        items = apps["items"]
        planned = [n for n in names if n in items]
        if not planned:
            return
        # papel compartilhado por vários apps: o primeiro app ainda não concluído
        pos = [items.index(n) for n in planned]
        start = max(apps["index"], 0)
        later = [p for p in pos if p >= start]
        idx = min(later) if later else max(pos)
        if idx > apps["index"]:
            apps["index"] = idx
        apps["current"] = items[idx]
        apps["dependency"] = role if role and role != items[idx] and role != "utils" else None
        self.data["phase"] = apps["label"]

    def result(self, status, ignore_errors=False, label=None):
        # o Ansible anuncia toda tarefa antes de avaliar o "when": uma tarefa pulada (ex.: "Cadastro
        # individual", do caminho original) não substitui na tela a última que rodou de verdade
        if label:
            if status == "skipped":
                if self._last_ran:
                    self.data["task"] = self._last_ran
            else:
                self._last_ran = label
        c = self.data["counts"]
        if status == "failed" and ignore_errors:
            c["ignored"] += 1
        elif status in c:
            c[status] += 1

    def warning(self, texts):
        w = self.data["warnings"]
        for t in texts:
            if any(e in str(t) for e in EXPECTED_WARNINGS):
                continue
            w["count"] += 1
            w["last"] = (w["last"] + [tail(t, 300)])[-3:]

    def failure(self, role, task_name, item, text):
        apps = self.data.get("apps") or {}
        err = {"role": role, "task": task_name, "item": item, "message": text, "at": now_iso(),
               # onde o setup estava na falha (depois o tratamento de erro muda a etapa para Finalização)
               "phase": self.data.get("phase"), "app": apps.get("current"), "dependency": apps.get("dependency")}
        if self.data["error"] is None:
            self.data["error"] = err  # a primeira falha é a causa; as seguintes são o tratamento de erro
        else:
            self.data["last_failure"] = err

    def stats(self, summary):
        self.data["summary"] = summary
        self.data["phase_final"] = self.data.get("phase")
        failed = (summary or {}).get("failures", 0) or (summary or {}).get("unreachable", 0)
        self.data["playbook_result"] = "failed" if failed else "success"


class CallbackModule(CallbackBase):
    CALLBACK_VERSION = 2.0
    CALLBACK_TYPE = "notification"
    CALLBACK_NAME = "korp_progress"
    CALLBACK_NEEDS_ENABLED = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._path = os.environ.get("KORP_PROGRESS_FILE")
        self._last_write = 0.0
        base = None
        if self._path:
            try:
                with open(self._path) as f:
                    base = json.load(f)
            except Exception:
                base = None
        self._state = ProgressState(base)
        self._state.data["ansible_pid"] = os.getpid()

    # escrita ---------------------------------------------------------------------
    def _write(self, force=False):
        if not self._path:
            return
        now = time.monotonic()
        if not force and now - self._last_write < WRITE_INTERVAL:
            return
        self._last_write = now
        try:
            self._state.data["updated_at"] = now_iso()
            tmp = f"{self._path}.{os.getpid()}.tmp"
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as f:
                json.dump(self._state.data, f, ensure_ascii=False)
            os.replace(tmp, self._path)
        except Exception:
            pass

    def _safe(self, fn, *args, force=False):
        if not self._path:
            return
        try:
            fn(*args)
        except Exception:
            pass
        self._write(force=force)

    # eventos do Ansible -----------------------------------------------------------
    def v2_playbook_on_play_start(self, play):
        self._safe(lambda: self._state.play(play.get_name().strip()), force=True)

    def _loop_item(self, task, values):
        """Laços com loop_var app_name (include_role de apps/install.yml) definem a lista de apps.

        O Ansible não chama v2_playbook_on_include para include_role; os itens chegam nos resultados
        do próprio laço, antes de as tarefas de cada app rodarem.
        """
        values = values or {}
        loop_var = values.get("ansible_loop_var", "item")
        self._state.include(getattr(task, "_uuid", None), task_label(task), loop_var, values.get(loop_var))

    def v2_playbook_on_include(self, included_file):
        self._safe(lambda: self._loop_item(getattr(included_file, "_task", None),
                                           getattr(included_file, "_vars", None)), force=True)

    def v2_runner_item_on_ok(self, result):
        self._safe(lambda: self._loop_item(result._task, result._result), force=True)

    def v2_runner_item_on_failed(self, result):
        def go():
            res = result._result or {}
            if not res.get("_ansible_no_log") and res.get("ansible_loop_var"):
                res = dict(res, item=res.get(res["ansible_loop_var"]))
            task = result._task
            self._state.failure(role_name(getattr(task, "_role", None)), task_label(task),
                                None if res.get("item") is None or res.get("_ansible_no_log") else tail(res["item"], 200),
                                error_text(res))
        self._safe(go, force=True)

    def v2_playbook_on_task_start(self, task, is_conditional):
        def go():
            role = getattr(task, "_role", None)
            names = [role_name(r) for r in role_ancestors(role)]
            self._state.task(role_name(role), names, task_label(task))
        self._safe(go)

    def v2_playbook_on_handler_task_start(self, task):
        self.v2_playbook_on_task_start(task, False)

    def _result(self, result, status, ignore_errors=False):
        def go():
            res = getattr(result, "_result", {}) or {}
            task = getattr(result, "_task", None)
            role = role_name(getattr(task, "_role", None))
            label = f"{role} : {task_label(task)}" if role else task_label(task)
            self._state.result(status, ignore_errors, label)
            if res.get("warnings"):
                self._state.warning(res["warnings"])
            if status == "failed" and not ignore_errors:
                item = res.get("item") if not res.get("_ansible_no_log") else None
                self._state.failure(role, task_label(task), None if item is None else tail(item, 200),
                                    error_text(res))
        self._safe(go, force=(status == "failed"))

    def v2_runner_on_ok(self, result):
        self._result(result, "changed" if (getattr(result, "_result", {}) or {}).get("changed") else "ok")

    def v2_runner_on_skipped(self, result):
        self._result(result, "skipped")

    def v2_runner_on_failed(self, result, ignore_errors=False):
        self._result(result, "failed", ignore_errors)

    def v2_runner_on_unreachable(self, result):
        self._result(result, "failed")

    def v2_playbook_on_stats(self, stats):
        def go():
            hosts = sorted(stats.processed.keys())
            summary = stats.summarize(hosts[0]) if hosts else {}
            self._state.stats(summary)
        self._safe(go, force=True)
