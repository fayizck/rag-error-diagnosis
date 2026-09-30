"""Main analysis only. Requires a verified protocol and sealed, reconciled main outputs."""
import argparse
import csv
import json
from experiment.common import ROOT, CONDITIONS, atomic_json, config, file_hash, read_json, read_jsonl, require, ranked, now
from experiment.freeze import verify_freeze
from experiment.storage import Store, process_lock
from .reconcile import reconcile
from .stats import paired_summary

def csv_write(path, rows, fields=None):
    fields = fields or list(rows[0])
    with path.open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(rows)

def analyze(root=ROOT, allow_missing=False):
    cfg = config(root); frozen = verify_freeze(root)
    seal = read_json(root/'outputs/main/sealed_outputs.json')
    require(seal['freeze_sha256'] == frozen['freeze_sha256'], 'Seal belongs to another protocol')
    r = reconcile('main', root)
    require(r['integrity_passed'] and r['all_planned_accounted'], f'Integrity/accounting failure: {r["integrity_errors"]}')
    require(r['logical_outputs_sha256'] == seal['logical_outputs_sha256'], 'Committed outputs changed after sealing')
    require(allow_missing or r['complete_valid_questions'] == cfg['main_size'],
            'Incomplete/invalid blocks: inspect reconciliation; --allow-missing explicitly enables prespecified complete-block analysis')
    store = Store(root/'outputs/main/collection.sqlite3', readonly=True)
    try: obs = store.observations()
    finally: store.close()
    manifest = read_jsonl(root/'outputs/main_manifest.jsonl')
    complete = [item for item in manifest if all(obs.get(item['item_id']+'::'+c, {}).get('status')=='valid' for c in CONDITIONS)]
    y = [[obs[item['item_id']+'::'+c]['em'] for c in CONDITIONS] for item in complete]
    f1 = [[obs[item['item_id']+'::'+c]['f1'] for c in CONDITIONS] for item in complete]
    conditions, contrasts = paired_summary(y, cfg['seed'], cfg['bootstrap_resamples'])
    f1_conditions, f1_contrasts = paired_summary(f1, cfg['seed'], cfg['bootstrap_resamples'])
    for row in contrasts: row['outcome'] = 'EM'
    for row in f1_contrasts: row.update(outcome='F1', status='exploratory_secondary')
    for row, f in zip(conditions, f1_conditions):
        c = row['condition']
        row.update(mean_f1=f['estimate'], f1_ci_low=f['ci_low'], f1_ci_high=f['ci_high'], planned=cfg['main_size'],
                   committed=r['per_condition'][c]['committed'], valid_outputs=r['per_condition'][c]['valid'],
                   technical_failures=sum(sid.endswith('::'+c) for sid in r['terminal_failures']))
    item_rows = []
    for item in manifest:
        row = {'item_id': item['item_id'], 'complete_valid_block': item in complete}
        for c in CONDITIONS:
            o = obs.get(item['item_id']+'::'+c, {})
            row.update({f'{c}_status': o.get('status','technical_failure'), f'{c}_answer': o.get('answer',''),
                        f'{c}_normalized_prediction':o.get('normalized_prediction',''),
                        f'{c}_normalized_gold':o.get('normalized_gold',''), f'{c}_em':o.get('em'), f'{c}_f1':o.get('f1')})
        item_rows.append(row)
    transitions = []
    for c in ('10','01','11'):
        j = CONDITIONS.index(c)
        counts = {(a,b):sum(v[0]==a and v[j]==b for v in y) for a in (0,1) for b in (0,1)}
        transitions.append({'condition':c, 'n':len(y), 'repair':counts[0,1], 'harm':counts[1,0],
                            'both_wrong':counts[0,0], 'both_correct':counts[1,1]})
    # Predeclared categories partition complete blocks. At most five per stratum, <=20 cases.
    strata = {x:[] for x in ('any_harm','repair_without_harm','unchanged_correctness_answer_switch','no_answer_switch')}
    for item in complete:
        records = [obs[item['item_id']+'::'+c] for c in CONDITIONS]
        base = records[0]['em']
        if base == 1 and any(v['em']==0 for v in records[1:]): category = 'any_harm'
        elif base == 0 and any(v['em']==1 for v in records[1:]): category = 'repair_without_harm'
        elif len({v['normalized_prediction'] for v in records}) > 1: category = 'unchanged_correctness_answer_switch'
        else: category = 'no_answer_switch'
        strata[category].append(item['item_id'])
    validation = []
    examples = []
    for category, ids in strata.items():
        chosen = sorted(ids, key=lambda i: ranked(cfg['seed'],'post-validation:'+category,i))[:5]
        validation += [{'item_id':i,'stratum':category} for i in chosen]
        if chosen and len(examples)<3: examples.append({'item_id':chosen[0],'stratum':category})
    out = root/'outputs/analysis'; out.mkdir(parents=True, exist_ok=True)
    csv_write(out/'item_level_results.csv', item_rows)
    csv_write(out/'condition_results.csv', conditions)
    csv_write(out/'contrasts.csv', contrasts+f1_contrasts)
    csv_write(out/'transitions.csv', transitions)
    atomic_json(out/'validation_sample.json', {'selection_rule':'five hash-ranked cases per prespecified disjoint stratum; no backfill',
                                              'cases':validation,'illustrative_examples':examples})
    summary = {'created_at':now(), 'split':'main', 'freeze_sha256':frozen['freeze_sha256'],
               'sealed_outputs_sha256':seal['logical_outputs_sha256'], 'n_planned':cfg['main_size'], 'n_complete':len(y),
               'excluded_incomplete_blocks':cfg['main_size']-len(y), 'analysis_population':'complete valid four-response blocks',
               'missingness_warning': 'Validity-conditioned estimates may be biased if output integrity depends on condition.' if len(y)<cfg['main_size'] else None,
               'bootstrap':{'seed':cfg['seed'],'resamples':cfg['bootstrap_resamples'],'unit':'question','interval':'percentile 95%'},
               'condition_results':conditions, 'contrasts':contrasts+f1_contrasts, 'transitions':transitions,
               'response_integrity':r['response_integrity'], 'validation_sample':validation,'examples':examples}
    atomic_json(out/'summary.json', summary)
    from .figures import create_exhibits
    create_exhibits(summary, out)
    # Check immutable snapshot again after writing outputs.
    store = Store(root/'outputs/main/collection.sqlite3', readonly=True)
    try: require(store.fingerprint()==seal['logical_outputs_sha256'], 'Output mutation during analysis')
    finally: store.close()
    print(f'Analyzed {len(y)} complete questions from sealed MAIN outputs. Files: {out}')

if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--allow-missing',action='store_true')
    args=parser.parse_args()
    with process_lock(ROOT/'outputs/main'): analyze(allow_missing=args.allow_missing)
