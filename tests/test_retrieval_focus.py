"""Regression seams for question form, mapping rows and independent task scope."""
import json,sys,tempfile,unittest
from pathlib import Path
from contextlib import closing
from unittest.mock import patch
sys.path.insert(0,str(Path.cwd()))
from scripts import knowledge_search as k,knowledge_evidence as e,semantic_search as sem

class Feedback(unittest.TestCase):
 def test_mapping_header_survives_a_passage_boundary(self):
  first=('a','D:/设备.md','设备方法','方法选型',1,'| 场景 | 方法 |\n| --- | --- |\n','personal','设备.md','date','hash',0)
  second=('b','D:/设备.md','设备方法','方法选型',3,'| 预测部件何时失效 | 寿命模型 |\n','personal','设备.md','date','hash',0)
  cards=list(e.table_cards([second,first]));self.assertEqual(len(cards),1);self.assertEqual(cards[0]['id'],'b');self.assertIn('场景：预测',cards[0]['text'])
 def test_repair_question_needs_actions_not_a_generic_cause_word(self):
  q='采购日期理解错误是怎样修复的'
  self.assertGreater(e.intent_fit(q,'已修正解析，补充澄清与规范化，校验请求时间范围。'),e.intent_fit(q,'因为生产投入增加导致成本变化。'))
 def test_colloquial_judgment_is_a_judgment(self):
  self.assertEqual(e.intent_fit('改了设备名字是不是就能启动？','名字不等于身份，必须先通过系统认证。'),1)
 def test_mapping_row_has_its_own_source_view(self):
  body='## 方法选型\n| 业务问题 | 分析方法 | 条件 |\n| --- | --- | --- |\n| 部件什么时候坏、什么因素加快损坏 | 寿命模型 | 记录失效时间 |\n'
  r=('id','D:/设备.md','设备方法','方法选型',1,body,'personal','设备.md','date','hash',0)
  cards=list(e.evidence_cards([r]));found=[x for x in cards if x.get('kind')=='mapping']
  self.assertTrue(found);self.assertIn('业务问题',found[0]['text']);self.assertIn('寿命模型',found[0]['text']);self.assertIn(body[found[0]['offset']:found[0]['end']],body)
 def test_independent_tasks_in_same_file_are_not_erased(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);cfg=dict(snapshot_output=str(root/'snapshot.json'),semantic_model_path='test')
   for key in ('memory_hub_root','job_vault_root','personal_vault_root'):p=root/key;p.mkdir();cfg[key]=str(p)
   p=Path(cfg['memory_hub_root'])/'2026-01-01-worklog.md'
   p.write_text('# 任务收工：未知重量治理\n未知重量不能当成零。\n# 任务收工：图表缺失重量展示\n图表可在零刻度展示未知重量，但正式统计不能当零。',encoding='utf-8');k.refresh(cfg)
   with closing(k.connect(cfg)) as c:ids=[r[0] for r in c.execute('SELECT id FROM passages ORDER BY line')]
   response=dict(ok=True,matches=[dict(id=pid,offset=0,end=150,similarity=.8-i*.01) for i,pid in enumerate(ids)])
   with patch.object(sem,'search',return_value=response):r=k.search(cfg,'未知重量图上标零，统计能不能按零算？')
   self.assertEqual(len(r['matches']),2)

class RankerBoundaries(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name);self.cfg=dict(snapshot_output=str(self.root/'snapshot.json'),semantic_model_path='test')
  for source,(_,key) in k.SOURCES.items():p=self.root/source;p.mkdir();self.cfg[key]=str(p)
  p=self.root/'job'/'规范.md';p.write_text('# 使用范围\n设备采用独立认证，不能按显示名称自动授权。\n# 历史记录\n测试通过后增加缓存，不改变认证规则。',encoding='utf-8');k.refresh(self.cfg)
  with closing(k.connect(self.cfg)) as c:self.rows=c.execute('SELECT id,heading,body FROM passages WHERE path=? ORDER BY line',(str(p),)).fetchall()
 def response(self):
  return dict(ok=True,matches=[dict(id=r[0],offset=0,end=len(r[2]),similarity=.7-i*.02) for i,r in enumerate(self.rows)])
 def test_source_and_relative_filter_apply_again_at_reranking(self):
  items=[dict(id=self.rows[0][0],offset=0,end=10)]
  self.assertTrue(sem.rerank_passages(self.cfg,items,'job'))
  self.assertFalse(sem.rerank_passages(self.cfg,items,'personal'))
  self.assertFalse(sem.rerank_passages(self.cfg,items,'all','另一个目录'))
  self.assertFalse(sem.rerank_passages(self.cfg,[dict(id='removed',offset=0,end=10)]))
 def test_candidate_payload_and_source_offsets_are_bounded(self):
  with self.assertRaises(ValueError):sem.rerank_passages(self.cfg,[dict(id='x',offset=0,end=10)]*65)
  with self.assertRaises(ValueError):sem.rerank_passages(self.cfg,[dict(id='x',offset=.5,end=10)])
  with self.assertRaises(ValueError):sem.rerank_passages(self.cfg,[dict(id='x',offset=0,end=701)])
 def test_missing_ranker_falls_back_without_changing_results(self):
  q='设备名字改变后是不是就能使用？'
  with patch.object(sem,'search',return_value=self.response()):original=k.search(self.cfg,q)
  self.cfg['reranker_model_path']='test'
  with patch.object(sem,'search',return_value=self.response()),patch.object(sem,'rerank',side_effect=TimeoutError('unavailable')):actual=k.search(self.cfg,q)
  self.assertEqual(actual['matches'],original['matches']);self.assertFalse(actual['retrieval']['rerank_ready']);self.assertIn('保留原检索',actual['retrieval']['notice'])
 def test_neural_selected_excerpt_is_not_replaced_by_another_refinement(self):
  self.cfg['reranker_model_path']='test';pid,_,body=self.rows[1]
  selected={}
  def rank(cfg,query,candidates,*args):
   chosen=next(x for x in candidates if x['id']==pid);selected.update(chosen)
   items=[dict(**x,score=10. if x==chosen else -10.) for x in candidates]
   return dict(ok=True,scores=items)
  with patch.object(sem,'search',return_value=self.response()),patch.object(sem,'rerank',side_effect=rank):r=k.search(self.cfg,'设备测试历史做了什么？')
  self.assertTrue(r['retrieval']['rerank_ready']);self.assertEqual(r['matches'][0]['id'],pid);self.assertEqual(r['matches'][0]['excerpt'],body[selected['offset']:selected['end']])
 def test_overview_does_not_erase_another_section_of_the_same_source(self):
  self.cfg['reranker_model_path']='test'
  def rank(cfg,query,candidates,*args):
   return dict(ok=True,scores=[dict(**x,score=2.) for x in candidates])
  with patch.object(sem,'search',return_value=self.response()),patch.object(sem,'rerank',side_effect=rank):r=k.search(self.cfg,'设备认证与测试有什么依据？')
  self.assertEqual({m['heading'] for m in r['matches']},{'使用范围','历史记录'})
  self.assertEqual(len({m['path'] for m in r['matches']}),1)

if __name__=='__main__':unittest.main()
