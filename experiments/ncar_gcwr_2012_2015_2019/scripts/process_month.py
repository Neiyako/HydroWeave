#!/usr/bin/env python3
"""Compute monthly GCWR components from NCAR slices registered in DBAS."""
from __future__ import annotations

import argparse
import calendar
import hashlib
import json
import math
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import xarray as xr

ROOT = Path(__file__).resolve().parents[1]
DBAS_ROOT = Path(os.environ.get('DBAS_ROOT', '/Users/apple/Desktop/era5数据dbas'))
DBAS_DB = Path(os.environ.get('DBAS_DB', DBAS_ROOT / 'data' / 'catalog.db'))
G = 9.80665
R_EARTH = 6_371_000.0
DT_SECONDS = 6 * 3600.0
SPECIES = ('clwc', 'ciwc', 'crwc', 'cswc')
OVERRIDE_FILE = ROOT / 'repairs' / 'source_overrides.json'

# Physical plausibility gates for ERA5 pressure-level fields. These are wide
# enough for the full global range but catch packed-value or NCSS corruption
# that still produces an openable NetCDF file.
PHYSICAL_LIMITS = {
    'T': (150.0, 350.0),
    'Q': (-1.0e-4, 0.1),
    'U': (-200.0, 200.0),
    'V': (-200.0, 200.0),
    'W': (-200.0, 200.0),
    'CLWC': (-1.0e-4, 0.1),
    'CIWC': (-1.0e-4, 0.1),
    'CRWC': (-1.0e-4, 0.1),
    'CSWC': (-1.0e-4, 0.1),
    'SP': (10_000.0, 110_000.0),
    'MTPR': (-0.1, 0.1),
    'MER': (-0.1, 0.1),
}


def _volume_root(db: sqlite3.Connection) -> Path:
    row = db.execute("SELECT last_mount_path FROM volumes WHERE volume_id='downloads'").fetchone()
    if not row or not row[0]:
        raise RuntimeError('downloads volume missing/offline in DBAS')
    return Path(row[0])


def _catalog_files(dataset_id: str) -> list[Path]:
    with sqlite3.connect(DBAS_DB) as db:
        root = _volume_root(db)
        rows = db.execute(
            "SELECT rel_path FROM files WHERE volume_id='downloads' AND dataset_id=? "
            "AND status='active' ORDER BY rel_path", (dataset_id,)
        ).fetchall()
    files = [root / r[0] for r in rows]
    if not OVERRIDE_FILE.exists():
        return files
    payload = json.loads(OVERRIDE_FILE.read_text(encoding='utf-8'))
    overrides = payload.get(dataset_id, {})
    resolved: list[Path] = []
    for path in files:
        override = overrides.get(path.name)
        if override is None:
            resolved.append(path)
            continue
        replacement = ROOT / override['replacement']
        if not replacement.exists():
            raise RuntimeError(f'修复文件不存在: {replacement}')
        expected = override.get('sha256')
        if expected:
            actual = hashlib.sha256(replacement.read_bytes()).hexdigest()
            if actual != expected:
                raise RuntimeError(
                    f'修复文件哈希不匹配: {replacement.name} {actual} != {expected}')
        resolved.append(replacement)
    return resolved


def _validate_physical_range(name: str, values: np.ndarray, path: Path) -> None:
    finite = np.isfinite(values)
    if not finite.any():
        raise ValueError(f'{path.name}: {name} 没有任何有限值')
    lo, hi = PHYSICAL_LIMITS[name]
    vmin = float(np.min(values[finite]))
    vmax = float(np.max(values[finite]))
    if vmin < lo or vmax > hi:
        raise ValueError(
            f'{path.name}: {name} 超出物理合理范围 [{lo}, {hi}]，'
            f'实际为 [{vmin}, {vmax}]；拒绝据此生成科学结论')


def _parse_month_files(files: list[Path], year: int, month: int) -> tuple[dict[str, dict[str, dict[str, Path]]], dict[str, Path]]:
    token = f'{year:04d}{month:02d}'
    by_day: dict[str, dict[str, dict[str, Path]]] = {}
    monthly: dict[str, Path] = {}
    for path in files:
        name = path.name
        if f'ncar_gcwr_{token}_sp_' in name:
            monthly['sp'] = path
            continue
        for flux in ('mtpr', 'mer'):
            if f'ncar_gcwr_{token}_{flux}_' in name:
                monthly[flux] = path
                break
        else:
            parts = name.split('_')
            if len(parts) < 3 or not parts[2].startswith(token):
                continue
            ymd = parts[2]
            var = parts[3]
            by_day.setdefault(ymd, {})[var] = path
    return by_day, monthly


