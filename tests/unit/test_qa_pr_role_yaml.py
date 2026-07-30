from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[2]
ROLE = ROOT / "roles/qa_pr_apply"
PLAYBOOK = ROOT / "pr-playbook.yml"
ANSIBLE_LINT_CONFIG = ROOT / ".ansible-lint"
DEFAULT_FILE = ROLE / "defaults/main.yml"
OPERATIONS_GUIDE = ROOT / "docs/ambiente-qualidade-prs.md"
TASK_FILES = (
    "main.yml",
    "load_pr.yml",
    "load_report.yml",
    "read_compose.yml",
    "read_override.yml",
    "prompt_conflict.yml",
    "write_override.yml",
    "apply_compose.yml",
)
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


def load_yaml(path):
    return yaml.safe_load(path.read_text())


def load_tasks(filename):
    tasks = load_yaml(ROLE / "tasks" / filename)
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


class QaPrRoleYamlTests(unittest.TestCase):
    def test_every_required_role_yaml_loads(self):
        self.assertIsInstance(load_yaml(DEFAULT_FILE), dict)
        for filename in TASK_FILES:
            with self.subTest(filename=filename):
                self.assertIsInstance(load_tasks(filename), list)

    def test_apply_playbook_is_local_privileged_and_role_only(self):
        plays = load_yaml(PLAYBOOK)
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
        self.assertEqual(play["roles"], ["qa_pr_apply"])
        self.assertNotIn("ansible.builtin.import_playbook", play)

        bootstrap_text = (ROOT / "setup.sh").read_text()
        main_text = (ROOT / "main.yml").read_text()
        for filename in ("pr-playbook.yml", "pr-reset-playbook.yml"):
            self.assertNotIn(filename, bootstrap_text)
            self.assertNotIn(filename, main_text)

    def test_ansible_lint_has_only_the_qa_pr_exception_and_context(self):
        config = load_yaml(ANSIBLE_LINT_CONFIG)

        self.assertEqual(
            config["skip_list"],
            ["var-naming[no-role-prefix]"],
        )
        self.assertEqual(
            config["extra_vars"],
            {
                "compose_dir_path": "/tmp/qa-pr-composes",
                "versioned_compose_dir_path": "/tmp/qa-pr-versioned-composes",
            },
        )

    def test_defaults_expose_minio_and_conflict_interfaces(self):
        defaults = load_yaml(DEFAULT_FILE)
        self.assertEqual(
            defaults["qa_pr_minio_api"],
            "https://minio-interno-api.korp.com.br",
        )
        self.assertEqual(defaults["qa_pr_minio_bucket"], "qa-prs")
        self.assertEqual(defaults["pr_conflict_policy"], "ask")
        self.assertEqual(defaults["qa_pr_reports"], [])
        self.assertEqual(defaults["qa_pr_compose_files"], [])
        self.assertEqual(defaults["qa_pr_override_files"], [])
        self.assertEqual(defaults["qa_pr_conflict_decisions"], {})

    def test_main_normalizes_and_validates_inputs_before_external_work(self):
        tasks = load_tasks("main.yml")
        normalize_index = next(
            index
            for index, task in enumerate(tasks)
            if "qa_pr_normalize_links" in scalar_text(
                task.get("ansible.builtin.set_fact", {})
            )
        )
        policy_index = next(
            index
            for index, task in enumerate(tasks)
            if "ansible.builtin.assert" in task
            and "pr_conflict_policy" in scalar_text(task)
        )
        load_index = next(
            index
            for index, task in enumerate(tasks)
            if task.get("ansible.builtin.include_tasks") == "load_pr.yml"
        )
        first_direct_effect = min(
            (
                index
                for index, task in enumerate(tasks)
                if set(task)
                & {
                    "ansible.builtin.uri",
                    "ansible.builtin.file",
                    "ansible.builtin.copy",
                    "community.docker.docker_compose_v2",
                }
            ),
            default=len(tasks),
        )
        self.assertEqual(normalize_index, 0)
        self.assertLess(normalize_index, policy_index)
        self.assertLess(policy_index, load_index)
        self.assertLess(normalize_index, first_direct_effect)

    def test_minio_reads_are_anonymous_https_gets_with_tls_validation(self):
        load_pr_tasks = load_tasks("load_pr.yml")
        load_report_tasks = load_tasks("load_report.yml")
        listing = module_tasks(load_pr_tasks, "ansible.builtin.uri")
        objects = module_tasks(load_report_tasks, "ansible.builtin.uri")
        self.assertEqual(len(listing), 1)
        self.assertEqual(len(objects), 1)

        listing_args = listing[0]["ansible.builtin.uri"]
        object_args = objects[0]["ansible.builtin.uri"]
        for args in (listing_args, object_args):
            self.assertEqual(args["method"], "GET")
            self.assertIs(args["return_content"], True)
            self.assertIs(args["validate_certs"], True)
            self.assertTrue(str(args["url"]).startswith("{{ qa_pr_minio_api }}"))
            self.assertNotIn("headers", args)
            self.assertNotIn("url_username", args)
            self.assertNotIn("url_password", args)

        self.assertIn("/?list-type=2&prefix=", listing_args["url"])
        self.assertIn("qa_pr_minio_prefix", listing_args["url"])
        self.assertIn("qa_pr_report_key", object_args["url"])
        self.assertIn("qa_pr_parse_minio_listing", scalar_text(load_pr_tasks))
        self.assertIn(
            "qa_pr_report_key | urlencode", object_args["url"]
        )
        self.assertIn("qa_pr_load_report", scalar_text(load_report_tasks))
        self.assertIn("qa_pr_reports", scalar_text(load_report_tasks))

        report_includes = module_tasks(
            load_pr_tasks, "ansible.builtin.include_tasks"
        )
        self.assertEqual(
            [task["ansible.builtin.include_tasks"] for task in report_includes],
            ["load_report.yml"],
        )
        self.assertIn("qa_pr_minio_keys", scalar_text(report_includes[0]))
        missing_report_asserts = module_tasks(
            load_pr_tasks, "ansible.builtin.assert"
        )
        self.assertTrue(missing_report_asserts)
        self.assertIn("JSON", scalar_text(missing_report_asserts))

    def test_base_and_override_discovery_stay_separate(self):
        compose_tasks = load_tasks("read_compose.yml")
        override_tasks = load_tasks("read_override.yml")

        compose_find = module_tasks(compose_tasks, "ansible.builtin.find")
        override_find = module_tasks(override_tasks, "ansible.builtin.find")
        self.assertEqual(len(compose_find), 1)
        self.assertEqual(len(override_find), 1)
        self.assertIs(
            compose_find[0]["ansible.builtin.find"]["recurse"], False
        )
        self.assertEqual(
            compose_find[0]["ansible.builtin.find"]["patterns"],
            ["*-compose.yml"],
        )
        self.assertIs(
            override_find[0]["ansible.builtin.find"]["recurse"], True
        )
        self.assertIn(
            "/pr-overrides",
            str(override_find[0]["ansible.builtin.find"]["paths"]),
        )

        self.assertTrue(
            module_tasks(compose_tasks, "ansible.builtin.slurp")
        )
        self.assertTrue(
            module_tasks(override_tasks, "ansible.builtin.slurp")
        )
        self.assertIn("b64decode", scalar_text(compose_tasks))
        self.assertIn("from_yaml", scalar_text(compose_tasks))
        self.assertIn("qa_pr_compose_files", scalar_text(compose_tasks))
        self.assertNotIn("qa_pr_override_files", scalar_text(compose_tasks))
        self.assertIn("qa_pr_compose_file.path", scalar_text(compose_tasks))
        self.assertNotIn(
            "qa_pr_slurped_compose.item", scalar_text(compose_tasks)
        )
        self.assertIn("b64decode", scalar_text(override_tasks))
        self.assertIn("from_yaml", scalar_text(override_tasks))
        self.assertIn("qa_pr_override_files", scalar_text(override_tasks))
        self.assertNotIn("qa_pr_compose_files", scalar_text(override_tasks))
        self.assertIn("qa_pr_override_file.path", scalar_text(override_tasks))
        override_accumulator = next(
            task
            for task in module_tasks(
                override_tasks, "ansible.builtin.set_fact"
            )
            if "qa_pr_override_files" in scalar_text(task)
        )
        self.assertIn(
            "qa_pr_project_src",
            scalar_text(override_accumulator["ansible.builtin.set_fact"]),
        )
        self.assertNotIn(
            "qa_pr_slurped_override.item", scalar_text(override_tasks)
        )

        main_text = scalar_text(load_tasks("main.yml"))
        self.assertIn("compose_dir_path", main_text)
        self.assertIn("versioned_compose_dir_path", main_text)
        self.assertIn("regex_replace", main_text)
        self.assertIn("qa_pr_build_targets", main_text)
        self.assertIn("qa_pr_compose_files", main_text)
        self.assertIn("qa_pr_index_active_overrides", main_text)
        self.assertIn("qa_pr_override_files", main_text)

    def test_ask_resolves_all_decisions_before_any_mutation(self):
        tasks = load_tasks("main.yml")
        prompt_index, prompt_task = next(
            (index, task)
            for index, task in enumerate(tasks)
            if task.get("ansible.builtin.include_tasks")
            == "prompt_conflict.yml"
        )
        plan_index = next(
            index
            for index, task in enumerate(tasks)
            if "qa_pr_resolve_application" in scalar_text(
                task.get("ansible.builtin.set_fact", {})
            )
        )
        gate_index = next(
            index
            for index, task in enumerate(tasks)
            if "ansible.builtin.assert" in task
            and "may_mutate" in scalar_text(task)
        )
        mutation_indices = [
            index
            for index, task in enumerate(tasks)
            if (
                "ansible.builtin.file" in task
                or task.get("ansible.builtin.include_tasks")
                in {"write_override.yml", "apply_compose.yml"}
            )
        ]
        self.assertIn("qa_pr_targets", scalar_text(prompt_task["loop"]))
        self.assertIn("pr_conflict_policy", scalar_text(prompt_task["when"]))
        self.assertLess(prompt_index, plan_index)
        self.assertLess(plan_index, gate_index)
        self.assertTrue(mutation_indices)
        self.assertLess(gate_index, min(mutation_indices))

    def test_prompt_recalculates_and_defaults_nonaccepted_input_to_abort(self):
        tasks = load_tasks("prompt_conflict.yml")
        self.assertIn("qa_pr_detect_conflicts", scalar_text(tasks))
        pauses = module_tasks(tasks, "ansible.builtin.pause")
        self.assertEqual(len(pauses), 1)
        prompt_text = scalar_text(pauses[0])
        for field in ("current", "incoming", "pr_key", "service", "compose"):
            self.assertIn(field, prompt_text)
        self.assertIn("qa_pr_prompt_target", scalar_text(pauses[0]["when"]))

        decisions = [
            task
            for task in module_tasks(tasks, "ansible.builtin.set_fact")
            if "qa_pr_conflict_decisions"
            in task["ansible.builtin.set_fact"]
        ]
        self.assertEqual(len(decisions), 1)
        decision_text = scalar_text(decisions[0])
        self.assertIn("user_input", decision_text)
        self.assertIn("default('abort')", decision_text)
        self.assertIn("lower", decision_text)
        self.assertIn("trim", decision_text)
        self.assertIn("replace", decision_text)
        self.assertIn("keep", decision_text)
        self.assertIn("abort", decision_text)
        self.assertFalse(
            module_names(tasks)
            & {
                "ansible.builtin.file",
                "ansible.builtin.copy",
                "community.docker.docker_compose_v2",
            }
        )

    def test_override_write_uses_only_the_pure_execution_plan(self):
        tasks = load_tasks("write_override.yml")
        directories = module_tasks(tasks, "ansible.builtin.file")
        copies = module_tasks(tasks, "ansible.builtin.copy")
        self.assertEqual(len(directories), 1)
        self.assertEqual(len(copies), 1)
        directory = directories[0]["ansible.builtin.file"]
        self.assertEqual(directory["state"], "directory")
        self.assertEqual(str(directory["mode"]), "0755")
        self.assertIn("dirname", str(directory["path"]))
        copy_args = copies[0]["ansible.builtin.copy"]
        self.assertIn("qa_pr_override_write.path", str(copy_args["dest"]))
        self.assertIn(
            "qa_pr_override_write.content", str(copy_args["content"])
        )
        self.assertIn("to_nice_yaml", str(copy_args["content"]))

    def test_compose_run_is_targeted_and_uses_expected_files(self):
        tasks = load_tasks("apply_compose.yml")
        compose_tasks = module_tasks(
            tasks, "community.docker.docker_compose_v2"
        )
        self.assertEqual(len(compose_tasks), 1)
        args = compose_tasks[0]["community.docker.docker_compose_v2"]
        self.assertEqual(
            args["project_src"], "{{ qa_pr_compose_run.project_src }}/"
        )
        self.assertEqual(args["env_files"], ["{{ docker_env_file_path }}"])
        self.assertEqual(args["files"], "{{ qa_pr_compose_run.files }}")
        self.assertEqual(
            args["services"], "{{ qa_pr_compose_run.services }}"
        )
        for forbidden in (
            "project_name",
            "remove_orphans",
            "pull",
            "recreate",
        ):
            self.assertNotIn(forbidden, args)

    def test_role_never_uses_credentialed_clients_or_setup_script(self):
        documents = [load_yaml(DEFAULT_FILE)]
        documents.extend(load_tasks(filename) for filename in TASK_FILES)
        text = scalar_text(documents).lower()
        for forbidden in ("mc ", "aws ", "boto3", "setup.sh"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, text)

    def test_operations_guide_warns_about_final_customer_environments(self):
        guide = OPERATIONS_GUIDE.read_text()
        self.assertIn("ambiente de cliente final", guide)
        self.assertIn("`<repositorio>#<N>`", guide)
        self.assertIn("`korp.pr`", guide)
        self.assertIn("`korp.repositorio`", guide)
        self.assertIn("repositórios diferentes", guide)


if __name__ == "__main__":
    unittest.main()
