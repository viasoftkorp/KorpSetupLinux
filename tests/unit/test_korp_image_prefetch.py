import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest

from _loader import REPO, load

plan_mod = load("roles/utils/library/korp_image_prefetch_plan.py", "korp_image_prefetch_plan")
SCRIPT = os.path.join(REPO, "roles/utils/files/korp_image_prefetch.py")
pf = load("roles/utils/files/korp_image_prefetch.py", "korp_image_prefetch")


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(textwrap.dedent(text))


class RolesFixture(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)
        r = self.dir
        write(f"{r}/base/tasks/main.yml", "")
        write(f"{r}/base/templates/composes/base-compose.yml.j2", """\
            services:
              db:
                image: "redis:7.4"
              web:
                image: nginx
            """)
        write(f"{r}/ERP/meta/main.yml", "dependencies:\n  - base\n")
        write(f"{r}/ERP/templates/composes/2025.1.0/ERP-compose.yml.j2", """\
            services:
              erp:
                image: "{{ docker_account }}/viasoft.erp:{{ version_without_build }}.x{{ docker_image_suffix }}"
            """)
        write(f"{r}/ERP/templates/composes/2024.2.0/ERP-compose.yml.j2",
              'services:\n  erp:\n    image: "{{ docker_account }}/viasoft.erp.old:2024.2.0.x"\n')
        write(f"{r}/A/meta/main.yml", "dependencies:\n  - role: ERP\n")
        write(f"{r}/A/vars/main.yml", "tool_version: \"1.2.3\"\ntool_image: \"tools/a:{{ tool_version }}\"\n"
                                      "docker_account: role-value-ignored\n")
        write(f"{r}/A/templates/composes/A-compose.yml.j2", """\
            services:
              a:
                image: '{{ docker_account }}/korp.a:2025.1.0.x{{ docker_image_suffix }}'  # comentário
              tool:
                image: {{ tool_image }}
              {% if feature | default(false) %}
              opt:
                image: "{{ opt_image | default('x/y:1') }}"
              {% endif %}
              env:
                image: "${CUSTOM_IMAGE}"
            """)
        write(f"{r}/B/meta/main.yml", "dependencies:\n  - ERP\n")
        write(f"{r}/B/templates/composes/2025.1.0/B-compose.yml.j2",
              'services:\n  b:\n    image: "{{ docker_account }}/korp.b:{{ version_without_build }}.x"\n'
              '  erp-again:\n    image: "{{ docker_account }}/viasoft.erp:{{ version_without_build }}.x"\n')
        self.vars = {"docker_account": "korp", "docker_image_suffix": "", "version_without_build": "2025.1.0"}


class ExpandRolesTest(RolesFixture):
    def test_dependencies_first_each_role_once(self):
        order, missing = plan_mod.expand_roles(self.dir, ["A", "B"])
        self.assertEqual(order, ["base", "ERP", "A", "B"])
        self.assertEqual(missing, [])

    def test_missing_roles_are_reported(self):
        order, missing = plan_mod.expand_roles(self.dir, ["X", "B", "X"])
        self.assertEqual(order, ["base", "ERP", "B"])
        self.assertEqual(missing, ["X"])

    def test_templates_versioned_first_and_only_current_version(self):
        names = [os.path.relpath(p, self.dir) for p in plan_mod.compose_templates(self.dir, "ERP", "2025.1.0")]
        self.assertEqual(names, ["ERP/templates/composes/2025.1.0/ERP-compose.yml.j2"])


class ResolveTest(unittest.TestCase):
    def test_simple_and_nested_variables(self):
        v = {"a": "acct", "img": "{{ a }}/x:{{ t }}", "t": "1"}
        self.assertEqual(plan_mod.resolve("{{ img }}", v), "acct/x:1")
        self.assertEqual(plan_mod.resolve("{{a}}/y:{{ t }}", v), "acct/y:1")

    def test_anything_else_is_unresolved(self):
        for value in ("{{ undefined }}/x:1", "{{ a | default('b') }}/x", "${IMG}", "{% if x %}a{% endif %}", ""):
            self.assertIsNone(plan_mod.resolve(value, {"a": "acct"}), value)

    def test_normalize(self):
        self.assertEqual(plan_mod.normalize("nginx"), "nginx:latest")
        self.assertEqual(plan_mod.normalize("host:5000/img"), "host:5000/img:latest")
        self.assertEqual(plan_mod.normalize("korp/a:2025.1.0.x"), "korp/a:2025.1.0.x")
        self.assertEqual(plan_mod.normalize("a/b@sha256:abc"), "a/b@sha256:abc")


