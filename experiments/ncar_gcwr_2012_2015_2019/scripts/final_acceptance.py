#!/usr/bin/env python3
"""Final, evidence-based acceptance for the 36-month GCWR experiment."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

from audit_outputs import YEARS, _audit_month, _load_overrides

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_FIGURES = (
    'fig01_clwc_annual_mean.png',
    'fig01_ciwc_annual_mean.png',
    'fig01_crwc_annual_mean.png',
    'fig01_cswc_annual_mean.png',
    'fig01_qh_annual_mean.png',
    'fig02_seasonal_cycle.png',
    'fig03_vertical_profiles.png',
    'fig04_qh_anomaly.png',
    'fig05_gcwr_budget.png',
    'fig06_residuals.png',
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _figure_hashes() -> dict[str, str]:
    path = ROOT / 'figures' / 'SHA256SUMS.txt'
    if not path.exists():
        return {}
    result = {}
    for line in path.read_text(encoding='utf-8').splitlines():
        digest, name = line.split(maxsplit=1)
        result[name.strip()] = digest
    return result


def evaluate() -> dict:
    overrides = _load_overrides()
    monthly = [_audit_month(year, month, overrides)
               for year in YEARS for month in range(1, 13)]
    failures: list[str] = []
    warnings: list[str] = []

    bad_months = [item for item in monthly if item['status'] != 'PASS']
    for item in bad_months:
        failures.append(f"{item['token']} monthly audit {item['status']}: "
                        f"{'; '.join(item.get('issues', []))}")

    annual = {}
    for year in YEARS:
        budget_path = ROOT / 'annual' / f'{year:04d}_budget.json'
        fields_path = ROOT / 'annual' / f'{year:04d}_fields.nc'
        if not budget_path.exists() or not fields_path.exists():
            failures.append(f'{year}: annual budget/fields missing')
            continue
        payload = json.loads(budget_path.read_text(encoding='utf-8'))
        evaluation = payload.get('evaluation', {})
        if not evaluation.get('gcwr_identity_ok'):
            failures.append(f'{year}: GCWR algebraic identity failed')
        if not evaluation.get('inventory_identity_ok'):
            failures.append(f'{year}: inventory identity Qm=Qv+Qh failed')
        if 'mean_inventory_kg' not in payload:
            failures.append(f'{year}: annual mean inventory is missing')
        sanity = payload.get('sanity_check', {})
        if not sanity.get('ok'):
            for flag in sanity.get('flags', ['unknown sanity failure']):
                warnings.append(f'{year}: {flag}')
        annual[str(year)] = {
            'budget': str(budget_path),
            'fields': str(fields_path),
            'gcwr_kg': evaluation.get('gcwr_kg'),
            'Eh': evaluation.get('Eh'),
            'Tv_days': evaluation.get('Tv_days'),
            'Th_hours': evaluation.get('Th_hours'),
            'sanity_ok': bool(sanity.get('ok')),
            'sanity_flags': list(sanity.get('flags', [])),
            'budget_sha256': _sha256(budget_path),
            'fields_sha256': _sha256(fields_path),
        }

    declared_hashes = _figure_hashes()
    figures = {}
    for name in EXPECTED_FIGURES:
        path = ROOT / 'figures' / name
        if not path.exists():
            failures.append(f'figure missing: {name}')
            continue
        actual = _sha256(path)
        declared = declared_hashes.get(name)
        if declared != actual:
            failures.append(f'figure hash missing/mismatch: {name}')
        figures[name] = actual

    if failures:
        verdict = 'FAIL'
    elif warnings:
        verdict = 'CONDITIONAL_PASS'
    else:
        verdict = 'PASS'
    return {
        'verdict': verdict,
        'months': {
            'expected': 36,
            'pass': sum(item['status'] == 'PASS' for item in monthly),
            'fail': sum(item['status'] == 'FAIL' for item in monthly),
            'not_run': sum(item['status'] == 'NOT_RUN' for item in monthly),
        },
        'annual': annual,
        'figures': figures,
        'failures': failures,
        'warnings': warnings,
        'monthly_results': monthly,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--output', type=Path,
                    default=ROOT / 'evidence' / 'final_acceptance.json')
    args = ap.parse_args()
    report = evaluate()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    tmp = args.output.with_suffix(args.output.suffix + '.tmp')
    tmp.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n',
                   encoding='utf-8')
    os.replace(tmp, args.output)
    print(json.dumps({key: report[key] for key in
                      ('verdict', 'months', 'failures', 'warnings')},
                     ensure_ascii=False))
    return 0 if report['verdict'] in {'PASS', 'CONDITIONAL_PASS'} else 1


if __name__ == '__main__':
    raise SystemExit(main())
