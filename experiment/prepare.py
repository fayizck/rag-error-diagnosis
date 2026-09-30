"""Download official data, log exclusions, and record prospective samples."""
import argparse
import json
from collections import Counter
from pathlib import Path
from urllib.request import urlopen
from .common import ROOT, CONDITIONS, atomic_json, config, digest, file_hash, now, ranked, read_json, require, write_jsonl_once
from .prompts import eligibility, make_item, manifest_item, schedule, render

SCORER_URL = 'https://raw.githubusercontent.com/hotpotqa/hotpot/master/hotpot_evaluate_v1.py'

def prepare(root=ROOT, fallback=False):
    cfg = config(root)
    out = root / 'outputs'; out.mkdir(exist_ok=True)
    existing = None
    if (out / 'preparation.json').exists():
        from .validate import validate_prepared
        existing = read_json(out / 'preparation.json')
        if (root/cfg['dataset_path']).exists():
            validate_prepared(root)
            return existing
        # Restore an omitted local cache using its already recorded source, without resampling.
        fallback = bool(existing['dataset_provenance'].get('revision'))
    path = root / cfg['dataset_path']; path.parent.mkdir(parents=True, exist_ok=True)
    download = path.with_suffix('.download.json')
    if not path.exists():
        url = cfg['dataset_fallback_url'] if fallback else cfg['dataset_url']
        with urlopen(url, timeout=60) as response:
            payload = response.read(); resolved_url = response.url
        extra = {}
        if fallback:
            import pyarrow.parquet as pq
            parquet = path.parent/'hotpot_distractor_validation.parquet'
            parquet.write_bytes(payload)
            original = pq.read_table(parquet).to_pylist()
            converted = []
            for row in original:
                context, facts = row['context'], row['supporting_facts']
                require(len(context['title']) == len(context['sentences']), 'Mismatched context arrays in Parquet')
                require(len(facts['title']) == len(facts['sent_id']), 'Mismatched support arrays in Parquet')
                converted.append({'_id': row['id'], 'question': row['question'], 'answer': row['answer'],
                    'type': row['type'], 'level': row['level'],
                    'context': [list(x) for x in zip(context['title'], context['sentences'])],
                    'supporting_facts': [list(x) for x in zip(facts['title'], facts['sent_id'])]})
            payload = json.dumps(converted, ensure_ascii=False).encode()
            extra = {'fallback_reason': 'Original CMU HTTPS and HTTP endpoints timed out during preparation',
                     'repository': 'https://huggingface.co/datasets/hotpotqa/hotpot_qa',
                     'revision': cfg['dataset_fallback_revision'], 'downloaded_filename': parquet.name,
                     'downloaded_file_sha256': file_hash(parquet),
                     'conversion': 'id renamed _id; parallel context/support arrays zipped in order. No string edits.'}
        # A bad response must never become the dataset cache.
        require(isinstance(json.loads(payload), list), 'Dataset response is not a JSON list')
        path.write_bytes(payload)
        atomic_json(download, {'requested_url': url, 'resolved_url': resolved_url.split('?')[0],
                             'accessed_at': now(), 'sha256': file_hash(path), **extra})
    require(download.exists(), 'Existing dataset cache has no provenance; refuse undocumented input')
    require(file_hash(path) == read_json(download)['sha256'], 'Dataset cache changed')
    if existing is not None:
        validate_prepared(root)
        print('Restored the frozen dataset cache; existing manifests and IDs preserved.')
        return existing
    source = root / 'data/reference/hotpot_evaluate_v1.py'
    source.parent.mkdir(parents=True, exist_ok=True)
    if not source.exists():
        with urlopen(SCORER_URL, timeout=60) as response: source.write_bytes(response.read())
    records = read_json(path)
    ids = [r.get('_id') for r in records]
    require(len(ids) == len(set(ids)), 'Duplicate dataset IDs; no silent deduplication')
    excluded, eligible, population = [], [], []
    counts = Counter()
    for record in records:
        errors = eligibility(record, cfg)
        if errors:
            excluded.append({'item_id': record.get('_id'), 'rules': errors})
            counts.update(errors)
        else:
            item = manifest_item(make_item(record, cfg['seed']))
            eligible.append(item)
            population.append({'item_id': item['item_id'], 'source_record_sha256': item['source_record_sha256'],
                               'paragraph_count': 10, 'sentence_count': sum(len(ss) for _, ss in item['context']),
                               'support_titles': sorted({t for t, _ in item['supporting_facts']}),
                               'support_fact_count': len(item['supporting_facts']),
                               'max_prompt_utf8_bytes': max(len(render(item, c).encode()) for c in CONDITIONS)})
    write_jsonl_once(out / 'exclusions.jsonl', excluded)
    write_jsonl_once(out / 'frozen_population.jsonl', population)
    eligible.sort(key=lambda r: ranked(cfg['seed'], 'sample', r['item_id']))
    require(len(eligible) >= cfg['pilot_size'] + cfg['main_size'], 'Insufficient eligible population')
    pilot = eligible[:cfg['pilot_size']]
    main = eligible[cfg['pilot_size']:cfg['pilot_size'] + cfg['main_size']]
    for split, items in [('pilot', pilot), ('main', main)]:
        write_jsonl_once(out / f'{split}_manifest.jsonl', items)
        write_jsonl_once(out / f'{split}_schedule.jsonl', schedule(items, cfg['seed'], split))
    manual = sorted(main, key=lambda r: ranked(cfg['seed'], 'manual-main-input', r['item_id']))[:10]
    atomic_json(out / 'manual_input_plan.json', {'pilot_ids': [r['item_id'] for r in pilot],
                'main_ids': [r['item_id'] for r in manual], 'seed': cfg['seed']}, exclusive=True)
    paths = [cfg['dataset_path'], 'config/study.json', 'data/reference/hotpot_evaluate_v1.py',
             'outputs/exclusions.jsonl', 'outputs/frozen_population.jsonl', 'outputs/manual_input_plan.json']
    paths += [f'outputs/{split}_{kind}.jsonl' for split in ('pilot', 'main') for kind in ('manifest', 'schedule')]
    report = {'created_at': now(), 'dataset': 'HotpotQA', 'split': 'dev distractor', 'dataset_filename': path.name,
              'dataset_provenance': read_json(download), 'dataset_sha256': file_hash(path),
              'original_count': len(records), 'eligible_count': len(eligible), 'excluded_count': len(excluded),
              'excluded_by_rule_nonexclusive': dict(counts), 'seed': cfg['seed'],
              'pilot_ids': [r['item_id'] for r in pilot], 'main_ids': [r['item_id'] for r in main],
              'scorer_source_url': SCORER_URL, 'files': {p: file_hash(root / p) for p in paths}}
    atomic_json(out / 'preparation.json', report, exclusive=True)
    print(f"Prepared {len(eligible)}/{len(records)} eligible; pilot={len(pilot)}, main={len(main)}; seed={cfg['seed']}")
    return report

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--documented-fallback', action='store_true', help='Use pinned HotpotQA-named HF snapshot; record conversion and provenance')
    prepare(fallback=parser.parse_args().documented_fallback)
