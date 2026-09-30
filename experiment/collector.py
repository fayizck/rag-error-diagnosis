import asyncio
import random
import time
from collections import Counter, deque
from .common import ROOT, atomic_json, config, digest, file_hash, now, read_json, read_jsonl, require
from .prompts import render
from .provider import Gemini, ProviderFailure, parse_response
from .scoring import score, normalize_answer
from .storage import Store, process_lock
from .validate import validate_prepared

class RateLimiter:
    """Rolling 60s request/token admission; reserve output cap, refund from actual usage."""
    def __init__(self, rpm, tpm):
        require(rpm > 0 and tpm > 0, 'Rate limits must be positive')
        self.rpm, self.tpm = rpm, tpm
        self.entries = deque(); self.lock = asyncio.Lock()

    async def acquire(self, tokens):
        require(tokens <= self.tpm, 'A request reservation exceeds TPM; raise --tpm to the actual account limit')
        while True:
            async with self.lock:
                t = time.monotonic()
                while self.entries and t - self.entries[0][0] >= 60: self.entries.popleft()
                if len(self.entries) < self.rpm and sum(e[1] for e in self.entries) + tokens <= self.tpm:
                    ticket = [t, tokens]; self.entries.append(ticket); return ticket
                delay = max(.05, min(1., 60 - (t - self.entries[0][0])))
            await asyncio.sleep(delay)

    async def settle(self, ticket, tokens):
        async with self.lock: ticket[1] = tokens

def pilot_lock(root):
    from .freeze import source_hashes
    return {'config_sha256': digest(config(root)), 'preparation_sha256': file_hash(root / 'outputs/preparation.json'),
            'source_hashes': source_hashes(root), 'token_verification_sha256': file_hash(root / 'outputs/token_verification.json')}

def check_online_preflight(root):
    cfg = config(root)
    require((root/'outputs/model_verification.json').exists() and (root/'outputs/token_verification.json').exists(),
            'Online preflight is missing. Export GEMINI_API_KEY and run python -m experiment.verify_model first.')
    model = read_json(root / 'outputs/model_verification.json')
    token = read_json(root / 'outputs/token_verification.json')
    require(model['availability'] == 'verified' and model['requested_model'] == cfg['model'], 'Model not account-verified')
    require(model['config_sha256'] == digest(cfg) == token['config_sha256'], 'Preflight configuration mismatch')
    require(token.get('complete') and token.get('equal_tokens_all_conditions') and token.get('all_within_limit'), 'Token audit incomplete')
    rows = read_jsonl(root/'outputs/pilot_schedule.jsonl') + read_jsonl(root/'outputs/main_schedule.jsonl')
    require(set(token['counts']) == {r['scientific_id'] for r in rows}, 'Token audit coverage mismatch')
    for row in rows:
        count = token['counts'][row['scientific_id']]
        require(count['prompt_sha256'] == row['prompt_sha256'], 'Token audit prompt hash mismatch')
        require(type(count['tokens']) is int and count['tokens'] > 0, 'Invalid audited token count')
    for split in ('pilot', 'main'):
        for item in read_jsonl(root/f'outputs/{split}_manifest.jsonl'):
            require(len({token['counts'][item['item_id']+'::'+c]['tokens'] for c in ('00','10','01','11')}) == 1,
                    'Token counts differ across conditions')
    return token

