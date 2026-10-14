"""Portable synthetic workbench, using the same product modules and UI.

Run from an exported package: python scripts/demo_server.py
All records stay under ./demo-data; no real vault is connected.
"""
import argparse
import json
import os
import secrets
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
from build_operations_dashboard import build_snapshot
from project_lifecycle import change_state
from work_cycle import command
from knowledge_search import refresh

ROOT=Path(__file__).resolve().parents[1]

def initialize():
    data=ROOT/'demo-data';formal=data/'formal';job=data/'job';personal=data/'personal'
    for p in [formal/'20-Projects',formal/'50-Agent-Workflows/90-Logs',job,personal,data/'sample-project',ROOT/'workbench/web/data',ROOT/'config']:p.mkdir(parents=True,exist_ok=True)
    config=dict(memory_hub_root=str(formal),job_vault_root=str(job),personal_vault_root=str(personal),job_knowledge_folder=str(job),
        current_tasks_file=str(formal/'当前任务.md'),project_index_file=str(formal/'20-Projects/项目索引.md'),capability_map_file=str(personal/'能力地图.md'),decision_resolution_file=str(formal/'决策闭环台账.md'),
        snapshot_output=str(ROOT/'workbench/web/data/operations_snapshot.json'),dashboard_output=str(data/'dashboard.md'),apex_dashboard_output=str(data/'home.md'),write_guard_scripts=str(ROOT/'scripts'),
        owner_aliases=['体验用户'],recent_work_days=7,project_review_days=21,stale_source_days=14,recent_job_days=45,activity_signal_days=3,max_items_per_section=8,focus_projects=[],discovery_project_roots=[],emerging_projects=[])
    seed={Path(config['current_tasks_file']):'# 当前任务\n',Path(config['decision_resolution_file']):'# 决策记录\n',Path(config['capability_map_file']):'# 能力地图\n',
        Path(config['project_index_file']):f'| 项目 | 状态 | 源码/产物路径 | 下一步 |\n| --- | --- | --- | --- |\n| [[团队月报]] | 活跃 | {data / "sample-project"} | 检查月报并决定是否采用 |\n',
        formal/'20-Projects/团队月报.md':'---\nproject_id: demo-report\n---\n# 团队月报\n\n## 项目目标\n让团队每月都能从报告找到下一步行动。\n\n## 现在怎样\n仅用于体验的虚构项目，未接入真实资料。\n',
        job/'月报口径.md':'# 月报口径（虚构示例）\n\n## 销量\n月报使用发货减退货的净销量，订单量与发货量分开。\n',personal/'分析方法.md':'# 分析方法（虚构示例）\n\n## 差异分解\n先区分新增、流失与存量变化，再查业务原因；统计相关不能直接当成因果。\n',
        data/'sample-project/月报v1.md':'# 团队月报 v1（虚构数据）\n\n本月净销量 100，上月 90。增长 10，其中新增客户贡献 6、存量客户贡献 4。\n\n待判断：是否补充退货明细。\n'}
    for path,text in seed.items():
        if not path.exists():path.write_text(text,encoding='utf-8')
    (ROOT/'config/operations_dashboard.json').write_text(json.dumps(config,ensure_ascii=False,indent=2),encoding='utf-8')
    rebuild(config);refresh(config)
    return config

def rebuild(config):
    snapshot=build_snapshot(config)
    Path(config['snapshot_output']).write_text(json.dumps(snapshot,ensure_ascii=False),encoding='utf-8')
    return snapshot

def serve(config,port):
    token=secrets.token_hex(32);gate=threading.Lock();authority=f'127.0.0.1:{port}';origin=f'http://{authority}'
    class Handler(SimpleHTTPRequestHandler):
        def log_message(self,*args):pass
        def json(self,value,status=200):
            raw=json.dumps(value,ensure_ascii=False).encode();self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(raw)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(raw)
        def allowed(self):
            return self.headers.get('Host')==authority and self.headers.get('Sec-Fetch-Site')!='cross-site' and self.headers.get('Origin',origin)==origin
        def do_GET(self):
            if not self.allowed():self.json(dict(ok=False,error='Forbidden origin'),403);return
            if self.path in ('/api/work-cycle','/api/project-lifecycle'):self.json(dict(token=token));return
            if self.path=='/':self.path='/full/index.html'
            super().do_GET()
        def do_POST(self):
            if not self.allowed() or self.headers.get('Origin')!=origin or self.headers.get('X-Workbench-Token')!=token:
                self.json(dict(ok=False,error='Forbidden request'),403);return
            try:
                size=int(self.headers.get('Content-Length','0'))
                if not 1<size<=65536 or self.headers.get('Content-Type')!='application/json' or self.headers.get('Transfer-Encoding'):raise ValueError('Invalid body')
                request=json.loads(self.rfile.read(size))
                with gate:
                    if self.path=='/api/work-cycle':result=command(config,request)
                    elif self.path=='/api/project-lifecycle':
                        event=change_state(config,request);result=dict(ok=True,event_id=event['event_id'])
                    else:raise ValueError('Unknown action')
                    if result.get('open_path'):
                        path=Path(result['open_path']).resolve()
                        if not path.is_relative_to(ROOT/'demo-data'):raise ValueError('Outside demo')
                        if not hasattr(os,'startfile'):raise ValueError('请使用成果旁的复制路径在本机打开文件。')
                        os.startfile(path);result=dict(ok=True,opened=True)
                    if result.get('event_id'):result['snapshot']=rebuild(config)
                self.json(result)
            except Exception as error:self.json(dict(ok=False,error=str(error)),400)
    server=ThreadingHTTPServer(('127.0.0.1',port),partial(Handler,directory=str(ROOT/'workbench/web')))
    print(f'独立体验工作台：{origin}/full/index.html',flush=True)
    server.serve_forever()

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8896);parser.add_argument('--initialize-only',action='store_true');args=parser.parse_args();config=initialize()
    if not args.initialize_only:serve(config,args.port)
