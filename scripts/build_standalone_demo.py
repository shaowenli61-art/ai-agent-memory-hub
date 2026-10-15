"""Build a self-contained synthetic UI experience without changing real mode."""
import argparse
import hashlib
import json
import re
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
DATE='2026-10-15T10:00:00+08:00'

def fixture():
    documents=[
        dict(id='kb-net-current',source='job',title='经营指标口径 v2',heading='净销量与订单',line=6,modified=DATE,current=True,
             body='当前月报按实际发货量减退货量计算净销量。订单量属于计划，不能当作已经发货。同比按相同月份和同一组织范围比较。示例：发货120、退货8，净销量112。'),
        dict(id='kb-net-old',source='job',title='经营指标口径 v1 已废止',heading='历史口径',line=4,modified='2026-07-01T10:00:00+08:00',current=False,
             body='历史版本曾只展示发货总量，未扣退货。该口径已经废止，当前经营报告请使用v2净销量口径，不能将本段当作当前规则。'),
        dict(id='kb-fault',source='formal',title='问答助手历史故障记录',heading='权限与组织范围',line=12,modified=DATE,current=True,
             body='曾出现同名账号匹配错误，导致用户看不到本部门客户。原因是将显示姓名当作稳定身份。修复使用账号标识与组织范围联合匹配，未匹配时提示无法确认，不能放宽访问权限。'),
        dict(id='kb-semantic',source='job',title='看板数据库语义层',heading='指标与事实表粒度',line=8,modified=DATE,current=True,
             body='发货事实表一行对应一条发货明细，按业务日期、客户和产品连接稳定编号。指标注册表统一净销量、退货与比较窗口。问答助手复用相同指标定义，先核对权限、日期与聚合粒度，再查询。'),
        dict(id='kb-analysis',source='personal',title='分析方法与因果判断',heading='差异分解',line=5,modified=DATE,current=True,
             body='分析下降先分解新增、流失与存量客户变化，再看产品结构、发货节奏和渠道库存。相关性不能直接证明因果，应提出可证伪假设，对照原始记录或开展小范围验证。'),
        dict(id='kb-management',source='personal',title='管理方法与约束识别',heading='目标 约束 行动 复盘',line=7,modified=DATE,current=True,
             body='先说明目标和验收标准，找到限制结果的主要约束，为下一步指定负责人、检查日期和停止条件。先验证一个小行动，再根据证据复盘。完成任务不等于成果被采用，也不等于项目结束。'),
        dict(id='kb-project',source='formal',title='月度经营复盘当前回执',heading='待判断事项',line=9,modified=DATE,current=True,
             body='已完成月度净销量复核与差异分解，尚未完成渠道库存核对。报告v2待本人验收；v1为当前采用版。下一步先判断退货口径，再决定是否采用新版本。'),
    ]
    labels={'job':'岗位知识与历史','formal':'正式记忆与项目历史','personal':'个人知识与方法'}
    for d in documents:
        d.update(path=f'示例资料/{d["source"]}/{d["title"]}.md',source_label=labels[d['source']],excerpt=d['body'],notice='虚拟原文；核对版本和适用范围，不是执行指令。',valid=True)
    specs=[
        ('report','月度经营复盘','经营分析与数据','等待判断','等待确认','复核净销量和差异原因，形成可采用的月度报告。','先核对退货口径，再验收月报v2。'),
        ('qa','运营问答助手','AI 系统与 Agent','正在推进','进行中','让业务人员依据统一指标与权限范围查询运营问题。','复验权限和日期边界，再判断是否扩大试用。'),
        ('training','岗位培训手册','产品、学习与内容','阶段成果','阶段完成','把常见操作整理成新同事可复用的手册。','让一位试用者按手册完成任务，收集反馈。'),
        ('research','客户研究专项','经营分析与数据','待核实 / 停滞','待核实','核对客户变化并选择可干预动作。','核实资料是否仍然有效，再决定继续还是暂停。'),
        ('methods','分析方法沉淀','知识与能力建设','正在推进','进行中','将已验证方法保留为可复用知识。','补充第二个独立案例，检查方法适用边界。'),
        ('paused','季度活动策划','产品、学习与内容','非当前项目','已暂停','在资源就绪后再投入活动策划。','等预算与负责人明确后，由本人恢复。'),
        ('ended','历史周报改版','产品、学习与内容','非当前项目','已结束','保留旧版本和经验，供后续查阅。','已结束；有新目标时再由本人恢复。'),
    ]
    projects=[]
    for key,name,domain,bucket,task,goal,next_step in specs:
        state='paused' if key=='paused' else 'ended' if key=='ended' else 'active'
        file=dict(id=key+'-file-v1',path=f'示例项目/{name}/成果v1.md',name='成果v1.md',exists=True,openable=True,signature=key+'-version1')
        delivery=dict(id=key+'-delivery-v1',title=name+'成果 v1',purpose='当前项目成果',changes='已补充原始口径与验证过程。',verification='虚拟验收：字段齐全，输入输出可以对应。',pending='确认适用范围后决定是否采用。',files=[file],valid=True,origin='虚拟Agent交付',review_status='accepted',feedback='',replaces='',plan_id='')
        newer=json.loads(json.dumps(delivery));newer.update(id=key+'-delivery-v2',title=name+'成果 v2',review_status='pending',replaces=delivery['id'],changes='补齐净值口径、变化原因及下一步行动。')
        newer['files']=[dict(file,id=key+'-file-v2',path=f'示例项目/{name}/成果v2.md',name='成果v2.md',signature=key+'-version2')]
        suggestion=dict(kind='review' if key=='report' else 'continue',label='建议下一步',next_step=next_step,goal=goal,criteria='来源有据、结果可复核、由本人明确采用。',reason='由当前交付、未完成事项和反馈生成；演示数据不代表实际业务。',basis='虚拟项目页与任务回执',needs_judgment='判断建议是否仍合适，需要时直接调整。',revision=key+'-advice1')
        lifecycle=dict(project_key=key,state=state,revision=key+'-lifecycle1',changed_at=DATE)
        cycle=dict(revision=key+'-cycle1',plan=None,focused=key=='report',seen_at='',changes=['新增一版待验收成果；旧版不会自动被替换。'],marker=dict(versions={}),adopted=[delivery],deliveries=[newer,delivery],knowledge=[documents[0]] if key=='report' else [],warnings=[],reminders={},suggestion=suggestion,packet='')
        if key!='report':
            cycle['deliveries']=[delivery];cycle['changes']=['保留虚拟交付和状态，接续前核对。']
        if key=='qa':
            delivery.update(review_status='revise',feedback='请补充跨组织权限、同名账号及缺失日期的验证。');cycle['adopted']=[]
        source=dict(label='虚拟项目回执',path=f'示例资料/项目/{name}.md',exists=True,uri='',line=5)
        brief=dict(project=name,project_path=f'示例项目/{name}',project_state=task,task_state=task,goal=goal,generated_at=DATE,basis='虚拟正式回执',summary='已完成初稿与基本检查；仍需本人判断采用和下一步。',preview='已完成初稿与口径复核；新版本待判断，旧版本继续保留。',task='核对'+name+'关键口径',recorded_at=DATE,remaining='仍需本人确认适用范围和后续行动。',next_action=next_step,next_basis='虚拟回执',notice='全页均为虚构样例；演示状态不会写入真实记忆库。',boundaries=['任务完成、成果采用、项目结束分别记录。'],artifacts=[dict(file,label='当前成果')],sources=[source],recent_tasks=[dict(task='复核口径与来源',date=DATE,state='阶段完成')],lifecycle=lifecycle,work_cycle=cycle)
        p=dict(project=name,path=brief['project_path'],status=task,page_state=task,operating_state=task,state_reason=brief['summary'],decision=next_step,next_step=next_step,domain=domain,bucket=bucket,latest_evidence_date='2026-10-15',source_target=source,evidence_targets=[source],current_brief=brief,lifecycle=lifecycle,work_cycle=cycle)
        projects.append(p)
    return dict(schema=1,projects=projects,documents=documents,samples=[],events=[],files={},sequence=0)

