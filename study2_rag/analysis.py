from __future__ import annotations
import csv,json,re,string,statistics
from collections import Counter,defaultdict
from experiment.storage import Store
from .common import ROOT,normalize_title,read_json,read_jsonl,require,write_csv,write_json
from .freeze import verify_freeze
from .reconcile import reconcile
from .scoring import normalize_answer

def phrase_in(a,b):
 a=normalize_answer(a);b=normalize_answer(b)
 return bool(a and re.search(r'(?:^|\\s)'+re.escape(a)+r'(?:$|\\s)',b))
def mean(xs):return sum(xs)/len(xs) if xs else None

def analyze(root=ROOT):
 frozen=verify_freeze(root);seal=read_json(root/'outputs/study2_rag/main/sealed_outputs.json');r=reconcile('main',root)
 require(r['technical_pass'] and seal['logical_fingerprint']==r['logical_fingerprint'],'Unsealed or unreconciled MAIN')
 store=Store(root/'outputs/study2_rag/main/collection.sqlite3',readonly=True)
 try:obs=store.observations()
 finally:store.close()
 retrieval={x['item_id']:x for x in read_jsonl(root/'outputs/study2_rag/retrieval_manifest.jsonl')}
 study1=list(csv.DictReader((root/'outputs/analysis/item_level_results.csv').open()))
 s1={x['item_id']:x for x in study1};rows=[]
 for iid,m in retrieval.items():
  o=obs[iid+'::rag'];top=m['top_20'][:10];support={normalize_title(m['group_a']),normalize_title(m['group_b'])}
  sup=' '.join(x['title']+' '+x['text'] for x in top if x['normalized_title'] in support)
  nonsup=' '.join(x['title']+' '+x['text'] for x in top if x['normalized_title'] not in support)
  answer=o['answer'];gold=m['answer']
  if o['em']==1:relation='official_em_correct'
  elif phrase_in(gold,answer):relation='gold_embedded_extra_material'
  elif phrase_in(answer,gold):relation='partial_gold_string'
  else:
   ins=phrase_in(answer,sup);ind=phrase_in(answer,nonsup)
   relation='support_and_non_support_associated' if ins and ind else 'support_associated' if ins else 'non_support_associated' if ind else 'lexically_unmatched'
  b=max(m['support_a_rank'],m['support_b_rank'])
  rankbin='both_top2' if b<=2 else 'both_top5_not2' if b<=5 else 'both_top10_not5' if b<=10 else 'not_complete_top10'
  a=s1[iid]
  rows.append({'item_id':iid,'retrieval_category':m['retrieval_category'],'support_a_rank':m['support_a_rank'],'support_b_rank':m['support_b_rank'],'rank_bin':rankbin,
   'rag_answer':answer,'rag_em':o['em'],'rag_f1':o['f1'],'failure_relationship':relation,
   'study1_00_answer':a['00_answer'],'study1_00_em':int(a['00_em']),'study1_00_f1':float(a['00_f1']),
   'study1_11_answer':a['11_answer'],'study1_11_em':int(a['11_em']),'study1_11_f1':float(a['11_f1'])})
 out=root/'outputs/study2_rag/analysis';out.mkdir(parents=True,exist_ok=True);write_csv(out/'item_results.csv',rows)
 cat=[]
 for c in ('complete','partial','failed','overall'):
  z=rows if c=='overall' else [x for x in rows if x['retrieval_category']==c]
  cat.append({'retrieval_category':c,'n':len(z),'em_correct':sum(x['rag_em'] for x in z),'em':mean([x['rag_em'] for x in z]),'mean_f1':mean([x['rag_f1'] for x in z]),'em_failures':sum(not x['rag_em'] for x in z)})
 write_csv(out/'category_results.csv',cat)
 transitions=[]
 for base in ('00','11'):
  co=Counter(('correct' if x[f'study1_{base}_em'] else 'wrong')+'_to_'+('correct' if x['rag_em'] else 'wrong') for x in rows)
  transitions.append({'study1_condition':base,**co})
 write_csv(out/'study1_transitions.csv',transitions)
 rb=[]
 for b in ('both_top2','both_top5_not2','both_top10_not5'):
  z=[x for x in rows if x['rank_bin']==b];rb.append({'rank_bin':b,'n':len(z),'em_correct':sum(x['rag_em'] for x in z),'em':mean([x['rag_em'] for x in z]),'mean_f1':mean([x['rag_f1'] for x in z])})
 write_csv(out/'rank_bin_results.csv',rb)
 complete=[x for x in rows if x['retrieval_category']=='complete'];fails=[x for x in complete if not x['rag_em']]
 rel=Counter(x['failure_relationship'] for x in fails)
 integrity=Counter(x['status'] for x in obs.values())
 summary={'freeze_sha256':frozen['freeze_sha256'],'n':len(rows),'category_results':cat,'study1_transitions':transitions,'rank_bins':rb,
  'complete_retrieval_failures':len(fails),'complete_failure_relationships':dict(rel),'response_integrity':dict(integrity),'post_hoc_descriptive':True}
 write_json(out/'summary.json',summary)
 report=f'''# Study 2 RAG results\n\nStudy 2 used the frozen shared-corpus BM25 rankings and the sealed reader outputs. Overall/category EM and F1 are descriptive.\n\nComplete retrieval: {len(complete)}/200; official-EM failures among complete retrieval: {len(fails)}/{len(complete)} ({100*len(fails)/len(complete):.1f}%).\n\nCategory results and paired Study 1 transitions are in the accompanying CSV files. Failure relationships use deterministic normalized phrase matching only and do not identify internal reasoning causes.\n'''
 (out/'STUDY2_RESULTS.md').write_text(report,encoding='utf-8')
 return summary