class PlanTest(RolesFixture):
    def test_plan_order_dedup_and_missing(self):
        local = {"redis:7.4", "korp/korp.b:2025.1.0.x"}
        result = plan_mod.plan(self.dir, ["A", "B"], "2025.1.0", self.vars, local)
        self.assertEqual(result["images"], [
            "redis:7.4", "nginx:latest", "korp/viasoft.erp:2025.1.0.x", "korp/korp.a:2025.1.0.x",
            "tools/a:1.2.3", "korp/korp.b:2025.1.0.x"])
        self.assertEqual(result["missing"], [
            "nginx:latest", "korp/viasoft.erp:2025.1.0.x", "korp/korp.a:2025.1.0.x", "tools/a:1.2.3"])
        self.assertEqual(sorted(u["value"] for u in result["unresolved"]),
                         ["${CUSTOM_IMAGE}", "{{ opt_image | default('x/y:1') }}"])

    def test_facts_override_role_vars(self):
        result = plan_mod.plan(self.dir, ["A"], "2025.1.0", self.vars, set())
        self.assertNotIn("role-value-ignored/korp.a:2025.1.0.x", result["images"])


class UpdateAppsTest(unittest.TestCase):
    def test_without_versioned_apps_uses_unversioned(self):
        self.assertEqual(plan_mod.update_apps({"unversioned": ["u1"], "versioned": None}, "2025.1.0"), ["u1"])
        self.assertEqual(plan_mod.update_apps({}, "2025.1.0"), [])

    def test_latest_equal_to_target_uses_previous_version(self):
        data = {"unversioned": ["u1"], "versioned": {"2024.2.0": ["a", "u1"], "2025.1.0": ["b"]}}
        self.assertEqual(plan_mod.update_apps(data, "2025.1.0"), ["u1", "a"])

    def test_upgrade_uses_latest_installed(self):
        data = {"unversioned": [], "versioned": {"2024.2.0": ["a"], "2025.1.0": ["b", "b"]}}
        self.assertEqual(plan_mod.update_apps(data, "2025.2.0"), ["b"])

    def test_newer_version_installed_is_used_like_update_yml(self):
        data = {"unversioned": [], "versioned": {"2024.2.0": ["a"], "2025.1.0": ["b"]}}
        self.assertEqual(plan_mod.update_apps(data, "2024.2.0"), ["b"])

    def test_empty_newer_key_selects_nothing_like_update_yml(self):
        data = {"unversioned": ["u"], "versioned": {"2025.1.0": ["b"], "2025.2.0": []}}
        self.assertEqual(plan_mod.update_apps(data, "2025.1.0"), ["u"])

    def test_numeric_version_order(self):
        data = {"unversioned": [], "versioned": {"2024.10.0": ["new"], "2024.9.0": ["old"]}}
        self.assertEqual(plan_mod.update_apps(data, "2026.1.0"), ["new"])


class RepositoryTemplatesTest(unittest.TestCase):
    def test_current_templates_resolve(self):
        roles_dir = os.path.join(REPO, "roles")
        roles = sorted(os.listdir(roles_dir))
        v = {"docker_account": "korp", "docker_image_suffix": "", "version_without_build": "2025.1.0"}
        result = plan_mod.plan(roles_dir, roles, "2025.1.0", v, set())
        self.assertGreater(len(result["images"]), 100)
        self.assertEqual([u for u in result["unresolved"]], [])
        for image in result["images"]:
            self.assertNotIn("{", image)


