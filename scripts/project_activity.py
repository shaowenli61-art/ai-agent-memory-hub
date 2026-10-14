"""Deterministic project discovery from redacted activity and formal progress.

Discovery is a read-only projection. It never registers, resumes or completes a
project, and conversation volume is deliberately not an importance signal.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import unquote


INACTIVE = ('暂停', '已终止', '历史', 'legacy', '参考')
NOISE = ('身份与配置', '身份与规则', 'Claude 长期记忆层', 'WorkBuddy 身份', '未记录')
DIAGNOSTIC = re.compile(r'排错|诊断|报错|故障|卡住|没有正常|失败|异常|高占用', re.I)


def normalize_path(value):
    value = unquote(str(value or '')).strip(' `').replace('\\', '/')
    value = re.sub(r'^file:///([a-zA-Z]:)', r'\1', value)
    value = re.split(r'[（(]', value, maxsplit=1)[0].rstrip('/')
    if not (re.match(r'^[a-zA-Z]:/', value) or value.startswith('/')):
        return ''
    return value.casefold()


def contains_path(parent, child):
    return bool(parent and child and (child == parent or child.startswith(parent + '/')))


def event_time(value, fallback, tz):
    try:
        moment = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except ValueError:
        moment = datetime.fromisoformat(fallback)
    return moment if moment.tzinfo else moment.replace(tzinfo=tz)


def public_snippets(values):
    return [str(value) for value in values if value and not str(value).startswith(
        ('# AGENTS.md', '<environment_context>', '<external_', '<in-app-browser-context>'))]


def discover_projects(config, now, projects, worklogs):
    tz = now.tzinfo or timezone(timedelta(hours=8))
    now = now.replace(tzinfo=tz) if now.tzinfo is None else now
    days = int(config.get('discovery_window_days', config['recent_work_days']))
    registry = {}
    # Prefer the current project when historical aliases share a checkout.
    for project in sorted(projects, key=lambda p: any(x in p['status'] for x in INACTIVE)):
        path = normalize_path(project['path'])
        if not path or path in registry:
            continue
        registry[path] = dict(path=path, name=project['project'], project_status=project['status'],
            aliases=[project['project'], project.get('wikilink', ''), path.rsplit('/', 1)[-1]],
            confirmed=False, focus_order=99)
    for focus in config.get('focus_projects', []):
        path = normalize_path(focus['path'])
        entry = registry.get(path, dict(path=path, project_status='未登记'))
        registry[path] = dict(entry, name=focus['name'],
            aliases=list(dict.fromkeys(entry.get('aliases', []) + focus.get('aliases', []) + [focus['name']])),
            confirmed=True, focus_order=focus.get('order', 99))
    sources = [normalize_path(p) for p in config.get('discovery_project_roots', [])]
    buckets, review, warnings = {}, [], []

    def resolve(cwd, title='', antigravity=False):
        path = normalize_path(cwd)
        by_path = sorted((entry for root, entry in registry.items() if contains_path(root, path)),
                         key=lambda entry: len(entry['path']), reverse=True)
        if antigravity and title:
            by_title = []
            for entry in registry.values():
                strength = max((len(alias) for alias in entry['aliases']
                    if len(alias) >= 4 and alias.casefold() in title.casefold()), default=0)
                if strength:
                    by_title.append((strength, entry))
            if by_title:
                by_title.sort(key=lambda row: row[0], reverse=True)
                if len(by_title) > 1 and by_title[0][0] == by_title[1][0]:
                    return None, '会话标题匹配多个项目，归属待核对'
                entry = by_title[0][1]
                reason = '会话主题匹配'
                if by_path and entry['path'] != by_path[0]['path']:
                    reason += '；主题与工作目录冲突，按明确标题归属'
                return entry, reason
        if by_path:
            return by_path[0], '工作目录匹配（已归并子目录与 worktree）'
        for parent in sources:
            if contains_path(parent, path) and path != parent:
                relative = path[len(parent) + 1:]
                first = relative.split('/')[0]
                if first.startswith('.'):
                    continue
                root = parent + '/' + first
                if not Path(root).is_dir():
                    return None, '新工作目录不存在，归属待核对'
                entry = dict(path=root, name=first, project_status='未登记', aliases=[first],
                             confirmed=False, focus_order=99)
                registry[root] = entry
                return entry, '近期对话出现新工作目录；尚未正式登记'
        return None, '缺少可确认的项目目录或主题'

    def add(entry, evidence):
        bucket = buckets.setdefault(entry['path'], dict(entry=entry, evidence=[]))
        bucket['evidence'].append(evidence)

    daily = Path(config['memory_hub_root']) / '10-Daily'
    for path in sorted(daily.glob('20??-??-??-ai-activity.json')):
        try:
            day = datetime.fromisoformat(path.name[:10]).date()
            if not 0 <= (now.date() - day).days <= days:
                continue
            packet = json.loads(path.read_text(encoding='utf-8'))
            if not isinstance(packet, dict) or not isinstance(packet.get('activities'), list):
                raise ValueError('invalid activity packet structure')
            if packet.get('date') != day.isoformat():
                raise ValueError('packet date differs from filename')
            for item in packet['activities']:
                if not isinstance(item, dict):
                    warnings.append(dict(source=str(path), reason='活动条目结构无效'))
                    continue
                title = ' '.join(item.get('titles', []))
                if any(marker in title + str(item.get('cwd', '')) for marker in NOISE[:-1]):
                    continue
                prompts = public_snippets(item.get('user_prompts', []))
                notes = public_snippets(item.get('assistant_notes', []))
                if not prompts and not notes:
                    continue
                stamp = event_time(item.get('updated_at', ''), day.isoformat(), tz)
                if stamp > now or stamp.astimezone(tz).date() != day:
                    continue
                entry, reason = resolve(item.get('cwd', ''), title, item.get('tool') == 'Gemini Antigravity')
                if not entry:
                    review.append(dict(title=title or '未明确归属的会话', reason=reason,
                        updated_at=stamp.isoformat(), source=str(path.with_suffix('.md'))))
                    continue
                # Stable session ID also merges Codex continuation/fork files.
                session = re.search(r'[0-9a-f]{8}-[0-9a-f-]{27,}', title, re.I)
                session_id = session.group(0) if session else item.get('source', title)
                add(entry, dict(kind='conversation', updated_at=stamp.isoformat(),
                    day=day.isoformat(), tool=item.get('tool', '未知工具'),
                    session_id=session_id, source=str(path.with_suffix('.md')),
                    raw_source=item.get('source', ''), progress=(notes or prompts)[-1],
                    user_request=prompts[-1] if prompts else '',
                    diagnostic=bool(prompts and DIAGNOSTIC.search(' '.join(prompts))),
                    assignment=reason))
        except (ValueError, KeyError, TypeError, OSError) as exc:
            warnings.append(dict(source=str(path), reason='活动投影无法读取：' + str(exc)))
    for log in worklogs:
        stamp = event_time(log.get('updated_at', ''), log['date'], tz)
        if stamp > now or not 0 <= (now.date() - stamp.astimezone(tz).date()).days <= days:
            continue
        paths = re.findall(r'[A-Za-z]:[\\/][^;\n|]+', log.get('key_files', '') + ';' + log.get('evidence', ''))
        entries = {}
        for path in paths:
            normalized = normalize_path(path)
            matches = sorted((e for root, e in registry.items() if contains_path(root, normalized)),
                             key=lambda e: len(e['path']), reverse=True)
            if matches:
                entries[matches[0]['path']] = matches[0]
            else:
                entry, _ = resolve(path)
                if entry:
                    entries[entry['path']] = entry
        if not entries:
            title = log['title']
            entries = {root: e for root, e in registry.items()
                if any(len(a) >= 4 and a.casefold() in title.casefold() for a in e['aliases'])}
        if len(entries) != 1:
            continue  # Multi-project receipts cannot prove a single project's progress.
        entry = next(iter(entries.values()))
        add(entry, dict(kind='formal', updated_at=stamp.isoformat(), day=log['date'],
            tool='正式工作记录', session_id=log.get('receipt_id') or log['title'],
            source=log['source'], raw_source=log.get('evidence', ''),
            progress=log.get('completed') or log['title'], user_request=log.get('next_action', ''),
            diagnostic=False, assignment='正式进展记录中的项目路径或名称',
            formal_status=log['status'], remaining=log.get('unfinished', '')))

    confirmed, discovered = [], []
    for root, entry in registry.items():
        if entry['confirmed']:
            buckets.setdefault(root, dict(entry=entry, evidence=[]))
    for bucket in buckets.values():
        entry = bucket['entry']
        unique = {}
        for evidence in bucket['evidence']:
            key = (evidence['kind'], evidence['tool'], evidence['session_id'], evidence['day'])
            if key not in unique or event_time(evidence['updated_at'], evidence['day'], tz) > event_time(
                    unique[key]['updated_at'], unique[key]['day'], tz):
                unique[key] = evidence
        evidence = sorted(unique.values(), key=lambda e: event_time(e['updated_at'], e['day'], tz), reverse=True)
        if not evidence:
            confirmed.append(dict(entry, task=entry['name'], status='已确认重点·暂无近期证据',
                updated_at='', progress='重点持续保留；未找到窗口内的活动，不推断为暂停或零进展。',
                discovery_reason='用户确认的重点，等待新的可追溯证据', evidence=[], score=0))
            continue
        if not entry['confirmed'] and any(marker in entry['project_status'] for marker in INACTIVE):
            review.append(dict(title=entry['name'], reason='项目已标记' + entry['project_status'] + '；发现新活动，生命周期待核对',
                updated_at=evidence[0]['updated_at'], source=evidence[0]['source']))
            continue
        conversations = [e for e in evidence if e['kind'] == 'conversation']
        formal = [e for e in evidence if e['kind'] == 'formal']
        active_days = len({e['day'] for e in evidence})
        tools = sorted({e['tool'] for e in conversations})
        age = (now.date() - datetime.fromisoformat(evidence[0]['updated_at']).astimezone(tz).date()).days
        diagnostic = bool(conversations and all(e['diagnostic'] for e in conversations) and not formal)
        status = '近期排错·待核实' if diagnostic else ('持续跟进·待核实' if active_days > 1 else '新近活动·待核实')
        active_candidate = True
        if formal and (not conversations or event_time(formal[0]['updated_at'], formal[0]['day'], tz)
                >= event_time(conversations[0]['updated_at'], conversations[0]['day'], tz)):
            latest_formal = formal[0]
            remaining = latest_formal.get('remaining', '').strip()
            closed = any(word in latest_formal.get('formal_status', '') for word in ('已完成', '阶段完成'))
            deferred = any(word in remaining + latest_formal['user_request'] for word in ('未来', '未启动', '暂存', '另行授权', '明确提出'))
            if closed and (not remaining or remaining == '无' or deferred):
                status = '近期交付·暂无新推进'
                active_candidate = False
        if formal and any(word in formal[0].get('formal_status', '') for word in ('等待', '待确认', '待接手')):
            status = '有正式记录·待推进/验收'
        score = (4 if age <= 1 else 3 if age <= 3 else 2) + min(active_days, 3) + min(len(tools), 2) + (2 if formal else 0)
        if diagnostic:
            score -= 2
        if not active_candidate:
            score -= 3
        reason = f'最近活动 {evidence[0]["day"]}；{active_days} 个活动日；{len(tools)} 种工具；{len(formal)} 条正式进展'
        if entry['confirmed'] and any(marker in entry['project_status'] for marker in INACTIVE):
            status = '已确认重点·生命周期待核对'
            reason += '；项目索引仍为' + entry['project_status'] + '，不自动恢复'
        if diagnostic:
            reason += '；文本包含排错信号，不以重复对话量提高排序'
        latest = evidence[0]
        row = dict(entry, task=entry['name'], status=status, updated_at=latest['updated_at'],
            progress=latest['progress'][:500], last_request=latest['user_request'][:300],
            discovery_reason=reason, activity_days=active_days, tools=tools,
            formal_count=len(formal), diagnostic_signal=diagnostic, score=score,
            active_candidate=active_candidate,
            evidence=evidence, new_project=entry['project_status'] == '未登记')
        (confirmed if entry['confirmed'] else discovered).append(row)
    confirmed.sort(key=lambda row: (row['focus_order'], row['name']))
    discovered.sort(key=lambda row: (-row['score'], -event_time(row['updated_at'], now.date().isoformat(), tz).timestamp(), row['name']))
    review = list({(item['title'], item['reason']): item for item in review}.values())
    return dict(confirmed=confirmed, discovered=discovered, review=review, warnings=warnings,
        window_days=days, ranking_note='排序依据为近期活动证据强度，不代表业务重要性；不使用原始对话条数。')
