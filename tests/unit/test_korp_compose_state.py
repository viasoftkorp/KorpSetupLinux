import unittest
from _loader import load

m = load("roles/utils/library/korp_compose_state.py", "korp_compose_state")
cm = load("filter_plugins/compose_migration.py", "compose_migration")
P, V = "202510", "2025.1.0"
SVC = {"svc-a": {"container_name": "Korp.A-2025.1.0", "image": "acct/korp.a:2025.1.0.x"}}
OK_LABELS = {"com.docker.compose.project": P, "com.docker.compose.service": "svc-a"}


class ArgvTest(unittest.TestCase):
    def test_same_argv_as_original_tasks(self):
        self.assertEqual(
            m.compose_config_argv("docker", "/etc/korp/composes/2025.1.0", P, ["/etc/korp/composes/.env"],
                                  ["ERP-compose.yml", "/abs/x.yml"]),
            ["docker", "compose", "--ansi", "never", "--project-directory", "/etc/korp/composes/2025.1.0",
             "--project-name", P, "--env-file", "/etc/korp/composes/.env",
             "--file", "/etc/korp/composes/2025.1.0/ERP-compose.yml", "--file", "/abs/x.yml",
             "config", "--format", "json"])

    def test_names_parsing(self):
        self.assertEqual(m.parse_container_names("a\nb,c\n\n d \n"), {"a", "b", "c", "d"})

    def test_helpers_equal_filter_plugin(self):
        for name in ("Korp.A-2025.1.0", "Korp.A", "x-2025.1.0-2025.1.0", ""):
            self.assertEqual(m.legacy_container_name(name, V), cm.legacy_container_name(name, V))
        names = ["0123456789ab_Korp.A", "0123456789ab_Korp.AB", "Korp.A", "zz3456789ab_Korp.A"]
        self.assertEqual(m.partial_container_names(names, "Korp.A"), cm.partial_container_names(names, "Korp.A"))


class ClassifyTest(unittest.TestCase):
    def pre(self, names, labels=None, services=SVC):
        return m.classify(services, set(names), labels or {}, P, V, "pre")

    def post(self, names, services=SVC):
        return m.classify(services, set(names), {}, P, V, "post")

    def test_canonical_is_noop(self):
        self.assertEqual(self.pre(["Korp.A-2025.1.0"], {"Korp.A-2025.1.0": OK_LABELS}), {})
        self.assertEqual(self.post(["Korp.A-2025.1.0"]), {})

    def test_new_service_is_noop(self):
        self.assertEqual(self.pre([]), {})
        self.assertEqual(self.post(["Korp.A-2025.1.0"]), {})

    def test_pre_partial_when_target_missing(self):  # estado E
        self.assertEqual(self.pre(["0123456789ab_Korp.A-2025.1.0"]), {"svc-a": ["partial_recovery"]})

    def test_pre_partial_ignored_when_target_exists(self):
        names = ["Korp.A-2025.1.0", "0123456789ab_Korp.A-2025.1.0"]
        self.assertEqual(self.pre(names, {"Korp.A-2025.1.0": OK_LABELS}), {})
        self.assertEqual(self.post(names), {"svc-a": ["partial_leftover"]})

    def test_pre_backup(self):  # estado F
        self.assertEqual(self.pre(["Korp.A-2025.1.0-legacy-compose-migration"]), {"svc-a": ["migration_backup"]})

    def test_pre_wrong_project_or_service(self):  # estados A e B
        for labels in ({"com.docker.compose.project": "composes", "com.docker.compose.service": "svc-a"},
                       {"com.docker.compose.project": P, "com.docker.compose.service": "old-key"},
                       {}):
            self.assertEqual(self.pre(["Korp.A-2025.1.0"], {"Korp.A-2025.1.0": labels}),
                             {"svc-a": ["identity_conflict"]})

    def test_pre_unknown_labels_are_conflict(self):
        self.assertEqual(self.pre(["Korp.A-2025.1.0"], {}), {"svc-a": ["identity_conflict"]})

    def test_post_legacy_container(self):  # estado C
        self.assertEqual(self.post(["Korp.A-2025.1.0", "Korp.A"]), {"svc-a": ["legacy_container"]})

    def test_service_without_container_name_is_ignored(self):
        services = {"svc-b": {"image": "x"}}
        self.assertEqual(self.pre(["svc-b", "0123456789ab_"], services=services), {})
        self.assertEqual(self.post(["svc-b"], services=services), {})

    def test_unsuffixed_target_has_no_legacy(self):
        services = {"consul": {"container_name": "consul-server"}}
        self.assertEqual(self.post(["consul-server"], services=services), {})


if __name__ == "__main__":
    unittest.main()
