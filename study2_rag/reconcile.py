from __future__ import annotations
from collections import Counter
import statistics,time
from experiment.storage import Store,process_lock
from .common import ROOT,digest,read_json,read_jsonl,require,write_json,split_artifact
from .freeze import verify_freeze
from .scoring import score

def reconcile(split='main',root=ROOT,write=True):
 require(split in ('pilot','main'),'Invalid split');frozen=verify_freeze(root);cfg=frozen['configuration']
 sched=read_jsonl(split_artifact(root,split,'schedule'));planned={x['scientific_id']:x for x in sched}
 retrieval={x['item_id']:x for x in read_jsonl(split_artifact(root,split,'retrieval'))}
 db=root/f'outputs/study2_rag/{split}/collection.sqlite3';obs={};events=[];fingerprint=None;errors=[]
 if db.exists():
  store=Store(db,readonly=True)
  try:obs=store.observations();events=store.events();fingerprint=store.fingerprint()
  finally:store.close()
 if set(obs)-set(planned):errors.append('unexpected_committed_ids')
 starts=[e for e in events if e['kind']=='start'];fin=[e for e in events if e['kind']=='finish']
 keys=[(e['scientific_id'],e['attempt'],e['kind']) for e in events]
 if len(keys)!=len(set(keys)):errors.append('duplicate_attempt_events')
 startkeys={(e['scientific_id'],e['attempt']) for e in starts};finkeys={(e['scientific_id'],e['attempt']) for e in fin}
 if finkeys-startkeys:errors.append('finish_without_start')
 if startkeys-finkeys:errors.append('inflight_attempts')
 terminal={e['scientific_id'] for e in fin if e.get('terminal')}
 for sid,row in obs.items():
  if sid not in planned:continue
  p=planned[sid];gold=retrieval[row['item_id']]['answer']
  for key in ('item_id','schedule_index','prompt_sha256'):
   if row.get(key)!=p[key]:errors.append(f'{key}_mismatch:{sid}')
  if row.get('freeze_sha256')!=frozen['freeze_sha256']:errors.append(f'freeze_mismatch:{sid}')
  if row.get('requested_model')!=cfg['model'] or row.get('generation_config')!=cfg['generation_config']:errors.append(f'model_config_mismatch:{sid}')
  if row.get('retrieval_category')!=retrieval[row['item_id']]['retrieval_category']:errors.append(f'retrieval_category_mismatch:{sid}')
  expected=score(row['answer'],gold)
  if any(row.get(k)!=v for k,v in expected.items()):errors.append(f'score_mismatch:{sid}')
  ends=[e for e in fin if e['scientific_id']==sid and e['attempt']==row['attempt']]
  if len(ends)!=1 or ends[0].get('observation_sha256')!=digest(row):errors.append(f'commit_event_mismatch:{sid}')
 counts=Counter(e['scientific_id'] for e in starts)
 for sid,n in counts.items():
  seq=sorted(e['attempt'] for e in starts if e['scientific_id']==sid)
  if seq!=list(range(1,n+1)) or n>cfg['retry_policy']['max_attempts']:errors.append(f'attempt_sequence:{sid}')
 for e in starts:
  if e['attempt']>1:
   prev=[x for x in fin if x['scientific_id']==e['scientific_id'] and x['attempt']==e['attempt']-1]
   if len(prev)!=1 or not prev[0].get('retryable') or prev[0].get('terminal'):errors.append(f'nontechnical_retry:{e["scientific_id"]}')
 statuses=Counter(x['status'] for x in obs.values());terminal_fail=terminal-set(obs);lat=[x['latency_seconds'] for x in obs.values()]
 usage=Counter()
 for x in obs.values():
  for k,v in x.get('token_usage',{}).items():
   if isinstance(v,(int,float)):usage[k]+=v
 collection_complete=not errors and len(obs)==len(planned) and not terminal_fail
 result={'split':split,'checked_at_unix':time.time(),'planned':len(planned),'committed':len(obs),'attempts':len(starts),
  'technical_retries':sum(e['attempt']>1 for e in starts),'technical_failure_attempts':sum('observation_sha256' not in e for e in fin),
  'valid_outputs':statuses['valid'],'response_integrity':{x:statuses[x] for x in ('valid','empty','malformed','refused','truncated')},
  'missing_ids':sorted(set(planned)-set(obs)-terminal_fail),'terminal_failures':sorted(terminal_fail),
  'duplicate_scientific_ids':len(sched)-len(planned),'unexpected_ids':sorted(set(obs)-set(planned)),
  'all_planned_accounted':set(planned)==set(obs)|terminal_fail,'integrity_errors':sorted(set(errors)),'integrity_passed':not errors,
  'collection_complete':collection_complete,'response_integrity_pass':statuses['valid']==len(planned),
  # Pilot formatting must pass before MAIN. During MAIN, every durably
  # committed response remains scientific data even if its content is invalid.
  'technical_pass':collection_complete and (split!='pilot' or statuses['valid']==len(planned)),
  'returned_model_versions':sorted({x.get('returned_model_version') or '<not exposed>' for x in obs.values()}),
  'token_usage_totals':dict(usage),'latency_seconds':{'median':statistics.median(lat) if lat else None,'mean':statistics.mean(lat) if lat else None,'max':max(lat) if lat else None},
  'logical_fingerprint':fingerprint,'freeze_sha256':frozen['freeze_sha256']}
 if write:write_json(root/f'outputs/study2_rag/{split}_reconciliation.json',result)
 return result

def seal_main(root=ROOT):
 r=reconcile('main',root);require(r['technical_pass'],'MAIN is incomplete or failed integrity; cannot seal')
 path=root/'outputs/study2_rag/main/sealed_outputs.json';payload={'freeze_sha256':r['freeze_sha256'],'logical_fingerprint':r['logical_fingerprint'],'planned':r['planned'],'committed':r['committed']}
 if path.exists():require(read_json(path)==payload,'Existing Study 2 seal differs')
 else:write_json(path,payload)
 return payload
