from copy import deepcopy
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[2]
PLAYBOOK = ROOT / "self_signed_renew-playbook.yml"
RENEW_SCRIPT = (
    ROOT / "roles/infrastructure/templates/scripts/cert_renew.sh.j2"
)


def load_playbook():
    return yaml.safe_load(PLAYBOOK.read_text())


def module_task(tasks, module):
    return next(task for task in tasks if module in task)


class SelfSignedRenewPlaybookTests(unittest.TestCase):
    def test_ansible_can_include_vault_encrypted_persisted_inventory(self):
        ansible_playbook = shutil.which("ansible-playbook")
        ansible_vault = shutil.which("ansible-vault")
        self.assertIsNotNone(ansible_playbook)
        self.assertIsNotNone(ansible_vault)

        with tempfile.TemporaryDirectory(prefix="devo-7624-") as temp_dir:
            temp = Path(temp_dir)
            vault_key = temp / ".vault_key"
            inventory = temp / "inventory.yml"
            harness = temp / "include-inventory.yml"
            vault_key.write_text("test-vault-password\n")
            inventory.write_text(
                yaml.safe_dump(
                    {
                        "all": {
                            "children": {
                                "nodes": {
                                    "hosts": {
                                        "localhost": {
                                            "linux_korp": {
                                                "user": "renew-user",
                                                "password": "secret",
                                            },
                                            "certs": {
                                                "pfx_passphrase": "pfx-secret"
                                            },
                                        }
                                    }
                                }
                            }
                        }
                    }
                )
            )
            bootstrap = deepcopy(load_playbook()[0])
            include_vars = [
                task["ansible.builtin.include_vars"]
                for task in bootstrap["tasks"]
                if "ansible.builtin.include_vars" in task
            ]
            include_vars[0]["file"] = str(ROOT / "group_vars/all")
            include_vars[1]["file"] = str(inventory)
            verify_facts = {
                "name": "Valida fatos disponíveis no segundo play",
                "hosts": "127.0.0.1",
                "connection": "local",
                "gather_facts": False,
                "tasks": [
                    {
                        "ansible.builtin.assert": {
                            "that": [
                                "linux_korp.user == 'renew-user'",
                                "certs.pfx_passphrase == 'pfx-secret'",
                            ]
                        }
                    }
                ],
            }
            harness.write_text(
                yaml.safe_dump(
                    [bootstrap, verify_facts],
                    sort_keys=False,
                )
            )
            environment = os.environ.copy()
            environment["ANSIBLE_LOCAL_TEMP"] = str(temp / "local")
            environment["ANSIBLE_REMOTE_TEMP"] = str(temp / "remote")
            encrypt = subprocess.run(
                [
                    ansible_vault,
                    "encrypt",
                    str(inventory),
                    "--vault-id",
                    str(vault_key),
                ],
                cwd=ROOT,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(
                encrypt.returncode, 0, encrypt.stdout + encrypt.stderr
            )

            result = subprocess.run(
                [
                    ansible_playbook,
                    str(harness),
                    "--limit",
                    "localhost",
                    "--vault-id",
                    str(vault_key),
                ],
                cwd=ROOT,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(
                result.returncode, 0, result.stdout + result.stderr
            )
            self.assertTrue(inventory.read_text().startswith("$ANSIBLE_VAULT;"))

    def test_loads_persisted_inventory_before_privileged_renewal(self):
        bootstrap, renewal = load_playbook()

        self.assertEqual(bootstrap["hosts"], "127.0.0.1")
        self.assertEqual(bootstrap["connection"], "local")
        self.assertIs(bootstrap["gather_facts"], False)
        self.assertIs(bootstrap["become"], False)
        self.assertNotIn("become_user", bootstrap)

        include_vars = [
            task["ansible.builtin.include_vars"]
            for task in bootstrap["tasks"]
            if "ansible.builtin.include_vars" in task
        ]
        self.assertIn(
            {"file": "{{ playbook_dir }}/group_vars/all"}, include_vars
        )
        self.assertIn(
            {
                "file": "/etc/korp/ansible/inventory.yml",
                "name": "persisted_inventory",
            },
            include_vars,
        )

        facts = module_task(
            bootstrap["tasks"], "ansible.builtin.set_fact"
        )["ansible.builtin.set_fact"]
        inventory_host = (
            "persisted_inventory.all.children.nodes.hosts.localhost"
        )
        self.assertIn(f"{inventory_host}.linux_korp", facts["linux_korp"])
        self.assertIn(f"{inventory_host}.certs", facts["certs"])

        self.assertEqual(renewal["hosts"], bootstrap["hosts"])
        self.assertIs(renewal["become"], True)
        self.assertEqual(renewal["become_user"], "{{ linux_korp.user }}")
        self.assertEqual(
            renewal["vars"]["ansible_become_password"],
            "{{ linux_korp.password }}",
        )

    def test_preserves_certificate_threshold_pfx_and_reload_flow(self):
        renewal = load_playbook()[1]
        certificate_info = module_task(
            renewal["tasks"], "community.crypto.x509_certificate_info"
        )
        self.assertEqual(
            certificate_info["community.crypto.x509_certificate_info"]["path"],
            "/etc/korp/certs/cert.crt",
        )
        certificate = module_task(
            renewal["tasks"], "community.crypto.x509_certificate"
        )
        certificate_args = certificate["community.crypto.x509_certificate"]
        self.assertEqual(certificate["when"], "(days_cert_is_valid | int) < 30")
        self.assertEqual(certificate_args["provider"], "ownca")
        self.assertEqual(certificate_args["ownca_not_after"], "+365d")
        self.assertEqual(
            certificate_args["ownca_path"], "{{ self_signed_ca_cert_path }}"
        )
        self.assertEqual(
            certificate_args["ownca_privatekey_path"],
            "{{ self_signed_ca_cert_privatekey_path }}",
        )
        for days_remaining, should_renew in ((31, False), (29, True), (-1, True)):
            with self.subTest(days_remaining=days_remaining):
                self.assertEqual(days_remaining < 30, should_renew)

        pfx = module_task(
            renewal["tasks"], "community.crypto.openssl_pkcs12"
        )
        self.assertEqual(pfx["register"], "cert_updated")
        self.assertEqual(
            pfx["community.crypto.openssl_pkcs12"]["certificate_path"],
            "{{ cert_crt_path }}",
        )

        reload_task = module_task(renewal["tasks"], "ansible.builtin.shell")
        self.assertEqual(
            reload_task["ansible.builtin.shell"],
            "/etc/korp/scripts/certs_reload.sh",
        )
        self.assertEqual(reload_task["when"], "cert_updated.changed")

    def test_future_installations_pass_persisted_inventory_to_ansible_pull(self):
        script = RENEW_SCRIPT.read_text()
        self.assertIn(
            "-i {{ korp_dir_path }}/ansible/inventory.yml", script
        )
        self.assertIn("--vault-id {{ korp_dir_path }}/ansible/.vault_key", script)


if __name__ == "__main__":
    unittest.main()
