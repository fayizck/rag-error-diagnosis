"""Reconcile scientific IDs, immutable commits, attempts and frozen inputs."""
import argparse
from collections import Counter
import statistics
from experiment.common import ROOT, CONDITIONS, atomic_json, config, digest, file_hash, now, read_json, read_jsonl, require
from experiment.storage import Store, process_lock
from experiment.prompts import render
from experiment.scoring import score
from experiment.validate import validate_prepared

def reconcile(split='main', root=ROOT, check_freeze=True):
    validate_prepared(root)
    cfg = config(root)
    items = {r['item_id']: r for r in read_jsonl(root / f'outputs/{split}_manifest.jsonl')}
    schedule = read_jsonl(root / f'outputs/{split}_schedule.jsonl')
    planned = {r['scientific_id']: r for r in schedule}
    errors = []
    frozen = None
    if split == 'main' and check_freeze:
        from experiment.freeze import verify_freeze
        frozen = verify_freeze(root)
    path = root / f'outputs/{split}/collection.sqlite3'
    obs, events, fingerprint = {}, [], None
    if path.exists():
        store = Store(path, readonly=True)
        try: obs, events, fingerprint = store.observations(), store.events(), store.fingerprint()
        finally: store.close()
    unexpected = set(obs) - set(planned)
    if unexpected: errors.append('unexpected committed scientific IDs')
    starts = [e for e in events if e['kind'] == 'start']
    finishes = [e for e in events if e['kind'] == 'finish']
    keys = [(e['scientific_id'], e['attempt'], e['kind']) for e in events]
    duplicates = len(keys) - len(set(keys))
    if duplicates: errors.append('duplicate attempt events')
    start_keys = {(e['scientific_id'], e['attempt']) for e in starts}
    finish_keys = {(e['scientific_id'], e['attempt']) for e in finishes}
    if finish_keys - start_keys: errors.append('finish without start')
    inflight = start_keys - finish_keys
    if inflight: errors.append('unfinished/ambiguous attempts; resume collector to record interruptions')
    terminal = {e['scientific_id'] for e in finishes if e.get('terminal')}
    count_starts = Counter(e['scientific_id'] for e in starts)
    for sid, n in count_starts.items():
        seq = sorted(e['attempt'] for e in starts if e['scientific_id'] == sid)
        if seq != list(range(1, n+1)) or n > cfg['retry_policy']['max_attempts']: errors.append(f'invalid attempt sequence: {sid}')
    for e in events:
        if e['scientific_id'] not in planned: errors.append('attempt outside frozen manifest')
    for sid, record in obs.items():
        if sid not in planned: continue
        row = planned[sid]
        for key in ('item_id', 'condition', 'prompt_sha256', 'schedule_index'):
            if record.get(key) != row[key]: errors.append(f'observation {key} mismatch: {sid}')
        if record.get('split') != split or record.get('config_sha256') != digest(cfg): errors.append(f'configuration/split mismatch: {sid}')
        if record.get('requested_model') != cfg['model'] or record.get('generation_config') != cfg['generation_config']:
            errors.append(f'model/settings mismatch: {sid}')
        if record.get('model_version_mismatch'): errors.append(f'provider version changed: {sid}')
        if frozen and record.get('protocol_identity') != frozen['freeze_sha256']: errors.append(f'freeze identity mismatch: {sid}')
        if record.get('status') == 'valid' and any(record[k] != v for k, v in score(record['answer'], items[row['item_id']]['answer']).items()):
            errors.append(f'scoring mismatch: {sid}')
        if record.get('status') != 'valid' and (record.get('em') is not None or record.get('f1') is not None):
            errors.append(f'invalid output silently scored: {sid}')
        end = [e for e in finishes if e['scientific_id'] == sid and e['attempt'] == record['attempt']]
        if len(end) != 1 or end[0].get('observation_sha256') != digest(record): errors.append(f'commit/event mismatch: {sid}')
        if any(e['attempt'] > record['attempt'] for e in starts if e['scientific_id'] == sid): errors.append(f'unexpected regeneration: {sid}')
    # Every retry must follow an explicitly retryable technical failure.
    for e in starts:
        if e['attempt'] > 1:
            previous = [f for f in finishes if f['scientific_id'] == e['scientific_id'] and f['attempt'] == e['attempt']-1]
            if len(previous) != 1 or not previous[0].get('retryable') or previous[0].get('terminal'):
                errors.append(f'nontechnical retry: {e["scientific_id"]}')
    versions = sorted({r.get('returned_model_version') or '<not exposed>' for r in obs.values()})
    if len(versions) > 1: errors.append('multiple returned model versions')
    if frozen and obs and versions != [frozen['returned_model_version'] or '<not exposed>']: errors.append('version differs from pilot freeze')
    if split == 'pilot' and obs:
        from experiment.collector import pilot_lock
        lock = read_json(root / 'outputs/pilot/run_lock.json')
        if lock != pilot_lock(root): errors.append('pilot code/config/token audit changed')
        if any(r['protocol_identity'] != digest(lock) for r in obs.values()): errors.append('mixed pilot protocol identities')
    per_item = {i: {'committed': sum(i+'::'+c in obs for c in CONDITIONS),
                    'valid': sum(obs.get(i+'::'+c, {}).get('status') == 'valid' for c in CONDITIONS)} for i in items}
    statuses = Counter(r['status'] for r in obs.values())
    terminal_fail = sorted(terminal - set(obs))
    missing = sorted(set(planned) - set(obs))
    latencies = [r['latency_seconds'] for r in obs.values()]
    result = {'split': split, 'checked_at': now(), 'planned': len(planned), 'committed': len(obs),
              'successful_calls': len(obs), 'valid_outputs': statuses.get('valid', 0),
              'missing_scientific_ids': missing, 'unexpected_scientific_ids': sorted(unexpected),
              'duplicate_scientific_ids': len(schedule)-len(planned), 'duplicate_commits': 0,
              'duplicate_attempt_events': duplicates, 'attempts': len(starts),
              'technical_retries': sum(e['attempt'] > 1 for e in starts),
              'technical_failure_attempts': sum('observation_sha256' not in e for e in finishes),
              'terminal_failures': terminal_fail, 'inflight_attempts': len(inflight),
              'unattempted': sorted(set(planned) - set(count_starts)),
              'per_condition': {c: {'planned': sum(r['condition']==c for r in schedule),
                                   'committed': sum(r['condition']==c for r in obs.values()),
                                   'valid': sum(r['condition']==c and r['status']=='valid' for r in obs.values())} for c in CONDITIONS},
              'per_item': per_item, 'complete_valid_questions': sum(v['valid']==4 for v in per_item.values()),
              'response_integrity': {s: statuses.get(s, 0) for s in ('valid','empty','malformed','refused','truncated')},
              'requested_model': cfg['model'], 'returned_model_versions': versions,
              'token_usage_totals': dict(sum((Counter({k:v for k,v in r.get('token_usage', {}).items() if isinstance(v, (int,float))})
                                            for r in obs.values()), Counter())),
              'total_tokens': sum(r.get('token_usage', {}).get('totalTokenCount',0) for r in obs.values()),
              'latency_seconds': {'median': statistics.median(latencies) if latencies else None,
                                  'mean': statistics.mean(latencies) if latencies else None,
                                  'max': max(latencies) if latencies else None},
              'integrity_errors': sorted(set(errors)), 'integrity_passed': not errors,
              'all_planned_accounted': set(planned) == set(obs) | set(terminal_fail),
              'logical_outputs_sha256': fingerprint, 'unexpected_regeneration': any('regeneration' in e for e in errors)}
    return result