def _open_field(path: Path, name: str) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    with xr.open_dataset(path, decode_times=True) as ds:
        var = ds[name].load()
        da = var.values
        lat_name = 'latitude' if 'latitude' in ds.coords else 'lat'
        lon_name = 'longitude' if 'longitude' in ds.coords else 'lon'
        lat = ds[lat_name].values.astype('float64')
        lon = ds[lon_name].values.astype('float64')
        level = ds['level'].values.astype('float64') * 100.0 if 'level' in ds.coords else None
        time = ds['time'].values if 'time' in ds.coords else None
    da = np.asarray(da, dtype='float64')
    _validate_physical_range(name, da, path)
    if name in {'Q', 'CLWC', 'CIWC', 'CRWC', 'CSWC'}:
        # ERA5 packing/interpolation can leave tiny negative mixing ratios.
        # Treat these as numerical zero after the wide physical-range gate.
        da = np.maximum(da, 0.0)
    if level is not None:
        level = np.asarray(level, dtype='float64')
        if level.ndim != 1 or level.size < 2 or not np.all(np.isfinite(level)):
            raise ValueError(f'{path.name}: 气压层坐标无效')
        if np.any(np.diff(level) == 0):
            raise ValueError(f'{path.name}: 气压层存在重复值')
        if da.ndim < 2 or da.shape[1] != level.size:
            raise ValueError(f'{path.name}: {name} 维度 {da.shape} 与气压层数 {level.size} 不匹配')
        if level[0] > level[-1]:
            da = np.flip(da, axis=1)
            level = level[::-1]
    if lat[0] > lat[-1]:
        da = da[..., ::-1, :]
        lat = lat[::-1]
    if lon[0] > lon[-1]:
        da = da[..., ::-1]
        lon = lon[::-1]
    return da, lat, lon, np.asarray(level), time


