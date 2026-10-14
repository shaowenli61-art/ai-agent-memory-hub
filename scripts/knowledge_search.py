"""Local cross-vault retrieval. Sources are read only; the index is disposable.

Character bigrams and an optional offline semantic model provide independent
recall. Results are evidence excerpts, never current-decision claims.
"""
from __future__ import annotations
import argparse
import codecs
import hashlib
import json
import os
import re
import sqlite3
import time
import math
import io
from contextlib import redirect_stdout
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from functools import lru_cache
try:
    from scripts import knowledge_evidence as evidence
except ImportError:
    import knowledge_evidence as evidence

SOURCES = {'formal': ('正式记忆', 'memory_hub_root'), 'job': ('岗位知识与历史', 'job_vault_root'), 'personal': ('个人知识', 'personal_vault_root')}
EXCLUDED = {'.git', '.obsidian', '.trash', 'node_modules', '__pycache__', '90-Logs', 'write-snapshots', '.venv'}
STOP = ('请帮我', '帮我', '我想', '需要了解', '有没有', '为什么', '怎么样', '如何', '什么', '有哪些', '中的', '的', '了', '这个', '一个', '进行', '关于', '以及', '时候', '需要', '之前', '相关')

def concepts(query):
    try:
        import jieba
        jieba.setLogLevel(40)
        words=jieba.lcut(query.casefold())
    except ImportError:
        words=tokens(query,True)
    stop=set(STOP)|{'怎样','以前','历史','助手','了解','查找','找到','选择','处理','做','时','中','历史上','知道','怎么','要说','每次','叫什么','自己','帮它','同时','一直','之后','以后','这些','本来','我不'}
    # Dictionary segmenters can split an unknown two-character domain noun into
    # two single characters. Retain adjacent pairs instead of losing that noun.
    singles=[];preserved=[]
    for word in [*words,' ']:
        if len(word)==1 and re.fullmatch(r'[\u4e00-\u9fff]',word) and word not in stop:
            singles.append(word)
        else:
            preserved.extend(''.join(singles[i:i+2]) for i in range(len(singles)-1))
            singles=[]
    words.extend(preserved)
    return list(dict.fromkeys(w for w in words if len(w)>1 and w.strip() and w not in stop and re.search(r'[\w\u4e00-\u9fff]',w)))

def tokens(text, query=False):
    text = text.casefold()
    if query:
        for word in STOP:
            text = text.replace(word, ' ')
    result=[]
    for run in re.findall(r'[\u4e00-\u9fff]+|[a-z0-9_]+', text):
        if re.fullmatch(r'[\u4e00-\u9fff]+', run):
            result.extend(run[i:i+2] for i in range(max(1,len(run)-1)))
        else:
            result.append(run)
    return list(dict.fromkeys(result))

def database(config):
    return Path(config.get('knowledge_index') or Path(config['snapshot_output']).parent / 'knowledge-index.sqlite3')

def connect(config):
    db=database(config); db.parent.mkdir(parents=True, exist_ok=True)
    c=sqlite3.connect(db,timeout=30)
    c.execute('PRAGMA journal_mode=WAL')
    c.executescript('''CREATE TABLE IF NOT EXISTS documents(path TEXT PRIMARY KEY, source TEXT, relative TEXT, signature TEXT, hash TEXT, modified TEXT);
    CREATE TABLE IF NOT EXISTS passages(id TEXT PRIMARY KEY, path TEXT, title TEXT, heading TEXT, line INTEGER, body TEXT);
    CREATE INDEX IF NOT EXISTS passages_path_heading_line ON passages(path,heading,line);
    CREATE VIRTUAL TABLE IF NOT EXISTS passages_fts USING fts5(id UNINDEXED, title, heading, body, tokenize='unicode61');
    CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY, value TEXT);
    CREATE VIRTUAL TABLE IF NOT EXISTS term_stats USING fts5vocab(passages_fts, 'row');''')
    return c

def read(path):
    raw=path.read_bytes()
    return (raw.decode('utf-16') if raw.startswith((codecs.BOM_UTF16_LE,codecs.BOM_UTF16_BE)) else raw.decode('utf-8-sig')), hashlib.sha256(raw).hexdigest()

def passages(text):
    heading=''; start=1; buf=[]; size=0
    for no,line in enumerate(text.splitlines(),1):
        is_heading=bool(re.match(r'^#{1,6}\s',line))
        if buf and (is_heading or size+len(line)>1600):
            yield heading,start,'\n'.join(buf)
            buf=[];size=0;start=no
        if is_heading: heading=line.lstrip('# ').strip()
        if not buf: start=no
        buf.append(line);size+=len(line)+1
    if buf: yield heading,start,'\n'.join(buf)

