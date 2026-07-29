from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[2]
ROLE = ROOT / "roles/qa_pr_reset"
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

    def test_main_reads_and_validates_overrides_before_deleting_them(self):
        tasks = load_tasks("main.yml")
        read_index = next(
            index
            for index, task in enumerate(tasks)
            if task.get("ansible.builtin.include_tasks") == "read_override.yml"
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

        self.assertLess(read_index, stat_index)
        self.assertLess(stat_index, assert_index)
        self.assertLess(assert_index, delete_index)
        self.assertLess(delete_index, reset_index)

    def test_override_read_builds_unique_base_compose_runs(self):
        tasks = load_tasks("read_override.yml")
        find_tasks = module_tasks(tasks, "ansible.builtin.find")
        slurp_tasks = module_tasks(tasks, "ansible.builtin.slurp")
        run_tasks = [
            task
            for task in module_tasks(tasks, "ansible.builtin.set_fact")
            if "qa_pr_reset_runs" in scalar_text(task)
        ]

        self.assertEqual(len(find_tasks), 1)
        self.assertEqual(len(slurp_tasks), 1)
        self.assertEqual(len(run_tasks), 1)
        self.assertEqual(find_tasks[0]["ansible.builtin.find"]["recurse"], True)
        self.assertEqual(
            find_tasks[0]["ansible.builtin.find"]["patterns"],
            ["*-compose.yml"],
        )
        self.assertIn("/pr-overrides", scalar_text(find_tasks[0]))
        self.assertIn("qa_pr_reset_found_overrides.files", scalar_text(slurp_tasks[0]))
        self.assertIn("qa_pr_reset_override.path", scalar_text(slurp_tasks[0]))

        run_text = scalar_text(run_tasks[0])
        self.assertIn("qa_pr_reset_project_src", run_text)
        self.assertIn("basename", run_text)
        self.assertIn("project_src", run_text)
        self.assertIn("compose_file", run_text)
        self.assertIn("not in qa_pr_reset_runs", scalar_text(run_tasks[0].get("when")))

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
        self.assertFalse(
            module_names(main_tasks) & {"community.docker.docker_compose_v2"}
        )


if __name__ == "__main__":
    unittest.main()
