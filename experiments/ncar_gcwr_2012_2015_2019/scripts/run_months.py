#!/usr/bin/env python3
"""Run assigned months without touching annual boundary snapshots."""
from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RDH = Path(os.environ.get('RDH_ROOT', '/Users/apple/Desktop/ResearchDataHub'))
DBAS = Path(os.environ.get('DBAS_ROOT', '/Users/apple/Desktop/era5数据dbas'))
HYDROWEAVE = Path(os.environ.get('HYDROWEAVE_ROOT', '/Users/apple/Desktop/Hydroweave'))
RDH_PY = Path(os.environ.get('RDH_PY', RDH / '.venv' / 'bin' / 'python'))
HW_PY = Path(os.environ.get('HW_PY', HYDROWEAVE / '.venv' / 'bin' / 'python'))
ENV = dict(os.environ)
ENV['PYTHONPATH'] = os.pathsep.join([str(RDH / 'src'), str(DBAS / 'src'), str(ROOT / 'scripts')])
OUTPUT_OVERRIDES = ROOT / 'repairs' / 'output_overrides.json'


def month_cache_ready(token: str) -> bool:
    """Return true only for a month that passes the scientific audit.

    File existence is not a completion signal: interrupted NetCDF writes and
    stale unvalidated caches can leave both expected paths behind. Import the
    audit implementation so the resumable runner and final acceptance use the
    same criteria.
    """
    from audit_outputs import _audit_month, _load_overrides

    year, month = int(token[:4]), int(token[4:])
    report = _audit_month(year, month, _load_overrides())
    if report['status'] == 'PASS':
        return True
    detail = '; '.join(report.get('issues', [])) or report['status']
    print(f'[not-ready] {token}: {detail}', flush=True)
    return False


def run(cmd, workdir, log):
    print('[start]', ' '.join(cmd), flush=True)
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open('a', encoding='utf-8') as f:
        p = subprocess.run(cmd, cwd=workdir, env=ENV, text=True,
                           stdout=f, stderr=subprocess.STDOUT, check=False)
    if p.returncode != 0:
        raise RuntimeError(f'failed ({p.returncode}): {log}')
    print('[ok]', log.name, flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--year', type=int, required=True)
    ap.add_argument('--months', type=int, nargs='+', required=True)
    ap.add_argument('--workers', type=int, default=24)
    args = ap.parse_args()
    for month in args.months:
        token = f'{args.year:04d}{month:02d}'
        fetch_state = ROOT / 'state' / f'{token}_fetch.json'
        if not fetch_state.exists():
            run([str(RDH_PY), str(ROOT / 'scripts' / 'fetch_month.py'),
                 '--year', str(args.year), '--month', str(month),
                 '--workers', str(args.workers)],
                RDH, ROOT / 'logs' / f'fetch_{token}.log')
        if not month_cache_ready(token):
            run([str(HW_PY), str(ROOT / 'scripts' / 'process_month.py'),
                 '--year', str(args.year), '--month', str(month)],
                ROOT, ROOT / 'logs' / f'process_{token}.log')
        if not month_cache_ready(token):
            raise RuntimeError(f'{token}: processed cache still fails audit')
        print(f'[ready] {token}', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
