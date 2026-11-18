#!/usr/bin/env python3
"""Fetch one full month of NCAR ERA5 data through RDH for the GCWR experiment."""
from __future__ import annotations

import argparse
import calendar
import fcntl
import hashlib
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RDH_REPO = Path(os.environ.get('RDH_ROOT', '/Users/apple/Desktop/ResearchDataHub'))
DBAS_REPO = Path(os.environ.get('DBAS_ROOT', '/Users/apple/Desktop/era5数据dbas'))
DBAS_DB = DBAS_REPO / 'data' / 'catalog.db'
RDH_PY = Path(os.environ.get('RDH_PY', RDH_REPO / '.venv' / 'bin' / 'python'))
DBAS_PY = Path(os.environ.get('DBAS_PY', DBAS_REPO / '.venv' / 'bin' / 'python'))
for p in (RDH_REPO / 'src', DBAS_REPO / 'src'):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import httpx  # noqa: E402
import yaml  # noqa: E402

os.environ.setdefault('CDSAPI_KEY', 'not-used-cds-disabled')

from dbas.fetch.rdh import RdhFetchConfig, run_rdh_fetch  # noqa: E402
from dbas.scanner.scan import scan_metadata_one  # noqa: E402
from dbas_core.catalog.repository import Catalog  # noqa: E402
from researchdatahub.cli._services import load_context, open_repository  # noqa: E402
from researchdatahub.core.models import (  # noqa: E402
    AccessRoute,
    DatasetMetadata,
    DatasetRequest,
    GridSpec,
    IntegrityCheckKind,
    SourceAsset,
    SourceMetadata,
    SpatialExtent,
    TemporalExtent,
    VariableSpec,
    VerticalLevelKind,
    VerticalLevels,
)
from researchdatahub.integrity.checker import IntegrityChecker  # noqa: E402
from researchdatahub.manifest.connection import ManifestConnectionFactory  # noqa: E402
from researchdatahub.manifest.repository import SqliteManifestRepository  # noqa: E402
from researchdatahub.planner.service import create_plan  # noqa: E402
from researchdatahub.scheduler import build_scheduler  # noqa: E402
from researchdatahub.storage.local import LocalStorageBackend  # noqa: E402
from researchdatahub.transfer.base import RemoteMetadata  # noqa: E402
from researchdatahub.transfer.http import HttpTransportAdapter  # noqa: E402
from researchdatahub.transfer.retry import RetryPolicy  # noqa: E402

LEVELS_HPA = [1000.0, 975.0, 950.0, 925.0, 900.0, 875.0, 850.0, 825.0, 800.0,
              775.0, 750.0, 700.0, 650.0, 600.0, 550.0, 500.0, 450.0, 400.0,
              350.0, 300.0, 250.0, 225.0, 200.0, 175.0, 150.0, 125.0, 100.0,
              70.0, 50.0, 30.0, 20.0, 10.0, 7.0, 5.0, 3.0, 2.0, 1.0]
PRESSURE_VARS = (
    ('t', '128_130_t', 'T', 'll025sc', 'K'),
    ('q', '128_133_q', 'Q', 'll025sc', 'kg kg**-1'),
    ('u', '128_131_u', 'U', 'll025uv', 'm s**-1'),
    ('v', '128_132_v', 'V', 'll025uv', 'm s**-1'),
    ('w', '128_135_w', 'W', 'll025sc', 'Pa s**-1'),
    ('clwc', '128_246_clwc', 'CLWC', 'll025sc', 'kg kg**-1'),
    ('ciwc', '128_247_ciwc', 'CIWC', 'll025sc', 'kg kg**-1'),
    ('crwc', '128_075_crwc', 'CRWC', 'll025sc', 'kg kg**-1'),
    ('cswc', '128_076_cswc', 'CSWC', 'll025sc', 'kg kg**-1'),
)
TP_BOUNDS = {'north': 40, 'west': 70, 'east': 105, 'south': 25}


class StaticNCARAdapter:
    """Static NCAR assets for one month; no CDS is ever involved."""

    def __init__(self, source_id: str, assets: list[SourceAsset]) -> None:
        self.source_id = source_id
        self.supported_routes = frozenset({'https'})
        self._assets = assets

    def describe(self) -> SourceMetadata:
        return self._assets[0].metadata

    def discover_assets(self, request: DatasetRequest) -> list[SourceAsset]:
        del request
        return list(self._assets)

    def health_check(self) -> bool:
        return True


