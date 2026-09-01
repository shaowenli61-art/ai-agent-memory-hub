from __future__ import annotations

import json
import shutil
from datetime import date, datetime
from pathlib import Path
from uuid import uuid4


COMPLETED_STATUSES = {"completed", "stage-complete", "terminated"}


def _event_log(vault: Path) -> Path:
    return vault / ".memory-hub" / "events" / "task-events.jsonl"


def _snapshot_path(vault: Path) -> Path:
    return vault / ".memory-hub" / "runtime" / "operations_snapshot.json"


def _read_events(vault: Path) -> list[dict]:
    path = _event_log(vault)
    if not path.exists():
        return []
    events: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            events.append(json.loads(line))
    return events


def build_snapshot(vault: Path) -> dict:
    events = _read_events(vault)
    latest_by_task: dict[str, dict] = {}
    for event in events:
        latest_by_task[event["task"]] = event
    current_tasks: list[dict] = []
    completed: list[dict] = []
    for event in latest_by_task.values():
        evidence_targets = [{"label": item, "path": item} for item in event["evidence"]]
        if event["status"] in COMPLETED_STATUSES:
            completed.append(
                {
                    "project": event["task"],
                    "status": event["status"],
                    "next_step": event["next_action"],
                    "latest_evidence_date": event["date"],
                    "bucket": "recently_completed",
                    "evidence_targets": evidence_targets,
                }
            )
        else:
            current_tasks.append(
                {
                    "status": event["status"],
                    "task": event["task"],
                    "agent": event.get("agent", ""),
                    "collaborator": event.get("collaborator", ""),
                    "evidence": "; ".join(event["evidence"]),
                    "next_action": event["next_action"],
                    "source_path": str(_event_log(vault)),
                    "blocked": event["status"] == "blocked",
                    "overdue": False,
                    "open": True,
                    "evidence_targets": evidence_targets,
                    "source_target": str(_event_log(vault)),
                }
            )
    completed.sort(key=lambda item: item["latest_evidence_date"], reverse=True)
    current_tasks.sort(key=lambda item: item["task"])
    return {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "metrics": {
            "open_tasks": len(current_tasks),
            "blocked_tasks": sum(1 for item in current_tasks if item["blocked"]),
            "overdue_tasks": 0,
            "indexed_active_projects": len(current_tasks),
            "this_week_projects": 0,
            "pending_projects": 0,
            "recently_completed_projects": len(completed),
            "projects_to_verify": 0,
            "decision_queue": 0,
            "resolved_decisions": 0,
            "emerging_projects": 0,
            "log_candidates": 0,
            "capability_gaps": 0,
            "p0_capability_gaps": 0,
            "meeting_actions_to_verify": 0,
            "recent_meetings": 0,
        },
        "current_tasks": current_tasks,
        "recent_worklogs": [],
        "decision_entries": [],
        "resolved_decisions": [],
        "decision_resolutions": [],
        "projects": [],
        "this_week_projects": [],
        "pending_projects": [],
        "recently_completed_projects": completed,
        "projects_to_verify": [],
        "emerging_projects": [],
        "log_candidates": [],
        "capabilities": [],
        "capability_gaps": [],
        "meeting_actions": [],
        "recent_job_notes": [],
        "meeting_topics": [],
        "sources": [str(_event_log(vault))],
        "integration": {
            "mode": "local",
            "source_count": 1,
            "stale_source_count": 0,
            "latest_source_modified_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        },
        "recommendations": [],
    }


def write_snapshot(vault: Path) -> Path:
    path = _snapshot_path(vault)
    path.parent.mkdir(parents=True, exist_ok=True)
    snapshot = build_snapshot(vault)
    path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    dashboard = vault / "50-Agent-Workflows" / "00-Dashboard" / "当前任务.md"
    dashboard.parent.mkdir(parents=True, exist_ok=True)
    tasks = snapshot["current_tasks"]
    if tasks:
        rows = [
            f"- [[{item['task']}]] | {item['status']} | 下一步：{item['next_action']} | 证据：{item['evidence'] or '无'}"
            for item in tasks
        ]
        dashboard.write_text("# 当前任务\n\n" + "\n".join(rows) + "\n", encoding="utf-8")
    else:
        dashboard.write_text("# 当前任务\n\n当前没有开放任务。\n", encoding="utf-8")
    web_data = vault / ".memory-hub" / "workbench" / "web" / "data"
    if web_data.exists():
        shutil.copy2(path, web_data / "operations_snapshot.json")
        health = web_data / "integration_health.json"
        if not health.exists():
            health.write_text(
                json.dumps(
                    {
                        "status": "live",
                        "message": "Local snapshot is available",
                        "checked_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                        "watched_sources": 1,
                        "mode": "read_only",
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
    return path


def load_snapshot(vault: Path) -> dict:
    path = _snapshot_path(vault)
    if not path.exists():
        write_snapshot(vault)
    return json.loads(path.read_text(encoding="utf-8"))


def close_task(
    *,
    vault: Path,
    task: str,
    status: str,
    completed: str,
    next_action: str,
    evidence: list[str],
    event_date: date | None = None,
    agent: str = "",
    collaborator: str = "",
) -> dict:
    day = event_date or date.today()
    event = {
        "receipt_id": f"MH-{day:%Y%m%d}-{uuid4().hex[:12]}",
        "date": day.isoformat(),
        "task": task,
        "status": status,
        "completed": completed,
        "next_action": next_action,
        "evidence": evidence,
        "agent": agent,
        "collaborator": collaborator,
    }
    log = _event_log(vault)
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")
    daily = vault / "10-Daily" / f"{day.isoformat()}-worklog.md"
    daily.parent.mkdir(parents=True, exist_ok=True)
    if not daily.exists():
        daily.write_text(f"# {day.isoformat()} Worklog\n", encoding="utf-8")
    with daily.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(
            f"\n## {task}\n\n"
            f"- Status: {status}\n"
            f"- Completed: {completed}\n"
            f"- Next action: {next_action}\n"
            f"- Evidence: {'; '.join(evidence) if evidence else 'None'}\n"
            f"- Receipt: `{event['receipt_id']}`\n"
        )
    write_snapshot(vault)
    return event