async def collect(split, concurrency, rpm, tpm, root=ROOT, provider=None):
    require(split in ('pilot', 'main'), 'Invalid split')
    cfg = config(root); validate_prepared(root)
    require(concurrency > 0, 'Concurrency must be positive')
    token = check_online_preflight(root)
    expected_version = None
    if split == 'main':
        from .freeze import verify_freeze
        frozen = verify_freeze(root)
        expected_version = frozen['returned_model_version']
        identity = frozen['freeze_sha256']
    else: identity = digest(pilot_lock(root))
    directory = root / f'outputs/{split}'
    require(not (directory / 'sealed_outputs.json').exists(), 'Outputs are sealed; collector cannot modify them')
    with process_lock(directory):
        lock = pilot_lock(root) if split == 'pilot' else {'freeze_sha256': identity}
        lockpath = directory / 'run_lock.json'
        if lockpath.exists(): require(read_json(lockpath) == lock, 'Run code/config changed; refusing mixed protocol')
        else: atomic_json(lockpath, lock, exclusive=True)
        store = Store(directory / 'collection.sqlite3')
        store.recover_inflight()
        try:
            items = {r['item_id']: r for r in read_jsonl(root / f'outputs/{split}_manifest.jsonl')}
            sched = read_jsonl(root / f'outputs/{split}_schedule.jsonl')
            committed = store.observations()
            previous_versions = {r.get('returned_model_version') for r in committed.values()}
            require(len(previous_versions) <= 1, 'Committed responses have inconsistent model versions')
            if split == 'pilot' and previous_versions:
                expected_version = next(iter(previous_versions))
            require(set(committed) <= {r['scientific_id'] for r in sched}, 'Unexpected committed scientific ID')
            events = store.events()
            terminal = {e['scientific_id'] for e in events if e['kind'] == 'finish' and e.get('terminal')}
            attempts = Counter(e['scientific_id'] for e in events if e['kind'] == 'start')
            provider = provider or Gemini(cfg)
            limiter = RateLimiter(rpm, tpm); sem = asyncio.Semaphore(concurrency)
            stop = asyncio.Event(); started = time.monotonic()
            usage_total = sum(r.get('token_usage', {}).get('totalTokenCount', 0) for r in committed.values())
            count_done, run_calls = len(committed), 0
            policy = cfg['retry_policy']

            async def one(row):
                nonlocal count_done, run_calls, usage_total, expected_version
                sid = row['scientific_id']
                if sid in committed or sid in terminal: return
                item = items[row['item_id']]
                for attempt in range(attempts[sid] + 1, policy['max_attempts'] + 1):
                    if stop.is_set(): return
                    async with sem:
                        if stop.is_set(): return
                        ticket = await limiter.acquire(token['counts'][sid]['tokens'] + cfg['generation_config']['maxOutputTokens'])
                        if stop.is_set(): return
                        t = time.monotonic(); timestamp = now()
                        common = dict(scientific_id=sid, item_id=row['item_id'], condition=row['condition'], split=split,
                                      protocol_identity=identity, config_sha256=digest(cfg), prompt_sha256=row['prompt_sha256'],
                                      requested_model=cfg['model'], generation_config=cfg['generation_config'], attempt=attempt,
                                      schedule_index=row['schedule_index'], started_at=timestamp)
                        store.start(sid, attempt, {'at': timestamp, 'protocol_identity': identity, 'prompt_sha256': row['prompt_sha256']})
                        run_calls += 1
                        try: raw = await provider.generate(render(item, row['condition']))
                        except ProviderFailure as e:
                            retry = e.retryable and attempt < policy['max_attempts']
                            store.fail(sid, attempt, {'at': now(), 'status': e.category, 'http_status': e.http_status,
                                'latency_seconds': time.monotonic()-t, 'retryable': e.retryable, 'terminal': not retry})
                            if not e.retryable: stop.set()  # Authentication, model or schema failure: stop new calls.
                            if not retry: return
                            delay = max(e.retry_after, min(policy['max_delay_seconds'], policy['base_delay_seconds'] * 2 ** (attempt-1))
                                        + random.SystemRandom().uniform(0, 1))
                        else:
                            parsed = parse_response(raw)
                            returned = parsed['returned_model_version']
                            if expected_version is None and returned is not None: expected_version = returned
                            mismatch = expected_version is not None and returned != expected_version
                            observation = dict(common, **parsed, finished_at=now(), latency_seconds=time.monotonic()-t,
                                               exception_category=None, model_version_mismatch=mismatch)
                            observation.update(score(parsed['answer'], item['answer']) if parsed['status'] == 'valid' else
                                {'normalized_prediction': normalize_answer(parsed['answer']), 'normalized_gold': normalize_answer(item['answer']),
                                 'em': None, 'f1': None})
                            store.commit(observation)
                            used = parsed['token_usage'].get('totalTokenCount')
                            if isinstance(used, int): await limiter.settle(ticket, used); usage_total += used
                            count_done += 1
                            elapsed = max(time.monotonic()-started, .001)
                            starts = [e for e in store.events() if e['kind'] == 'start']
                            retries = sum(e['attempt'] > 1 for e in starts)
                            print(f'{split}: committed {count_done}/{len(sched)}; attempts {len(starts)}; retries {retries}; '
                                  f'run rate {60*run_calls/elapsed:.1f}/min; tokens {usage_total}; last={parsed["status"]}', flush=True)
                            if mismatch: stop.set()
                            return
                    await asyncio.sleep(delay)  # No semaphore held while backing off.
            async def guarded(row):
                try: await one(row)
                except Exception:
                    stop.set()
                    raise
            try:
                results = await asyncio.gather(*(guarded(row) for row in sched), return_exceptions=True)
                for result in results:
                    if isinstance(result, BaseException): raise result
            finally: await provider.close()
            if stop.is_set(): raise ValueError('Collection stopped after a provider, configuration, or version failure; inspect reconciliation.')
        finally: store.close()

def dry_run(root=ROOT, require_frozen=True):
    result = validate_prepared(root)
    from .freeze import verify_freeze
    if require_frozen: verify_freeze(root)
    # Exercise store, request payload, response parsing and resume in a temporary directory only.
    from .selfcheck import exercise
    exercise(root)
    result.update(api_calls=0, output_schema='validated with synthetic fixture in temporary storage',
                  protocol_freeze='verified' if require_frozen else 'not verified; offline preparation only')
    return result
