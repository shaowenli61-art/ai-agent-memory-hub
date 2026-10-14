"""Local workbench configuration, registration and read-only projection."""
from __future__ import annotations
import hashlib
import json
import re
import sqlite3
import os
from pathlib import Path
from memory_hub.deploy import _initialize_vault

PACKAGE_ROOT=Path(__file__).resolve().parents[1]

def config_path(vault):
    return Path(vault)/'.memory-hub/workbench-config.json'

def configure(vault, *, job=None, personal=None, owner=None, semantic_model=None, semantic_onnx=None, reranker=None, package_root=None):
    vault=Path(vault).expanduser().resolve()
    target=config_path(vault)
    prior=json.loads(target.read_text(encoding='utf-8')) if target.exists() else {}
    for path in (job,personal,semantic_model,semantic_onnx,reranker):
        if path is not None and not Path(path).expanduser().exists():
            raise FileNotFoundError('Configured source or model does not exist: '+str(path))
    for path in (job,personal):
        if path is not None and not Path(path).expanduser().is_dir():
            raise ValueError('Knowledge source must be a directory')
    # External knowledge libraries are read only; initialize only missing Hub files.
    _initialize_vault(vault)
    state=vault/'.memory-hub'
    default_job=state/'knowledge/job'; default_personal=state/'knowledge/personal'
    for folder in (default_job,default_personal):
        folder.mkdir(parents=True,exist_ok=True)
    config=dict(prior)
    config.setdefault('job_vault_root',str(default_job))
    config.setdefault('personal_vault_root',str(default_personal))
    for key,value in [('job_vault_root',job),('personal_vault_root',personal),('semantic_model_path',semantic_model),('semantic_onnx_path',semantic_onnx),('reranker_model_path',reranker)]:
        if value is not None:
            config[key]=str(Path(value).expanduser().resolve())
    if owner is not None:
        config['owner_aliases']=[owner]
    config.setdefault('owner_aliases',[])
    config.setdefault('recent_work_days',7)
    config.setdefault('project_review_days',21)
    config.setdefault('stale_source_days',14)
    config.setdefault('recent_job_days',45)
    config.setdefault('activity_signal_days',3)
    config.setdefault('max_items_per_section',8)
    for key in ('focus_projects','discovery_project_roots','emerging_projects'):
        config.setdefault(key,[])
    config.update(schema_version=1,memory_hub_root=str(vault))
    config.setdefault('current_tasks_file',str(vault/'50-Agent-Workflows/00-Dashboard/当前任务.md'))
    config.setdefault('project_index_file',str(vault/'20-Projects/项目索引.md'))
    config.setdefault('capability_map_file',str(Path(config['personal_vault_root'])/'能力地图.md'))
    config.setdefault('decision_resolution_file',str(vault/'50-Agent-Workflows/00-Dashboard/决策闭环台账.md'))
    config.setdefault('job_knowledge_folder',config['job_vault_root'])
    config.setdefault('dashboard_output',str(state/'runtime/dashboard.md'))
    config.setdefault('apex_dashboard_output',str(state/'runtime/home.md'))
    config['snapshot_output']=str(state/'runtime/operations_snapshot.json')
    config['knowledge_index']=str(state/'runtime/knowledge-index.sqlite3')
    config['write_guard_scripts']=str((package_root or PACKAGE_ROOT)/'scripts')
    rendered=json.dumps(config,ensure_ascii=False,indent=2)+'\n'
    if not target.exists() or target.read_text(encoding='utf-8')!=rendered:
        from scripts.file_write_guard import safe_write_text
        safe_write_text(target,rendered,'Installer','configure-local-workbench',state/'backups/config')
    config['_config_path']=str(target)
    return config

def load_config(vault):
    path=config_path(vault)
    if not path.is_file():
        raise ValueError('先运行 python -m memory_hub setup --vault "你的记忆库目录"')
    config=json.loads(path.read_text(encoding='utf-8'))
    if config.get('schema_version')!=1:
        raise ValueError('Unsupported workbench configuration version')
    config['write_guard_scripts']=str(PACKAGE_ROOT/'scripts')
    config['_config_path']=str(path.resolve())
    return config

def doctor(vault=None):
    problems=[]
    try:
        with sqlite3.connect(':memory:') as db:
            db.execute('CREATE VIRTUAL TABLE smoke USING fts5(body)')
    except sqlite3.Error:
        problems.append('Python SQLite 缺少 FTS5 支持')
    report=dict(ok=not problems,problems=problems,model_downloads=False,global_rule_changes=False)
    if vault is not None:
        config=load_config(vault)
        for key in ('memory_hub_root','job_vault_root','personal_vault_root'):
            if not Path(config[key]).is_dir():
                problems.append('Missing source directory: '+key)
        report.update(ok=not problems,config=str(config_path(vault)),retrieval='offline semantic configured' if config.get('semantic_model_path') else 'lexical',sources={key:config[key] for key in ('memory_hub_root','job_vault_root','personal_vault_root')})
    return report

