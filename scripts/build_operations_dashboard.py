from __future__ import annotations

import argparse
import json
import re
import shutil
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote

try:
    from scripts.project_activity import discover_projects
    from scripts.project_brief import enrich_briefs, no_remaining
    from scripts.project_lifecycle import apply_lifecycle
    from scripts.work_cycle import enrich_work_cycle
except ModuleNotFoundError:
    import importlib.util
    lifecycle_spec = importlib.util.spec_from_file_location('operations_project_lifecycle', Path(__file__).with_name('project_lifecycle.py'))
    lifecycle_module = importlib.util.module_from_spec(lifecycle_spec)
    lifecycle_spec.loader.exec_module(lifecycle_module)
    apply_lifecycle = lifecycle_module.apply_lifecycle
    activity_spec = importlib.util.spec_from_file_location('operations_project_activity', Path(__file__).with_name('project_activity.py'))
    activity_module = importlib.util.module_from_spec(activity_spec)
    activity_spec.loader.exec_module(activity_module)
    discover_projects = activity_module.discover_projects
    brief_spec = importlib.util.spec_from_file_location('operations_project_brief', Path(__file__).with_name('project_brief.py'))
    brief_module = importlib.util.module_from_spec(brief_spec)
    brief_spec.loader.exec_module(brief_module)
    enrich_briefs = brief_module.enrich_briefs
    no_remaining = brief_module.no_remaining
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    from work_cycle import enrich_work_cycle


COMPLETED_STATUS_MARKERS = ("已完成", "阶段完成", "已终止")
MEETING_EXCLUDES = ("-原文转写", "-压缩稿")
PLAN_CANDIDATE_SECTIONS = ("建议推进", "下一步", "待办", "后续", "未完成")
PLAN_COMPLETED_MARKERS = ("已完成", "阶段完成", "已终止")
COMPLETED_FOLLOWUP_EXCLUDES = (
    "等待用户",
    "用户阅读",
    "用户体验",
    "用户按",
    "无",
    "没有",
    "不存在",
    "本次不",
)
PORTFOLIO_DOMAINS = {
    "经营分析与数据": (
        "销售看板Skill",
        "生产数据分析",
        "月度经营分析",
        "园艺项目",
        "农业种植系统",
        "自建数据分析Agent",
        "示例企业企业销售问答知识库",
        "客户经营本体试点",
        "示例企业数据底座梳理",
        "示例企业公司业务语义层",
    ),
    "AI 系统与 Agent": (
        "AI助手记忆中枢",
        "思维助手",
        "AIRI岗位数字人",
        "数字人智能体",
        "工程师",
        "项目招投标分析工具",
        "AI增强开发",
        "维修工",
    ),
    "产品、学习与内容": (
        "寓言学习小程序",
        "AI赋能培训",
        "示例产品官网",
        "示例研究研究与Agent落地",
        "小红书内容提取",
        "示例企业间AI合作",
    ),
    "知识与能力建设": (
        "方法论沉淀体系建设",
        "Claude 技能学习基地",
        "Claude code 汇报工作",
    ),
}


@dataclass(frozen=True)
class SourceState:
    label: str
    path: Path
    modified_at: datetime
    age_days: int
    stale: bool


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def markdown_tables(text: str) -> list[list[dict[str, str]]]:
    lines = text.splitlines()
    tables: list[list[dict[str, str]]] = []
    index = 0
    while index + 1 < len(lines):
        header = lines[index].strip()
        divider = lines[index + 1].strip()
        if header.startswith("|") and divider.startswith("|") and re.fullmatch(
            r"\|?[\s:|\-]+\|?", divider
        ):
            headers = split_table_row(header)
            rows: list[dict[str, str]] = []
            index += 2
            while index < len(lines) and lines[index].strip().startswith("|"):
                values = split_table_row(lines[index].strip())
                if len(values) < len(headers):
                    values.extend([""] * (len(headers) - len(values)))
                rows.append(dict(zip(headers, values[: len(headers)])))
                index += 1
            if rows:
                tables.append(rows)
            continue
        index += 1
    return tables


def split_table_row(line: str) -> list[str]:
    raw = line.strip()
    if raw.startswith("|"):
        raw = raw[1:]
    if raw.endswith("|"):
        raw = raw[:-1]
    cells: list[str] = []
    current: list[str] = []
    wikilink_depth = 0
    index = 0
    while index < len(raw):
        pair = raw[index : index + 2]
        if pair == "[[":
            wikilink_depth += 1
            current.append(pair)
            index += 2
            continue
        if pair == "]]" and wikilink_depth:
            wikilink_depth -= 1
            current.append(pair)
            index += 2
            continue
        if raw[index] == "|" and wikilink_depth == 0:
            cells.append("".join(current).strip())
            current = []
        else:
            current.append(raw[index])
        index += 1
    cells.append("".join(current).strip())
    return cells


def table_with_columns(text: str, required: Iterable[str]) -> list[dict[str, str]]:
    required_set = set(required)
    for table in markdown_tables(text):
        if table and required_set.issubset(table[0].keys()):
            return table
    return []


def clean_markdown(value: str) -> str:
    value = value.replace("**", "").replace("`", "")
    value = re.sub(r"\[\[([^\]|]+)\|([^\]]+)\]\]", r"\2", value)
    value = re.sub(r"\[\[([^\]]+)\]\]", r"\1", value)
    return value.strip()


def extract_wikilink(value: str) -> str | None:
    match = re.search(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]", value)
    return match.group(1).strip() if match else None


def parse_frontmatter(text: str) -> dict[str, Any]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    data: dict[str, Any] = {}
    current_list: str | None = None
    for line in lines[1:]:
        if line.strip() == "---":
            break
        list_match = re.match(r"^\s+-\s+(.+)$", line)
        if list_match and current_list:
            data.setdefault(current_list, []).append(list_match.group(1).strip())
            continue
        pair = re.match(r"^([^:#][^:]*):\s*(.*)$", line)
        if not pair:
            continue
        key, raw_value = pair.group(1).strip(), pair.group(2).strip()
        if not raw_value:
            data[key] = []
            current_list = key
        else:
            data[key] = raw_value.strip('"')
            current_list = None
    return data


def parse_date(value: str, fallback: datetime) -> datetime:
    match = re.search(r"(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})", value)
    if not match:
        return fallback
    year, month, day = (int(part) for part in match.groups())
    return datetime(year, month, day, tzinfo=fallback.tzinfo)


def owner_mentions_alias(owner: str, alias: str) -> bool:
    pattern = rf"(?:^|[/+、，,\s]){re.escape(alias)}(?:$|[/+、，,（(\s])"
    return re.search(pattern, owner) is not None


def obsidian_link(vault_root: Path, path: Path, label: str | None = None) -> str:
    relative = path.relative_to(vault_root).as_posix()
    target = f"obsidian://open?vault={quote(vault_root.name)}&file={quote(relative)}"
    return f"[{label or path.stem}]({target})"


def evidence_target(path: Path, vault_roots: Iterable[Path]) -> dict[str, Any]:
    resolved = path.resolve()
    uri = ""
    for vault_root in vault_roots:
        try:
            relative = resolved.relative_to(vault_root.resolve()).as_posix()
        except ValueError:
            continue
        uri = f"obsidian://open?vault={quote(vault_root.name)}&file={quote(relative)}"
        break
    return {
        "label": resolved.stem,
        "path": str(resolved),
        "uri": uri,
        "exists": resolved.exists(),
        "modified_at": (
            datetime.fromtimestamp(resolved.stat().st_mtime).astimezone().isoformat(timespec="seconds")
            if resolved.exists()
            else ""
        ),
    }


def resolve_evidence_targets(
    value: str,
    memory_hub_root: Path,
    vault_roots: Iterable[Path],
) -> list[dict[str, Any]]:
    targets: list[dict[str, Any]] = []
    seen: set[Path] = set()
    for raw_part in filter(None, (part.strip() for part in value.split(";"))):
        wikilink = extract_wikilink(raw_part)
        candidates: list[Path] = []
        if wikilink:
            name = wikilink if wikilink.endswith(".md") else f"{wikilink}.md"
            candidates.extend(
                (
                    memory_hub_root / "10-Daily" / name,
                    memory_hub_root / "20-Projects" / name,
                    memory_hub_root / "50-Agent-Workflows" / "00-Dashboard" / name,
                    memory_hub_root / name,
                )
            )
        elif re.match(r"^[A-Za-z]:[\\/]", raw_part):
            candidates.append(Path(re.split(r"\s+[（(]", raw_part, maxsplit=1)[0].strip()))

        for candidate in candidates:
            resolved = candidate.resolve()
            if not resolved.exists() or resolved in seen:
                continue
            seen.add(resolved)
            targets.append(evidence_target(resolved, vault_roots))
            break
    return targets


def source_state(label: str, path: Path, now: datetime, stale_days: int) -> SourceState:
    modified_at = datetime.fromtimestamp(path.stat().st_mtime, tz=now.tzinfo)
    age_days = max(0, (now.date() - modified_at.date()).days)
    return SourceState(label, path, modified_at, age_days, age_days > stale_days)


def load_current_tasks(path: Path) -> list[dict[str, str]]:
    rows = table_with_columns(read_text(path), ("状态", "任务", "主 agent", "证据路径"))
    result = []
    for row in rows:
        status = clean_markdown(row["状态"])
        result.append(
            {
                "status": status,
                "task": clean_markdown(row["任务"]),
                "agent": clean_markdown(row["主 agent"]),
                "collaborator": clean_markdown(row.get("协作/审查", "")),
                "evidence": row["证据路径"].strip(),
                "source_path": str(path),
                "blocked": "受阻" in status,
                "overdue": "超期" in status or "超21天" in status,
                "open": not any(marker in status for marker in COMPLETED_STATUS_MARKERS),
            }
        )
    return result


def integer_metadata(metadata: dict[str, Any], key: str) -> int | None:
    match = re.search(r"-?\d+", str(metadata.get(key, "")))
    return int(match.group()) if match else None


def ledger_item_state(status: str) -> tuple[str, bool]:
    normalized = clean_markdown(status)
    if any(marker in normalized for marker in ("不纳入", "延期", "暂缓", "已终止")):
        return "deferred", False
    if "跨阶段" in normalized or "后续保留" in normalized:
        return "open", True
    if normalized.startswith("已完成") or normalized in {"完成", "关闭"}:
        return "completed", "未部署" in normalized
    needs_review = any(
        marker in normalized for marker in ("待验证", "待确认", "等待决策", "受阻", "未开始")
    )
    return "open", needs_review


