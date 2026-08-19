import importlib.util
import pathlib
import unittest


PLUGIN_PATH = (
    pathlib.Path(__file__).parents[1] / "filter_plugins" / "compose_migration.py"
)
SPEC = importlib.util.spec_from_file_location("compose_migration", PLUGIN_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ComposeMigrationFilterTests(unittest.TestCase):
    def test_image_repository_removes_tag(self):
        self.assertEqual(
            MODULE.docker_image_repository(
                "registry.example:5000/korp/service:2025.1.0.x"
            ),
            "registry.example:5000/korp/service",
        )

    def test_image_repository_removes_digest(self):
        self.assertEqual(
            MODULE.docker_image_repository("korp/service@sha256:abc123"),
            "korp/service",
        )

    def test_image_repository_keeps_untagged_image(self):
        self.assertEqual(
            MODULE.docker_image_repository("registry.example:5000/korp/service"),
            "registry.example:5000/korp/service",
        )

    def test_legacy_name_removes_only_exact_version_suffix(self):
        self.assertEqual(
            MODULE.legacy_container_name("ADM01-2025.1.0", "2025.1.0"),
            "ADM01",
        )
        self.assertEqual(
            MODULE.legacy_container_name("ADM01-2025.1.0-old", "2025.1.0"),
            "ADM01-2025.1.0-old",
        )

    def test_anonymous_volume_detection(self):
        anonymous_name = "a" * 64
        self.assertTrue(
            MODULE.has_anonymous_volume(
                [{"Type": "volume", "Name": anonymous_name}]
            )
        )
        self.assertFalse(
            MODULE.has_anonymous_volume(
                [
                    {"Type": "volume", "Name": "korp-data"},
                    {"Type": "bind", "Name": ""},
                ]
            )
        )


if __name__ == "__main__":
    unittest.main()
