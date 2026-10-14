"""Evidence spans and explicit version relations; no business-topic dictionary."""
from __future__ import annotations
import re
from pathlib import Path
from functools import lru_cache

DEFINITION_HEADINGS={'定义','核心要点','当前事实入口','关键口径与规则','已确认边界','数据边界'}
REFERENCE_HEADINGS={'来源引用','相关概念','参考资料','来源','收工回执索引','项目导航'}
PATH=re.compile(r'(?:[A-Z]:[\\/][^\s;；|`]+|https?://[^\s|`]+|(?:/opt/|/home/)[^\s;；|`]+)',re.I)
META_FIELD=re.compile(r'^\s*[-*>\s]*\*{0,2}(?:关键文件|修改文件|证据路径|更新时间与 Agent|收工回执|成长复盘\S*|方法论候选|来源任务|提取 Agent)\*{0,2}[：:]')

def _lines(body):
    offset=0;frontmatter=bool(re.match(r'^\s*---\r?\n',body));inside=frontmatter;opened=False
    for index,line in enumerate(body.splitlines(keepends=True)):
        text=line.strip();meta=bool(META_FIELD.match(text))
        if inside:
            meta=True
            if text=='---':
                if opened:inside=False
                else:opened=True
        if text.startswith('#'):meta=True
        if re.search(r'\|\s*`?MC-\d',text):meta=True
        clean=PATH.sub('',text)
        meaningful=re.sub(r'[\W_\d]+','',clean)
        ratio=(len(text)-len(clean))/max(1,len(text))
        explanation=bool(re.search(r'根因|原因是|因为|导致|造成|不得|不能|禁止',clean)) and len(meaningful)>=20
        yield offset,offset+len(line),text,meta or (ratio>.4 and len(meaningful)<40 and not explanation),meaningful
        offset+=len(line)


@lru_cache(maxsize=4096)
def line_records(body):
    # Content-keyed records remain valid when files or the index are refreshed.
    return tuple(_lines(body))


def lines(body):
    return iter(line_records(body))

def content_quality(text):
    rows=list(lines(text));total=sum(len(r[2]) for r in rows)
    useful=sum(len(r[4]) for r in rows if not r[3])
    return useful/max(1,total)

def has_explanation(text):
    return any(not r[3] and len(r[4])>=8 for r in lines(text))

def intent_fit(query,text):
    """Match the form of evidence to the question, independent of its topic."""
    decision=bool(re.search(r'能不能|能否|是否|是不是|行不行|可不可以|(?:能|可以|应该|算|就是).{0,60}吗|哪些.{0,8}(?:还|要)',query))
    repair=bool(re.search(r'(?:怎么|怎样|如何).{0,10}(?:修复|修正|处理|解决)|(?:修复|修正).{0,5}的',query))
    cause=bool(re.search(r'为什么|怎么会|原因|为何',query))
    clean='\n'.join(r[2] for r in lines(text) if not r[3])
    boundary=bool(re.search(r'不得|不能|禁止|不应|不支持|不等于|必须|只能|尚未完成|未验收',clean))
    causal=bool(re.search(r'根因|原因|因为|由于|导致|造成|引起',clean))
    action=bool(re.search(r'修复|修正|澄清|规范化|校验|排查|改为|改成|替换|回滚|重启|补充.{0,12}(?:测试|规则|检查)',clean))
    return (int(decision and boundary)+int(cause and causal)+int(repair and action))/max(1,int(decision)+int(cause)+int(repair))

def table_cards(rows):
    """Give each mapping row its own representation, labelled by original headers."""
    scope=None;header=None;previous=None
    for row in sorted(rows,key=lambda r:(r[1],r[4])):
        pid,path,title,heading,line,body,*_=row
        if scope!=(path,heading):scope=(path,heading);header=None;previous=None
        if re.search(r'原文转写|逐字稿',title+' '+heading):continue
        for a,b,text,meta,meaningful in lines(body):
            if not text:continue
            if not text.startswith('|'):
                header=None;previous=None;continue
            cells=[x.strip() for x in text.strip('|').split('|')]
            if all(re.fullmatch(r':?-{2,}:?',x.replace(' ','')) for x in cells):
                header=previous if previous and any(re.search(r'问题|场景|类型|症状',x) for x in previous) and any(re.search(r'模型|方法|措施|做法|策略|处理|结论',x) for x in previous) else None
                continue
            if header and len(cells)==len(header):
                labelled='\n'.join(f'{key}：{value}' for key,value in zip(header,cells) if value and value!='---')
                yield dict(id=pid,offset=a,end=b,text=f'{title}\n{heading}\n{labelled}',kind='mapping')
            previous=cells