def refresh(config,force=False):
    started=time.perf_counter(); coverage={}; errors=[]; total_updated=0
    with closing(connect(config)) as c, c:
        existing={r[0]:r[1] for r in c.execute('SELECT path,signature FROM documents')}
        current=set()
        for source,(label,key) in SOURCES.items():
            root=Path(config.get(key) or '__missing__')
            info=dict(label=label,available=root.is_dir(),markdown=0,indexed=0,updated=0,reused=0,excluded=0,unsupported=0,errors=0)
            coverage[source]=info
            if not root.is_dir(): continue
            for folder,dirs,files in os.walk(root):
                dirs[:]=[d for d in dirs if d not in EXCLUDED and not d.startswith('.worktrees')]
                for name in files:
                    path=Path(folder)/name
                    if path.suffix.casefold()!='.md':
                        info['unsupported']+=1;continue
                    info['markdown']+=1
                    if name.endswith(('-ai-activity.md','-draft-worklog.md')) or re.search(r'(?i)(\.backup[-.]|\.bak\.)',name):
                        info['excluded']+=1;continue
                    raw_path=str(path.resolve());current.add(raw_path)
                    try:
                        if not path.resolve().is_relative_to(root.resolve()):
                            raise ValueError('链接超出配置知识库')
                        stat=path.stat(); signature=f'{stat.st_size}:{stat.st_mtime_ns}'
                        if not force and existing.get(raw_path)==signature:
                            info['reused']+=1;info['indexed']+=1;continue
                        if stat.st_size>8*1024*1024:
                            raise ValueError('Markdown 超过 8 MiB，未索引')
                        text,sha=read(path)
                        old_ids=[r[0] for r in c.execute('SELECT id FROM passages WHERE path=?',(raw_path,))]
                        c.executemany('DELETE FROM passages_fts WHERE id=?',((i,) for i in old_ids))
                        c.execute('DELETE FROM passages WHERE path=?',(raw_path,))
                        for heading,line,body in passages(text):
                            if not body.strip(): continue
                            pid=hashlib.sha256(f'{raw_path}:{sha}:{line}'.encode()).hexdigest()[:32]
                            c.execute('INSERT INTO passages VALUES (?,?,?,?,?,?)',(pid,raw_path,path.stem,heading,line,body))
                            c.execute('INSERT INTO passages_fts VALUES (?,?,?,?)',(pid,' '.join(tokens(path.stem)),' '.join(tokens(heading)),' '.join(tokens(body))))
                        c.execute('INSERT OR REPLACE INTO documents VALUES (?,?,?,?,?,?)',(raw_path,source,str(path.relative_to(root)),signature,sha,datetime.fromtimestamp(stat.st_mtime,timezone.utc).isoformat()))
                        info['updated']+=1;info['indexed']+=1;total_updated+=1
                    except (OSError,UnicodeError,ValueError) as error:
                        info['errors']+=1;errors.append(dict(path=str(path),error=str(error)))
                        # A now unreadable source must not keep returning stale indexed text.
                        current.discard(raw_path)
        removed=set(existing)-current
        for path in removed:
            c.execute('DELETE FROM passages_fts WHERE id IN (SELECT id FROM passages WHERE path=?)',(path,))
            c.execute('DELETE FROM passages WHERE path=?',(path,));c.execute('DELETE FROM documents WHERE path=?',(path,))
        report=dict(indexed_at=datetime.now(timezone.utc).isoformat(),sources=coverage,errors=errors,removed=len(removed),updated=total_updated,seconds=round(time.perf_counter()-started,3),
            boundary='仅 Markdown；附件原文、聊天原始记录及运行日志未检索。来源日期是文件修改时间，不代表业务有效期。')
        c.execute('INSERT OR REPLACE INTO metadata VALUES (?,?)',('coverage',json.dumps(report,ensure_ascii=False)))
    return report

def coverage(config):
    with closing(connect(config)) as c:
        row=c.execute('SELECT value FROM metadata WHERE key=?',('coverage',)).fetchone()
        result=json.loads(row[0]) if row else dict(sources={},boundary='尚未建立本地知识索引')
        if config.get('semantic_model_path'):
            item=c.execute('SELECT value FROM metadata WHERE key="semantic"').fetchone()
            semantic=json.loads(item[0]) if item else dict(ok=False,passages=0)
            revision=hashlib.sha256(''.join(r[0] for r in c.execute('SELECT id FROM passages ORDER BY id')).encode()).hexdigest()
            semantic['current']=semantic.get('text_revision')==revision
            result['semantic']=semantic
        return result


def refresh_all(config,force=False):
    result=refresh(config,force)
    if config.get('semantic_model_path'):
        try:
            try:
                from scripts import semantic_search
            except ImportError:
                import semantic_search
            # Encoder progress belongs in diagnostics, not the JSON CLI result.
            if semantic_search.building(config) and not coverage(config).get('semantic',{}).get('current'):
                result['semantic_error']='语义索引正在构建，完成后查询自动使用新索引；未重复启动构建。'
            else:
                with redirect_stdout(io.StringIO()):
                    semantic_search.build(config)
                    semantic_search.build_definitions(config)
        except Exception:
            result['semantic_error']='文字索引已刷新，语义索引刷新失败；查询会保留可用的文字召回。'
    return coverage(config)|dict(seconds=result['seconds'],semantic_error=result.get('semantic_error',''))