def build_task_ledgers(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Read structured task-scope ledgers linked by formal current tasks."""
    ledgers: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    for task in tasks:
        for target in task.get("evidence_targets", []):
            raw_path = target.get("path", "")
            if not raw_path:
                continue
            path = Path(raw_path)
            path_key = str(path.resolve()).lower()
            if path_key in seen_paths or not path.exists() or path.suffix.lower() != ".md":
                continue
            text = read_text(path)
            metadata = parse_frontmatter(text)
            total = integer_metadata(metadata, "tasks_total")
            if not total:
                continue
            rows = table_with_columns(text, ("任务", "当前状态"))
            if not rows:
                continue
            items: list[dict[str, Any]] = []
            for row in rows:
                item_id = clean_markdown(row.get("任务", ""))
                if not re.fullmatch(r"[A-Za-z]+\d+", item_id):
                    continue
                status = clean_markdown(row.get("当前状态", ""))
                state, needs_review = ledger_item_state(status)
                items.append(
                    {
                        "id": item_id,
                        "title": clean_markdown(row.get("工作项", "")) or item_id,
                        "status": status,
                        "ledger_state": state,
                        "needs_review": needs_review,
                    }
                )
            if not items:
                continue
            counts = Counter(item["ledger_state"] for item in items)
            completed = counts["completed"]
            deferred = counts["deferred"]
            open_items = counts["open"]
            current_scope = integer_metadata(metadata, "tasks_in_current_scope")
            metadata_completed = integer_metadata(metadata, "tasks_completed")
            metadata_deferred = integer_metadata(metadata, "tasks_excluded_from_current_scope")
            ledgers.append(
                {
                    "id": path_key,
                    "title": clean_markdown(str(metadata.get("title", ""))) or path.stem,
                    "linked_task": task.get("task", ""),
                    "source_target": target,
                    "total": total,
                    "completed": completed,
                    "deferred": deferred,
                    "open": open_items,
                    "needs_review": sum(item["needs_review"] for item in items),
                    "current_scope": current_scope,
                    "metadata_completed": metadata_completed,
                    "metadata_deferred": metadata_deferred,
                    "conserved": total == completed + deferred + open_items == len(items),
                    "items": items,
                }
            )
            seen_paths.add(path_key)
    return ledgers


def formal_task_state(task: dict[str, Any]) -> str:
    status = clean_markdown(task.get("status", ""))
    if task.get("open", True):
        return "open"
    if any(marker in status for marker in ("不纳入", "延期", "暂缓", "已终止")):
        return "deferred"
    return "completed"


def load_projects(path: Path) -> list[dict[str, str]]:
    rows = table_with_columns(read_text(path), ("项目", "状态", "下一步"))
    result = []
    for row in rows:
        result.append(
            {
                "project": clean_markdown(row["项目"]),
                "wikilink": extract_wikilink(row["项目"]) or clean_markdown(row["项目"]),
                "status": clean_markdown(row["状态"]),
                "path": row.get("源码/产物路径", "").strip(' `<>'),
                "next_step": clean_markdown(row["下一步"]),
            }
        )
    return result


def bullet_field(text: str, label: str) -> str:
    match = re.search(rf"^-\s+\*\*{re.escape(label)}\*\*[：:]\s*(.+)$", text, re.MULTILINE)
    return clean_markdown(match.group(1)) if match else ""


def load_worklog_entries(memory_hub_root: Path, now: datetime) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    daily_folder = memory_hub_root / "10-Daily"
    for path in sorted(daily_folder.glob("20??-??-??-worklog.md")):
        work_date = parse_date(path.name, now).date()
        text = read_text(path)
        matches = list(
            re.finditer(r"^##\s+任务(?:收工|推进)[：:]\s*(.+)$", text, re.MULTILINE)
        )
        for index, match in enumerate(matches):
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            block = text[match.end() : end]
            entries.append(
                {
                    "date": work_date.isoformat(),
                    "title": clean_markdown(match.group(1)),
                    "receipt_id": bullet_field(block, "收工回执"),
                    "status": bullet_field(block, "当前状态") or "未标注",
                    "completed": bullet_field(block, "本次完成"),
                    "unfinished": bullet_field(block, "尚未完成"),
                    "next_action": bullet_field(block, "下一步动作"),
                    "key_files": bullet_field(block, "关键文件"),
                    "evidence": bullet_field(block, "证据路径"),
                    "updated_at": bullet_field(block, "更新时间与 Agent").split("/")[0].strip(),
                    "source": str(path),
                }
            )
    return entries


def candidate_key(value: str) -> str:
    value = clean_markdown(value).lower()
    value = re.sub(r"20\d{2}[-/.年]\d{1,2}[-/.月]\d{1,2}日?", "", value)
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", value)


def candidate_matches(value: str, candidates: Iterable[str]) -> bool:
    key = candidate_key(value)
    if len(key) < 4:
        return False
    for candidate in candidates:
        other = candidate_key(candidate)
        if len(other) >= 4 and (key in other or other in key):
            return True
    return False


def load_plan_candidate_entries(
    path: Path, now: datetime, scan_days: int
) -> list[dict[str, str]]:
    plan_date = parse_date(path.name, now).date()
    age_days = (now.date() - plan_date).days
    if age_days < 0 or age_days > scan_days:
        return []

    result: list[dict[str, str]] = []
    in_candidate_section = False
    for raw_line in read_text(path).splitlines():
        heading = re.match(r"^##\s+(.+)$", raw_line.strip())
        if heading:
            in_candidate_section = any(
                marker in heading.group(1) for marker in PLAN_CANDIDATE_SECTIONS
            )
            continue
        if not in_candidate_section:
            continue

        item_match = re.match(r"^\s*-\s*(?:\[[ xX]\]\s*)?(.+)$", raw_line)
        if not item_match:
            continue
        body = item_match.group(1).strip()
        status_match = re.match(r"^([^：:]+)[：:](.+)$", body)
        status = clean_markdown(status_match.group(1)) if status_match else "计划线索"
        if any(marker in status for marker in PLAN_COMPLETED_MARKERS):
            continue
        detail = status_match.group(2).strip() if status_match else body
        evidence_match = re.search(r"证据[：:]\s*(.*?)(?:[）)]\s*$|$)", detail)
        evidence = clean_markdown(evidence_match.group(1)) if evidence_match else ""
        title = re.split(r"[（(]\s*(?:主\s*agent|文件占用|证据)\s*[：:]", detail, maxsplit=1)[0]
        title = clean_markdown(title)
        if not title or title == status:
            continue
        result.append(
            {
                "date": plan_date.isoformat(),
                "title": title,
                "status": status,
                "candidate_kind": "计划候选",
                "unfinished": f"计划中标记为“{status}”",
                "next_action": f"核实计划项“{title}”是否仍需继续，并补正式任务和验收标准",
                "evidence": evidence,
                "key_files": "",
                "source": str(path),
                "source_kind": "plan",
            }
        )
    return result


def load_log_candidates(
    memory_hub_root: Path,
    projects: list[dict[str, str]],
    worklogs: list[dict[str, str]],
    current_tasks: list[dict[str, str]],
    decision_entries: list[dict[str, str]],
    now: datetime,
    scan_days: int,
    max_items: int,
) -> list[dict[str, str]]:
    project_titles = [
        value
        for item in projects
        for value in (
            item.get("project", ""),
            item.get("task", ""),
            item.get("title", ""),
        )
        if value
    ]
    active_current_tasks = [
        item
        for item in current_tasks
        if item.get(
            "open",
            not any(
                marker in clean_markdown(item.get("status", ""))
                for marker in COMPLETED_STATUS_MARKERS
            ),
        )
    ]
    task_titles = [
        value
        for item in (*active_current_tasks, *decision_entries)
        for value in (item.get("task", ""), item.get("title", ""))
        if value
    ]
    covered_receipts = {
        receipt
        for item in (*active_current_tasks, *decision_entries)
        for receipt in receipt_ids(item.get("evidence", ""))
    }
    existing_titles = project_titles + task_titles
    project_basenames = Counter(source_basename(project.get("path", "")) for project in projects)
    unique_project_basenames = {
        basename
        for basename, count in project_basenames.items()
        if len(basename) >= 8 and count == 1
    }
    result: list[dict[str, str]] = []
    seen_titles: list[str] = []

    for entry in worklogs:
        age_days = (now.date() - date.fromisoformat(entry["date"])).days
        if age_days < 0 or age_days > scan_days:
            continue
        status = clean_markdown(entry["status"])
        unfinished = clean_markdown(entry["unfinished"])
        next_action = clean_markdown(entry["next_action"])
        completed = any(marker in status for marker in COMPLETED_STATUS_MARKERS)
        if completed:
            if (
                not unfinished
                or unfinished.startswith("无")
                or any(marker in unfinished for marker in COMPLETED_FOLLOWUP_EXCLUDES)
            ):
                continue
            candidate_kind = "已完成任务的后续"
            if entry.get("receipt_id") in covered_receipts:
                continue
        else:
            if not unfinished and not next_action:
                continue
            candidate_kind = "未闭环任务"
        entry_paths = f"{entry['key_files']} {entry['evidence']}".lower().replace("/", "\\")
        if candidate_kind != "已完成任务的后续" and any(
            basename in entry_paths for basename in unique_project_basenames
        ):
            continue
        comparison_titles = (
            task_titles if candidate_kind == "已完成任务的后续" else existing_titles
        )
        if candidate_matches(entry["title"], comparison_titles + seen_titles):
            continue
        result.append(
            {
                "date": entry["date"],
                "title": clean_markdown(entry["title"]),
                "status": status,
                "candidate_kind": candidate_kind,
                "receipt_id": entry.get("receipt_id", ""),
                "unfinished": unfinished,
                "next_action": next_action or unfinished,
                "evidence": entry["evidence"],
                "key_files": entry["key_files"],
                "source": entry["source"],
                "source_kind": "worklog",
            }
        )
        seen_titles.append(entry["title"])

    for path in sorted((memory_hub_root / "10-Daily").glob("20??-??-??-plan.md")):
        for candidate in load_plan_candidate_entries(path, now, scan_days):
            known = existing_titles + [entry["title"] for entry in worklogs] + seen_titles
            if candidate_matches(candidate["title"], known):
                continue
            result.append(candidate)
            seen_titles.append(candidate["title"])

    kind_order = {"未闭环任务": 0, "已完成任务的后续": 1, "计划候选": 2}
    result.sort(
        key=lambda item: (
            -date.fromisoformat(item["date"]).toordinal(),
            kind_order.get(item["candidate_kind"], 9),
            item["title"],
        ),
    )
    return result[:max_items]


def build_omission_findings(
    tasks: list[dict[str, Any]],
    ledgers: list[dict[str, Any]],
    log_candidates: list[dict[str, Any]],
    worklogs: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []

    def add(
        rule: str,
        priority: str,
        title: str,
        reason: str,
        next_action: str,
        source_target: dict[str, Any] | None,
        reference_key: str,
    ) -> None:
        findings.append(
            {
                "id": f"{rule}:{reference_key}",
                "rule": rule,
                "priority": priority,
                "title": title,
                "reason": reason,
                "next_action": next_action,
                "source_target": source_target or {},
                "reference_key": reference_key,
                "read_only": True,
            }
        )

    for task in tasks:
        if not task.get("open", True):
            continue
        key = candidate_key(task.get("task", "")) or str(len(findings))
        owner = clean_markdown(task.get("agent", ""))
        if not owner or owner in {"-", "—", "待定", "待登记"}:
            add(
                "missing_owner",
                "P1",
                task.get("task", "未命名任务"),
                "开放任务没有明确执行主体。",
                "人工确认负责人，并回填正式任务源。",
                task.get("source_target"),
                f"task-owner:{key}",
            )
        if not clean_markdown(task.get("evidence", "")):
            add(
                "missing_evidence",
                "P1",
                task.get("task", "未命名任务"),
                "开放任务没有证据路径，后续无法自动核对状态。",
                "补充验收证据或明确说明尚无证据。",
                task.get("source_target"),
                f"task-evidence:{key}",
            )

    latest_worklog_by_title: dict[str, dict[str, Any]] = {}
    for entry in worklogs or []:
        key = candidate_key(entry.get("title", ""))
        if not key:
            continue
        current = latest_worklog_by_title.get(key)
        if not current or (entry.get("updated_at") or entry.get("date", "")) > (
            current.get("updated_at") or current.get("date", "")
        ):
            latest_worklog_by_title[key] = entry
    for task in tasks:
        key = candidate_key(task.get("task", ""))
        latest = latest_worklog_by_title.get(key)
        if not latest:
            continue
        worklog_completed = any(
            marker in clean_markdown(latest.get("status", ""))
            for marker in COMPLETED_STATUS_MARKERS
        )
        task_open = task.get("open", True)
        if task_open and worklog_completed and not has_meaningful_remaining(latest.get("unfinished", "")):
            add(
                "status_conflict",
                "P1",
                task.get("task", "未命名任务"),
                "正式任务仍为开放状态，但同名最新工作日志已完成且没有后续事项。",
                "人工确认任务应关闭还是工作日志需要更正。",
                task.get("source_target"),
                f"task-status:{key}",
            )
        elif not task_open and not worklog_completed:
            add(
                "status_conflict",
                "P1",
                task.get("task", "未命名任务"),
                "正式任务已关闭，但同名最新工作日志仍处于未闭环状态。",
                "人工确认任务是否需要重新打开或修正日志状态。",
                task.get("source_target"),
                f"task-status:{key}",
            )

    for ledger in ledgers:
        key = ledger.get("id", candidate_key(ledger.get("title", "")))
        source_target = ledger.get("source_target", {})
        if not ledger.get("conserved"):
            add(
                "scope_conservation",
                "P0",
                ledger.get("title", "未命名任务清单"),
                f"原始总数 {ledger.get('total', 0)} 与完成、延期、未闭环三类合计不一致。",
                "核对缺失编号；修正前不允许以缩小范围替代原始总账。",
                source_target,
                f"ledger-scope:{key}",
            )
        current_scope = ledger.get("current_scope")
        deferred = ledger.get("deferred", 0)
        if current_scope is not None and current_scope + deferred != ledger.get("total", 0):
            add(
                "scope_reduction_mismatch",
                "P0",
                ledger.get("title", "未命名任务清单"),
                "当前范围与延期保留项无法还原原始总数。",
                "确认被排除事项仍留在延期账，并修正范围元数据。",
                source_target,
                f"ledger-range:{key}",
            )
        metadata_completed = ledger.get("metadata_completed")
        if metadata_completed is not None and metadata_completed != ledger.get("completed"):
            add(
                "completion_count_conflict",
                "P0",
                ledger.get("title", "未命名任务清单"),
                f"元数据完成数 {metadata_completed} 与逐项状态完成数 {ledger.get('completed', 0)} 不一致。",
                "逐项复核完成证据后统一元数据与明细状态。",
                source_target,
                f"ledger-complete:{key}",
            )
        metadata_deferred = ledger.get("metadata_deferred")
        if metadata_deferred is not None and metadata_deferred != deferred:
            add(
                "deferred_count_conflict",
                "P0",
                ledger.get("title", "未命名任务清单"),
                f"元数据延期数 {metadata_deferred} 与逐项状态延期数 {deferred} 不一致。",
                "恢复遗漏的延期事项或更正逐项状态。",
                source_target,
                f"ledger-deferred:{key}",
            )

    for candidate in log_candidates:
        if candidate.get("candidate_kind") != "已完成任务的后续":
            continue
        receipt = candidate.get("receipt_id", "")
        reference_key = receipt or candidate_key(candidate.get("title", ""))
        add(
            "phase_follow_up",
            "P1",
            candidate.get("title", "未命名后续"),
            "阶段完成记录仍声明了未完成事项，但尚未被正式任务或决策覆盖。",
            candidate.get("next_action") or "确认继续、延期或关闭，并登记正式状态。",
            candidate.get("source_target"),
            f"candidate:{reference_key}",
        )

    priority_rank = {"P0": 0, "P1": 1, "P2": 2}
    return sorted(
        findings,
        key=lambda item: (priority_rank.get(item["priority"], 9), item["rule"], item["title"]),
    )


def build_confirmation_queue(
    decision_entries: list[dict[str, Any]],
    log_candidates: list[dict[str, Any]],
    omission_findings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    queue: list[dict[str, Any]] = []
    seen: set[str] = set()

    def append(item: dict[str, Any], reference_key: str) -> None:
        dedup_key = reference_key or candidate_key(item.get("title", ""))
        title_key = f"title:{candidate_key(item.get('title', ''))}"
        if dedup_key in seen or title_key in seen:
            return
        seen.update((dedup_key, title_key))
        queue.append({**item, "reference_key": dedup_key, "read_only": True})

    for finding in omission_findings:
        append(
            {
                "id": finding["id"],
                "kind": "自动防漏",
                "priority": finding["priority"],
                "title": finding["title"],
                "status": finding["rule"],
                "reason": finding["reason"],
                "next_action": finding["next_action"],
                "date": "",
                "source_target": finding.get("source_target", {}),
                "evidence_targets": [],
            },
            finding.get("reference_key", ""),
        )
    for entry in sorted(
        decision_entries,
        key=lambda item: item.get("updated_at") or item.get("date", ""),
        reverse=True,
    ):
        receipt = entry.get("receipt_id", "")
        append(
            {
                "id": f"decision:{receipt or candidate_key(entry.get('title', ''))}",
                "kind": "正式决策",
                "priority": "P0",
                "title": entry.get("title", "未命名决策"),
                "status": entry.get("status", "等待判断"),
                "reason": entry.get("unfinished") or entry.get("completed") or "正式记录等待判断。",
                "next_action": entry.get("next_action") or "确认通过、修改、继续或暂停。",
                "date": entry.get("date", ""),
                "source_target": entry.get("source_target", {}),
                "evidence_targets": entry.get("evidence_targets", []),
            },
            f"decision:{receipt or candidate_key(entry.get('title', ''))}",
        )
    for candidate in log_candidates:
        receipt = candidate.get("receipt_id", "")
        reference = f"candidate:{receipt or candidate_key(candidate.get('title', ''))}"
        append(
            {
                "id": reference,
                "kind": "日志候选",
                "priority": "P1" if candidate.get("candidate_kind") != "计划候选" else "P2",
                "title": candidate.get("title", "未命名候选"),
                "status": candidate.get("candidate_kind", "待核实"),
                "reason": candidate.get("unfinished") or candidate.get("status") or "日志线索等待核实。",
                "next_action": candidate.get("next_action") or "确认继续、合并或关闭。",
                "date": candidate.get("date", ""),
                "source_target": candidate.get("source_target", {}),
                "evidence_targets": candidate.get("evidence_targets", []),
            },
            reference,
        )

    priority_rank = {"P0": 0, "P1": 1, "P2": 2}
    return sorted(
        queue,
        key=lambda item: (priority_rank.get(item["priority"], 9), item.get("date", ""), item["title"]),
    )


def receipt_ids(value: str) -> list[str]:
    return re.findall(r"MC-[A-Z0-9-]+", clean_markdown(value))


def load_decision_resolutions(path: Path) -> list[dict[str, Any]]:
    rows = table_with_columns(
        read_text(path),
        ("决策键", "状态", "已关闭回执", "闭环回执"),
    )
    return [
        {
            "decision_key": clean_markdown(row["决策键"]),
            "status": clean_markdown(row["状态"]),
            "closed_receipts": receipt_ids(row["已关闭回执"]),
            "resolved_by_receipt": next(iter(receipt_ids(row["闭环回执"])), ""),
            "resolved_at": clean_markdown(row.get("闭环日期", "")),
            "note": clean_markdown(row.get("说明", "")),
            "source": str(path),
        }
        for row in rows
    ]


def apply_decision_resolutions(
    recent_worklogs: list[dict[str, str]],
    all_worklogs: list[dict[str, str]],
    resolutions: list[dict[str, Any]],
) -> tuple[list[dict[str, str]], list[dict[str, Any]], list[dict[str, Any]]]:
    worklogs_by_receipt = {
        entry["receipt_id"]: entry for entry in all_worklogs if entry["receipt_id"]
    }
    valid_resolutions: list[dict[str, Any]] = []
    resolution_by_receipt: dict[str, dict[str, Any]] = {}
    for resolution in resolutions:
        resolver = worklogs_by_receipt.get(resolution["resolved_by_receipt"])
        if not resolver or not any(marker in resolver["status"] for marker in COMPLETED_STATUS_MARKERS):
            continue
        valid_resolutions.append(resolution)
        for closed_receipt in resolution["closed_receipts"]:
            closed_entry = worklogs_by_receipt.get(closed_receipt)
            if closed_entry and any(
                marker in closed_entry["status"] for marker in ("等待", "待确认", "受阻")
            ):
                resolution_by_receipt[closed_receipt] = resolution

    decision_entries: list[dict[str, str]] = []
    resolved_decisions: list[dict[str, Any]] = []
    for entry in recent_worklogs:
        if not any(marker in entry["status"] for marker in ("等待", "待确认", "受阻")):
            continue
        resolution = resolution_by_receipt.get(entry["receipt_id"])
        if resolution:
            resolved_decisions.append(
                {
                    **entry,
                    "resolution": {
                        "decision_key": resolution["decision_key"],
                        "status": resolution["status"],
                        "resolved_by_receipt": resolution["resolved_by_receipt"],
                        "resolved_at": resolution["resolved_at"],
                        "note": resolution["note"],
                        "source": resolution["source"],
                    },
                }
            )
        else:
            decision_entries.append(entry)
    return decision_entries, resolved_decisions, valid_resolutions


def source_basename(raw_path: str) -> str:
    cleaned = clean_markdown(raw_path)
    cleaned = re.split(r"[（(]", cleaned, maxsplit=1)[0].strip()
    cleaned = re.sub(r"\s+-\s+20\d{6}$", "", cleaned)
    return cleaned.replace("/", "\\").rstrip("\\").split("\\")[-1].lower()


def worklog_matches_project(
    entry: dict[str, str], project: dict[str, str], allow_path_match: bool = True
) -> bool:
    name = project["project"].lower()
    title = entry["title"].lower()
    if name and (name in title or title in name):
        return True
    basename = source_basename(project["path"])
    haystack = f"{entry['key_files']} {entry['evidence']}".lower().replace("/", "\\")
    return bool(
        allow_path_match and basename and basename not in {"等", ""} and basename in haystack
    )


def worklog_match_strength(
    entry: dict[str, str], project: dict[str, str], allow_path_match: bool = True
) -> int:
    name = project["project"].lower()
    title = entry["title"].lower()
    if name and (name in title or title in name):
        return 2
    return 1 if worklog_matches_project(entry, project, allow_path_match) else 0


def has_meaningful_remaining(value: str) -> bool:
    remaining = clean_markdown(value).strip()
    if not remaining:
        return False
    return not no_remaining(remaining) and re.match(r"^(?:无|没有|不适用|已全部完成)(?:$|[（(，,。；;])", remaining) is None


def project_page_state(memory_hub_root: Path, project: dict[str, str]) -> dict[str, Any]:
    path = memory_hub_root / "20-Projects" / f"{project['wikilink']}.md"
    if not path.exists():
        return {"path": "", "current_state": "", "unchecked": 0, "receipt_ids": []}
    text = read_text(path)
    return {
        "path": str(path),
        "current_state": bullet_field(text, "当前状态"),
        "unchecked": len(re.findall(r"^-\s*\[\s\]", text, re.MULTILINE)),
        "receipt_ids": receipt_ids(text),
    }


def classify_projects(
    projects: list[dict[str, str]],
    worklogs: list[dict[str, str]],
    memory_hub_root: Path,
    now: datetime,
    recent_days: int,
    review_days: int,
) -> list[dict[str, Any]]:
    classified: list[dict[str, Any]] = []
    basename_counts = Counter(
        source_basename(project["path"])
        for project in projects
        if project["status"] not in {"历史", "legacy", "参考"}
    )
    for project in projects:
        basename = source_basename(project["path"])
        page = project_page_state(memory_hub_root, project)
        linked_receipts = set(page["receipt_ids"])
        explicitly_linked = [
            entry for entry in worklogs if entry.get("receipt_id") in linked_receipts
        ]
        heuristic_matches = [
            entry
            for entry in worklogs
            if worklog_matches_project(entry, project, basename_counts[basename] == 1)
        ]
        matches = explicitly_linked or heuristic_matches
        latest = max(
            matches,
            key=lambda item: (
                item["updated_at"] or item["date"],
                worklog_match_strength(item, project, basename_counts[basename] == 1),
            ),
            default=None,
        )
        age_days = (now.date() - date.fromisoformat(latest["date"])).days if latest else None
        explicit = page["current_state"]
        latest_status = latest["status"] if latest else ""
        latest_unfinished = latest["unfinished"] if latest else ""
        latest_next_action = latest["next_action"] if latest else ""
        remaining = has_meaningful_remaining(latest_unfinished)
        awaiting = any(
            marker
            in f"{explicit} {latest_status} {latest_unfinished} {latest_next_action}"
            for marker in ("等待", "待验收", "待确认", "待负责人", "待用户", "真人验收")
        )
        completed = any(marker in explicit for marker in ("已完成", "阶段完成"))

        if project["status"] in {"历史", "legacy", "参考"}:
            state = project["status"]
            reason = "项目索引已明确标为非当前项目，不因共享路径或近期文件变化自动重新激活。"
        elif latest and age_days is not None and age_days <= recent_days:
            if any(marker in latest_status for marker in ("已完成", "阶段完成", "已终止")):
                if remaining:
                    state = "待验收/待决策" if awaiting else "本周推进"
                    reason = (
                        f"最近正式工作证据为 {latest['date']}，状态：{latest_status}；"
                        f"仍登记后续：{latest_unfinished}"
                    )
                else:
                    state = "近期完成"
            else:
                state = "待验收/待决策" if awaiting or "等待用户" in latest["status"] else "本周推进"
            if not (remaining and any(marker in latest_status for marker in ("已完成", "阶段完成", "已终止"))):
                reason = f"最近正式工作证据为 {latest['date']}，状态：{latest_status}。"
        elif project["status"] in {"活跃", "调研"} and (age_days is None or age_days > review_days):
            state = "待核实"
            if completed and page["unchecked"]:
                reason = f"项目页写为“{explicit}”，但仍有 {page['unchecked']} 个未勾选事项，且近期无正式推进证据。"
            elif awaiting:
                reason = f"项目停在“{explicit or latest['status']}”，已超过 {review_days} 天没有正式推进证据。"
            else:
                latest_text = latest["date"] if latest else "未找到"
                reason = f"项目索引仍标为“{project['status']}”，但最近正式工作证据为 {latest_text}。"
        elif completed:
            state = "待核实" if page["unchecked"] else "待归档"
            reason = f"项目页写为“{explicit}”，需要确认是否还有真实后续。"
        elif latest and age_days is not None and age_days <= review_days:
            state = "近期有进展"
            reason = f"最近正式工作证据为 {latest['date']}，但不在本周窗口内。"
        else:
            state = project["status"]
            reason = "沿用项目索引状态；尚无足够证据改变判断。"

        if state == "待核实" and (completed or awaiting):
            decision = "确认三选一：补最后验收并归档、安排明确日期继续、暂停并写重启条件。"
        elif state == "待核实":
            decision = "确认继续、暂停或归档；若继续，补本周动作、负责人和验收日期。"
        elif state == "待验收/待决策":
            decision = latest["next_action"] if latest and latest["next_action"] else project["next_step"]
        elif state == "近期完成":
            decision = "确认成果是否已进入稳定使用；若没有新里程碑，本周不继续占用主推进名额。"
        else:
            decision = latest["next_action"] if latest and latest["next_action"] else project["next_step"]

        classified.append(
            {
                **project,
                "operating_state": state,
                "state_reason": reason,
                "decision": decision,
                "latest_evidence_date": latest["date"] if latest else "",
                "latest_worklog": latest["source"] if latest else "",
                "project_page": page["path"],
                "page_state": explicit,
                "unchecked_items": page["unchecked"],
            }
        )
    return classified


def load_emerging_projects(
    config: dict[str, Any], memory_hub_root: Path, project_index: list[dict[str, str]], now: datetime
) -> list[dict[str, str]]:
    activity_days = int(config["activity_signal_days"])
    activity_files = []
    for path in (memory_hub_root / "10-Daily").glob("20??-??-??-ai-activity.md"):
        activity_date = parse_date(path.name, now).date()
        if (now.date() - activity_date).days <= activity_days:
            activity_files.append((path, activity_date, read_text(path)))
    indexed_haystack = " ".join(
        f"{project['project']} {project['path']}" for project in project_index
    ).lower()
    result: list[dict[str, str]] = []
    for candidate in config.get("emerging_projects", []):
        aliases = [candidate["name"], candidate["path"], *candidate.get("aliases", [])]
        if any(alias.lower() in indexed_haystack for alias in aliases):
            continue
        matches = [
            (path, activity_date)
            for path, activity_date, text in activity_files
            if any(alias.lower() in text.lower() for alias in aliases)
        ]
        if not matches or not Path(candidate["path"]).exists():
            continue
        source, activity_date = max(matches, key=lambda item: item[1])
        result.append(
            {
                "name": candidate["name"],
                "path": candidate["path"],
                "status": "新工作待登记",
                "latest_activity_date": activity_date.isoformat(),
                "decision": candidate["decision"],
                "source": str(source),
                "evidence_note": "已发现近期 AI 活动和项目文件变化；尚未进入正式项目索引与验收流程。",
            }
        )
    return result


def load_capabilities(path: Path) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    text = read_text(path)
    capability_rows = table_with_columns(text, ("能力域", "成熟度", "判断"))
    gap_rows = table_with_columns(text, ("优先级", "空白能力", "为什么重要"))
    capabilities = [
        {
            "domain": clean_markdown(row["能力域"]),
            "maturity": clean_markdown(row["成熟度"]),
            "evidence": row.get("个人库证据", "").strip(),
            "judgement": clean_markdown(row["判断"]),
        }
        for row in capability_rows
    ]
    gaps = [
        {
            "priority": clean_markdown(row["优先级"]),
            "capability": clean_markdown(row["空白能力"]),
            "importance": clean_markdown(row["为什么重要"]),
            "starting_point": clean_markdown(row.get("起点（库内 TODO）", "")),
        }
        for row in gap_rows
    ]
    return capabilities, gaps


def select_meeting_files(folder: Path, now: datetime, recent_days: int) -> list[Path]:
    cutoff = now.date() - timedelta(days=recent_days)
    selected = []
    for path in folder.rglob("*.md"):
        if "会议纪要" not in path.parts or any(marker in path.stem for marker in MEETING_EXCLUDES):
            continue
        text = read_text(path)
        metadata = parse_frontmatter(text)
        meeting_time = parse_date(str(metadata.get("时间", path.stem)), now)
        if meeting_time.date() >= cutoff:
            selected.append(path)
    return sorted(selected, key=lambda item: item.stat().st_mtime, reverse=True)


def meeting_actions(
    meeting_files: list[Path], owner_aliases: list[str], job_vault_root: Path, now: datetime
) -> list[dict[str, str]]:
    actions: list[dict[str, str]] = []
    for path in meeting_files:
        text = read_text(path)
        metadata = parse_frontmatter(text)
        meeting_date = parse_date(str(metadata.get("时间", path.stem)), now).date().isoformat()
        for table in markdown_tables(text):
            if not table:
                continue
            headers = table[0].keys()
            action_key = next((key for key in ("交付物", "任务", "动作", "任务描述") if key in headers), None)
            owner_key = next((key for key in ("负责人", "责任团队", "责任人") if key in headers), None)
            if not action_key or not owner_key:
                continue
            collaborator_key = next((key for key in ("协作人", "协作") if key in headers), None)
            for row in table:
                owner = clean_markdown(row.get(owner_key, ""))
                collaborator = clean_markdown(row.get(collaborator_key, "")) if collaborator_key else ""
                if not any(owner_mentions_alias(owner, alias) for alias in owner_aliases):
                    continue
                actions.append(
                    {
                        "meeting_date": meeting_date,
                        "action": clean_markdown(row[action_key]),
                        "owner": owner,
                        "collaborator": collaborator,
                        "due": clean_markdown(row.get("日期", row.get("截止", row.get("截止日期", "未明确")))) or "未明确",
                        "acceptance": clean_markdown(row.get("验收标准", "")),
                        "source": str(path),
                        "source_link": obsidian_link(job_vault_root, path, path.stem),
                    }
                )
            break
    unique: dict[tuple[str, str], dict[str, str]] = {}
    for action in actions:
        unique[(action["action"], action["source"])] = action
    return sorted(unique.values(), key=lambda item: item["meeting_date"], reverse=True)


def recent_job_notes(folder: Path, job_vault_root: Path, limit: int) -> list[dict[str, str]]:
    paths = [
        path
        for path in folder.rglob("*.md")
        if not any(marker in path.stem for marker in MEETING_EXCLUDES)
        and not any(part.startswith(".") for part in path.relative_to(folder).parts)
    ]
    paths.sort(key=lambda item: item.stat().st_mtime, reverse=True)
    result = []
    for path in paths[:limit]:
        modified = datetime.fromtimestamp(path.stat().st_mtime).astimezone()
        result.append(
            {
                "title": path.stem,
                "modified": modified.isoformat(timespec="seconds"),
                "link": obsidian_link(job_vault_root, path, path.stem),
                "source": str(path),
            }
        )
    return result


def topic_counts(meeting_files: list[Path]) -> list[dict[str, Any]]:
    keywords = ("销售", "供应链", "AI", "CRM", "数据", "生产", "物流", "市场", "看板")
    counts = Counter(keyword for path in meeting_files for keyword in keywords if keyword.lower() in path.stem.lower())
    return [{"topic": topic, "meeting_count": count} for topic, count in counts.most_common(6)]


def recommendation_rules(snapshot: dict[str, Any]) -> list[dict[str, str]]:
    recommendations: list[dict[str, str]] = []
    metrics = snapshot["metrics"]
    if metrics.get("omission_findings", 0):
        recommendations.append(
            {
                "priority": "P0",
                "type": "事实驱动",
                "recommendation": "先处理自动防漏告警，再关闭或缩小任务范围。",
                "basis": f"自动规则发现 {metrics['omission_findings']} 条范围守恒、阶段后续、负责人或证据缺口。",
                "next_action": "逐条进入人工确认队列，确认继续、延期、合并或关闭；确认前保持只读。",
                "stop_condition": "P0 防漏告警清零，其余告警均有负责人和明确处理状态。",
            }
        )
    if metrics["decision_queue"]:
        recommendations.append(
            {
                "priority": "P0",
                "type": "事实驱动",
                "recommendation": "先验收或否决近期交付，再开启更多开发。",
                "basis": f"近 {snapshot['windows']['recent_work_days']} 天有 {metrics['decision_queue']} 项正式交付处于等待确认或待决策。",
                "next_action": "每天先处理一个待验收项，明确通过、修改或暂停，避免已完成开发长期悬空。",
                "stop_condition": "每项近期交付都有明确决定和后续负责人。",
            }
        )
    if metrics["emerging_projects"]:
        recommendations.append(
            {
                "priority": "P0",
                "type": "证据驱动",
                "recommendation": "把 WeKnora 从活动信号升级为可验收项目，而不是只算一次部署。",
                "basis": f"识别到 {metrics['emerging_projects']} 个近期真实工作目录和文件变化，但尚未进入项目索引。",
                "next_action": "先定义目标用户、首个使用场景、最小验收问题集和下一里程碑，再决定正式立项。",
                "stop_condition": "新工作已登记为项目，或明确记录为一次性试验并关闭。",
            }
        )
    if metrics.get("log_candidates", 0):
        recommendations.append(
            {
                "priority": "P1",
                "type": "事实驱动",
                "recommendation": "先核实日志发现候选，再决定继续、并入已有项目或关闭。",
                "basis": f"近 {snapshot['windows'].get('candidate_scan_days', 45)} 天日志和计划识别到 {metrics['log_candidates']} 条未被当前项目、任务或决策队列覆盖的线索。",
                "next_action": "逐条确认真实目标、负责人、下一里程碑和停止条件；确认前不自动立项。",
                "stop_condition": "每条候选都已进入正式项目/任务，或明确标记为历史计划并关闭。",
            }
        )
    if metrics["projects_to_verify"]:
        recommendations.append(
            {
                "priority": "P0",
                "type": "推断",
                "recommendation": "核对缺少近期证据的项目，决定继续、暂停或结束。",
                "basis": f"有 {metrics['projects_to_verify']} 个索引项目缺少 {snapshot['windows']['project_review_days']} 天内正式推进证据，或项目页状态与未完成项冲突。",
                "next_action": "每个项目只做一次三选一：补验收并归档、排定明确日期继续、暂停并写重启条件。",
                "stop_condition": "待核实项目全部获得生命周期决定；本周在制主线不超过 3 条。",
            }
        )
    if metrics["blocked_tasks"]:
        recommendations.append(
            {
                "priority": "P1",
                "type": "事实驱动",
                "recommendation": "清理旧任务源中的受阻和超期项。",
                "basis": f"当前任务源仍有 {metrics['blocked_tasks']} 项受阻、{metrics['overdue_tasks']} 项带超期标记，且该来源可能未同步最近正式收工记录。",
                "next_action": "先确认其是否仍有效；有效则补检查日期，无效则转暂停或归档。",
                "stop_condition": "旧任务项与近期正式工作日志一致。",
            }
        )
    p0_gaps = [gap for gap in snapshot["capability_gaps"] if "P0" in gap["priority"]]
    if p0_gaps:
        gap_names = "、".join(gap["capability"] for gap in p0_gaps[:2])
        recommendations.append(
            {
                "priority": "P1",
                "type": "证据驱动",
                "recommendation": f"把 {gap_names} 绑定到真实项目验收，不单独按课程推进。",
                "basis": "个人能力地图将这些能力列为 P0，但成熟度证据仍主要来自知识条目而非稳定复用。",
                "next_action": "各选一个真实业务问题，定义基线、应用方法、复盘误差并沉淀可复现产物。",
                "stop_condition": "每项能力至少有一个可复跑案例和一次跨场景复用证据。",
            }
        )
    stale_labels = [source["label"] for source in snapshot["sources"] if source["stale"]]
    if stale_labels:
        recommendations.append(
            {
                "priority": "P1",
                "type": "数据质量",
                "recommendation": "刷新过期的事实源后再做周计划。",
                "basis": f"超过阈值未更新的来源：{'、'.join(stale_labels)}。",
                "next_action": "先核对源文件是否仍为正式入口，再更新事实或标记停用。",
                "stop_condition": "关键来源在新鲜度阈值内，或明确记录停用原因。",
            }
        )
    return recommendations[:6]


def load_recent_focus(config: dict[str, Any], now: datetime, vault_roots) -> list[dict[str, Any]]:
    """Project-scoped activity signals, kept separate from formal task status."""
    root = Path(config['memory_hub_root']) / '10-Daily'
    packets = []
    for path in root.glob('20??-??-??-ai-activity.json'):
        day = date.fromisoformat(path.name[:10])
        if not 0 <= (now.date() - day).days <= int(config['recent_work_days']):
            continue
        packet = json.loads(path.read_text(encoding='utf-8'))
        packets.extend((path, day, item) for item in packet.get('activities', []))
    result = []
    for focus in config.get('focus_projects', []):
        aliases = [alias.lower() for alias in focus.get('aliases', [])]
        matches = []
        for path, day, item in packets:
            titles = ' '.join(item.get('titles', [])).lower()
            cwd = item.get('cwd', '').replace('\\', '/').lower()
            target = focus['path'].replace('\\', '/').lower()
            snippets = item.get('user_prompts', []) + item.get('assistant_notes', [])
            relevant = [text for text in snippets if any(alias in text.lower() for alias in aliases)]
            title_match = any(alias in titles for alias in aliases)
            path_match = cwd == target or cwd.startswith(target + '/')
            other_topic = any(alias.lower() in titles
                for other in config.get('focus_projects', []) if other['name'] != focus['name']
                for alias in other.get('aliases', []))
            if item.get('tool') == 'Gemini Antigravity' and other_topic and not title_match:
                continue
            # Antigravity workspaces can be stale (digital twin conversation
            # located under portrait workspace). Require topic evidence there.
            if item.get('tool') == 'Gemini Antigravity' and not relevant and not title_match:
                continue
            topic_match = item.get('tool') == 'Gemini Antigravity' and (title_match or relevant)
            if not snippets or not (path_match or topic_match):
                continue
            matches.append((item.get('updated_at') or day.isoformat(), path, item, relevant))
        if not matches:
            continue
        def event_time(row):
            moment = datetime.fromisoformat(row[0].replace('Z', '+00:00'))
            return moment if moment.tzinfo else moment.replace(tzinfo=now.tzinfo)
        stamp, path, item, relevant = max(matches, key=event_time)
        notes = relevant or item.get('assistant_notes', []) or item.get('user_prompts', [])
        target = evidence_target(path.with_suffix('.md'), vault_roots)
        result.append(dict(task=focus['name'], status='近期跟进·待核实',
            agent=item['tool'], collaborator='体验用户', open=True, blocked=False,
            overdue=False, updated_at=stamp, evidence=item['source'],
            progress=clean_markdown(notes[-1])[:300], source_target=target,
            evidence_targets=[target], activity_signal=True,
            focus_order=focus.get('order', 99)))
    return sorted(result, key=lambda row: (row['focus_order'], row['task']))


def build_snapshot(config: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now().astimezone()
    current_tasks_file = Path(config["current_tasks_file"])
    project_index_file = Path(config["project_index_file"])
    capability_map_file = Path(config["capability_map_file"])
    decision_resolution_file = Path(config["decision_resolution_file"])
    job_knowledge_folder = Path(config["job_knowledge_folder"])
    job_vault_root = Path(config["job_vault_root"])
    memory_hub_root = Path(config["memory_hub_root"])
    vault_roots = (
        memory_hub_root,
        job_vault_root,
        Path(config["personal_vault_root"]),
    )
    tasks = load_current_tasks(current_tasks_file)
    for task in tasks:
        task["evidence_targets"] = resolve_evidence_targets(
            task["evidence"], memory_hub_root, vault_roots
        )
        task["source_target"] = evidence_target(current_tasks_file, vault_roots)
    projects = load_projects(project_index_file)
    worklogs = load_worklog_entries(memory_hub_root, now)
    activity_discovery = discover_projects(config, now, projects, worklogs)
    for row in activity_discovery['confirmed'] + activity_discovery['discovered']:
        evidence = row.pop('evidence')
        row['activity_evidence'] = evidence
        row['progress'] = clean_markdown(row['progress'])
        row['activity_signal'] = True
        row['open'] = True
        row['blocked'] = False
        row['agent'] = ', '.join(row.get('tools', [])) or '用户确认重点'
        row['evidence'] = ';'.join(dict.fromkeys(item['source'] for item in evidence))
        row['source_target'] = evidence_target(Path(evidence[0]['source']), vault_roots) if evidence else evidence_target(Path(config['snapshot_output']).parents[1] / 'config' / 'operations_dashboard.json', vault_roots)
        row['evidence_targets'] = resolve_evidence_targets(row['evidence'], memory_hub_root, vault_roots)
    recent_focus = activity_discovery['confirmed']
    decision_resolutions = load_decision_resolutions(decision_resolution_file)
    classified_projects = classify_projects(
        projects,
        worklogs,
        memory_hub_root,
        now,
        int(config["recent_work_days"]),
        int(config["project_review_days"]),
    )
    for project in classified_projects:
        project["domain"] = portfolio_domain(project)
        project["bucket"] = portfolio_bucket(project)
        source_path = Path(project["project_page"] or project_index_file)
        project["source_target"] = evidence_target(source_path, vault_roots)
        project["evidence_targets"] = resolve_evidence_targets(
            ";".join(
                value
                for value in (project["latest_worklog"], project["project_page"])
                if value
            ),
            memory_hub_root,
            vault_roots,
        )
    brief_health = enrich_briefs(
        classified_projects, recent_focus + activity_discovery['discovered'], config, now,
        lambda path: evidence_target(path, vault_roots),
    )
    emerging_projects = load_emerging_projects(config, memory_hub_root, projects, now)
    capabilities, capability_gaps = load_capabilities(capability_map_file)
    meetings = select_meeting_files(job_knowledge_folder, now, int(config["recent_job_days"]))
    actions = meeting_actions(meetings, config["owner_aliases"], job_vault_root, now)
    open_tasks = [task for task in tasks if task["open"]]
    recent_worklogs = [
        entry
        for entry in worklogs
        if 0
        <= (now.date() - date.fromisoformat(entry["date"])).days
        <= int(config["recent_work_days"])
    ]
    decision_entries, resolved_decisions, valid_resolutions = apply_decision_resolutions(
        recent_worklogs,
        worklogs,
        decision_resolutions,
    )
    for entry in decision_entries:
        source_path = Path(entry["source"])
        entry["source_target"] = evidence_target(source_path, vault_roots)
        entry["evidence_targets"] = resolve_evidence_targets(
            ";".join(value for value in (entry["evidence"], entry["key_files"]) if value),
            memory_hub_root,
            vault_roots,
        )
    log_candidates = load_log_candidates(
        memory_hub_root,
        projects,
        worklogs,
        open_tasks,
        decision_entries,
        now,
        int(config.get("candidate_scan_days", 45)),
        int(config.get("candidate_max_items", config["max_items_per_section"])),
    )
    for candidate in log_candidates:
        source_path = Path(candidate["source"])
        candidate["source_target"] = evidence_target(source_path, vault_roots)
        candidate["evidence_targets"] = resolve_evidence_targets(
            ";".join(value for value in (candidate["evidence"], candidate["key_files"]) if value),
            memory_hub_root,
            vault_roots,
        )
    task_register = [
        {**task, "ledger_state": formal_task_state(task)}
        for task in tasks
    ]
    task_ledgers = build_task_ledgers(tasks)
    task_ledger_summary = {
        "formal_tasks": len(task_register),
        "formal_open": sum(item["ledger_state"] == "open" for item in task_register),
        "formal_completed": sum(item["ledger_state"] == "completed" for item in task_register),
        "formal_deferred": sum(item["ledger_state"] == "deferred" for item in task_register),
        "structured_sources": len(task_ledgers),
        "total": sum(item["total"] for item in task_ledgers),
        "completed": sum(item["completed"] for item in task_ledgers),
        "deferred": sum(item["deferred"] for item in task_ledgers),
        "open": sum(item["open"] for item in task_ledgers),
        "needs_review": sum(item["needs_review"] for item in task_ledgers),
        "conserved": all(item["conserved"] for item in task_ledgers),
    }
    omission_findings = build_omission_findings(
        tasks, task_ledgers, log_candidates, worklogs
    )
    confirmation_queue = build_confirmation_queue(
        decision_entries, log_candidates, omission_findings
    )
    this_week_projects = [project for project in classified_projects if project["operating_state"] == "本周推进"]
    pending_projects = [
        project for project in classified_projects if project["operating_state"] == "待验收/待决策"
    ]
    recently_completed_projects = [
        project for project in classified_projects if project["operating_state"] == "近期完成"
    ]
    projects_to_verify = sorted(
        (project for project in classified_projects if project["bucket"] == "待核实 / 停滞"),
        key=lambda project: (
            0 if any(keyword in project["project"] for keyword in ("思维助手", "数字人")) else 1,
            project["project"],
        ),
    )
    indexed_active_projects = [project for project in projects if project["status"] == "活跃"]
    latest_worklog_path = max(
        (Path(entry["source"]) for entry in worklogs), key=lambda path: path.name, default=None
    )
    activity_paths = sorted((memory_hub_root / "10-Daily").glob("20??-??-??-ai-activity.md"))
    latest_activity_path = activity_paths[-1] if activity_paths else None
    sources = [
        source_state("当前任务", current_tasks_file, now, int(config["stale_source_days"])),
        source_state("项目索引", project_index_file, now, int(config["stale_source_days"])),
        source_state("能力地图", capability_map_file, now, int(config["stale_source_days"])),
        source_state("决策闭环台账", decision_resolution_file, now, int(config["stale_source_days"])),
    ]
    if latest_worklog_path:
        sources.append(source_state("最近正式工作日志", latest_worklog_path, now, int(config["stale_source_days"])))
    if latest_activity_path:
        sources.append(source_state("最近 AI 活动索引", latest_activity_path, now, int(config["stale_source_days"])))
    snapshot: dict[str, Any] = {
        "generated_at": now.isoformat(timespec="seconds"),
        "windows": {
            "recent_work_days": int(config["recent_work_days"]),
            "project_review_days": int(config["project_review_days"]),
            "activity_signal_days": int(config["activity_signal_days"]),
            "candidate_scan_days": int(config.get("candidate_scan_days", 45)),
        },
        "metrics": {
            "confirmed_focus": len(recent_focus),
            "discovered_projects": sum(row.get('active_candidate', True) for row in activity_discovery['discovered']),
            "discovery_review": len(activity_discovery['review']),
            "open_tasks": len(open_tasks),
            "blocked_tasks": sum(task["blocked"] for task in open_tasks),
            "overdue_tasks": sum(task["overdue"] for task in open_tasks),
            "indexed_active_projects": len(indexed_active_projects),
            "this_week_projects": len(this_week_projects),
            "pending_projects": len(pending_projects),
            "recently_completed_projects": len(recently_completed_projects),
            "projects_to_verify": len(projects_to_verify),
            "decision_queue": len(decision_entries),
            "resolved_decisions": len(resolved_decisions),
            "emerging_projects": len(emerging_projects),
            "log_candidates": len(log_candidates),
            "task_ledger_items": task_ledger_summary["total"],
            "task_ledger_open": task_ledger_summary["open"],
            "task_ledger_deferred": task_ledger_summary["deferred"],
            "omission_findings": len(omission_findings),
            "confirmation_queue": len(confirmation_queue),
            "capability_gaps": len(capability_gaps),
            "p0_capability_gaps": sum("P0" in gap["priority"] for gap in capability_gaps),
            "meeting_actions_to_verify": len(actions),
            "recent_meetings": len(meetings),
        },
        "current_tasks": open_tasks,
        "recent_focus": recent_focus,
        "project_brief_health": brief_health,
        "activity_discovery": activity_discovery,
        "discovered_projects": activity_discovery['discovered'],
        "task_register": task_register,
        "task_ledgers": task_ledgers,
        "task_ledger_summary": task_ledger_summary,
        "omission_findings": omission_findings,
        "confirmation_queue": confirmation_queue,
        "recent_worklogs": sorted(
            recent_worklogs, key=lambda item: item["updated_at"] or item["date"], reverse=True
        ),
        "decision_entries": sorted(
            decision_entries, key=lambda item: item["updated_at"] or item["date"], reverse=True
        ),
        "resolved_decisions": sorted(
            resolved_decisions, key=lambda item: item["updated_at"] or item["date"], reverse=True
        ),
        "decision_resolutions": valid_resolutions,
        "projects": classified_projects,
        "this_week_projects": this_week_projects,
        "pending_projects": pending_projects,
        "recently_completed_projects": recently_completed_projects,
        "projects_to_verify": projects_to_verify,
        "emerging_projects": emerging_projects,
        "log_candidates": log_candidates,
        "capabilities": capabilities,
        "capability_gaps": capability_gaps,
        "meeting_actions": actions,
        "recent_job_notes": recent_job_notes(
            job_knowledge_folder, job_vault_root, int(config["max_items_per_section"])
        ),
        "meeting_topics": topic_counts(meetings),
        "sources": [
            {
                "label": state.label,
                "path": str(state.path),
                "modified_at": state.modified_at.isoformat(timespec="seconds"),
                "age_days": state.age_days,
                "stale": state.stale,
            }
            for state in sources
        ],
        "integration": {
            "mode": "read_only",
            "source_count": len(sources),
            "stale_source_count": sum(state.stale for state in sources),
            "latest_source_modified_at": max(
                (state.modified_at for state in sources), default=now
            ).isoformat(timespec="seconds"),
        },
    }
    apply_lifecycle(snapshot, config)
    enrich_work_cycle(snapshot, config)
    snapshot["recommendations"] = recommendation_rules(snapshot)
    return snapshot


def escape_cell(value: str) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def portfolio_domain(project: dict[str, Any]) -> str:
    identity = project.get("wikilink") or project.get("project", "")
    for domain, project_names in PORTFOLIO_DOMAINS.items():
        if identity in project_names or project.get("project") in project_names:
            return domain
    return "其他项目"


def portfolio_bucket(project: dict[str, Any]) -> str:
    state = str(project.get("operating_state", ""))
    formal = str(project.get("status", ""))
    if state in {"本周推进", "近期有进展"}:
        return "正在推进"
    if state in {"待验收/待决策", "待确认"} or formal == "待确认":
        return "等待判断"
    if state == "待核实":
        return "待核实 / 停滞"
    if state in {"近期完成", "阶段完成", "待归档"} or formal == "阶段完成":
        return "阶段成果"
    if state in {"参考", "历史", "legacy"} or formal in {"参考", "历史", "legacy"}:
        return "非当前项目"
    return "待核实 / 停滞"


def project_links(projects: list[dict[str, Any]]) -> str:
    if not projects:
        return "—"
    return "<br>".join(project_link(project) for project in projects)


def project_link(project: dict[str, Any]) -> str:
    if project["project"] == project["wikilink"]:
        return f"[[{project['wikilink']}]]"
    return f"[[{project['wikilink']}|{project['project']}]]"


def target_link(target: dict[str, Any]) -> str:
    if target.get("uri"):
        return f"[{target['label']}]({target['uri']})"
    if target.get("path"):
        return f"`{target['path']}`"
    return "—"


def candidate_evidence(candidate: dict[str, Any]) -> str:
    targets = candidate.get("evidence_targets", [])
    if targets:
        return "<br>".join(target_link(target) for target in targets[:2])
    return escape_cell(candidate.get("evidence") or candidate.get("key_files") or "—")


def render_workbench(snapshot: dict[str, Any], config: dict[str, Any]) -> str:
    metrics = snapshot["metrics"]
    max_items = int(config["max_items_per_section"])
    buckets = ("正在推进", "等待判断", "待核实 / 停滞", "阶段成果", "新信号")
    domains = list(PORTFOLIO_DOMAINS) + ["其他项目"]
    grouped: dict[str, dict[str, list[dict[str, Any]]]] = {
        domain: {bucket: [] for bucket in (*buckets, "非当前项目")} for domain in domains
    }
    for project in snapshot["projects"]:
        grouped[portfolio_domain(project)][portfolio_bucket(project)].append(project)
    for project in snapshot["emerging_projects"]:
        grouped["其他项目"]["新信号"].append(
            {"wikilink": project["name"], "project": project["name"]}
        )

    state_counts = {
        bucket: sum(len(grouped[domain][bucket]) for domain in domains) for bucket in buckets
    }
    if metrics["decision_queue"]:
        directive = "关闭一个判断环节，让项目重新流动。"
        directive_basis = f"当前有 {metrics['decision_queue']} 项正式记录等待确认；先完成一个决定，再开启新的开发线。"
    elif state_counts["待核实 / 停滞"]:
        directive = "清理一个悬空项目，恢复组合可信度。"
        directive_basis = f"当前有 {state_counts['待核实 / 停滞']} 个项目需要核实状态、证据或生命周期。"
    else:
        directive = "保持唯一主线，用证据推进下一步。"
        directive_basis = "当前没有显著判断拥堵，优先维护正在推进项目的下一项可验收成果。"

    focus = snapshot.get('recent_focus', [])
    if focus:
        directive = '近期重点：' + '、'.join(item['task'] for item in focus)
        directive_basis = '对话活动与正式验收分别呈现；点击来源核对最新进展与未完成项。'
    lines = [
        "---",
        "title: 个人运营工作台",
        "type: dashboard",
        f"generated: {snapshot['generated_at']}",
        "cssclasses:",
        "  - portfolio-control-tower",
        "tags:",
        "  - dashboard",
        "  - personal-operations",
        "---",
        "",
        "# 个人运营工作台",
        "",
        f"> [!info] 派生视图 · `{snapshot['generated_at']}`",
        "> 本页与外部 Web 工作台共享项目组合语义；以正式项目页、收工回执和工作日志为依据，不反向改写源知识。",
        "",
        "## 01 · 当前主线与组合总览",
        "",
        "> [!abstract] 当前唯一主线",
        f"> **{directive}**",
        f"> {directive_basis}",
        "",
        "| 正在推进 | 等待判断 | 待核实 / 停滞 | 阶段成果 | 新信号 | 当前决策事项 | 日志候选 |",
        "|---:|---:|---:|---:|---:|---:|---:|",
        f"| **{state_counts['正在推进']}** | **{state_counts['等待判断']}** | **{state_counts['待核实 / 停滞']}** | **{state_counts['阶段成果']}** | **{state_counts['新信号']}** | **{metrics['decision_queue']}** | **{metrics['log_candidates']}** |",
        "",
        "> [!warning] 计数口径",
        "> 前五项按项目计数；“当前决策事项”按正式任务/交付记录计数，两者不可相加。项目阶段成果不等于持续项目结束。",
        f"> 任务总账覆盖 {metrics['task_ledger_items']} 个结构化清单项，其中 {metrics['task_ledger_open']} 项未闭环、{metrics['task_ledger_deferred']} 项延期保留；自动防漏 {metrics['omission_findings']} 条，人工确认队列 {metrics['confirmation_queue']} 条。",
        "",
        "## 02 · 项目组合态势",
        "",
        "横向看项目运营状态，纵向看工作领域。空白表示当前没有正式证据，不用虚假完成率填充。",
        "",
        "| 工作领域 | 正在推进 | 等待判断 | 待核实 / 停滞 | 阶段成果 | 新信号 |",
        "|---|---|---|---|---|---|",
    ]
    if focus:
        section = ['### 近期重点跟进', '',
            '| 重点 | 最近对话时间 | 进展摘录（待核实） | 来源 |',
            '| --- | --- | --- | --- |']
        section.extend(f"| {escape_cell(item['task'])} | {item['updated_at']} | {escape_cell(item['progress'])} | {item['source_target']['path']} |"
            for item in focus)
        section.append('')
        position = lines.index('## 02 · 项目组合态势')
        lines[position:position] = section
    discovered = snapshot.get('discovered_projects', [])
    if discovered:
        section = ['### 自动发现的近期项目', '',
            '> 按活动证据排序，不代表业务重要性；已交付且没有新推进的项目单独标记。', '',
            '| 项目 | 活动判断 | 最近动作 | 发现依据 |',
            '| --- | --- | --- | --- |']
        section.extend(f"| {escape_cell(item['task'])} | {item['status']} | {escape_cell(item['progress'])} | {escape_cell(item['discovery_reason'])} |"
            for item in discovered)
        section.append('')
        position = lines.index('## 02 · 项目组合态势')
        lines[position:position] = section
    for domain in domains:
        cells = [project_links(grouped[domain][bucket]) for bucket in buckets]
        lines.append(f"| **{domain}** | " + " | ".join(cells) + " |")

    lines.extend(
        [
            "",
            "> [!important] 项目状态边界",
            "> “索引为活跃”不等于“当前推进”。只有近期正式证据才进入正在推进；状态冲突、证据过期或验收悬空进入待核实。项目页缺少统一里程碑和完成证据时，仍不生成虚假的完成率。",
            "",
            "### 最近成果",
            "",
            "| 项目 | 最近证据 | 已形成的阶段成果 | 下一步边界 |",
            "|---|---|---|---|",
        ]
    )
    for project in snapshot["recently_completed_projects"][:max_items]:
        lines.append(
            f"| {project_link(project)} | {project['latest_evidence_date'] or '未找到'} | {escape_cell(project['state_reason'])} | {escape_cell(project['decision'])} |"
        )
    if not snapshot["recently_completed_projects"]:
        lines.append("| - | - | 近期没有正式阶段成果 | - |")

    ledger_summary = snapshot["task_ledger_summary"]
    lines.extend(
        [
            "",
            "### 任务总账",
            "",
            f"> 当前正式任务表共 {ledger_summary['formal_tasks']} 条，其中开放 {ledger_summary['formal_open']} 条。结构化范围清单按原始编号守恒，延期或排除事项保留在账，不计完成但不会消失。",
            "",
            "| 结构化清单 | 原始总数 | 已完成 | 延期保留 | 未闭环 | 需复核 | 守恒校验 | 来源 |",
            "|---|---:|---:|---:|---:|---:|---|---|",
        ]
    )
    for ledger in snapshot["task_ledgers"]:
        lines.append(
            f"| {escape_cell(ledger['title'])} | {ledger['total']} | {ledger['completed']} | {ledger['deferred']} | {ledger['open']} | {ledger['needs_review']} | {'通过' if ledger['conserved'] else '异常'} | {target_link(ledger['source_target'])} |"
        )
    if not snapshot["task_ledgers"]:
        lines.append("| - | 0 | 0 | 0 | 0 | 0 | 暂无结构化范围清单 | - |")

    lines.extend(
        [
            "",
            "#### 自动防漏规则",
            "",
            "> 已启用：原始范围守恒、缩小范围保留、元数据与逐项状态一致、阶段完成仍有后续、开放任务负责人和证据完整性。规则只生成告警，不自动改写正式任务。",
            "",
            "| 优先级 | 规则 | 事项 | 触发原因 | 下一动作 |",
            "|---|---|---|---|---|",
        ]
    )
    for finding in snapshot["omission_findings"][:max_items]:
        lines.append(
            f"| {finding['priority']} | {finding['rule']} | {escape_cell(finding['title'])} | {escape_cell(finding['reason'])} | {escape_cell(finding['next_action'])} |"
        )
    if not snapshot["omission_findings"]:
        lines.append("| - | - | 当前未发现自动防漏异常 | - | - |")

    lines.extend(
        [
            "",
            "### 人工确认队列",
            "",
            f"> 共 **{metrics['confirmation_queue']} 条**；合并正式决策、日志候选和防漏告警，并按回执/事项去重。确认前保持只读，不自动立项或关闭。",
            "",
            "| 优先级 | 类型 | 事项 | 当前原因 | 建议确认动作 | 来源 |",
            "|---|---|---|---|---|---|",
        ]
    )
    for item in snapshot["confirmation_queue"][:max_items]:
        lines.append(
            f"| {item['priority']} | {item['kind']} | {escape_cell(item['title'])} | {escape_cell(item['reason'])} | {escape_cell(item['next_action'])} | {target_link(item.get('source_target', {}))} |"
        )
    if not snapshot["confirmation_queue"]:
        lines.append("| - | - | 当前没有需要人工确认的事项 | - | - | - |")

    lines.extend(
        [
            "",
            "### 当前决策",
            "",
            f"> 当前共识别 **{metrics['decision_queue']} 项**等待判断的正式记录；首页只展示最高优先级的 {max_items} 项。",
            "",
            "| 日期 | 交付 / 任务 | 当前状态 | 下一动作 |",
            "|---|---|---|---|",
        ]
    )
    for entry in snapshot["decision_entries"][:max_items]:
        lines.append(
            f"| {entry['date']} | {escape_cell(entry['title'])} | {escape_cell(entry['status'])} | {escape_cell(entry['next_action'])} |"
        )
    if not snapshot["decision_entries"]:
        lines.append("| - | 当前没有等待判断的正式记录 | - | - |")

    lines.extend(
        [
            "",
            "### 日志发现候选（待你核实）",
            "",
            f"> 只读扫描近 {snapshot['windows']['candidate_scan_days']} 天的正式工作日志和每日计划；候选未被当前项目、任务或决策队列覆盖，不自动改变项目状态。正式完成回执优先于旧计划。",
            "",
            "| 日期 | 候选事项 | 线索类型 | 当前线索 | 下一动作 | 来源 | 证据 |",
            "|---|---|---|---|---|---|---|",
        ]
    )
    for candidate in snapshot["log_candidates"]:
        lines.append(
            f"| {candidate['date']} | {escape_cell(candidate['title'])} | {escape_cell(candidate['candidate_kind'])} | {escape_cell(candidate['status'])} | {escape_cell(candidate['next_action'])} | {target_link(candidate['source_target'])} | {candidate_evidence(candidate)} |"
        )
    if not snapshot["log_candidates"]:
        lines.append("| - | 当前没有未被正式来源覆盖的日志候选 | - | - | - | - | - |")

    non_current = [
        project
        for domain in domains
        for project in grouped[domain]["非当前项目"]
    ]
    lines.extend(
        [
            "",
            "### 非当前项目",
            "",
            "| 项目 | 正式状态 | 当前边界 |",
            "|---|---|---|",
        ]
    )
    for project in non_current:
        lines.append(
            f"| {project_link(project)} | {escape_cell(project['status'])} | {escape_cell(project['decision'])} |"
        )
    if not non_current:
        lines.append("| - | 当前没有参考、历史或 legacy 项目 | - |")

    lines.extend(
        [
            "",
            "## 03 · 知识与方法",
            "",
            "### 能力与方法证据",
            "",
            "| 能力域 | 当前成熟度 | 证据 | 判断 |",
            "|---|---|---|---|",
        ]
    )
    for capability in snapshot["capabilities"]:
        lines.append(
            f"| {escape_cell(capability['domain'])} | {escape_cell(capability['maturity'])} | {escape_cell(capability['evidence'])} | {escape_cell(capability['judgement'])} |"
        )
    lines.extend(
        [
            "",
            "> [!note] 证据阶梯",
            "> 成熟度按“能解释 → 做过一次 → 多次复用 → 形成 SOP/Skill → 跨场景迁移”判断，不能按笔记数量自动打分。",
            "",
            "### 当前优先能力空白",
            "",
            "| 优先级 | 能力空白 | 业务价值 |",
            "|---|---|---|",
        ]
    )
    for gap in snapshot["capability_gaps"][:max_items]:
        lines.append(
            f"| {escape_cell(gap['priority'])} | {escape_cell(gap['capability'])} | {escape_cell(gap['importance'])} |"
        )
    lines.extend(["", "### 最近更新的岗位知识", ""])
    for note in snapshot["recent_job_notes"][:max_items]:
        lines.append(f"- {note['link']} · `{note['modified'][:10]}`")

    lines.extend(
        [
            "",
            "## 04 · 证据与审计",
            "",
            "### 事实、推断与建议",
            "",
            "| 优先级 | 认识类型 | 建议 | 依据 | 下一动作 | 停止条件 |",
            "|---|---|---|---|---|---|",
        ]
    )
    for item in snapshot["recommendations"]:
        lines.append(
            "| {priority} | {type} | {recommendation} | {basis} | {next_action} | {stop_condition} |".format(
                **{key: escape_cell(value) for key, value in item.items()}
            )
        )
    lines.extend(
        [
            "",
            "### 数据新鲜度与审计",
            "",
            "| 来源 | 最后修改 | 距今天 | 状态 | 路径 |",
            "|---|---|---:|---|---|",
        ]
    )
    for source in snapshot["sources"]:
        status = "⚠️ 超过阈值" if source["stale"] else "✅ 阈值内"
        lines.append(
            f"| {source['label']} | {source['modified_at'][:10]} | {source['age_days']} 天 | {status} | `{source['path']}` |"
        )

    lines.extend(
        [
            "",
            "## 05 · 待核对附录",
            "",
            "> [!warning] 待核对，不等于未完成",
            "> 当前任务投影和会议行动可能落后于正式项目页。以下记录用于对账，不能直接改变项目状态。",
            "",
            "### 当前任务投影",
            "",
            "| 状态 | 任务 | 主 Agent | 证据 |",
            "|---|---|---|---|",
        ]
    )
    for task in snapshot["current_tasks"][:max_items]:
        lines.append(
            f"| {escape_cell(task['status'])} | {escape_cell(task['task'])} | {escape_cell(task['agent'])} | {escape_cell(task['evidence'])} |"
        )
    if not snapshot["current_tasks"]:
        lines.append("| - | 当前任务投影没有未完成事项 | - | - |")

    lines.extend(
        [
            "",
            "### 会议行动对账",
            "",
            "| 会议日期 | 行动项 | 角色 | 原记录日期 | 来源 |",
            "|---|---|---|---|---|",
        ]
    )
    for action in snapshot["meeting_actions"][:max_items]:
        role = f"负责人：{action['owner']}"
        if action["collaborator"]:
            role += f"；协作：{action['collaborator']}"
        lines.append(
            f"| {action['meeting_date']} | {escape_cell(action['action'])} | {escape_cell(role)} | {escape_cell(action['due'])} | {action['source_link']} |"
        )
    if not snapshot["meeting_actions"]:
        lines.append("| - | 近期会议中未识别到涉及你的结构化行动项 | - | - | - |")

    lines.extend(
        [
            "",
            "### 使用节奏",
            "",
            "- **每天 5 分钟**：关闭一个判断，确认当天唯一主推进，收工时写清证据、未完成和下一动作。",
            "- **每周 30 分钟**：对待核实项目做一次生命周期决定，在制主线不超过 3 个。",
            "- **新思路进入项目的四个条件**：服务对象、真实场景、最小验收问题集、下一里程碑与停止条件。",
            "",
            "---",
            "",
            "刷新命令：",
            "",
            "```powershell",
            "python \"scripts/build_operations_dashboard.py\"",
            "```",
            "",
            "[[当前任务]] · [[项目索引]] · [[多Agent协同看板]]",
            "",
        ]
    )
    return "\n".join(lines)


def render_apex_dashboard(snapshot: dict[str, Any]) -> str:
    metrics = snapshot["metrics"]
    recommendations = snapshot["recommendations"][:3]
    project_cards = (snapshot["this_week_projects"] + snapshot["pending_projects"])[:6]
    lines = [
        "---",
        "dashboard: true",
        "banner:",
        '  quote: "不靠记忆管理工作，靠证据决定下一步。"',
        '  author: "个人运营工作台"',
        "columns:",
        "  - name: 运营指挥台",
        '    color: "#f59e0b"',
        "    type: memo",
        "  - name: 待决策与核实",
        '    color: "#ef4444"',
        "    type: memo",
        "  - name: 待验收项目",
        '    color: "#10b981"',
        "    type: projects",
        "  - name: 新工作与入口",
        '    color: "#6366f1"',
        "    type: notes",
        "---",
        "",
        "## 运营指挥台",
        "",
        "### 打开完整工作台",
        "id: operations-workbench",
        "[[50-Agent-Workflows/00-Dashboard/个人运营工作台]]",
        "",
        "### 当前快照",
        "id: operations-snapshot",
        f"本周推进 {metrics['this_week_projects']} · 任务总账 {metrics['task_ledger_items']} 项（未闭环 {metrics['task_ledger_open']}、延期 {metrics['task_ledger_deferred']}）· 自动防漏 {metrics['omission_findings']} 条 · 人工确认 {metrics['confirmation_queue']} 条。",
        "",
        "### 本周 1+1+1",
        "id: weekly-111",
        "1 个主推进 · 1 个交付验收 · 1 个悬空项目决定；在制主线不超过 3 个。",
        "",
        "### 使用边界",
        "id: operations-boundary",
        "Apex 是入口；项目、会议和能力结论以完整工作台中的来源与证据为准。",
        "",
        "## 待决策与核实",
        "",
    ]
    for index, item in enumerate(recommendations, start=1):
        lines.extend(
            [
                f"### {item['priority']} · {item['recommendation']}",
                f"id: recommendation-{index}",
                f"依据：{item['basis']} 下一步：{item['next_action']}",
                "",
            ]
        )
    for index, project in enumerate(snapshot["projects_to_verify"][:3], start=1):
        lines.extend(
            [
                f"### 待核实 · {project['project']}",
                f"id: verify-project-{index}",
                f"{project['state_reason']} {project['decision']}",
                "",
            ]
        )
    lines.extend(["## 任务总账与人工确认", ""])
    for index, ledger in enumerate(snapshot["task_ledgers"][:3], start=1):
        lines.extend(
            [
                f"### 总账 · {ledger['title']}",
                f"id: task-ledger-{index}",
                f"原始 {ledger['total']} = 完成 {ledger['completed']} + 延期 {ledger['deferred']} + 未闭环 {ledger['open']}；守恒校验：{'通过' if ledger['conserved'] else '异常'}。",
                "",
            ]
        )
    for index, item in enumerate(snapshot["confirmation_queue"][:3], start=1):
        lines.extend(
            [
                f"### {item['priority']} · {item['kind']} · {item['title']}",
                f"id: confirmation-{index}",
                f"{item['reason']} 下一步：{item['next_action']}",
                "",
            ]
        )
    lines.extend(["## 日志发现候选", ""])
    for index, candidate in enumerate(snapshot["log_candidates"][:3], start=1):
        lines.extend(
            [
                f"### 待核实 · {candidate['title']}",
                f"id: log-candidate-{index}",
                f"{candidate['candidate_kind']}；{candidate['status']}；下一步：{candidate['next_action']}",
                "",
            ]
        )
    if not snapshot["log_candidates"]:
        lines.extend(["当前没有未被正式来源覆盖的日志候选。", ""])
    lines.extend(["## 待验收项目", ""])
    for index, project in enumerate(project_cards, start=1):
        lines.extend(
            [
                f"### {project['project']}",
                f"id: current-project-{index}",
                "type: project",
                project_link(project),
                "",
            ]
        )
    lines.extend(
        [
            "## 新工作与入口",
            "",
        ]
    )
    for index, project in enumerate(snapshot["emerging_projects"], start=1):
        lines.extend(
            [
                f"### {project['status']} · {project['name']}",
                f"id: emerging-project-{index}",
                f"{project['decision']}",
                "",
            ]
        )
    lines.extend(
        [
            "### 当前任务",
            "id: quick-current-tasks",
            "type: project",
            "[[50-Agent-Workflows/00-Dashboard/当前任务]]",
            "",
            "### 项目索引",
            "id: quick-project-index",
            "type: project",
            "[[20-Projects/项目索引]]",
            "",
            "### 多 Agent 协同看板",
            "id: quick-agent-dashboard",
            "type: project",
            "[[50-Agent-Workflows/00-Dashboard/多Agent协同看板]]",
            "",
        ]
    )
    return "\n".join(lines)


def write_snapshot(snapshot: dict[str, Any], config: dict[str, Any]) -> None:
    snapshot_path = Path(config["snapshot_output"])
    temporary_path = snapshot_path.with_suffix(f"{snapshot_path.suffix}.tmp")
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary_path.replace(snapshot_path)


def write_outputs(snapshot: dict[str, Any], config: dict[str, Any]) -> None:
    dashboard_path = Path(config["dashboard_output"])
    apex_path = Path(config["apex_dashboard_output"])
    dashboard_path.parent.mkdir(parents=True, exist_ok=True)
    write_snapshot(snapshot, config)
    dashboard_path.write_text(render_workbench(snapshot, config), encoding="utf-8")
    if apex_path.exists():
        backup_dir = apex_path.parent / ".dashboard-backup"
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_path = backup_dir / "dashboard-before-personal-operations.md"
        if not backup_path.exists():
            shutil.copy2(apex_path, backup_path)
    apex_path.write_text(render_apex_dashboard(snapshot), encoding="utf-8")


def validate_config(config: dict[str, Any]) -> None:
    required_inputs = (
        "current_tasks_file",
        "project_index_file",
        "capability_map_file",
        "job_knowledge_folder",
    )
    missing = [key for key in required_inputs if not Path(config[key]).exists()]
    if missing:
        raise FileNotFoundError(f"缺少输入路径：{', '.join(missing)}")


def main() -> int:
    project_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="生成个人运营工作台与可审计运营快照。")
    parser.add_argument(
        "--config",
        default=str(project_root / "config" / "operations_dashboard.json"),
        help="配置文件路径",
    )
    parser.add_argument("--check", action="store_true", help="只构建并校验，不写文件")
    parser.add_argument(
        "--snapshot-only",
        action="store_true",
        help="只更新工作台快照，不写入任何 Obsidian 派生视图",
    )
    args = parser.parse_args()
    config = json.loads(read_text(Path(args.config)))
    validate_config(config)
    snapshot = build_snapshot(config)
    workbench = render_workbench(snapshot, config)
    if "个人运营工作台" not in workbench or not snapshot["sources"]:
        raise RuntimeError("生成结果缺少核心区块或来源审计。")
    if not args.check:
        if args.snapshot_only:
            write_snapshot(snapshot, config)
        else:
            write_outputs(snapshot, config)
    print(
        json.dumps(
            {
                "status": "ok",
                "check_only": args.check,
                "snapshot_only": args.snapshot_only,
                "metrics": snapshot["metrics"],
                "dashboard_output": config["dashboard_output"],
                "snapshot_output": config["snapshot_output"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