def definition_cards(rows):
    for row in rows:
        pid,path,title,heading,line,body,*_=row
        if heading.lstrip('一二三四五六七八九十、. 0123456789') not in DEFINITION_HEADINGS:continue
        kept=[r for r in lines(body) if not r[3] and len(r[4])>=8]
        if not kept:continue
        start,end=kept[0][0],min(len(body),kept[0][0]+440)
        text='\n'.join(r[2] for r in kept if r[0]<end)
        if len(text)<25:continue
        yield dict(id=pid,offset=start,end=end,text=f'{title}\n{heading}\n{text}',kind='definition')
        # A core section can describe many unrelated concepts. Preserve each
        # meaningful original bullet as an independent candidate, not keywords.
        for a,b,line,meta,meaningful in kept:
            if line.lstrip().startswith(('- ','* ','▪','①','②','③')) and len(meaningful)>=18 and b-a<=400:
                yield dict(id=pid,offset=a,end=b,text=f'{title}\n{heading}\n{line}',kind='definition')


def complete_span(row,start,end):
    """Display neighbouring original reasoning, without synthesizing answers."""
    body=row[5];records=line_records(body);cap=1200
    first=next((a for a,b,t,meta,m in records if re.match(r'^\s*-\s*\*\*本次完成\*\*[：:]',t)),None) if row[3].startswith('任务收工：') else None
    useful_end=len(body)
    for a,b,text,meta,meaningful in records:
        if a>= (first if first is not None else end) and META_FIELD.match(text):useful_end=a;break
    if useful_end<=start:return start,end
    # Receipts put actions first and limitations later. A short complete receipt
    # body is more useful than one isolated "completed" or "do not" field.
    if row[3].startswith('任务收工：'):
        if first is not None and first<=start and useful_end-first<=cap:return first,useful_end
    # Keep the nearby section preamble and complete the last paragraph. Long
    # sections stay bounded; headings outside this passage are never borrowed.
    first=0 if start<=400 else max(0,start-240)
    first=max((a for a,b,t,meta,m in records if a<=first),default=0)
    last=min(useful_end,first+cap)
    if last<useful_end:
        paragraph=body.rfind('\n\n',max(end,first),last)
        if paragraph>=end:last=paragraph
    if last<end:return start,end
    return first,last

def evidence_cards(rows):
    """Index individual explanatory claims with their source section context.

    This is a disposable retrieval view, never a generated answer. Offsets refer
    to the unchanged source; reference paths cannot replace the explanation.
    """
    yield from definition_cards(rows)
    yield from table_cards(rows)
    section=re.compile(r'定义|核心要点|规则|约束|边界|禁止|根因|原因分析')
    claim=re.compile(r'因为|由于|导致|根因|原因是|不得|不能|禁止|不应|不支持|不等于|必须|只能')
    for row in rows:
        pid,path,title,heading,line,body,*_=row
        if heading in REFERENCE_HEADINGS:continue
        # Raw transcripts already have complete body vectors. Their conversational
        # "can't"/"because" remarks are not structured explanations or policies.
        if re.search(r'原文转写|逐字稿',title):continue
        for a,b,text,meta,meaningful in lines(body):
            if meta or len(meaningful)<16:continue
            if not (section.search(heading) or claim.search(text)):continue
            # Sentence chunks keep a long historical entry's cause visible even
            # when its beginning is an unrelated result and its end is paths.
            boundaries=[a]+[a+m.end() for m in re.finditer(r'[。；]\s*',body[a:b])]+[b]
            chunks=[];start=boundaries[0]
            for end in boundaries[1:]:
                if end-start>=120 or end==b:
                    chunks.append((start,end));start=end
            for start,end in chunks:
                for x in range(start,end,320):
                    y=min(end,x+400);raw=body[x:y];clean=PATH.sub('',raw).strip()
                    if len(re.sub(r'[\W_\d]+','',clean))<16:continue
                    if not section.search(heading) and not claim.search(clean):continue
                    yield dict(id=pid,offset=x,end=y,text=f'{title}\n{heading}\n{clean}',kind='claim')

def choose_span(row,query,words,semantic=None,definition=None):
    """Only contiguous original text; offsets remain verifiable against source."""
    body=row[5];candidates={0};line_rows=list(lines(body))
    candidates.update(r[0] for r in line_rows if not r[3] and len(r[4])>=8)
    candidates.update(m.end() for m in re.finditer(r'[。；]\s*',body))
    starts=[r[0] for r in line_rows]
    aligned={}
    for hit in (semantic,definition):
        if hit:
            aligned[hit['offset']]=hit['offset'] if hit is definition else max((x for x in starts if x<=hit['offset']),default=0)
            candidates.add(aligned[hit['offset']])
    decision=bool(re.search(r'能不能|能否|是否|是不是|行不行|(?:能|可以|应该|算|就是).{0,60}吗|哪些.{0,8}(?:还|要)|还.{0,8}(?:检查|回听|验证)',query))
    scored=[]
    for start in candidates:
        end=min(len(body),start+(700 if decision else 480));fragment=body[start:end]
        explained=0
        for a,b,text,meta,meaningful in line_rows:
            if a<start:continue
            if a>=end:break
            if explained>=25 and META_FIELD.match(text):
                end=a;fragment=body[start:end];break
            if not meta:explained+=len(meaningful)
        useful='\n'.join(r[2] for r in lines(fragment) if not r[3])
        coverage=sum(weight for word,weight in words.items() if word in useful.casefold())
        quality=content_quality(fragment)
        semantic_bonus=3 if semantic and start==aligned[semantic['offset']] else 0
        definition_bonus=6 if definition and start==aligned[definition['offset']] else 0
        boundary_bonus=6*intent_fit(query,useful)
        scored.append((coverage+quality*8+semantic_bonus*quality+definition_bonus*quality+boundary_bonus,start,end))
    _,start,end=max(scored,key=lambda x:(x[0],-x[1]))
    return start,end,content_quality(body[start:end])

