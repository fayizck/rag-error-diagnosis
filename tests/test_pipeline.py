import ast
import asyncio
from collections import Counter
import copy
import json
import re
import sqlite3
import string
from pathlib import Path
import httpx
import numpy as np
import pytest
from experiment.common import ROOT, CONDITIONS, atomic_json, config, digest, read_jsonl
from experiment.prompts import eligibility, make_item, manifest_item, render, schedule, validate_item
from experiment.scoring import normalize_answer, score
from experiment.storage import Store, process_lock
from experiment.provider import Gemini, ProviderFailure, parse_response
from experiment.freeze import verify_freeze, source_hashes
from analysis.stats import paired_summary

@pytest.fixture
def record():
    return {'_id':'item-1','type':'bridge','question':'Where was the painter born?','answer':'London',
            'context':[['Painter',['The painter is Ada.','Ada was born in London.']],['Ada',['Ada painted the image.']]]+
                       [[f'Distractor {i}',[f'Irrelevant sentence {i}.']] for i in range(8)],
            'supporting_facts':[['Painter',1],['Ada',0]]}

@pytest.mark.parametrize('prediction,gold,em,f1',[
    ('The Eiffel Tower.','Eiffel Tower',1,1),('New York','York',0,2/3),
    ('yes','yes please',0,0),('noanswer','answer',0,0),('','',1,0),
    ('the','a',1,0),('London!','London',1,1),('x x y','x y y',0,2/3)])
def test_scoring(prediction,gold,em,f1):
    r=score(prediction,gold);assert r['em']==em;assert r['f1']==pytest.approx(f1)

def test_scorer_matches_official():
    source=ROOT/'data/reference/hotpot_evaluate_v1.py'
    assert source.exists(), 'Run dataset preparation to cache official scorer'
    tree=ast.parse(source.read_text())
    funcs=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in ('normalize_answer','f1_score','exact_match_score')]
    namespace={'re':re,'string':string,'Counter':Counter}
    exec(compile(ast.Module(body=funcs,type_ignores=[]),str(source),'exec'),namespace)
    terms=['','The','a B-C','yes','no','noanswer','New York','YORK','x x y','a\n b','Beyoncé','can\'t','1,000']
    for a in terms:
        for b in terms:
            r=score(a,b)
            assert r['normalized_prediction']==namespace['normalize_answer'](a)
            assert r['em']==namespace['exact_match_score'](a,b)
            assert r['f1']==namespace['f1_score'](a,b)[0]

def test_mapping_and_randomization(record):
    assert eligibility(record,config())==[]
    a=make_item(record,20260929);b=make_item(record,20260929)
    assert a==b and {a['group_a'],a['group_b']}=={'Painter','Ada'}
    reversed_record=copy.deepcopy(record);reversed_record['supporting_facts'].reverse()
    assert make_item(reversed_record,20260929)['group_a']==a['group_a']
    assert len({make_item(record,s)['group_a'] for s in range(10)})==2
    invalid=copy.deepcopy(record);invalid['supporting_facts'][0][1]=99
    assert 'invalid_support_index' in eligibility(invalid,config())
    invalid['supporting_facts'][0][1]=-1
    assert 'invalid_support_index' in eligibility(invalid,config())

def test_four_conditions(record):
    item=manifest_item(make_item(record,1));r=validate_item(item)
    assert r['focus_counts']=={'00':0,'10':1,'01':1,'11':2}
    for c in CONDITIONS:
        assert render(item,c).replace('focus="1"','focus="0"')==render(item,'00')
        assert '<s focus="1">Irrelevant' not in render(item,c)

@pytest.mark.parametrize('change',['question','title','order','text','duplicate','lost','flag'])
def test_invariance_rejects_mutations(record,change):
    item=make_item(record,1);p={c:render(item,c) for c in CONDITIONS}
    if change=='question':p['10']=p['10'].replace('Where was','When was')
    elif change=='title':p['10']=p['10'].replace('Title: Ada','Title: Ada2')
    elif change=='order':p['10']=p['10'].replace('The painter is Ada.','PLACEHOLDER').replace('Ada was born in London.','The painter is Ada.').replace('PLACEHOLDER','Ada was born in London.')
    elif change=='text':p['10']=p['10'].replace('London','Paris')
    elif change=='duplicate':p['10']+='\n<s focus="0">duplicate</s>'
    elif change=='lost':p['10']=p['10'].replace('<s focus="0">Irrelevant sentence 1.</s>','')
    else:p['10']=p['10'].replace('<s focus="0">Irrelevant sentence 1.', '<s focus="1">Irrelevant sentence 1.')
    with pytest.raises(ValueError):validate_item(item,p)

