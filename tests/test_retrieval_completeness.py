"""Unrelated source examples exercising completeness, cache and derived views."""
import unittest,json,tempfile,sqlite3
from pathlib import Path
from unittest.mock import patch
from scripts import knowledge_search as k,knowledge_evidence as e

class CompletenessTests(unittest.TestCase):
 def test_receipt_context_keeps_action_and_late_reason(self):
  body='## 任务收工：设备认证修复\n- **收工回执**：MC-TEST\n- **当前状态**：已完成\n- **本次完成**：建立经过核验的设备编号桥接，原认证不变。\n- **验证方式与结果**：'+('测试通过，保留记录。'*32)+'\n- **尚未完成**：用户实际设备验收。\n- **残留风险**：未知编号拒绝访问。\n- **禁止重踩**：显示名称与设备序列号不是同一身份空间，不可按名称放权。\n- **关键文件**：D:/设备/认证.py\n'
  row=('id','D:/设备.md','设备','任务收工：设备认证修复',1,body,'formal','设备.md','date','hash',0)
  a,b=e.complete_span(row,body.index('建立'),body.index('建立')+40)
  self.assertIn('建立经过核验',body[a:b]);self.assertIn('不是同一身份空间',body[a:b]);self.assertNotIn('D:/设备/',body[a:b])
 def test_cause_explanation_keeps_section_preamble(self):
  body='## 故障排查\n\n不要先假设容量不够，应先核实重复加载。\n\n检查步骤：\n'+('先检查设备状态。'*24)+'\n因为缓存写得太晚导致重入；先写缓存再做后续还原。\n\n下一章节与本次故障无关。\n'
  row=('id','D:/设备.md','设备','故障排查',1,body,'job','设备.md','date','hash',0)
  a,b=e.complete_span(row,body.index('因为'),body.index('因为')+35)
  self.assertIn('不要先假设',body[a:b]);self.assertIn('先写缓存',body[a:b]);self.assertLessEqual(b-a,1200)
 def test_each_core_bullet_is_an_independent_definition(self):
  body='## 核心要点\n- 诊断型：从现象追踪原因，核实关键变量与数据。\n- 决策型：通过成本收益比较确定资源投入优先顺序。\n'
  row=('id','D:/设备.md','设备方法','核心要点',1,body,'personal','设备.md','date','hash',0)
  cards=list(e.definition_cards([row]));self.assertTrue(any('决策型' in c['text'] and '诊断型' not in c['text'] for c in cards))
 def test_version_cache_survives_a_fresh_process_cache_and_invalidates(self):
  with tempfile.TemporaryDirectory() as td:
   path=Path(td)/'index.sqlite3';db=sqlite3.connect(path);db.executescript('CREATE TABLE documents(path,source,relative,modified,hash);CREATE TABLE passages(id,path,title,heading,line,body);');db.close()
   k.version_catalog.cache_clear()
   with patch.object(e,'version_rules',return_value=[]) as build:k.version_catalog(str(path),'r1');self.assertEqual(build.call_count,1)
   k.version_catalog.cache_clear()
   with patch.object(e,'version_rules',return_value=[]) as build:k.version_catalog(str(path),'r1');self.assertEqual(build.call_count,0)
   with patch.object(e,'version_rules',return_value=[]) as build:k.version_catalog(str(path),'r2');self.assertEqual(build.call_count,1)
 def test_cached_scope_sets_roundtrip_and_corrupt_cache_rebuilds(self):
  with tempfile.TemporaryDirectory() as td:
   path=Path(td)/'index.sqlite3';db=sqlite3.connect(path);db.executescript('CREATE TABLE documents(path,source,relative,modified,hash);CREATE TABLE passages(id,path,title,heading,line,body);');db.close()
   rules=[dict(scope={'设备','认证'},target='old.md',authority='new.md',phrase='旧账号',explicit=False)]
   k.version_catalog.cache_clear()
   with patch.object(e,'version_rules',return_value=rules):self.assertEqual(k.version_catalog(str(path),'r1'),rules)
   k.version_catalog.cache_clear()
   with patch.object(e,'version_rules',side_effect=AssertionError('should reuse')):self.assertEqual(k.version_catalog(str(path),'r1'),rules)
   for broken in ('{broken','[]'):
    path.with_suffix('.versions.json').write_text(broken,encoding='utf8');k.version_catalog.cache_clear()
    with patch.object(e,'version_rules',return_value=rules) as build:self.assertEqual(k.version_catalog(str(path),'r1'),rules);self.assertEqual(build.call_count,1)

if __name__=='__main__':unittest.main()
