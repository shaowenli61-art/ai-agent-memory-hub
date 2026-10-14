"""Loopback-only operating server for the real local workbench."""
from __future__ import annotations
import json
import os
import secrets
import shutil
import threading
import time
import urllib.request
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from functools import partial
from urllib.parse import urlparse
from memory_hub.workbench import PACKAGE_ROOT, load_config, refresh_snapshot

def make_server(vault, port=8896):
    from scripts.work_cycle import command
    from scripts.project_lifecycle import change_state
    from scripts.knowledge_search import refresh
    vault=Path(vault).resolve(); config=load_config(vault)
    web=vault/'.memory-hub/workbench/web'
    shutil.copytree(PACKAGE_ROOT/'workbench/web',web,dirs_exist_ok=True,ignore=shutil.ignore_patterns('data'))
    (web/'data').mkdir(exist_ok=True)
    refresh_snapshot(vault); refresh(config)
    authority=f'127.0.0.1:{port}';origin='http://'+authority
    token=secrets.token_hex(32); instance=secrets.token_hex(16)
    gate=threading.Lock(); latest=[time.monotonic()]
    class Handler(SimpleHTTPRequestHandler):
        def log_message(self,*args):
            pass
        def send_json(self,value,status=200):
            raw=json.dumps(value,ensure_ascii=False).encode()
            self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8')
            self.send_header('Content-Length',str(len(raw)));self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff');self.end_headers();self.wfile.write(raw)
        def allowed(self):
            return self.headers.get('Host')==authority and self.headers.get('Origin',origin)==origin and self.headers.get('Sec-Fetch-Site')!='cross-site'
        def do_GET(self):
            if not self.allowed():
                self.send_json(dict(ok=False,error='Forbidden origin'),403);return
            route=urlparse(self.path).path
            if route=='/health':
                self.send_json(dict(ok=True,instance=instance,mode='real-local-workbench'));return
            if route in ('/api/work-cycle','/api/project-lifecycle'):
                self.send_json(dict(token=token));return
            if route=='/data/operations_snapshot.json' and time.monotonic()-latest[0]>2:
                try:
                    with gate:
                        refresh_snapshot(vault); latest[0]=time.monotonic()
                except Exception as error:
                    self.send_json(dict(ok=False,error=str(error)),500);return
            if route=='/':
                self.path='/full/index.html'
            path=Path(self.translate_path(self.path)).resolve()
            if not path.is_relative_to(web.resolve()) or path.suffix not in ('.html','.js','.css','.json') or path.is_dir():
                self.send_json(dict(ok=False,error='Not found'),404);return
            super().do_GET()
        def do_POST(self):
            if not self.allowed() or self.headers.get('Origin')!=origin or self.headers.get('X-Workbench-Token')!=token:
                self.send_json(dict(ok=False,error='Forbidden request'),403);return
            try:
                size=int(self.headers.get('Content-Length','0'))
                if not 1<size<=65536 or self.headers.get('Content-Type')!='application/json' or self.headers.get('Transfer-Encoding'):
                    raise ValueError('Invalid request body')
                request=json.loads(self.rfile.read(size))
                if self.path=='/api/shutdown':
                    if request.get('instance')!=instance:
                        raise ValueError('Service instance has changed')
                    self.send_json(dict(ok=True));threading.Thread(target=self.server.shutdown,daemon=True).start();return
                with gate:
                    if self.path=='/api/work-cycle':
                        result=command(config,request)
                    elif self.path=='/api/project-lifecycle':
                        event=change_state(config,request); result=dict(ok=True,event_id=event['event_id'])
                    else:
                        raise ValueError('Unknown action')
                    if result.get('open_path'):
                        path=Path(result['open_path']).resolve()
                        if not path.is_file():
                            raise ValueError('File does not exist')
                        if not hasattr(os,'startfile'):
                            raise ValueError('请使用成果旁的复制路径，在本机打开原文。')
                        # The command already validates current source/file versions and ownership.
                        os.startfile(path);result=dict(ok=True,opened=True)
                    if result.get('event_id'):
                        result['snapshot']=refresh_snapshot(vault)
                self.send_json(result)
            except Exception as error:
                self.send_json(dict(ok=False,error=str(error)),400)
    server=ThreadingHTTPServer(('127.0.0.1',port),partial(Handler,directory=str(web)))
    server.workbench_state=dict(port=port,instance=instance,pid=os.getpid())
    (vault/'.memory-hub/workbench-install.json').write_text(json.dumps(dict(status='installed',vault=str(vault),
        workbench='web',web_workbench=str(web),managed_rule_files=[],global_rules_changed=False,
        source=str(PACKAGE_ROOT),configuration=str(vault/'.memory-hub/workbench-config.json')),ensure_ascii=False,indent=2),encoding='utf-8')
    return server

def serve(vault,port=8896,open_browser=True):
    server=make_server(vault,port)
    descriptor=Path(vault)/'.memory-hub/server.json'
    descriptor.write_text(json.dumps(server.workbench_state),encoding='utf-8')
    url=f'http://127.0.0.1:{port}/full/index.html'
    print('个人工作台：'+url,flush=True)
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    finally:
        server.server_close()
        if descriptor.exists() and json.loads(descriptor.read_text(encoding='utf-8')).get('instance')==server.workbench_state['instance']:
            descriptor.unlink()

def stop(vault):
    descriptor=Path(vault)/'.memory-hub/server.json'
    if not descriptor.exists():
        return dict(ok=True,stopped=False,note='No recorded workbench service')
    state=json.loads(descriptor.read_text(encoding='utf-8')); origin=f"http://127.0.0.1:{state['port']}"
    with urllib.request.urlopen(origin+'/health',timeout=3) as response:
        health=json.load(response)
    if health.get('instance')!=state['instance']:
        raise ValueError('该端口现在运行的是其他服务，不停止。')
    with urllib.request.urlopen(origin+'/api/work-cycle',timeout=3) as response:
        token=json.load(response)['token']
    request=urllib.request.Request(origin+'/api/shutdown',data=json.dumps(dict(instance=state['instance'])).encode(),headers={'Origin':origin,'Content-Type':'application/json','X-Workbench-Token':token})
    with urllib.request.urlopen(request,timeout=3) as response:
        return json.load(response)
