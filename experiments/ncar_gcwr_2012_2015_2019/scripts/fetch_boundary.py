#!/usr/bin/env python3
"""Fetch and reduce annual start/end inventory snapshots."""
from __future__ import annotations

import argparse
import calendar
import hashlib
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import xarray as xr

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import fetch_month as fm  # noqa: E402

from dbas.scanner.scan import scan_metadata_one  # noqa: E402
from dbas_core.catalog.repository import Catalog  # noqa: E402
from researchdatahub.core.models import (  # noqa: E402
    DatasetRequest,
    DatasetMetadata,
    GridSpec,
    IntegrityCheckKind,
    SpatialExtent,
    TemporalExtent,
    VariableSpec,
    VerticalLevelKind,
    VerticalLevels,
)
from researchdatahub.cli._services import load_context  # noqa: E402


def _sp_day_url(date: datetime) -> str:
    last = calendar.monthrange(date.year, date.month)[1]
    ymd0 = f'{date.year:04d}{date.month:02d}01'
    ymd1 = f'{date.year:04d}{date.month:02d}{last:02d}'
    name = f'e5.oper.an.sfc.128_134_sp.ll025sc.{ymd0}00_{ymd1}23.nc'
    base = f'https://tds.gdex.ucar.edu/thredds/ncss/grid/files/d633000/e5.oper.an.sfc/{date.year:04d}{date.month:02d}/{name}'
    ts = date.strftime('%Y-%m-%dT%H:%M:%SZ')
    return (f'{base}?var=SP&north=40&west=70&east=105&south=25&horizStride=1'
            f'&time_start={ts}&time_end={ts}&timeStride=1&accept=netcdf')



def _dbas_files(dataset_id: str) -> list[Path]:
    import sqlite3
    with sqlite3.connect(fm.DBAS_DB) as db:
        row = db.execute("SELECT last_mount_path FROM volumes WHERE volume_id='downloads'").fetchone()
        if not row or not row[0]:
            raise RuntimeError('downloads volume missing/offline in DBAS')
        root = Path(row[0])
        rows = db.execute(
            "SELECT rel_path FROM files WHERE volume_id='downloads' AND dataset_id=? "
            "AND status='active' ORDER BY rel_path", (dataset_id,)
        ).fetchall()
    return [root / r[0] for r in rows]



G = 9.80665
SPECIES = ('clwc', 'ciwc', 'crwc', 'cswc')
R_EARTH = 6_371_000.0


