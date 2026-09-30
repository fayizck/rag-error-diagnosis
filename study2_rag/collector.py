from __future__ import annotations
import asyncio,math,random,time,tempfile
from collections import Counter,deque
from pathlib import Path
from experiment.provider import Gemini,ProviderFailure,parse_response
from experiment.storage import Store,process_lock
from .common import ROOT,OUT,digest,read_json,read_jsonl,require,split_artifact
from .freeze import verify_freeze
from .scoring import score,normalize_answer

class RateLimiter:
 def __init__(self,rpm,tpm):self.rpm=rpm;self.tpm=tpm;self.entries=deque();self.lock=asyncio.Lock()
 async def acquire(self,tokens):
  require(tokens<=self.tpm,'Request reservation exceeds TPM')
  while True:
   async with self.lock:
    now=time.monotonic()
    while self.entries and now-self.entries[0][0]>=60:self.entries.popleft()
    if len(self.entries)<self.rpm and sum(x[1] for x in self.entries)+tokens<=self.tpm:
     ticket=[now,tokens];self.entries.append(ticket);return ticket
    wait=max(.05,min(1.0,60-(now-self.entries[0][0])))
   await asyncio.sleep(wait)
 async def settle(self,ticket,tokens):
  async with self.lock:ticket[1]=tokens

def usage_cost(usage,cost):
 inp=usage.get('promptTokenCount',0) if isinstance(usage,dict) else 0
 out=(usage.get('candidatesTokenCount',0)+usage.get('thoughtsTokenCount',0)) if isinstance(usage,dict) else 0
 return inp*cost['input_usd_per_million']/1e6+out*cost['output_usd_per_million']/1e6

def pilot_passed(root,frozen):
 p=root/'outputs/study2_rag/pilot_reconciliation.json'
 if not p.exists():return False
 r=read_json(p);allowed={frozen['freeze_sha256'],*frozen.get('compatible_pilot_freeze_sha256',[])}
 return r.get('technical_pass') is True and r.get('freeze_sha256') in allowed

