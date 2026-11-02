"""Synthetic receipts only; no private Vault, network or model credentials."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from memory_growth._core import REVIEW_FIELDS
from memory_growth.workspace import GrowthWorkspace
from memory_hub import workflow
from memory_hub.workbench import configure, register_project, refresh_snapshot, config_path
from scripts import work_cycle


def answer(ref):
    result = {name: "有机制线索并核对对照证据" for name in REVIEW_FIELDS}
    result.update(increment_state="validated", evidence_state="partial", outcome_state="positive",
        pattern_key="sample.coverage", methodology_candidate="补证停止闸门", evidence_refs=[ref])
    return json.dumps(result, ensure_ascii=False)


@contextmanager
def case(project=False, enabled=True):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        vault = root / "vault"
        config = configure(vault, growth_mode="enabled" if enabled else "disabled")
        args = dict(vault=vault, task="合成任务", task_id="TK-CASE", status="stage-complete",
            completed="完成受测版本", next_action="核查结果", evidence=["evidence:sample"])
        if project:
            source = root / "project"
            source.mkdir()
            register_project(vault, "Demo", source)
            artifact = source / "result.md"
            artifact.write_text("# Synthetic result\n", encoding="utf-8")
            args.update(project="Demo", evidence=[str(artifact)])
        yield vault, config, args


def review(config, vault, **observation):
    row = next(p for p in work_cycle.all_projects(refresh_snapshot(vault)).values() if p["project"] == "Demo")
    delivery = row["work_cycle"]["deliveries"][0]
    return work_cycle.command(config, dict(action="review", project_key=row["lifecycle"]["project_key"],
        revision=row["work_cycle"]["revision"], data=dict(delivery_id=delivery["id"], status="revise",
            purpose="报告", feedback="遗漏影响判断的比较口径", growth_observation=observation)))


class GrowthNegativeRegressionTests(unittest.TestCase):
    def test_writer_raising_after_complete_write_is_rolled_back_before_retry(self):
        from scripts.file_write_guard import safe_write_text
        with case(project=True) as (vault, config, args):
            def write_then_fail(path, *values):
                value = safe_write_text(path, *values)
                if path.name == 'memory-close-receipts.jsonl':
                    raise PermissionError('synthetic error after writing exact expected bytes')
                return value
            with patch('scripts.file_write_guard.safe_write_text', side_effect=write_then_fail):
                with self.assertRaises(PermissionError):
                    workflow.close_task(**args, request_id='write-then-fail')
            self.assertEqual(workflow._read_events(vault), [])
            self.assertEqual(GrowthWorkspace(config).receipts(), [])
            workflow.close_task(**args, request_id='write-then-fail')
            self.assertEqual(len(workflow._read_events(vault)), 1)

    def test_broken_growth_history_does_not_block_valid_formal_task_close(self):
        with case() as (vault, config, args):
            first = workflow.close_task(**args)
            workspace = GrowthWorkspace(config)
            source = workspace.path(workspace.events_name)
            original = source.read_bytes()
            source.write_bytes(b'{"synthetic broken json":')
            second = workflow.close_task(**args)
            self.assertEqual(second['growth']['review_state'], 'pending_storage')
            self.assertEqual(second['growth_sync']['state'], 'pending')
            self.assertEqual(len(workflow._read_events(vault)), 2)
            self.assertEqual(source.read_bytes(), b'{"synthetic broken json":')
            source.write_bytes(original)
            self.assertEqual(workspace.after_receipt(second['receipt_id'])['pending'], 0)
            self.assertEqual(workspace.view()['tasks'][0]['growth']['review_state'], 'not_required')

    def test_plain_feedback_save_retains_explicit_observation(self):
        with case(project=True) as (vault, config, args):
            workflow.close_task(**args)
            review(config, vault, outcome_state='positive', protocol_verdict='hit')
            review(config, vault)
            row = GrowthWorkspace(config).view()['tasks'][0]
            self.assertEqual(row['outcome_state'], 'positive')
            self.assertEqual(row['protocol_verdict'], 'hit')

    def test_formal_write_failure_rolls_back_before_idempotent_retry(self):
        from scripts.file_write_guard import safe_write_text
        with case(project=True) as (vault, config, args):
            def fail_formal(path, *values):
                if path.name == 'memory-close-receipts.jsonl':
                    raise PermissionError('synthetic formal write failure')
                return safe_write_text(path, *values)
            with patch('scripts.file_write_guard.safe_write_text', side_effect=fail_formal):
                with self.assertRaises(PermissionError):
                    workflow.close_task(**args, request_id='same-retry')
            self.assertEqual(workflow._read_events(vault), [])
            completed = workflow.close_task(**args, request_id='same-retry')
            self.assertEqual(len(workflow._read_events(vault)), 1)
            self.assertIn(completed['receipt_id'], (vault / '50-Agent-Workflows/90-Logs/memory-close-receipts.jsonl').read_text(encoding='utf-8'))

    def test_stale_review_cannot_replace_a_later_corrected_version(self):
        with case() as (vault, config, args):
            first = workflow.close_task(**args)
            corrected = workflow.close_task(**{**args, 'completed': 'corrected'})
            before = (vault / '.memory-hub/events/task-events.jsonl').read_bytes()
            with self.assertRaisesRegex(ValueError, '新|stale|latest'):
                workflow.close_task(**args, revises_receipt_id=first['receipt_id'])
            self.assertEqual((vault / '.memory-hub/events/task-events.jsonl').read_bytes(), before)

    def test_feedback_projection_failure_is_durable_and_replayable_without_new_receipt(self):
        from scripts.file_write_guard import safe_write_text
        with case(project=True) as (vault, config, args):
            closed = workflow.close_task(**args)
            formal = vault / "50-Agent-Workflows/90-Logs/memory-close-receipts.jsonl"
            before = formal.read_bytes()
            def fail_state(path, *values):
                if path.name == "growth-state.json":
                    raise OSError("synthetic state persistence failure")
                return safe_write_text(path, *values)
            with patch.object(work_cycle, "growth_workspace", return_value=GrowthWorkspace(config, writer=fail_state)):
                saved = review(config, vault, protocol_verdict="miss", confirmed_omission=True)
            self.assertTrue(saved["ok"])
            self.assertEqual(saved["growth"]["state"], "pending")
            workspace = GrowthWorkspace(config)
            self.assertGreater(workspace.view()["pending"], 0)
            self.assertEqual(workspace.after_receipt(closed["receipt_id"])["pending"], 0)
            self.assertEqual(workspace.view()["pending"], 0)
            self.assertEqual(formal.read_bytes(), before)

    def test_source_edit_stays_pending_then_original_receipt_replay_recovers(self):
        with case() as (vault, config, args):
            closed = workflow.close_task(**args)
            workspace = GrowthWorkspace(config)
            source = workspace.path(workspace.events_name)
            original = source.read_bytes()
            receipts = (vault / ".memory-hub/events/task-events.jsonl").read_bytes()
            changed = original.replace(b"{", b"{ ", 1)
            source.write_bytes(changed)
            failed = workspace.after_receipt(closed["receipt_id"])
            self.assertEqual(failed["state"], "pending")
            self.assertEqual(source.read_bytes(), changed)
            self.assertEqual((vault / ".memory-hub/events/task-events.jsonl").read_bytes(), receipts)
            source.write_bytes(original)  # Restore only this test's exact original bytes.
            self.assertEqual(workspace.after_receipt(closed["receipt_id"])["pending"], 0)
            self.assertEqual(workspace.after_receipt(closed["receipt_id"])["pending"], 0)
            self.assertEqual(source.read_bytes(), original)
            self.assertEqual((vault / ".memory-hub/events/task-events.jsonl").read_bytes(), receipts)

    def test_conflicting_append_is_rejected_without_sorting_or_rewriting_source(self):
        with case() as (vault, config, args):
            closed = workflow.close_task(**args)
            workspace = GrowthWorkspace(config)
            source = workspace.path(workspace.events_name)
            row = json.loads(source.read_text(encoding="utf-8").splitlines()[0])
            row["payload"]["pattern_key"] = "conflicting.payload"
            changed = source.read_bytes() + (json.dumps(row) + "\n").encode()
            source.write_bytes(changed)
            self.assertEqual(workspace.after_receipt(closed["receipt_id"])["state"], "pending")
            self.assertEqual(source.read_bytes(), changed)

    def test_read_only_views_do_not_write_and_disabled_mode_creates_no_growth_ledger(self):
        for enabled in (False, True):
            with self.subTest(enabled=enabled), case(enabled=enabled) as (vault, config, args):
                workflow.close_task(**args)
                before = {p.relative_to(vault): p.read_bytes() for p in vault.rglob("*") if p.is_file()}
                GrowthWorkspace(config).view()
                self.assertEqual(before, {p.relative_to(vault): p.read_bytes() for p in vault.rglob("*") if p.is_file()})
                if not enabled:
                    self.assertFalse((vault / "50-Agent-Workflows/90-Logs/growth-evaluation-events.jsonl").exists())

    def test_unknown_event_and_request_conflict_fail_before_any_new_task_event(self):
        with case() as (vault, config, args):
            workflow.close_task(**args, request_id="same-key")
            log = vault / ".memory-hub/events/task-events.jsonl"
            before = log.read_bytes()
            with self.assertRaisesRegex(ValueError, "unknown growth event"):
                workflow.close_task(**args, growth_events=("invented_event",))
            with self.assertRaisesRegex(ValueError, "request_id"):
                workflow.close_task(**{**args, "completed": "different"}, request_id="same-key")
            self.assertEqual(log.read_bytes(), before)

    def test_old_configuration_stays_unconfigured_not_implicitly_enabled(self):
        with case(enabled=False) as (vault, config, args):
            stored = json.loads(config_path(vault).read_text(encoding="utf-8"))
            stored.pop("growth_mode")
            config_path(vault).write_text(json.dumps(stored), encoding="utf-8")
            result = workflow.close_task(**args)
            self.assertEqual(result["growth"]["mode"], "legacy_unconfigured")
            self.assertEqual(result["growth_sync"]["state"], "disabled")

    def test_two_supported_episodes_only_create_pending_revalidation_method(self):
        with case() as (vault, config, args):
            first = workflow.close_task(**args, growth_events=("user_requested_retrospective",),
                growth_reviewer=lambda _: answer("evidence:sample"))
            second = workflow.close_task(**{**args, "task": "第二个合成任务", "task_id": "TK-SECOND",
                "evidence": ["evidence:second"]}, growth_events=("user_requested_retrospective",),
                growth_reviewer=lambda _: answer("evidence:second"))
            self.assertEqual(first["growth"]["methodology_decision"], "暂缓")
            self.assertEqual(second["growth"]["methodology_decision"], "沉淀")
            view = GrowthWorkspace(config).view()
            self.assertEqual(view["metrics"]["assessed"], 0)
            self.assertEqual(view["metrics"]["unknown_outcome"], 2)
            self.assertTrue(all(m["state"] == "pending_revalidation" for m in view["methods"]))
            cards = list((vault / "50-Agent-Workflows/10-SOP").glob("Growth-*.md"))
            self.assertEqual(len(cards), 1)
            self.assertIn("不是正式 Policy", cards[0].read_text(encoding="utf-8"))

    def test_revision_after_confirmed_omission_resolves_pending_across_timezones(self):
        with case(project=True) as (vault, config, args):
            first = workflow.close_task(**args)
            feedback = review(config, vault, protocol_verdict="miss", confirmed_omission=True)
            self.assertEqual(feedback["growth"]["state"], "recorded")
            self.assertEqual(GrowthWorkspace(config).view()["metrics"]["pending_reviews"], 1)
            future = datetime.fromisoformat(first["timestamp"]) + timedelta(minutes=1)
            with patch.object(workflow, "datetime") as clock:
                clock.now.return_value = future
                second = workflow.close_task(**args, growth_reviewer=lambda _: answer(args["evidence"][0]))
            self.assertEqual(second["growth"]["review_state"], "completed")
            self.assertEqual(GrowthWorkspace(config).view()["metrics"]["pending_reviews"], 0)


if __name__ == "__main__":
    unittest.main()
