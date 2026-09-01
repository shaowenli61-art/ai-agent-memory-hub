import tempfile
import unittest
from pathlib import Path

from memory_hub.deploy import apply_install_plan, build_install_plan, inspect_environment, verify_install


class DeployTests(unittest.TestCase):
    def test_inspect_environment_discovers_existing_agent_rules_without_writing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir)
            codex_rule = home / ".codex" / "AGENTS.md"
            codex_rule.parent.mkdir()
            codex_rule.write_text("# existing codex rules\n", encoding="utf-8")

            report = inspect_environment(home=home, system="Windows")

            self.assertEqual(report["platform"], "windows")
            self.assertTrue(report["agents"]["codex"]["installed"])
            self.assertEqual(report["agents"]["codex"]["rule_file"], str(codex_rule))
            self.assertFalse((home / ".claude" / "CLAUDE.md").exists())
            self.assertIn("python", report["prerequisites"])
            self.assertIn("obsidian", report["prerequisites"])
            self.assertTrue(report["workbench_options"]["web"])
            self.assertTrue(report["workbench_options"]["desktop"])

    def test_macos_doctor_marks_desktop_workbench_as_unsupported(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            report = inspect_environment(home=Path(temp_dir), system="Darwin")

            self.assertFalse(report["workbench_options"]["desktop"])

    def test_macos_plan_rejects_windows_desktop_workbench(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            environment = inspect_environment(home=root / "home", system="Darwin")

            with self.assertRaisesRegex(ValueError, "Windows 10/11 only"):
                build_install_plan(
                    environment=environment,
                    vault=root / "vault",
                    agents=["codex"],
                    rule_scope="global",
                    workbench="desktop",
                )

    def test_confirmed_install_creates_empty_vault_and_preserves_existing_global_rules(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            home = root / "home"
            codex_rule = home / ".codex" / "AGENTS.md"
            codex_rule.parent.mkdir(parents=True)
            codex_rule.write_text("# My existing rules\n", encoding="utf-8")
            package_root = root / "package"
            protocol = package_root / "protocols" / "growth-ai-collaboration-v3.2.1.md"
            protocol.parent.mkdir(parents=True)
            protocol.write_text("# Core protocol V3.2.1\n", encoding="utf-8")
            web_source = package_root / "workbench" / "web"
            web_source.mkdir(parents=True)
            (web_source / "index.html").write_text("<h1>Memory Hub</h1>\n", encoding="utf-8")
            environment = inspect_environment(home=home, system="Windows")
            plan = build_install_plan(
                environment=environment,
                vault=root / "vault",
                agents=["codex"],
                rule_scope="global",
                workbench="web",
            )

            receipt = apply_install_plan(plan, package_root=package_root, confirmed=True)

            self.assertTrue((root / "vault" / "README.md").exists())
            self.assertTrue((root / "vault" / "20-Projects" / "项目索引.md").exists())
            self.assertTrue(
                (root / "vault" / "50-Agent-Workflows" / "00-Dashboard" / "当前任务.md").exists()
            )
            self.assertIn("# My existing rules", codex_rule.read_text(encoding="utf-8"))
            self.assertIn("AI_MEMORY_HUB_RULES_V1:START", codex_rule.read_text(encoding="utf-8"))
            self.assertIn("python -m memory_hub close", codex_rule.read_text(encoding="utf-8"))
            self.assertTrue(Path(receipt["backups"][0]).exists())

    def test_project_scope_targets_project_rule_instead_of_global_rule(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            home = root / "home"
            global_rule = home / ".codex" / "AGENTS.md"
            global_rule.parent.mkdir(parents=True)
            global_rule.write_text("# global\n", encoding="utf-8")
            project = root / "project"
            project.mkdir()
            environment = inspect_environment(home=home, system="Windows")

            plan = build_install_plan(
                environment=environment,
                vault=root / "vault",
                agents=["codex"],
                rule_scope="project",
                project_root=project,
                workbench="none",
            )

            self.assertEqual(plan["rule_targets"]["codex"], str(project / "AGENTS.md"))
            self.assertEqual(global_rule.read_text(encoding="utf-8"), "# global\n")

    def test_web_workbench_install_uses_generated_snapshot(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            package_root = root / "package"
            protocol = package_root / "protocols" / "growth-ai-collaboration-v3.2.1.md"
            protocol.parent.mkdir(parents=True)
            protocol.write_text("# Protocol\n", encoding="utf-8")
            web_source = package_root / "workbench" / "web"
            web_source.mkdir(parents=True)
            (web_source / "index.html").write_text("<h1>Memory Hub</h1>\n", encoding="utf-8")
            environment = inspect_environment(home=root / "home", system="Darwin")
            plan = build_install_plan(
                environment=environment,
                vault=root / "vault",
                agents=[],
                rule_scope="global",
                workbench="web",
            )

            receipt = apply_install_plan(plan, package_root=package_root, confirmed=True)

            web_install = Path(receipt["web_workbench"])
            self.assertTrue((web_install / "index.html").exists())
            self.assertTrue((web_install / "data" / "operations_snapshot.json").exists())

    def test_growth_protocol_can_be_disabled_in_reviewed_plan(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            package_root = root / "package"
            protocol = package_root / "protocols" / "growth-ai-collaboration-v3.2.1.md"
            protocol.parent.mkdir(parents=True)
            protocol.write_text("# Protocol\n", encoding="utf-8")
            environment = inspect_environment(home=root / "home", system="Windows")
            plan = build_install_plan(
                environment=environment,
                vault=root / "vault",
                agents=["codex"],
                rule_scope="global",
                workbench="none",
                growth_mode="disabled",
            )

            apply_install_plan(plan, package_root=package_root, confirmed=True)

            rule = Path(plan["rule_targets"]["codex"]).read_text(encoding="utf-8")
            self.assertNotIn("# Protocol", rule)
            self.assertIn("AI_MEMORY_HUB_RULES_V1:START", rule)

    def test_verify_install_detects_a_missing_rule_block(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            vault = root / "vault"
            vault.mkdir()
            rule = root / "AGENTS.md"
            receipt = {
                "vault": str(vault),
                "updated_rule_files": [str(rule)],
                "workbench": "none",
            }
            (vault / ".memory-hub").mkdir()
            (vault / ".memory-hub" / "install-receipt.json").write_text(
                __import__("json").dumps(receipt), encoding="utf-8"
            )

            report = verify_install(vault)

            self.assertFalse(report["ok"])
            self.assertIn(str(rule), report["missing_rule_blocks"])


if __name__ == "__main__":
    unittest.main()
