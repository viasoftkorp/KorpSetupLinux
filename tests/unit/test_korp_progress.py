import json
import os
import tempfile
import unittest

from _loader import load

cb = load("callback_plugins/korp_progress.py", "korp_progress")


class Role:
    def __init__(self, name, parents=()):
        self._name, self._parents = name, list(parents)

    def get_name(self):
        return self._name


class Task:
    def __init__(self, name, role=None, uuid="t"):
        self._name, self._role, self._uuid = name, role, uuid

    def get_name(self):
        return self._name


class Included:
    def __init__(self, task, var_values):
        self._task, self._vars = task, var_values


class Result:
    def __init__(self, task, res):
        self._task, self._result = task, res


class Play:
    def __init__(self, name):
        self._name = name

    def get_name(self):
        return self._name


class Stats:
    processed = {"127.0.0.1": 1}

    def __init__(self, summary):
        self._summary = summary

    def summarize(self, host):
        return self._summary


def include_batch(callback, task_name, uuid, items):
    task = Task(task_name, uuid=uuid)
    for item in items:
        callback.v2_playbook_on_include(Included(task, {"ansible_loop_var": "app_name", "app_name": item}))


class CallbackTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.dir.name, "status.json")
        with open(self.path, "w") as f:
            json.dump({"run_id": "r1", "log": "/x.log", "runner_pid": 42, "tags": "update"}, f)
        os.environ["KORP_PROGRESS_FILE"] = self.path
        self.cb = cb.CallbackModule()

    def tearDown(self):
        os.environ.pop("KORP_PROGRESS_FILE", None)
        self.dir.cleanup()

    def status(self):
        with open(self.path) as f:
            return json.load(f)

    def test_full_flow_phases_apps_and_error(self):
        c = self.cb
        c.v2_playbook_on_play_start(Play("Setup de provisioning"))
        c.v2_playbook_on_task_start(Task("Instalação", Role("provisioning")), False)
        self.assertEqual(self.status()["phase"], "Provisionamento")
        c.v2_playbook_on_play_start(Play("Setup main"))
        c.v2_playbook_on_task_start(Task("Arquivos", Role("infrastructure")), False)
        include_batch(c, "Instalação de apps padrões", "b1", ["REL01", "FAT02_W"])
        c.v2_playbook_on_task_start(Task("Definição", Role("REL01")), False)
        fat = Role("FAT02_W")
        c.v2_playbook_on_task_start(Task("Kv", Role("solicitacao-faturamento", [fat])), False)
        c.v2_playbook_on_task_start(Task("Cadastro em lote", Role("utils", [fat])), False)
        s = self.cb._state.data
        self.assertEqual((s["apps"]["label"], s["apps"]["index"], s["apps"]["current"]), ("Apps padrão", 1, "FAT02_W"))
        self.assertIsNone(s["apps"]["dependency"])
        self.assertEqual(s["task"], "utils : Cadastro em lote")

        include_batch(c, "Instalação de apps", "b2", ["LOG01_W", "LOG102"])
        log01, log102 = Role("LOG01_W"), Role("LOG102")
        c.v2_playbook_on_task_start(Task("x", log01), False)
        # dependência compartilhada: produto (pais LOG01_W e LOG102) enquanto LOG01_W roda
        produto = Role("produto", [log01, log102])
        c.v2_playbook_on_task_start(Task("y", produto), False)
        self.assertEqual(s["apps"]["current"], "LOG01_W")
        self.assertEqual(s["apps"]["dependency"], "produto")
        # wms só é dependência de LOG102: avança para o próximo app
        c.v2_playbook_on_task_start(Task("z", Role("wms", [log102])), False)
        self.assertEqual((s["apps"]["index"], s["apps"]["current"], s["phase"]), (1, "LOG102", "Aplicativos"))

        failing = Task("Garantia dos KVs", Role("utils", [log102]))
        c.v2_runner_on_failed(Result(failing, {"msg": "esperado"}), ignore_errors=True)
        self.assertIsNone(self.status()["error"])
        c.v2_runner_on_failed(Result(failing, {"msg": "Consul indisponível", "item": "svc-a"}))
        c.v2_playbook_on_task_start(Task("Falha do playbook", Role("finishing")), False)
        c.v2_runner_on_failed(Result(Task("Falha do playbook", Role("finishing")), {"msg": {"msg": "repasse"}}))
        st = self.status()
        self.assertEqual(st["error"]["message"], "Consul indisponível")
        self.assertEqual((st["error"]["role"], st["error"]["item"]), ("utils", "svc-a"))
        self.assertEqual(st["last_failure"]["message"], "repasse")
        # a etapa e o app são os do momento da falha (o tratamento de erro roda depois, em Finalização)
        self.assertEqual((st["error"]["phase"], st["error"]["app"]), ("Aplicativos", "LOG102"))
        self.assertEqual(st["phase"], "Finalização")
        self.assertEqual(st["counts"]["ignored"], 1)
        self.assertEqual(st["counts"]["failed"], 2)

        c.v2_playbook_on_stats(Stats({"ok": 5, "changed": 1, "failures": 1, "unreachable": 0}))
        st = self.status()
        self.assertEqual(st["playbook_result"], "failed")
        # o callback preserva o que o executor gravou antes
        self.assertEqual((st["run_id"], st["log"], st["runner_pid"], st["tags"]), ("r1", "/x.log", 42, "update"))

    def test_app_list_from_loop_item_results(self):
        # include_role não gera v2_playbook_on_include: os itens vêm dos resultados do laço
        loop = Task("Instalação de apps", uuid="u1")
        for app in ("vendas", "LOG102"):
            self.cb.v2_runner_item_on_ok(Result(loop, {"ansible_loop_var": "app_name", "app_name": app}))
        self.cb.v2_runner_item_on_ok(Result(Task("outro laço", uuid="u2"), {"ansible_loop_var": "item", "item": "x"}))
        self.assertEqual(self.status()["apps"]["items"], ["vendas", "LOG102"])
        self.cb.v2_runner_item_on_failed(Result(Task("Criação", Role("utils")),
                                                {"msg": "falhou", "ansible_loop_var": "item", "item": "svc-b"}))
        self.assertEqual((self.status()["error"]["item"], self.status()["error"]["task"]), ("svc-b", "Criação"))

    def test_skipped_task_does_not_replace_current_task(self):
        ran = Task("Cadastro em lote dos serviços de X", Role("utils"))
        self.cb.v2_playbook_on_task_start(ran, False)
        self.cb.v2_runner_on_ok(Result(ran, {}))
        skipped = Task("Cadastro individual de svc", Role("utils"))
        self.cb.v2_playbook_on_task_start(skipped, False)
        self.assertEqual(self.cb._state.data["task"], "utils : Cadastro individual de svc")  # anunciada
        self.cb.v2_runner_on_skipped(Result(skipped, {}))
        self.assertEqual(self.cb._state.data["task"], "utils : Cadastro em lote dos serviços de X")
        running = Task("Inicialização do compose reconciliado", Role("utils"))
        self.cb.v2_playbook_on_task_start(running, False)  # em execução, ainda sem resultado
        self.assertEqual(self.cb._state.data["task"], "utils : Inicialização do compose reconciliado")

    def test_counts_and_warnings(self):
        t = Task("a", Role("infrastructure"))
        self.cb.v2_runner_on_ok(Result(t, {"changed": True, "warnings": ["w1", "w2", "w3", "w4"]}))
        self.cb.v2_runner_on_ok(Result(t, {}))
        self.cb.v2_runner_on_skipped(Result(t, {}))
        self.cb.v2_playbook_on_stats(Stats({"failures": 0, "unreachable": 0}))
        st = self.status()
        self.assertEqual((st["counts"]["changed"], st["counts"]["ok"], st["counts"]["skipped"]), (1, 1, 1))
        self.assertEqual(st["warnings"], {"count": 4, "last": ["w2", "w3", "w4"]})
        self.cb.v2_runner_on_ok(Result(t, {"warnings": [
            "Found orphan containers ([x y]) for this project.",
            "network servicos: network.external.name is deprecated. Please set network.name with external: true",
            "Platform linux on host localhost is using the discovered Python interpreter at /usr/bin/python3.10"]}))
        self.cb.v2_playbook_on_stats(Stats({"failures": 0, "unreachable": 0}))
        self.assertEqual(self.status()["warnings"]["count"], 4)  # avisos esperados não contam
        self.assertEqual(st["playbook_result"], "success")

    def test_no_log_and_loop_item_failures(self):
        self.cb.v2_runner_on_failed(Result(Task("segredo"), {"msg": "senha=123", "_ansible_no_log": True,
                                                             "item": "x"}))
        st = self.status()
        self.assertEqual(st["error"]["message"], "(detalhes ocultos: tarefa com no_log)")
        self.assertIsNone(st["error"]["item"])
        self.assertEqual(cb.error_text({"results": [{"failed": False}, {"failed": True, "stderr": "boom"}]}), "boom")
        self.assertEqual(cb.error_text({"rc": 1}), "falha sem mensagem")

    def test_never_raises_and_disabled_without_file(self):
        for call in (lambda: self.cb.v2_playbook_on_task_start(None, False),
                     lambda: self.cb.v2_playbook_on_include(None),
                     lambda: self.cb.v2_runner_on_failed(None),
                     lambda: self.cb.v2_playbook_on_stats(None)):
            call()
        os.environ.pop("KORP_PROGRESS_FILE")
        silent = cb.CallbackModule()
        silent.v2_playbook_on_play_start(Play("Setup main"))
        self.assertIsNone(silent._path)

    def test_role_ancestors_handles_cycles(self):
        a = Role("a")
        b = Role("b", [a])
        a._parents.append(b)
        self.assertEqual([r.get_name() for r in cb.role_ancestors(b)], ["b", "a"])


if __name__ == "__main__":
    unittest.main()
