from __future__ import annotations
import math
from collections import Counter,defaultdict
from .common import tokenize,require

class BM25:
 def __init__(self,docs,k1=1.2,b=0.75):
  require(docs,'Empty corpus');self.docs=docs;self.k1=float(k1);self.b=float(b)
  self.postings=defaultdict(list);self.length=[]
  for i,d in enumerate(docs):
   counts=Counter(tokenize(d['title']+' '+d['text']));self.length.append(sum(counts.values()))
   for term,tf in counts.items():self.postings[term].append((i,tf))
  self.n=len(docs);self.avgdl=sum(self.length)/self.n
  self.idf={t:math.log(1+(self.n-len(p)+.5)/(len(p)+.5)) for t,p in self.postings.items()}
  self.by_title={d['normalized_title']:i for i,d in enumerate(docs)}
  require(len(self.by_title)==len(docs),'Corpus normalized titles are not unique')
 def score(self,query):
  out=defaultdict(float)
  for term in set(tokenize(query)):
   for i,tf in self.postings.get(term,()):
    out[i]+=self.idf[term]*(tf*(self.k1+1))/(tf+self.k1*(1-self.b+self.b*self.length[i]/self.avgdl))
  return out
 def top(self,scores,k):
  positive=[i for i,s in scores.items() if s>0]
  positive.sort(key=lambda i:(-scores[i],self.docs[i]['passage_id']))
  if len(positive)>=k:return positive[:k]
  used=set(positive);zeros=[i for i,d in enumerate(self.docs) if i not in used]
  zeros.sort(key=lambda i:self.docs[i]['passage_id'])
  return (positive+zeros)[:k]
 def exact_rank(self,scores,index):
  score=scores.get(index,0.0);pid=self.docs[index]['passage_id']
  higher=sum(v>score for v in scores.values())
  if score>0:
   tied=sum(v==score and self.docs[i]['passage_id']<pid for i,v in scores.items())
  else:
   positive={i for i,v in scores.items() if v>0}
   tied=sum(i not in positive and d['passage_id']<pid for i,d in enumerate(self.docs))
  return 1+higher+tied
