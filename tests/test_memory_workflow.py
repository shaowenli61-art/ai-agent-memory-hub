import tempfile
import unittest
from datetime import date
from pathlib import Path

from memory_hub.workflow import close_task, load_snapshot


class MemoryWorkflowTests(unittest.TestCase):
    def test_close_task_writes_obsidian_worklog_and_workbench_snapshot(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            vault = Path(temp_dir) / "vault"
            receipt = close_task(
                vault=vault,
                task="Prepare quarterly review",
                status="completed",
                completed="Built the review draft",
                next_action="Ask the manager for feedback",
                evidence=["reports/review.md"],
                event_date=date(2026, 9, 1),
            )

            snapshot = load_snapshot(vault)

            worklog = vault / "10-Daily" / "2026-09-01-worklog.md"
            self.assertTrue(worklog.exists())
            self.assertIn("Prepare quarterly review", worklog.read_text(encoding="utf-8"))
            self.assertEqual(snapshot["recently_completed_projects"][0]["project"], "Prepare quarterly review")
            self.assertEqual(receipt["status"], "completed")

    def test_close_task_refreshes_an_installed_web_workbench_copy(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            vault = Path(temp_dir) / "vault"
            web_data = vault / ".memory-hub" / "workbench" / "web" / "data"
            web_data.mkdir(parents=True)

            close_task(
                vault=vault,
                task="Refresh the workbench",
                status="stage-complete",
                completed="Updated the snapshot",
                next_action="Open the web page",
                evidence=[],
                event_date=date(2026, 9, 1),
            )

            copied_snapshot = web_data / "operations_snapshot.json"
            self.assertTrue(copied_snapshot.exists())
            self.assertIn("Refresh the workbench", copied_snapshot.read_text(encoding="utf-8"))
            self.assertTrue((web_data / "integration_health.json").exists())

    def test_active_task_exposes_its_next_action_to_the_workbench(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            vault = Path(temp_dir) / "vault"

            close_task(
                vault=vault,
                task="Build the first project index",
                status="active",
                completed="Initialized the Vault",
                next_action="Create 20-Projects/Project Index.md",
                evidence=["README.md"],
                event_date=date(2026, 9, 1),
            )

            task = load_snapshot(vault)["current_tasks"][0]
            self.assertEqual(task["status"], "active")
            self.assertEqual(task["next_action"], "Create 20-Projects/Project Index.md")
            dashboard = (
                vault / "50-Agent-Workflows" / "00-Dashboard" / "当前任务.md"
            ).read_text(encoding="utf-8")
            self.assertIn("Build the first project index", dashboard)
            self.assertIn("Create 20-Projects/Project Index.md", dashboard)


if __name__ == "__main__":
    unittest.main()