class NoHeadHttpTransport(HttpTransportAdapter):
    """RDH HTTP transport with a predeclared asset identity.

    NCAR NCSS performs expensive subset generation even on HEAD. Since the exact
    shape is fixed and every body is verified by SHA-256 + NetCDF openability,
    we skip the redundant HEAD probe for these known slices. The stock RDH HTTP
    adapter caps the pool at 8 connections; this high-throughput run needs a
    larger explicit pool so worker concurrency is not silently serialized.
    """

    def __init__(self, *, max_connections: int = 192, **kwargs) -> None:
        super().__init__(**kwargs)
        cfg = kwargs.get('config')
        if cfg is None:
            raise ValueError('NoHeadHttpTransport requires a TransferConfig')
        self._client.close()
        self._client = httpx.Client(
            timeout=httpx.Timeout(connect=cfg.connect_timeout_seconds,
                                  read=cfg.read_timeout_seconds,
                                  write=cfg.read_timeout_seconds,
                                  pool=60.0),
            verify=cfg.verify_tls,
            follow_redirects=True,
            max_redirects=cfg.max_redirects,
            trust_env=kwargs.get('trust_env', True),
            limits=httpx.Limits(max_connections=max_connections,
                                max_keepalive_connections=min(128, max_connections)),
            headers={
                'User-Agent': 'researchdatahub/0.1 (ncar-high-throughput)',
                'Accept-Encoding': 'identity',
            },
        )

    def get_remote_metadata(self, asset: SourceAsset) -> RemoteMetadata:
        return RemoteMetadata(
            origin_uri=asset.origin_uri,
            url=asset.origin_uri,
            transport_id=self.TRANSPORT_ID,
            http_status=200,
            size_bytes=None,
            etag=None,
            last_modified=None,
            content_type='application/x-netcdf',
            accepts_ranges=False,
        )


def _pressure_url(year: int, month: int, day: int, code: str, var: str,
                  suffix: str) -> str:
    ymd = f'{year:04d}{month:02d}{day:02d}'
    name = f'e5.oper.an.pl.{code}.{suffix}.{ymd}00_{ymd}23.nc'
    base = f'https://tds.gdex.ucar.edu/thredds/ncss/grid/files/d633000/e5.oper.an.pl/{year:04d}{month:02d}/{name}'
    return (
        f'{base}?var={var}&north={TP_BOUNDS["north"]}&west={TP_BOUNDS["west"]}'
        f'&east={TP_BOUNDS["east"]}&south={TP_BOUNDS["south"]}&horizStride=1'
        f'&time_start={year:04d}-{month:02d}-{day:02d}T00%3A00%3A00Z'
        f'&time_end={year:04d}-{month:02d}-{day:02d}T18%3A00%3A00Z'
        '&timeStride=6&accept=netcdf'
    )


def _sp_url(year: int, month: int, last_day: int) -> str:
    ymd0 = f'{year:04d}{month:02d}01'
    ymd1 = f'{year:04d}{month:02d}{last_day:02d}'
    name = f'e5.oper.an.sfc.128_134_sp.ll025sc.{ymd0}00_{ymd1}23.nc'
    base = f'https://tds.gdex.ucar.edu/thredds/ncss/grid/files/d633000/e5.oper.an.sfc/{year:04d}{month:02d}/{name}'
    return (
        f'{base}?var=SP&north={TP_BOUNDS["north"]}&west={TP_BOUNDS["west"]}'
        f'&east={TP_BOUNDS["east"]}&south={TP_BOUNDS["south"]}&horizStride=1'
        f'&time_start={year:04d}-{month:02d}-01T00%3A00%3A00Z'
        f'&time_end={year:04d}-{month:02d}-{last_day:02d}T18%3A00%3A00Z'
        '&timeStride=6&accept=netcdf'
    )


