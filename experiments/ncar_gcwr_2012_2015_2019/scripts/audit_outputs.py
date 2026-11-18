#!/usr/bin/env python3
"""Audit monthly GCWR caches before annual assembly and plotting."""
from __future__ import annotations

import argparse
import calendar
import hashlib
import json
import os
from pathlib import Path

import numpy as np
import xarray as xr

ROOT = Path(__file__).resolve().parents[1]
YEARS = (2012, 2015, 2019)
SPECIES = ('clwc', 'ciwc', 'crwc', 'cswc')
OVERRIDE_FILE = ROOT / 'repairs' / 'output_overrides.json'


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_overrides() -> dict:
    return json.loads(OVERRIDE_FILE.read_text(encoding='utf-8')) if OVERRIDE_FILE.exists() else {}


def _selected(token: str, kind: str, overrides: dict) -> Path:
    entry = overrides.get(token, {}).get(kind)
    if entry:
        path = ROOT / entry['path']
        if not path.exists():
            raise RuntimeError(f'{token} {kind} 覆盖文件不存在: {path}')
        actual = _sha256(path)
        if actual != entry['sha256']:
            raise RuntimeError(f'{token} {kind} 覆盖文件哈希不匹配: {actual}')
        return path
    subtree = 'monthly' if kind == 'fields' else 'state'
    suffix = 'fields.nc' if kind == 'fields' else 'budget.json'
    return ROOT / subtree / f'{token}_{suffix}'


def _audit_month(year: int, month: int, overrides: dict) -> dict:
    token = f'{year:04d}{month:02d}'
    fields = _selected(token, 'fields', overrides)
    budget = _selected(token, 'budget', overrides)
    issues: list[str] = []
    if not fields.exists():
        issues.append(f'缺少月度场: {fields}')
    if not budget.exists():
        issues.append(f'缺少月度收支: {budget}')
    if issues:
        return {'token': token, 'status': 'NOT_RUN', 'issues': issues,
                'fields': str(fields), 'budget': str(budget)}

    expected_days = calendar.monthrange(year, month)[1]
    with xr.open_dataset(fields) as ds:
        required = {f'{name}_col' for name in ('qv', *SPECIES, 'qh')}
        required |= {f'{name}_profile' for name in ('qv', *SPECIES, 'qh')}
        missing = required - set(ds.data_vars)
        if missing:
            issues.append(f'缺少变量: {sorted(missing)}')
        if 'day' not in ds.coords or ds.day.size != expected_days:
            issues.append(f'day 坐标应为 {expected_days} 天，实际 {ds.sizes.get("day")}')
        level = ds.level.values.astype('float64') if 'level' in ds.coords else np.array([])
        if level.size != 37 or not np.allclose(level, [1, 2, 3, 5, 7, 10, 20, 30, 50,
              70, 100, 125, 150, 175, 200, 225, 250, 300, 350, 400, 450, 500, 550,
              600, 650, 700, 750, 775, 800, 825, 850, 875, 900, 925, 950, 975, 1000]):
            issues.append('气压层不是预期的 37 层 1–1000 hPa 序列')
        for name in ('qv', *SPECIES, 'qh'):
            col = ds[f'{name}_col'].values
            prof = ds[f'{name}_profile'].values
            if not np.isfinite(col).all():
                issues.append(f'{name}_col 含非有限值')
            if not np.isfinite(prof).all():
                issues.append(f'{name}_profile 含非有限值')
            if col.size and np.nanmin(col) < 0:
                issues.append(f'{name}_col 含负值 {float(np.nanmin(col)):.4g}')
            if name == 'qv' and col.size and np.nanmax(col) > 500.0:
                issues.append(f'qv_col 异常上限 {float(np.nanmax(col)):.4g} kg m-2')
            if name != 'qv' and col.size and np.nanmax(col) > 100.0:
                issues.append(f'{name}_col 异常上限 {float(np.nanmax(col)):.4g} kg m-2')
        if not missing:
            residual = ds.qh_col.values - sum(ds[f'{name}_col'].values for name in SPECIES)
            if residual.size and not np.allclose(residual, 0.0, atol=1e-5):
                issues.append(f'Qh 柱量恒等残差最大 {float(np.nanmax(np.abs(residual))):.4g}')
            residual_profile = ds.qh_profile.values - sum(
                ds[f'{name}_profile'].values for name in SPECIES)
            if residual_profile.size and not np.allclose(residual_profile, 0.0, atol=1e-8):
                issues.append('Qh 廓线恒等残差非零')

    payload = json.loads(budget.read_text(encoding='utf-8'))
    if payload.get('days') != expected_days:
        issues.append(f'budget days={payload.get("days")} != {expected_days}')
    if payload.get('duration_s') != expected_days * 86400.0:
        issues.append('budget duration_s 与天数不一致')
    return {
        'token': token,
        'status': 'PASS' if not issues else 'FAIL',
        'issues': issues,
        'fields': str(fields),
        'budget': str(budget),
        'fields_sha256': _sha256(fields),
        'budget_sha256': _sha256(budget),
        'override': token in overrides,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--output', type=Path,
                    default=ROOT / 'evidence' / 'multiyear_output_audit.json')
    args = ap.parse_args()
    overrides = _load_overrides()
    months = [_audit_month(year, month, overrides)
              for year in YEARS for month in range(1, 13)]
    summary = {
        'PASS': sum(item['status'] == 'PASS' for item in months),
        'FAIL': sum(item['status'] == 'FAIL' for item in months),
        'NOT_RUN': sum(item['status'] == 'NOT_RUN' for item in months),
    }
    years = {}
    for year in YEARS:
        selected = [item for item in months if item['token'].startswith(str(year))]
        years[str(year)] = {
            'ready': all(item['status'] == 'PASS' for item in selected),
            'status': {state: sum(item['status'] == state for item in selected)
                       for state in ('PASS', 'FAIL', 'NOT_RUN')},
        }
    report = {'schema_version': 1, 'summary': summary,
              'years': years, 'months': months}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    tmp = args.output.with_suffix(args.output.suffix + '.tmp')
    tmp.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n',
                   encoding='utf-8')
    os.replace(tmp, args.output)
    print(json.dumps({'summary': summary, 'years': years, 'output': str(args.output)},
                     ensure_ascii=False))
    return 0 if summary['PASS'] == len(months) else 1


if __name__ == '__main__':
    raise SystemExit(main())
