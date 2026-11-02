"""Shared month projection; task deduplication is not quality scoring."""
from __future__ import annotations
import calendar
from collections import Counter
from ._core import DEFAULT_RULES, known_growth_events, normalize_growth_event

SCHEMA_V2_START = "2026-08-17"

def summarize_month(
    receipts: list[dict],
    events: list[dict],
    *,
    month: str,
    rules: dict | None = None,
) -> dict:
    monthly_receipts = [
        row for row in receipts if str(row.get("timestamp", "")).startswith(month)
    ]
    legacy = [row for row in monthly_receipts if int(row.get("schema_version", 1)) < 2]
    v2 = [
        row
        for row in monthly_receipts
        if int(row.get("schema_version", 1)) >= 2 and row.get("task_id")
    ]
    latest_by_task: dict[str, dict] = {}
    for row in sorted(v2, key=lambda item: str(item.get("timestamp", ""))):
        latest_by_task[str(row["task_id"])] = row
    latest = list(latest_by_task.values())
    high_impact = [row for row in latest if (row.get("growth") or {}).get("impact") in {"high", "safety"}]
    review_required = [row for row in latest if (row.get("growth") or {}).get("review_required")]
    review_completed = [row for row in review_required if (row.get("growth") or {}).get("review_state") == "completed"]
    review_pending = [row for row in review_required if (row.get("growth") or {}).get("review_state") != "completed"]
    candidate_patterns = {
        str((row.get("growth") or {}).get("pattern_key"))
        for row in latest
        if str((row.get("growth") or {}).get("pattern_key", "")).strip()
    }
    promoted = [
        row
        for row in latest
        if (row.get("growth") or {}).get("methodology_decision") == "沉淀"
    ]
    monthly_events = [
        row for row in events if str(row.get("timestamp", "")).startswith(month)
    ]
    config = rules if rules is not None else DEFAULT_RULES
    unknown_events = [row for row in monthly_events if normalize_growth_event(str(row.get("event", "")), strict=False, config=config) not in known_growth_events(config)]
    events_by_task: dict[str, list[dict]] = {}
    for row in events:
        if str(row.get("timestamp", ""))[:7] > month:
            continue
        if row.get("task_id"):
            events_by_task.setdefault(str(row["task_id"]), []).append(row)
    active_tasks = []
    for task_rows in events_by_task.values():
        ordered = sorted(task_rows, key=lambda item: str(item.get("timestamp", "")))
        names = {str(row.get("event")) for row in ordered}
        if "claim" in names and "close" not in names:
            active_tasks.append(ordered[-1])
    return {
        "month": month,
        "legacy_receipts": len(legacy),
        "v2_receipts": len(v2),
        "v2_tasks": len(latest_by_task),
        "latest_receipts": latest,
        "high_impact_tasks": len(high_impact),
        "review_required_tasks": len(review_required),
        "review_completed_tasks": len(review_completed),
        "review_pending_tasks": len(review_pending),
        "review_insufficient_tasks": sum((row.get("growth") or {}).get("review_state") == "insufficient_evidence" for row in review_required),
        "unclassified_tasks": sum((row.get("growth") or {}).get("impact") == "unknown" for row in latest),
        "classification_unassessed_tasks": sum("classification_state" not in (row.get("growth") or {}) for row in latest),
        "source_latest_timestamp": max((str(row.get("timestamp", "")) for row in monthly_receipts), default="无"),
        "unrecognized_event_rows": len(unknown_events),
        "candidate_patterns": len(candidate_patterns),
        "methodology_promoted_tasks": len(promoted),
        "growth_events": len(monthly_events),
        "event_counts": dict(Counter(str(row.get("event")) for row in monthly_events)),
        "active_claims": len(active_tasks),
        "active_tasks": active_tasks,
    }

def _cell(value: object) -> str:
    if isinstance(value, list):
        value = ", ".join(str(item) for item in value)
    return str(value or "-").replace("|", "\\|").replace("\n", " ")