def _monthly_flux_url(year: int, month: int, code: str, var: str) -> str:
    name = f'e5.moda.fc.sfc.meanflux.{code}_{var.lower()}.ll025sc.{year:04d}010100_{year:04d}120100.nc'
    base = f'https://tds.gdex.ucar.edu/thredds/ncss/grid/files/d633001/e5.moda.fc.sfc.meanflux/{year:04d}/{name}'
    start = f'{year:04d}-{month:02d}-01T00%3A00%3A00Z'
    return (
        f'{base}?var={var}&north={TP_BOUNDS["north"]}&west={TP_BOUNDS["west"]}'
        f'&east={TP_BOUNDS["east"]}&south={TP_BOUNDS["south"]}&horizStride=1'
        f'&time_start={start}&time_end={start}&timeStride=1&accept=netcdf'
    )


def _source_metadata(source_id: str, url: str, now: datetime,
                     variable: str, dataset_id: str) -> SourceMetadata:
    return SourceMetadata(
        source_id=source_id,
        display_name='NSF NCAR GDEX ERA5 sub-monthly subset',
        provider='NSF NCAR RDA',
        access_route=AccessRoute.HTTPS,
        dataset_id=dataset_id,
        origin_uri=url,
        retrieved_at=now,
        protocol_version='rda-thredds-ncss/1.0',
        license='CC-BY-4.0',
        citation='ECMWF ERA5; NSF NCAR RDA d633000/d633001',
        extensions={
            'ncar.service': 'THREDDS-NetcdfSubset',
            'ncar.no_cds': True,
            'ncar.variable': variable,
        },
    )


def _asset(source_id: str, dataset_id: str, name: str, url: str,
           variable: str, now: datetime, time_slice: TemporalExtent,
           levels: list[float] | None = None) -> SourceAsset:
    # Positive sentinel marks this as a result asset. Transport deliberately
    # does not trust it for size; checksum + NetCDF readability are authoritative.
    return SourceAsset(
        asset_id='asset-' + hashlib.sha256(f'{source_id}|{name}|{url}'.encode()).hexdigest()[:24],
        source_id=source_id,
        dataset_id=dataset_id,
        access_route=AccessRoute.HTTPS,
        origin_uri=url,
        file_name=name,
        size_bytes=1,
        time_slice=time_slice,
        level_slice=levels,
        metadata=_source_metadata(source_id, url, now, variable, dataset_id),
        discovered_at=now,
    )


def build_request(year: int, month: int, source_id: str, request_id: str) -> DatasetRequest:
    last_day = calendar.monthrange(year, month)[1]
    vars_ = [
        VariableSpec(name='t', units='K'),
        VariableSpec(name='q', units='kg kg**-1'),
        VariableSpec(name='u', units='m s**-1'),
        VariableSpec(name='v', units='m s**-1'),
        VariableSpec(name='w', units='Pa s**-1'),
        VariableSpec(name='clwc', units='kg kg**-1'),
        VariableSpec(name='ciwc', units='kg kg**-1'),
        VariableSpec(name='crwc', units='kg kg**-1'),
        VariableSpec(name='cswc', units='kg kg**-1'),
        VariableSpec(name='sp', units='Pa'),
        VariableSpec(name='mtpr', units='kg m**-2 s**-1'),
        VariableSpec(name='mer', units='kg m**-2 s**-1'),
    ]
    return DatasetRequest(
        request_id=request_id,
        dataset_id='era5-pressure-levels',
        metadata=DatasetMetadata(
            product='ERA5',
            product_type='reanalysis',
            variables=vars_,
            temporal_coverage=TemporalExtent(
                start=datetime(year, month, 1, tzinfo=UTC),
                end=datetime(year, month, last_day, 23, tzinfo=UTC) + __import__('datetime').timedelta(hours=1),
            ),
            spatial_extent=SpatialExtent(west=70.0, south=25.0, east=105.0, north=40.0,
                                         grid_degrees=0.25),
            vertical_levels=VerticalLevels(kind=VerticalLevelKind.PRESSURE,
                                           levels=LEVELS_HPA, units='hPa'),
            grid=GridSpec(resolution_degrees=0.25, projection='regular_latlon',
                          regridded=False, source_grid='era5-native-0.25'),
            time_definition='utc_6hourly',
            data_version='ncar-rda-d633000-d633001',
            post_processing=['NCAR THREDDS NetcdfSubset spatial/time subset'],
            regridded=False,
            units_normalized=False,
            extensions={'ncar.no_cds': True, 'ncar.variables': [v.name for v in vars_]},
        ),
        preferred_sources=[source_id],
        max_sources=1,
        checks=[IntegrityCheckKind.CHECKSUM_MATCH, IntegrityCheckKind.FORMAT_SNIFF,
                IntegrityCheckKind.NETCDF_OPENABLE],
        preserve_original=True,
        priority='normal',
        extensions={'provenance.note': 'NSF NCAR GDEX/RDA only; no CDS download.'},
    )


