import argparse
import asyncio
from .common import ROOT, config, read_json
from .collector import collect

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Technical pilot only: ten frozen items, forty planned generations.')
    cfg = config()
    parser.add_argument('--concurrency', type=int, default=cfg['default_concurrency'])
    parser.add_argument('--rpm', type=int, default=cfg['default_rpm'])
    parser.add_argument('--tpm', type=int, default=cfg['default_tpm'])
    args = parser.parse_args()
    try: asyncio.run(collect('pilot', args.concurrency, args.rpm, args.tpm))
    finally:
        from analysis.reconcile import pilot_report
        pilot_report(ROOT)
