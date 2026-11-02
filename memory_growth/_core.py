"""Portable deterministic growth rules; no private paths, writes or Agent configuration."""
from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, replace
import json

DEFAULT_RULES = json.loads("{\n  \"schema_version\": 1,\n  \"hard_event_rules\": [\n    {\n      \"event\": \"repair_failed\",\n      \"min_count\": 2,\n      \"trigger_code\": \"REPEATED_REPAIR_FAILURE\"\n    },\n    {\n      \"event\": \"user_confirmed_omission\",\n      \"min_count\": 1,\n      \"trigger_code\": \"USER_CONFIRMED_OMISSION\"\n    },\n    {\n      \"event\": \"key_assumption_overturned\",\n      \"min_count\": 1,\n      \"trigger_code\": \"KEY_ASSUMPTION_OVERTURNED\"\n    },\n    {\n      \"event\": \"major_rework\",\n      \"min_count\": 1,\n      \"trigger_code\": \"MAJOR_REWORK\"\n    },\n    {\n      \"event\": \"production_incident\",\n      \"min_count\": 1,\n      \"trigger_code\": \"PRODUCTION_INCIDENT\"\n    },\n    {\n      \"event\": \"user_requested_retrospective\",\n      \"min_count\": 1,\n      \"trigger_code\": \"USER_OVERRIDE\"\n    }\n  ],\n  \"impact_event_rules\": {\n    \"production_state\": \"PRODUCTION_STATE\",\n    \"privacy_compliance\": \"PRIVACY_COMPLIANCE\",\n    \"metric_definition\": \"METRIC_DEFINITION\",\n    \"long_term_architecture\": \"LONG_TERM_ARCHITECTURE\",\n    \"external_result\": \"EXTERNAL_RESULT\",\n    \"money_contract\": \"MONEY_CONTRACT\",\n    \"safety_boundary\": \"SAFETY_BOUNDARY\"\n  },\n  \"methodology_promotion\": {\n    \"independent_evidence_required\": 2,\n    \"safety_boundary_allows_single_case\": true\n  }\n}")

@dataclass(frozen=True)
class GrowthInput:
    task: str
    summary: str
    events: tuple[str, ...] = ()
    impact: str = "unknown"
    impact_reason: str = ""
    evidence_refs: tuple[str, ...] = ()


@dataclass(frozen=True)
class TriggerDecision:
    scope: str
    impact: str
    trigger_codes: tuple[str, ...]
    review_required: bool
    classification_state: str = "unknown"
    impact_reason: str = ""
    unrecognized_events: tuple[str, ...] = ()


@dataclass(frozen=True)
class GrowthReview:
    review_state: str
    increment_state: str
    increment_summary: str
    evidence_state: str
    decision_effect: str
    outcome_state: str
    failure_type: str
    missed_variable: str
    earliest_available_evidence: str
    why_not_triggered: str
    new_stop_rule: str
    pattern_key: str
    methodology_candidate: str
    methodology_decision: str
    methodology_reason: str
    evidence_refs: tuple[str, ...] = ()

def known_growth_events(config: dict) -> set[str]:
    return {"claim", "close"} | set(config.get("impact_event_rules", {})) | {rule["event"] for rule in config.get("hard_event_rules", [])}

def normalize_growth_event(event: str, *, strict: bool = True, config: dict | None = None) -> str:
    config = DEFAULT_RULES if config is None else config
    known = known_growth_events(config)
    normalized = event.strip().lower()
    if normalized not in known and strict:
        raise ValueError(f"unknown growth event: {event!r}; use an event code and put details in notes")
    return normalized if normalized in known else event