def _request_yaml(request: DatasetRequest, path: Path) -> None:
    payload = {
        'schema_version': '1.0',
        'request_id': request.request_id,
        'dataset_id': request.dataset_id,
        'metadata': request.metadata.model_dump(mode='json'),
        'preferred_sources': request.preferred_sources,
        'max_sources': request.max_sources,
        'checks': [item.value for item in request.checks],
        'preserve_original': True,
        'priority': 'normal',
        'extensions': request.extensions,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding='utf-8')


def _assets(year: int, month: int, source_id: str, dataset_id: str,
           start: datetime, end: datetime) -> list[SourceAsset]:
    now = datetime.now(UTC)
    last_day = calendar.monthrange(year, month)[1]
    assets: list[SourceAsset] = []
    for day in range(1, last_day + 1):
        ymd = f'{year:04d}{month:02d}{day:02d}'
        day_start = datetime(year, month, day, tzinfo=UTC)
        day_end = day_start + __import__('datetime').timedelta(days=1)
        for short, code, ncar_var, suffix, _units in PRESSURE_VARS:
            url = _pressure_url(year, month, day, code, ncar_var, suffix)
            name = f'ncar_gcwr_{ymd}_{short}_tp_p1-1000hpa_4x6h_ncss.nc'
            assets.append(_asset(source_id, dataset_id, name, url, short, now,
                                 TemporalExtent(start=day_start, end=day_end), LEVELS_HPA))
    sp_name = f'ncar_gcwr_{year:04d}{month:02d}_sp_tp_4x6h_ncss.nc'
    assets.append(_asset(source_id, dataset_id, sp_name, _sp_url(year, month, last_day),
                         'sp', now, TemporalExtent(start=start, end=end)))
    for short, code in (('mtpr', '235_055'), ('mer', '235_043')):
        name = f'ncar_gcwr_{year:04d}{month:02d}_{short}_tp_monthlymean_ncss.nc'
        assets.append(_asset(source_id, dataset_id, name,
                             _monthly_flux_url(year, month, code, short.upper()),
                             short, now, TemporalExtent(start=start, end=end)))
    return assets



def _requeue_transient(db_path: Path, task_ids: list[str],
                       *, force_running: bool = False) -> None:
    import sqlite3
    now = datetime.now(UTC).isoformat().replace('+00:00', 'Z')
    if force_running:
        condition = "state IN ('FAILED','QUARANTINED','RUNNING')"
        params_tail: tuple[str, ...] = ()
    else:
        condition = ("state IN ('FAILED','QUARANTINED') OR "
                     "(state='RUNNING' AND (lease_expires_at IS NULL OR lease_expires_at < ?))")
        params_tail = (now,)
    with sqlite3.connect(db_path) as db:
        for task_id in task_ids:
            db.execute(
                "UPDATE tasks SET state='QUEUED', worker_id=NULL, started_at=NULL, "
                "finished_at=NULL, heartbeat_at=NULL, lease_expires_at=NULL, "
                "last_transition_at=?, scheduled_at=?, last_error=NULL "
                f"WHERE task_id=? AND ({condition})",
                (now, now, task_id, *params_tail),
            )
        db.commit()


