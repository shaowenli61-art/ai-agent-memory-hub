import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from scripts.build_standalone_demo import build,fixture

ROOT=Path(__file__).resolve().parents[1]

class StandaloneDemoTests(unittest.TestCase):
    def test_html_is_self_contained_and_fixture_has_no_machine_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'体验.html';build(path);text=path.read_text(encoding='utf-8')
            self.assertNotIn('<script src=',text);self.assertNotIn('<link rel="stylesheet"',text)
            self.assertIn('虚拟数据 · 离线交互',text)
            raw=re.search(r'<script id="previewFixture" type="application/json">(.*?)</script>',text,re.S).group(1)
            data=json.loads(raw)
            self.assertEqual(len(data['projects']),7);self.assertEqual(len(data['documents']),7)
            self.assertNotRegex(raw,r'[A-Z]:[\\/]|/Users/|/home/')
            self.assertEqual({p['lifecycle']['state'] for p in data['projects']},{'active','paused','ended'})

    @unittest.skipUnless(shutil.which('node'),'Node is optional for this JavaScript regression')
    def test_virtual_workflow_state_and_guards_without_network(self):
        harness=r'''
const vm=require('node:vm'),fs=require('node:fs'),assert=require('node:assert/strict');
const fixture=JSON.parse(fs.readFileSync(process.argv[1],'utf8'));
const store=new Map();const node=()=>({append(){},addEventListener(){},showModal(){},close(){}});
const context={console,Date,Set,Map,JSON,Response,localStorage:{getItem:k=>store.get(k)||null,setItem:(k,v)=>store.set(k,v),removeItem:k=>store.delete(k)},
 document:{getElementById:id=>id==='previewFixture'?{textContent:JSON.stringify(fixture)}:{textContent:''},createElement:node,body:node()},window:{addEventListener(){}}};
vm.createContext(context);const code=fs.readFileSync(process.argv[2],'utf8');vm.runInContext(code,context);
const api=context.window.previewDemo;let s=api.snapshot();let p=s.projects.find(p=>p.lifecycle.project_key==='report');
let r=api.command({action:'search',query:'净销量退货订单',source:'job'});assert.equal(r.matches[0].id,'kb-net-current');assert.ok(r.matches.every(x=>x.source==='job'));
r=api.command({action:'knowledge',project_key:'report',revision:p.work_cycle.revision,data:{source_ids:['kb-management']}});p=r.snapshot.projects.find(p=>p.lifecycle.project_key==='report');
assert.ok(api.command({action:'packet',project_key:'report'}).packet.includes('管理方法'));
assert.throws(()=>api.command({action:'adjust',project_key:'report',revision:'stale',data:{next_step:'x'}}),/更新/);
r=api.command({action:'review',project_key:'report',revision:p.work_cycle.revision,data:{delivery_id:'report-delivery-v2',status:'accepted',purpose:'当前项目成果'}});p=r.snapshot.projects.find(p=>p.lifecycle.project_key==='report');
assert.equal(p.work_cycle.adopted.length,1);assert.equal(p.work_cycle.adopted[0].id,'report-delivery-v2');
p.work_cycle.adopted[0].valid=false;
assert.throws(()=>api.command({action:'review',project_key:'report',revision:p.work_cycle.revision,data:{delivery_id:'report-delivery-v2',status:'accepted',purpose:'当前项目成果'}}),/修改/);
api.command({action:'review',project_key:'report',revision:p.work_cycle.revision,data:{delivery_id:'report-delivery-v2',status:'revise',feedback:'请补充退货跨期解释'}});
assert.ok(api.command({action:'packet',project_key:'report'}).packet.includes('请补充退货跨期解释'));
r=api.command({action:'delivery',project_key:'report',revision:p.work_cycle.revision,data:{title:'重交版',paths:['示例项目/修订.md']}});p=r.snapshot.projects.find(p=>p.lifecycle.project_key==='report');assert.equal(p.work_cycle.deliveries[0].title,'重交版');
r=api.lifecycle({project_key:'report',revision:p.lifecycle.revision,state:'ended'});p=r.snapshot.archived_projects.find(p=>p.lifecycle.project_key==='report');assert.ok(p);assert.throws(()=>api.command({action:'packet',project_key:'report'}),/恢复/);
vm.runInContext(code,context);assert.ok(context.window.previewDemo.snapshot().archived_projects.some(p=>p.lifecycle.project_key==='report'));
context.window.previewDemo.reset();assert.equal(context.window.previewDemo.snapshot().projects.length,5);
(async()=>{const denied=await context.window.fetch('https://example.invalid/api');assert.equal(denied.status,404);console.log('virtual workflow PASS');})();
'''
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'fixture.json';path.write_text(json.dumps(fixture(),ensure_ascii=False),encoding='utf-8')
            result=subprocess.run(['node','-e',harness,str(path),str(ROOT/'workbench/preview/preview.js')],capture_output=True,text=True,timeout=15)
            self.assertEqual(result.returncode,0,result.stderr)