async def collect(split,confirm_freeze,live,concurrency=None,rpm=None,tpm=None,root=ROOT,provider=None):
 require(split in ('pilot','main'),'Invalid split');require(live,'Live collection requires explicit --live')
 frozen=verify_freeze(root);require(confirm_freeze==frozen['freeze_sha256'],'Freeze confirmation mismatch')
 if split=='main':require(pilot_passed(root,frozen),'Live Study 2 pilot has not passed under a compatible freeze; MAIN remains blocked')
 cfg=frozen['configuration'];concurrency=concurrency or cfg['default_concurrency'];rpm=rpm or cfg['default_rpm'];tpm=tpm or cfg['default_tpm']
 prompts={r['item_id']:r for r in read_jsonl(split_artifact(root,split,'prompt'))}
 retrieval={r['item_id']:r for r in read_jsonl(split_artifact(root,split,'retrieval'))}
 schedule=read_jsonl(split_artifact(root,split,'schedule'))
 directory=root/f'outputs/study2_rag/{split}';directory.mkdir(parents=True,exist_ok=True)
 with process_lock(directory):
  store=Store(directory/'collection.sqlite3');store.recover_inflight()
  try:
   obs=store.observations();events=store.events();terminal={e['scientific_id'] for e in events if e['kind']=='finish' and e.get('terminal')}
   attempts=Counter(e['scientific_id'] for e in events if e['kind']=='start')
   require(set(obs)<={r['scientific_id'] for r in schedule},'Unexpected committed ID')
   provider=provider or Gemini(cfg);limiter=RateLimiter(rpm,tpm);sem=asyncio.Semaphore(concurrency);stop=asyncio.Event()
   running_cost=sum(usage_cost(x.get('token_usage',{}),cfg['cost']) for x in obs.values())
   guard=cfg['cost']['main_emergency_guard_usd'] if split=='main' else min(.25,cfg['cost']['main_emergency_guard_usd'])
   started=time.monotonic()
   async def one(row):
    nonlocal running_cost
    sid=row['scientific_id'];item=row['item_id']
    if sid in obs or sid in terminal:return
    prompt=prompts[item]['prompt']
    for attempt in range(attempts[sid]+1,cfg['retry_policy']['max_attempts']+1):
     if stop.is_set():return
     async with sem:
      # A UTF-8 byte count is a deliberately loose upper bound for admission;
      # provider-reported tokens settle the reservation after the response.
      ticket=await limiter.acquire(len(prompt.encode('utf-8'))+cfg['generation_config']['maxOutputTokens'])
      t=time.monotonic();store.start(sid,attempt,{'at':time.time(),'freeze_sha256':frozen['freeze_sha256'],'prompt_sha256':row['prompt_sha256']})
      try:raw=await provider.generate(prompt)
      except ProviderFailure as e:
       retry=e.retryable and attempt<cfg['retry_policy']['max_attempts']
       store.fail(sid,attempt,{'at':time.time(),'status':e.category,'http_status':e.http_status,'retryable':e.retryable,'terminal':not retry,'latency_seconds':time.monotonic()-t})
       if not retry:
        if not e.retryable:stop.set()
        return
       delay=max(e.retry_after,min(cfg['retry_policy']['max_delay_seconds'],cfg['retry_policy']['base_delay_seconds']*2**(attempt-1))+random.SystemRandom().uniform(0,1))
      else:
       parsed=parse_response(raw);record={'scientific_id':sid,'item_id':item,'split':split,'attempt':attempt,'schedule_index':row['schedule_index'],
        'freeze_sha256':frozen['freeze_sha256'],'prompt_sha256':row['prompt_sha256'],'requested_model':cfg['model'],'generation_config':cfg['generation_config'],
        'retrieval_category':retrieval[item]['retrieval_category'],'support_a_rank':retrieval[item]['support_a_rank'],'support_b_rank':retrieval[item]['support_b_rank'],
        **parsed,'latency_seconds':time.monotonic()-t}
       # A scientific response is never retried because of its content or
       # formatting. Apply the official answer scorer to every returned text
       # (empty/refused responses consequently score zero) and retain the
       # response-integrity status for separate reporting.
       record.update(score(parsed['answer'],retrieval[item]['answer']))
       this_cost=usage_cost(parsed['token_usage'],cfg['cost'])
       require(this_cost<=cfg['cost']['per_request_guard_usd'],'Per-request cost guard exceeded')
       require(running_cost+this_cost<=guard,'Run cost guard exceeded')
       store.commit(record);running_cost+=this_cost
       used=parsed['token_usage'].get('totalTokenCount')
       if isinstance(used,int):await limiter.settle(ticket,used)
       done=len(store.observations());elapsed=time.monotonic()-started
       print(f'{split} committed={done}/{len(schedule)} attempts={len([e for e in store.events() if e["kind"]=="start"])} cost=${running_cost:.6f} elapsed={elapsed:.1f}s last={sid}',flush=True)
       return
     await asyncio.sleep(delay)
   try:
    results=await asyncio.gather(*(one(r) for r in schedule),return_exceptions=True)
    for x in results:
     if isinstance(x,BaseException):raise x
   finally:await provider.close()
   if stop.is_set():raise RuntimeError('Collection failed closed; inspect reconciliation')
  finally:store.close()

def synthetic_rehearsal(root=ROOT):
 frozen=verify_freeze(root);schedule=read_jsonl(root/'outputs/study2_rag/main_schedule.jsonl')
 with tempfile.TemporaryDirectory() as td:
  store=Store(Path(td)/'collection.sqlite3')
  for row in schedule:
   store.start(row['scientific_id'],1,{'synthetic':True})
   record={'scientific_id':row['scientific_id'],'item_id':row['item_id'],'split':'synthetic','attempt':1,'status':'valid','answer':'synthetic','em':0,'f1':0.0,'latency_seconds':0.0}
   store.commit(record)
  obs=store.observations();events=store.events();store.close()
  require(len(obs)==200 and len(events)==400,'Synthetic schedule accounting failed')
 return {'status':'PASS','planned':200,'committed':200,'events':400,'duplicate_ids':len(schedule)-len({x['scientific_id'] for x in schedule}),'freeze_sha256':frozen['freeze_sha256']}
