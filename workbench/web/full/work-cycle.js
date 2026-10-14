/* Explicit decisions and disposable views share the same server projection. */
window.workCycle = (() => {
  const el = (tag, cls, text) => element(tag, cls, text);
  let snapshot;
  function button(text, fn, cls='wc-button') {
    const b=el('button',cls,text); b.type='button';
    b.addEventListener('click', async()=>{b.disabled=true;try{await fn();}finally{b.disabled=false;}});return b;
  }
  function message(host,text,error=false){host.textContent=text;host.className=error?'wc-error':'wc-note';}
  function status(){const p=el('p','wc-note');p.setAttribute('role','status');p.setAttribute('aria-live','polite');return p;}
  function projects(){return [...new Map(['projects','recent_focus','discovered_projects','archived_projects'].flatMap(g=>snapshot?.[g]||[]).map(p=>[p.lifecycle?.project_key,p])).values()];}
  function project(key){return projects().find(p=>p.lifecycle?.project_key===key);}
  async function api(request){
    const session=await fetch('/api/work-cycle',{cache:'no-store'});
    if(!session.ok)throw new Error('本地服务尚未更新，请打开新版工作台。');
    const {token}=await session.json();
    const response=await fetch('/api/work-cycle',{method:'POST',headers:{'Content-Type':'application/json','X-Workbench-Token':token},body:JSON.stringify(request)});
    const result=await response.json(); if(!response.ok||!result.ok)throw new Error(result.error||'本次操作未完成');
    return result;
  }
  async function mutate(brief,action,data,output){
    try{
      message(output,'正在保存…');
      const key=brief.lifecycle.project_key;
      const result=await api({project_key:key,revision:brief.work_cycle.revision,action,data});
      render(result.snapshot);
      const current=project(key)?.current_brief;
      if(current)renderBrief(current);
      const target=document.querySelector('#workCycleProject > [role="status"]');if(target)message(target,'已保存；所有接续入口使用同一份记录。');
      return true;
    }catch(error){message(output,error.message,true);return false;}
  }
  function open(key,trigger){const p=project(key);if(!p)return;const record=recordForProject(p);const id=`wc-${key}`;dashboardState.records.set(id,record);openDrawer(id,trigger);}
  function section(title){const n=el('section','wc-section');n.append(el('h3','',title));return n;}
  function details(title){const n=el('details','wc-details');n.append(el('summary','',title));return n;}
  function field(form,name,label,value='',required=false,type='text'){
    const wrap=el('label','wc-field',label);const input=el(type==='textarea'?'textarea':'input');input.name=name;
    if(type!=='textarea')input.type=type;else input.rows=3;
    input.value=value||'';input.required=required;input.maxLength=4000;wrap.append(input);form.append(wrap);return input;
  }
  function formSubmit(form,label,fn){const p=status(),b=el('button','wc-button primary',label);b.type='submit';form.append(b,p);form.addEventListener('submit',async e=>{e.preventDefault();b.disabled=true;try{await fn(Object.fromEntries(new FormData(form)),p);}finally{b.disabled=false;}});}
  function renderDaily(data){
    snapshot=data;
    const host=document.getElementById('knowledgeSearch');
    if(!host.children.length)renderSearch(host);
  }
  function renderProject(brief){
    const host=document.getElementById('workCycleProject');host.replaceChildren();host.hidden=!brief?.work_cycle;if(host.hidden)return;
    const cycle=brief.work_cycle,active=brief.lifecycle.state==='active';host.append(status());
    const advice=cycle.suggestion||{next_step:brief.next_action,reason:brief.next_basis,basis:brief.basis,criteria:'核对验证结果',needs_judgment:'判断是否继续。'};
    const resume=section(active?advice.label:'项目当前决定');const plan=cycle.plan;
    resume.append(el('h4','wc-advice-step',advice.next_step),el('p','wc-note',advice.reason));
    if(active){
      resume.append(el('p','wc-note',`需要你判断：${advice.needs_judgment}`));
      const edit=details('调整建议');const f=el('form','wc-form');
      field(f,'next_step','你希望下一步做什么',advice.next_step,true,'textarea');
      const criteria=details('调整完成标准（可选）');const c=el('div');field(c,'criteria','完成标准',advice.criteria,false,'textarea');criteria.append(c);f.append(criteria);
      formSubmit(f,'保存调整',(data,p)=>mutate(brief,'adjust',{...data,advice_revision:advice.revision},p));edit.append(f);resume.append(edit);
    }
    const why=details('建议依据与当前变化');why.append(el('p','wc-note',`依据：${advice.basis}`),el('p','wc-note',`建议完成标准：${advice.criteria||'当前无需执行'}`));
    for(const change of cycle.changes)why.append(el('p','wc-change',change));
    if(plan?.due)why.append(el('p','wc-note',`检查日期：${plan.due}`));
    const seenStatus=status();why.append(button('已了解这些变化',()=>mutate(brief,'seen',{},seenStatus)),seenStatus);resume.append(why);
    host.append(resume);
    const adopted=section('当前采用的成果');

    for(const d of cycle.adopted){const card=el('article','wc-delivery adopted');card.append(el('small','',d.purpose),el('h4','',d.title),el('p',d.valid?'wc-note':'wc-error',d.valid?'本人已确认采用 · 文件版本未变':'采用后的文件已改变或丢失，需重新登记并确认'));addFiles(card,d,brief);adopted.append(card);}if(cycle.adopted.length)host.append(adopted);
    const deliveries=details(`成果与反馈 · ${cycle.deliveries.length} 项`);
    for(const d of cycle.deliveries){
      const card=el('article','wc-delivery');card.append(el('small','',`${d.origin} · ${{candidate:'候选，未确认',pending:'待验收',accepted:'已采用',revise:'待修改',deferred:'暂缓'}[d.review_status]}`),el('h4','',d.title));
      for(const [label,value] of [['变化',d.changes],['已验证',d.verification],['还需判断',d.pending],['我的反馈',d.feedback]])if(value)card.append(el('p','wc-note',`${label}：${value}`));
      if(d.replaces)card.append(el('p','wc-note',`替代版本：${cycle.deliveries.find(x=>x.id===d.replaces)?.title||d.replaces}`));addFiles(card,d,brief);
      if(active){const review=details('查看后作出决定');const rf=el('form','wc-form');field(rf,'purpose','采用用途（如：正式报告／设计稿）',d.purpose==='待选择用途'?'当前项目成果':d.purpose,true);field(rf,'feedback','修改意见或判断说明',d.feedback||'',false,'textarea');
        const choice=el('label','wc-field','验收决定'),select=el('select');select.name='status';select.setAttribute('aria-label','验收决定');for(const [v,l] of [['accepted','采用这个版本'],['revise','需要修改'],['deferred','暂缓验收']]){const o=el('option','',l);o.value=v;select.append(o);}choice.append(select);rf.append(choice);field(rf,'until','暂缓到哪天（仅暂缓时填写）','',false,'date');
        if(d.plan_id&&d.plan_id===plan?.id){const done=field(rf,'complete_plan','本次目标全部达到完成标准，同时完成本次工作','',false,'checkbox');done.value='yes';}
        formSubmit(rf,'保存验收决定',(data,p)=>mutate(brief,'review',{...data,complete_plan:data.complete_plan==='yes',delivery_id:d.id},p));review.append(rf);card.append(review);}deliveries.append(card);
    }
    if(active){const submit=details('补充成果（也可由 Agent 自动登记）');const f=el('form','wc-form');for(const [n,l]of [['title','成果名称'],['purpose','用途'],['paths','成果文件完整路径（每行一个）'],['changes','相对上一版有什么变化'],['verification','已经验证了什么'],['pending','仍需本人判断什么（没有请写“无”）']])field(f,n,l,'',true,n==='title'||n==='purpose'?'text':'textarea');
      const label=el('label','wc-field','替代哪一版（可选）'),select=el('select');select.name='replaces';select.append(el('option','',''));for(const d of cycle.deliveries){const o=el('option','',d.title);o.value=d.id;select.append(o);}label.append(select);f.append(label);
      formSubmit(f,'登记，等待本人验收',(data,p)=>mutate(brief,'delivery',{...data,paths:data.paths.split(/\r?\n/).map(x=>x.trim()).filter(Boolean),plan_id:plan?.status==='working'?plan.id:''},p));submit.append(f);deliveries.append(submit);}host.append(deliveries);
    const knowledge=details(`本次参考资料 · ${cycle.knowledge?.length||0} 条`);
    for(const source of cycle.knowledge||[]){const row=el('article','wc-delivery');row.append(el('strong','',source.title),el('p',source.valid?'wc-note':'wc-error',`${source.heading} · 第 ${source.line} 行 · ${source.valid?'版本未变':'原文变化，请重新检索'}`));if(active)row.append(button('从接续包移除',()=>mutate(brief,'knowledge',{source_ids:cycle.knowledge.filter(s=>s.id!==source.id).map(s=>s.id)},host.firstChild)));knowledge.append(row);}
    if(active){const searchHost=el('div');renderSearch(searchHost,brief);knowledge.append(searchHost);}host.append(knowledge);
    const sample=details('记录一次真实使用');const sf=el('form','wc-form');const phaseLabel=el('label','wc-field','记录阶段'),phase=el('select');phase.name='phase';for(const [v,l]of [['after','使用后'],['before','使用前基线']]){const o=el('option','',l);o.value=v;phase.append(o);}phaseLabel.append(phase);sf.append(phaseLabel);const minutes=field(sf,'minutes','从打开项目到能继续工作的分钟数','',true,'number');minutes.min='0';minutes.max='1440';minutes.step='0.1';const repeats=field(sf,'reexplains','重复解释背景的次数','0',true,'number');repeats.min='0';repeats.max='100';const wrong=field(sf,'wrong_version','这次误用了旧版本','',false,'checkbox');wrong.value='yes';formSubmit(sf,'保存实际记录',(data,p)=>mutate(brief,'sample',{...data,wrong_version:data.wrong_version==='yes'},p));sample.append(sf);host.append(sample);
  }
  function addFiles(card,d,brief){
    for(const f of d.files){const row=el('div','wc-file');row.append(el('span','',f.name));const output=status();row.append(button('打开成果',async()=>{try{await api({action:'open_artifact',project_key:brief.lifecycle.project_key,delivery_id:d.id,file_id:f.id});message(output,'已请求本机应用打开');}catch(e){message(output,e.message,true);}}),button('复制路径',async()=>{try{await navigator.clipboard.writeText(f.path);message(output,'已复制路径');}catch{message(output,'浏览器未允许复制，请从来源路径复制',true);}}),output);card.append(row);}
  }
  function renderSearch(host,brief){
    const heading=el('h3','','从历史知识中找依据');const form=el('form','wc-search-form');const q=field(form,'query','用工作问题检索','',true);q.placeholder='直接描述你想找的资料，例如：之前日期问错了是怎么修好的';q.maxLength=240;
    const scopeLabel=el('label','wc-field','检索范围'),scope=el('select');scope.name='source';scope.setAttribute('aria-label','检索范围');for(const [v,l]of [['all','全部三个知识库'],['formal','正式记忆与项目历史'],['job','岗位知识与历史'],['personal','个人知识与方法']]){const o=el('option','',l);o.value=v;scope.append(o);}scopeLabel.append(scope);const advanced=details('限定范围（可选）');const advancedFields=el('div','wc-advanced-fields');advancedFields.append(scopeLabel);advanced.append(advancedFields);form.append(advanced);
    const filter=field(advancedFields,'path_filter','来源路径含有（可选，用项目名或目录缩小范围）');filter.placeholder='例如：销售看板、2026-09、wiki/concepts';
    const results=el('div','wc-search-results'),info=status();
    formSubmit(form,'查找资料',async(data,p)=>{try{message(p,'正在检索…');const r=await api({action:'search',...data});results.replaceChildren();renderCoverage(r.coverage,info);message(p,`${r.matches.length} 条资料 · ${r.seconds} 秒 · ${r.retrieval?.method||'文字检索'}。${r.retrieval?.notice||''}`);
      if(!r.matches.length)results.append(el('p','wc-empty','未找到足够相关的资料。可以补充项目或事情的背景；也可检查知识索引是否已刷新。'));
      for(const hit of r.matches){const card=el('article','wc-search-hit');card.append(el('small','',`${hit.source_label} · 文件修改 ${formatDate(hit.modified)}`),el('h4','',hit.title),el('p','wc-note',`${hit.heading} · 第 ${hit.line} 行`),el('p','wc-excerpt',hit.excerpt),el('p','wc-note',hit.notice));const out=status();
        card.append(button('打开原文',async()=>{try{await api({action:'open_knowledge',source_id:hit.id});message(out,'已请求本机应用打开');}catch(e){message(out,e.message,true);}}),button('复制带来源的摘录',async()=>{try{await navigator.clipboard.writeText(`${hit.title}\n${hit.path}:${hit.line}\n${hit.excerpt}\n${hit.notice}`);message(out,'已复制');}catch(e){message(out,e.message,true);}}));
        if(brief)card.append(button('加入本次接续包',()=>mutate(brief,'knowledge',{source_ids:[...new Set([...(brief.work_cycle.knowledge||[]).map(s=>s.id),hit.id])]},out)));card.append(out);results.append(card);}
    }catch(e){message(p,e.message,true);}});
    const refreshStatus=status();host.append(heading,form,button('刷新知识索引',async()=>{try{message(refreshStatus,'正在增量检查三个知识库…');const r=await api({action:'refresh_knowledge'});renderCoverage(r.coverage,info);message(refreshStatus,`索引已刷新。${r.coverage.semantic_error||""}`);}catch(e){message(refreshStatus,e.message,true);}}),refreshStatus,info,results);
    if(!brief)host.append(el('p','wc-note','需要带入某个项目时，在项目详情的“本次参考资料”中检索并选择。'));
  }
  function renderCoverage(c,p){const sources=Object.values(c.sources||{}).map(s=>`${s.label} ${s.indexed||0} 篇${s.errors?`（${s.errors} 篇失败）`:''}`);message(p,`${sources.join(' · ')}。索引时间 ${c.indexed_at?formatDate(c.indexed_at,true):'未建立'}。${c.semantic?` 本地语义覆盖 ${c.semantic.passages||0} 个段落；${c.semantic.current?'与文字索引一致':'部分资料更新，需刷新语义索引'}。`:''}${c.boundary||''}`);}
  async function packet(brief){const result=await api({action:'packet',project_key:brief.lifecycle.project_key});return result.packet;}
  return {render:renderDaily,renderProject,packet};
})();
