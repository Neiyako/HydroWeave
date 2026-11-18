#!/usr/bin/env python3
"""Assemble monthly GCWR components into one full-year budget."""
from __future__ import annotations

import argparse
import calendar
import hashlib
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import xarray as xr

ROOT = Path(__file__).resolve().parents[1]
HW = Path(os.environ.get('HYDROWEAVE_ROOT', '/Users/apple/Desktop/Hydroweave'))
OUTPUT_OVERRIDE_FILE = ROOT / 'repairs' / 'output_overrides.json'
if str(HW) not in sys.path:
    sys.path.insert(0, str(HW))

from experiments.tp_cloud_water import budget as B  # noqa: E402


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def _verified_override(token: str, kind: str) -> Path | None:
    if not OUTPUT_OVERRIDE_FILE.exists():
        return None
    payload = json.loads(OUTPUT_OVERRIDE_FILE.read_text(encoding='utf-8'))
    entry = payload.get(token, {}).get(kind)
    if entry is None:
        return None
    path = ROOT / entry['path']
    if not path.exists():
        raise RuntimeError(f'{token} {kind} 覆盖文件不存在: {path}')
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != entry['sha256']:
        raise RuntimeError(f'{token} {kind} 覆盖文件哈希不匹配: {actual}')
    return path


def _month_paths(year: int) -> list[Path]:
    paths = []
    for month in range(1, 13):
        token = f'{year:04d}{month:02d}'
        paths.append(_verified_override(token, 'budget')
                     or ROOT / 'state' / f'{token}_budget.json')
    return paths


def _time_weighted_inventory(months: list[dict], year: int, prefix: str) -> float:
    """Annual mean inventory from monthly linear start/end estimates.

    The renewal period is a ratio of mean inventory to mean sink. Using only
    the two annual boundary snapshots would implicitly assume a linear annual
    inventory path and would bias the result whenever seasonal storage changes.
    """
    total_days = sum(calendar.monthrange(year, month)[1] for month in range(1, 13))
    weighted_kg_days = 0.0
    for month, payload in enumerate(months, start=1):
        days = calendar.monthrange(year, month)[1]
        mean_kg = 0.5 * (float(payload[f'{prefix}_start_kg'])
                         + float(payload[f'{prefix}_end_kg']))
        weighted_kg_days += mean_kg * days
    return weighted_kg_days / total_days


