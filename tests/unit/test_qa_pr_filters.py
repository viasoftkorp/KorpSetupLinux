from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import json
import unittest

ROOT = Path(__file__).resolve().parents[2]
PLUGIN_PATH = ROOT / "roles/qa_pr_apply/filter_plugins/qa_pr_filters.py"
spec = spec_from_file_location("qa_pr_filters", PLUGIN_PATH)
filters = module_from_spec(spec)
spec.loader.exec_module(filters)


def target(
    pr_key,
    pr,
    service_key,
    project_src="/etc/korp/composes",
    compose_file="logistica-compose.yml",
):
    identity = f"{project_src}|{compose_file}|{service_key}"
    return {
        "target_id": f"{pr_key}|{identity}",
        "identity": identity,
        "pr_key": pr_key,
        "repo": pr_key.rsplit("#", 1)[0],
        "pr": pr,
        "service": service_key,
        "service_key": service_key,
        "desired_image": f"korp/{service_key}:pr{pr}",
        "project_src": project_src,
        "compose_file": compose_file,
        "override_path": f"{project_src}/pr-overrides/pr{pr}/{compose_file}",
    }


class NormalizePrLinksTests(unittest.TestCase):
    def test_accepts_csv_and_preserves_order(self):
        value = (
            "https://github.com/viasoftkorp/compras/pull/123,"
            " https://github.com/viasoftkorp/vendas/pull/456/"
        )
        self.assertEqual(
            filters.normalize_pr_links(value),
            [
                {
                    "url": "https://github.com/viasoftkorp/compras/pull/123",
                    "repo": "compras",
                    "pr": 123,
                    "key": "compras#123",
                },
                {
                    "url": "https://github.com/viasoftkorp/vendas/pull/456/",
                    "repo": "vendas",
                    "pr": 456,
                    "key": "vendas#456",
                },
            ],
        )

    def test_rejects_unqualified_or_foreign_links(self):
        for value in ("123", "https://github.com/outra/compras/pull/123"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                filters.normalize_pr_links(value)

    def test_rejects_empty_input(self):
        with self.assertRaises(ValueError):
            filters.normalize_pr_links("")


class MinioParsingTests(unittest.TestCase):
    def test_extracts_only_json_keys_under_expected_prefix(self):
        xml_text = (ROOT / "tests/fixtures/qa_prs/listing.xml").read_text()
        self.assertEqual(
            filters.parse_minio_listing(xml_text, "prs/compras/123/"),
            ["prs/compras/123/korp.compras.core.json"],
        )

    def test_rejects_truncated_listing(self):
        xml_text = """
        <ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">
          <IsTruncated>true</IsTruncated>
        </ListBucketResult>
        """
        with self.assertRaises(ValueError):
            filters.parse_minio_listing(xml_text, "prs/compras/123/")


class ReportParsingTests(unittest.TestCase):
    def test_validates_container_report_against_object_key(self):
        raw = (ROOT / "tests/fixtures/qa_prs/korp.compras.core.json").read_text()
        report = filters.load_report(
            raw,
            "compras",
            123,
            "prs/compras/123/korp.compras.core.json",
        )
        self.assertEqual(report["desired_image"], "korp/korp.compras.core:2025.1.0.42-pr123")

    def test_rejects_kind_not_implemented_in_phase_one(self):
        raw = json.dumps({
            "kind": "delphi",
            "pr": 123,
            "repositorio": "compras",
            "branch": "DEVO-6789-delphi",
            "servico": "KorpCadastrosService",
            "imagem": "korp/KorpCadastrosService",
            "tag": "2025.1.0.42-pr123",
            "versao": "2025.1.0",
            "commit": "abc1234",
            "build": 42,
        })
        with self.assertRaises(ValueError):
            filters.load_report(
                raw,
                "compras",
                123,
                "prs/compras/123/KorpCadastrosService.json",
            )


class BuildTargetsTests(unittest.TestCase):
    def test_finds_service_by_image_and_keeps_yaml_service_key(self):
        reports = [{
            "pr_key": "compras#123",
            "repositorio": "compras",
            "pr": 123,
            "servico": "korp.compras.core",
            "imagem": "korp/korp.compras.core",
            "tag": "2025.1.0.42-pr123",
            "desired_image": "korp/korp.compras.core:2025.1.0.42-pr123",
        }]
        compose_files = [{
            "path": "/etc/korp/composes/compras-compose.yml",
            "content": {
                "services": {
                    "korp-compras-core": {
                        "image": "korp/korp.compras.core:2025.1.0.x"
                    }
                }
            },
        }]
        targets = filters.build_targets(reports, compose_files)
        self.assertEqual(targets[0]["service_key"], "korp-compras-core")
        self.assertEqual(targets[0]["project_src"], "/etc/korp/composes")
        self.assertEqual(
            targets[0]["override_path"],
            "/etc/korp/composes/pr-overrides/pr123/compras-compose.yml",
        )

    def test_rejects_service_not_found_or_duplicated(self):
        report = {
            "pr_key": "compras#123",
            "repositorio": "compras",
            "pr": 123,
            "servico": "korp.compras.core",
            "imagem": "korp/korp.compras.core",
            "tag": "2025.1.0.42-pr123",
            "desired_image": "korp/korp.compras.core:2025.1.0.42-pr123",
        }
        with self.assertRaises(ValueError):
            filters.build_targets([report], [])
        duplicate = [
            {"path": f"/tmp/{name}-compose.yml",
             "content": {"services": {"core": {"image": "korp/korp.compras.core:base"}}}}
            for name in ("a", "b")
        ]
        with self.assertRaises(ValueError):
            filters.build_targets([report], duplicate)


class ConflictPlanningTests(unittest.TestCase):
    def setUp(self):
        self.current = target(
            pr_key="logistica#579", pr=579, service_key="wms-core"
        )
        self.incoming = target(
            pr_key="logistica#580", pr=580, service_key="wms-core"
        )
        self.other_service = target(
            pr_key="logistica#580", pr=580, service_key="wms-gateway"
        )
        self.active = {
            self.current["identity"]: {
                "pr_key": "#579",
                "pr": 579,
                "override_path": self.current["override_path"],
                "service_key": "wms-core",
            }
        }

    def test_different_service_in_same_compose_is_not_a_conflict(self):
        plan = filters.resolve_application(
            [self.other_service], self.active, policy="fail"
        )
        self.assertEqual(plan["conflicts"], [])
        self.assertEqual(plan["apply_targets"], [self.other_service])

    def test_reapplying_same_pr_is_not_a_conflict(self):
        plan = filters.resolve_application(
            [self.current], self.active, policy="fail"
        )
        self.assertEqual(plan["conflicts"], [])

    def test_fail_and_abort_produce_no_mutations(self):
        for policy, decisions in (
            ("fail", {}),
            ("ask", {self.incoming["target_id"]: "abort"}),
        ):
            plan = filters.resolve_application(
                [self.incoming], self.active, policy=policy, decisions=decisions
            )
            self.assertFalse(plan["may_mutate"])
            self.assertEqual(plan["writes"], [])
            self.assertEqual(plan["deletes"], [])

    def test_keep_skips_only_conflicting_target(self):
        plan = filters.resolve_application(
            [self.incoming, self.other_service], self.active, policy="keep"
        )
        self.assertEqual(plan["skipped_targets"], [self.incoming])
        self.assertEqual(plan["apply_targets"], [self.other_service])

    def test_replace_removes_old_owner_and_applies_new_target(self):
        plan = filters.resolve_application(
            [self.incoming], self.active, policy="replace"
        )
        self.assertEqual(
            plan["remove_services"],
            [{
                "path": self.current["override_path"],
                "service_key": "wms-core",
            }],
        )
        self.assertEqual(plan["apply_targets"], [self.incoming])


class MutationShapeTests(unittest.TestCase):
    def setUp(self):
        self.old_path = (
            "/etc/korp/composes/pr-overrides/pr579/logistica-compose.yml"
        )
        self.current_content = {
            "services": {
                "wms-core": {
                    "image": "korp/wms-core:pr579",
                    "labels": {"korp.pr": "579"},
                },
                "wms-gateway": {
                    "image": "korp/wms-gateway:pr579",
                    "labels": {"korp.pr": "579"},
                },
            }
        }

    def active_owners(self, content=None):
        override_file = {
            "path": self.old_path,
            "content": content or self.current_content,
        }
        return filters.index_active_overrides([override_file]), override_file

    def test_indexes_each_active_service_without_aliasing_input(self):
        active, override_file = self.active_owners()
        core_identity = "/etc/korp/composes|logistica-compose.yml|wms-core"
        self.assertEqual(active[core_identity]["pr_key"], "#579")
        self.assertEqual(active[core_identity]["pr"], 579)
        self.assertEqual(active[core_identity]["override_path"], self.old_path)
        self.assertEqual(active[core_identity]["service_key"], "wms-core")
        self.assertIsNot(
            active[core_identity]["override_content"], override_file["content"]
        )

    def test_rejects_duplicate_persisted_owner_identity(self):
        override_files = [
            {
                "path": (
                    f"/etc/korp/composes/pr-overrides/pr{pr}/"
                    "logistica-compose.yml"
                ),
                "content": {
                    "services": {
                        "wms-core": {"labels": {"korp.pr": str(pr)}}
                    }
                },
            }
            for pr in (579, 580)
        ]
        with self.assertRaisesRegex(ValueError, "Mais de um override ativo"):
            filters.index_active_overrides(override_files)

    def test_replace_of_only_service_deletes_old_override(self):
        current_content = {
            "services": {
                "wms-core": {
                    "image": "korp/wms-core:pr579",
                    "labels": {"korp.pr": "579"},
                }
            }
        }
        active, override_file = self.active_owners(current_content)
        incoming = target("logistica#580", 580, "wms-core")
        plan = filters.resolve_application([incoming], active, policy="replace")
        self.assertEqual(plan["deletes"], [self.old_path])
        self.assertEqual(
            plan["writes"],
            [{
                "path": incoming["override_path"],
                "content": {
                    "services": {
                        "wms-core": {
                            "image": "korp/wms-core:pr580",
                            "labels": {"korp.pr": "580"},
                        }
                    }
                },
            }],
        )
        self.assertEqual(override_file["content"], current_content)

    def test_replace_rewrites_old_override_when_another_service_remains(self):
        active, override_file = self.active_owners()
        incoming = target("logistica#580", 580, "wms-core")
        plan = filters.resolve_application([incoming], active, policy="replace")
        writes = {write["path"]: write["content"] for write in plan["writes"]}
        self.assertEqual(plan["deletes"], [])
        self.assertEqual(
            writes[self.old_path],
            {"services": {"wms-gateway": self.current_content["services"]["wms-gateway"]}},
        )
        self.assertEqual(override_file["content"], self.current_content)

    def test_groups_two_services_in_one_write_and_compose_run(self):
        incoming = [
            target("logistica#580", 580, "wms-core"),
            target("logistica#580", 580, "wms-gateway"),
        ]
        plan = filters.resolve_application(incoming, {}, policy="fail")
        self.assertEqual(
            plan["writes"],
            [{
                "path": incoming[0]["override_path"],
                "content": {
                    "services": {
                        "wms-core": {
                            "image": "korp/wms-core:pr580",
                            "labels": {"korp.pr": "580"},
                        },
                        "wms-gateway": {
                            "image": "korp/wms-gateway:pr580",
                            "labels": {"korp.pr": "580"},
                        },
                    }
                },
            }],
        )
        self.assertEqual(
            plan["compose_runs"],
            [{
                "project_src": "/etc/korp/composes",
                "files": [
                    "logistica-compose.yml",
                    "pr-overrides/pr580/logistica-compose.yml",
                ],
                "services": ["wms-core", "wms-gateway"],
            }],
        )

    def test_keep_does_not_advance_simulated_owner(self):
        active, _ = self.active_owners()
        first = target("logistica#580", 580, "wms-core")
        kept = target("logistica#581", 581, "wms-core")
        plan = filters.resolve_application(
            [first, kept],
            active,
            policy="ask",
            decisions={first["target_id"]: "replace", kept["target_id"]: "keep"},
        )
        self.assertEqual(plan["apply_targets"], [first])
        self.assertEqual(plan["skipped_targets"], [kept])
        write_paths = [write["path"] for write in plan["writes"]]
        self.assertIn(first["override_path"], write_paths)
        self.assertNotIn(kept["override_path"], write_paths)

    def test_replaced_batch_candidate_never_produces_a_write(self):
        first = target("logistica#580", 580, "wms-core")
        final = target("logistica#581", 581, "wms-core")
        plan = filters.resolve_application([first, final], {}, policy="replace")
        self.assertEqual(plan["apply_targets"], [final])
        self.assertEqual(
            [write["path"] for write in plan["writes"]],
            [final["override_path"]],
        )

    def test_refresh_then_replace_removes_persisted_owner(self):
        current_content = {
            "services": {
                "wms-core": {
                    "image": "korp/wms-core:pr579",
                    "labels": {"korp.pr": "579"},
                }
            }
        }
        active, _ = self.active_owners(current_content)
        refresh = target("logistica#579", 579, "wms-core")
        final = target("logistica#580", 580, "wms-core")
        plan = filters.resolve_application([refresh, final], active, policy="replace")
        self.assertEqual(plan["apply_targets"], [final])
        self.assertEqual(plan["deletes"], [self.old_path])
        self.assertEqual(
            [write["path"] for write in plan["writes"]],
            [final["override_path"]],
        )

    def test_invalid_or_missing_ask_decision_aborts(self):
        active, _ = self.active_owners()
        incoming = target("logistica#580", 580, "wms-core")
        for decisions in ({}, {incoming["target_id"]: "invalid"}):
            with self.subTest(decisions=decisions):
                plan = filters.resolve_application(
                    [incoming], active, policy="ask", decisions=decisions
                )
                self.assertFalse(plan["may_mutate"])
                self.assertEqual(plan["compose_runs"], [])

    def test_rejects_unknown_policy(self):
        with self.assertRaisesRegex(ValueError, "Política de conflito inválida"):
            filters.resolve_application([], {}, policy="unknown")
