import hashlib
import json
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
from scripts import knowledge_search as k,knowledge_evidence as e,semantic_search as sem


def row(title,heading,body,path=None,line=1):
    return ('id-'+title,path or 'D:\\库\\'+title+'.md',title,heading,line,body,'job',title+'.md','2026-01-01','hash',0)


class EvidenceRulesTests(unittest.TestCase):
    def test_path_heavy_historical_entry_keeps_real_cause(self):
        text='- 本次记录：样机恢复供电。根因是控制进程读取旧配置，重启后重新加载。证据：'+('D:\\设备\\输出\\'+('检查目录'*30)+'.png ')*5
        r=row('设备档案','历史进展摘要',text)
        self.assertTrue(e.has_explanation(text))
        cards=list(e.evidence_cards([r]))
        self.assertTrue(any('读取旧配置' in c['text'] for c in cards))
        self.assertTrue(all('D:\\设备' not in c['text'] for c in cards))
        for card in cards:self.assertIn(text[card['offset']:card['end']],text)

    def test_individual_boundary_claims_preserve_their_source_offset(self):
        text='## 核心要点\n- 设备维护先检查电源。\n- 仅标注操作员名字不能获得启动许可，授权由认证系统决定。\n'
        cards=list(e.evidence_cards([row('设备操作','核心要点',text)]))
        self.assertTrue(any(c['offset']==text.index('- 仅') for c in cards))
        self.assertEqual(e.intent_fit('把名字改成管理员就能启动设备吗？',text),1)
        self.assertEqual(e.intent_fit('为何重启后恢复？','控制进程未加载新配置，导致启动失败。'),1)

    def test_raw_speech_does_not_become_a_normative_claim_view(self):
        r=row('设备讨论-原文转写','原文','因为控制器出错，所以不能开机，这个只是随口讨论。')
        self.assertFalse(list(e.evidence_cards([r])))

    def test_new_phrase_in_a_historical_comparison_is_not_retired(self):
        authority=row('采购流程规范','当前事实入口','采购数据以“签收入库数”为事实；若与历史笔记冲突，以当前规则为准。')
        target=row('采购流程说明','入库字段','本字段采用签收入库数。')
        self.assertFalse(e.retired_by(target,e.version_rules([authority,target])))

    def test_combined_old_formulation_does_not_retire_each_component(self):
        authority=row('采购流程规范','当前事实入口','历史文档中的“凭合同、按货架计数”已经废止。')
        old=row('采购流程旧说明','定义','本阶段凭合同、按货架计数。')
        component=row('采购流程新说明','定义','此处仍可凭合同核对供应商信息。')
        rules=e.version_rules([authority,old,component])
        self.assertTrue(e.retired_by(old,rules));self.assertFalse(e.retired_by(component,rules))

    def test_superseding_metadata_needs_an_indexed_unambiguous_target(self):
        old=row('采购方案旧版','', '---\nsupersededBy: "采购方案新版.md"\n---\n旧内容')
        new=row('采购方案新版','', '---\nsupersedes: ["采购方案旧版.md"]\n---\n新内容')
        rules=e.version_rules([old,new]);self.assertTrue(e.retired_by(old,rules));self.assertFalse(e.retired_by(new,rules))
        missing=row('孤立文件','', '---\nsupersededBy: "../../secret.md"\n---\n内容')
        self.assertFalse(e.version_rules([missing]))

    def test_legacy_receipt_follows_the_named_normative_document(self):
        standard=row('采购数据标准','当前事实入口','当前有效规则。')
        receipt=row('2026-01-01-worklog','采购数据标准提炼','- **任务目标**：提炼规则。\n- **修改文件**：`D:\\其他仓库\\采购数据标准.md`\n- **残留风险**：旧文档仍写“手抄口径/旧计算法”，后续以本标准为准，不引用旧注释。')
        old=row('采购数据旧说明','手抄口径','这里采用手抄口径。')
        rules=e.version_rules([standard,receipt,old]);claim=e.retired_by(old,rules)[0]
        self.assertEqual(claim['authority'],standard[1]);self.assertEqual(claim['basis_path'],receipt[1])

    def test_frontmatter_and_paths_have_no_explanatory_weight(self):
        body='\n---\n类型: local_audio\n说明: 仅为来源元数据\n---\n'
        self.assertEqual(e.content_quality(body),0)
        self.assertEqual(e.content_quality('- **关键文件**：D:\\项目\\output\\最终测试.md'),0)

    def test_span_preserves_original_text_and_boundary(self):
        body='## 任务收工：样机验证\n- **本次完成**：生成检测样机。\n- **尚未完成**：压力测试未完成，不能量产。\n- **关键文件**：D:\\设备\\output\\样机最终成功.md\n'
        r=row('设备试验','任务收工：样机验证',body)
        hit=dict(offset=body.index('D:'),end=len(body),similarity=.9)
        a,b,q=e.choose_span(r,'样机能不能量产',{'样机':2,'量产':2},hit)
        self.assertIn('不能量产',body[a:b]);self.assertGreater(q,0)
        self.assertIn(a,[x[0] for x in e.lines(body)])


class EvidenceSearchTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.cfg=dict(snapshot_output=str(self.root/'snapshot.json'))
        for src,(_,key) in k.SOURCES.items():
            p=self.root/src;p.mkdir();self.cfg[key]=str(p)

    def write(self,src,name,text):
        p=self.root/src/(name+'.md');p.write_text(text,encoding='utf-8');return p

    def test_decision_fragment_competes_with_another_section_in_same_file(self):
        target=self.write('job','仓储规范','# 汇总规则\n日报按车间统计入库数量。\n# 禁止项\n禁止把车间日报用作单件追溯底表，它没有序列号粒度。')
        k.refresh(self.cfg)
        with closing(k.connect(self.cfg)) as c:rs=c.execute('SELECT id,heading FROM passages').fetchall()
        summary=next(x[0] for x in rs if x[1]=='汇总规则');detail=next(x[0] for x in rs if x[1]=='禁止项')
        self.cfg['semantic_model_path']='test'
        response=dict(ok=True,matches=[dict(id=summary,offset=0,end=50,similarity=.65)],definitions=[dict(id=detail,offset=6,end=80,similarity=.63)])
        with patch.object(sem,'search',return_value=response):r=k.search(self.cfg,'查单件追溯能用车间日报做底表吗？')
        self.assertEqual(r['matches'][0]['path'],str(target))
        self.assertIn('没有序列号粒度',r['matches'][0]['excerpt'])
        self.assertEqual(r['matches'][0]['id'],detail)

    def test_independent_definition_recall_without_query_word_overlap(self):
        target=self.write('personal','隔离机制','# 核心要点\n认证凭证和后端校验决定可读取范围，聊天自称职务不具备授权效力。')
        k.refresh(self.cfg)
        with closing(k.connect(self.cfg)) as c:pid=c.execute('SELECT id FROM passages').fetchone()[0]
        self.cfg['semantic_model_path']='test'
        response=dict(ok=True,matches=[],definitions=[dict(id=pid,offset=0,end=100,similarity=.8)])
        with patch.object(sem,'search',return_value=response):
            result=k.search(self.cfg,'名字改成老板就能打开整个公司的材料吗')
            scoped=k.search(self.cfg,'名字改成老板就能打开整个公司的材料吗',source='job')
        self.assertEqual(result['matches'][0]['path'],str(target));self.assertFalse(scoped['matches'])

    def test_path_hit_uses_same_task_explanation_and_verifiable_id(self):
        body='# 任务收工：设备验证\n- **本次完成**：生成检测样机。\n- **尚未完成**：压力测试未完成，不能量产。\n'+'- **关键文件**：D:\\设备\\output\\样机成功.md\n'*55
        target=self.write('formal','试验日志',body);k.refresh(self.cfg)
        with closing(k.connect(self.cfg)) as c:
            parts=c.execute('SELECT id,body FROM passages WHERE path=? ORDER BY line',(str(target),)).fetchall()
        pid,text=parts[-1];self.cfg['semantic_model_path']='test'
        response=dict(ok=True,matches=[dict(id=pid,offset=0,end=400,similarity=.99)])
        with patch.object(sem,'search',return_value=response):result=k.search(self.cfg,'样机能不能量产')
        hit=result['matches'][0]
        self.assertIn('不能量产',hit['excerpt']);resolved=k.resolve(self.cfg,hit['id'])
        self.assertIn(hit['excerpt'],resolved['excerpt']);self.assertNotEqual(hit['id'],pid)

    def test_replaced_file_ranks_after_successor_without_losing_history(self):
        old=self.write('job','采购旧办法','---\nsupersededBy: "采购新办法.md"\n---\n# 采购入库统计\n采购入库统计采用手抄方式，采购入库数据汇总。')
        new=self.write('job','采购新办法','# 当前事实入口\n采购入库统计采用签收记录。')
        k.refresh(self.cfg);result=k.search(self.cfg,'采购入库统计')
        self.assertEqual(result['matches'][0]['path'],str(new))
        old_hit=next(h for h in result['matches'] if h['path']==str(old));self.assertIn('替代声明',old_hit['notice'])
        history=k.search(self.cfg,'以前采购入库统计采用什么办法')
        self.assertTrue(any(h['path']==str(old) for h in history['matches']))
        self.assertEqual(hashlib.sha256(old.read_bytes()).hexdigest(),old_hit['sha256'])

    def test_optional_definition_cache_failure_does_not_require_model_call(self):
        import numpy as np
        target=sem.definition_path(self.cfg);target.write_bytes(b'broken cache')
        result,notice=sem.definition_results(self.cfg,{},np.ones(3),{'valid-id'})
        self.assertEqual(result,[]);self.assertIn('保留正文语义',notice)

    def test_definition_view_checks_current_scope_and_removed_ids(self):
        import numpy as np
        target=sem.definition_path(self.cfg)
        np.savez(target,fingerprint=np.asarray(sem.fingerprint(self.cfg)),ids=np.asarray(['removed-id','valid-id']),offsets=np.asarray([0,0]),ends=np.asarray([50,50]),vectors=np.ones((2,3)))
        result,notice=sem.definition_results(self.cfg,{},np.ones(3),{'valid-id'})
        self.assertEqual([x['id'] for x in result],['valid-id']);self.assertFalse(notice)

    def test_large_claim_pool_does_not_evict_the_definition_view(self):
        import numpy as np
        ids=['rule-'+str(i) for i in range(120)]+['concept']
        vectors=np.asarray([[1.,0.]]*120+[[.3,0.]])
        np.savez(sem.definition_path(self.cfg),fingerprint=np.asarray(sem.fingerprint(self.cfg)),ids=np.asarray(ids),offsets=np.zeros(121,dtype=int),ends=np.full(121,50),kinds=np.asarray(['claim']*120+['definition']),vectors=vectors)
        result,notice=sem.definition_results(self.cfg,{},np.asarray([1.,0.]),dict.fromkeys(ids))
        self.assertFalse(notice)
        self.assertEqual(sum(h['kind']=='claim' for h in result),40)
        self.assertIn('concept',[h['id'] for h in result])


if __name__=='__main__':unittest.main()