def excerpt(body,terms):
    positions=[body.casefold().find(t) for t in terms if t in body.casefold()]
    offset=max(0,min(positions)-80) if positions else 0
    return ('…' if offset else '')+body[offset:offset+480]+('…' if len(body)>offset+480 else '')

def project_contexts(config,query):
    """Use the user's existing catalogue, never a hand-written topic alias list."""
    path=Path(config.get('memory_hub_root',''))/'20-Projects'/'项目索引.md'
    if not path.is_file(): return []
    words=concepts(query);contexts=[]
    for line in read(path)[0].splitlines():
        if not line.startswith('| [['): continue
        link=re.search(r'\[\[([^\]]+)\]\]',line)
        root=re.search(r'[A-Z]:[\\/][^`|\r\n]+',line,re.I)
        if not link or not root: continue
        names=link[1].split('|');name=' '.join(names)
        overlap=[w for w in words if w in name.casefold()]
        if len(overlap)<2 and not any(len(n)>=3 and n in query for n in names):
            # The catalogue's own receipts often use a different product name.
            # Learn literal aliases from those records, scoped by the catalogue
            # name; do not maintain a per-question/domain synonym dictionary.
            page=path.parent/(names[0]+'.md')
            if not overlap or not page.is_file() or page.stat().st_size>1024*1024:continue
            text=read(page)[0]
            prefix=query[:24]
            aliases=[prefix[i:j] for i in range(len(prefix)) for j in range(i+5,min(i+13,len(prefix))+1) if re.fullmatch(r'[\u4e00-\u9fff]+',prefix[i:j]) and prefix[i:j] in text]
            if not aliases:continue
            alias=max(aliases,key=len)
            overlap=list(dict.fromkeys(overlap+[w for w in words if w in alias]))
        contexts.append((name,root[0].strip().replace('/','\\').casefold(),overlap))
    return contexts

@lru_cache(maxsize=4)
def version_catalog(index_path,revision):
    cache=Path(index_path).with_suffix('.versions.json')
    signature=hashlib.sha256(('version-rules-v1|'+revision).encode()).hexdigest()
    try:
        saved=json.loads(cache.read_text(encoding='utf-8'))
        if isinstance(saved,dict) and saved.get('revision')==signature and isinstance(saved.get('rules'),list):
            return [dict(rule,scope=set(rule['scope'])) for rule in saved['rules']]
    except (OSError,ValueError,TypeError,KeyError):pass
    with closing(sqlite3.connect(index_path)) as c:
        rows=c.execute('SELECT p.*,d.source,d.relative,d.modified,d.hash,0 FROM passages p JOIN documents d ON p.path=d.path').fetchall()
    rules=evidence.version_rules(rows)
    staged=cache.with_suffix(f'.{os.getpid()}.pending')
    try:
        serial=[dict(rule,scope=sorted(rule['scope'])) for rule in rules]
        staged.write_text(json.dumps(dict(revision=signature,rules=serial),ensure_ascii=False),encoding='utf-8')
        os.replace(staged,cache)
    except OSError:pass
    finally:staged.unlink(missing_ok=True)
    return rules

def evidence_key(row):
    independent=row[3].startswith('任务收工：') or (row[6]=='formal' and re.match(r'\d{4}-\d{2}-\d{2}-worklog$',row[2]))
    return (row[1],row[3] if independent else '')

def explaining_span(config,row,query,words,semantic_hits,definition_hits):
    pid=row[0];sh=semantic_hits.get(pid);dh=definition_hits.get(pid)
    start,end,quality=evidence.choose_span(row,query,words,sh,dh)
    if re.search(r'文件名|源码路径|证据路径|哪个文件|源文件在哪',query):
        if sh:return row,sh['offset'],sh['end']
        return row,start,end
    with closing(connect(config)) as c:
        if row[3].startswith('任务收工：') or (row[6]=='formal' and re.match(r'\d{4}-\d{2}-\d{2}-worklog$',row[2]) and row[3] not in evidence.REFERENCE_HEADINGS):
            siblings=c.execute('SELECT p.*,d.source,d.relative,d.modified,d.hash,0 FROM passages p JOIN documents d ON p.path=d.path WHERE p.path=? AND p.heading=? ORDER BY p.line LIMIT 30',(row[1],row[3])).fetchall()
        else:
            siblings=c.execute('SELECT p.*,d.source,d.relative,d.modified,d.hash,0 FROM passages p JOIN documents d ON p.path=d.path WHERE p.path=? ORDER BY p.line LIMIT 240',(row[1],)).fetchall()
    candidates=[]
    siblings=list({candidate[0]:candidate for candidate in [row,*siblings]}.values())
    for candidate in siblings:
        if candidate[3] in evidence.REFERENCE_HEADINGS:continue
        a,b,q=evidence.choose_span(candidate,query,words,semantic_hits.get(candidate[0]),definition_hits.get(candidate[0]))
        text=candidate[5][a:b]
        content='\n'.join(line[2] for line in evidence.lines(text) if not line[3])
        relevance=sum(weight for word,weight in words.items() if word in content.casefold())
        hits=[h for h in (semantic_hits.get(candidate[0]),definition_hits.get(candidate[0])) if h]
        similarity=max((h['similarity'] for h in hits),default=0)
        candidates.append((12*relevance/max(1,sum(words.values()))+similarity*10+6*evidence.intent_fit(query,text)+q*2,candidate,a,b))
    if not candidates:return row,start,end
    _,candidate,a,b=max(candidates,key=lambda x:x[0])
    return candidate,a,b

