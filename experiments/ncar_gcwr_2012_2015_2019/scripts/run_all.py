#!/usr/bin/env python3
"""Resumable driver for the full three-year NCAR GCWR experiment."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, UTC
from pathlib import Path

from run_months import month_cache_ready

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'scripts'
RDH = Path(os.environ.get('RDH_ROOT', '/Users/apple/Desktop/ResearchDataHub'))
DBAS = Path(os.environ.get('DBAS_ROOT', '/Users/apple/Desktop/era5数据dbas'))
HYDROWEAVE = Path(os.environ.get('HYDROWEAVE_ROOT', '/Users/apple/Desktop/Hydroweave'))
RDH_PY = Path(os.environ.get('RDH_PY', RDH / '.venv' / 'bin' / 'python'))
HW_PY = Path(os.environ.get('HW_PY', HYDROWEAVE / '.venv' / 'bin' / 'python'))
YEARS = (2012, 2015, 2019)
ENV = dict(os.environ)
ENV['PYTHONPATH'] = os.pathsep.join([
    str(RDH / 'src'), str(DBAS / 'src'), str(SCRIPTS)
])


def run(cmd: list[str], *, workdir: Path, log: Path) -> None:
    log.parent.mkdir(parents=True, exist_ok=True)
    print('[start]', ' '.join(cmd), flush=True)
    with log.open('a', encoding='utf-8') as handle:
        proc = subprocess.run(cmd, cwd=workdir, env=ENV, text=True,
                              stdout=handle, stderr=subprocess.STDOUT, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f'command failed ({proc.returncode}); see {log}')
    print('[ok]', log, flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--workers', type=int, default=64)
    ap.add_argument('--year', type=int, action='append', default=[])
    ap.add_argument('--months', type=int, nargs='*', default=list(range(1, 13)))
    args = ap.parse_args()
    years = tuple(args.year) if args.year else YEARS
    for year in years:
        start = f'{year:04d}-01-01'
        end = f'{year + 1:04d}-01-01'
        for date in (start, end):
            tag = date.replace('-', '')
            if not (ROOT / 'state' / f'boundary_{tag}.json').exists():
                run([str(RDH_PY), str(SCRIPTS / 'fetch_boundary.py'), '--date', date,
                     '--workers', str(min(args.workers, 16))],
                    workdir=RDH, log=ROOT / 'logs' / f'boundary_{tag}.log')
        for month in args.months:
            token = f'{year:04d}{month:02d}'
            fetch_state = ROOT / 'state' / f'{token}_fetch.json'
            if not month_cache_ready(token):
                if not fetch_state.exists():
                    run([str(RDH_PY), str(SCRIPTS / 'fetch_month.py'), '--year', str(year),
                         '--month', str(month), '--workers', str(args.workers)],
                        workdir=RDH, log=ROOT / 'logs' / f'fetch_{token}.log')
                run([str(HW_PY), str(SCRIPTS / 'process_month.py'),
                     '--year', str(year), '--month', str(month)],
                    workdir=ROOT, log=ROOT / 'logs' / f'process_{token}.log')
                if not month_cache_ready(token):
                    raise RuntimeError(f'{token}: processed cache still fails audit')
            print(f'[year {year}] {token} ready', flush=True)
        if all(month_cache_ready(f'{year:04d}{m:02d}') for m in range(1, 13)):
            run([str(HW_PY), str(SCRIPTS / 'assemble_year.py'), '--year', str(year)],
                workdir=ROOT, log=ROOT / 'logs' / f'assemble_{year}.log')
    run([str(HW_PY), str(SCRIPTS / 'audit_outputs.py')],
        workdir=ROOT, log=ROOT / 'logs' / 'audit_outputs.log')
    run([str(HW_PY), str(SCRIPTS / 'plot_results.py')],
        workdir=ROOT, log=ROOT / 'logs' / 'plot_results.log')
    run([str(HW_PY), str(SCRIPTS / 'final_acceptance.py')],
        workdir=ROOT, log=ROOT / 'logs' / 'final_acceptance.log')
    print(json.dumps({'finished_at': datetime.now(UTC).isoformat(), 'years': years,
                      'months': args.months}), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
