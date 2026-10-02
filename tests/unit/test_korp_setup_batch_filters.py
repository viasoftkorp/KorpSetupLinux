import base64, hashlib, re, unittest
from _loader import load

f = load("filter_plugins/korp_setup_batch.py", "korp_setup_batch")
UUID_UP = re.compile(r"^[0-9A-F]{8}-[0-9A-F]{4}-5[0-9A-F]{3}-[89AB][0-9A-F]{3}-[0-9A-F]{12}$")


class PlanTest(unittest.TestCase):
    def test_none_service(self):
        plan = f.korp_service_plan({"Svc.A": None}, ["Svc.A"], "_", "")
        self.assertEqual(plan["services"]["Svc.A"], {"kv_skip": False, "oauth_client": {"skip": False}})
        self.assertEqual(plan["service_vars"]["Svc.A"], {"kv_skip": False, "oauth_client": {"skip": False}})
        self.assertEqual(plan["kv_services"], ["Svc.A"])
        self.assertEqual(plan["oauth_services"], ["Svc.A"])
        self.assertRegex(plan["secrets"]["Svc.A"], UUID_UP)
        self.assertEqual(plan["last_service"], "Svc.A")

    def test_existing_values_are_kept(self):
        svc = {"kv_skip": True, "oauth_client": {"skip": True, "x": 1}, "custom_kv_overwrite": ["Core"]}
        plan = f.korp_service_plan({"S": svc}, ["S"], "_", "")
        self.assertEqual(plan["services"]["S"], svc)
        self.assertEqual(plan["kv_services"], [])
        self.assertEqual(plan["oauth_services"], [])

    def test_oauth_client_without_skip_gets_default_and_keeps_keys(self):
        plan = f.korp_service_plan({"S": {"oauth_client": {"x": 1}}}, ["S"], "_", "")
        self.assertEqual(plan["services"]["S"]["oauth_client"], {"x": 1, "skip": False})

    def test_db_name_default_and_suffix(self):
        plan = f.korp_service_plan({"Korp.Svc.Core": {"db": {"type": "mssql"}}}, ["Korp.Svc.Core"], "_", "HML")
        self.assertEqual(plan["services"]["Korp.Svc.Core"]["db"], {"type": "mssql", "name": "Korp_Svc_Core"})
        self.assertEqual(plan["service_vars"]["Korp.Svc.Core"]["db"]["name"], "Korp_Svc_Core_HML")
        self.assertEqual(plan["mssql_databases"], [{"service": "Korp.Svc.Core", "name": "Korp_Svc_Core_HML"}])

    def test_db_suffix_and_lists(self):
        services = {
            "A": {"db": {"type": "postgres", "name": "dba"}, "volumes_directories": ["/d/a", "/d/b"]},
            "B": {"db": {"type": "mssql", "name": None}},
            "C": {"db": {"type": "oracle"}},
        }
        plan = f.korp_service_plan(services, ["A", "B", "C"], "_", "x")
        self.assertEqual(plan["postgres_databases"], [{"service": "A", "name": "dba_x"}])
        self.assertEqual(plan["mssql_databases"], [{"service": "B", "name": "B_x"}])
        self.assertEqual(plan["unsupported_databases"], [{"service": "C", "type": "oracle"}])
        self.assertEqual(plan["volume_directories"], ["/d/a", "/d/b"])
        self.assertEqual(services["B"]["db"]["name"], None, "a entrada não pode ser alterada")

    def test_invalid_db_type(self):
        for db in ({}, {"type": None}, None, "x"):
            plan = f.korp_service_plan({"A": {"db": db}, "B": None}, ["A", "B"], "_", "")
            self.assertEqual(plan["invalid"], ["A"])

    def test_volumes_directories_must_be_list(self):
        from ansible.errors import AnsibleFilterError
        for value in ("/d/a", None):
            with self.assertRaises(AnsibleFilterError) as ctx:
                f.korp_service_plan({"A": {"volumes_directories": value}}, ["A"], "_", "")
            self.assertIn("'volumes_directories' de A deve ser uma lista", str(ctx.exception))

    def test_order_follows_names(self):
        plan = f.korp_service_plan({"A": None, "B": None, "C": None}, ["C", "A", "B"], "_", "")
        self.assertEqual(plan["kv_services"], ["C", "A", "B"])
        self.assertEqual(plan["last_service"], "B")

    def test_secret_like_ansible_expression(self):
        from ansible.plugins.filter.core import to_uuid
        valid = {to_uuid(i).upper() for i in range(10000)}
        plan = f.korp_service_plan({"A": None, "B": None}, ["A", "B"], "_", "")
        self.assertIn(plan["secrets"]["A"], valid)
        self.assertIn(plan["secrets"]["B"], valid)


class ItemsTest(unittest.TestCase):
    def test_items_with_custom_overwrite(self):
        results = [{"korp_svc": "A", "ansible_facts": {"korp_rendered_kv": {"x": 1}}},
                   {"korp_svc": "B", "ansible_facts": {"korp_rendered_kv": "texto"}}]
        services = {"A": {"custom_kv_overwrite": ["Core"]}, "B": None}
        self.assertEqual(f.korp_kv_batch_items(results, services), [
            {"key": "A", "new_kv": {"x": 1}, "has_custom_kv_overwrite": True, "custom_kv_overwrite": ["Core"]},
            {"key": "B", "new_kv": "texto", "has_custom_kv_overwrite": False, "custom_kv_overwrite": None},
        ])


class OAuthTest(unittest.TestCase):
    def test_hash_matches_original_module(self):
        secret = "0F1E2D3C-0000-5000-8000-000000000000"
        expected = base64.b64encode(hashlib.sha256(secret.encode("utf-8")).digest()).decode()
        self.assertEqual(f.korp_sha256_base64(secret), expected)

    def test_clients(self):
        values = {"A": '{"Authorization": {"Secret": "S1"}}'}
        self.assertEqual(f.korp_oauth_clients(values, ["A"]),
                         [{"service_name": "A", "secret_as_hash": f.korp_sha256_base64("S1")}])

    def test_missing_kv_or_secret_fails(self):
        from ansible.errors import AnsibleFilterError
        for values in ({"A": None}, {"A": '{"x": 1}'}, {}):
            with self.assertRaises(AnsibleFilterError):
                f.korp_oauth_clients(values, ["A"])


class PathStatTest(unittest.TestCase):
    def test_existing_file_has_path(self):
        import tempfile
        with tempfile.NamedTemporaryFile() as fh:
            self.assertEqual(f.korp_path_stat(fh.name), {"stat": {"exists": True, "path": fh.name}})

    def test_missing_file_has_no_path(self):
        self.assertEqual(f.korp_path_stat("/nao/existe/compose.yml.j2"), {"stat": {"exists": False}})


if __name__ == "__main__":
    unittest.main()
