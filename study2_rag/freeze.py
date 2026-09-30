from __future__ import annotations
import json
from pathlib import Path
from .common import ROOT,OUT,CONFIG,canonical,digest,file_hash,read_json,require,write_json

PROTECTED_CODE=['study2_rag/__init__.py','study2_rag/common.py','study2_rag/corpus.py','study2_rag/bm25.py','study2_rag/prompts.py','study2_rag/scoring.py','study2_rag/prepare.py','study2_rag/freeze.py','study2_rag/collector.py','study2_rag/reconcile.py','study2_rag/analysis.py','study2_rag/cli.py','study2_rag/README.md','tests/test_study2_rag.py']
PROTECTED_ARTIFACTS=['outputs/main_manifest.jsonl','outputs/pilot_manifest.jsonl','data/cache/hotpot_dev_distractor_v1.json',
 'outputs/study2_rag/corpus_provenance.json','outputs/study2_rag/retrieval_manifest.jsonl','outputs/study2_rag/retrieval_results.csv','outputs/study2_rag/retrieval_summary.json','outputs/study2_rag/prompt_manifest.jsonl','outputs/study2_rag/main_schedule.jsonl','outputs/study2_rag/pilot_retrieval_manifest.jsonl','outputs/study2_rag/pilot_prompt_manifest.jsonl','outputs/study2_rag/pilot_schedule.jsonl','outputs/study2_rag/offline_preparation.json']

def build_freeze(root=ROOT):
 cfg=read_json(root/'outputs/study2_rag/configuration.unfrozen.json')
 for p in PROTECTED_CODE+PROTECTED_ARTIFACTS:require((root/p).is_file(),f'Missing protected file: {p}')
 corpus=read_json(root/'outputs/study2_rag/corpus_provenance.json');summary=read_json(root/'outputs/study2_rag/retrieval_summary.json')
 core={'schema_version':1,'status':'FROZEN_BEFORE_ANY_STUDY2_GENERATION','study':'study2_rag',
  'specified_after_study1':True,'main_generation_authorized':False,'configuration':cfg,
  'compatible_pilot_freeze_sha256':['7964ee4f53c248e38ab56d370d6cd624e5204c8fc42d61b61799f44db955b384'],
  'pilot_freeze_compatibility_basis':'The completed pilot used identical scientific prompts, retrieval, model settings, and protocol. The successor freeze changes only MAIN artifact filename resolution and its regression test.',
  'study1_freeze_sha256':read_json(root/'config/frozen_protocol.json')['freeze_sha256'],
  'study1_sealed_outputs_sha256':read_json(root/'outputs/main/sealed_outputs.json')['logical_outputs_sha256'],
  'corpus':corpus,'retrieval_summary':summary,
  'scientific_plan':{'main_items':200,'pilot_items':10,'main_scientific_requests':200,'primary_top_k':10,
   'primary_question':'Among questions with both annotated support documents in top-10, what proportion fail official HotpotQA EM?',
   'categories':['complete','partial','failed'],
   'analysis':'Overall/category EM and F1; complete-retrieval failure count; paired descriptive comparisons with Study 1 00/11; predeclared rank bins top2, top5-not2, top10-not5.',
   'no_oracle_highlighting':True,'no_answer_dependent_resampling':True,
   'invalid_output_handling':'Commit once without scientific retry; apply official EM/F1 to returned text (empty responses score zero); report response-integrity categories separately.'},
  'source_hashes':{p:file_hash(root/p) for p in PROTECTED_CODE},
  'artifact_hashes':{p:file_hash(root/p) for p in PROTECTED_ARTIFACTS}}
 freeze=dict(core,freeze_sha256=digest(core))
 write_json(root/'config/study2_rag_frozen_protocol.json',freeze)
 (root/'study2_rag/STUDY2_RAG_PROTOCOL_FREEZE.md').write_text(render_markdown(freeze),encoding='utf-8')
 return freeze

