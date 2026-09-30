"""Account-specific metadata and countTokens verification; generates no answers."""
import argparse
import asyncio
from .common import ROOT, CONDITIONS, atomic_json, config, digest, file_hash, now, read_json, read_jsonl, require
from .provider import Gemini, ProviderFailure
from .prompts import render
from .validate import validate_prepared

async def verify(root=ROOT):
    validate_prepared(root); cfg = config(root)
    provider = Gemini(cfg)
    try:
        info = await provider.model()  # Fail immediately on absent/inaccessible requested model.
        model_record = {'checked_at': now(), 'requested_model': cfg['model'], 'metadata': info,
                        'config_sha256': digest(cfg), 'availability': 'verified',
                        'parameter_support': 'metadata and official REST documentation checked; configuration verified during the technical pilot'}
        atomic_json(root / 'outputs/model_verification.json', model_record)
        path = root / 'outputs/token_verification.json'
        audit = read_json(path) if path.exists() else {'config_sha256': digest(cfg), 'counts': {}}
        require(audit['config_sha256'] == digest(cfg), 'Token audit belongs to different configuration')
        sem = asyncio.Semaphore(4)
        async def count(item, c):
            sid = item['item_id'] + '::' + c
            if sid in audit['counts']:
                require(audit['counts'][sid]['prompt_sha256'] == item['prompt_sha256'][c], 'Cached token count hash mismatch')
                return
            async with sem:
                for attempt in range(3):
                    try: n = await provider.count(render(item, c)); break
                    except ProviderFailure as e:
                        if not e.retryable or attempt == 2: raise
                        await asyncio.sleep(max(e.retry_after, 2 ** attempt))
                require(n + cfg['generation_config']['maxOutputTokens'] < info['inputTokenLimit'], 'Prompt/context limit exceeded; no truncation allowed')
                audit['counts'][sid] = {'tokens': n, 'prompt_sha256': item['prompt_sha256'][c]}
                atomic_json(path, audit)
        all_items = read_jsonl(root / 'outputs/pilot_manifest.jsonl') + read_jsonl(root / 'outputs/main_manifest.jsonl')
        await asyncio.gather(*(count(item, c) for item in all_items for c in CONDITIONS))
        require(len(audit['counts']) == len(all_items) * 4, 'Unexpected countTokens coverage')
        require(all(type(r['tokens']) is int and r['tokens'] > 0 and
                    r['tokens'] + cfg['generation_config']['maxOutputTokens'] < info['inputTokenLimit']
                    for r in audit['counts'].values()), 'Cached token counts exceed current advertised input limit')
        deltas = {item['item_id']: max(audit['counts'][item['item_id']+'::'+c]['tokens'] for c in CONDITIONS)
                  - min(audit['counts'][item['item_id']+'::'+c]['tokens'] for c in CONDITIONS) for item in all_items}
        audit.update(checked_at=now(), all_within_limit=True, condition_token_deltas=deltas,
                     equal_tokens_all_conditions=all(x == 0 for x in deltas.values()), complete=True)
        atomic_json(path, audit)
        require(audit['equal_tokens_all_conditions'], 'Focus values tokenize to unequal lengths. Technical review required before pilot; do not tune on accuracy.')
        print(f"Verified requested model {cfg['model']}; {len(audit['counts'])} prompt-token checks completed.")
    finally: await provider.close()

if __name__ == '__main__':
    argparse.ArgumentParser(description=__doc__).parse_args()
    asyncio.run(verify())
