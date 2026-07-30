from copy import deepcopy
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import json
import os
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[2]
PLUGIN_PATH = ROOT / "filter_plugins/qa_pr_filters.py"
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


class PluginDiscoveryTests(unittest.TestCase):
    def test_root_config_loads_shared_filter_for_ad_hoc_ansible(self):
        ansible_binary = shutil.which("ansible")
        self.assertIsNotNone(
            ansible_binary,
            "Ative o ambiente Ansible antes de executar os testes",
        )
        environment = os.environ.copy()
        environment.pop("ANSIBLE_CONFIG", None)
        environment.pop("ANSIBLE_FILTER_PLUGINS", None)
        environment["ANSIBLE_COLLECTIONS_PATH"] = (
            "/tmp/devo-6789-collections"
        )
        result = subprocess.run(
            [
                ansible_binary,
                "localhost",
                "-i",
                "localhost,",
                "-c",
                "local",
                "-m",
                "ansible.builtin.debug",
                "-a",
                "msg={{ [] | qa_pr_index_active_overrides }}",
            ],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(
            result.returncode,
            0,
            result.stdout + result.stderr,
        )
        self.assertIn('"msg": {}', result.stdout)


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

    def test_listing_rejects_nested_json_objects(self):
        xml_text = """
        <ListBucketResult>
          <IsTruncated>false</IsTruncated>
          <Contents><Key>prs/repo-a/123/service.json</Key></Contents>
          <Contents><Key>prs/repo-a/123/nested/other.json</Key></Contents>
        </ListBucketResult>
        """
        self.assertEqual(
            filters.parse_minio_listing(xml_text, "prs/repo-a/123/"),
            ["prs/repo-a/123/service.json"],
        )

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
                "pr_key": "logistica#579",
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

    def test_same_number_from_different_repositories_conflicts(self):
        current = target("repo-a#123", 123, "wms-core")
        incoming = target("repo-b#123", 123, "wms-core")
        conflicts = filters.detect_conflicts([current, incoming], {})
        self.assertEqual(
            [conflict["target_id"] for conflict in conflicts],
            [incoming["target_id"]],
        )

    def test_repo_qualified_refresh_does_not_conflict(self):
        incoming = target("repo-a#123", 123, "wms-core")
        owner = {**incoming, "pr_key": "repo-a#123"}
        self.assertEqual(
            filters.detect_conflicts(
                [incoming], {incoming["identity"]: owner}
            ),
            [],
        )

    def test_legacy_numeric_owner_conflicts_conservatively(self):
        incoming = target("repo-a#123", 123, "wms-core")
        owner = {**incoming, "pr_key": "#123"}
        self.assertEqual(
            len(filters.detect_conflicts(
                [incoming], {incoming["identity"]: owner}
            )),
            1,
        )

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

    def test_two_argument_detection_uses_keep_at_collisions(self):
        conflicts = filters.detect_conflicts(
            [self.incoming, self.current], self.active
        )
        self.assertEqual(
            [conflict["target_id"] for conflict in conflicts],
            [self.incoming["target_id"]],
        )

    def test_explicit_empty_decisions_stops_at_first_unresolved_conflict(self):
        later = target("logistica#581", 581, "wms-core")
        conflicts = filters.detect_conflicts(
            [self.incoming, later], self.active, {}
        )
        self.assertEqual(
            [conflict["target_id"] for conflict in conflicts],
            [self.incoming["target_id"]],
        )

    def test_explicit_keep_preserves_owner_for_following_refresh(self):
        conflicts = filters.detect_conflicts(
            [self.incoming, self.current],
            self.active,
            {self.incoming["target_id"]: "keep"},
        )
        self.assertEqual(
            [conflict["target_id"] for conflict in conflicts],
            [self.incoming["target_id"]],
        )

    def test_explicit_replace_reveals_next_real_conflict(self):
        conflicts = filters.detect_conflicts(
            [self.incoming, self.current],
            self.active,
            {self.incoming["target_id"]: "replace"},
        )
        self.assertEqual(
            [conflict["target_id"] for conflict in conflicts],
            [self.incoming["target_id"], self.current["target_id"]],
        )
        self.assertEqual(conflicts[1]["current"], self.incoming)

    def test_plan_conflicts_follow_ask_replay(self):
        keep_plan = filters.resolve_application(
            [self.incoming, self.current],
            self.active,
            policy="ask",
            decisions={self.incoming["target_id"]: "keep"},
        )
        replace_plan = filters.resolve_application(
            [self.incoming, self.current],
            self.active,
            policy="ask",
            decisions={
                self.incoming["target_id"]: "replace",
                self.current["target_id"]: "keep",
            },
        )
        self.assertEqual(
            [conflict["target_id"] for conflict in keep_plan["conflicts"]],
            [self.incoming["target_id"]],
        )
        self.assertEqual(
            [conflict["target_id"] for conflict in replace_plan["conflicts"]],
            [self.incoming["target_id"], self.current["target_id"]],
        )


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
            "project_src": "/etc/korp/composes",
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

    def test_indexes_repo_qualified_owner(self):
        content = deepcopy(self.current_content)
        content["services"]["wms-core"]["labels"]["korp.repositorio"] = (
            "logistica"
        )
        active, _ = self.active_owners(content)
        identity = "/etc/korp/composes|logistica-compose.yml|wms-core"
        self.assertEqual(active[identity]["pr_key"], "logistica#579")

    def test_indexes_valid_legacy_owner_without_repository_label(self):
        active = filters.index_active_overrides([{
            "project_src": "/srv",
            "path": "/srv/pr-overrides/pr123/app-compose.yml",
            "content": {
                "services": {
                    "api": {
                        "image": "korp/api:pr123",
                        "labels": {"korp.pr": "123"},
                    }
                }
            },
        }])
        identity = "/srv|app-compose.yml|api"
        self.assertEqual(active[identity]["pr_key"], "#123")

    def test_rejects_service_without_pr_label(self):
        content = deepcopy(self.current_content)
        del content["services"]["wms-core"]["labels"]["korp.pr"]
        with self.assertRaisesRegex(ValueError, "Label korp.pr inválida"):
            self.active_owners(content)

    def test_rejects_repeated_override_root_for_expected_project(self):
        override_file = {
            "project_src": "/srv",
            "path": (
                "/srv/pr-overrides/pr1/pr-overrides/"
                "pr123/app-compose.yml"
            ),
            "content": {
                "services": {
                    "api": {
                        "image": "korp/api:pr123",
                        "labels": {"korp.pr": "123"},
                    }
                }
            },
        }
        with self.assertRaisesRegex(ValueError, "Caminho de override inválido"):
            filters.index_active_overrides([override_file])

    def test_rejects_missing_or_mismatched_project_src(self):
        content = {
            "services": {
                "api": {
                    "image": "korp/api:pr123",
                    "labels": {"korp.pr": "123"},
                }
            }
        }
        invalid_overrides = [
            {
                "path": "/srv/pr-overrides/pr123/app-compose.yml",
                "content": content,
            },
            {
                "project_src": "/srv/other",
                "path": "/srv/pr-overrides/pr123/app-compose.yml",
                "content": content,
            },
        ]
        for override_file in invalid_overrides:
            with self.subTest(override_file=override_file):
                with self.assertRaises(ValueError):
                    filters.index_active_overrides([override_file])

    def test_rejects_invalid_override_schema(self):
        invalid_overrides = [
            {
                "project_src": "/srv",
                "path": "/srv/pr-overrides/pr123/app-compose.yml",
                "content": [],
            },
            {
                "project_src": "/srv",
                "path": "/srv/pr-overrides/pr123/app-compose.yml",
                "content": {"services": {}},
            },
            {
                "project_src": "/srv",
                "path": "/srv/pr-overrides/pr123/app-compose.yml",
                "content": {
                    "services": {
                        "api": {"labels": {"korp.pr": "123"}}
                    }
                },
            },
            {
                "project_src": "/srv",
                "path": (
                    "/srv/pr-overrides/pr123/nested/app-compose.yml"
                ),
                "content": {
                    "services": {
                        "api": {
                            "image": "korp/api:pr123",
                            "labels": {"korp.pr": "123"},
                        }
                    }
                },
            },
        ]
        for override_file in invalid_overrides:
            with self.subTest(override_file=override_file):
                with self.assertRaises(ValueError):
                    filters.index_active_overrides([override_file])

    def test_rejects_invalid_repository_label(self):
        content = deepcopy(self.current_content)
        content["services"]["wms-core"]["labels"]["korp.repositorio"] = (
            "repo/invalido"
        )
        with self.assertRaisesRegex(
            ValueError, "Label korp.repositorio inválida"
        ):
            self.active_owners(content)

    def test_rejects_duplicate_persisted_owner_identity(self):
        override_files = [
            {
                "project_src": "/etc/korp/composes",
                "path": (
                    f"/etc/korp/composes/pr-overrides/pr{pr}/"
                    "logistica-compose.yml"
                ),
                "content": {
                    "services": {
                        "wms-core": {
                            "image": f"korp/wms-core:pr{pr}",
                            "labels": {"korp.pr": str(pr)},
                        }
                    }
                },
            }
            for pr in (579, 580)
        ]
        with self.assertRaisesRegex(ValueError, "Mais de um override ativo"):
            filters.index_active_overrides(override_files)

    def test_rejects_noncanonical_override_paths(self):
        paths = (
            "/etc/korp/composes/pr-overrides/logistica-compose.yml",
            "/etc/korp/composes/pr-overrides/pr0/logistica-compose.yml",
            "/etc/korp/composes/pr-overrides/pr579/nested/logistica-compose.yml",
            "/etc/korp/composes/pr-overrides/pr579/logistica.yml",
        )
        for path in paths:
            with self.subTest(path=path), self.assertRaisesRegex(
                ValueError, "Caminho de override inválido"
            ):
                filters.index_active_overrides([{
                    "project_src": "/etc/korp/composes",
                    "path": path,
                    "content": self.current_content,
                }])

    def test_rejects_nonpositive_pr_label(self):
        override_file = {
            "project_src": "/etc/korp/composes",
            "path": "/etc/korp/composes/pr-overrides/pr1/logistica-compose.yml",
            "content": {
                "services": {
                    "wms-core": {
                        "image": "korp/wms-core:pr1",
                        "labels": {"korp.pr": "0"},
                    }
                }
            },
        }
        with self.assertRaisesRegex(ValueError, "Label korp.pr inválida"):
            filters.index_active_overrides([override_file])

    def test_rejects_override_path_pr_different_from_label(self):
        override_file = {
            "project_src": "/etc/korp/composes",
            "path": "/etc/korp/composes/pr-overrides/pr580/logistica-compose.yml",
            "content": {
                "services": {
                    "wms-core": {
                        "image": "korp/wms-core:pr579",
                        "labels": {"korp.pr": "579"},
                    }
                }
            },
        }
        with self.assertRaisesRegex(ValueError, "PR do caminho diverge"):
            filters.index_active_overrides([override_file])

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
                            "labels": {
                                "korp.pr": "580",
                                "korp.repositorio": "logistica",
                            },
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
                            "labels": {
                                "korp.pr": "580",
                                "korp.repositorio": "logistica",
                            },
                        },
                        "wms-gateway": {
                            "image": "korp/wms-gateway:pr580",
                            "labels": {
                                "korp.pr": "580",
                                "korp.repositorio": "logistica",
                            },
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