def evaluate_trigger(value: GrowthInput, config: dict | None = None) -> TriggerDecision:
    config = DEFAULT_RULES if config is None else config
    if value.impact not in {"unknown", "ordinary", "high", "safety"}:
        raise ValueError("invalid growth impact")
    if value.impact != "unknown" and not value.impact_reason.strip():
        raise ValueError("explicit growth impact requires impact_reason")
    events = tuple(normalize_growth_event(event, strict=False, config=config) for event in value.events)
    counts = Counter(events)
    unrecognized = tuple(dict.fromkeys(event for event in events if event not in known_growth_events(config)))
    trigger_codes: list[str] = []
    for rule in config.get("hard_event_rules", []):
        if counts[str(rule["event"])] >= int(rule.get("min_count", 1)):
            trigger_codes.append(str(rule["trigger_code"]))
    for event, trigger_code in config.get("impact_event_rules", {}).items():
        if counts[event] > 0:
            trigger_codes.append(str(trigger_code))
    required = bool(trigger_codes)
    impact = value.impact
    if required:
        impact = "safety" if "safety_boundary" in counts else "high"
    if unrecognized:
        impact = "unknown"
    return TriggerDecision(
        scope="light" if required else "none",
        impact=impact,
        trigger_codes=tuple(trigger_codes),
        review_required=required,
        classification_state="known" if impact != "unknown" else "unknown",
        impact_reason=value.impact_reason or (", ".join(trigger_codes) if required else "未提供影响分类"),
        unrecognized_events=unrecognized,
    )


REVIEW_FIELDS = (
    "increment_state",
    "increment_summary",
    "evidence_state",
    "decision_effect",
    "outcome_state",
    "failure_type",
    "missed_variable",
    "earliest_available_evidence",
    "why_not_triggered",
    "new_stop_rule",
    "pattern_key",
    "methodology_candidate",
)

def build_review_prompt(value: GrowthInput, decision: TriggerDecision) -> str:
    schema = {field: "必填字符串；证据不足时填 unknown" for field in REVIEW_FIELDS}
    schema["evidence_state"] = "verified | partial | unknown"
    schema["outcome_state"] = "unknown | pending | recovered | positive | neutral | negative | unattributed"
    schema["evidence_refs"] = list(value.evidence_refs)
    evidence = {
        "task": value.task,
        "summary": value.summary,
        "events": value.events,
        "trigger_codes": decision.trigger_codes,
        "evidence_refs": value.evidence_refs,
    }
    return (
        "你是成长型 AI 协作的事后复盘员。只能根据下列证据识别遗漏、最早证据和新的停止规则；"
        "不得声称方法已被验证，不得评定长期有效次数。只输出一个 JSON 对象，不要 Markdown。\n"
        "下方是从任务记录提取的授权证据包，不要要求原始对话。"
        "若某字段仍无法判定，必须填字面值 unknown；"
        "不得改用 error、status、required_input 等其他字段。\n"
        "evidence_refs只能引用证据包已列出的来源，不得编造文件；verified只表示本次记录有依据，不表示方法长期有效。\n"
        f"输出字段：{json.dumps(schema, ensure_ascii=False)}\n"
        f"证据：{json.dumps(evidence, ensure_ascii=False)}"
    )

def run_growth_review(
    value: GrowthInput,
    decision: TriggerDecision,
    *,
    reviewer,
) -> GrowthReview:
    if not decision.review_required:
        raise ValueError("growth review requires a triggered task")
    prompt = build_review_prompt(value, decision)
    data: dict | None = None
    last_error: Exception | None = None
    for attempt in range(2):
        try:
            try:
                raw = reviewer(prompt)
            except Exception as adapter_error:
                # External stderr can contain credentials; neither receipts nor
                # corrective prompts may retain arbitrary Adapter exception text.
                raise RuntimeError("reviewer unavailable: " + type(adapter_error).__name__) from None
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError("growth review must be a JSON object")
            missing = [field for field in REVIEW_FIELDS if not isinstance(data.get(field), str) or not data[field].strip()]
            if missing:
                raise ValueError("growth review fields incomplete: " + ", ".join(missing))
            if data["evidence_state"] not in {"verified", "partial", "unknown"}:
                raise ValueError("invalid evidence_state")
            if data["outcome_state"] not in {"unknown", "pending", "recovered", "positive", "neutral", "negative", "unattributed"}:
                raise ValueError("invalid outcome_state")
            if data["increment_state"] not in {"candidate", "unknown", "none", "validated"}:
                raise ValueError("invalid increment_state")
            refs = data.get("evidence_refs", list(value.evidence_refs))
            if not isinstance(refs, list) or any(not isinstance(ref, str) or not ref.strip() for ref in refs):
                raise ValueError("evidence_refs must be a list of nonempty strings")
            if not set(refs).issubset(value.evidence_refs):
                raise ValueError("evidence_refs contains unauthorized sources")
            break
        except Exception as exc:
            last_error = exc
            data = None
            prompt = (
                build_review_prompt(value, decision)
                + f"\n上一次输出不合格，缺失或错误：{exc}。"
                + "请补齐所有字段，仍只输出 JSON。"
            )
    if data is None:
        return GrowthReview(
            review_state="pending_llm",
            increment_state="unknown",
            increment_summary="",
            evidence_state="pending",
            decision_effect="",
            outcome_state="unknown",
            failure_type="",
            missed_variable="",
            earliest_available_evidence="",
            why_not_triggered="",
            new_stop_rule="",
            pattern_key="",
            methodology_candidate="",
            methodology_decision="暂缓",
            methodology_reason=f"LLM 复盘未完成，保留待处理事件：{last_error}",
        )
    essential = ("increment_summary", "decision_effect", "earliest_available_evidence", "new_stop_rule", "pattern_key", "methodology_candidate")
    sufficient = bool(refs) and data["evidence_state"] != "unknown" and all(_meaningful(data[field]) for field in essential)
    fields = {field: data[field].strip() for field in REVIEW_FIELDS if field != "increment_state"}
    if not sufficient:
        fields.update(pattern_key="", methodology_candidate="")
    return GrowthReview(
        review_state="completed" if sufficient else "insufficient_evidence",
        increment_state="candidate" if sufficient else "unknown",
        methodology_decision="暂缓",
        methodology_reason="首次候选仅记录为待验证方法，不由复盘 Agent 自行晋升。" if sufficient else "证据不足；不计有效增量，不进入方法晋升。",
        evidence_refs=tuple(refs),
        **fields,
    )

