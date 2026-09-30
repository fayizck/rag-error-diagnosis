from __future__ import annotations
import argparse,asyncio,json
from .common import ROOT,write_json
from .prepare import prepare
from .freeze import build_freeze,verify_freeze
from .collector import collect,synthetic_rehearsal
from .reconcile import reconcile,seal_main
from .analysis import analyze

def main():
 p=argparse.ArgumentParser();sp=p.add_subparsers(dest='cmd',required=True)
 sp.add_parser('prepare');sp.add_parser('freeze');sp.add_parser('verify');sp.add_parser('synthetic-main')
 for name in ('pilot','main'):
  q=sp.add_parser('collect-'+name);q.add_argument('--live',action='store_true');q.add_argument('--confirm-freeze',required=True);q.add_argument('--concurrency',type=int);q.add_argument('--rpm',type=int);q.add_argument('--tpm',type=int)
 for name in ('pilot','main'):sp.add_parser('reconcile-'+name)
 sp.add_parser('seal-main');sp.add_parser('analyze')
 a=p.parse_args()
 if a.cmd=='prepare':prepare()
 elif a.cmd=='freeze':print(build_freeze()['freeze_sha256'])
 elif a.cmd=='verify':print(json.dumps({'status':'PASS','freeze_sha256':verify_freeze()['freeze_sha256']},indent=2))
 elif a.cmd=='synthetic-main':
  r=synthetic_rehearsal();write_json(ROOT/'outputs/study2_rag/synthetic_main_rehearsal.json',r);print(json.dumps(r,indent=2))
 elif a.cmd.startswith('collect-'):asyncio.run(collect(a.cmd.split('-')[1],a.confirm_freeze,a.live,a.concurrency,a.rpm,a.tpm))
 elif a.cmd.startswith('reconcile-'):print(json.dumps(reconcile(a.cmd.split('-')[1]),indent=2))
 elif a.cmd=='seal-main':print(json.dumps(seal_main(),indent=2))
 elif a.cmd=='analyze':print(json.dumps(analyze(),indent=2))
if __name__=='__main__':main()