def test_schedule_hashes(record):
    item=manifest_item(make_item(record,1));a=schedule([item],1,'main')
    assert a==schedule([item],1,'main')
    assert len({r['scientific_id'] for r in a})==4
    assert item['item_sha256']==digest({k:v for k,v in item.items() if k!='item_sha256'})
    with pytest.raises(ValueError):schedule([item,item],1,'main')

def test_storage_resume_duplicate_and_orphan(tmp_path):
    path=tmp_path/'out.sqlite3';s=Store(path)
    obs={'scientific_id':'i::00','attempt':1,'status':'valid','latency_seconds':.1,'answer':'WRONG'}
    s.start('i::00',1,{});s.commit(obs)
    with pytest.raises((sqlite3.IntegrityError,ValueError)):s.commit(obs)
    with pytest.raises(ValueError):s.start('i::00',2,{})
    s.start('i::10',1,{});s.close()
    s=Store(path);s.recover_inflight()
    assert s.observations()=={'i::00':obs}
    assert any(e.get('status')=='uncertain_interruption' for e in s.events())
    with pytest.raises(sqlite3.IntegrityError):s.db.execute('DELETE FROM observations')
    s.close()

def test_process_lock(tmp_path):
    with process_lock(tmp_path):
        with pytest.raises(ValueError):
            with process_lock(tmp_path):pass

@pytest.mark.parametrize('status,retry',[(400,False),(401,False),(403,False),(404,False),(408,True),(429,True),(500,True),(503,True)])
def test_retry_http(status,retry):
    async def run():
        client=httpx.AsyncClient(transport=httpx.MockTransport(lambda request:httpx.Response(status,json={'error':{'message':'secret'}})))
        g=Gemini(config(),client)
        with pytest.raises(ProviderFailure) as e:await g.generate('test')
        assert e.value.retryable==retry and 'secret' not in str(e.value)
        await g.close()
    asyncio.run(run())

@pytest.mark.parametrize('finish,text,status',[
    ('STOP','London','valid'),('STOP','Paris','valid'),('MAX_TOKENS','Lon','truncated'),
    ('SAFETY','','refused'),('STOP','','empty'),('STOP','a\nb','malformed'),
    ('STOP','I cannot answer this.','refused'),('OTHER','London','malformed')])
def test_response_integrity(finish,text,status):
    r=parse_response({'candidates':[{'content':{'parts':[{'text':text}]},'finishReason':finish}]})
    assert r['status']==status

def test_thoughts_not_collected():
    r=parse_response({'candidates':[{'content':{'parts':[{'thought':True,'text':'hidden'},{'text':'London'}]},'finishReason':'STOP'}]})
    assert r['answer']=='London' and 'hidden' not in json.dumps(r)

@pytest.mark.parametrize('usage',[None,[],{'totalTokenCount':'not a number'},{'totalTokenCount':-1}])
def test_malformed_metadata_preserves_answer(usage):
    raw={'candidates':[{'content':{'parts':[{'text':'London'}]},'finishReason':'STOP'}], 'usageMetadata':usage}
    r=parse_response(raw)
    assert r['answer']=='London' and r['status']=='malformed'
    assert isinstance(r['token_usage'],dict)
    assert r['provider_metadata']['usageMetadata']==usage

@pytest.mark.parametrize('error,retry',[(httpx.ReadTimeout,True),(httpx.ConnectError,True),(httpx.UnsupportedProtocol,False)])
def test_transport_retry_policy(error,retry):
    async def run():
        def handler(request):raise error('sensitive provider detail')
        g=Gemini(config(),httpx.AsyncClient(transport=httpx.MockTransport(handler)))
        with pytest.raises(ProviderFailure) as e:await g.generate('fixture')
        assert e.value.retryable is retry and 'sensitive' not in str(e.value)
        await g.close()
    asyncio.run(run())

def test_pending_freeze_refused(tmp_path):
    atomic_json(tmp_path/'config/frozen_protocol.json',{'status':'PENDING'})
    with pytest.raises(ValueError,match='NOT FROZEN'):verify_freeze(tmp_path)

def test_bootstrap():
    y=[[0,1,0,1],[1,1,1,0],[0,0,0,0],[1,0,1,1]]
    a=paired_summary(y,42,1000);assert a==paired_summary(y,42,1000)
    primary=next(r for r in a[1] if r['contrast'].endswith('primary'))
    assert primary['estimate']==pytest.approx(0)
    assert primary['ci_low']<=primary['estimate']<=primary['ci_high']
    with pytest.raises(ValueError):paired_summary([[1,0,1]],42)