def _cell_area(lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    import math
    dlat = math.radians(abs(lat[1] - lat[0])) if lat.size > 1 else math.radians(0.25)
    dlon = math.radians(abs(lon[1] - lon[0])) if lon.size > 1 else math.radians(0.25)
    return R_EARTH**2 * np.cos(np.deg2rad(lat))[:, None] * dlat * dlon * np.ones((1, lon.size))


def _layer_mass(levels_pa: np.ndarray, sp_pa: np.ndarray) -> np.ndarray:
    levels = np.asarray(levels_pa, dtype='float64')
    edges = np.empty(levels.size + 1)
    edges[0] = levels[0]
    edges[-1] = levels[-1]
    edges[1:-1] = 0.5 * (levels[:-1] + levels[1:])
    lo = edges[:-1, None, None]
    hi = edges[1:, None, None]
    bottom = np.minimum(np.asarray(sp_pa, dtype='float64'), levels[-1])
    return np.clip(np.minimum(hi, bottom[None]) - lo, 0.0, None) / G


def fetch_boundary(date: datetime, workers: int = 10) -> dict:
    tag = date.strftime('%Y%m%d')
    request_id = f'gcwr-ncar-boundary-{tag}'
    source_id = f'ncar-gcwr-boundary-{tag}'
    dataset_id = f'era5_gcwr_boundary_{tag}'
    vars_ = [VariableSpec(name=v[0], units=u) for v in fm.PRESSURE_VARS for u in [v[4]]]
    vars_.append(VariableSpec(name='sp', units='Pa'))
    request = DatasetRequest(
        request_id=request_id,
        dataset_id='era5-pressure-levels',
        metadata=DatasetMetadata(
            product='ERA5', product_type='reanalysis', variables=vars_,
            temporal_coverage=TemporalExtent(start=date, end=date + timedelta(days=1)),
            spatial_extent=SpatialExtent(west=70.0, south=25.0, east=105.0, north=40.0,
                                         grid_degrees=0.25),
            vertical_levels=VerticalLevels(kind=VerticalLevelKind.PRESSURE,
                                           levels=fm.LEVELS_HPA, units='hPa'),
            grid=GridSpec(resolution_degrees=0.25, projection='regular_latlon',
                          regridded=False, source_grid='era5-native-0.25'),
            time_definition='utc_6hourly', data_version='ncar-rda-d633000',
            post_processing=['NCAR THREDDS NetcdfSubset boundary snapshot'],
            regridded=False, units_normalized=False,
            extensions={'ncar.no_cds': True, 'ncar.boundary': True},
        ),
        preferred_sources=[source_id], max_sources=1,
        checks=[IntegrityCheckKind.CHECKSUM_MATCH, IntegrityCheckKind.FORMAT_SNIFF,
                IntegrityCheckKind.NETCDF_OPENABLE],
        preserve_original=True, priority='normal',
        extensions={'provenance.note': 'NSF NCAR GDEX/RDA only; no CDS download.'},
    )
    now = datetime.now(UTC)
    assets = []
    for short, code, ncar_var, suffix, _units in fm.PRESSURE_VARS:
        url = fm._pressure_url(date.year, date.month, date.day, code, ncar_var, suffix)
        name = f'ncar_gcwr_boundary_{tag}_{short}_tp_4x6h_ncss.nc'
        assets.append(fm._asset(source_id, dataset_id, name, url, short, now,
                                TemporalExtent(start=date, end=date + timedelta(days=1)),
                                fm.LEVELS_HPA))
    sp_url = _sp_day_url(date)
    assets.append(fm._asset(source_id, dataset_id, f'ncar_gcwr_boundary_{tag}_sp_tp_ncss.nc',
                            sp_url, 'sp', now, TemporalExtent(start=date, end=date + timedelta(days=1))))
    request_file = fm.ROOT / 'requests' / f'boundary_{tag}.yaml'
    fm._request_yaml(request, request_file)
    fm.ensure_rdh_state()
    context = load_context()
    run = fm._run_scheduler(context, request, assets, workers)
    fm._rdh_report(request_id, run['plan_id'])
    imported = fm._import_to_dbas(date.year, date.month, run['plan_id'], request_file, dataset_id)
    # reduce start inventory (first synoptic time) after DBAS parse
    files = _dbas_files(dataset_id)
    by_var = {}
    for p in files:
        if p.name.endswith('_sp_tp_ncss.nc'):
            by_var['sp'] = p
        else:
            for short, *_ in fm.PRESSURE_VARS:
                if f'_{short}_tp_4x6h_ncss.nc' in p.name:
                    by_var[short] = p
                    break
    if len(by_var) != 10:
        raise RuntimeError(f'boundary files incomplete: {sorted(by_var)}')
    data = {}
    for short, path in by_var.items():
        with xr.open_dataset(path) as ds:
            arr = ds[short.upper()].isel(time=0).values.astype('float64')
            lat = ds['latitude'].values.astype('float64')
            lon = ds['longitude'].values.astype('float64')
            lev = (ds['level'].values.astype('float64') * 100.0
                   if 'level' in ds.coords else None)
        if lat[0] > lat[-1]:
            arr = arr[..., ::-1, :] if arr.ndim == 3 else arr[::-1, :]
            lat = lat[::-1]
        if lon[0] > lon[-1]:
            arr = arr[..., ::-1] if arr.ndim == 3 else arr[:, ::-1]
            lon = lon[::-1]
        data[short] = arr
        if short == 'sp':
            data['lat'], data['lon'] = lat, lon
        else:
            data['level'] = lev
    area = _cell_area(data['lat'], data['lon'])
    layer = _layer_mass(data['level'], data['sp'])
    qv = data['q'] * layer
    species = [data[s] * layer for s in SPECIES]
    qh = sum(species)
    out = {
        'date': date.isoformat(), 'dataset_id': dataset_id,
        'qv_kg': float(np.nansum(qv * area)),
        'qh_kg': float(np.nansum(qh * area)),
        'species_kg': {s: float(np.nansum(v * area)) for s, v in zip(SPECIES, species)},
        'files': sorted(str(p) for p in files),
        'dbas': imported,
        'computed_at': datetime.now(UTC).isoformat(),
    }
    path = fm.ROOT / 'state' / f'boundary_{tag}.json'
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: out[k] for k in ('date', 'qv_kg', 'qh_kg', 'species_kg')}))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--date', required=True, help='YYYY-MM-DD')
    ap.add_argument('--workers', type=int, default=10)
    args = ap.parse_args()
    fetch_boundary(datetime.strptime(args.date, '%Y-%m-%d').replace(tzinfo=UTC), args.workers)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