def register_project(vault, name, path, goal='', next_action='先核对项目当前成果、阻塞与证据。'):
    from scripts.file_write_guard import safe_write_text
    from scripts.build_operations_dashboard import load_projects
    vault=Path(vault).resolve(); path=Path(path).expanduser().resolve()
    if not path.is_dir():
        raise ValueError('项目目录必须已经存在；登记不会创建或移动项目文件。')
    if not name.strip() or re.search(r'[\\/:*?"<>|\[\]\r\n]',name):
        raise ValueError('项目名包含不支持的文件名或表格字符。')
    config=load_config(vault)
    index=Path(config['project_index_file'])
    existing=load_projects(index)
    row=next((p for p in existing if p['project']==name),None)
    if row:
        if Path(row['path']).resolve()!=path:
            raise ValueError('同名项目已指向其他目录；请使用不同名称。')
        return dict(project=name,path=str(path),project_page=str(vault/'20-Projects'/f'{name}.md'),existing=True)
    page=vault/'20-Projects'/f'{name}.md'
    if page.exists():
        raise ValueError('同名项目页已存在但未登记；先核对内容再接入，不能覆盖。')
    identity='project-'+hashlib.sha256(str(path).casefold().encode()).hexdigest()[:16]
    text=f'---\nproject_id: {identity}\n---\n# {name}\n\n## 项目目标\n{goal or "目标以本人本次请求为准。"}\n\n## 现在怎样\n已接入真实项目目录；尚无正式完成回执。\n'
    backups=vault/'.memory-hub/backups/projects'
    lock=backups/'register.lock'; lock.parent.mkdir(parents=True,exist_ok=True)
    fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY);os.close(fd)
    try:
            current=index.read_text(encoding='utf-8')
            if '源码/产物路径' not in current:
                current+='\n| 项目 | 状态 | 源码/产物路径 | 下一步 |\n| --- | --- | --- | --- |\n'
            safe_write_text(page,text,'Agent','register-project',backups)
            safe_write_text(index,current.rstrip()+f'\n| [[{name}]] | 活跃 | `{path}` | {next_action.replace(chr(10)," ").replace("|","／")} |\n','Agent','register-project',backups)
    finally:
        lock.unlink()
    refresh_snapshot(vault)
    return dict(project=name,path=str(path),project_page=str(page),existing=False)

def refresh_snapshot(vault):
    from scripts.build_operations_dashboard import build_snapshot
    from memory_hub.workflow import build_snapshot as legacy_snapshot
    config=load_config(vault)
    snapshot=build_snapshot(config)
    legacy=legacy_snapshot(Path(vault))
    archived={p['project'] for p in snapshot.get('archived_projects',[])}
    known={t['task'] for t in snapshot['current_tasks']}
    events={row['task']:row for row in __import__('memory_hub.workflow',fromlist=['_read_events'])._read_events(Path(vault))}
    registered={row['task'] for row in snapshot.get('task_register',[])}
    for event in events.values():
        if event['task'] not in registered:
            snapshot['task_register'].append(dict(task=event['task'],status=event['status'],agent=event.get('agent',''),
                collaborator=event.get('collaborator',''),next_action=event['next_action'],evidence=';'.join(event['evidence']),
                open=event['status'] not in ('completed','stage-complete','terminated'),blocked=event['status']=='blocked',
                overdue=False,evidence_targets=[],source_target=dict(path=str(Path(vault)/'.memory-hub/events/task-events.jsonl'),exists=True,uri='')))
    snapshot['current_tasks'] += [row for row in legacy['current_tasks'] if row['task'] not in known and events.get(row['task'],{}).get('project','') not in archived]
    snapshot['metrics']['open_tasks']=len(snapshot['current_tasks'])
    snapshot['metrics']['blocked_tasks']=sum(t.get('blocked',False) for t in snapshot['current_tasks'])
    if not snapshot['recently_completed_projects']:
        snapshot['recently_completed_projects']=legacy['recently_completed_projects']
    snapshot['metrics']['recently_completed_projects']=len(snapshot['recently_completed_projects'])
    target=Path(config['snapshot_output']);target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(snapshot,ensure_ascii=False,indent=2),encoding='utf-8')
    installed=Path(vault)/'.memory-hub/workbench/web/data'
    if installed.exists():
        (installed/'operations_snapshot.json').write_bytes(target.read_bytes())
    return snapshot
