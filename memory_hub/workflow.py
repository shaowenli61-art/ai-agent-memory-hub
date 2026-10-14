from __future__ import annotations

import json
import shutil
import hashlib
import os
import re
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
    configured = (vault / '.memory-hub/workbench-config.json').exists()
    if configured:
        from memory_hub.workbench import refresh_snapshot
        snapshot = refresh_snapshot(vault)
    path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    dashboard = vault / ('.memory-hub/runtime/public-current-tasks.md' if configured else '50-Agent-Workflows/00-Dashboard/当前任务.md')
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


def _close_task(
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
    project: str = "",
    remaining: str = "未登记",
    risks: str = "无",
    avoid_repeat: str = "无",
    verification: str = "",
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
        "project": project,
    }
    formal = None
    if project:
        from memory_hub.workbench import load_config
        from scripts.build_operations_dashboard import load_projects
        config = load_config(vault)
        row = next((p for p in load_projects(Path(config['project_index_file'])) if p['project'] == project), None)
        if not row:
            raise ValueError('项目未登记；先运行 memory_hub project 接入项目目录。')
        page = vault / '20-Projects' / f"{row['wikilink']}.md"
        if not page.is_file():
            raise ValueError('项目页缺失，不能生成可信项目回执。')
        identity = re.search(r'^project_id:\s*(.+)$',page.read_text(encoding='utf-8'),re.M)
        if not identity:
            raise ValueError('项目页缺少 project_id；请核对后补充稳定身份。')
        project_id = identity.group(1).strip().strip('"\'')
        moment = datetime.now().astimezone().isoformat(timespec='seconds')
        event['receipt_id'] = f'MC-{day:%Y%m%d}-{uuid4().hex[:12]}'
        states = dict(active='进行中',completed='已完成',**{'stage-complete':'阶段完成'},waiting='等待用户',blocked='受阻',handoff='待接手',terminated='已终止')
        formal = dict(schema_version=3,receipt_id=event['receipt_id'],task_id='TK-'+uuid4().hex,
            timestamp=moment,project_id=project_id,scope='project:'+project_id,project_page=str(page),
            task=task,state=states[status],completed=completed,remaining=remaining,next_action=next_action,
            files=';'.join(str((vault/Path(item)).resolve()) if not Path(item).is_absolute() else item for item in evidence),
            evidence=';'.join(evidence),risks=risks,avoid_repeat=avoid_repeat,agent=agent,verification=verification)
        formal['record_hash'] = hashlib.sha256(json.dumps(formal,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
    log = _event_log(vault)
    log.parent.mkdir(parents=True, exist_ok=True)
    from scripts.file_write_guard import safe_write_text
    backups = vault / '.memory-hub/backups/close'
    old = log.read_text(encoding='utf-8') if log.exists() else ''
    safe_write_text(log,old+json.dumps(event,ensure_ascii=False)+'\n',agent or 'Agent',event['receipt_id'],backups)
    if formal:
        receipts = vault / '50-Agent-Workflows/90-Logs/memory-close-receipts.jsonl'
        old = receipts.read_text(encoding='utf-8') if receipts.exists() else ''
        safe_write_text(receipts,old+json.dumps(formal,ensure_ascii=False)+'\n',agent or 'Agent',event['receipt_id'],backups)
    daily = vault / "10-Daily" / f"{day.isoformat()}-worklog.md"
    daily.parent.mkdir(parents=True, exist_ok=True)
    if not daily.exists():
        daily.write_text(f"# {day.isoformat()} Worklog\n", encoding="utf-8")
    safe_write_text(daily,daily.read_text(encoding='utf-8')+(
            f"\n## 任务收工：{task}\n\n"
            f"- **当前状态**：{formal['state'] if formal else status}\n"
            f"- **本次完成**：{completed}\n"
            f"- **尚未完成**：{remaining}\n"
            f"- **下一步动作**：{next_action}\n"
            f"- **验证方式与结果**：{verification or '未单独登记验证结果'}\n"
            f"- **证据路径**：{'; '.join(evidence) if evidence else '未附证据'}\n"
            f"- **更新时间与 Agent**：{datetime.now().astimezone().isoformat(timespec='seconds')} / {agent or '未登记'}\n"
            f"- **关键文件**：{formal['files'] if formal else '; '.join(evidence)}\n"
            f"- **残留风险**：{risks}\n"
            f"- **禁止重踩**：{avoid_repeat}\n"
            f"- **收工回执**：`{event['receipt_id']}`\n"
        ),agent or 'Agent',event['receipt_id'],backups)
    write_snapshot(vault)
    return event


def close_task(**kwargs) -> dict:
    """Serialize closure in this Vault; never steal an existing writer's lock."""
    vault = Path(kwargs['vault']).resolve()
    lock = vault / '.memory-hub/close.lock'
    lock.parent.mkdir(parents=True,exist_ok=True)
    fd = os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
    os.close(fd)
    try:
        kwargs['vault'] = vault
        return _close_task(**kwargs)
    finally:
        lock.unlink()
