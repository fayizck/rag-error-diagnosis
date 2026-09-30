from __future__ import annotations
import json,statistics,math
from collections import Counter
from pathlib import Path
from .common import ROOT,OUT,canonical,digest,file_hash,normalize_title,rank,read_jsonl,require,write_csv,write_json,write_jsonl
from .corpus import build_shared_dev_corpus,logical_hash
from .bm25 import BM25
from .prompts import render

CFG={'schema_version':1,'study':'study2_rag','seed':20260929,'corpus_kind':'shared_hotpotqa_dev_distractor_page_pool',
 'corpus_source':'data/cache/hotpot_dev_distractor_v1.json','retrieval_unit':'one merged page-introduction unit per normalized Wikipedia title',
 'bm25':{'k1':1.2,'b':0.75,'query':'question text only','document':'title once plus page text','tokenizer':'Unicode NFKC casefold; regex [^\\W_]+; no stopword removal or stemming','tie_break':'passage_id ascending'},
 'primary_top_k':10,'descriptive_cutoffs':[1,2,5,10,20],
 'model':'gemini-3.5-flash-lite','api_base':'https://generativelanguage.googleapis.com/v1beta',
 'generation_config':{'temperature':0.0,'candidateCount':1,'maxOutputTokens':2048,'responseMimeType':'text/plain','thinkingConfig':{'thinkingLevel':'MINIMAL','includeThoughts':False}},
 'retry_policy':{'max_attempts':3,'retry_http_statuses':[408,429,500,502,503,504],
   'retry_transport':['ConnectError','ConnectTimeout','ReadTimeout','WriteTimeout','ReadError','WriteError','RemoteProtocolError','PoolTimeout'],
   'base_delay_seconds':2.0,'max_delay_seconds':60.0,'request_timeout_seconds':90},
 'default_concurrency':4,'default_rpm':30,'default_tpm':60000,
 'cost':{'input_usd_per_million':0.30,'output_usd_per_million':2.50,'main_emergency_guard_usd':2.0,'per_request_guard_usd':0.05},
 'prompt_utf8_byte_limit':100000,'documented_input_token_limit':1048576}

def median(values):return statistics.median(values) if values else None

def build_split(items,engine,docs,split):
 rows=[];csvrows=[];prompts=[]
 for m in items:
  scores=engine.score(m['question']);topidx=engine.top(scores,20)
  supports=[normalize_title(m['group_a']),normalize_title(m['group_b'])]
  missing=[x for x in supports if x not in engine.by_title]
  require(not missing,f'Support title absent from shared corpus: {missing}')
  support_idx=[engine.by_title[x] for x in supports]
  ranks=[engine.exact_rank(scores,i) for i in support_idx]
  top=[]
  for n,i in enumerate(topidx,1):
   d=docs[i];top.append({'rank':n,'passage_id':d['passage_id'],'title':d['title'],'normalized_title':d['normalized_title'],
    'text':d['text'],'bm25_score':scores.get(i,0.0),'source_variant_count':d['source_variant_count']})
  present=sum(r<=CFG['primary_top_k'] for r in ranks)
  category='complete' if present==2 else 'partial' if present==1 else 'failed'
  ambiguous=[]
  for label,i in zip(('A','B'),support_idx):
   if docs[i]['distinct_raw_title_count']>1:ambiguous.append(label+'_normalization_collision')
   if docs[i]['source_variant_count']>1:ambiguous.append(label+'_merged_text_variants')
  row={'item_id':m['item_id'],'question':m['question'],'answer':m['answer'],'group_a':m['group_a'],'group_b':m['group_b'],
    'support_a_rank':ranks[0],'support_b_rank':ranks[1],'best_support_rank':min(ranks),'worst_support_rank':max(ranks),
    'retrieval_category':category,'support_match_flags':ambiguous,'top_20':top}
  for k in CFG['descriptive_cutoffs']:
   row[f'support_a_at_{k}']=ranks[0]<=k;row[f'support_b_at_{k}']=ranks[1]<=k;row[f'both_at_{k}']=max(ranks)<=k
  prompt=render(m['question'],top[:CFG['primary_top_k']]);sid=m['item_id']+'::rag'
  promptrow={'scientific_id':sid,'item_id':m['item_id'],'split':split,'prompt':prompt,'prompt_sha256':digest(prompt),
    'retrieved_passage_ids':[x['passage_id'] for x in top[:CFG['primary_top_k']]],
    'retrieved_titles':[x['title'] for x in top[:CFG['primary_top_k']]],'retrieval_category':category,
    'prompt_utf8_bytes':len(prompt.encode()),'approx_input_tokens_char4':math.ceil(len(prompt)/4),
    'input_token_upper_bound_utf8_bytes':len(prompt.encode())}
  rows.append(row);prompts.append(promptrow)
  csvrows.append({k:v for k,v in row.items() if k!='top_20'}|{'support_match_flags':' | '.join(ambiguous),
    'top10_passage_ids':' | '.join(x['passage_id'] for x in top[:10]),'top10_titles':' | '.join(x['title'] for x in top[:10])})
 schedule=[{'scientific_id':p['scientific_id'],'item_id':p['item_id'],'prompt_sha256':p['prompt_sha256']} for p in prompts]
 schedule.sort(key=lambda x:rank(CFG['seed'],split+':schedule',x['scientific_id']))
 for i,x in enumerate(schedule):x['schedule_index']=i
 return rows,csvrows,prompts,schedule

