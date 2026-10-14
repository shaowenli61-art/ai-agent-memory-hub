import hashlib
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch
from memory_hub.workbench import configure,config_path,load_config,register_project,refresh_snapshot
from memory_hub.workflow import close_task
from scripts import work_cycle,project_lifecycle,knowledge_search

class LocalWorkbenchTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='personal workbench ');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.vault=self.root/'真实模式记忆';self.job=self.root/'岗位库';self.personal=self.root/'个人库';self.project=self.root/'项目目录'
        for folder in (self.job,self.personal,self.project):folder.mkdir()
        (self.job/'计量.md').write_text('# 计量规则\n\n## 净值\n净值为实际完成量减撤销量。订单属于计划，不能直接当成实际完成。\n',encoding='utf-8')
        (self.personal/'分析.md').write_text('# 差异分析\n\n先区分新增、流失与存量变化，再查原因。\n',encoding='utf-8')
        self.config=configure(self.vault,job=self.job,personal=self.personal,owner='验收用户')
        register_project(self.vault,'经营报告',self.project,'核实差异并形成行动建议','先查计量口径。')
    def current(self):
        return next(p for p in work_cycle.all_projects(refresh_snapshot(self.vault)).values() if p['project']=='经营报告')
    def command(self,action,data):
        p=self.current()
        result=work_cycle.command(self.config,dict(action=action,project_key=p['lifecycle']['project_key'],revision=p['work_cycle']['revision'],data=data))
        self.assertTrue(result['ok']);refresh_snapshot(self.vault)
        return result
    def test_real_configuration_and_reconfigure_preserve_custom_settings_and_external_files(self):
        path=config_path(self.vault);config=json.loads(path.read_text(encoding='utf-8'))
        config.update(custom_flag='keep',project_review_days=37);path.write_text(json.dumps(config),encoding='utf-8')
        before={p:p.read_bytes() for root in (self.job,self.personal) for p in root.rglob('*') if p.is_file()}
        configure(self.vault)
        after=load_config(self.vault)
        self.assertEqual(after['job_vault_root'],str(self.job));self.assertEqual(after['personal_vault_root'],str(self.personal))
        self.assertEqual(after['custom_flag'],'keep');self.assertEqual(after['project_review_days'],37)
        self.assertEqual(before,{p:p.read_bytes() for p in before})
        self.assertFalse((self.vault/'20-Projects/团队月报.md').exists())
    def test_setup_never_overwrites_existing_vault_pages_or_rules(self):
        index=Path(self.config['project_index_file']);index.write_text(index.read_text(encoding='utf-8')+'\n本人补充内容\n',encoding='utf-8')
        page=self.vault/'20-Projects/经营报告.md';before=index.read_bytes(),page.read_bytes()
        with patch('pathlib.Path.home',return_value=self.root/'home'):
            configure(self.vault)
        self.assertEqual(before,(index.read_bytes(),page.read_bytes()));self.assertFalse((self.root/'home/.codex/AGENTS.md').exists())
    def test_project_is_idempotent_and_same_name_different_path_rejected(self):
        before=Path(self.config['project_index_file']).read_bytes()
        self.assertTrue(register_project(self.vault,'经营报告',self.project)['existing'])
        self.assertEqual(before,Path(self.config['project_index_file']).read_bytes())
        with self.assertRaises(ValueError):register_project(self.vault,'经营报告',self.job)
        self.assertIn(str(config_path(self.vault)),self.current()['work_cycle']['packet'])
    def test_unknown_project_cannot_leave_a_partial_receipt(self):
        with self.assertRaises(ValueError):
            close_task(vault=self.vault,task='新任务',status='completed',completed='完成',next_action='验收',evidence=[],project='不存在')
        self.assertFalse((self.vault/'.memory-hub/events/task-events.jsonl').exists())
    def test_close_receipt_drives_summary_and_preserves_unrelated_dashboard(self):
        dashboard=Path(self.config['current_tasks_file']);before=dashboard.read_bytes()
        file=self.project/'成果.md';file.write_text('# 成果\n已核验原始数据。',encoding='utf-8')
        event=close_task(vault=self.vault,task='差异分析',status='stage-complete',completed='计量和差异已核验',next_action='请本人确认',evidence=[str(file)],project='经营报告',remaining='等待本人采用',verification='原始数字核对通过')
        p=self.current();self.assertEqual(p['current_brief']['task'],'差异分析');self.assertIn('计量和差异',p['current_brief']['summary'])
        self.assertEqual(p['current_brief']['receipt_id'],event['receipt_id'])
        self.assertEqual(p['lifecycle']['state'],'active');self.assertTrue(p['work_cycle']['deliveries'])
        self.assertEqual(p['work_cycle']['deliveries'][0]['verification'],'原始数字核对通过')
        self.assertEqual(len(refresh_snapshot(self.vault)['task_register']),1)
        self.assertEqual(before,dashboard.read_bytes())
    def test_close_respects_existing_lock(self):
        lock=self.vault/'.memory-hub/close.lock';lock.touch()
        with self.assertRaises(FileExistsError):close_task(vault=self.vault,task='t',status='active',completed='c',next_action='n',evidence=[])
        self.assertTrue(lock.exists())
    def test_registered_project_complete_loop_and_version_protection(self):
        file=self.project/'报告.md';file.write_text('# 报告\n净值 90。',encoding='utf-8')
        self.command('delivery',dict(title='报告',purpose='决策',changes='说明净值',verification='核对',pending='待采用',paths=[str(file)]))
        delivery=self.current()['work_cycle']['deliveries'][0]
        self.command('review',dict(delivery_id=delivery['id'],status='revise',feedback='补充原因'))
        self.assertTrue(self.current()['work_cycle']['feedback'])
        self.command('review',dict(delivery_id=delivery['id'],status='accepted',purpose='决策'))
        self.assertEqual(self.current()['work_cycle']['deliveries'][0]['review_status'],'accepted')
        configure(self.vault);self.assertEqual(self.current()['work_cycle']['deliveries'][0]['review_status'],'accepted')
        file.write_text('# 报告\n变更后的净值。',encoding='utf-8')
        with self.assertRaises(ValueError):self.command('review',dict(delivery_id=delivery['id'],status='accepted',purpose='决策'))
    def test_archive_survives_setup_and_keeps_recorded_files(self):
        p=self.current();page=self.vault/'20-Projects/经营报告.md';before=page.read_bytes()
        project_lifecycle.change_state(self.config,dict(state='ended',project_key=p['lifecycle']['project_key'],revision=p['lifecycle']['revision']))
        configure(self.vault)
        snapshot=refresh_snapshot(self.vault)
        self.assertFalse(snapshot['projects']);self.assertEqual(len(snapshot['archived_projects']),1)
        self.assertEqual(before,page.read_bytes())
        with self.assertRaises(ValueError):work_cycle.command(self.config,dict(action='packet',project_key=p['lifecycle']['project_key']))
    def test_natural_language_queries_use_external_sources_and_skip_runtime(self):
        runtime=self.vault/'.memory-hub/backups/private.md';runtime.parent.mkdir(parents=True,exist_ok=True);runtime.write_text('# 净值\n内部备份不能作为知识。',encoding='utf-8')
        knowledge_search.refresh(self.config)
        found=knowledge_search.search(self.config,'订单能直接当成实际完成吗，净值该怎么算')
        self.assertTrue(found['matches']);self.assertIn('实际完成量减撤销量',found['matches'][0]['excerpt'])
        self.assertFalse(any('.memory-hub' in row['path'] for row in found['matches']))
    def test_http_operating_actions_origin_gate_and_recorded_shutdown(self):
        from memory_hub import local_server
        import socket
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        server=local_server.make_server(self.vault,port)
        from memory_hub.deploy import verify_install
        self.assertTrue(verify_install(self.vault)['ok'])
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        origin=f'http://127.0.0.1:{port}'
        with urllib.request.urlopen(origin+'/full/index.html') as response:self.assertEqual(response.status,200)
        with urllib.request.urlopen(origin+'/api/work-cycle') as response:token=json.load(response)['token']
        p=self.current();payload=json.dumps(dict(action='packet',project_key=p['lifecycle']['project_key'])).encode()
        headers={'Content-Type':'application/json','Origin':origin,'X-Workbench-Token':token}
        with urllib.request.urlopen(urllib.request.Request(origin+'/api/work-cycle',data=payload,headers=headers)) as response:
            self.assertIn('经营报告',json.load(response)['packet'])
        headers['Origin']='https://unrelated.invalid'
        with self.assertRaises(urllib.error.HTTPError) as failure:urllib.request.urlopen(urllib.request.Request(origin+'/api/work-cycle',data=payload,headers=headers))
        self.assertEqual(failure.exception.code,403)
        with self.assertRaises(urllib.error.HTTPError):urllib.request.urlopen(origin+'/../workbench-config.json')
        descriptor=self.vault/'.memory-hub/server.json';descriptor.write_text(json.dumps(server.workbench_state),encoding='utf-8')
        self.assertTrue(local_server.stop(self.vault)['ok'])