def search(config,query,source='all',limit=8,mode='natural',path_filter=''):
    if not isinstance(query,str) or not 1<=len(query.strip())<=240: raise ValueError('请输入 1 至 240 字的问题。')
    if source!='all' and source not in SOURCES: raise ValueError('知识库范围无效。')
    if not isinstance(path_filter,str) or len(path_filter)>160: raise ValueError('来源限定无效。')
    if not database(config).exists(): refresh(config)
    started=time.perf_counter();terms=tokens(query,True)[:90]
    contexts=project_contexts(config,query) if mode!='strict' else []
    key_words=concepts(query);word_weights={w:1 for w in key_words}
    location_query=bool(re.search(r'文件名|源码路径|证据路径|哪个文件|源文件在哪',query))
    scope_links={}
    if not terms: raise ValueError('问题中需要有文字或数字。')
    with closing(connect(config)) as c:
        conditions=[];params=[]
        if source!='all': conditions.append('d.source=?');params.append(source)
        if path_filter: conditions.append('instr(lower(d.relative),lower(?))>0');params.append(path_filter)
        if mode=='strict':
            # Existing runtime semantics: space separated literals must all occur.
            conditions += ['instr(lower(p.body),lower(?))>0' for _ in query.split()]
            params += query.split()
            sql='SELECT p.*,d.source,d.relative,d.modified,d.hash,0 AS score FROM passages p JOIN documents d ON p.path=d.path WHERE '+' AND '.join(conditions or ['1'])+' LIMIT 300'
        else:
            conditions.insert(0,'passages_fts MATCH ?');params.insert(0,' OR '.join('"'+t.replace('"','""')+'"' for t in terms))
            sql='SELECT p.*,d.source,d.relative,d.modified,d.hash,bm25(passages_fts,0,1.5,2,1) AS score FROM passages_fts JOIN passages p ON passages_fts.id=p.id JOIN documents d ON p.path=d.path WHERE '+' AND '.join(conditions)+' ORDER BY score LIMIT 500'
        rows=c.execute(sql,params).fetchall() if mode=='strict' or source!='all' else []
        if mode!='strict':
            if source=='all':
                # A large transcript collection must not consume the entire
                # candidate budget before another library can be considered.
                rows=[]
                for candidate_source in SOURCES:
                    scoped_sql=sql.replace(' ORDER BY score LIMIT 500',' AND d.source=? ORDER BY score LIMIT 300')
                    rows.extend(c.execute(scoped_sql,params+[candidate_source]).fetchall())
            # Retrieve referenced project receipts even when their section only
            # contains a repo path, rather than the user's project nickname.
            if contexts:
                extra=[]
                for name,root,overlap in contexts:
                    linked_rows=c.execute('SELECT p.*,d.source,d.relative,d.modified,d.hash,0 FROM passages p JOIN documents d ON p.path=d.path WHERE instr(lower(p.body),?)>0 AND (?="all" OR d.source=?) AND instr(lower(d.relative),lower(?))>0 LIMIT 1000',(root,source,source,path_filter)).fetchall()
                    extra.extend(linked_rows)
                    for linked_row in linked_rows:
                        # Source-code identity often sits in a later file-list
                        # chunk. Carry that identity only within this task scope,
                        # while keeping its file list out of the displayed answer.
                        if not linked_row[3].startswith('任务收工：'):continue
                        key=evidence_key(linked_row);scope_links.setdefault(key,set()).update(overlap)
                        extra.extend(c.execute('SELECT p.*,d.source,d.relative,d.modified,d.hash,0 FROM passages p JOIN documents d ON p.path=d.path WHERE p.path=? AND p.heading=? ORDER BY p.line LIMIT 30',(linked_row[1],linked_row[3])).fetchall())
                by_id={r[0]:r for r in rows}
                by_id.update({r[0]:r for r in extra})
                rows=list(by_id.values())
            if not location_query:
                rows=[r for r in rows if evidence.has_explanation(r[5])]
            n=c.execute('SELECT count(*) FROM passages').fetchone()[0]
            counts=dict(c.execute('SELECT term,doc FROM term_stats WHERE term IN ('+','.join('?' for _ in terms)+')',terms))
            weights={t:math.log(1+n/(1+counts.get(t,n))) for t in terms}
            key_words=concepts(query)
            word_weights={w:sum(weights.get(t,1) for t in tokens(w))/max(1,len(tokens(w))) for w in key_words}
            @lru_cache(maxsize=4096)
            def rerank(row):
                title,heading,body=row[2].casefold(),row[3].casefold(),row[5].casefold()
                linked=[word for _,root,overlap in contexts if root in body.replace('/','\\') for word in overlap]
                linked.extend(scope_links.get(evidence_key(row),()))
                content=sum(w for t,w in word_weights.items() if t in body or t in linked)
                project_words={t for _,_,overlap in contexts for t in overlap}
                location=sum(w for t,w in word_weights.items() if (t in heading or t in title) and t not in project_words)
                # Summaries and coordination pages repeat many topics. Prefer the
                # actual section explaining the question, retaining all sources.
                aggregate=any(x in row[7] for x in ('00-Dashboard','dashboard.md','索引')) or row[3] in ('项目导航','收工回执索引')
                score=content+location*1.5+min(-row[-1],40)*.05
                return score*(.65 if aggregate else 1)
            rows=sorted(rows,key=rerank,reverse=True)
    semantic=dict(ok=False,reason='当前为文字召回。',matches=[])
    semantic_hits={};definition_hits={};row_scores={}
    if mode!='strict' and config.get('semantic_model_path'):
        try:
            try:
                from scripts import semantic_search
            except ImportError:
                import semantic_search
            semantic=semantic_search.search(config,query,source,path_filter)
            if source=='all' and semantic.get('ok'):
                pools=[semantic]
                pools.extend(semantic_search.search(config,query,s,path_filter) for s in SOURCES)
                recalled={}
                definitions={}
                claims={}
                mappings={}
                for pool in pools:
                    if pool.get('ok'):
                        for hit in pool['matches']:
                            if hit['id'] not in recalled or hit['similarity']>recalled[hit['id']]['similarity']:recalled[hit['id']]=hit
                        for hit in pool.get('definitions',[]):
                            definitions[hit['id']]=hit
                        for hit in pool.get('claims',[]):claims[hit['id']]=hit
                        for hit in pool.get('mappings',[]):mappings[hit['id']]=hit
                semantic['matches']=sorted(recalled.values(),key=lambda h:h['similarity'],reverse=True)
                semantic['definitions']=sorted(definitions.values(),key=lambda h:h['similarity'],reverse=True)
                semantic['claims']=sorted(claims.values(),key=lambda h:h['similarity'],reverse=True)
                semantic['mappings']=sorted(mappings.values(),key=lambda h:h['similarity'],reverse=True)
                if any(not pool.get('ok') for pool in pools):
                    semantic['reason']='部分分库语义召回不可用，保留可用语义与文字结果。'
        except (OSError,ValueError,ImportError):
            semantic=dict(ok=False,reason='本地语义服务不可用，当前使用文字召回。',matches=[])
        if semantic.get('ok'):
            semantic_hits={r['id']:dict(r,rank=i+1) for i,r in enumerate(semantic['matches'])}
            definition_hits={r['id']:dict(r,rank=i+1) for i,r in enumerate(semantic.get('definitions',[]))}
            claim_hits={r['id']:dict(r,rank=i+1) for i,r in enumerate(semantic.get('claims',[]))}
            mapping_hits={r['id']:dict(r,rank=i+1) for i,r in enumerate(semantic.get('mappings',[]))}
            base_definition_hits=definition_hits.copy()
            for pool in (claim_hits,mapping_hits):
                for pid,hit in pool.items():
                    if pid not in definition_hits or hit['similarity']>definition_hits[pid]['similarity']:definition_hits[pid]=hit
            # Rank documents rather than passages: a long document must not
            # gain or lose places merely because it has more indexed sections.
            lexical={}
            for row in rows:
                lexical.setdefault(evidence_key(row),len(lexical)+1)
            union={r[0]:r for r in rows}
            with closing(connect(config)) as c:
                if semantic_hits or definition_hits:
                    query_ids=list(set(semantic_hits)|set(definition_hits))
                    for row in c.execute('SELECT p.*,d.source,d.relative,d.modified,d.hash,0 FROM passages p JOIN documents d ON p.path=d.path WHERE p.id IN ('+','.join('?' for _ in query_ids)+') AND (?="all" OR d.source=?) AND instr(lower(d.relative),lower(?))>0',query_ids+[source,source,path_filter]):
                        union.setdefault(row[0],row)
            if not location_query:
                union={pid:row for pid,row in union.items() if evidence.has_explanation(row[5])}
            semantic_docs={}
            for pid,hit in semantic_hits.items():
                if pid in union:
                    semantic_docs.setdefault(evidence_key(union[pid]),len(semantic_docs)+1)
            definition_docs={}
            for pid in base_definition_hits:
                if pid in union:definition_docs.setdefault(evidence_key(union[pid]),len(definition_docs)+1)
            claim_docs={}
            for pid in claim_hits:
                if pid in union:claim_docs.setdefault(evidence_key(union[pid]),len(claim_docs)+1)
            mapping_docs={}
            for pid in mapping_hits:
                if pid in union:mapping_docs.setdefault(evidence_key(union[pid]),len(mapping_docs)+1)
            # Fuse document ranks, then select a passage within each document.
            def fused(row):
                key=evidence_key(row);sr=semantic_docs.get(key);lr=lexical.get(key)
                a=1/(8+sr) if sr else 0;b=1/(8+lr) if lr else 0
                # A strong paraphrase-only or catalogue-only match must survive
                # even when the other retriever misses it. Sum-only fusion
                # systematically favoured weak matches seen by both channels.
                d=1/(8+definition_docs[key]) if key in definition_docs else 0
                e=1/(8+claim_docs[key]) if key in claim_docs else 0
                m=1/(8+mapping_docs[key]) if key in mapping_docs else 0
                score=max(a,b,d,e,m)+.1*(a+b+d+e+m-max(a,b,d,e,m))
                aggregate=any(x in row[7] for x in ('00-Dashboard','dashboard.md','索引','多Agent协同看板'))
                return score*(.65 if aggregate else 1)
            @lru_cache(maxsize=4096)
            def passage_score(row):
                sh=semantic_hits.get(row[0]);dh=definition_hits.get(row[0])
                # Rank selects candidate documents; the actual explanation must
                # compete on its own semantic evidence and question form.
                score=max(sh['similarity'] if sh else 0,dh['similarity'] if dh else 0)
                hit=dh or sh
                fit_text=row[5][hit['offset']:hit['end']] if hit else row[5]
                content='\n'.join(r[2] for r in evidence.lines(fit_text) if not r[3]).casefold()
                lexical_fit=sum(w for word,w in word_weights.items() if word in content)/max(1,sum(word_weights.values()))
                score+=.35*evidence.intent_fit(query,fit_text)+.30*lexical_fit
                # References are useful for following links, but do not replace
                # the explanatory section as the default evidence excerpt.
                if row[3] in ('来源引用','相关概念','参考资料','来源'):score*=.9
                return score
            rows=sorted(union.values(),key=lambda row:(fused(row),passage_score(row),rerank(row)),reverse=True)
            anchors=[];anchor_keys=set()
            for row in rows:
                key=evidence_key(row)
                if key not in anchor_keys:
                    anchors.append(row);anchor_keys.add(key)
                if len(anchors)==8:break
            referenced={}
            for row in union.values():
                name=Path(row[1]).stem
                if len(name)<6:continue
                referenced[row[1]]=sum(1 for anchor in anchors if anchor[1]!=row[1] and (name+'.md' in anchor[5] or '[['+name in anchor[5]))
            curated=set()
            with closing(connect(config)) as c:
                curated={r[0] for r in c.execute('SELECT path FROM passages WHERE line=1 AND instr(body,"memoryTier: semantic")>0')}
            def supported(row):
                # Source metadata and explicit document links are general
                # provenance signals, not hard-coded business/question rules.
                factor=1.15 if row[1] in curated else 1
                factor*=1+min(referenced.get(row[1],0),4)*.04
                # A weak lexical rank must not outrank a direct explanation just
                # because it was recalled by multiple channels. Use the strongest
                # evidence in this document, retaining a lexical-only fallback.
                return fused(row)*factor
            document_strength={}
            for row in rows:
                key=evidence_key(row)
                document_strength[key]=max(document_strength.get(key,0),passage_score(row))
            base_supported=supported
            def supported(row):
                spoken=bool(re.search(r'原文转写|逐字稿',row[2]+' '+row[3]) or re.search(r'说话人\d|\[\d\d:\d\d:\d\d\]',row[5]))
                seek_original=bool(re.search(r'原话|谁说|逐字|转写|录音原文',query))
                evidence_question=bool(re.search(r'吗|行不行|能否|是否|为什么|原因|怎么会|为何|修复',query))
                form_factor=.6 if spoken and evidence_question and not seek_original else 1
                # Keep rank-based recall stable: an incidental boundary word in
                # a long document must not multiply its relevance several-fold.
                return base_supported(row)*(1 if location_query else 1+min(.3,document_strength[evidence_key(row)]*.3))*form_factor
            rows=sorted(rows,key=lambda row:(supported(row),passage_score(row),rerank(row)),reverse=True)
            row_scores={row[0]:supported(row) for row in rows}
    retired={}
    if mode!='strict':
        with closing(connect(config)) as c:
            revision=c.execute('SELECT value FROM metadata WHERE key="coverage"').fetchone()
        rules=version_catalog(str(database(config)),revision[0] if revision else '')
        historical=bool(re.search(r'旧版|历史版本|以前|原来|为什么改|变更过程|迁移过程',query))
        row_scores=row_scores or {row[0]:1/(8+i) for i,row in enumerate(rows,1)}
        authorities={};previous_order={row[0]:i for i,row in enumerate(rows)}
        for row in rows:
            claims=evidence.retired_by(row,rules)
            if claims:
                a,b,_=evidence.choose_span(row,query,word_weights,semantic_hits.get(row[0]),definition_hits.get(row[0]))
                claims=[claim for claim in claims if claim['explicit'] or claim['phrase'] in row[5][a:b]]
            if not claims:continue
            retired.setdefault(row[1],[]).extend(claims)
            if not historical:
                original=row_scores[row[0]];row_scores[row[0]]*=.35
                for claim in claims:authorities[claim['authority']]=max(authorities.get(claim['authority'],0),original)
        if authorities:
            by_id={row[0]:row for row in rows}
            with closing(connect(config)) as c:
                for path,score in authorities.items():
                    for row in c.execute('SELECT p.*,d.source,d.relative,d.modified,d.hash,0 FROM passages p JOIN documents d ON p.path=d.path WHERE p.path=? AND (?="all" OR d.source=?) AND instr(lower(d.relative),lower(?))>0',(path,source,source,path_filter)):
                        by_id.setdefault(row[0],row);row_scores[row[0]]=max(row_scores.get(row[0],0),score*1.05)
            rows=list(by_id.values())
        if not historical:
            def tie(row):
                if row[0] in previous_order:return -previous_order[row[0]]
                useful='\n'.join(r[2] for r in evidence.lines(row[5]) if not r[3])
                return sum(w for word,w in word_weights.items() if word in useful.casefold())-10000
            rows=sorted(rows,key=lambda row:(row_scores.get(row[0],0),tie(row)),reverse=True)
    rerank_spans={};rerank_ready=False
    if mode!='strict' and semantic.get('ok') and config.get('reranker_model_path'):
        by_id={row[0]:row for row in rows};prepared=[];identities=set();budgets={};spans_by_id={}
        def prepare(row,hit=None):
            if len(prepared)>=48 or not row or not evidence.has_explanation(row[5]):return False
            if hit:
                candidate=row
                # A single constraint or table row needs neighbouring original
                # context so its qualification is visible in the same excerpt.
                a=max(0,hit['offset']-180)
                a=row[5].rfind('\n',0,a)+1
                b=min(len(row[5]),max(hit['end'],hit['offset']+480),a+700)
            else:
                candidate,a,b=explaining_span(config,row,query,word_weights,semantic_hits,definition_hits)
            if b-a<180:
                start=max(0,a-180)
                start=candidate[5].rfind('\n',0,start)+1
                b=min(len(candidate[5]),max(b,a+300),start+700)
                a=start
            for start,end,text,meta,meaningful in evidence.lines(candidate[5]):
                if a<start<b and evidence.META_FIELD.match(text):
                    b=start;break
            key=(candidate[1],candidate[3]);identity=(candidate[0],a,b)
            if a>=b or identity in identities or budgets.get(key,0)>=2:return False
            if any(max(0,min(b,y)-max(a,x))>=.8*min(b-a,y-x) for x,y in spans_by_id.get(candidate[0],[])):return False
            identities.add(identity);budgets[key]=budgets.get(key,0)+1;prepared.append((candidate,a,b));spans_by_id.setdefault(candidate[0],[]).append((a,b));return True
        # Final ranking sees a bounded, diverse pool. A useful concept or mapping
        # cannot disappear merely because a transcript has more literal hits.
        selected=set()
        for row in rows:
            key=evidence_key(row)
            if key in selected:continue
            prepare(row);selected.add(key)
            if len(selected)>=16:break
        for channel,budget in [('definitions',8),('mappings',8),('claims',8),('matches',8)]:
            added=0
            for hit in semantic.get(channel,[]):
                row=by_id.get(hit['id'])
                if not row:continue
                if prepare(row,hit):added+=1
                if added>=budget:break
        try:
            ranked=semantic_search.rerank(config,query,[dict(id=row[0],offset=a,end=b) for row,a,b in prepared],source,path_filter)
        except (OSError,ValueError,ImportError):
            ranked=dict(ok=False,reason='本地证据重排暂不可用，保留原检索结果。',scores=[])
        if ranked.get('ok') and ranked.get('scores'):
            weights={};best={};prepared_by_key={(row[0],a,b):row for row,a,b in prepared}
            prior={}
            for row in rows:
                prior.setdefault(evidence_key(row),len(prior)+1)
            for hit in ranked['scores']:
                row=prepared_by_key.get((hit['id'],hit['offset'],hit['end']))
                if not row:continue
                probability=1/(1+math.exp(-max(-60,min(60,hit['score']))))
                text=row[5][hit['offset']:hit['end']]
                if not historical and any(claim['explicit'] or claim['phrase'] in text for claim in retired.get(row[1],[])):probability*=.35
                if probability>weights.get(row[0],-1):
                    weights[row[0]]=probability;best[row[0]]=row;rerank_spans[row[0]]=(hit['offset'],hit['end'])
            neural=sorted(best.values(),key=lambda row:weights[row[0]],reverse=True)
            neural_prior={}
            for row in neural:
                neural_prior.setdefault(evidence_key(row),len(neural_prior)+1)
            def combined(row):
                a,b=rerank_spans[row[0]]
                fit=evidence.intent_fit(query,row[5][a:b])
                # A model estimates topical relevance; project provenance and
                # evidence form remain independent signals, on bounded ranks.
                if contexts:
                    # Explicit project identity is provenance, which a generic
                    # topical model cannot establish. Keep scope order and use
                    # the model to select evidence within those scopes.
                    return -prior.get(evidence_key(row),160)+.01/(8+neural_prior[evidence_key(row)])
                provenance=1.15 if row[1] in curated else 1
                return (1/(8+neural_prior[evidence_key(row)])+.35/(8+prior.get(evidence_key(row),160)))*(1+.4*fit)*provenance
            ranked_rows=sorted(neural,key=combined,reverse=True)
            rows=ranked_rows+[row for row in rows if row[0] not in best];rerank_ready=bool(ranked_rows)
        elif ranked.get('reason'):
            semantic['reason']=ranked['reason']
    matches=[];seen=set();seen_hashes={};seen_fragments=set();file_counts={}
    for row in rows:
        pid,path,title,heading,line,body,src,relative,modified,sha,score=row
        key=(path,heading) if rerank_ready and not contexts else evidence_key(row) if mode!='strict' else (path,'')
        if key in seen or (sha in seen_hashes and seen_hashes[sha]!=path) or file_counts.get(path,0)>=2: continue
        if not Path(path).is_file(): continue
        if mode!='strict':
            if pid in rerank_spans:
                offset,end=rerank_spans[pid] if location_query else evidence.complete_span(row,*rerank_spans[pid])
            else:row,offset,end=explaining_span(config,row,query,word_weights,semantic_hits,definition_hits)
            pid,path,title,heading,line,body,src,relative,modified,sha,score=row
            fragment=body[offset:end]
        else:
            offset=0;fragment=excerpt(body,terms)
        seen.add(key);seen_hashes[sha]=path;file_counts[path]=file_counts.get(path,0)+1
        matched=[t for t in terms if t in (title+' '+heading+' '+body).casefold()]
        sh=semantic_hits.get(pid) or definition_hits.get(pid)
        fragment_key=re.sub(r'\s+','',fragment).casefold()
        if fragment_key in seen_fragments:continue
        seen_fragments.add(fragment_key)
        claims=retired.get(path,[])
        notice='历史资料，请核对版本和适用条件；不是当前项目决定。'
        if claims:
            claim=claims[0];notice=f'该资料含明确替代声明涉及的表述，请优先核对《{Path(claim["authority"]).stem}》。声明见《{Path(claim["basis_path"]).stem}》第 {claim["line"]} 行；本片段不一定整体失效。'
        matches.append(dict(id=pid,path=path,title=title,heading=heading,line=line+body[:offset].count('\n'),excerpt=fragment,source=src,source_label=SOURCES[src][0],relative=relative,modified=modified,sha256=sha,
            matched_terms=matched,score=score,retrieval='语义与文字融合' if sh else '文字召回',notice=notice))
        if len(matches)>=min(max(1,limit),20):break
    return dict(ok=True,query=query,matches=matches,coverage=coverage(config),seconds=round(time.perf_counter()-started,3),mode=mode,
        retrieval=dict(semantic_ready=semantic.get('ok',False),rerank_ready=rerank_ready,method='本地语义＋文字＋证据重排' if rerank_ready else '本地语义＋文字融合' if semantic.get('ok') else '文字召回',notice=semantic.get('reason',''),project_contexts=[name for name,_,_ in contexts]))

