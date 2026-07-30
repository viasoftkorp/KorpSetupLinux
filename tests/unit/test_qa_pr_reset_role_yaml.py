from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[2]
ROLE = ROOT / "roles/qa_pr_reset"
PLAYBOOK = ROOT / "pr-reset-playbook.yml"
TASK_FILES = ("main.yml", "read_override.yml", "reset_compose.yml")
CONTROL_KEYS = {
    "name",
    "when",
    "loop",
    "loop_control",
    "register",
    "vars",
    "tags",
    "changed_when",
    "failed_when",
    "delegate_to",
    "become",
}


def load_tasks(filename):
    tasks = yaml.safe_load((ROLE / "tasks" / filename).read_text())
    if not isinstance(tasks, list):
        raise AssertionError(f"{filename} must contain a YAML task list")
    return tasks


def module_tasks(tasks, module):
    return [task for task in tasks if module in task]


def scalar_text(value):
    if isinstance(value, dict):
        return " ".join(
            f"{key} {scalar_text(item)}" for key, item in value.items()
        )
    if isinstance(value, list):
        return " ".join(scalar_text(item) for item in value)
    return str(value)


def module_names(tasks):
    names = set()
    for task in tasks:
        names.update(set(task) - CONTROL_KEYS)
        for block_name in ("block", "rescue", "always"):
            block = task.get(block_name)
            if isinstance(block, list):
                names.update(module_names(block))
    return names


