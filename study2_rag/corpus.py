from __future__ import annotations
import json,hashlib
from collections import defaultdict
from .common import canonical,digest,normalize_title

def build_shared_dev_corpus(records):
 """One deterministic page unit per normalized title from all dev contexts.

 Text variants for the same title are merged sentence-by-sentence in variant-hash
 order. This prevents repeated titles occupying multiple ranks and retains facts
 found in any locally supplied version.
 """
 variants=defaultdict(dict)
 raw_titles=defaultdict(set)
 for rec in records:
  for title,sents in rec.get('context',[]):
   key=digest([title,sents]); variants[normalize_title(title)][key]=(title,sents);raw_titles[normalize_title(title)].add(title)
 docs=[]
 for nt,vs in variants.items():
  title=sorted(raw_titles[nt],key=lambda x:(normalize_title(x),x))[0]
  seen=set();sentences=[]
  for key in sorted(vs):
   for sentence in vs[key][1]:
    if sentence not in seen:seen.add(sentence);sentences.append(sentence)
  docs.append({'passage_id':'hpdev:'+hashlib.sha256(nt.encode()).hexdigest()[:20],
    'title':title,'normalized_title':nt,'text':' '.join(sentences),
    'source_variant_count':len(vs),'distinct_raw_title_count':len(raw_titles[nt])})
 docs.sort(key=lambda d:d['passage_id'])
 return docs

def logical_hash(docs):
 return digest([{'passage_id':d['passage_id'],'title':d['title'],'text':d['text']} for d in docs])
