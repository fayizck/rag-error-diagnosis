from __future__ import annotations
import csv, hashlib, json, os, re, unicodedata
from pathlib import Path

ROOT=Path(os.environ.get('NLP_TERM_PAPER_ROOT',Path(__file__).resolve().parents[1])).resolve()
OUT=ROOT/'outputs/study2_rag'
CONFIG=ROOT/'config/study2_rag_frozen_protocol.json'
CONDITIONS=('rag',)

def canonical(x):return json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':'))
def digest(x):return hashlib.sha256((x if isinstance(x,bytes) else canonical(x).encode())).hexdigest()
def file_hash(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read_json(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def read_jsonl(p):return [json.loads(x) for x in Path(p).read_text(encoding='utf-8').splitlines() if x.strip()]
def write_json(p,x):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(x,ensure_ascii=False,sort_keys=True,indent=2)+'\n',encoding='utf-8')
def write_jsonl(p,rows):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(''.join(canonical(x)+'\n' for x in rows),encoding='utf-8')
def write_csv(p,rows,fields=None):
 rows=list(rows);p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);fields=fields or list(rows[0])
 with p.open('w',newline='',encoding='utf-8') as f:
  w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');w.writeheader();w.writerows(rows)
def normalize_title(s):return ' '.join(unicodedata.normalize('NFKC',s).casefold().split())
def tokenize(s):return re.findall(r'[^\W_]+',unicodedata.normalize('NFKC',s).casefold(),flags=re.UNICODE)
def require(v,msg):
 if not v:raise ValueError(msg)
def rank(seed,namespace,key):return hashlib.sha256(f'{seed}|{namespace}|{key}'.encode()).hexdigest()
def split_artifact(root,split,kind):
 require(split in ('pilot','main'),'Invalid split')
 require(kind in ('prompt','retrieval','schedule'),'Invalid artifact kind')
 if split=='pilot':name=f'pilot_{kind}_manifest.jsonl' if kind!='schedule' else 'pilot_schedule.jsonl'
 else:name=f'{kind}_manifest.jsonl' if kind!='schedule' else 'main_schedule.jsonl'
 return Path(root)/'outputs/study2_rag'/name