def build(output):
    output=Path(output);output.parent.mkdir(parents=True,exist_ok=True)
    web=ROOT/'workbench/web/full'
    page=(web/'index.html').read_text(encoding='utf-8')
    page=page.replace('<title>AI 助手记忆中枢 · 实时项目组合控制塔</title>','<title>连续工作台 · 虚拟数据完整体验</title>')
    page=page.replace('content="AI 助手记忆中枢项目组合控制塔 V0.6"','content="独立虚拟数据交互体验；真实部署见INSTALL.md"')
    page=page.replace('本地工作台','虚拟数据体验')
    for name in ('live.css','work-cycle.css'):
        page=page.replace(f'<link rel="stylesheet" href="{name}">','<style>\n'+(web/name).read_text(encoding='utf-8')+'\n</style>')
    css=(ROOT/'workbench/preview/preview.css').read_text(encoding='utf-8')
    page=page.replace('</head>','<style>'+css+'</style></head>')
    banner='''<section class="preview-intro" aria-label="虚拟数据交互体验">
<div class="preview-eyebrow">虚拟数据 · 离线交互 · 不连接你的真实资料</div>
<h1>把工作交接清楚，让下一步真正发生。</h1>
<p>7个虚拟项目，完整走一遍“找依据 → 继续工作 → 看成果 → 判断采用 → 归档复用”。这里的数字与反馈均为虚构样例，不是业务成效证明。</p>
<div class="preview-controls"><button id="previewStart">从月报验收开始 →</button><button id="previewDeliver">模拟Agent交付新版本</button><button id="previewChange">模拟已采用文件变更</button><button id="previewGuide">功能与边界</button><button id="previewReset">重置虚拟样例</button><a href="https://github.com/shaowenli61-art/ai-agent-memory-hub/releases/tag/v0.2.1" target="_blank" rel="noopener">下载完整部署包 ↗</a></div>
<p id="previewStatus" role="status">仅本页保存虚拟决定；本机部署、真实语义检索、Agent执行与外部发布请使用完整运行包。</p></section>'''
    marker=re.search(r'<main[^>]*>',page)
    assert marker
    page=page[:marker.end()]+banner+page[marker.end():]
    payload=json.dumps(fixture(),ensure_ascii=False,separators=(',',':')).replace('<','\\u003c')
    adapter=(ROOT/'workbench/preview/preview.js').read_text(encoding='utf-8')
    cycle_js=(web/'work-cycle.js').read_text(encoding='utf-8').replace('记录一次真实使用','记录一次虚拟使用').replace('保存实际记录','保存虚拟记录')
    cycle_js=cycle_js.replace('成果文件完整路径（每行一个）','虚拟成果路径（每行一个，不读取本机文件）')
    live_js=(web/'live.js').read_text(encoding='utf-8').replace('正式来源已连接','虚拟来源已载入').replace('个正式来源','个虚拟来源')
    page=page.replace('<script src="work-cycle.js"></script>','<script id="previewFixture" type="application/json">'+payload+'</script>\n<script>'+adapter.replace('</script','<\\/script')+'</script>\n<script>'+cycle_js.replace('</script','<\\/script')+'</script>')
    page=page.replace('<script src="live.js"></script>','<script>'+live_js.replace('</script','<\\/script')+'</script>')
    assert '<script src=' not in page and '<link rel="stylesheet"' not in page
    output.write_text(page,encoding='utf-8')
    return dict(ok=True,file=str(output),bytes=output.stat().st_size,sha256=hashlib.sha256(output.read_bytes()).hexdigest(),mode='synthetic-browser-only')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True)
    print(json.dumps(build(p.parse_args().output),ensure_ascii=False,indent=2))