FAKE_DOCKER = """#!/bin/bash
img="${@: -1}"
key="$FAKE_DIR/present/${img//\\//_}"
if [ "$1 $2" = "image inspect" ]; then [ -f "$key" ] && exit 0 || exit 1; fi
if [ "$1" = pull ]; then
  echo "$img" >> "$FAKE_DIR/calls"
  case "$img" in
    fail/*) echo "pull access denied for $img" >&2; exit 1;;
    slow/*) exec sleep 30;;
  esac
  touch "$key"; exit 0
fi
exit 2
"""


class PrefetchProcessTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)
        os.makedirs(f"{self.dir}/present")
        self.docker = f"{self.dir}/docker"
        write(self.docker, FAKE_DOCKER)
        os.chmod(self.docker, stat.S_IRWXU)
        os.environ["FAKE_DIR"] = self.dir
        self.status = f"{self.dir}/st/status.json"
        self.addCleanup(lambda: pf.stop(self.status, wait=5))

    def cli(self, *args):
        out = subprocess.run([sys.executable, SCRIPT] + list(args), capture_output=True, text=True, timeout=30)
        self.assertEqual(out.returncode, 0, out.stderr)
        return json.loads(out.stdout)

    def wait_for(self, predicate, timeout=10):
        limit = time.monotonic() + timeout
        while time.monotonic() < limit:
            st = pf.read_status(self.status)
            if st and predicate(st):
                return st
            time.sleep(0.05)
        self.fail("timeout: %s" % pf.read_status(self.status))

    def test_run_pulls_skips_present_and_records_failures(self):
        open(f"{self.dir}/present/have_b:1", "w").close()
        os.makedirs(os.path.dirname(self.status))
        rc = pf.Prefetch(self.status, ["ok/a:1", "have/b:1", "fail/c:1"], 2, 60, self.docker).run()
        self.assertEqual(rc, 0)
        st = pf.read_status(self.status)
        self.assertEqual(st["state"], "done")
        self.assertEqual(st["pulled"], ["ok/a:1"])
        self.assertEqual(st["present"], ["have/b:1"])
        self.assertEqual([f["image"] for f in st["failed"]], ["fail/c:1"])
        self.assertIn("denied", st["failed"][0]["error"])
        self.assertEqual(st["active"], [])
        self.assertEqual(oct(os.stat(self.status).st_mode & 0o777), "0o644")

    def test_start_detaches_and_stop_cancels(self):
        started = self.cli("start", "--status", self.status, "--parallel", "1", "--docker", self.docker,
                           "--", "slow/x:1", "ok/y:1")
        self.assertTrue(pf.is_prefetch_process(started["pid"]))
        self.wait_for(lambda st: st["active"] == ["slow/x:1"])
        result = self.cli("stop", "--status", self.status)
        self.assertTrue(result["stopped"])
        self.assertEqual(result["state"], "cancelled")
        self.assertFalse(pf.is_prefetch_process(started["pid"]))
        self.assertFalse(os.path.exists(f"{self.dir}/present/ok_y:1"))

    def test_start_replaces_running_prefetch(self):
        first = self.cli("start", "--status", self.status, "--parallel", "1", "--docker", self.docker,
                         "--", "slow/x:1")
        self.wait_for(lambda st: st["active"] == ["slow/x:1"])
        second = self.cli("start", "--status", self.status, "--docker", self.docker, "--", "ok/z:1")
        self.assertFalse(pf.is_prefetch_process(first["pid"]))
        st = self.wait_for(lambda st: st["pid"] == second["pid"] and st["state"] == "done")
        self.assertEqual(st["pulled"], ["ok/z:1"])
        self.assertEqual(self.cli("stop", "--status", self.status)["stopped"], False)

    def test_stop_without_prefetch_and_with_foreign_pid(self):
        self.assertEqual(self.cli("stop", "--status", self.status), {"state": "absent"})
        os.makedirs(os.path.dirname(self.status))
        pf.write_status(self.status, {"pid": os.getpid(), "state": "running", "total": 1})
        result = self.cli("stop", "--status", self.status)
        self.assertFalse(result["stopped"])


if __name__ == "__main__":
    unittest.main()
