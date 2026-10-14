"""Offline embedding retrieval. Only configured local weights, no downloads.

The short-lived loopback worker avoids reloading torch for every browser query.
It accepts bounded queries only; it cannot open files or change work decisions.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import secrets
import subprocess
import sys
import time
import urllib.request
from contextlib import closing
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

VERSION = 'bge-window-v1'

def worker_fingerprint(config):
    return hashlib.sha256((fingerprint(config)+'|retrieval-rpc-v2|'+str(config.get('reranker_model_path',''))).encode()).hexdigest()

def ranker_encoder(config):
    """Only explicit local ONNX weights; no network, installation or model code."""
    import numpy as np
    import onnxruntime as ort
    from tokenizers import Tokenizer
    root=Path(config['reranker_model_path'])
    tokenizer=Tokenizer.from_file(str(root/'tokenizer.json'))
    tokenizer.enable_truncation(max_length=384);tokenizer.enable_padding()
    options=ort.SessionOptions();options.intra_op_num_threads=8;options.inter_op_num_threads=1
    session=ort.InferenceSession(str(root/'onnx/model.onnx'),sess_options=options,providers=['CPUExecutionProvider'])
    names={item.name for item in session.get_inputs()}
    def score(pairs):
        order=sorted(range(len(pairs)),key=lambda i:len(pairs[i][1]));result=[0.]*len(pairs)
        for start in range(0,len(order),8):
            indices=order[start:start+8];encoded=tokenizer.encode_batch([pairs[i] for i in indices])
            inputs={name:np.asarray([getattr(e,attr) for e in encoded],dtype=np.int64) for name,attr in [('input_ids','ids'),('attention_mask','attention_mask'),('token_type_ids','type_ids')] if name in names}
            values=session.run(None,inputs)[0].reshape(-1)
            for i,value in zip(indices,values):result[i]=float(value)
        return result
    return score

def rerank_passages(config,candidates,source='all',path_filter=''):
    """Resolve bounded candidate IDs against the same source scope as recall."""
    try:
        from scripts import knowledge_search as k
    except ImportError:
        import knowledge_search as k
    if not isinstance(candidates,list) or not 1<=len(candidates)<=64:raise ValueError('重排候选数量无效')
    for item in candidates:
        if not isinstance(item,dict) or not isinstance(item.get('id'),str) or not 1<=len(item['id'])<=128:raise ValueError('重排候选ID无效')
        if type(item.get('offset')) is not int or type(item.get('end')) is not int or not 0<=item['offset']<item['end'] or item['end']-item['offset']>700:raise ValueError('重排候选区间无效')
    ids=list(dict.fromkeys(item['id'] for item in candidates))
    with closing(k.connect(config)) as c:
        rows={row[0]:row for row in c.execute('SELECT p.id,p.title,p.heading,p.body FROM passages p JOIN documents d ON p.path=d.path WHERE p.id IN ('+','.join('?' for _ in ids)+') AND (?="all" OR d.source=?) AND instr(lower(d.relative),lower(?))>0',ids+[source,source,path_filter])}
    result=[]
    for item in candidates:
        row=rows.get(item['id'])
        if row and item['end']<=len(row[3]):result.append((item,row[1]+'\n'+row[2]+'\n'+row[3][item['offset']:item['end']]))
    return result

def rerank(config,query,candidates,source='all',path_filter=''):
    if not config.get('reranker_model_path'):return dict(ok=False,reason='本机未启用证据重排。',scores=[])
    request=dict(operation='rerank',query=query,candidates=candidates,source=source,path_filter=path_filter)
    try:
        info=json.loads(paths(config)[1].read_text(encoding='utf-8'))
        if info.get('fingerprint')!=worker_fingerprint(config):raise ValueError('worker configuration changed')
        return call(info,request,timeout=45)
    except (OSError,ValueError,KeyError):
        return dict(ok=False,reason='本地证据重排暂不可用，保留原检索结果。',scores=[])

def definition_path(config):
    return paths(config)[0].with_suffix('.definitions.npz')

def definition_results(config,state,vector,valid):
    """Optional evidence view failure must not disable normal semantic recall."""
    import numpy as np
    target=definition_path(config)
    if not target.exists():return [],''
    try:
        signature=target.stat().st_mtime_ns
        if state.get('card_signature')!=signature:
            with np.load(target,allow_pickle=False) as data:
                if str(data['fingerprint'])!=fingerprint(config):raise ValueError('stale definition view')
                cards={name:data[name] for name in ('ids','offsets','ends','vectors')}
                cards['kinds']=data['kinds'] if 'kinds' in data else np.asarray(['definition']*len(cards['ids']))
            if any(len(cards[name])!=len(cards['ids']) for name in cards):raise ValueError('invalid definition view')
            state.update(card_signature=signature,cards=cards)
        cards=state.get('cards');result=[];seen={'definition':set(),'claim':set(),'mapping':set()}
        if cards and len(cards['ids']):
            scores=cards['vectors']@vector
            for i in np.argsort(-scores):
                pid=str(cards['ids'][i])
                kind=str(cards['kinds'][i])
                if kind not in seen or pid not in valid or pid in seen[kind] or len(seen[kind])>=40:continue
                seen[kind].add(pid);result.append(dict(id=pid,similarity=float(scores[i]),offset=int(cards['offsets'][i]),end=int(cards['ends'][i]),kind=kind))
                if all(len(ids)>=40 for ids in seen.values()):break
        return result,''
    except (OSError,ValueError,KeyError,TypeError):
        state.pop('cards',None);state.pop('card_signature',None)
        return [],'定义与约束通道暂不可用，保留正文语义与文字结果。'

def build_definitions(config):
    import numpy as np
    try:
        from scripts import knowledge_search as k,knowledge_evidence as evidence
    except ImportError:
        import knowledge_search as k
        import knowledge_evidence as evidence
    target=definition_path(config);previous={}
    if target.exists():
        with np.load(target,allow_pickle=False) as data:
            if str(data['fingerprint'])==fingerprint(config):
                previous=dict(zip(map(str,data['keys']),data['vectors']))
    with closing(k.connect(config)) as c:
        rows=c.execute('SELECT p.*,d.source,d.relative,d.modified,d.hash,0 FROM passages p JOIN documents d ON p.path=d.path ORDER BY p.id').fetchall()
    cards=list(evidence.evidence_cards(rows));vectors=[];keys=[];pending=[]
    for i,card in enumerate(cards):
        key=hashlib.sha256(('definitions-v1'+card['text']).encode()).hexdigest();keys.append(key)
        cached=previous.get(key);vectors.append(cached)
        if cached is None:pending.append(i)
    model=encoder(config) if pending else None
    # Batch similarly sized claims so one long paragraph cannot force padding
    # every short rule to the same length. Source/card order stays unchanged.
    pending.sort(key=lambda i:len(cards[i]['text']))
    for start in range(0,len(pending),32):
        indices=pending[start:start+32]
        for i,v in zip(indices,model.encode([cards[i]['text'] for i in indices])):vectors[i]=v
        if start % 320 == 0: print(json.dumps(dict(evidence_encoded=min(start+32,len(pending)),total=len(cards))),flush=True)
    staged=target.with_suffix('.pending.npz')
    try:
        np.savez(staged,keys=np.asarray(keys),ids=np.asarray([x['id'] for x in cards]),offsets=np.asarray([x['offset'] for x in cards]),ends=np.asarray([x['end'] for x in cards]),kinds=np.asarray([x['kind'] for x in cards]),vectors=np.asarray(vectors,dtype=np.float32),fingerprint=np.asarray(fingerprint(config)))
        os.replace(staged,target)
    finally:staged.unlink(missing_ok=True)
    return dict(cards=len(cards),encoded=len(pending),reused=len(cards)-len(pending))


def paths(config):
    base = Path(config.get('knowledge_index') or Path(config['snapshot_output']).parent / 'knowledge-index.sqlite3')
    return base.with_suffix('.semantic.npz'), base.with_suffix('.worker.json')


def fingerprint(config):
    model = Path(config.get('semantic_model_path', ''))
    if not model.is_dir() or not (model / 'config.json').is_file():
        return ''
    backend = config.get('semantic_onnx_path', '')
    return hashlib.sha256((str(model.resolve()) + VERSION + str(backend)).encode()).hexdigest()


def encoder(config):
    os.environ['HF_HUB_OFFLINE'] = '1'
    os.environ['TRANSFORMERS_OFFLINE'] = '1'
    os.environ['TOKENIZERS_PARALLELISM'] = 'false'
    if config.get('semantic_onnx_path'):
        import numpy as np
        import onnxruntime as ort
        from tokenizers import Tokenizer
        tokenizer = Tokenizer.from_file(str(Path(config['semantic_model_path']) / 'tokenizer.json'))
        tokenizer.enable_truncation(max_length=512)
        tokenizer.enable_padding()
        options = ort.SessionOptions()
        options.intra_op_num_threads = 8
        options.inter_op_num_threads = 1
        session = ort.InferenceSession(config['semantic_onnx_path'], sess_options=options, providers=['CPUExecutionProvider'])
        class LocalEncoder:
            def encode(self, texts, **kwargs):
                encoded = tokenizer.encode_batch(texts)
                inputs = {name:np.asarray([getattr(e, attr) for e in encoded], dtype=np.int64)
                          for name,attr in [('input_ids','ids'),('attention_mask','attention_mask'),('token_type_ids','type_ids')]}
                return session.run(None, inputs)[0]
        return LocalEncoder()
    from sentence_transformers import SentenceTransformer
    import torch
    torch.set_num_threads(4)
    model = SentenceTransformer(config['semantic_model_path'], device='cpu', local_files_only=True)
    model.max_seq_length = 512
    return model


def building(config):
    """A recent progress heartbeat prevents an overlapping UI rebuild."""
    progress=paths(config)[0].with_suffix('.progress.json')
    try:
        value=json.loads(progress.read_text(encoding='utf-8'))
        return 0<=value['encoded']<value['total'] and 0<=time.time()-progress.stat().st_mtime<180
    except (OSError,ValueError,KeyError,TypeError):return False


def windows(body):
    # Chinese characters can each consume a token. Keep full coverage rather
    # than silently truncating the end of a 1600-character source passage.
    for start in range(0, len(body), 360):
        yield start, min(len(body), start + 440), body[start:start + 440]
        if start + 440 >= len(body):
            break


def build(config):
    import numpy as np
    try:
        from scripts import knowledge_search as k
    except ImportError:
        import knowledge_search as k
    if not fingerprint(config):
        raise ValueError('本地语义模型未配置或文件不完整。')
    target, _ = paths(config)
    previous = {}
    if target.exists():
        with np.load(target, allow_pickle=False) as old:
            if str(old['fingerprint']) == fingerprint(config):
                previous = {str(i):v for i,v in zip(old['keys'],old['vectors'])}
    with closing(k.connect(config)) as c:
        rows = c.execute('SELECT id,title,heading,body FROM passages ORDER BY id').fetchall()
    keys, ids, offsets, ends, texts, pending = [], [], [], [], [], []
    vectors = []
    for pid,title,heading,body in rows:
        for start,end,content in windows(body):
            text = f'{title}\n{heading}\n{content}'
            # Embeddings depend on text/model, not the document-wide passage ID.
            # A new receipt in a large worklog must not re-encode every old
            # unchanged section. Legacy keys migrate without an expensive build.
            key = hashlib.sha256((VERSION+text).encode()).hexdigest()
            legacy = hashlib.sha256((pid+VERSION+text).encode()).hexdigest()
            cached = previous.get(key)
            if cached is None:cached=previous.get(legacy)
            keys.append(key);ids.append(pid);offsets.append(start);ends.append(end)
            vectors.append(cached)
            if cached is None:
                texts.append(text);pending.append(len(keys)-1)
    # Group similar lengths to avoid padding short records to the longest one
    # in every batch. Rank fusion and source text remain unchanged.
    ordered = sorted(zip(texts,pending), key=lambda item:len(item[0]))
    model = encoder(config) if pending else None
    for start in range(0,len(ordered),32):
        batch=ordered[start:start+32]
        encoded = model.encode([t for t,i in batch], normalize_embeddings=True, show_progress_bar=False)
        for (_,index),vector in zip(batch,encoded):
            vectors[index] = vector
        if start % 320 == 0:
            print(json.dumps(dict(encoded=min(start+32,len(texts)),total=len(texts))),flush=True)
            target.with_suffix('.progress.json').write_text(json.dumps(dict(encoded=min(start+32,len(texts)),total=len(texts))),encoding='utf-8')
    staged = target.with_suffix('.pending.npz')
    try:
        np.savez(staged, keys=np.asarray(keys),ids=np.asarray(ids),offsets=np.asarray(offsets),ends=np.asarray(ends),
                 vectors=np.asarray(vectors,dtype=np.float32),fingerprint=np.asarray(fingerprint(config)))
        os.replace(staged,target)
    finally:
        staged.unlink(missing_ok=True)
    report=dict(ok=True,windows=len(keys),passages=len(rows),encoded=len(pending),reused=len(keys)-len(pending),model='本地 bge-base-zh-v1.5',
        text_revision=hashlib.sha256(''.join(r[0] for r in rows).encode()).hexdigest())
    with closing(k.connect(config)) as c,c:
        c.execute('INSERT OR REPLACE INTO metadata VALUES (?,?)',('semantic',json.dumps(report,ensure_ascii=False)))
    target.with_suffix('.progress.json').write_text(json.dumps(dict(encoded=len(texts),total=len(texts))),encoding='utf-8')
    return report


def call(info,request,timeout=15):
    payload=json.dumps(request,ensure_ascii=False).encode()
    req=urllib.request.Request(f"http://127.0.0.1:{int(info['port'])}/search",data=payload,
        headers={'Content-Type':'application/json','Authorization':'Bearer '+info['token']})
    # Ignore machine proxy settings for a strictly loopback-only service.
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req,timeout=timeout) as response:
        return json.load(response)


def search(config,query,source='all',path_filter=''):
    target,descriptor=paths(config)
    if not fingerprint(config) or not target.exists():
        return dict(ok=False,reason='本地语义索引未建立，当前使用文字召回。',matches=[])
    request=dict(query=query,source=source,path_filter=path_filter)
    try:
        info=json.loads(descriptor.read_text(encoding='utf-8'))
        if info.get('fingerprint')==worker_fingerprint(config):
            return call(info,request)
    except (OSError,ValueError,KeyError):
        pass
    # Exclusive startup claim prevents two simultaneous queries launching two
    # heavyweight encoders. A crashed claim expires after the startup budget.
    lock=descriptor.with_suffix('.starting')
    owner=False
    try:
        if lock.exists() and time.time()-lock.stat().st_mtime>60:
            lock.unlink()
        try:
            with lock.open('x') as f: f.write(str(os.getpid()))
            owner=True
            config_path=descriptor.with_suffix('.config.json')
            config_path.write_text(json.dumps({key:config[key] for key in ('semantic_model_path','semantic_onnx_path','snapshot_output','knowledge_index','reranker_model_path') if key in config}),encoding='utf-8')
            with descriptor.with_suffix('.error.log').open('ab') as error:
                subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'--serve','--config',str(config_path)],
                    stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=error,
                    creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        except FileExistsError:
            pass
        deadline=time.monotonic()+40
        while time.monotonic()<deadline:
            try:
                info=json.loads(descriptor.read_text(encoding='utf-8'))
                if info.get('fingerprint')==worker_fingerprint(config):
                    return call(info,request,timeout=3)
            except (OSError,ValueError,KeyError):
                time.sleep(.25)
        return dict(ok=False,reason='本地语义服务尚未就绪，当前使用文字召回。',matches=[])
    finally:
        if owner: lock.unlink(missing_ok=True)


def serve(config):
    import numpy as np
    try:
        from scripts import knowledge_search as k
    except ImportError:
        import knowledge_search as k
    model=encoder(config)
    target,descriptor=paths(config);state={};token=secrets.token_urlsafe(32)
    last=time.monotonic()
    def retrieve(query,source,path_filter):
        signature=target.stat().st_mtime_ns
        if state.get('signature')!=signature:
            with np.load(target,allow_pickle=False) as data:
                if str(data['fingerprint'])!=fingerprint(config):
                    raise ValueError('模型版本变化，请重建语义索引。')
                state.update(signature=signature,ids=data['ids'],offsets=data['offsets'],ends=data['ends'],vectors=data['vectors'])
        v=model.encode(['为这个句子生成表示以用于检索相关文章：'+query],normalize_embeddings=True,show_progress_bar=False)[0]
        scores=state['vectors']@v
        with closing(k.connect(config)) as c:
            # Join against the current index so removed/changed passages cannot
            # leak back from an older vector file; all UI pinning rechecks hashes.
            valid=dict(c.execute('SELECT p.id,d.relative FROM passages p JOIN documents d ON d.path=p.path WHERE (?="all" OR d.source=?) AND instr(lower(d.relative),lower(?))>0',(source,source,path_filter)))
        result=[];seen=set()
        for i in np.argsort(-scores):
            pid=str(state['ids'][i])
            if pid not in valid or pid in seen:continue
            seen.add(pid)
            result.append(dict(id=pid,similarity=float(scores[i]),offset=int(state['offsets'][i]),end=int(state['ends'][i])))
            if len(result)>=160:break
        definitions,notice=definition_results(config,state,v,valid)
        return dict(ok=True,matches=result,definitions=[h for h in definitions if h.get('kind','definition')=='definition'],claims=[h for h in definitions if h.get('kind')=='claim'],mappings=[h for h in definitions if h.get('kind')=='mapping'],reason=notice,model='本地 bge-base-zh-v1.5')
    def reorder(query,candidates,source,path_filter):
        if not config.get('reranker_model_path'):return dict(ok=False,reason='本机未启用证据重排。',scores=[])
        selected=rerank_passages(config,candidates,source,path_filter)
        if not selected:return dict(ok=True,scores=[])
        if 'ranker' not in state:state['ranker']=ranker_encoder(config)
        scores=state['ranker']([(query,text) for item,text in selected])
        return dict(ok=True,scores=[dict(**item,score=score) for (item,text),score in zip(selected,scores)])
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            nonlocal last
            if self.path!='/search' or self.headers.get('Authorization')!='Bearer '+token:
                self.send_error(403);return
            try:
                size=int(self.headers.get('Content-Length','0'))
                if not 0<size<=16384:raise ValueError('请求长度无效')
                request=json.loads(self.rfile.read(size));q=request.get('query')
                source=request.get('source','all');f=request.get('path_filter','')
                if not isinstance(q,str) or not 1<=len(q)<=240 or source not in {'all',*k.SOURCES} or not isinstance(f,str) or len(f)>160:
                    raise ValueError('检索参数无效')
                last=time.monotonic()
                if request.get('operation','search')=='rerank':response=reorder(q,request.get('candidates'),source,f)
                elif request.get('operation','search')=='search':response=retrieve(q,source,f)
                else:raise ValueError('检索操作无效')
            except Exception:
                response=dict(ok=False,reason='本地语义检索失败，当前使用文字召回。',matches=[])
            body=json.dumps(response,ensure_ascii=False).encode()
            self.send_response(200);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
    server=HTTPServer(('127.0.0.1',0),Handler);server.timeout=5
    descriptor.write_text(json.dumps(dict(port=server.server_port,token=token,pid=os.getpid(),fingerprint=worker_fingerprint(config))),encoding='utf-8')
    try:
        while time.monotonic()-last<1200:server.handle_request()
    finally:
        server.server_close()
        try:
            if json.loads(descriptor.read_text(encoding='utf-8')).get('pid')==os.getpid():descriptor.unlink()
        except (OSError,ValueError):pass


def main():
    p=argparse.ArgumentParser();p.add_argument('--config',required=True);p.add_argument('--build',action='store_true');p.add_argument('--build-definitions',action='store_true');p.add_argument('--serve',action='store_true');args=p.parse_args()
    config=json.loads(Path(args.config).read_text(encoding='utf-8-sig'))
    if args.serve:serve(config)
    elif args.build_definitions:print(json.dumps(build_definitions(config),ensure_ascii=False))
    else:print(json.dumps(build(config),ensure_ascii=False))

if __name__=='__main__':main()
