import tempfile
import unittest
from pathlib import Path

from memory_hub.workbench import configure, register_project, refresh_snapshot
from memory_hub.workflow import close_task, _read_events
from memory_growth.workspace import GrowthWorkspace
from scripts import work_cycle


class GrowthIntegrationTests(unittest.TestCase):
    def test_month_report_keeps_receipt_count_while_deduplicating_episode(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            config = configure(vault, growth_mode="enabled")
            args = dict(vault=vault, task="修订样例", status="stage-complete", completed="形成版本",
                next_action="检查", evidence=[], task_id="TK-REV")
            close_task(**args)
            closed = close_task(**args)
            view = GrowthWorkspace(config).view()
            self.assertEqual(view["metrics"]["tasks"], 1)
            report = vault / "90-Reviews" / (closed["timestamp"][:7] + "-AI协作质量月度评估.md")
            self.assertIn("| schema v2 收工回执 | 2 |", report.read_text(encoding="utf-8"))

    def test_adoption_links_episode_without_claiming_effectiveness_or_promotion(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vault, project = root / "vault", root / "project"
            project.mkdir()
            config = configure(vault, growth_mode="enabled")
            register_project(vault, "Demo", project)
            artifact = project / "result.md"
            artifact.write_text("# Synthetic result\n", encoding="utf-8")
            closed = close_task(vault=vault, task="合成分析", status="stage-complete", completed="形成结果",
                next_action="请判断", evidence=[str(artifact)], project="Demo", task_id="TK-DEMO")
            row = next(p for p in work_cycle.all_projects(refresh_snapshot(vault)).values() if p["project"] == "Demo")
            delivery = row["work_cycle"]["deliveries"][0]
            self.assertEqual(delivery["episode_ref"]["task_id"], closed["task_id"])
            result = work_cycle.command(config, dict(action="review", project_key=row["lifecycle"]["project_key"],
                revision=row["work_cycle"]["revision"], data=dict(delivery_id=delivery["id"], status="accepted", purpose="报告")))
            self.assertEqual(result["growth"]["state"], "recorded")
            view = GrowthWorkspace(config).view()
            self.assertEqual(view["tasks"][0]["adoption_state"], "accepted")
            self.assertEqual(view["tasks"][0]["outcome_state"], "unknown")
            self.assertEqual(view["metrics"]["assessed"], 0)
            self.assertEqual(view["methods"], [])
            packet = next(p for p in work_cycle.all_projects(refresh_snapshot(vault)).values()
                if p["project"] == "Demo")["work_cycle"]["packet"]
            self.assertIn("成长协作状态", packet)
            self.assertIn("TK-DEMO", packet)

    def test_enabled_trigger_persists_pending_evaluation_and_month_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            config = configure(vault, growth_mode="enabled")
            event = close_task(vault=vault, task="有遗漏的分析", status="stage-complete", completed="补齐比较期",
                next_action="独立复验", evidence=[], agent="Fixture", task_id="TK-ANALYSIS",
                growth_events=("user_confirmed_omission",))
            self.assertEqual(event["growth"]["review_state"], "pending_llm")
            self.assertEqual(event["growth_sync"]["state"], "synchronized")
            view = GrowthWorkspace(config).view()
            self.assertEqual(view["metrics"]["pending_reviews"], 1)
            self.assertEqual(view["metrics"]["assessed"], 0)
            self.assertEqual(view["metrics"]["unknown_outcome"], 1)
            self.assertTrue((vault / "90-Reviews" / (event["timestamp"][:7] + "-AI协作质量月度评估.events.jsonl")).exists())
            self.assertTrue(view["reports"])

    def test_explicit_episode_revisions_and_idempotent_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            configure(vault)
            args = dict(vault=vault, task="合成任务", status="stage-complete", completed="完成一个版本",
                next_action="复验", evidence=[], agent="Fixture", task_id="TK-SAMPLE")
            first = close_task(**args, request_id="request-one")
            second = close_task(**args, request_id="request-two")
            repeated = close_task(**args, request_id="request-two")
            self.assertEqual(first["task_id"], second["task_id"])
            self.assertEqual(second["revision"], 2)
            self.assertEqual(second["supersedes_receipt_id"], first["receipt_id"])
            self.assertEqual(repeated["receipt_id"], second["receipt_id"])
            self.assertEqual(len(_read_events(vault)), 2)


if __name__ == "__main__":
    unittest.main()
