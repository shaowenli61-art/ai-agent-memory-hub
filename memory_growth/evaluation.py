"""Durable evaluation intake and protected human sections; never self-score."""
from __future__ import annotations
import datetime
import hashlib
import json
import re
from pathlib import Path
from scripts.file_write_guard import safe_write_text

CANDIDATE_HEADING = "## 自动候选池"
CANDIDATE_HEADER = "| 日期 | 任务 | 主入口 | 动作 | 自动判断 | 触发依据 | 样本状态 | 证据 |"
CANDIDATE_SEPARATOR = "| --- | --- | --- | --- | --- | --- | --- | --- |"

HIGH_VALUE_SIGNALS = (
    "决策", "设计", "架构", "分析", "诊断", "审计", "评估", "规划",
    "计划", "MVP", "口径", "高风险", "治理", "重构", "复盘", "方案",
)
ORDINARY_SIGNALS = ("翻译", "润色", "格式", "改名", "机械整理", "机械修改")

def observation_period(content: str) -> tuple[bool, str, str]:
    frontmatter = re.match(r"\A---\s*\n(.*?)\n---(?:\n|$)", content, re.S)
    if frontmatter:
        fields = dict(re.findall(r"^([a-z_]+):\s*[\"']?([^\n\"']+)", frontmatter.group(1), re.M))
        if "status" in fields:
            return fields["status"].strip() == "观察中", fields.get("period_start", "").strip(), fields.get("period_end", "").strip()
    match = re.search(r"观察期\s*(\d{4}-\d{2}-\d{2})\s*至\s*(\d{4}-\d{2}-\d{2})", content)
    return "状态：观察中" in content, match.group(1) if match else "", match.group(2) if match else ""

def evaluation_ledger_path(path: Path) -> Path:
    return Path(path).with_suffix(".events.jsonl")

def read_evaluation_events(path: Path) -> list[dict]:
    ledger = evaluation_ledger_path(path)
    if not ledger.exists():
        return []
    return [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines() if line.strip()]

def _append_evaluation_event(path: Path, event: dict, agent: str, *, writer=None) -> None:
    ledger = evaluation_ledger_path(path)
    payload = json.dumps(event, ensure_ascii=False, sort_keys=True)
    event_id = "AE-" + hashlib.sha256(payload.encode("utf-8")).hexdigest()
    if any(row.get("event_id") == event_id for row in read_evaluation_events(path)):
        return
    row = {"schema_version": 1, "event_id": event_id, **event}
    old = ledger.read_bytes().decode("utf-8") if ledger.exists() else ""
    (writer or safe_write_text)(ledger, old + json.dumps(row, ensure_ascii=False) + "\n", agent, "append AI evaluation evidence")

def preserve_evaluation_sections(path: Path, content: str, agent: str, *, writer=None) -> None:
    sections = {}
    for match in re.finditer(r"^## ([^\n]+)\n.*?(?=^## |\Z)", content, re.M | re.S):
        if match.group(1).startswith(("真实任务汇总", "自动候选池", "人工", "用户反馈", "独立评审", "结果跟踪", "结果回看")):
            sections[match.group(1)] = match.group(0).rstrip()
    if not sections:
        return
    snapshots = [row for row in read_evaluation_events(path) if row.get("event_type") == "evaluation_snapshot"]
    if snapshots and snapshots[-1]["sections"] == sections:
        return
    _append_evaluation_event(path, {
        "event_type": "evaluation_snapshot", "sections": sections,
        "timestamp": datetime.datetime.now().astimezone().isoformat(),
    }, agent, writer=writer)

def project_evaluation_events(content: str, events: list[dict]) -> str:
    snapshot_index = -1
    for i, row in enumerate(events):
        if row.get("event_type") == "evaluation_snapshot":
            snapshot_index = i
    if snapshot_index >= 0:
        content = content.rstrip() + "\n\n" + "\n\n".join(events[snapshot_index]["sections"].values()) + "\n"
    if events and "## 真实任务汇总" not in content:
        content += "\n## 真实任务汇总\n\n| 序号 | 任务 | 主入口 | 层级 | 基础质量/10 | 有效独立见解 | 有效异议 | 无效异议 | 是否改判 | L3状态 | 净协作价值 | 证据 |\n|---:|---|---|---|---:|---:|---:|---:|---|---|---|---|\n"
    for row in events:
        if row.get("event_type") == "intake":
            content = record_event(content, **{key: row[key] for key in (
                "event_date", "task", "agent", "action", "evidence", "notes", "override", "retrospective",
            )})
    return content