class QaPrResetRoleYamlTests(unittest.TestCase):
    def test_every_required_role_yaml_loads(self):
        for filename in TASK_FILES:
            with self.subTest(filename=filename):
                self.assertIsInstance(load_tasks(filename), list)

    def test_reset_playbook_is_local_privileged_and_role_only(self):
        plays = yaml.safe_load(PLAYBOOK.read_text())
        self.assertEqual(len(plays), 1)
        play = plays[0]

        self.assertEqual(play["hosts"], "127.0.0.1")
        self.assertEqual(play["connection"], "local")
        self.assertIs(play["become"], True)
        self.assertEqual(play["become_user"], "{{ linux_korp.user }}")
        self.assertEqual(
            play["vars"]["ansible_become_password"],
            "{{ linux_korp.password }}",
        )
        self.assertEqual(play["roles"], ["qa_pr_reset"])
        self.assertNotIn("ansible.builtin.import_playbook", play)

        bootstrap_text = (ROOT / "setup.sh").read_text()
        main_text = (ROOT / "main.yml").read_text()
        for filename in ("pr-playbook.yml", "pr-reset-playbook.yml"):
            self.assertNotIn(filename, bootstrap_text)
            self.assertNotIn(filename, main_text)

    def test_main_reads_and_validates_overrides_before_deleting_them(self):
        tasks = load_tasks("main.yml")
        read_index = next(
            index
            for index, task in enumerate(tasks)
            if task.get("ansible.builtin.include_tasks") == "read_override.yml"
        )
        validate_override_index = next(
            (
                index
                for index, task in enumerate(tasks)
                if (
                    "ansible.builtin.set_fact" in task
                    and "qa_pr_index_active_overrides" in scalar_text(task)
                )
            ),
            len(tasks),
        )
        stat_index = next(
            index
            for index, task in enumerate(tasks)
            if "ansible.builtin.stat" in task
        )
        assert_index = next(
            index
            for index, task in enumerate(tasks)
            if "ansible.builtin.assert" in task
            and "qa_pr_reset_base_file.stat.exists" in scalar_text(task)
        )
        compose_check_index = next(
            (
                index
                for index, task in enumerate(tasks)
                if "community.docker.docker_compose_v2" in task
            ),
            len(tasks),
        )
        delete_index = next(
            index
            for index, task in enumerate(tasks)
            if "ansible.builtin.file" in task
        )
        reset_index = next(
            index
            for index, task in enumerate(tasks)
            if task.get("ansible.builtin.include_tasks") == "reset_compose.yml"
        )

        base_assert = tasks[assert_index]["ansible.builtin.assert"]
        base_assert_checks_exists_and_isreg = all(
            expression in base_assert["that"]
            for expression in (
                "qa_pr_reset_base_file.stat.exists | bool",
                "qa_pr_reset_base_file.stat.isreg | bool",
            )
        )
        compose_check_task = (
            tasks[compose_check_index]
            if compose_check_index < len(tasks)
            else {}
        )
        compose_check_module = compose_check_task.get(
            "community.docker.docker_compose_v2", {}
        )

        self.assertLess(read_index, validate_override_index)
        self.assertLess(validate_override_index, stat_index)
        self.assertLess(stat_index, assert_index)
        self.assertLess(assert_index, compose_check_index)
        self.assertLess(compose_check_index, delete_index)
        self.assertLess(delete_index, reset_index)
        self.assertTrue(base_assert_checks_exists_and_isreg)
        self.assertTrue(compose_check_task["check_mode"])
        self.assertEqual(
            compose_check_module["files"],
            ["{{ qa_pr_reset_run.compose_file }}"],
        )

    def test_override_read_builds_unique_base_compose_runs(self):
        tasks = load_tasks("read_override.yml")
        find_tasks = module_tasks(tasks, "ansible.builtin.find")
        slurp_tasks = module_tasks(tasks, "ansible.builtin.slurp")
        override_file_tasks = [
            task
            for task in module_tasks(tasks, "ansible.builtin.set_fact")
            if "qa_pr_reset_override_files" in scalar_text(task)
        ]
        run_tasks = [
            task
            for task in module_tasks(tasks, "ansible.builtin.set_fact")
            if "qa_pr_reset_runs" in scalar_text(task)
        ]

        self.assertEqual(len(find_tasks), 1)
        self.assertEqual(len(slurp_tasks), 1)
        self.assertEqual(len(override_file_tasks), 1)
        self.assertEqual(len(run_tasks), 1)
        self.assertEqual(find_tasks[0]["ansible.builtin.find"]["recurse"], True)
        self.assertNotIn("patterns", find_tasks[0]["ansible.builtin.find"])
        self.assertIn("/pr-overrides", scalar_text(find_tasks[0]))
        self.assertIn(
            "qa_pr_reset_found_overrides.files", scalar_text(slurp_tasks[0])
        )
        self.assertIn("qa_pr_reset_override.path", scalar_text(slurp_tasks[0]))

        override_file_text = scalar_text(override_file_tasks[0])
        self.assertIn("qa_pr_reset_project_src", override_file_text)
        self.assertIn("qa_pr_reset_slurped_override.content", override_file_text)
        self.assertIn("b64decode", override_file_text)
        self.assertIn("from_yaml", override_file_text)

        run_text = scalar_text(run_tasks[0])
        self.assertIn("qa_pr_reset_project_src", run_text)
        self.assertIn("basename", run_text)
        self.assertIn("project_src", run_text)
        self.assertIn("compose_file", run_text)
        self.assertIn(
            "not in qa_pr_reset_runs", scalar_text(run_tasks[0].get("when"))
        )

    def test_main_removes_only_the_two_override_roots(self):
        tasks = load_tasks("main.yml")
        deletions = module_tasks(tasks, "ansible.builtin.file")
        self.assertEqual(len(deletions), 1)
        deletion = deletions[0]
        args = deletion["ansible.builtin.file"]

        self.assertEqual(args["path"], "{{ qa_pr_reset_override_root }}")
        self.assertEqual(args["state"], "absent")
        self.assertIn("qa_pr_reset_override_roots", scalar_text(deletion["loop"]))
        roots_text = scalar_text(tasks)
        self.assertIn("compose_dir_path", roots_text)
        self.assertIn("versioned_compose_dir_path", roots_text)
        self.assertIn("/pr-overrides", roots_text)
        self.assertNotIn("qa_pr_reset_override.path", scalar_text(deletion))

    def test_reset_reapplies_only_each_full_base_compose(self):
        tasks = load_tasks("reset_compose.yml")
        compose_tasks = module_tasks(
            tasks, "community.docker.docker_compose_v2"
        )
        self.assertEqual(len(compose_tasks), 1)
        args = compose_tasks[0]["community.docker.docker_compose_v2"]

        self.assertEqual(
            args["project_src"], "{{ qa_pr_reset_run.project_src }}/"
        )
        self.assertEqual(args["env_files"], ["{{ docker_env_file_path }}"])
        self.assertEqual(args["files"], ["{{ qa_pr_reset_run.compose_file }}"])
        for forbidden in (
            "services",
            "project_name",
            "remove_orphans",
            "pull",
            "recreate",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, args)

    def test_empty_environment_has_no_compose_runs(self):
        main_tasks = load_tasks("main.yml")
        reset_task = next(
            task
            for task in main_tasks
            if task.get("ansible.builtin.include_tasks") == "reset_compose.yml"
        )
        initialization = next(
            task
            for task in main_tasks
            if task.get("ansible.builtin.set_fact", {}).get(
                "qa_pr_reset_runs"
            )
            == []
        )

        self.assertEqual(
            initialization["ansible.builtin.set_fact"]["qa_pr_reset_runs"], []
        )
        self.assertIn("qa_pr_reset_runs", scalar_text(reset_task["loop"]))
        compose_check_tasks = [
            task
            for task in main_tasks
            if "community.docker.docker_compose_v2" in task
        ]
        self.assertEqual(len(compose_check_tasks), 1)
        self.assertIn(
            "qa_pr_reset_runs", scalar_text(compose_check_tasks[0]["loop"])
        )


if __name__ == "__main__":
    unittest.main()