def pilot_report(root=ROOT):
    r = reconcile('pilot', root, check_freeze=False)
    safe = r['integrity_passed'] and r['valid_outputs'] == 40 and r['committed'] == 40 and not r['terminal_failures']
    r['safe_to_freeze_technical'] = safe
    atomic_json(root / 'outputs/pilot_reconciliation.json', r)
    items = read_jsonl(root / 'outputs/pilot_manifest.jsonl')
    text = ['# Pilot technical validation\n', f"Status: {'TECHNICAL PASS' if safe else 'NOT READY'}; no experimental effects are interpreted.\n",
            f"Planned IDs: {r['planned']}; committed {r['committed']}; missing {len(r['missing_scientific_ids'])}; "
            f"valid {r['valid_outputs']}; attempts {r['attempts']}; retries {r['technical_retries']}; "
            f"terminal failures {len(r['terminal_failures'])}; duplicate commits {r['duplicate_commits']}.\n",
            f"Model: {r['requested_model']}; returned versions: {r['returned_model_versions'] or 'not yet observed'}.\n",
            f"Integrity: {r['response_integrity']}. Errors: {r['integrity_errors']}.\n",
            f"Tokens: {r['total_tokens']}; latency seconds: {r['latency_seconds']}.\n",
            'All 16 input invariants were validated for all 210 sampled items / 840 prompts.\n',
            'Scoring sanity: '+str(score('The Eiffel Tower.', 'Eiffel Tower'))+'\n',
            'Freeze additionally requires model/token preflight, passing tests, and recorded input review.\n',
            'Missing IDs:\n```text\n'+'\n'.join(r['missing_scientific_ids'])+'\n```\n',
            '## Four exact prompts from one pilot item\n']
    for c in CONDITIONS: text.append(f'### {c}\n```text\n{render(items[0], c)}\n```\n')
    (root / 'outputs/PILOT_VALIDATION.md').write_text('\n'.join(text))
    return r

def seal(root=ROOT):
    with process_lock(root / 'outputs/main'):
        r = reconcile('main', root)
        require(r['integrity_passed'], f'Integrity failure: {r["integrity_errors"]}')
        require(r['all_planned_accounted'], 'Not all 800 IDs are committed or terminally accounted; resume collection')
        frozen = read_json(root / 'config/frozen_protocol.json')
        payload = {'sealed_at': now(), 'logical_outputs_sha256': r['logical_outputs_sha256'],
                   'freeze_sha256': frozen['freeze_sha256'], 'planned': r['planned'],
                   'committed': r['committed'], 'terminal_failures': r['terminal_failures']}
        path = root / 'outputs/main/sealed_outputs.json'
        if path.exists(): require(read_json(path)['logical_outputs_sha256'] == payload['logical_outputs_sha256'], 'Sealed outputs changed')
        else: atomic_json(path, payload, exclusive=True)
        return r

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--split', choices=['pilot','main'], default='main')
    parser.add_argument('--seal', action='store_true')
    args = parser.parse_args()
    require(not args.seal or args.split == 'main', 'Only main outputs can be sealed for main analysis')
    result = pilot_report() if args.split == 'pilot' else seal() if args.seal else reconcile()
    atomic_json(ROOT / f'outputs/{args.split}_reconciliation.json', result)
    print({k: result[k] for k in ('planned','committed','attempts','technical_retries','complete_valid_questions','integrity_passed','all_planned_accounted')})
    if not result['integrity_passed']: raise SystemExit(1)
