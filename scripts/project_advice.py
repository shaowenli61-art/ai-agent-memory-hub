"""Evidence-grounded next actions; reading never creates a commitment."""
from datetime import datetime
import hashlib
import json


def propose(project, cycle, now):
    brief=project.get('current_brief',{})
    result=dict(kind='next',label='建议下一步',next_step=brief.get('next_action') or '先核对项目当前目标与最近成果，再继续。',
        goal=brief.get('goal') or project.get('project','继续当前项目'),criteria='完成此动作，附验证结果、剩余问题和可定位证据。',
        boundary='；'.join(brief.get('boundaries',[])),dependency='',due='',priority='normal',
        reason='根据最近记录中的下一步生成；尚未形成新的承诺。',basis=brief.get('next_basis') or brief.get('basis','证据缺口'),
        sources=brief.get('sources',[]),generated_at=now.isoformat(timespec='seconds'),needs_judgment='判断这是否仍是当前最有价值的一步；可直接调整。')
    state=project.get('lifecycle',{}).get('state','active');plan=cycle.get('plan')
    invalid=[d for d in cycle.get('adopted',[]) if not d['valid']]
    feedback=cycle.get('feedback',[])
    pending=[d for d in cycle.get('deliveries',[]) if d['review_status']=='pending']
    def newer(a,b):
        try:return datetime.fromisoformat(a.replace('Z','+00:00'))>datetime.fromisoformat(b.replace('Z','+00:00'))
        except (ValueError,TypeError,AttributeError):return False
    working=bool(plan and plan['status']=='working')
    if state!='active':
        result.update(kind='inactive',label='已暂停' if state=='paused' else '已结束',next_step='保留历史记录。需要再次投入时，由你恢复跟进。',
            criteria='',reason='遵循本人已确定的项目生命周期。',needs_judgment='是否恢复项目，由你决定。',basis='项目生命周期决定')
    elif invalid:
        result.update(kind='version',next_step='核对当前文件与已采用版本的差异，登记变更并重新确认：'+invalid[0]['title'],
            criteria='明确可采用的文件及版本；旧版变化原因可追溯。',reason='已采用的文件发生变化或丢失，直接使用容易用错版本。',priority='high')
    elif feedback:
        result.update(kind='revise',next_step='先处理已提出的修改意见：'+feedback[0]['feedback'],
            criteria='说明如何响应修改意见，并提供验证结果与新版本。',reason='本人已明确反馈，应优先于开启新的工作。',basis='本人修改意见',priority='high')
    elif pending and (not working or newer(pending[0]['submitted_at'],plan['created_at'])):
        d=pending[0]
        result.update(kind='decision',label='需要你判断',next_step='查看最新成果并决定采用或修改：'+d['title'],
            criteria='留下采用、修改或暂缓的明确判断。',reason=d.get('pending') or '已有新成果，下一步取决于本人判断。',basis='新成果及其验证记录',needs_judgment=d.get('pending') or '是否采用这一版成果。')
    elif working:
        result.update({k:plan.get(k,'') for k in ('goal','next_step','criteria','boundary','dependency','due','priority')})
        result.update(kind='adjusted',reason='沿用你已确认或调整的下一步；有新证据时再判断。',basis='本人调整',needs_judgment='判断是否需要根据新变化调整。')
    elif brief.get('task_state') in ('受阻','blocked','等待外部输入'):
        result.update(kind='blocked',criteria='阻塞解除有证据；未解除时不重复执行同一失败步骤。',dependency=brief.get('remaining',''),reason='最近正式记录仍有阻塞。',priority='high')
    elif brief.get('task_state') in ('等待用户确认','waiting_user') and '正式回执' in brief.get('basis',''):
        result.update(kind='decision',label='需要你判断',criteria='对原记录中待确认事项作出判断。',reason='最新正式成果的后续取决于你的判断。',needs_judgment=brief.get('remaining') or '是否继续当前方向。')
    else:
        recorded=brief.get('recorded_at','')
        try: stale=bool(recorded) and (now-datetime.fromisoformat(recorded.replace('Z','+00:00'))).days>21
        except (ValueError,TypeError): stale=False
        if brief.get('activity'):
            result.update(kind='verify',next_step='先核对最近会话相对正式记录的新变化，再继续：'+result['next_step'],
                reason='发现比正式回执更新的会话线索，尚未确认实际完成状态。',criteria='确认会话线索的真实成果及边界，再执行可验证的一步。')
        elif stale:
            result.update(kind='verify',next_step='先核对最近记录之后是否有变化，再继续：'+result['next_step'],
                reason='正式记录超过21天，无法仅靠旧下一步判断现在应做什么。',criteria='确认当前状态与旧记录仍一致；有变化则调整下一步。')
        elif not brief.get('receipt_id'):
            result.update(kind='verify',reason='尚无可归属的正式成果回执，先核对现状更可靠。',criteria='找到当前成果、阻塞及验证证据，再明确下一步。')
    result['revision']=hashlib.sha256(json.dumps({k:v for k,v in result.items() if k!='generated_at'},ensure_ascii=False,sort_keys=True).encode()).hexdigest()[:24]
    return result