def assemble_year(year: int) -> dict:
    months = [_read(p) for p in _month_paths(year)]
    start_date = datetime(year, 1, 1)
    end_date = datetime(year + 1, 1, 1)
    boundary_start = _read(ROOT / 'state' / f'boundary_{year:04d}0101.json')
    boundary_end = _read(ROOT / 'state' / f'boundary_{year + 1:04d}0101.json')
    qv_in = sum(m['boundary_kg']['qv_in'] for m in months)
    qv_out = sum(m['boundary_kg']['qv_out'] for m in months)
    qh_in = sum(m['boundary_kg']['qh_in'] for m in months)
    qh_out = sum(m['boundary_kg']['qh_out'] for m in months)
    precip = sum(m['precip_kg'] for m in months)
    evap_obs = sum(m['evap_obs_kg'] for m in months)
    days = 366 if calendar.isleap(year) else 365
    terms = B.BudgetTerms(
        qv_init=float(boundary_start['qv_kg']),
        qv_final=float(boundary_end['qv_kg']),
        qh_init=float(boundary_start['qh_kg']),
        qh_final=float(boundary_end['qh_kg']),
        qv_in=float(qv_in), qv_out=float(qv_out),
        qh_in=float(qh_in), qh_out=float(qh_out),
        rain_kg=float(precip), duration_s=float(days * 86400),
    )
    eval_ = B.evaluate(terms)
    residuals = B.residuals(terms)
    mean_inventory_kg = {
        'qv': _time_weighted_inventory(months, year, 'qv'),
        'qh': _time_weighted_inventory(months, year, 'qh'),
    }
    eval_['Tv_days'] = B.renewal_period(
        mean_inventory_kg['qv'], precip, float(days * 86400), unit='day')
    eval_['Th_hours'] = B.renewal_period(
        mean_inventory_kg['qh'], precip, float(days * 86400), unit='hour')
    sanity = B.sanity_check(eval_)
    evap_from_total = float(residuals['evap_total'])
    result = {
        'year': year,
        'period': {'start': start_date.isoformat(), 'end': end_date.isoformat(),
                   'days': days, 'sampling_utc': '00/06/12/18'},
        'control_volume': {'lat': [25.0, 40.0], 'lon': [70.0, 105.0],
                           'vertical': '1-1000 hPa, surface-masked, no extrapolation'},
        'cloud_water_definition': 'Qh = clwc + ciwc + crwc + cswc',
        'terms_kg': {
            'qv_init': float(terms.qv_init), 'qv_final': float(terms.qv_final),
            'qh_init': float(terms.qh_init), 'qh_final': float(terms.qh_final),
            'qv_in': float(terms.qv_in), 'qv_out': float(terms.qv_out),
            'qh_in': float(terms.qh_in), 'qh_out': float(terms.qh_out),
            'rain_kg': float(precip), 'duration_s': float(terms.duration_s),
        },
        'evaluation': eval_,
        'mean_inventory_kg': mean_inventory_kg,
        'renewal_period_method': (
            'annual mean of monthly (start+end)/2 inventories, weighted by month length'),
        'residuals_kg': {k: float(v) for k, v in residuals.items()},
        'sanity_check': sanity,
        'evaporation_observed_kg': float(evap_obs),
        'evaporation_derived_total_kg': evap_from_total,
        'evaporation_difference_kg': float(evap_obs - evap_from_total),
        'boundary_start': boundary_start,
        'boundary_end': boundary_end,
        'monthly_diagnostics': months,
    }
    out = ROOT / 'annual' / f'{year:04d}_budget.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    # Monthly-mean maps/profiles for figures.
    arrays = {}
    month_labels = []
    for month in range(1, 13):
        token = f'{year:04d}{month:02d}'
        p = (_verified_override(token, 'fields')
             or ROOT / 'monthly' / f'{token}_fields.nc')
        with xr.open_dataset(p) as ds:
            month_labels.append(month)
            for key in ('qv', 'clwc', 'ciwc', 'crwc', 'cswc', 'qh'):
                map_name = f'{key}_col'
                prof_name = f'{key}_profile'
                arrays.setdefault(map_name, []).append(
                    ds[map_name].mean(dim='day').values.astype('float32'))
                arrays.setdefault(prof_name, []).append(
                    ds[prof_name].mean(dim='day').values.astype('float32'))
            lat = ds.latitude.values
            lon = ds.longitude.values
            level = ds.level.values
    data_vars = {}
    for name, values in arrays.items():
        arr = np.asarray(values)
        if name.endswith('_col'):
            data_vars[name] = (('month', 'latitude', 'longitude'), arr)
        else:
            data_vars[name] = (('month', 'level'), arr)
    ds = xr.Dataset(
        data_vars,
        coords={'month': np.arange(1, 13), 'latitude': lat, 'longitude': lon, 'level': level},
        attrs={
            'year': year,
            'qh_definition': 'clwc+ciwc+crwc+cswc',
            'sampling': '4 synoptic times/day; monthly values are daily means',
            'source': 'NSF NCAR RDA d633000/d633001; no CDS',
        },
    )
    annual_path = ROOT / 'annual' / f'{year:04d}_fields.nc'
    ds.to_netcdf(annual_path, encoding={name: {'zlib': True, 'complevel': 3}
                                        for name in ds.data_vars})
    ds.close()
    result['fields_file'] = str(annual_path)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({
        'year': year,
        'gcwr_kg': float(eval_['gcwr_kg']),
        'gcwr_identity_ok': bool(eval_['gcwr_identity_ok']),
        'sanity_ok': bool(sanity['ok']),
        'sanity_flags': sanity['flags'],
        'Em': eval_['Em'], 'Eh': eval_['Eh'],
        'Tv_days': eval_['Tv_days'], 'Th_hours': eval_['Th_hours'],
    }, ensure_ascii=False))
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--year', type=int, required=True)
    args = ap.parse_args()
    assemble_year(args.year)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
