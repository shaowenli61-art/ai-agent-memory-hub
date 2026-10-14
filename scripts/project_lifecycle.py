"""Explicit, reversible project decisions. Activity can never undo a user decision."""
from __future__ import annotations

import argparse
import hashlib
import json
import ntpath
import os
import re
import sys
import uuid
from datetime import datetime
from pathlib import Path

LABELS = {'active': '继续跟进', 'paused': '已暂停', 'ended': '已结束'}


def project_key(row):
    path = str(row.get('path') or row.get('project_path') or '').strip(' `<>')
    return hashlib.sha256(ntpath.normpath(path).replace('\\', '/').casefold().encode()).hexdigest()[:24] if path else ''


def ledger_path(config):
    return Path(config['memory_hub_root']) / '50-Agent-Workflows/90-Logs/project-lifecycle.jsonl'


def digest(row):
    return hashlib.sha256(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def load_events(config):
    path = ledger_path(config)
    latest = {}
    if path.exists():
        for line in path.read_text(encoding='utf-8').splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            expected = row.pop('record_hash')
            if digest(row) != expected or row['state'] not in LABELS:
                raise ValueError('项目决定记录校验失败；请恢复快照后重试，不能自动恢复项目。')
            row['record_hash'] = expected
            latest[project_key(row.get('project', {})) or row['project_key']] = row
    return latest


def attach_lifecycle(row, event, config):
    row.setdefault('project', row.get('current_brief', {}).get('project') or row.get('task') or row.get('name') or '未命名项目')
    key = project_key(row)
    lifecycle = dict(project_key=key, state=event['state'] if event else 'active',
        revision=event['event_id'] if event else '', changed_at=event['timestamp'] if event else '')
    row['lifecycle'] = lifecycle
    brief = row.get('current_brief')
    if brief:
        already_attached = event and brief.get('lifecycle', {}).get('revision') == event['event_id'] and brief.get('lifecycle', {}).get('state') == event['state']
        brief['lifecycle'] = lifecycle
        if event and not already_attached:
            source = Path(config.get('project_index_file', '')) if event.get('inherited') else ledger_path(config)
            label = '项目索引状态' if event.get('inherited') else '本人项目决定'
            brief['notice'] += f" {label}：{LABELS[event['state']]}；结束不代表成果已验收。"
            if event['state'] != 'active':
                brief['project_state'] = LABELS[event['state']]
                brief['next_action'] = '项目已移出当前推进；需要继续时，请先点击恢复跟进，再准备接续包。'
            else:
                brief['project_state'] = '跟进中（本人恢复）'
                if any(word in brief.get('next_action', '') for word in ('暂停 / 结束', '恢复跟进')):
                    brief['next_action'] = '先核对项目最新变化，再确定本次继续工作的范围。'
            # Put the explicit current decision first, ahead of older receipt context.
            brief['continuation'] = (f"工作台当前项目决定：{LABELS[event['state']]}\n"
                f"决定来源：{source} · {event['event_id']}\n"
                '暂停或结束的项目须由本人明确恢复；历史任务记录不代表新的执行授权。\n以下为原记录上下文，项目管理状态以本段为准。\n\n' + brief['continuation'])
            brief['sources'].append(dict(path=str(source), label=label, sha256=event['record_hash'], uri=''))


def apply_lifecycle(snapshot, config):
    events = load_events(config)
    # Receipt ownership outranks a related output path (e.g. a photo used by a 3D project).
    owners = {}
    pages = {ntpath.normcase(p.get('project_page', '')): project_key(p) for p in snapshot.get('projects', []) if p.get('project_page')}
    receipt_file = Path(config['memory_hub_root']) / '50-Agent-Workflows/90-Logs/memory-close-receipts.jsonl'
    if receipt_file.exists():
        for line in receipt_file.read_text(encoding='utf-8-sig').splitlines():
            try:
                receipt = json.loads(line)
                if not isinstance(receipt, dict):
                    continue
                record_hash = receipt.pop('record_hash', None)
                page = ntpath.normcase(receipt.get('project_page', ''))
                if receipt.get('schema_version') == 3 and receipt.get('receipt_id') and digest(receipt) == record_hash and page in pages:
                    owners[receipt['receipt_id']] = pages[page]
            except (ValueError, TypeError):
                continue
    effective = dict(events)
    # Honor existing explicit project statuses too; never infer completion from a task.
    for row in snapshot.get('projects', []):
        key = project_key(row)
        status = row.get('status', '')
        state = 'paused' if '暂停' in status else 'ended' if status in ('已结束', '已终止', '已完成', '已归档', '已关闭') else ''
        if state and key not in effective:
            effective[key] = dict(state=state, event_id='', timestamp='', inherited=True, record_hash='', project=row)
    archived = {}
    groups = ['projects', 'recent_focus', 'discovered_projects', 'this_week_projects',
              'pending_projects', 'recently_completed_projects', 'projects_to_verify', 'emerging_projects']
    seen = set()
    for group in groups:
        kept = []
        for row in snapshot.get(group, []):
            key = project_key(row)
            event = effective.get(key)
            if id(row) not in seen:
                attach_lifecycle(row, event, config)
                seen.add(id(row))
            if event and event['state'] != 'active':
                if key not in archived or (archived[key].get('status') in ('历史', 'legacy', '参考')):
                    archived[key] = row
            else:
                kept.append(row)
        snapshot[group] = kept
    # Unindexed projects remain recoverable after the activity window expires.
    for key, event in events.items():
        if event['state'] != 'active' and key not in archived:
            row = json.loads(json.dumps(event['project']))
            attach_lifecycle(row, event, config)
            archived[key] = row
        elif event['state'] == 'active' and not any(project_key(r) == key for g in groups for r in snapshot[g]):
            row = json.loads(json.dumps(event['project']))
            attach_lifecycle(row, event, config)
            row['progress'] = row.get('current_brief', {}).get('preview', '本人恢复跟进')
            snapshot['discovered_projects'].append(row)
    snapshot['archived_projects'] = list(archived.values())
    snapshot['activity_discovery']['confirmed'] = snapshot['recent_focus']
    snapshot['activity_discovery']['discovered'] = snapshot['discovered_projects']
    snapshot['activity_discovery']['review'] = [r for r in snapshot['activity_discovery'].get('review', [])
        if project_key(r) not in archived]
    # Keep the task ledger intact, but remove archived projects' actionable reminders.
    paths = [str(p.get('path', '')).replace('\\', '/').casefold().rstrip('/') for p in archived.values() if p.get('path')]
    receipts = {t['receipt_id'] for p in archived.values()
        if not p.get('current_brief', {}).get('basis', '').startswith('关联')
        for t in p.get('current_brief', {}).get('recent_tasks', [])}
    def is_archived(row):
        ids = re.findall(r'MC-[A-Za-z0-9-]+', str(row.get('receipt_id', '')) + ' ' + str(row.get('reference_key', '')))
        known_owners = {owners[rid] for rid in ids if rid in owners}
        if known_owners:
            return known_owners.issubset(archived)
        if any(rid in receipts for rid in ids):
            return True
        text = ';'.join(str(row.get(f, '')) for f in ('evidence', 'key_files', 'source', 'path')).replace('\\', '/').casefold()
        text += ';' + ';'.join(t.get('path', '') for t in row.get('evidence_targets', [])).replace('\\', '/').casefold()
        return any(p + '/' in text or text == p for p in paths)
    for group in ('decision_entries', 'confirmation_queue', 'log_candidates', 'current_tasks', 'omission_findings'):
        snapshot[group] = [r for r in snapshot.get(group, []) if not is_archived(r)]
    metrics = snapshot['metrics']
    for key, group in {'confirmed_focus': 'recent_focus', 'discovered_projects': 'discovered_projects',
                      'this_week_projects': 'this_week_projects', 'pending_projects': 'pending_projects',
                      'recently_completed_projects': 'recently_completed_projects', 'projects_to_verify': 'projects_to_verify',
                      'decision_queue': 'decision_entries', 'confirmation_queue': 'confirmation_queue',
                      'log_candidates': 'log_candidates', 'open_tasks': 'current_tasks'}.items():
        metrics[key] = len(snapshot.get(group, []))
    metrics['archived_projects'] = len(archived)
    metrics['blocked_tasks'] = sum(r.get('blocked', False) for r in snapshot['current_tasks'])
    metrics['overdue_tasks'] = sum(r.get('overdue', False) for r in snapshot['current_tasks'])
    metrics['emerging_projects'] = len(snapshot['emerging_projects'])
    metrics['discovery_review'] = len(snapshot['activity_discovery']['review'])
    metrics['omission_findings'] = len(snapshot['omission_findings'])
    metrics['indexed_active_projects'] = sum(p.get('status') == '活跃' for p in snapshot['projects'])
    snapshot['project_lifecycle'] = dict(source=str(ledger_path(config)), mode='explicit_user_decision')


def change_state(config, request):
    if request.get('state') not in LABELS or not isinstance(request.get('revision'), str):
        raise ValueError('项目操作参数无效。')
    path = ledger_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.with_suffix('.lock')
    # Fail closed on concurrent writes/crash locks; never silently steal a lock.
    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    try:
        os.close(fd)
        events = load_events(config)
        key = request.get('project_key')
        previous = events.get(key)
        if request['revision'] != (previous['event_id'] if previous else ''):
            raise ValueError('项目状态已变化，请关闭详情并刷新后再操作。')
        snapshot = json.loads(Path(config['snapshot_output']).read_text(encoding='utf-8'))
        candidates = snapshot.get('projects', []) + snapshot.get('recent_focus', []) + snapshot.get('discovered_projects', []) + snapshot.get('archived_projects', [])
        project = next((r for r in candidates if project_key(r) == key and r.get('status') not in ('历史', 'legacy', '参考')), None)
        project = project or next((r for r in candidates if project_key(r) == key), None)
        if not project or not key:
            raise ValueError('未找到当前快照中的项目，请刷新后重试。')
        if previous and previous['state'] == request['state']:
            return previous
        # Use the existing protected writer and coordination registry of the memory hub.
        guard_root = Path(config.get('write_guard_scripts') or Path(__file__).resolve().parent)
        sys.path.insert(0, str(guard_root))
        from file_write_guard import safe_write_text, snapshot_file
        board = Path(config['memory_hub_root']) / '50-Agent-Workflows/00-Dashboard/多Agent协同看板.md'
        if board.exists():
            from agent_handoff import active_claims
            for claim in active_claims(board.read_text(encoding='utf-8')):
                if str(path).replace('\\', '/').casefold() in claim['lock'].replace('\\', '/').casefold():
                    raise ValueError('项目决定记录正在被其他任务占用，请稍后重试。')
        event_id = 'PL-' + uuid.uuid4().hex
        clean_project = json.loads(json.dumps(project))
        clean_project.setdefault('project', clean_project.get('current_brief', {}).get('project') or clean_project.get('task') or '未命名项目')
        clean_project.pop('lifecycle', None)
        # Preserve original context only once, avoiding repeated continuation prefixes.
        if previous:
            clean_project = previous['project']
        event = dict(schema_version=1, event_id=event_id, task_id=event_id, project_key=key,
            state=request['state'], previous_event=previous['event_id'] if previous else '',
            timestamp=datetime.now().astimezone().isoformat(timespec='seconds'), actor='本人（工作台按钮）',
            project=clean_project, evidence='本地工作台显式项目操作',
            scope='project_lifecycle_only', note='不修改任务验收、项目文件或运行中的 Agent。')
        event['record_hash'] = digest(event)
        content = path.read_text(encoding='utf-8') if path.exists() else ''
        snapshot_file(path, 'Workbench', event_id, path.parent / 'write-snapshots')
        staged = path.with_suffix('.pending')
        try:
            safe_write_text(staged, content + json.dumps(event, ensure_ascii=False) + '\n',
                'Workbench', event_id, path.parent / 'write-snapshots')
            os.replace(staged, path)
        finally:
            staged.unlink(missing_ok=True)
        return event
    finally:
        lock.unlink()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True)
    args = parser.parse_args()
    try:
        config = json.loads(Path(args.config).read_text(encoding='utf-8-sig'))
        event = change_state(config, json.loads(sys.stdin.read()))
        print(json.dumps(dict(ok=True, event_id=event['event_id']), ensure_ascii=False))
        return 0
    except Exception as error:
        print(json.dumps(dict(ok=False, error=str(error)), ensure_ascii=False))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
