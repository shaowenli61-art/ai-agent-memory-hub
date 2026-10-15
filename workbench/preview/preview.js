/* Browser-only adapter for explicitly synthetic data. Never used by real mode. */
(() => {
  'use strict';
  const clone=x=>JSON.parse(JSON.stringify(x));
  const seed=JSON.parse(document.getElementById('previewFixture').textContent);
  const storageKey='memory-hub-synthetic-preview-v021-1';
  let state=clone(seed),persistent=true;
  try{const saved=JSON.parse(localStorage.getItem(storageKey)||'null');if(saved?.schema===1&&Array.isArray(saved.projects)&&saved.projects.length===7&&Array.isArray(saved.documents))state=saved;}catch{persistent=false;}
  function notice(text){const n=document.getElementById('previewStatus');if(n)n.textContent=text;}
  function save(){try{localStorage.setItem(storageKey,JSON.stringify(state));}catch{persistent=false;}notice(persistent?'虚拟决定已保存在本浏览器；刷新仍保留。未连接真实资料或外部AI。':'当前浏览器不允许本地保存；本次操作仍生效，刷新会恢复样例。');}
  const now=()=>new Date().toISOString();
  const ident=()=>`preview-${++state.sequence}-${Date.now()}`;
  function dialog(title,body){
    const d=document.createElement('dialog');d.className='preview-dialog';
    const h=document.createElement('h3');h.textContent=title;
    const pre=document.createElement('pre');pre.textContent=body;
    const b=document.createElement('button');b.textContent='关闭';b.addEventListener('click',()=>d.close());
    d.addEventListener('close',()=>d.remove());d.append(h,pre,b);document.body.append(d);d.showModal();
  }
  function fileText(file,p){return state.files[file.path]||`# ${p.project} · 虚拟成果\n\n本文件用于离线体验，不是实际业务报告。\n\n## 口径\n净销量 = 实际发货量 - 退货量。订单是计划，不能替代实际发货。\n\n## 示例\n发货120，退货8，净销量112。\n\n## 下一步\n${p.work_cycle.suggestion.next_step}\n\n文件：${file.path}\n版本：${file.signature}`;}
  function packet(p){return `# 接续工作：${p.project}（虚拟演示）\n项目：${p.path}\n当前决定：${p.lifecycle.state}\n目标：${p.current_brief.goal}\n\n## 当前摘要\n${p.current_brief.summary}\n尚未完成：${p.current_brief.remaining}\n\n## 建议下一步\n${p.work_cycle.suggestion.next_step}\n理由：${p.work_cycle.suggestion.reason}\n完成标准：${p.work_cycle.suggestion.criteria}\n\n## 当前采用版本\n${p.work_cycle.adopted.map(d=>d.title+' · '+d.purpose+(d.valid?'':'（文件已改变，需重验）')).join('\n')||'尚未采用'}\n\n## 本次参考资料\n${p.work_cycle.knowledge.map(d=>d.title+' · 第'+d.line+'行\n'+d.excerpt).join('\n\n')||'尚未选入'}\n\n## 交付要求\n核对资料后完成工作，说明变化、验证和未完成项，由本人判断采用。不得代本人恢复或结束项目。\n此接续包只生成文本，没有调用Agent或扩大执行授权。真实接续请从部署包读取skills/continuous-workbench/SKILL.md。`;}
  function withFeedback(p){
    const deliveries=p.work_cycle.deliveries.map(d=>`${d.title} · ${d.review_status}\n变化：${d.changes}\n已验证：${d.verification}\n本人反馈：${d.feedback||'尚未补充'}${p.work_cycle.reminders[d.id]?.until?'\n暂缓到：'+p.work_cycle.reminders[d.id].until:''}`).join('\n\n');
    return packet(p)+'\n\n## 近期交付与本人反馈\n'+deliveries;
  }
  function project(key){const p=state.projects.find(x=>x.lifecycle.project_key===key);if(!p)throw Error('未找到虚拟项目。');p.current_brief.lifecycle=p.lifecycle;p.current_brief.work_cycle=p.work_cycle;return p;}
  function snapshot(){
    const all=state.projects.map(p=>{
      const stateLabel={active:'跟进中',paused:'已暂停',ended:'已结束'}[p.lifecycle.state];
      p.current_brief.project_state=stateLabel;p.current_brief.lifecycle=p.lifecycle;p.current_brief.work_cycle=p.work_cycle;
      p.work_cycle.adopted=p.work_cycle.deliveries.filter(d=>d.review_status==='accepted'&&d.current_adoption!==false);
      p.work_cycle.packet=withFeedback(p);p.current_brief.continuation=p.work_cycle.packet;
      if(p.lifecycle.project_key==='report'){
        const needsReview=p.work_cycle.deliveries.some(d=>['pending','revise'].includes(d.review_status));
        p.bucket=needsReview?'等待判断':'正在推进';
        p.current_brief.summary=needsReview?'口径与初稿已有依据；新版本或修改意见等待本人判断。':'已记录本人验收决定，当前采用版本与历史版本分别保留。';
        p.current_brief.preview=p.current_brief.summary;
      }
      return p;
    });
    const active=all.filter(p=>p.lifecycle.state==='active'),archived=all.filter(p=>p.lifecycle.state!=='active');
    const pending=active.flatMap(p=>p.work_cycle.deliveries.filter(d=>d.review_status==='pending'||d.review_status==='revise').map(d=>({title:p.project+' · '+d.title,kind:d.review_status==='revise'?'待修改':'待验收',priority:'P1',status:'等待判断',reason:d.pending,next_action:'打开项目详情查看成果，作出采用、修改或暂缓决定。',source:'虚拟成果反馈',project_key:p.lifecycle.project_key})));
    const task_register=all.map(p=>({task:p.current_brief.task,status:p.current_brief.task_state,open:p.current_brief.task_state!=='阶段完成',source_target:p.source_target}));
    const completed=task_register.filter(t=>!t.open).length;
    const focus=active.filter(p=>p.lifecycle.project_key==='report').map(p=>({...p,task:p.project,progress:p.current_brief.preview,updated_at:p.current_brief.recorded_at}));
    return {generated_at:now(),projects:active,archived_projects:archived,recent_focus:focus,discovered_projects:[{task:'知识文档整理线索',status:'活动线索·待核实',progress:'虚拟会话中发现文档整理活动，尚未形成正式成果。',updated_at:seed.projects[0].current_brief.generated_at,new_project:true,active_candidate:true,discovery_reason:'只读活动线索，不能自动视为完成。',activity_evidence:[{kind:'activity',tool:'示例Agent',updated_at:seed.projects[0].current_brief.generated_at,assignment:'整理操作手册'}]}],
      emerging_projects:[{name:'流程自动汇总试验',status:'新信号',evidence_note:'发现虚拟活动线索，尚未正式立项。',decision:'核实价值与负责人后再决定是否立项。',path:'示例项目/自动汇总',latest_activity_date:'2026-10-15'}],
      projects_to_verify:active.filter(p=>p.bucket==='待核实 / 停滞'),recently_completed_projects:active.filter(p=>p.bucket==='阶段成果'),
      sources:[{label:'虚拟正式记忆',modified_at:seed.projects[0].current_brief.generated_at,age_days:0,stale:false},{label:'虚拟岗位库',modified_at:seed.projects[0].current_brief.generated_at,age_days:0,stale:false},{label:'虚拟个人库',modified_at:'2026-10-01T10:00:00+08:00',age_days:14,stale:true}],
      integration:{latest_source_modified_at:seed.projects[0].current_brief.generated_at,stale_source_count:1},metrics:{open_tasks:task_register.length-completed,blocked_tasks:1},
      task_register,task_ledgers:[{title:'虚拟复盘交付清单',total:8,completed:5,deferred:1,open:2,needs_review:1,conserved:true,current_scope:8}],task_ledger_summary:{formal_completed:completed,formal_deferred:0,formal_open:task_register.length-completed,total:8},
      decision_entries:pending,confirmation_queue:pending,omission_findings:[],activity_discovery:{review:[{title:'线索待核实',reason:'活动不覆盖正式验收，先核对成果。'}],warnings:[]},
      capabilities:[{domain:'经营差异分析',maturity:'🟢 已实践',judgement:'已有虚拟案例，仍需复验适用边界。'},{domain:'跨项目知识复用',maturity:'🟡 发展中',judgement:'指标定义已整理，跨场景需要补证。'},{domain:'因果判断与验证',maturity:'待补证',judgement:'方法候选，不把相关性当因果。'}],capability_gaps:[{priority:'P0',capability:'真实试用与独立复验'}],
      recommendations:[{type:'事实驱动',priority:'P0',recommendation:'先判断月报新版本，再推进更多交付。',basis:`虚拟项目中有${pending.length}个待判断版本；旧版不会自动替换。`,next_action:'从“月度经营复盘”查看来源与v2成果，决定采用、修改或暂缓。',stop_condition:'待判断成果有明确决定。'},{type:'推断',priority:'P1',recommendation:'核对历史口径与资料新鲜度。',basis:'岗位库保留一个已废止版本，个人库有较旧资料。',next_action:'检索原文，核对日期、粒度和适用条件。',stop_condition:'使用的口径与当前任务一致。'}]};
  }
  function coverage(){return {indexed_at:now(),sources:Object.fromEntries(['formal','job','personal'].map(source=>[source,{label:{formal:'虚拟正式记忆',job:'虚拟岗位库',personal:'虚拟个人库'}[source],indexed:state.documents.filter(d=>d.source===source).length}])),boundary:'仅虚拟内嵌Markdown资料；浏览器文字匹配演示，不运行真实语义模型。'};}
  function terms(s){s=String(s||'').toLowerCase().replace(/[^\p{L}\p{N}]/gu,'');return new Set([...s,...Array.from({length:Math.max(0,s.length-1)},(_,i)=>s.slice(i,i+2))]);}
  function search(r){
    if(!String(r.query||'').trim())throw Error('请描述想找的工作资料。');
    const q=terms(r.query);const filter=String(r.path_filter||'').toLowerCase();
    const matches=state.documents.filter(d=>(!r.source||r.source==='all'||r.source===d.source)&&(!filter||d.path.toLowerCase().includes(filter))).map(d=>{const title=terms(d.title+' '+d.heading),body=terms(d.body);let score=0;for(const t of q)score+=(title.has(t)?3:0)+(body.has(t)?1:0);return {...d,score};}).filter(d=>d.score>0).sort((a,b)=>b.score-a.score||Number(b.current)-Number(a.current)).slice(0,8);
    return {ok:true,matches,coverage:coverage(),seconds:0.01,retrieval:{method:'虚拟库文字匹配',notice:'离线交互样例；不是正式模型命中率或性能成绩。'}};
  }
  function deliver(p,incoming={}){
    const id=ident(),version=p.work_cycle.deliveries.length+1;
    const paths=Array.isArray(incoming.paths)?incoming.paths:[`${p.path}/成果v${version}.md`];
    if(!paths.length)throw Error('至少提供一个虚拟成果路径。');
    const d={id,title:incoming.title||`${p.project}成果 v${version}`,purpose:incoming.purpose||'当前项目成果',changes:incoming.changes||'根据反馈补充口径、来源与行动建议。',verification:incoming.verification||'虚拟交付：核对示例数据和输入输出。',pending:incoming.pending||'由本人判断是否采用。',files:paths.map((path,i)=>({id:id+'-file'+i,path,name:path.split(/[\\/]/).at(-1),exists:true,openable:true,signature:id+'-version'})),valid:true,origin:'虚拟Agent交付',review_status:'pending',feedback:'',replaces:incoming.replaces||p.work_cycle.deliveries[0]?.id||'',plan_id:''};
    p.work_cycle.deliveries.unshift(d);p.work_cycle.changes=['虚拟Agent已交付新版本，等待本人判断。'];return d;
  }
  function command(r){
    if(r.action==='search')return search(r);
    if(r.action==='refresh_knowledge')return {ok:true,coverage:coverage()};
    if(r.action==='open_knowledge'){
      const d=state.documents.find(x=>x.id===r.source_id);if(!d)throw Error('虚拟资料已不存在。');
      dialog(d.title,`${d.path} · 第${d.line}行\n\n${d.body}\n\n${d.notice}`);return {ok:true,opened:true};
    }
    const p=project(r.project_key),c=p.work_cycle,data=r.data||{};
    if(r.action==='packet'){if(p.lifecycle.state!=='active')throw Error('请先由本人恢复虚拟项目。');return {ok:true,packet:withFeedback(p)};}
    if(r.action==='open_artifact'){
      const d=c.deliveries.find(x=>x.id===r.delivery_id),f=d?.files.find(x=>x.id===r.file_id);if(!f)throw Error('未找到成果版本。');
      dialog(d.title+' · 虚拟原文',fileText(f,p));return {ok:true,opened:true};
    }
    if(r.revision!==c.revision)throw Error('演示记录已更新，请重新打开项目详情。');
    if(p.lifecycle.state!=='active'&&r.action!=='sample')throw Error('项目已暂停或结束，请先恢复跟进。');
    if(r.action==='adjust'){
      if(!String(data.next_step||'').trim())throw Error('下一步不能为空。');
      c.suggestion={...c.suggestion,next_step:data.next_step,criteria:data.criteria||c.suggestion.criteria,basis:'本人在虚拟页调整',reason:'保留本人判断，覆盖自动初步建议。',revision:ident()};
    }else if(r.action==='seen'){c.changes=[];c.seen_at=now();}
    else if(r.action==='delivery'){deliver(p,data);}
    else if(r.action==='review'){
      const d=c.deliveries.find(x=>x.id===data.delivery_id);if(!d)throw Error('未找到交付。');
      if(!['accepted','revise','deferred'].includes(data.status))throw Error('请选择验收决定。');
      if(data.status==='accepted'&&!d.valid)throw Error('已采用文件被模拟修改；请登记新版本并重新验收，不能接受旧版本。');
      if(data.status==='accepted'&&!data.purpose?.trim())throw Error('请填写采用用途。');
      if(data.status==='revise'&&!data.feedback?.trim())throw Error('请说明需要修改什么。');
      if(data.status==='deferred'&&(!data.until||data.until<=new Date().toISOString().slice(0,10)))throw Error('暂缓日期应晚于今天。');
      if(data.status==='accepted')for(const old of c.deliveries)if(old.purpose===data.purpose&&old.review_status==='accepted')old.current_adoption=false;
      d.review_status=data.status;d.purpose=data.purpose||d.purpose;d.feedback=data.feedback||'';
      if(data.status==='accepted')d.current_adoption=true;
      if(data.status==='deferred')c.reminders[d.id]={mode:'date',until:data.until};
      else delete c.reminders[d.id];
      c.changes=[data.status==='accepted'?'本人已采用当前版本；任务和项目状态仍分别保留。':data.status==='revise'?'已记录修改意见，接续包会包含反馈。':'已登记暂缓验收日期：'+data.until];
    }else if(r.action==='knowledge'){
      c.knowledge=(data.source_ids||[]).map(id=>state.documents.find(d=>d.id===id)).filter(Boolean);
    }else if(r.action==='sample'){
      if(!['before','after'].includes(data.phase)||!Number.isFinite(Number(data.minutes))||Number(data.minutes)<0||Number(data.minutes)>1440)throw Error('请填写有效的虚拟分钟数。');
      const sample={...data,project_key:p.lifecycle.project_key,synthetic:true,at:now()};state.samples.push(sample);
      dialog('已保存虚拟使用记录',`阶段：${data.phase==='before'?'使用前基线':'使用后'}\n分钟：${data.minutes}\n重复解释：${data.reexplains}\n\n仅用于体验记录方式，不能作为真实节时或用户成效。\n当前虚拟记录：${state.samples.length}条。`);
    }else throw Error('该操作不在离线体验范围内，请使用本地完整部署包。');
    c.revision=ident();state.events.push({action:r.action,project_key:p.lifecycle.project_key,at:now()});save();
    return {ok:true,event_id:c.revision,snapshot:snapshot()};
  }
  function lifecycle(r){const p=project(r.project_key);if(r.revision!==p.lifecycle.revision)throw Error('项目决定已更新，请重开详情。');if(!['active','paused','ended'].includes(r.state))throw Error('状态无效。');p.lifecycle={...p.lifecycle,state:r.state,revision:ident(),changed_at:now()};state.events.push({action:r.state,project_key:r.project_key,at:now()});save();return {ok:true,snapshot:snapshot()};}
  window.fetch=async(input,options={})=>{
    const url=String(input),response=(body,status=200)=>new Response(JSON.stringify(body),{status,headers:{'Content-Type':'application/json'}});
    try{
      if(url.includes('operations_snapshot.json'))return response(snapshot());
      const route=url.split('?')[0];
      if(!['/api/work-cycle','/api/project-lifecycle'].includes(route))return response({ok:false,error:'离线体验没有连接外部接口。'},404);
      if((options.method||'GET')==='GET')return response({token:'synthetic-browser-session'});
      const r=JSON.parse(options.body||'{}');return response(route==='/api/work-cycle'?command(r):lifecycle(r));
    }catch(e){return response({ok:false,error:e.message},400);}
  };
  window.previewDemo={snapshot,command,lifecycle,reset(){state=clone(seed);try{localStorage.removeItem(storageKey);}catch{}return snapshot();}};
  window.addEventListener('DOMContentLoaded',()=>{
    document.querySelector('.topbar .status')?.setAttribute('title','虚拟数据');
    const mode=document.querySelector('.mode-label');if(mode)mode.textContent='虚拟数据体验';
    function openReport(){const p=project('report');const key=registerRecord(recordForProject(p));openDrawer(key,document.getElementById('previewStart'));return p;}
    document.getElementById('previewStart').addEventListener('click',openReport);
    document.getElementById('previewDeliver').addEventListener('click',()=>{const p=project('report');if(p.lifecycle.state!=='active'){dialog('先恢复项目','请在归档区明确恢复跟进，再模拟交付。');return;}deliver(p);p.work_cycle.revision=ident();save();render(snapshot());openReport();});
    document.getElementById('previewChange').addEventListener('click',()=>{const p=project('report'),d=p.work_cycle.deliveries.find(x=>x.review_status==='accepted');if(!d){dialog('当前没有采用版本','先采用一个虚拟成果，再体验文件变更保护。');return;}d.valid=false;d.files.forEach(f=>f.signature+='-changed');p.work_cycle.changes=['已采用的文件发生模拟变更，旧验收不会自动沿用。'];p.work_cycle.revision=ident();save();render(snapshot());openReport();});
    document.getElementById('previewGuide').addEventListener('click',()=>dialog('功能与边界',`可以实际操作的离线流程\n1. 项目矩阵、任务总账、确认队列与资料新鲜度。\n2. 当前摘要、正式回执与未确认活动线索分别查看。\n3. 自动建议、人工调整、变化确认。\n4. 三类虚拟知识库检索、范围筛选、打开原文、加入和移除接续资料。\n5. 接续包预览、复制和下载Markdown。\n6. 模拟Agent交付、版本变化、原文查看与人工采用/修改/暂缓。\n7. 模拟已采用文件变更，拒绝接受失效版本。\n8. 暂停、结束归档、恢复、刷新保留与重置。\n9. 虚拟使用记录与方法论证据阶段。\n\n需要完整本地包的能力\n真实资料接入、原始文件读取与SHA256验证、真实语义模型、Agent执行、规则安装、升级和回退。\n本页只模拟其界面结果，不连接你的文件、AI服务或记忆库。所有数值均为虚构，不构成效果证据。`));
    document.getElementById('previewReset').addEventListener('click',()=>{window.previewDemo.reset();closeDrawer();render(snapshot());notice('已重置全部虚拟决定；没有修改任何真实资料。');});
    notice(persistent?'虚拟交互可保存到本浏览器；可随时重置。真实部署请让Agent读取INSTALL.md。':'浏览器不允许本地保存，刷新将恢复样例；其余交互仍可体验。');
  });
})();
