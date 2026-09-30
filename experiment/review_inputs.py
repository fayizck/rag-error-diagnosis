"""Record an actual completed input review; does not infer or perform human review."""
import argparse
from .common import ROOT, atomic_json, file_hash, now, read_json, require
from .validate import validate_prepared

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--reviewer',required=True)
    p.add_argument('--notes',required=True)
    p.add_argument('--confirm-reviewed',action='store_true',required=True)
    a=p.parse_args();validate_prepared()
    require(not (ROOT/'outputs/main/collection.sqlite3').exists(),'Pre-main input review must precede main collection')
    plan=read_json(ROOT/'outputs/manual_input_plan.json')
    atomic_json(ROOT/'outputs/manual_input_review.json',{'passed':True,'reviewer':a.reviewer,'notes':a.notes,'reviewed_at':now(),
        'plan_sha256':file_hash(ROOT/'outputs/manual_input_plan.json'),
        'preparation_sha256':file_hash(ROOT/'outputs/preparation.json'),'reviewed_ids':plan},exclusive=True)
    print('Recorded input review for the fixed ten pilot and ten main inputs.')
