import argparse
from .common import ROOT, CONDITIONS, atomic_json, config, digest, file_hash, read_json, read_jsonl, require, now
from .prompts import render, schedule, validate_item

def validate_prepared(root=ROOT):
    cfg = config(root); prep = read_json(root / 'outputs/preparation.json')
    for name, expected in prep['files'].items():
        require(file_hash(root / name) == expected, f'Prepared file changed: {name}')
    split_ids = {}
    for split, n in [('pilot', cfg['pilot_size']), ('main', cfg['main_size'])]:
        items = read_jsonl(root / f'outputs/{split}_manifest.jsonl')
        require(len(items) == n, f'Wrong {split} sample size')
        split_ids[split] = {r['item_id'] for r in items}
        require(len(split_ids[split]) == n, 'Duplicate item ID')
        for item in items:
            unhashed = {k: v for k, v in item.items() if k != 'item_sha256'}
            require(digest(unhashed) == item['item_sha256'], 'Item hash mismatch')
            validate_item(item)
            for c in CONDITIONS:
                require(digest(render(item, c)) == item['prompt_sha256'][c], 'Prompt hash mismatch')
        sched = read_jsonl(root / f'outputs/{split}_schedule.jsonl')
        require(sched == schedule(items, cfg['seed'], split), f'{split} schedule mismatch')
        require(len(sched) == n * 4, 'Wrong planned scientific-ID count')
    require(not split_ids['pilot'] & split_ids['main'], 'Pilot/main overlap')
    return {'passed': True, 'checked_at': now(), 'items': sum(map(len, split_ids.values())),
            'prompts': 4 * sum(map(len, split_ids.values())), 'invariants_per_item': 16,
            'main_planned': cfg['main_size'] * 4, 'pilot_planned': cfg['pilot_size'] * 4,
            'preparation_sha256': file_hash(root / 'outputs/preparation.json')}

def render_review(root=ROOT):
    plan = read_json(root / 'outputs/manual_input_plan.json')
    for split in ('pilot', 'main'):
        items = {r['item_id']: r for r in read_jsonl(root / f'outputs/{split}_manifest.jsonl')}
        text = [f'# {split.title()} input review\nNo model outputs are included.\n']
        for identifier in plan[f'{split}_ids']:
            item = items[identifier]
            text.append(f"## {identifier}\nA: {item['group_a']}\n\nB: {item['group_b']}\n\nSupporting facts: {item['supporting_facts']}\n")
            for c in CONDITIONS:
                text.append(f'### Condition {c}\n```text\n{render(item, c)}\n```\n')
        (root / f'outputs/{split}_renderings.md').write_text('\n'.join(text))

if __name__ == '__main__':
    argparse.ArgumentParser(description='Validate recorded inputs and prompt invariants.').parse_args()
    result = validate_prepared(); render_review()
    atomic_json(ROOT / 'outputs/input_validation.json', result)
    print(result)
