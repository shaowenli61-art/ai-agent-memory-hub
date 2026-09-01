import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from memory_hub.cli import main


class CliTests(unittest.TestCase):
    def test_doctor_json_is_machine_readable_for_deploying_agent(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = main(["doctor", "--json", "--home", temp_dir, "--system", "Darwin"])

            report = json.loads(output.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertEqual(report["platform"], "macos")
            self.assertEqual(report["home"], str(Path(temp_dir).resolve()))

    def test_plan_writes_reviewable_json_without_installing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plan_path = root / "install-plan.json"

            exit_code = main(
                [
                    "plan",
                    "--vault",
                    str(root / "vault"),
                    "--agent",
                    "codex",
                    "--rule-scope",
                    "global",
                    "--workbench",
                    "web",
                    "--growth-mode",
                    "enabled",
                    "--home",
                    str(root / "home"),
                    "--system",
                    "Windows",
                    "--output",
                    str(plan_path),
                ]
            )

            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            self.assertEqual(exit_code, 0)
            self.assertEqual(plan["workbench"], "web")
            self.assertFalse((root / "vault").exists())

    def test_install_requires_explicit_confirmation_and_applies_saved_plan(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            package = root / "package"
            protocol = package / "protocols" / "growth-ai-collaboration-v3.2.1.md"
            protocol.parent.mkdir(parents=True)
            protocol.write_text("# Protocol\n", encoding="utf-8")
            plan_path = root / "install-plan.json"
            plan_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "platform": "windows",
                        "vault": str(root / "vault"),
                        "agents": [],
                        "rule_targets": {},
                        "rule_scope": "global",
                        "workbench": "none",
                    }
                ),
                encoding="utf-8",
            )

            exit_code = main(
                ["install", "--plan", str(plan_path), "--yes", "--package-root", str(package)]
            )

            self.assertEqual(exit_code, 0)
            self.assertTrue((root / "vault" / "README.md").exists())

    def test_close_command_records_task_and_refreshes_snapshot(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            vault = Path(temp_dir) / "vault"

            exit_code = main(
                [
                    "close",
                    "--vault",
                    str(vault),
                    "--task",
                    "First task",
                    "--status",
                    "completed",
                    "--completed",
                    "Created the first memory",
                    "--next-action",
                    "Review it",
                    "--evidence",
                    "notes/result.md",
                ]
            )

            snapshot = json.loads(
                (vault / ".memory-hub" / "runtime" / "operations_snapshot.json").read_text(encoding="utf-8")
            )
            self.assertEqual(exit_code, 0)
            self.assertEqual(snapshot["recently_completed_projects"][0]["project"], "First task")

    def test_verify_command_returns_failure_for_an_incomplete_install(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            vault = Path(temp_dir) / "vault"
            vault.mkdir()
            output = io.StringIO()

            with redirect_stdout(output):
                exit_code = main(["verify", "--vault", str(vault)])

            report = json.loads(output.getvalue())
            self.assertEqual(exit_code, 1)
            self.assertFalse(report["ok"])

    def test_snapshot_command_creates_runtime_snapshot(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            vault = Path(temp_dir) / "vault"

            exit_code = main(["snapshot", "--vault", str(vault)])

            self.assertEqual(exit_code, 0)
            self.assertTrue((vault / ".memory-hub" / "runtime" / "operations_snapshot.json").exists())


if __name__ == "__main__":
    unittest.main()