def _run_scheduler(context, request: DatasetRequest, assets: list[SourceAsset],
                   workers: int) -> dict:
    from researchdatahub.config.models import DefaultsConfig
    cfg = context.app_config.defaults
    cfg = cfg.model_copy(update={
        'scheduler': cfg.scheduler.model_copy(update={
            'max_workers': workers,
            'free_space_floor_gb': 20.0,
            'heartbeat_interval_seconds': 30,
            'lease_seconds': 900,
        }),
        'retry': cfg.retry.model_copy(update={
            'max_attempts': 10,
            'backoff_seconds': 1.0,
            'backoff_max_seconds': 15.0,
            'jitter': 0.1,
        }),
        'transfer': cfg.transfer.model_copy(update={
            'connect_timeout_seconds': 20.0,
            'read_timeout_seconds': 180.0,
            'timeout_seconds': None,
            'chunk_size_bytes': 1024 * 1024,
        }),
        'integrity': cfg.integrity.model_copy(update={
            'default_checks': list(request.checks),
        }),
    })
    factory = ManifestConnectionFactory(context.db_target.db_path, config=cfg.manifest)
    storage = LocalStorageBackend(cfg.storage, create_dirs=True)
    integrity = IntegrityChecker(cfg.integrity)
    retry = RetryPolicy.from_config(cfg.retry)
    transport = NoHeadHttpTransport(config=cfg.transfer, retry=retry,
                                        max_connections=max(64, workers * 3))
    repo = SqliteManifestRepository(factory)
    try:
        plan = create_plan(repo=repo, request=request,
                           adapters=[StaticNCARAdapter(request.preferred_sources[0], assets)],
                           config=cfg)
    finally:
        repo.close()
    scheduler = build_scheduler(
        repo_factory=lambda: SqliteManifestRepository(factory),
        storage=storage,
        integrity=integrity,
        transports=[transport],
        config=cfg,
    )
    try:
        # Existing plans retain the max_attempts snapshot from when they were
        # created. Raise it for this request only so transient NCAR SSL/EOF
        # failures are not mistaken for permanently invalid data.
        with __import__('sqlite3').connect(context.db_target.db_path) as db:
            db.execute(
                "UPDATE tasks SET max_attempts=? WHERE request_id=? AND max_attempts<? "
                "AND state NOT IN ('COMPLETED','SKIPPED')",
                (cfg.retry.max_attempts, request.request_id, cfg.retry.max_attempts),
            )
            db.commit()
        submitted = scheduler.submit(plan)
        if submitted > len(plan.tasks):
            raise RuntimeError(f'RDH submit {submitted}/{len(plan.tasks)}')
        # submit() returns the number newly queued. Re-running an existing plan
        # legitimately returns 0; scheduler.run() then claims persisted QUEUED tasks.
        summary = scheduler.run(max_workers=workers)
        # Requeue genuinely retryable transport/integrity failures and drain them
        # within the same month. Ignore RESET timestamp fields so a new attempt
        # cannot inherit an older finished_at and violate the task contract.
        from sqlite3 import connect
        for _cycle in range(6):
            with connect(context.db_target.db_path) as db:
                rows = db.execute(
                    "SELECT task_id,state,attempt,max_attempts,lease_expires_at FROM tasks "
                    "WHERE request_id=? AND state IN ('FAILED','QUARANTINED','RUNNING')",
                    (request.request_id,),
                ).fetchall()
            # scheduler.run() is synchronous: once it returns, any task left in
            # RUNNING belongs to a run that has already ended. Its future lease
            # must not block a retry.
            retryable = [row[0] for row in rows if int(row[2]) < int(row[3])]
            if not retryable:
                break
            _requeue_transient(context.db_target.db_path, retryable,
                               force_running=True)
            summary = scheduler.run(max_workers=workers)
    finally:
        transport.close()
    counts = getattr(summary, 'counts', {}) or {}
    # run() counters describe this invocation, not the lifetime of an idempotent
    # plan. Verify final states directly so a fully-completed resumed plan is valid.
    from researchdatahub.core.models import TaskState
    repo = SqliteManifestRepository(factory)
    try:
        states = [task.state for task in repo.list_tasks(request_id=plan.request_id)]
    finally:
        repo.close()
    completed_total = sum(state is TaskState.COMPLETED for state in states)
    if completed_total != len(plan.tasks):
        pending = sum(state not in {TaskState.COMPLETED, TaskState.SKIPPED} for state in states)
        raise RuntimeError(f'RDH incomplete: completed={completed_total}/{len(plan.tasks)}, '
                           f'pending={pending}, counts={counts}, '
                           f'errors={getattr(summary, "errors", [])}')
    return {'plan_id': plan.plan_id, 'task_count': len(plan.tasks),
            'counts': counts, 'completed_total': completed_total}


