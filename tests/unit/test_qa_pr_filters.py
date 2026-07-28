from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import json
import unittest

ROOT = Path(__file__).resolve().parents[2]
PLUGIN_PATH = ROOT / "roles/qa_pr_apply/filter_plugins/qa_pr_filters.py"
spec = spec_from_file_location("qa_pr_filters", PLUGIN_PATH)
filters = module_from_spec(spec)
spec.loader.exec_module(filters)


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
