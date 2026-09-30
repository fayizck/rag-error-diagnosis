import argparse
import asyncio
from .common import config
from .collector import collect, dry_run

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Main collection. Requires successful pilot and verified freeze.')
    cfg = config()
    parser.add_argument('--concurrency', type=int, default=cfg['default_concurrency'])
    parser.add_argument('--rpm', type=int, default=cfg['default_rpm'])
    parser.add_argument('--tpm', type=int, default=cfg['default_tpm'])
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    if args.dry_run: print(dry_run())
    else: asyncio.run(collect('main', args.concurrency, args.rpm, args.tpm))
