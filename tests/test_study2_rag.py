import asyncio,json,sqlite3,tempfile
from pathlib import Path
import pytest
from study2_rag.common import normalize_title,tokenize,digest,split_artifact,read_json
from study2_rag.corpus import build_shared_dev_corpus,logical_hash
from study2_rag.bm25 import BM25
from study2_rag.prompts import render
from study2_rag.scoring import score
from experiment.storage import Store
from experiment.provider import parse_response
from experiment.provider import ProviderFailure
from study2_rag.collector import collect
from study2_rag.reconcile import reconcile
from study2_rag.common import write_jsonl

def fixture_records():
 return [{'_id':'q1','context':[['Alpha',['Alpha links to Beta.']],['Noise',['Unrelated text.']]]},
         {'_id':'q2','context':[['Beta',['Beta contains the answer.']],['Alpha',['Alpha links to Beta.']]]}]

def test_title_normalization():
 assert normalize_title('  Café\u00a0Page ')=='café page'

def test_corpus_deduplicates_and_is_deterministic():
 a=build_shared_dev_corpus(fixture_records());b=build_shared_dev_corpus(list(reversed(fixture_records())))
 assert len(a)==3 and logical_hash(a)==logical_hash(b)
 assert len({x['normalized_title'] for x in a})==3

def test_bm25_deterministic_and_support_title_resolves():
 docs=build_shared_dev_corpus(fixture_records());x=BM25(docs);s=x.score('Which Alpha links to Beta?')
 assert x.top(s,3)==x.top(s,3)
 assert normalize_title('Alpha') in x.by_title
 assert x.exact_rank(s,x.by_title['alpha'])>=1

def test_prompt_has_titles_but_no_experimental_labels():
 p=render('Question?',[{'title':'Alpha','text':'Text.'}])
 assert 'Title: Alpha' in p and 'focus=' not in p and 'support A' not in p

def test_scoring_reuses_official_behavior():
 assert score('The Eiffel Tower.','Eiffel Tower')['em']==1

def test_parser_accepts_short_stop_answer():
 r=parse_response({'modelVersion':'x','candidates':[{'finishReason':'STOP','content':{'parts':[{'text':'Paris'}]}}],'usageMetadata':{'promptTokenCount':10,'candidatesTokenCount':1,'totalTokenCount':11}})
 assert r['status']=='valid' and r['answer']=='Paris'

def test_parser_rejects_multiline():
 r=parse_response({'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':'Paris\nBecause'}]}}],'usageMetadata':{}})
 assert r['status']=='malformed'

def test_store_duplicate_prevention_and_immutability():
 with tempfile.TemporaryDirectory() as td:
  s=Store(Path(td)/'x.sqlite3');s.start('q::rag',1,{'x':1});o={'scientific_id':'q::rag','attempt':1,'status':'valid','latency_seconds':0.0};s.commit(o)
  with pytest.raises(sqlite3.IntegrityError):s.commit(o)
  with pytest.raises(ValueError):s.start('q::rag',2,{})
  assert len(s.observations())==1;s.close()

def test_corpus_variant_merge():
 records=[{'context':[['Same',['A.']]]},{'context':[['Same',['B.']]]}]
 d=build_shared_dev_corpus(records)[0]
 assert d['source_variant_count']==2 and 'A.' in d['text'] and 'B.' in d['text']

def test_tokenizer_unicode_and_punctuation():
 assert tokenize('New-York, 2026!')==['new','york','2026']

def test_recorded_protocol_self_hash():
 frozen=read_json(Path('config/study2_rag_frozen_protocol.json'))
 core={k:v for k,v in frozen.items() if k!='freeze_sha256'}
 assert digest(core)==frozen['freeze_sha256']
 assert frozen['retrieval_summary']['n_questions']==200

def test_split_artifact_names_match_frozen_files():
 root=Path('/tmp/root')
 assert split_artifact(root,'main','prompt').name=='prompt_manifest.jsonl'
 assert split_artifact(root,'main','retrieval').name=='retrieval_manifest.jsonl'
 assert split_artifact(root,'main','schedule').name=='main_schedule.jsonl'
 assert split_artifact(root,'pilot','prompt').name=='pilot_prompt_manifest.jsonl'
 assert split_artifact(root,'pilot','retrieval').name=='pilot_retrieval_manifest.jsonl'
 assert split_artifact(root,'pilot','schedule').name=='pilot_schedule.jsonl'

class FlakyProvider:
 def __init__(self):self.calls=0
 async def generate(self,prompt):
  self.calls+=1
  if self.calls==1:raise ProviderFailure('ReadTimeout',retryable=True)
  return {'modelVersion':'gemini-3.5-flash-lite','candidates':[{'finishReason':'STOP','content':{'parts':[{'text':'Paris'}]}}],
          'usageMetadata':{'promptTokenCount':10,'candidatesTokenCount':1,'totalTokenCount':11}}
 async def close(self):pass

def mini_frozen():
 return {'freeze_sha256':'test-freeze','configuration':{
  'default_concurrency':1,'default_rpm':100,'default_tpm':100000,'model':'gemini-3.5-flash-lite',
  'generation_config':{'maxOutputTokens':16},
  'retry_policy':{'max_attempts':3,'base_delay_seconds':0,'max_delay_seconds':0},
  'cost':{'input_usd_per_million':0.3,'output_usd_per_million':2.5,'main_emergency_guard_usd':2,'per_request_guard_usd':.05}}}

def test_retry_idempotent_resume_and_reconciliation(tmp_path,monkeypatch):
 out=tmp_path/'outputs/study2_rag';out.mkdir(parents=True)
 sid='q::rag';schedule=[{'scientific_id':sid,'item_id':'q','prompt_sha256':digest('prompt'),'schedule_index':0}]
 prompt=[{'scientific_id':sid,'item_id':'q','prompt':'prompt','prompt_sha256':digest('prompt')}]
 retrieval=[{'item_id':'q','answer':'Paris','retrieval_category':'complete','support_a_rank':1,'support_b_rank':2}]
 write_jsonl(out/'pilot_schedule.jsonl',schedule);write_jsonl(out/'pilot_prompt_manifest.jsonl',prompt);write_jsonl(out/'pilot_retrieval_manifest.jsonl',retrieval)
 frozen=mini_frozen()
 monkeypatch.setattr('study2_rag.collector.verify_freeze',lambda root:frozen)
 provider=FlakyProvider()
 asyncio.run(collect('pilot','test-freeze',True,root=tmp_path,provider=provider))
 assert provider.calls==2
 # Re-running the same schedule must not regenerate the committed observation.
 asyncio.run(collect('pilot','test-freeze',True,root=tmp_path,provider=provider))
 assert provider.calls==2
 monkeypatch.setattr('study2_rag.reconcile.verify_freeze',lambda root:frozen)
 result=reconcile('pilot',tmp_path,write=False)
 assert result['technical_pass'] and result['committed']==1 and result['technical_retries']==1
