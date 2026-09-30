"""Freeze only after a successful pilot. A pending document never authorizes collection."""
import argparse
import subprocess
from .common import ROOT, atomic_json, config, digest, file_hash, now, read_json, require
from .prompts import TEMPLATE
from .validate import validate_prepared

def source_hashes(root=ROOT):
    names = [str(p.relative_to(root)) for folder in ('experiment','analysis','tests') for p in (root/folder).glob('*.py')]
    names += ['requirements.txt','config/study.json','docs/PROTOCOL_SPEC.md']
    return {name: file_hash(root/name) for name in sorted(names)}

def verify_freeze(root=ROOT):
    frozen = read_json(root / 'config/frozen_protocol.json')
    require(frozen.get('status') == 'FROZEN', 'Protocol is NOT FROZEN. Complete model verification, pilot, input review and freeze first.')
    require(digest({k:v for k,v in frozen.items() if k != 'freeze_sha256'}) == frozen['freeze_sha256'], 'Freeze JSON hash mismatch')
    for path, sha in frozen['files'].items(): require(file_hash(root/path) == sha, f'Frozen input/code changed: {path}')
    require(source_hashes(root) == frozen['source_hashes'], 'Source set/hash changed after freeze')
    require(config(root) == frozen['configuration'], 'Configuration changed')
    if 'pilot_outputs_sha256' in frozen:
        from .storage import Store
        pilot = Store(root/'outputs/pilot/collection.sqlite3', readonly=True)
        try: require(pilot.fingerprint() == frozen['pilot_outputs_sha256'], 'Pilot evidence changed after freeze')
        finally: pilot.close()
    validate_prepared(root)
    return frozen

def freeze(root=ROOT, pending=False):
    validate_prepared(root)
    cfg = config(root); prep = read_json(root/'outputs/preparation.json')
    source = source_hashes(root)
    spec = (root/'docs/PROTOCOL_SPEC.md').read_text()
    frozen = {'status': 'PENDING', 'created_at': now(), 'configuration': cfg, 'source_hashes': source,
              'dataset': prep, 'exact_prompt_template': TEMPLATE, 'blocking_requirements':
              ['Account-specific model verification','840 non-generative token checks','40-call technical pilot and reconciliation',
               'Passing recorded test suite','Input review of ten pilot and ten fixed main inputs','Committed source code']}
    if pending:
        tests = root/'outputs/test_status.json'
        if tests.exists() and read_json(tests).get('passed') and read_json(tests).get('source_hashes') == source:
            frozen['blocking_requirements'].remove('Passing recorded test suite')
        review_path = root/'outputs/manual_input_review.json'
        if review_path.exists():
            review = read_json(review_path)
            if (review.get('passed') and review.get('plan_sha256') == file_hash(root/'outputs/manual_input_plan.json')
                    and review.get('preparation_sha256') == file_hash(root/'outputs/preparation.json')):
                frozen['blocking_requirements'].remove('Input review of ten pilot and ten fixed main inputs')
        try:
            commit = subprocess.check_output(['git','rev-parse','HEAD'], cwd=root, text=True, stderr=subprocess.DEVNULL).strip()
            import hashlib
            committed = all(hashlib.sha256(subprocess.check_output(['git','show',f'{commit}:{name}'], cwd=root,
                            stderr=subprocess.DEVNULL)).hexdigest() == sha for name, sha in source.items())
            if committed:
                frozen['code_git_commit'] = commit
                frozen['blocking_requirements'].remove('Committed source code')
        except subprocess.CalledProcessError:
            pass
    path = root/'config/frozen_protocol.json'
    if path.exists() and read_json(path).get('status') == 'FROZEN':
        verify_freeze(root); print('Existing valid freeze preserved.'); return
    if not pending:
        from .collector import check_online_preflight, pilot_lock
        from analysis.reconcile import pilot_report
        check_online_preflight(root)
        r = pilot_report(root)
        require(r['safe_to_freeze_technical'], 'Pilot has not passed all 40 observations')
        review = read_json(root/'outputs/manual_input_review.json')
        require(review['passed'] is True and review['plan_sha256'] == file_hash(root/'outputs/manual_input_plan.json'), 'Input review incomplete or stale')
        require(review['preparation_sha256'] == file_hash(root/'outputs/preparation.json'), 'Input review dataset mismatch')
        test = read_json(root/'outputs/test_status.json')
        require(test['passed'] and test['source_hashes'] == source, 'Tests missing, failed or stale')
        commit = subprocess.check_output(['git','rev-parse','HEAD'], cwd=root, text=True).strip()
        for name, sha in source.items():
            blob = subprocess.check_output(['git','show',f'{commit}:{name}'], cwd=root)
            import hashlib
            require(hashlib.sha256(blob).hexdigest() == sha, f'Code not committed: {name}')
        files = dict(prep['files']); files.update(source)
        for name in ['outputs/preparation.json','outputs/model_verification.json','outputs/token_verification.json',
                     'outputs/manual_input_review.json','outputs/test_status.json','outputs/pilot/run_lock.json']:
            files[name] = file_hash(root/name)
        versions = r['returned_model_versions']
        frozen.update(status='FROZEN', files=files, code_git_commit=commit,
                      returned_model_version=None if versions == ['<not exposed>'] else versions[0],
                      pilot_outputs_sha256=r['logical_outputs_sha256'], blocking_requirements=[])
    frozen['freeze_sha256'] = digest(frozen)
    atomic_json(path, frozen)
    text = f"# Protocol freeze\n\n**Status: {frozen['status']}**\n\n"
    if pending: text += 'Main collection is disabled. No successful live pilot or account availability is being claimed.\n\n'
    text += spec+'\n\n## Exact prompt template\n```text\n'+TEMPLATE+'\n```\n'
    text += '\n## Recorded configuration and provenance\n```json\n'
    import json
    text += json.dumps(frozen, ensure_ascii=False, indent=2)+'\n```\n'
    (root/'PROTOCOL_FREEZE.md').write_text(text)
    print(f"Protocol {frozen['status']}; seed {cfg['seed']}.")

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pending', action='store_true', help='Write clearly marked blocked draft; never permits main calls')
    freeze(pending=parser.parse_args().pending)
