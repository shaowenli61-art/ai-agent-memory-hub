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


def _commit_texts(writes, *, writer, actor, reason, backups):
    """Rollback owned writes on failure; refuse to overwrite a concurrent edit."""
    completed = []
    try:
        for path, original, content in writes:
            current = path.read_bytes() if path.exists() else None
            if current != original:
                raise RuntimeError('收工来源被并发修改；保留原文，刷新后再试。')
            expected = content.encode('utf-8')
            completed.append((path, original, expected))
            writer(path, content, actor, reason, backups)
            if path.read_bytes() != expected:
                raise RuntimeError('收工写入未通过字节校验；保留快照后检查。')
    except Exception as failure:
        conflicts = []
        for path, original, expected in reversed(completed):
            current = path.read_bytes() if path.exists() else None
            if current == original:
                continue
            if current != expected:
                conflicts.append(str(path)); continue
            if original is None:
                path.unlink()
            else:
                path.write_bytes(original)
        if conflicts:
            raise RuntimeError('收工未完成，存在并发版本；不得自动恢复：' + '; '.join(conflicts)) from failure
        raise


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
    task_id: str | None = None,
    revises_receipt_id: str | None = None,
    request_id: str | None = None,
    new_task: bool = False,
    growth_events: tuple[str, ...] = (),
    growth_impact: str = "unknown",
    growth_impact_reason: str = "",
    growth_reviewer=None,
) -> dict:
    day = event_date or date.today()
    prior_events = _read_events(vault)
    request_payload = dict(task=task, status=status, completed=completed, next_action=next_action,
        evidence=evidence, agent=agent, collaborator=collaborator, project=project,
        remaining=remaining, risks=risks, avoid_repeat=avoid_repeat, verification=verification,
        task_id=task_id, revises_receipt_id=revises_receipt_id, new_task=new_task,
        growth_events=list(growth_events), growth_impact=growth_impact, growth_impact_reason=growth_impact_reason)
    request_hash = hashlib.sha256(json.dumps(request_payload, ensure_ascii=False,
        sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    if request_id:
        previous_request = next((r for r in prior_events if r.get('request_id') == request_id), None)
        if previous_request:
            if previous_request.get('request_hash') != request_hash:
                raise ValueError('request_id 已用于不同收工内容；请核对或使用新请求键。')
            daylog = vault / '10-Daily' / (previous_request['date'] + '-worklog.md')
            if not daylog.exists() or previous_request['receipt_id'] not in daylog.read_text(encoding='utf-8'):
                raise RuntimeError('原请求未完整提交；保留写前快照并恢复缺失日志，不能当作已完成。')
            if previous_request.get('project'):
                source = vault / '50-Agent-Workflows/90-Logs/memory-close-receipts.jsonl'
                rows = [json.loads(line) for line in source.read_text(encoding='utf-8-sig').splitlines() if line.strip()] if source.exists() else []
                formal_previous = next((r for r in rows if r.get('receipt_id') == previous_request['receipt_id']), None)
                if not formal_previous:
                    raise RuntimeError('原请求缺少正式回执；请从写前快照恢复，不重复认证成功。')
                from memory_growth.receipts import require_valid_formal_receipt
                require_valid_formal_receipt(formal_previous)
            return dict(previous_request, replayed_request=True)
    revised = next((r for r in prior_events if r['receipt_id'] == revises_receipt_id), None) if revises_receipt_id else None
    if revises_receipt_id and (not revised or not revised.get('task_id')):
        raise ValueError('修订回执不存在或缺少稳定 task_id；不能自动推断历史身份。')
    if revised:
        if task_id and task_id != revised['task_id']:
            raise ValueError('task_id 与修订回执冲突。')
        task_id = revised['task_id']
    if new_task and (task_id or revises_receipt_id):
        raise ValueError('new_task 不能与已有任务身份混用。')
    explicit = bool(task_id or new_task)
    if task_id and not re.fullmatch(r'TK-[A-Za-z0-9_.-]{1,120}', task_id):
        raise ValueError('task_id 必须为 TK- 开头的稳定标识。')
    if not task_id and not new_task:
        prior = next((r for r in reversed(prior_events) if r['task'] == task
            and r.get('project', '') == project and r.get('agent', '') == agent), None)
        task_id = prior.get('task_id') if prior else None
    task_id = task_id or 'TK-' + uuid4().hex
    episode = [r for r in prior_events if r.get('task_id') == task_id]
    if any(r['task'] != task or r.get('project', '') != project for r in episode):
        raise ValueError('同一 task_id 不能跨任务或项目复用。')
    previous = episode[-1] if episode else None
    if revised and previous and revised['receipt_id'] != previous['receipt_id']:
        raise ValueError('任务已有更新回执；旧复盘不能替代最新更正，请先读取新版本。')
    moment = datetime.now().astimezone().isoformat(timespec='microseconds')
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
        "schema_version": 2,
        "timestamp": moment,
        "task_id": task_id,
        "identity_state": "explicit" if explicit else "identity_unresolved",
        "revision": (previous.get('revision', 1) + 1) if previous else 1,
        "supersedes_receipt_id": previous['receipt_id'] if previous else '',
        "request_id": request_id or '',
        "request_hash": request_hash,
        "remaining": remaining, "risks": risks, "avoid_repeat": avoid_repeat, "verification": verification,
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
        event['receipt_id'] = f'MC-{day:%Y%m%d}-{uuid4().hex[:12]}'
        states = dict(active='进行中',completed='已完成',**{'stage-complete':'阶段完成'},waiting='等待用户',blocked='受阻',handoff='待接手',terminated='已终止')
        formal = dict(schema_version=3,receipt_id=event['receipt_id'],task_id=task_id,
            timestamp=moment,project_id=project_id,scope='project:'+project_id,project_page=str(page),
            task=task,state=states[status],completed=completed,remaining=remaining,next_action=next_action,
            files=';'.join(str((vault/Path(item)).resolve()) if not Path(item).is_absolute() else item for item in evidence),
            evidence=';'.join(evidence),risks=risks,avoid_repeat=avoid_repeat,agent=agent,verification=verification)
        formal.update(revision=event['revision'], supersedes_receipt_id=event['supersedes_receipt_id'],
            identity_state=event['identity_state'], request_id=event['request_id'])
    from memory_growth.workspace import GrowthWorkspace
    config_file = vault / '.memory-hub/workbench-config.json'
    growth_config = json.loads(config_file.read_text(encoding='utf-8')) if config_file.exists() else dict(memory_hub_root=str(vault))
    workspace = GrowthWorkspace(growth_config)
    growth = workspace.assess(formal or event, events=growth_events, impact=growth_impact,
        impact_reason=growth_impact_reason, reviewer=growth_reviewer)
    event['growth'] = growth
    if formal:
        from memory_growth.receipts import seal_formal_receipt
        formal = seal_formal_receipt({**formal, 'growth': growth})
    log = _event_log(vault)
    log.parent.mkdir(parents=True, exist_ok=True)
    from scripts.file_write_guard import safe_write_text
    backups = vault / '.memory-hub/backups/close'
    old_log = log.read_bytes() if log.exists() else None
    writes = []
    if formal:
        receipts = vault / '50-Agent-Workflows/90-Logs/memory-close-receipts.jsonl'
        old = receipts.read_bytes() if receipts.exists() else None
        writes.append((receipts, old, (old.decode('utf-8') if old is not None else '') + json.dumps(formal,ensure_ascii=False)+'\n'))
    daily = vault / "10-Daily" / f"{day.isoformat()}-worklog.md"
    daily.parent.mkdir(parents=True, exist_ok=True)
    old_daily = daily.read_bytes() if daily.exists() else None
    writes.append((daily, old_daily, (old_daily.decode('utf-8') if old_daily is not None else f"# {day.isoformat()} Worklog\n")+(
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
        )))
    writes.append((log, old_log, (old_log.decode('utf-8') if old_log is not None else '') + json.dumps(event,ensure_ascii=False)+'\n'))
    _commit_texts(writes, writer=safe_write_text, actor=agent or 'Agent', reason=event['receipt_id'], backups=backups)
    event['growth_sync'] = workspace.after_receipt(event['receipt_id'])
    try:
        write_snapshot(vault)
        event['snapshot_state'] = 'refreshed'
    except Exception as exc:
        event['snapshot_state'] = 'pending'
        event['snapshot_error'] = str(exc)
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