def summarize(rows,docs):
 ranks=[r[x] for r in rows for x in ('support_a_rank','support_b_rank')]
 cats=Counter(r['retrieval_category'] for r in rows)
 cut={}
 for k in CFG['descriptive_cutoffs']:
  recalled=sum(r[f'support_a_at_{k}']+r[f'support_b_at_{k}'] for r in rows)
  cut[str(k)]={'support_documents_recalled':recalled,'support_document_recall':recalled/(2*len(rows)),
    'questions_with_both':sum(r[f'both_at_{k}'] for r in rows),'questions_with_both_percent':100*sum(r[f'both_at_{k}'] for r in rows)/len(rows)}
 sr=sorted(ranks)
 return {'n_questions':len(rows),'n_corpus_documents':len(docs),'primary_top_k':CFG['primary_top_k'],
  'categories':{k:{'count':cats[k],'percent':100*cats[k]/len(rows)} for k in ('complete','partial','failed')},
  'recall_by_cutoff':cut,'support_rank_statistics':{'minimum':min(ranks),'median':median(ranks),'mean':statistics.mean(ranks),
   'p75':sr[math.ceil(.75*len(sr))-1],'p90':sr[math.ceil(.90*len(sr))-1],'maximum':max(ranks)},
  'ambiguous_normalized_title_matches':sum(any('normalization_collision' in x for x in r['support_match_flags']) for r in rows),
  'support_matches_with_merged_text_variants':sum(any('merged_text_variants' in x for x in r['support_match_flags']) for r in rows)}