def render_report(
    summary: dict,
    *,
    generated_at: str,
    schema_start: str,
) -> str:
    month = summary["month"]
    year, month_number = (int(part) for part in month.split("-"))
    period_end = f"{month}-{calendar.monthrange(year, month_number)[1]:02d}"
    latest = summary["latest_receipts"]
    backlog = "存在待处理复盘" if summary["review_pending_tasks"] else "已登记复盘无待处理项（不代表触发覆盖充分）"
    task_rows = []
    for row in latest:
        growth = row.get("growth") or {}
        task_rows.append(
            "| {task_id} | {task} | {state} | {impact} | {triggers} | {review} | {method} |".format(
                task_id=_cell(row.get("task_id")),
                task=_cell(row.get("task")),
                state=_cell(row.get("state")),
                impact=_cell(growth.get("impact")),
                triggers=_cell(growth.get("trigger_codes")),
                review=_cell(growth.get("review_state")),
                method=_cell(growth.get("methodology_decision")),
            )
        )
    if not task_rows:
        task_rows.append("| - | 暂无 schema v2 已收工任务 | - | - | - | - | - |")

    pattern_rows = []
    for row in latest:
        growth = row.get("growth") or {}
        if not growth.get("pattern_key"):
            continue
        pattern_rows.append(
            "| {task_id} | {pattern} | {candidate} | {decision} |".format(
                task_id=_cell(row.get("task_id")),
                pattern=_cell(growth.get("pattern_key")),
                candidate=_cell(growth.get("methodology_candidate")),
                decision=_cell(growth.get("methodology_decision")),
            )
        )
    if not pattern_rows:
        pattern_rows.append("| - | - | 暂无候选 | 不适用 |")

    active_rows = [
        f"- `{_cell(row.get('task_id'))}` {_cell(row.get('task'))}"
        for row in summary["active_tasks"]
    ] or ["- 无"]

    return f"""---
title: {month} AI协作质量月度评估
schema_version: 2
status: 观察中
period_start: {schema_start}
period_end: {period_end}
generated_at: {generated_at}
source_mode: event-derived
---

# {month} AI 协作质量月度评估｜事件驱动 schema v2

## Executive Summary

- **新口径已建立，但当前只是运行基线。** schema v2 自 {schema_start} 起生效；截至 {generated_at}，有 {summary['v2_tasks']} 个唯一任务、{summary['v2_receipts']} 条 v2 收工回执。
- **重复收工不重复计样本。** 本报告以 `task_id` 为分母，每个任务只取最新回执；因此 {summary['v2_receipts']} 条回执只形成 {summary['v2_tasks']} 个任务样本。
- **{backlog}。** {summary['review_required_tasks']} 个任务需要复盘，{summary['review_completed_tasks']} 个已完成，{summary['review_pending_tasks']} 个尚待处理，其中 {summary['review_insufficient_tasks']} 个证据不足。
- **质量与结果证据尚需独立判定。** 任务数量不等于有效认知增量样本；未分类 {summary['unclassified_tasks']} 个，旧记录未执行新分类校验 {summary['classification_unassessed_tasks']} 个。

## 新口径从 {schema_start} 开始，旧数据只作背景

{month_number} 月共发现 {summary['legacy_receipts']} 条 legacy 回执。它们缺少稳定 `task_id` 或完整 `growth` 对象，因此不进入 schema v2 分母，也不用来计算复盘完成率和方法晋升率。旧回执继续保留，只用于历史反查。

| 指标 | 当前值 | 口径 | 当前判断 |
|---|---:|---|---|
| schema v2 唯一任务 | {summary['v2_tasks']} | 按 `task_id` 去重 | 不等于质量样本数 |
| schema v2 收工回执 | {summary['v2_receipts']} | 一个任务可多次收工 | 不作质量分母 |
| 高影响任务 | {summary['high_impact_tasks']} | 最新回执 `impact=high/safety` | 需规则触发证据 |
| 需复盘任务 | {summary['review_required_tasks']} | `review_required=true` | 必须有完成或待处理状态 |
| 已完成复盘 | {summary['review_completed_tasks']} | 任务级最新回执 | 仅代表复盘契约完成 |
| 待处理复盘 | {summary['review_pending_tasks']} | 需复盘但未 completed | 包含 pending_llm 与证据不足 |
| 证据不足 | {summary['review_insufficient_tasks']} | insufficient_evidence | 不计有效增量与方法晋升 |
| 影响未分类 | {summary['unclassified_tasks']} | impact=unknown | 不得按普通任务解释 |
| 历史分类未核验 | {summary['classification_unassessed_tasks']} | 缺少新分类标记 | 保留原始记录，不回填 |
| 未识别事件记录 | {summary['unrecognized_event_rows']} | 原文不在事件码配置中 | 需要审查，不静默忽略 |
| 方法模式候选 | {summary['candidate_patterns']} | 每任务最新 `pattern_key` | 不等于已验证 |
| 已晋升方法 | {summary['methodology_promoted_tasks']} | `methodology_decision=沉淀` | 晋升后仍为待复验 |

## schema v2 任务级样本

| task_id | 任务 | 状态 | 影响 | 触发码 | 复盘 | 方法闸门 |
|---|---|---|---|---|---|---|
{chr(10).join(task_rows)}

**含义：** 本表展示账本运行状态。未完成复盘、未知分类或缺少独立判断时，不能据此宣称成长闭环或比较 Agent 效果。

## 方法候选只做任务级去重

| task_id | pattern_key | 候选方法 | 闸门决定 |
|---|---|---|---|
{chr(10).join(pattern_rows)}

同一任务多次收工不能被当作多个独立案例。只有相同模式在不同 `task_id` 中出现，或命中安全边界单例条件，才可进入“沉淀”。

## 本月剩余时间只做真实运行验证

1. 每个任务以确定性事件触发，不为凑样本人工制造复盘。
2. 持续观察 `pending_llm` 比例、误触发、漏触发和重复收工的任务级去重。
3. 出现第二个独立案例时，核对方法卡是否自动生成、登记索引并保留“待复验”状态。
4. 月末只在有用户判定、独立审查或真实结果时计算有效增量；用户沉默仍为 unknown。

## 待处理任务

{chr(10).join(active_rows)}

## 进一步问题

- 规则是否产生无效触发，或在用户明确指出遗漏时未触发？
- 同一任务的后续收工是否包含新证据？若没有，是否应避免重复调用 LLM？
- 方法卡晋升后，新未见变体是否真正支持其有效性？

## 限制与假设

- schema v2 自 {schema_start} 才开始，当前观察窗口和样本量都很小。
- legacy 数据不能可靠反推出完整 `growth` 字段，因此不回填、不估算。
- 本报告不展示模型排名，不把 Agent 自评、用户沉默或工程测试通过当作认知增量有效。
- 当前样本量不支持图表趋势，因此使用精确表格而非制造无意义的可视化。

## 数据源与可复现性

- 收工回执：`{summary.get('receipts_source', 'in-memory receipts')}`
- 成长事件：`{summary.get('events_source', 'in-memory events')}`
- 生成模块：`memory_growth.reporting`
- 口径：回执按月筛选；`schema_version>=2`才进入 v2；按 `task_id` 取最新回执；方法候选仅读取每任务最新 `pattern_key`。
- 本月源回执最新时间：{summary['source_latest_timestamp']}。
- 输入文件 SHA256：{summary.get('source_hashes', '内存输入；无文件指纹')}。
"""

def affected_report_months(receipts: list[dict], receipt_id: str) -> list[str]:
    by_id = {row.get("receipt_id"): row for row in receipts}
    row = by_id[receipt_id]
    year, month = map(int, str(row["timestamp"])[:7].split("-"))
    previous = f"{year if month > 1 else year - 1:04d}-{month - 1 if month > 1 else 12:02d}"
    months = {previous}
    visited = set()
    while row and row.get("receipt_id") not in visited:
        visited.add(row.get("receipt_id"))
        months.add(str(row["timestamp"])[:7])
        row = by_id.get(row.get("supersedes_receipt_id"))
    return sorted(months)

def default_schema_start(month: str) -> str:
    month_start = f"{month}-01"
    return max(month_start, SCHEMA_V2_START)
