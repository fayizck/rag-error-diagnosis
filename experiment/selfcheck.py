"""Offline output-schema/storage smoke test. Synthetic artifacts stay in a temporary directory."""
import argparse
import tempfile
from pathlib import Path
from .common import ROOT, read_jsonl, config, require
from .provider import parse_response, request_body
from .prompts import render
from .storage import Store

def exercise(root=ROOT):
    cfg=config(root)
    items={r['item_id']:r for r in read_jsonl(root/'outputs/main_manifest.jsonl')}
    schedule=read_jsonl(root/'outputs/main_schedule.jsonl')
    with tempfile.TemporaryDirectory(prefix='c2-synthetic-dry-run-') as tmp:
        store=Store(Path(tmp)/'synthetic.sqlite3')
        for row in schedule:
            prompt=render(items[row['item_id']],row['condition'])
            payload=request_body(prompt,cfg)
            require(set(payload)=={'contents','generationConfig'},'Unexpected API payload fields')
            parsed=parse_response({'candidates':[{'content':{'parts':[{'text':'SYNTHETIC TEST ONLY'}]},'finishReason':'STOP'}],
                                   'modelVersion':'synthetic','usageMetadata':{'totalTokenCount':10}})
            observation=dict(row,**parsed,attempt=1,latency_seconds=0,synthetic=True)
            store.start(row['scientific_id'],1,{'synthetic':True})
            store.commit(observation)
        require(len(store.observations())==len(schedule),'Dry-run commit count mismatch')
        store.close()
        store=Store(Path(tmp)/'synthetic.sqlite3')
        committed=store.observations()
        require(all(r['scientific_id'] in committed for r in schedule),'Resume lookup failed')
        store.close()
    return {'planned':len(schedule),'api_calls':0,'synthetic_artifacts_retained':False}

if __name__=='__main__':
    argparse.ArgumentParser(description=__doc__).parse_args()
    from .collector import dry_run
    print(dry_run(require_frozen=False))