def prepare(root=ROOT,out=OUT):
 source=root/CFG['corpus_source'];records=json.loads(source.read_text(encoding='utf-8'))
 docs=build_shared_dev_corpus(records);engine=BM25(docs,CFG['bm25']['k1'],CFG['bm25']['b'])
 main=read_jsonl(root/'outputs/main_manifest.jsonl');pilot=read_jsonl(root/'outputs/pilot_manifest.jsonl')
 require(len(main)==200 and len(pilot)==10,'Study 1 manifest sizes changed')
 require(not ({x['item_id'] for x in main}&{x['item_id'] for x in pilot}),'Pilot/main overlap')
 mainrows,maincsv,mainprompts,mainsched=build_split(main,engine,docs,'main')
 pilotrows,pilotcsv,pilotprompts,pilotsched=build_split(pilot,engine,docs,'pilot')
 summary=summarize(mainrows,docs)
 corpusprov={'dataset':'HotpotQA development distractor split','source_path':CFG['corpus_source'],'source_sha256':file_hash(source),
  'source_records':len(records),'source_context_entries':sum(len(x.get('context',[])) for x in records),
  'corpus_construction':'Pool every context page across all 7,405 dev records; normalize titles; merge exact text variants; one page unit per normalized title.',
  'corpus_documents':len(docs),'logical_corpus_sha256':logical_hash(docs),
  'raw_unique_titles':len({p[0] for x in records for p in x.get('context',[])}),
  'normalized_title_units':len(docs),'units_with_multiple_text_variants':sum(d['source_variant_count']>1 for d in docs),
  'normalization_collisions':sum(d['distinct_raw_title_count']>1 for d in docs),
  'license':'CC BY-SA 4.0 (HotpotQA distribution)','limitation':'Shared development-derived page pool, not the official 2017 FullWiki corpus. Every dev question contributes its support pages and distractors, so open-domain recall may be optimistic.'}
 write_json(out/'corpus_provenance.json',corpusprov)
 write_jsonl(out/'retrieval_manifest.jsonl',mainrows);write_csv(out/'retrieval_results.csv',maincsv);write_json(out/'retrieval_summary.json',summary)
 write_jsonl(out/'prompt_manifest.jsonl',mainprompts);write_jsonl(out/'main_schedule.jsonl',mainsched)
 write_jsonl(out/'pilot_retrieval_manifest.jsonl',pilotrows);write_jsonl(out/'pilot_prompt_manifest.jsonl',pilotprompts);write_jsonl(out/'pilot_schedule.jsonl',pilotsched)
 # No-gold/support-label leakage: prompt rows contain only scientific metadata, retrieval titles/IDs and exact prompt.
 for p in mainprompts+pilotprompts:
  require('support_a' not in p['prompt'].lower() and 'support_b' not in p['prompt'].lower(),'Support label leak')
  require('focus=' not in p['prompt'].lower(),'Study 1 focus flag leaked')
  require(p['prompt_utf8_bytes']<=CFG['prompt_utf8_byte_limit'],'Prompt byte limit exceeded')
 write_json(out/'offline_preparation.json',{'status':'PASS','main_items':200,'pilot_items':10,'main_prompts':200,'pilot_prompts':10,
  'main_pilot_overlap':0,'max_main_prompt_bytes':max(p['prompt_utf8_bytes'] for p in mainprompts),
  'max_pilot_prompt_bytes':max(p['prompt_utf8_bytes'] for p in pilotprompts)})
 audit=f'''# Study 2 retrieval audit\n\n**Status:** deterministic retrieval preparation complete.\n\n## Corpus\n\nThe corpus is a shared pool of all page-introduction contexts present anywhere in the locally pinned HotpotQA development distractor split. It contains **{len(docs):,} page units** derived from {corpusprov['source_context_entries']:,} context entries. It is not per-question reranking and is not the official FullWiki corpus. The latter is absent locally and is approximately 1.55 GB compressed according to the official HotpotQA documentation.\n\nPages are keyed by Unicode-NFKC, case-folded, whitespace-normalized title. Repeated versions of a title are merged deterministically sentence-by-sentence; {corpusprov['units_with_multiple_text_variants']} units contain multiple text variants. The source hash is `{corpusprov['source_sha256']}` and the logical corpus hash is `{corpusprov['logical_corpus_sha256']}`.\n\n## Retriever\n\nBM25 uses k1=1.2 and b=0.75 over the page title plus paragraph text, with Unicode word tokenization, no stemming and no stopword removal. Ties are resolved by stable passage ID. The primary generator context is frozen at **top-10**; recall at 1/2/5/10/20 is descriptive.\n\n## Retrieval coverage for the 200 Study 1 MAIN questions\n\n- Complete annotated-support retrieval: **{summary['categories']['complete']['count']}/200 ({summary['categories']['complete']['percent']:.1f}%)**\n- Partial retrieval: **{summary['categories']['partial']['count']}/200 ({summary['categories']['partial']['percent']:.1f}%)**\n- Failed retrieval: **{summary['categories']['failed']['count']}/200 ({summary['categories']['failed']['percent']:.1f}%)**\n\nSupport-document recall: {', '.join(f'R@{k}={v["support_document_recall"]:.3f}' for k,v in summary['recall_by_cutoff'].items())}. Support ranks have median {summary['support_rank_statistics']['median']}, mean {summary['support_rank_statistics']['mean']:.1f}, p90 {summary['support_rank_statistics']['p90']}, and maximum {summary['support_rank_statistics']['maximum']}.\n\nNormalized-title matching produced {summary['ambiguous_normalized_title_matches']} ambiguous collision cases among the 200 questions. {summary['support_matches_with_merged_text_variants']} question-level support matches use a deterministically merged multi-variant page. These are flagged in the manifest.\n\n## Limitation\n\nThis is an actual shared-corpus retrieval pipeline, but the corpus is development-derived rather than unrestricted Wikipedia. Because every development item contributes its annotated pages to the shared pool, results should be described as retrieval over a pooled HotpotQA development corpus and not as FullWiki retrieval.\n'''
 (out/'RETRIEVAL_AUDIT.md').write_text(audit,encoding='utf-8')
 write_json(out/'configuration.unfrozen.json',CFG)
 print(json.dumps(summary,indent=2))
 return summary

if __name__=='__main__':prepare()
