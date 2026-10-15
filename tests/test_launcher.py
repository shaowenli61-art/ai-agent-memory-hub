"""Exercise the exported entry point, not just its internal business modules."""
import hashlib
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path
from scripts.build_local_release import build
from memory_hub.deploy import apply_install_plan

SOURCE=Path(__file__).resolve().parents[1]

def files(root):
    return {p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob('*') if p.is_file()}

class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='workbench trial ');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.package=self.root/'中文 部署包'
        build(self.package,SOURCE)
        self.env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',PYTHONUTF8='1')
        self.env.pop('PYTHONPATH',None)

    def run_cli(self,*args,input=''):
        return subprocess.run([sys.executable,'-B',*args],cwd=self.package,env=self.env,
            input=input,text=True,encoding='utf-8',capture_output=True,timeout=15)

    def test_first_run_menu_demo_from_export_starts_http_and_saves_choice(self):
        with socket.socket() as probe:
            probe.bind(('127.0.0.1',0));port=probe.getsockname()[1]
        log=self.root/'launcher.log'
        with log.open('w',encoding='utf-8') as output:
            process=subprocess.Popen([sys.executable,'-B',str(self.package/'launch.py'),'--no-browser','--port',str(port)],
                cwd=self.root,env=self.env,stdin=subprocess.PIPE,stdout=output,stderr=output,text=True,encoding='utf-8',
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            try:
                process.stdin.write('2\n');process.stdin.close()
                deadline=time.monotonic()+12;ready=False
                opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
                while time.monotonic()<deadline and process.poll() is None:
                    try:
                        with opener.open(f'http://127.0.0.1:{port}/data/operations_snapshot.json',timeout=.3) as response:
                            snapshot=json.load(response)
                        ready=any(p['project']=='团队月报' for p in snapshot['projects']);break
                    except (OSError,ValueError):time.sleep(.05)
                self.assertTrue(ready,log.read_text(encoding='utf-8'))
                saved=json.loads((self.package/'local-settings.json').read_text(encoding='utf-8'))
                self.assertEqual(saved,dict(mode='demo',port=port))
            finally:
                if process.poll() is None:process.terminate()
                process.wait(timeout=5)

    def test_check_is_read_only_and_accepts_github_source_without_manifest(self):
        (self.package/'release-files.json').unlink()
        before=files(self.package)
        result=self.run_cli('launch.py','--check')
        self.assertEqual(result.returncode,0,result.stderr+result.stdout)
        report=json.loads(result.stdout)
        self.assertTrue(report['ok']);self.assertEqual(report['package']['integrity'],'source-checkout')
        self.assertEqual(files(self.package),before)

    def test_doctor_detects_broken_demo_import_without_initializing_data(self):
        path=self.package/'scripts/demo_server.py'
        path.write_text(path.read_text(encoding='utf-8')+'\nimport missing_demo_entry_dependency\n',encoding='utf-8')
        manifest_path=self.package/'release-files.json';manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
        for row in manifest['files']:
            if row['path']=='scripts/demo_server.py':row['sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
        manifest_path.write_text(json.dumps(manifest),encoding='utf-8')
        before=files(self.package)
        result=self.run_cli('-m','memory_hub','doctor','--json')
        self.assertNotEqual(result.returncode,0)
        report=json.loads(result.stdout)
        self.assertFalse(report['ok']);self.assertIn('missing_demo_entry_dependency',str(report))
        self.assertEqual(before,files(self.package))

    def test_busy_port_does_not_save_failed_first_run_choice(self):
        with socket.socket() as busy:
            busy.bind(('127.0.0.1',0));busy.listen();port=busy.getsockname()[1]
            result=self.run_cli('launch.py','--mode','demo','--port',str(port),'--no-browser',input='2\n')
        self.assertNotEqual(result.returncode,0)
        self.assertFalse((self.package/'local-settings.json').exists())
        self.assertNotIn('Traceback',result.stderr+result.stdout)

    def test_modified_release_refused_before_rules_or_vault_written(self):
        path=self.package/'scripts/work_cycle.py';path.write_bytes(path.read_bytes()+b'\n# local edit\n')
        vault=self.root/'never-created-vault';rule=self.root/'never-created-rule.md'
        plan=dict(vault=str(vault),rule_targets={'codex':str(rule)},workbench='none',growth_mode='disabled')
        with self.assertRaisesRegex(ValueError,'hash mismatch'):
            apply_install_plan(plan,package_root=self.package,confirmed=True)
        self.assertFalse(vault.exists());self.assertFalse(rule.exists())
        before=files(self.package)
        result=self.run_cli('launch.py','--check')
        self.assertNotEqual(result.returncode,0)
        self.assertIn('hash mismatch',str(json.loads(result.stdout)))
        self.assertEqual(before,files(self.package))

    def test_real_launcher_and_saved_restart_keep_external_notes(self):
        vault=self.root/'自己的记忆库';job=self.root/'已有岗位库';job.mkdir()
        note=job/'原始资料.md';note.write_text('# 自己的资料\n原文件保持不变。',encoding='utf-8')
        original=note.read_bytes()
        with socket.socket() as probe:
            probe.bind(('127.0.0.1',0));port=probe.getsockname()[1]
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        for extra in (['--mode','real','--vault',str(vault),'--job',str(job),'--port',str(port)],[]):
            with (self.root/'real.log').open('w',encoding='utf-8') as log:
                process=subprocess.Popen([sys.executable,'-B','launch.py','--no-browser',*extra],cwd=self.package,
                    env=self.env,stdout=log,stderr=log,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                try:
                    deadline=time.monotonic()+12;ready=False
                    while time.monotonic()<deadline and process.poll() is None:
                        try:
                            with opener.open(f'http://127.0.0.1:{port}/health',timeout=.3) as response:
                                ready=json.load(response)['mode']=='real-local-workbench'
                            break
                        except OSError:time.sleep(.05)
                    self.assertTrue(ready,(self.root/'real.log').read_text(encoding='utf-8'))
                    saved=json.loads((self.package/'local-settings.json').read_text(encoding='utf-8'))
                    self.assertEqual(saved['vault'],str(vault));self.assertEqual(saved['port'],port)
                    stop=self.run_cli('-m','memory_hub','stop','--vault',str(vault))
                    self.assertEqual(stop.returncode,0,stop.stderr)
                    process.wait(timeout=5)
                finally:
                    if process.poll() is None:process.terminate();process.wait(timeout=5)
            self.assertEqual(original,note.read_bytes())
            self.assertFalse((vault/'.memory-hub/server.json').exists())
