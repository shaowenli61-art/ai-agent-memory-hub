"""Shared growth Module used by closure and feedback Adapters."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from ._core import GrowthInput, GrowthReview, TriggerDecision
from ._core import evaluate_trigger, run_growth_review, promotion_for_history
from ._admissions import AdmissionPlan, project_admissions

__version__ = "0.3.0"


@dataclass(frozen=True)
class GrowthAssessment:
    decision: TriggerDecision
    review: GrowthReview | None
    receipt_payload: dict


def review_task(value: GrowthInput, *, task_id: str, history: tuple[dict, ...] = (),
                rules: dict | None = None, reviewer=None) -> GrowthAssessment:
    """Assess one Episode; only an injected reviewer may call an external Agent."""
    if not task_id.strip():
        raise ValueError("growth assessment requires task_id")
    decision = evaluate_trigger(value, config=rules)
    if decision.review_required:
        def missing_reviewer(_):
            raise RuntimeError("LLM reviewer not configured")
        review = run_growth_review(value, decision, reviewer=reviewer or missing_reviewer)
        review = promotion_for_history(review, history=history, current_task_id=task_id,
            current_task=value.task, current_events=value.events, config=rules)
        return GrowthAssessment(decision, review, {**asdict(decision), **asdict(review),
            "core_version": __version__, "protocol_contract": "3.3.0"})
    payload = {
        "core_version": __version__, "protocol_contract": "3.3.0",
        **asdict(decision),
        "review_state": "not_required", "increment_state": "none",
        "increment_summary": "", "evidence_state": "not_required",
        "decision_effect": "", "outcome_state": "unknown", "failure_type": "",
        "missed_variable": "", "earliest_available_evidence": "",
        "why_not_triggered": "", "new_stop_rule": "", "pattern_key": "",
        "methodology_candidate": "", "methodology_decision": "不适用",
        "methodology_reason": "未命中成长复盘触发规则。",
    }
    return GrowthAssessment(decision, None, payload)