def select_active_evaluation(paths: list[Path], event_date: str) -> Path | None:
    """按文档内观察期选择活动评估，允许观察期跨自然月。"""
    undated_active = None
    for path in sorted(paths, reverse=True):
        content = path.read_text(encoding="utf-8")
        active, start, end = observation_period(content)
        if not active:
            continue
        if start and end and start <= event_date <= end:
            return path
        if not start and not end and undated_active is None:
            undated_active = path
    return undated_active

def classify_task(task: str, notes: str, override: str = "auto") -> tuple[bool, str]:
    """判断任务是否自动进入正式 L0 样本，并返回可审计理由。"""
    if override == "include":
        return True, "显式纳入"
    if override == "exclude":
        return False, "显式排除"

    text = f"{task} {notes}"
    high_hits = [signal for signal in HIGH_VALUE_SIGNALS if signal in text]
    if high_hits:
        return True, f"高价值信号：{'、'.join(high_hits)}"

    ordinary_hits = [signal for signal in ORDINARY_SIGNALS if signal in text]
    if ordinary_hits:
        return False, f"普通任务信号：{'、'.join(ordinary_hits)}"
    return False, "未命中高价值信号"

def _escape_cell(value: str) -> str:
    return str(value or "-").replace("|", "\\|").replace("\r", " ").replace("\n", " ").strip()

def _cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]

def _candidate_state(action: str, included: bool, retrospective: bool) -> str:
    if retrospective:
        return "回顾性候选（不可计L1）"
    if action == "claim":
        return "进行中-待评估"
    if included:
        return "待评分"
    return "已排除-普通任务"

def _ensure_candidate_section(content: str) -> str:
    if CANDIDATE_HEADING in content:
        return content
    return content.rstrip() + f"\n\n{CANDIDATE_HEADING}\n\n{CANDIDATE_HEADER}\n{CANDIDATE_SEPARATOR}\n"

def _upsert_candidate(content: str, row: list[str]) -> str:
    content = _ensure_candidate_section(content)
    lines = content.splitlines()
    heading_idx = lines.index(CANDIDATE_HEADING)
    table_start = next(
        i for i in range(heading_idx + 1, len(lines))
        if lines[i].startswith("| 日期 |")
    )
    table_end = len(lines)
    for i in range(table_start + 2, len(lines)):
        if lines[i].startswith("## "):
            table_end = i
            break

    rendered = "| " + " | ".join(_escape_cell(value) for value in row) + " |"
    key = (row[0], row[1])
    for i in range(table_start + 2, table_end):
        if not lines[i].startswith("|"):
            continue
        cells = _cells(lines[i])
        if len(cells) >= 2 and (cells[0], cells[1]) == key:
            lines[i] = rendered
            return "\n".join(lines) + "\n"

    lines.insert(table_end, rendered)
    return "\n".join(lines) + "\n"