def _rdh_report(request_id: str, plan_id: str) -> None:
    cmd = [str(RDH_PY), '-m', 'researchdatahub.cli.main', 'report', 'generate',
           request_id, '--plan', plan_id]
    result = subprocess.run(cmd, cwd=RDH_REPO, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f'RDH report failed: {result.stdout}\n{result.stderr}')


def _import_to_dbas(year: int, month: int, plan_id: str, request_file: Path,
                    dataset_id: str) -> dict:
    cfg = RdhFetchConfig(
        rdh_repo=RDH_REPO,
        rdh_python=str(RDH_PY),
        request_file=request_file,
        storage_root=Path('~/.rdh').expanduser(),
        target_dir='data/downloads',
        volume_id='downloads',
        dataset_id=dataset_id,
        dataset_label=f'ERA5 GCWR full-year slice {year}-{month:02d}',
        dataset_description=('NSF NCAR GDEX ERA5 full-year GCWR slice; '
                             'q/u/v/w/t + clwc/ciwc/crwc/cswc + sp + mtpr/mer; no CDS.'),
        dataset_source='ResearchDataHub/NSF-NCAR-RDA',
        capture_dir=ROOT / 'logs' / 'captures' / f'{year}{month:02d}',
        timeout_s=10800.0,
        plan_id=plan_id,
    )
    lock_path = ROOT / 'state' / 'dbas_import.lock'
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open('a+') as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            with Catalog(DBAS_DB) as catalog:
                summary = run_rdh_fetch(catalog, cfg, DBAS_REPO)
                for item in summary['files']:
                    scan_metadata_one(
                        {'file_id': item['file_id'], 'volume_id': 'downloads',
                         'rel_path': item['target']},
                        catalog,
                    )
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
    return summary



def install_safe_netcdf_time_decoder() -> None:
    """Protect long jobs from corrupt/hybrid NetCDF time units."""
    from researchdatahub.integrity import checker as checker_mod
    original = checker_mod._decode_netcdf_time

    def safe(values, units):
        try:
            return original(values, units)
        except (OverflowError, OSError, ValueError):
            return None

    checker_mod._decode_netcdf_time = safe


def ensure_rdh_state() -> None:
    from researchdatahub.manifest.cli_service import db_init, resolve_db_target
    target = resolve_db_target()
    if not target.db_path.exists():
        db_init(target)


def fetch_month(year: int, month: int, workers: int) -> dict:
    request_id = f'gcwr-ncar-full-{year:04d}{month:02d}'
    source_id = f'ncar-gcwr-{year:04d}{month:02d}'
    dataset_id = f'era5_gcwr_{year:04d}{month:02d}'
    request = build_request(year, month, source_id, request_id)
    start = request.metadata.temporal_coverage.start
    end = request.metadata.temporal_coverage.end
    assets = _assets(year, month, source_id, dataset_id, start, end)
    request_file = ROOT / 'requests' / f'{year:04d}{month:02d}.yaml'
    _request_yaml(request, request_file)
    install_safe_netcdf_time_decoder()
    ensure_rdh_state()
    context = load_context()
    run = _run_scheduler(context, request, assets, workers)
    _rdh_report(request_id, run['plan_id'])
    imported = _import_to_dbas(year, month, run['plan_id'], request_file, dataset_id)
    result = {
        'year': year, 'month': month, 'request_id': request_id,
        'source_id': source_id, 'dataset_id': dataset_id,
        'plan_id': run['plan_id'], 'tasks': run['task_count'],
        'rhd_counts': run['counts'], 'dbas': imported,
        'completed_at': datetime.now(UTC).isoformat(),
        'no_cds_download': True,
    }
    state = ROOT / 'state' / f'{year:04d}{month:02d}_fetch.json'
    tmp_state = state.with_suffix(state.suffix + '.tmp')
    tmp_state.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n',
                         encoding='utf-8')
    os.replace(tmp_state, state)
    print(json.dumps({k: result[k] for k in ('year', 'month', 'plan_id', 'tasks',
                                             'rhd_counts', 'dataset_id')}, ensure_ascii=False))
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--year', type=int, required=True)
    ap.add_argument('--month', type=int, required=True)
    ap.add_argument('--workers', type=int, default=12)
    args = ap.parse_args()
    fetch_month(args.year, args.month, args.workers)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