def subject_words(title):
    # Character bigrams allow project identity checks without topic synonyms.
    return {title[i:i+2] for i in range(len(title)-1) if re.fullmatch(r'[\u4e00-\u9fff]{2}',title[i:i+2])}

def version_rules(rows):
    """Only explicit replacement metadata or quoted retired formulations."""
    names={}
    contexts={}
    normative=set()
    for row in rows:
        names.setdefault(Path(row[1]).stem.casefold(),set()).add(row[1])
        contexts.setdefault((row[1],row[3]),[]).append(row[5])
        if row[3].lstrip('一二三四五六七八九十、. 0123456789') in {'当前事实入口','关键口径与规则'} or ('适用范围' in row[5] and '核心结论' in row[5]):
            normative.add(row[1])
    rules=[]
    for row in rows:
        pid,path,title,heading,line,body,*_=row
        own=subject_words(title+' '+heading)
        # Do not infer authority from file modification time.
        for match in re.finditer(r'(?m)^supersededBy:\s*(.+)$',body):
            value=match[1].strip(' \"\'[]')
            if value.casefold() in {'null','none','~',''}:continue
            targets=names.get(Path(value).stem.casefold(),set())
            if len(targets)==1:
                rules.append(dict(target=path,authority=next(iter(targets)),phrase='',scope=own,id=pid,line=line+body[:match.start()].count('\n'),basis_path=path,explicit=True))
        for match in re.finditer(r'(?m)^supersedes:\s*(\[[^\n]*\]|\n(?:[ \t]+-[^\n]*\n?)+)',body):
            values=re.findall(r'[\"\']([^\"\']+)[\"\']',match[1]) if match[1].startswith('[') else [v.strip(' \"\'') for v in re.findall(r'(?m)^\s*-\s*(.+)$',match[1])]
            for value in values:
                targets=names.get(Path(value).stem.casefold(),set())
                if len(targets)==1:
                    rules.append(dict(target=next(iter(targets)),authority=path,phrase='',scope=own,id=pid,line=line+body[:match.start()].count('\n'),basis_path=path,explicit=True))
        for offset,_,text,meta,_ in lines(body):
            if meta or not re.search(r'旧|历史',text) or not re.search(r'废止|不引用|旧表述|最新标准|为准',text):continue
            quotes=list(re.finditer(r'[“「](.+?)[”」]',text))
            for quote in quotes:
                phrase=quote[1];before=text[max(0,quote.start()-40):quote.start()];after=text[quote.end():quote.end()+40]
                old_prefix=bool(re.search(r'旧|历史',before)) and not re.search(r'最新|当前|改为|改成|统一为|新的|新版',before)
                old_suffix=bool(re.match(r'\s*(?:的旧(?:表述|说法)|(?:已经?|已)?废止|不再适用|已失效|被.{0,8}替代)',after))
                if not (old_prefix or old_suffix):continue
                if len(phrase)<3:continue
                # A combined formulation must stay combined. A comma-separated
                # pair can be retired without either component being invalid.
                for part in re.split(r'/',phrase):
                    part=part.strip()
                    if len(part)<3:continue
                    authority=path
                    if heading.startswith('任务收工：') or re.match(r'\d{4}-\d{2}-\d{2}-worklog$',title) or '**任务目标**' in body:
                        context='\n'.join(contexts[path,heading]).casefold()
                        exact=[p for paths in names.values() for p in paths if p!=path and p.casefold() in context]
                        linked=exact or [next(iter(paths)) for name,paths in names.items() if len(paths)==1 and (name+'.md' in context or '[['+name in context) and len(subject_words(name)&own)>=3]
                        if len(linked)>1:
                            declared=[p for p in linked if p in normative and len(subject_words(Path(p).stem)&own)>=3]
                            if len(declared)==1:linked=declared
                        if len(linked)==1:authority=linked[0]
                    rules.append(dict(target='',authority=authority,phrase=part,scope=own,id=pid,line=line+body[:offset].count('\n'),basis_path=path,explicit=False))
    return rules

def retired_by(row,rules):
    pid,path,title,heading,line,body,*_=row
    result=[];own=subject_words(title)
    for rule in rules:
        if path==rule['authority']:continue
        if rule['explicit']:
            if path==rule['target']:result.append(rule)
            continue
        if len(own & rule['scope'])<3 or rule['phrase'] not in heading+'\n'+body:continue
        # A quotation of an old rule with a correction is not an endorsement.
        if re.search(r'废止|不引用|旧表述|最新标准|以.{0,30}为准',body):continue
        result.append(rule)
    return result
