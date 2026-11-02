from __future__ import annotations

import json
import hashlib
import unittest

from memory_growth import GrowthInput, review_task
from memory_growth._core import REVIEW_FIELDS


class MemoryGrowthInterfaceTests(unittest.TestCase):
    def test_unresolved_identity_with_evidence_cannot_count_as_independent_support(self):
        value = GrowthInput(task='新案例', summary='覆盖缺口', events=('user_confirmed_omission',),
            evidence_refs=('evidence:new',))
        response = {field: '机制与对照验证路径' for field in REVIEW_FIELDS}
        response.update(increment_state='candidate', evidence_state='partial', outcome_state='unknown',
            pattern_key='coverage-gap', evidence_refs=['evidence:new'])
        history = ({'task_id': 'TK-UNKNOWN', 'task': '未知身份案例', 'identity_state': 'identity_unresolved',
            'event': 'close', 'payload': {'review_state': 'completed', 'pattern_key': 'coverage-gap',
                'evidence_state': 'partial', 'evidence_refs': ['evidence:old']}},)
        result = review_task(value, task_id='TK-NEW', history=history, reviewer=lambda _: json.dumps(response))
        self.assertEqual(result.receipt_payload['methodology_decision'], '暂缓')

    def test_external_reviewer_error_cannot_leak_credentials_to_receipt_or_retry_prompt(self):
        calls = []
        secret = "API_KEY=synthetic-sensitive-value"
        def unavailable(prompt):
            calls.append(prompt)
            raise RuntimeError(secret)
        result = review_task(GrowthInput(task="复盘", summary="失败", events=("user_requested_retrospective",)),
            task_id="TK-SECRET", reviewer=unavailable)
        self.assertEqual(result.receipt_payload["review_state"], "pending_llm")
        self.assertNotIn(secret, str(result.receipt_payload))
        self.assertNotIn(secret, "\n".join(calls))

    def test_late_episode_admission_keeps_accepted_order_and_checks_source_bytes(self):
        from memory_growth import project_admissions
        a = {"event_id": "A-claim", "task_id": "A"}
        b = {"event_id": "B-claim", "task_id": "B"}
        ac = {"event_id": "A-close", "task_id": "A"}
        bc = {"event_id": "B-close", "task_id": "B"}
        before = b"original physical source\n"
        prior = {"growth_events": [a, ac], "growth_source_checkpoint": {
            "schema_version": 1, "source": "fixture:events", "byte_count": len(before),
            "sha256": hashlib.sha256(before).hexdigest()}}
        plan = project_admissions((a, b, ac, bc), prior_document=prior,
            source_id="fixture:events", source_bytes=before + b"append\n")
        self.assertEqual([e["event_id"] for e in plan.events], ["A-claim", "A-close", "B-claim", "B-close"])
        with self.assertRaisesRegex(ValueError, "append-only"):
            project_admissions((a, b, ac, bc), prior_document=prior,
                source_id="fixture:events", source_bytes=b"tampered source\n")

    def test_historical_completed_label_without_evidence_cannot_unlock_method_card(self):
        value = GrowthInput(task="新案例", summary="发现覆盖缺口",
            events=("user_confirmed_omission",), evidence_refs=("evidence:case-two",))
        answer = {field: "存在机制和验证路径" for field in REVIEW_FIELDS}
        answer.update(increment_state="validated", evidence_state="partial", outcome_state="unknown",
            pattern_key="coverage-gap", evidence_refs=["evidence:case-two"])
        history = ({"task_id": "TK-OLD", "task": "旧案例", "event": "close", "payload": {
            "review_state": "completed", "pattern_key": "coverage-gap"}},)
        result = review_task(value, task_id="TK-TWO", history=history,
            reviewer=lambda _: json.dumps(answer))
        self.assertEqual(result.receipt_payload["increment_state"], "candidate")
        self.assertEqual(result.receipt_payload["methodology_decision"], "暂缓")

    def test_ordinary_task_does_not_call_reviewer_and_has_explicit_unknown_outcome(self):
        calls = []
        result = review_task(
            GrowthInput(task="读取一行", summary="已返回", impact="ordinary", impact_reason="机械读取"),
            task_id="TK-ONE",
            history=(),
            reviewer=lambda prompt: calls.append(prompt),
        )
        self.assertEqual(calls, [])
        self.assertEqual(result.receipt_payload["review_state"], "not_required")
        self.assertEqual(result.receipt_payload["outcome_state"], "unknown")
        self.assertEqual(result.receipt_payload["classification_state"], "known")


if __name__ == "__main__":
    unittest.main()