def render_markdown(f):
 c=f['configuration'];s=f['retrieval_summary'];return f'''# Study 2 RAG protocol record\n\n**Status:** Recorded before Study 2 collection.\n\n**Protocol SHA-256:** `{f['freeze_sha256']}`\n\n## Question and sample\n\nThe study reuses exactly the 200 sealed Study 1 MAIN question IDs. It asks: among questions for which BM25 retrieves both human-annotated support documents within a fixed top-10 context, what proportion still fail official HotpotQA exact match? All 200 questions are collected; partial and failed retrieval cases are not discarded. A disjoint ten-item Study 1 pilot set is reserved for technical validation.\n\n## Corpus and retrieval\n\nThe shared corpus contains {f['corpus']['corpus_documents']:,} page units pooled from the pinned 7,405-record HotpotQA development distractor cache. It is a shared retrieval corpus, not per-question reranking, but it is not official FullWiki and must be described as development-derived. Corpus logical hash: `{f['corpus']['logical_corpus_sha256']}`.\n\nBM25: k1={c['bm25']['k1']}, b={c['bm25']['b']}; query is question text only; document is title once plus paragraph text; NFKC/casefold Unicode word tokens; no stemming or stopword removal; passage-ID tie break. Primary top-k: **{c['primary_top_k']}**.\n\nRecorded retrieval coverage: complete {s['categories']['complete']['count']}/200, partial {s['categories']['partial']['count']}/200, failed {s['categories']['failed']['count']}/200. These are descriptive retrieval results obtained before Study 2 collection.\n\n## Reader\n\nModel `{c['model']}` with the same Study 1 settings: temperature 0, one candidate, maxOutputTokens 2048, text/plain, thinking level MINIMAL, thoughts excluded, no tools/grounding. The reader sees only the question and the fixed top-10 titles/texts. It receives no gold answer, support labels, retrieval category, Study 1 outputs, focus flags, or scores.\n\n## Collection and scoring\n\nScientific ID `<item_id>::rag`. One fresh request per question. Append-only SQLite attempts and immutable commits; up to three attempts only for the recorded transient transport/HTTP classes; no answer-based retry. Official HotpotQA answer EM/F1 is reused unchanged. Invalid, empty, refused, or truncated scientific responses are committed once, never resampled, scored on their returned text for whole-pipeline performance, and reported separately by integrity category. The technical pilot verified the model configuration and storage path before the main collection. The stored manifests and reconciliation report document the completed collection.\n\n## Analysis\n\nPrimary descriptive quantity: EM failures among complete top-10 annotated-support retrieval cases. Report overall and retrieval-category EM/F1, ranks/recall, deterministic output-context relationships, and paired descriptive transitions against sealed Study 1 conditions 00 and 11. Rank bins are both supports top-2, both top-5 but not both top-2, and both top-10 but not both top-5. No significance search or semantic LLM judge.\n\n## Protected hashes\n\nThe machine-readable protocol records every protected source and artifact hash. The release verifier checks published files against `release_manifest.json`. Study 1 protocol `{f['study1_freeze_sha256']}` and sealed-output fingerprint `{f['study1_sealed_outputs_sha256']}` are references only and remain untouched.\n'''

def verify_freeze(root=ROOT):
 f=read_json(root/'config/study2_rag_frozen_protocol.json');want=f['freeze_sha256'];core={k:v for k,v in f.items() if k!='freeze_sha256'}
 require(digest(core)==want,'Study 2 freeze self-hash mismatch')
 for p,h in f['source_hashes'].items():require(file_hash(root/p)==h,f'Study 2 source changed: {p}')
 for p,h in f['artifact_hashes'].items():require(file_hash(root/p)==h,f'Study 2 artifact changed: {p}')
 s1=read_json(root/'config/frozen_protocol.json');seal=read_json(root/'outputs/main/sealed_outputs.json')
 require(s1['freeze_sha256']==f['study1_freeze_sha256'],'Study 1 freeze changed')
 require(seal['logical_outputs_sha256']==f['study1_sealed_outputs_sha256'],'Study 1 seal changed')
 return f

if __name__=='__main__':print(build_freeze()['freeze_sha256'])
