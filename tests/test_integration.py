"""Fake-provider tests only; all artifacts live in pytest temporary directories."""
import asyncio
import copy
import json
from pathlib import Path
import shutil
import numpy as np
import pytest
from experiment.common import ROOT, CONDITIONS, atomic_json, config, digest, file_hash, read_json, read_jsonl, write_jsonl_once
from experiment.prompts import make_item, manifest_item, schedule
from experiment.collector import collect
from experiment.provider import ProviderFailure
from experiment.freeze import source_hashes, verify_freeze
from experiment.storage import Store
from analysis.reconcile import reconcile, seal
from analysis.run import analyze

@pytest.fixture
def prepared(tmp_path):
    cfg=config();cfg.update(pilot_size=1,main_size=2)
    cfg['retry_policy']['base_delay_seconds']=0;cfg['retry_policy']['max_delay_seconds']=0
    atomic_json(tmp_path/'config/study.json',cfg)
    (tmp_path/'docs').mkdir();(tmp_path/'docs/PROTOCOL_SPEC.md').write_text('synthetic test protocol')
    (tmp_path/'requirements.txt').write_text('')
    source=read_jsonl(ROOT/'outputs/pilot_manifest.jsonl')[:3]
    paths=['config/study.json']
    all_items=[]
    for split,part in [('pilot',source[:1]),('main',source[1:])]:
        write_jsonl_once(tmp_path/f'outputs/{split}_manifest.jsonl',part)
        write_jsonl_once(tmp_path/f'outputs/{split}_schedule.jsonl',schedule(part,cfg['seed'],split))
        paths += [f'outputs/{split}_manifest.jsonl',f'outputs/{split}_schedule.jsonl']
        all_items+=part
    atomic_json(tmp_path/'outputs/preparation.json',{'files':{p:file_hash(tmp_path/p) for p in paths}})
    atomic_json(tmp_path/'outputs/model_verification.json',{'availability':'verified','requested_model':cfg['model'],'config_sha256':digest(cfg)})
    atomic_json(tmp_path/'outputs/token_verification.json',{'config_sha256':digest(cfg),'complete':True,'all_within_limit':True,
        'equal_tokens_all_conditions':True,'counts':{r['item_id']+'::'+c:{'tokens':10,'prompt_sha256':r['prompt_sha256'][c]} for r in all_items for c in CONDITIONS}})
    return tmp_path

class Fake:
    def __init__(self, fail_first=False, finish='STOP'):
        self.calls=0;self.fail_first=fail_first;self.finish=finish
    async def generate(self,prompt):
        self.calls+=1
        if self.fail_first and self.calls==1:raise ProviderFailure('http_503',retryable=True,http_status=503)
        return {'candidates':[{'content':{'parts':[{'text':'WRONG FIXTURE ANSWER'}]},'finishReason':self.finish}],
                'modelVersion':'fixture-version','usageMetadata':{'totalTokenCount':20,'promptTokenCount':10,'candidatesTokenCount':10}}
    async def close(self):pass

def fake_freeze(root):
    files=read_json(root/'outputs/preparation.json')['files']
    source=source_hashes(root)
    f={'status':'FROZEN','source_hashes':source,'files':dict(files,**source),'configuration':config(root),
       'returned_model_version':'fixture-version'}
    f['freeze_sha256']=digest(f)
    atomic_json(root/'config/frozen_protocol.json',f)
    return f

def test_real_collector_retry_resume_wrong_answer_not_retried(prepared):
    provider=Fake(fail_first=True)
    asyncio.run(collect('pilot',2,10000,1000000,prepared,provider))
    assert provider.calls==5
    r=reconcile('pilot',prepared,False)
    assert r['integrity_passed'] and r['committed']==4 and r['technical_retries']==1
    second=Fake();asyncio.run(collect('pilot',2,10000,1000000,prepared,second))
    assert second.calls==0
    store=Store(prepared/'outputs/pilot/collection.sqlite3',readonly=True)
    try:assert all(r['em']==0 for r in store.observations().values())
    finally:store.close()

def test_invalid_response_never_regenerated(prepared):
    provider=Fake(finish='MAX_TOKENS')
    asyncio.run(collect('pilot',2,10000,1000000,prepared,provider))
    assert provider.calls==4
    r=reconcile('pilot',prepared,False)
    assert r['response_integrity']['truncated']==4 and r['valid_outputs']==0
    second=Fake();asyncio.run(collect('pilot',2,10000,1000000,prepared,second));assert second.calls==0

def test_valid_freeze_and_tampering(prepared):
    fake_freeze(prepared);assert verify_freeze(prepared)['status']=='FROZEN'
    p=prepared/'outputs/main_schedule.jsonl';p.write_text(p.read_text()+'\n')
    with pytest.raises(ValueError,match='changed'):verify_freeze(prepared)

def test_fake_main_full_analysis_and_seal(prepared):
    fake_freeze(prepared)
    fake=Fake();asyncio.run(collect('main',2,10000,1000000,prepared,fake));assert fake.calls==8
    r=seal(prepared);assert r['integrity_passed'] and r['all_planned_accounted']
    analyze(prepared)
    out=prepared/'outputs/analysis'
    assert read_json(out/'summary.json')['n_complete']==2
    for f in ['item_level_results.csv','condition_results.csv','contrasts.csv','transitions.csv','tables.md',
              'figure_1_accuracy.pdf','figure_2_transitions.png']:
        assert (out/f).stat().st_size>0
    with pytest.raises(ValueError,match='sealed'):asyncio.run(collect('main',2,10000,1000000,prepared,Fake()))

def test_no_freeze_no_main_calls(prepared):
    atomic_json(prepared/'config/frozen_protocol.json',{'status':'PENDING'})
    provider=Fake()
    with pytest.raises(ValueError,match='NOT FROZEN'):asyncio.run(collect('main',2,10000,1000000,prepared,provider))
    assert provider.calls==0

def test_changed_config_stops_before_api(prepared):
    cfg=config(prepared);cfg['seed']+=1;atomic_json(prepared/'config/study.json',cfg)
    p=Fake()
    with pytest.raises(ValueError):asyncio.run(collect('pilot',2,10000,1000000,prepared,p))
    assert p.calls==0

def test_stale_token_audit_stops_before_api(prepared):
    path=prepared/'outputs/token_verification.json';audit=read_json(path)
    next(iter(audit['counts'].values()))['prompt_sha256']='wrong'
    atomic_json(path,audit);provider=Fake()
    with pytest.raises(ValueError,match='Token audit prompt hash mismatch'):
        asyncio.run(collect('pilot',2,10000,1000000,prepared,provider))
    assert provider.calls==0

def test_model_version_change_stops_dispatch(prepared):
    frozen=fake_freeze(prepared);frozen['returned_model_version']='other-version'
    frozen['freeze_sha256']=digest({k:v for k,v in frozen.items() if k!='freeze_sha256'})
    atomic_json(prepared/'config/frozen_protocol.json',frozen)
    provider=Fake()
    with pytest.raises(ValueError,match='version failure'):
        asyncio.run(collect('main',1,10000,1000000,prepared,provider))
    assert provider.calls==1
    report=reconcile('main',prepared)
    assert report['committed']==1 and not report['integrity_passed']

def test_paired_bootstrap_unit():
    from analysis.stats import paired_summary
    # Every within-question contrast is zero even though between-question outcomes vary.
    y=[[0,0,0,0],[1,1,1,1]]*10
    _, contrasts=paired_summary(y,5,10000)
    assert all(r['estimate']==r['ci_low']==r['ci_high']==0 for r in contrasts)