def _cell_area(lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    dlat = math.radians(abs(lat[1] - lat[0])) if lat.size > 1 else math.radians(0.25)
    dlon = math.radians(abs(lon[1] - lon[0])) if lon.size > 1 else math.radians(0.25)
    return R_EARTH**2 * np.cos(np.deg2rad(lat))[:, None] * dlat * dlon * np.ones((1, lon.size))


def _pressure_layer_kg_m2(levels_pa: np.ndarray, sp_pa: np.ndarray) -> np.ndarray:
    """Layer mass per m2 for pressure centers, masked at the actual surface."""
    levels = np.asarray(levels_pa, dtype='float64')
    if levels.ndim != 1 or levels.size < 2 or not np.all(np.isfinite(levels)):
        raise ValueError('气压层必须是有限的至少二维向量')
    if np.any(np.diff(levels) <= 0):
        raise ValueError('气压层必须严格递增；调用方应先统一坐标方向')
    edges = np.empty(levels.size + 1)
    edges[0] = levels[0]
    edges[-1] = levels[-1]
    edges[1:-1] = 0.5 * (levels[:-1] + levels[1:])
    lo = edges[:-1, None, None]
    hi = edges[1:, None, None]
    bottom = np.minimum(np.asarray(sp_pa, dtype='float64'), levels[-1])
    thickness = np.clip(np.minimum(hi, bottom[None, :, :]) - lo, 0.0, None)
    return thickness / G


def _area_weighted_mean(field: np.ndarray, area: np.ndarray) -> float:
    values = np.asarray(field, dtype='float64')
    good = np.isfinite(values)
    if not good.any():
        return float('nan')
    return float(np.sum(values[good] * area[good]) / np.sum(area[good]))


def _mass_weighted_profile(field: np.ndarray, layer_kg: np.ndarray,
                           area: np.ndarray) -> np.ndarray:
    """Layer-mass and area weighted profile; below-surface cells have zero mass."""
    values = np.asarray(field, dtype='float64')
    weights = np.asarray(layer_kg, dtype='float64') * area[None, :, :]
    if values.shape != weights.shape:
        raise ValueError(f'profile shape {values.shape} != mass weight shape {weights.shape}')
    good = np.isfinite(values) & np.isfinite(weights) & (weights > 0.0)
    num = np.sum(np.where(good, values * weights, 0.0), axis=(0, 2, 3))
    den = np.sum(np.where(good, weights, 0.0), axis=(0, 2, 3))
    return np.divide(num, den, out=np.full_like(num, np.nan), where=den > 0)


def _split_signed(arr: np.ndarray) -> tuple[float, float]:
    x = np.asarray(arr, dtype='float64')
    return float(np.nansum(np.maximum(-x, 0.0))), float(np.nansum(np.maximum(x, 0.0)))


def _boundary_flux_one_time(fields: dict[str, np.ndarray], layer_kg: np.ndarray,
                            area: np.ndarray, lat: np.ndarray, lon: np.ndarray,
                            t_index: int) -> dict[str, float]:
    level = fields['level']
    q = fields['q'][t_index]
    u = fields['u'][t_index]
    v = fields['v'][t_index]
    w = fields['w'][t_index]
    qh = sum(fields[s][t_index] for s in SPECIES)
    dlat = math.radians(abs(lat[1] - lat[0]))
    dlon = math.radians(abs(lon[1] - lon[0]))
    dy = R_EARTH * dlat * np.ones(lat.size)
    dx_s = R_EARTH * dlon * math.cos(math.radians(float(lat[0])))
    dx_n = R_EARTH * dlon * math.cos(math.radians(float(lat[-1])))
    west = layer_kg[:, :, 0] * dy[None, :]
    east = layer_kg[:, :, -1] * dy[None, :]
    south = layer_kg[:, 0, :] * dx_s
    north = layer_kg[:, -1, :] * dx_n
    signed_qv = np.concatenate([
        (q[:, :, 0] * u[:, :, 0] * (-1.0) * west).ravel(),
        (q[:, :, -1] * u[:, :, -1] * east).ravel(),
        (q[:, 0, :] * v[:, 0, :] * (-1.0) * south).ravel(),
        (q[:, -1, :] * v[:, -1, :] * north).ravel(),
    ]) * DT_SECONDS
    signed_qh = np.concatenate([
        (qh[:, :, 0] * u[:, :, 0] * (-1.0) * west).ravel(),
        (qh[:, :, -1] * u[:, :, -1] * east).ravel(),
        (qh[:, 0, :] * v[:, 0, :] * (-1.0) * south).ravel(),
        (qh[:, -1, :] * v[:, -1, :] * north).ravel(),
    ]) * DT_SECONDS
    qv_in, qv_out = _split_signed(signed_qv)
    qh_in, qh_out = _split_signed(signed_qh)
    # ERA5 w is dp/dt: positive is downward. At the top face, -w is therefore
    # the outward (upward-positive) mass flux.
    qv_top = -q[0] * w[0] / G * area * DT_SECONDS
    qh_top = -qh[0] * w[0] / G * area * DT_SECONDS
    qv_tin, qv_tout = _split_signed(qv_top)
    qh_tin, qh_tout = _split_signed(qh_top)
    return {
        'qv_in': qv_in + qv_tin, 'qv_out': qv_out + qv_tout,
        'qh_in': qh_in + qh_tin, 'qh_out': qh_out + qh_tout,
        'qv_top_in': qv_tin, 'qv_top_out': qv_tout,
        'qh_top_in': qh_tin, 'qh_top_out': qh_tout,
    }


def _monthly_rate_total(path: Path, var: str, seconds: float) -> tuple[float, float]:
    with xr.open_dataset(path, decode_times=True) as ds:
        arr = ds[var].squeeze(drop=True)
        da = np.asarray(arr.values, dtype='float64')
        lat = ds['latitude'].values.astype('float64')
        lon = ds['longitude'].values.astype('float64')
    _validate_physical_range(var, da, path)
    if lat[0] > lat[-1]:
        da = da[..., ::-1, :]
        lat = lat[::-1]
    if lon[0] > lon[-1]:
        da = da[..., ::-1]
        lon = lon[::-1]
    area = _cell_area(lat, lon)
    if da.ndim == 2:
        mean = _area_weighted_mean(da, area)
        total = float(np.nansum(da * area)) * seconds
    elif da.ndim == 3 and da.shape[0] == 1:
        mean = _area_weighted_mean(da[0], area)
        total = float(np.nansum(da[0] * area)) * seconds
    else:
        raise ValueError(f'{path}: unexpected rate shape {da.shape}')
    return mean, total


def process_month(year: int, month: int, output_suffix: str = '') -> dict:
    dataset_id = f'era5_gcwr_{year:04d}{month:02d}'
    files = _catalog_files(dataset_id)
    by_day, monthly = _parse_month_files(files, year, month)
    last_day = calendar.monthrange(year, month)[1]
    missing_days = [d for d in range(1, last_day + 1)
                    if f'{year:04d}{month:02d}{d:02d}' not in by_day]
    if missing_days:
        raise RuntimeError(f'{dataset_id}: missing days {missing_days}')
    required_monthly = {'sp', 'mtpr', 'mer'}
    if not required_monthly <= set(monthly):
        raise RuntimeError(f'{dataset_id}: missing monthly assets {required_monthly - set(monthly)}')

    sp_da, lat, lon, _sp_level, sp_time = _open_field(monthly['sp'], 'SP')
    first_day = f'{year:04d}{month:02d}01'
    _, lat_p, lon_p, level, _ = _open_field(by_day[first_day]['t'], 'T')
    if not (np.array_equal(lat, lat_p) and np.array_equal(lon, lon_p)):
        raise ValueError(f'{dataset_id}: SP grid differs from pressure-level grid')
    if sp_da.ndim == 3 and sp_da.shape[0] == 1:
        sp_da = np.repeat(sp_da, 4 * last_day, axis=0)
    if sp_da.shape[0] != 4 * last_day:
        raise ValueError(f'{dataset_id}: SP time count {sp_da.shape[0]} != {4 * last_day}')
    if not np.all(np.isfinite(sp_da)) or np.any(sp_da <= 0) or np.any(sp_da > 110_000.0):
        raise ValueError(f'{dataset_id}: SP 包含非有限值或超出 0–110000 Pa')
    area = _cell_area(lat, lon)
    maps: dict[str, list[np.ndarray]] = {k: [] for k in ('qv',) + SPECIES + ('qh',)}
    profiles: dict[str, list[np.ndarray]] = {k: [] for k in ('qv',) + SPECIES + ('qh',)}
    daily_flux: list[dict[str, float]] = []
    qv_start = qh_start = None
    qv_end = qh_end = None
    total_flux = {k: 0.0 for k in ('qv_in', 'qv_out', 'qh_in', 'qh_out',
                                    'qv_top_in', 'qv_top_out', 'qh_top_in', 'qh_top_out')}

    level_hpa = level / 100.0
    for day in range(1, last_day + 1):
        ymd = f'{year:04d}{month:02d}{day:02d}'
        paths = by_day[ymd]
        missing_vars = set(v for v, *_ in [
            ('t',), ('q',), ('u',), ('v',), ('w',), ('clwc',), ('ciwc',), ('crwc',), ('cswc',)
        ]) - set(paths)
        if missing_vars:
            raise RuntimeError(f'{dataset_id} {ymd}: missing vars {missing_vars}')
        fields: dict[str, np.ndarray] = {'level': level}
        for short in ('t', 'q', 'u', 'v', 'w', *SPECIES):
            arr, la, lo, lv, _tm = _open_field(paths[short], short.upper())
            if not (np.array_equal(la, lat) and np.array_equal(lo, lon) and np.allclose(lv, level)):
                raise ValueError(f'{dataset_id} {ymd} {short}: grid mismatch')
            if arr.shape[0] != 4:
                raise ValueError(f'{dataset_id} {ymd} {short}: time count {arr.shape[0]} != 4')
            fields[short] = arr
        tidx0 = 4 * (day - 1)
        layer_kg = np.stack([
            _pressure_layer_kg_m2(level, sp_da[tidx0 + k])
            for k in range(4)
        ], axis=0)
        # columns and profiles for the four synoptic hours
        columns = {}
        for name, arr in (('qv', fields['q']),
                          ('clwc', fields['clwc']), ('ciwc', fields['ciwc']),
                          ('crwc', fields['crwc']), ('cswc', fields['cswc'])):
            columns[name] = np.sum(arr * layer_kg, axis=1)
        columns['qh'] = sum(columns[s] for s in SPECIES)
        for name in maps:
            maps[name].append(columns[name].mean(axis=0))
            if name == 'qh':
                day_field = sum(fields[s] for s in SPECIES)
            elif name == 'qv':
                day_field = fields['q']
            else:
                day_field = fields[name]
            profiles[name].append(_mass_weighted_profile(day_field, layer_kg, area))
        day_flux = {k: 0.0 for k in total_flux}
        for k in range(4):
            single = _boundary_flux_one_time(fields, layer_kg[k], area, lat, lon, k)
            for key, value in single.items():
                day_flux[key] += value
                total_flux[key] += value
        daily_flux.append(day_flux)
        if day == 1:
            qv_start = float(np.nansum(columns['qv'][0] * area))
            qh_start = float(np.nansum(columns['qh'][0] * area))
        if day == last_day:
            qv_end = float(np.nansum(columns['qv'][-1] * area))
            qh_end = float(np.nansum(columns['qh'][-1] * area))

    seconds = float(last_day * 86400.0)
    mtpr_mean, precip_kg = _monthly_rate_total(monthly['mtpr'], 'MTPR', seconds)
    mer_mean, mer_integral = _monthly_rate_total(monthly['mer'], 'MER', seconds)
    evap_factor = -1.0 if mer_mean < 0 else 1.0
    evap_kg = evap_factor * mer_integral

    # Write daily-mean maps and profiles.
    day_coord = np.arange(1, last_day + 1)
    data_vars = {}
    for name in maps:
        data_vars[f'{name}_col'] = (('day', 'latitude', 'longitude'),
                                     np.asarray(maps[name], dtype='float32'))
        data_vars[f'{name}_profile'] = (('day', 'level'),
                                         np.asarray(profiles[name], dtype='float32'))
    out_ds = xr.Dataset(
        data_vars,
        coords={'day': day_coord, 'latitude': lat, 'longitude': lon, 'level': level_hpa},
        attrs={
            'dataset_id': dataset_id,
            'region': '25-40N,70-105E',
            'times_per_day_utc': '00,06,12,18',
            'qh_definition': 'clwc+ciwc+crwc+cswc',
            'no_extrapolation': 'pressure layer weights clipped at surface pressure',
            'source': 'NSF NCAR RDA d633000/d633001; no CDS',
        },
    )
    out_dir = ROOT / 'monthly'
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f'{year:04d}{month:02d}_fields{output_suffix}.nc'
    tmp_path = out_path.with_suffix(out_path.suffix + '.tmp')
    out_ds.to_netcdf(tmp_path, encoding={name: {'zlib': True, 'complevel': 3}
                                          for name in out_ds.data_vars})
    out_ds.close()
    os.replace(tmp_path, out_path)

    summary = {
        'year': year, 'month': month, 'dataset_id': dataset_id,
        'days': last_day, 'files': len(files), 'duration_s': seconds,
        'boundary_kg': total_flux,
        'qv_start_kg': qv_start, 'qh_start_kg': qh_start,
        'qv_end_kg': qv_end, 'qh_end_kg': qh_end,
        'precip_kg': precip_kg, 'mtpr_area_mean_kg_m2_s': mtpr_mean,
        'evap_obs_kg': evap_kg, 'mer_area_mean_kg_m2_s': mer_mean,
        'mer_sign_factor': evap_factor,
        'daily_flux': daily_flux,
        'fields_file': str(out_path),
        'processed_at': datetime.now(UTC).isoformat(),
    }
    state_path = ROOT / 'state' / f'{year:04d}{month:02d}_budget{output_suffix}.json'
    tmp_state = state_path.with_suffix(state_path.suffix + '.tmp')
    tmp_state.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    os.replace(tmp_state, state_path)
    print(json.dumps(summary, ensure_ascii=False))
    return summary


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--year', type=int, required=True)
    ap.add_argument('--month', type=int, required=True)
    ap.add_argument('--output-suffix', default='',
                    help='写入带后缀的 fields/budget 文件，先验证再替换正式产物')
    args = ap.parse_args()
    process_month(args.year, args.month, args.output_suffix)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