def _meaningful(value: str) -> bool:
    return value.strip().lower() not in {"", "unknown", "none", "null", "n/a", "[]", "{}", "-", "无", "未知", "未验证", "待验证", "不确定"}

def promotion_for_history(
    review: GrowthReview,
    *,
    history: tuple[dict, ...],
    current_task_id: str,
    current_events: tuple[str, ...],
    current_task: str = "",
    config: dict | None = None,
) -> GrowthReview:
    if review.review_state != "completed" or not _meaningful(review.pattern_key):
        return review
    config = DEFAULT_RULES if config is None else config
    promotion = config.get("methodology_promotion", {})
    # A completed label is not evidence. Legacy rows without traceable support
    # remain readable, but cannot silently unlock a new methodology card.
    if not _review_has_support(asdict(review)):
        return replace(review, methodology_decision="暂缓",
            methodology_reason="缺少可追溯复盘证据；不计独立方法案例。")
    latest_by_task = {}
    for row in history:
        identity = row.get("task_id")
        if isinstance(identity, str) and identity.strip() and row.get("event", "close") == "close":
            latest_by_task[identity] = row
    prior_task_ids = {
        str(row.get("task_id"))
        for row in latest_by_task.values()
        if row.get("task_id") != current_task_id
        and (not current_task or row.get("task") != current_task)
        and row.get("identity_state") != "identity_unresolved"
        and (row.get("payload") or {}).get("identity_state") != "identity_unresolved"
        and (row.get("payload") or {}).get("review_state") == "completed"
        and (row.get("payload") or {}).get("pattern_key") == review.pattern_key
        and _review_has_support(row.get("payload") or {})
    }
    occurrences = len(prior_task_ids) + 1
    safety_override = (
        "safety_boundary" in current_events
        and bool(promotion.get("safety_boundary_allows_single_case"))
    )
    required = int(promotion.get("independent_evidence_required", 2))
    if occurrences < required and not safety_override:
        return replace(
            review,
            methodology_reason=(
                f"当前仅 {occurrences} 个独立任务命中该模式；"
                f"达到 {required} 个前保持暂缓。"
            ),
        )
    reason = (
        "命中安全边界单例晋升条件。"
        if safety_override and occurrences < required
        else f"已有 {occurrences} 个独立任务命中同一模式。"
    )
    return replace(review, methodology_decision="沉淀", methodology_reason=reason)


def _review_has_support(value: dict) -> bool:
    refs = value.get("evidence_refs")
    return (value.get("review_state") == "completed"
        and value.get("evidence_state") in {"partial", "verified"}
        and isinstance(refs, (list, tuple)) and bool(refs)
        and all(isinstance(ref, str) and _meaningful(ref) for ref in refs))