def resolve(config,passage_id):
    with closing(connect(config)) as c:
        row=c.execute('SELECT p.path,p.title,p.heading,p.line,p.body,d.source,d.hash FROM passages p JOIN documents d ON p.path=d.path WHERE p.id=?',(passage_id,)).fetchone()
    if not row: raise ValueError('资料已更新，请重新检索。')
    path,title,heading,line,body,source,sha=row
    root=Path(config[SOURCES[source][1]]).resolve()
    if not Path(path).resolve().is_relative_to(root): raise ValueError('资料不在配置知识库中。')
    _,current=read(Path(path))
    if current!=sha: raise ValueError('原文已变化，请刷新知识索引并重新选择。')
    return dict(id=passage_id,path=path,title=title,heading=heading,line=line,excerpt=body,source=source,sha256=sha)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--config',default=str(Path(__file__).resolve().parents[1]/'config/operations_dashboard.json'));parser.add_argument('--refresh',action='store_true');parser.add_argument('--force',action='store_true');parser.add_argument('--query');parser.add_argument('--source',default='all');parser.add_argument('--mode',default='natural')
    args=parser.parse_args();config=json.loads(Path(args.config).read_text(encoding='utf-8-sig'))
    print(json.dumps(refresh_all(config,args.force) if args.refresh else search(config,args.query,args.source,mode=args.mode),ensure_ascii=False))

if __name__=='__main__':main()
