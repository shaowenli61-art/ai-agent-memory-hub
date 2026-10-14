import copy
import json
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from scripts import work_cycle as w
from scripts import project_lifecycle as life
from scripts import knowledge_search as k


class WorkCycleTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.now=datetime(2026,10,11,10,tzinfo=w.ZONE)
        self.config=dict(memory_hub_root=str(self.root/'vault'),snapshot_output=str(self.root/'snapshot.json'))
        self.project=dict(project='真实流程测试副本',path=str(self.root/'project'),status='活跃',current_brief=dict(project='测试项目',project_state='活跃',task_state='待验收',notice='',continuation='历史边界',sources=[],receipt_id='R1'))
        Path(self.project['path']).mkdir();self.file=Path(self.project['path'])/'成果.md';self.file.write_text('第一版',encoding='utf-8')
        self.key=life.project_key(self.project)
        self.base=dict(projects=[self.project],recent_focus=[],discovered_projects=[],archived_projects=[],metrics={},activity_discovery={},decision_entries=[],confirmation_queue=[])
        self.project['lifecycle']=dict(state='active',project_key=self.key,revision='')
        Path(self.config['snapshot_output']).write_text(json.dumps(self.base),encoding='utf-8')
        self.revision=''

    def act(self,action,data=None,**extra):
        result=w.command(self.config,dict(project_key=self.key,revision=self.revision,action=action,data=data or {},**extra),self.now)
        self.revision=result.get('event_id',self.revision);return result

    def view(self):
        result=copy.deepcopy(self.base);life.apply_lifecycle(result,self.config);w.enrich_work_cycle(result,self.config,self.now)
        return result,w.all_projects(result)[self.key]['work_cycle']

    def plan(self):
        return self.act('plan',dict(goal='验证一个目标',next_step='检查成果',criteria='数据一致且文件能打开',boundary='不部署',due='2026-10-12'))

    def delivery(self,plan_id=''):
        return self.act('delivery',dict(title='分析报告第一版',purpose='正式报告',paths=[str(self.file)],changes='完成分析',verification='用样例对账通过',pending='业务判断',plan_id=plan_id))

    def test_complete_loop_adoption_feedback_packet_and_no_project_close(self):
        plan=self.plan()['event_id'];delivery=self.delivery(plan)['event_id']
        self.act('review',dict(delivery_id=delivery,status='revise',feedback='补充同比口径'))
        self.assertIn('补充同比口径',self.act('packet')['packet'])
        self.act('review',dict(delivery_id=delivery,status='accepted',purpose='正式报告',complete_plan=True))
        snapshot,cycle=self.view()
        self.assertEqual(cycle['plan']['status'],'accepted');self.assertEqual(len(cycle['adopted']),1)
        self.assertFalse(snapshot['daily_work']['today']);self.assertEqual(snapshot['projects'][0]['lifecycle']['state'],'active')

    def test_adopting_version_does_not_finish_goal_without_explicit_choice(self):
        plan=self.plan()['event_id'];delivery=self.delivery(plan)['event_id']
        self.act('review',dict(delivery_id=delivery,status='accepted',purpose='正式报告'))
        self.assertEqual(self.view()[1]['plan']['status'],'working')

    def test_file_change_invalidates_adoption_and_open(self):
        delivery=self.delivery()['event_id'];self.act('review',dict(delivery_id=delivery,status='accepted',purpose='报告'))
        f=self.view()[1]['adopted'][0]['files'][0];self.file.write_text('第二版不同内容',encoding='utf-8')
        snapshot,cycle=self.view();self.assertFalse(cycle['adopted'][0]['valid']);self.assertTrue(snapshot['daily_work']['attention'])
        with self.assertRaises(ValueError):self.act('open_artifact',delivery_id=delivery,file_id=f['id'])
        with self.assertRaises(ValueError):self.act('review',dict(delivery_id=delivery,status='accepted',purpose='报告'))

    def test_revision_lock_and_corruption_protect_decisions(self):
        self.plan();before=w.log_path(self.config).read_bytes()
        with self.assertRaises(ValueError):w.command(self.config,dict(project_key=self.key,action='seen',revision=''),self.now)
        self.assertEqual(before,w.log_path(self.config).read_bytes())
        lock=w.log_path(self.config).with_suffix('.lock');lock.touch()
        with self.assertRaises(FileExistsError):self.act('seen')
        lock.unlink();w.log_path(self.config).write_bytes(before.replace(b'"action": "plan"',b'"action": "seen"'))
        with self.assertRaises(ValueError):self.view()

    def test_dates_and_new_version_reminders(self):
        self.plan();self.act('reminder',dict(item_id='plan',mode='date',until='2026-10-13'))
        self.assertFalse(self.view()[0]['daily_work']['today']);self.now+=timedelta(days=2)
        self.assertEqual(len(self.view()[0]['daily_work']['today']),1)
        self.act('reminder',dict(item_id='plan',mode='change'));self.assertFalse(self.view()[0]['daily_work']['today'])
        self.delivery();self.assertEqual(len(self.view()[0]['daily_work']['today']),1)

    def test_deferred_review_is_quiet_until_date(self):
        d=self.delivery()['event_id'];self.act('review',dict(delivery_id=d,status='deferred',until='2026-10-13'))
        self.assertFalse(self.view()[0]['daily_work']['decisions']);self.now+=timedelta(days=2)
        self.assertTrue(self.view()[0]['daily_work']['decisions'])

    def test_pause_excludes_actions_and_refuses_continuation(self):
        self.plan();self.delivery();life.change_state(self.config,dict(project_key=self.key,state='paused',revision=''))
        view,_=self.view();self.assertFalse(view['daily_work']['today']);self.assertFalse(view['daily_work']['decisions'])
        with self.assertRaises(ValueError):self.act('packet')
        with self.assertRaises(ValueError):self.act('delivery')

    def test_seen_and_sample_are_explicit(self):
        self.assertFalse(w.log_path(self.config).exists());self.view();self.assertFalse(w.log_path(self.config).exists())
        self.act('seen');self.base['projects'][0]['current_brief']['receipt_id']='R2';self.assertTrue(self.view()[1]['changes'])
        self.act('sample',dict(phase='after',minutes=2.5,reexplains=0,wrong_version=False))
        stats=self.view()[0]['daily_work']['measurements'];self.assertEqual(stats['before']['count'],0);self.assertEqual(stats['after']['average_minutes'],2.5)

    def test_outside_arbitrary_file_cannot_be_registered(self):
        outside=self.root/'outside.md';outside.write_text('test')
        with self.assertRaises(ValueError):self.act('delivery',dict(title='x',purpose='x',changes='x',verification='x',pending='x',paths=[str(outside)]))

    def test_explicit_work_outlives_activity_discovery_window(self):
        self.plan();self.base['projects']=[]
        view,cycle=self.view();self.assertEqual(len(view['daily_work']['today']),1)
        self.assertEqual(view['discovered_projects'][0]['project'],'真实流程测试副本')

    def test_markdown_and_activity_paths_share_work_and_legacy_decisions(self):
        self.plan();alias=copy.deepcopy(self.project);alias['path']='`'+alias['path']+'`'
        self.base['recent_focus']=[alias]
        snapshot,_=self.view()
        self.assertEqual(snapshot['projects'][0]['work_cycle']['revision'],snapshot['recent_focus'][0]['work_cycle']['revision'])
        # Old hashed identities remain readable without rewriting their records.
        path=w.log_path(self.config);row=json.loads(path.read_text(encoding='utf-8'))
        row['project_key']='legacy-markdown-key';row['project']['path']=alias['path'];row['record_hash']=w.digest({k:v for k,v in row.items() if k!='record_hash'})
        path.write_text(json.dumps(row)+'\n',encoding='utf-8')
        self.assertEqual(self.view()[1]['plan']['goal'],'验证一个目标')
        self.act('seen');self.assertEqual(len(w.events(self.config)),2)

    def test_knowledge_selection_checked_and_enters_packet(self):
        root=self.root/'knowledge';root.mkdir();source=root/'方法.md';source.write_text('# 方法\n客户下降需要分解新增流失存量。',encoding='utf-8');self.config['personal_vault_root']=str(root)
        k.refresh(self.config);hit=k.search(self.config,'客户下降')['matches'][0]
        self.act('knowledge',dict(source_ids=[hit['id']]));self.assertIn('方法.md',self.act('packet')['packet'])
        source.write_text('修改后的方法',encoding='utf-8');self.assertFalse(self.view()[1]['knowledge'][0]['valid'])
        with self.assertRaises(ValueError):self.act('knowledge',dict(source_ids=[hit['id']]))

    def test_advice_without_manual_plan_does_not_write_and_enters_packet(self):
        self.base['projects'][0]['current_brief'].update(next_action='独立核对客户映射',next_basis='最新回执',goal='数据一致')
        _,cycle=self.view()
        self.assertEqual(cycle['suggestion']['next_step'],'独立核对客户映射')
        self.assertIn('独立核对客户映射',cycle['packet'])
        self.assertFalse(w.log_path(self.config).exists())

    def test_one_sentence_adjustment_preserves_context_and_stale_advice_rejected(self):
        self.base['projects'][0]['current_brief'].update(goal='目标',next_action='核对口径',boundaries=['不能部署'])
        Path(self.config['snapshot_output']).write_text(json.dumps(self.base),encoding='utf-8')
        advice=self.view()[1]['suggestion']
        self.act('adjust',dict(next_step='先查数据来源',advice_revision=advice['revision']))
        cycle=self.view()[1]
        self.assertEqual(cycle['plan']['next_step'],'先查数据来源')
        self.assertIn('不能部署',cycle['plan']['boundary'])
        with self.assertRaises(ValueError):self.act('adjust',dict(next_step='改掉',advice_revision=advice['revision']))

    def test_advice_prioritizes_feedback_and_changed_adopted_file(self):
        d=self.delivery()['event_id'];self.act('review',dict(delivery_id=d,status='revise',feedback='补上对照组'))
        self.assertEqual(self.view()[1]['suggestion']['kind'],'revise')
        self.act('review',dict(delivery_id=d,status='accepted',purpose='正式报告'))
        self.file.write_text('无提示地改变了文件',encoding='utf-8')
        self.assertEqual(self.view()[1]['suggestion']['kind'],'version')

    def test_pause_advice_never_invites_execution_and_keeps_adjustment(self):
        self.plan();life.change_state(self.config,dict(project_key=self.key,state='paused',revision=''))
        cycle=self.view()[1]
        self.assertEqual(cycle['suggestion']['kind'],'inactive')
        self.assertIn('恢复',cycle['suggestion']['next_step'])
        self.assertEqual(cycle['plan']['goal'],'验证一个目标')

    def test_new_delivery_prompts_judgment_and_later_adjustment_is_respected(self):
        self.plan();self.now+=timedelta(seconds=1);self.delivery()
        self.assertEqual(self.view()[1]['suggestion']['kind'],'decision')
        advice=self.view()[1]['suggestion'];self.now+=timedelta(seconds=1)
        self.act('adjust',dict(next_step='先处理另一项依赖',advice_revision=advice['revision']))
        self.assertEqual(self.view()[1]['suggestion']['next_step'],'先处理另一项依赖')


class KnowledgeSearchTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.config=dict(snapshot_output=str(self.root/'output/snapshot.json'))
        for source,(_,key) in k.SOURCES.items():
            path=self.root/source;path.mkdir();self.config[key]=str(path)
        self.job=Path(self.config['job_vault_root'])/'销售指标.md';self.job.write_text('# 客户销量\n必须使用发货净销量，订单不是发货。',encoding='utf-8')
        self.personal=Path(self.config['personal_vault_root'])/'分析方法.md';self.personal.write_text('# 因果推断\nPSM 和 DID 用于因果分析。',encoding='utf-8')

    def test_natural_query_cross_vault_sources_lines_and_strict_control(self):
        report=k.refresh(self.config);self.assertEqual(report['sources']['job']['indexed'],1)
        self.assertFalse(k.search(self.config,'客户销量要用什么口径',mode='strict')['matches'])
        hit=k.search(self.config,'客户销量要用什么口径')['matches'][0];self.assertEqual(hit['source'],'job')
        source_line=self.job.read_text(encoding='utf-8').splitlines()[hit['line']-1]
        self.assertTrue(hit['excerpt'].startswith(source_line))
        self.assertEqual(k.search(self.config,'PSM DID','personal')['matches'][0]['source'],'personal')
        self.assertFalse(k.search(self.config,'PSM DID','formal')['matches'])

    def test_incremental_update_delete_and_stale_pin_rejected(self):
        k.refresh(self.config);hit=k.search(self.config,'PSM')['matches'][0];self.assertEqual(k.refresh(self.config)['updated'],0)
        self.personal.write_text('新内容',encoding='utf-8')
        with self.assertRaises(ValueError):k.resolve(self.config,hit['id'])
        k.refresh(self.config);self.assertFalse(k.search(self.config,'PSM')['matches'])
        self.job.unlink();self.assertEqual(k.refresh(self.config)['removed'],1)

    def test_unreadable_and_backup_are_not_silently_returned(self):
        k.refresh(self.config);self.job.write_bytes(b'\xffinvalid')
        backup=self.root/'formal'/'old.backup-20260101.md';backup.write_text('old')
        report=k.refresh(self.config);self.assertEqual(report['sources']['job']['errors'],1);self.assertEqual(report['sources']['formal']['excluded'],1)
        self.assertFalse(k.search(self.config,'客户销量')['matches'])

    def test_semantic_recall_without_word_overlap_and_stale_ids_excluded(self):
        from scripts import semantic_search
        self.personal.write_text('# 对照试验\n比较处理组与参照组，不能直接从增长断言因果。',encoding='utf-8')
        k.refresh(self.config)
        hit=k.search(self.config,'对照试验','personal')['matches'][0]
        self.config['semantic_model_path']='test-local-model'
        recalled=dict(ok=True,matches=[dict(id='removed-id',offset=0,end=100,similarity=.9),dict(id=hit['id'],offset=0,end=100,similarity=.8)])
        with patch.object(semantic_search,'search',return_value=recalled):
            result=k.search(self.config,'办会后卖得好了，是它的功劳吗')
            scoped=k.search(self.config,'办会后卖得好了，是它的功劳吗',source='job')
        self.assertEqual(result['matches'][0]['id'],hit['id'])
        self.assertTrue(result['retrieval']['semantic_ready'])
        self.assertNotIn('removed-id',[r['id'] for r in result['matches']])
        self.assertTrue(all(r['source']=='job' for r in scoped['matches']))
        self.assertNotIn(hit['id'],[r['id'] for r in scoped['matches']])

    def test_semantic_service_failure_returns_explicit_lexical_fallback(self):
        from scripts import semantic_search
        k.refresh(self.config);self.config['semantic_model_path']='missing'
        with patch.object(semantic_search,'search',return_value=dict(ok=False,reason='服务不可用',matches=[])):
            result=k.search(self.config,'客户销量')
        self.assertTrue(result['matches']);self.assertFalse(result['retrieval']['semantic_ready'])
        self.assertIn('不可用',result['retrieval']['notice'])

    def test_refresh_does_not_start_an_overlapping_semantic_build(self):
        from scripts import semantic_search
        k.refresh(self.config);self.config['semantic_model_path']='existing-local-model'
        progress=semantic_search.paths(self.config)[0].with_suffix('.progress.json')
        progress.write_text(json.dumps(dict(encoded=32,total=640)),encoding='utf-8')
        with patch.object(semantic_search,'build') as build:
            result=k.refresh_all(self.config)
        build.assert_not_called();self.assertIn('正在构建',result['semantic_error'])

    def test_semantic_windows_cover_long_source_tail(self):
        from scripts.semantic_search import windows
        body='甲'*3187+'尾部关键事实'
        chunks=list(windows(body))
        self.assertEqual(chunks[0][0],0);self.assertEqual(chunks[-1][1],len(body))
        self.assertIn('尾部关键事实',chunks[-1][2])
        self.assertTrue(all(b[0]<=a[1] for a,b in zip(chunks,chunks[1:])))

    def test_catalogue_alias_is_derived_from_real_project_records(self):
        pages=self.root/'formal'/'20-Projects';pages.mkdir()
        (pages/'项目索引.md').write_text('| [[企业采购问答知识库]] | 活跃 | `D:\\采购系统` | 继续 |',encoding='utf-8')
        (pages/'企业采购问答知识库.md').write_text('# 历史任务\n修复采购智能助理的调用失败。',encoding='utf-8')
        context=k.project_contexts(self.config,'采购智能助理以前失败的原因是什么')
        self.assertEqual(len(context),1);self.assertEqual(context[0][1],'d:\\采购系统')
        self.assertIn('智能',context[0][2])
        self.assertFalse(k.project_contexts(self.config,'完全无关的天气'))

    def test_copies_do_not_consume_search_result_slots(self):
        copied=self.root/'formal'/'复制的指标.md';copied.write_bytes(self.job.read_bytes())
        other=self.root/'job'/'客户细分.md';other.write_text('# 客户销量\n客户销量需要按客户分别统计。',encoding='utf-8')
        k.refresh(self.config);result=k.search(self.config,'客户销量',limit=3)
        hashes=[h['sha256'] for h in result['matches']]
        self.assertEqual(len(hashes),len(set(hashes)))
        self.assertIn(str(other),[h['path'] for h in result['matches']])

    def test_semantic_document_rank_is_independent_of_passage_count(self):
        from scripts import semantic_search
        self.personal.write_text('# 第一部分\n处理组。\n# 第二部分\n参照组。',encoding='utf-8')
        self.job.write_text('# 另一方法\n对比差异。',encoding='utf-8');k.refresh(self.config)
        with closing(k.connect(self.config)) as db:
            a=[r[0] for r in db.execute('SELECT id FROM passages WHERE path=?',(str(self.personal),))]
            b=db.execute('SELECT id FROM passages WHERE path=?',(str(self.job),)).fetchone()[0]
        self.config['semantic_model_path']='test-local-model'
        def run(ids):
            recalled=dict(ok=True,matches=[dict(id=pid,offset=0,end=80,similarity=.9-i*.01) for i,pid in enumerate(ids)])
            with patch.object(semantic_search,'search',return_value=recalled):
                return [h['path'] for h in k.search(self.config,'卖得好是不是活动的功劳',source='all')['matches']]
        self.assertEqual(run([a[0],b]),run(a+[b]))

    def test_semantic_cache_reuses_unchanged_sections_after_document_edit(self):
        import numpy as np
        from scripts import semantic_search as sem
        model=self.root/'local-model';model.mkdir();(model/'config.json').write_text('{}')
        self.config['semantic_model_path']=str(model)
        k.refresh(self.config)
        class Encoder:
            def encode(self,texts,**kwargs):return np.ones((len(texts),3),dtype=np.float32)
        with patch.object(sem,'encoder',return_value=Encoder()):
            first=sem.build(self.config)
            self.job.write_text(self.job.read_text(encoding='utf-8')+'\n# 新增独立记录\n新的补充事项。',encoding='utf-8')
            k.refresh(self.config);second=sem.build(self.config)
        self.assertEqual(second['encoded'],1)
        self.assertEqual(second['reused'],first['windows'])