def _promote_to_l0(content: str, task: str, agent: str, evidence: str) -> str:
    lines = content.splitlines()
    try:
        heading_idx = lines.index("## 真实任务汇总")
    except ValueError:
        return content

    table_start = next(
        (i for i in range(heading_idx + 1, len(lines)) if lines[i].startswith("| 序号 |")),
        -1,
    )
    if table_start == -1:
        return content

    table_end = len(lines)
    for i in range(table_start + 2, len(lines)):
        if lines[i].startswith("## "):
            table_end = i
            break

    for i in range(table_start + 2, table_end):
        cells = _cells(lines[i]) if lines[i].startswith("|") else []
        if len(cells) >= 2 and cells[1] == task:
            return content

    for i in range(table_start + 2, table_end):
        if not lines[i].startswith("|"):
            continue
        cells = _cells(lines[i])
        if len(cells) >= 12 and not cells[1]:
            cells = cells[:12]
            cells[1] = task
            cells[2] = agent
            cells[3] = "L0（自动入流）"
            cells[8] = "否"
            cells[9] = "未进入"
            cells[10] = "等待评估"
            cells[11] = evidence
            lines[i] = "| " + " | ".join(cells) + " |"
            return "\n".join(lines) + "\n"
    # IMP-6：无空占位行时扩容追加新行，避免正式样本表填满后停止增长
    max_seq = 0
    for i in range(table_start + 2, table_end):
        if not lines[i].startswith("|"):
            continue
        cells = _cells(lines[i])
        if cells and cells[0].isdigit():
            max_seq = max(max_seq, int(cells[0]))
    new_row = "| " + " | ".join([
        str(max_seq + 1),
        _escape_cell(task),
        _escape_cell(agent),
        "L0（自动入流）",
        "",
        "",
        "",
        "",
        "否",
        "未进入",
        "等待评估",
        _escape_cell(evidence),
    ]) + " |"
    lines.insert(table_end, new_row)
    return "\n".join(lines) + "\n"

def record_event(
    content: str,
    *,
    event_date: str,
    task: str,
    agent: str,
    action: str,
    evidence: str,
    notes: str,
    override: str = "auto",
    retrospective: bool = False,
) -> str:
    """把一个任务生命周期事件写入月度候选池，必要时晋级正式 L0。"""
    if retrospective:
        existing = next(
            (
                row for row in _candidate_rows(content)
                if row["date"] == event_date and row["task"] == task
            ),
            None,
        )
        if existing and existing["state"] != "回顾性候选（不可计L1）":
            return content
    included, reason = classify_task(task, notes, override)
    state = _candidate_state(action, included, retrospective)
    decision = "纳入" if included else "排除"
    updated = _upsert_candidate(
        content,
        [event_date, task, agent, action, decision, reason, state, evidence],
    )
    if included and action in {"complete", "archive", "close"} and not retrospective:
        updated = _promote_to_l0(updated, task, agent, evidence)
    return updated

def _candidate_rows(content: str) -> list[dict[str, str]]:
    if CANDIDATE_HEADING not in content:
        return []
    lines = content.splitlines()
    heading_idx = lines.index(CANDIDATE_HEADING)
    table_start = next(
        (i for i in range(heading_idx + 1, len(lines)) if lines[i].startswith("| 日期 |")),
        -1,
    )
    if table_start == -1:
        return []
    rows = []
    for line in lines[table_start + 2:]:
        if line.startswith("## "):
            break
        if not line.startswith("|"):
            continue
        cells = _cells(line)
        if len(cells) >= 8:
            rows.append(dict(zip(
                ("date", "task", "agent", "action", "decision", "reason", "state", "evidence"),
                cells[:8],
            )))
    return rows

def record_event_file(
    path: Path,
    *,
    event_date: str,
    task: str,
    agent: str,
    action: str,
    evidence: str,
    notes: str,
    override: str = "auto",
    retrospective: bool = False,
    task_id: str = "",
    writer=None,
) -> bool:
    """安全写入一个事件；不存在活动观察时保持无操作。"""
    path = Path(path)
    content = path.read_text(encoding="utf-8") if path.exists() else f"---\nstatus: 观察中\nperiod_start: {event_date[:7]}-01\n---\n\n# AI 协作质量月度评估\n"
    active, start, end = observation_period(content)
    if not active:
        return False
    if (start and event_date < start) or (end and event_date > end):
        return False
    preserve_evaluation_sections(path, content, agent, writer=writer)
    _append_evaluation_event(path, {
        "event_type": "intake", "task_id": task_id, "event_date": event_date,
        "task": task, "agent": agent, "action": action, "evidence": evidence,
        "notes": notes, "override": override, "retrospective": retrospective,
    }, agent, writer=writer)
    updated = record_event(
        content,
        event_date=event_date,
        task=task,
        agent=agent,
        action=action,
        evidence=evidence,
        notes=notes,
        override=override,
        retrospective=retrospective,
    )
    if updated == content:
        return False
    (writer or safe_write_text)(path, updated, agent, f"AI协作评估入流 {action}: {task}")
    return True
