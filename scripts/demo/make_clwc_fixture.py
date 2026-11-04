#!/usr/bin/env python3
"""生成 cloud_water_strict 的离线合成 fixture（合成 NetCDF + 临时 DBAS catalog）。

真实 ERA5 clwc/ciwc 卷依赖 DBAS 下载/导入链与外接盘；本脚本用确定性合成数据
复刻本实验依赖的最小结构，供单测与演示全流程使用：

* ``<dest>/volume/ERA5_2024_cloud_water.nc`` —— 含 clwc/ciwc 的 ERA5 风格
  单时次 NetCDF（valid_time/pressure_level/latitude/longitude；默认 500/400/300
  hPa、25–40°N/70–105°E、0.25°）；
* ``<dest>/catalog.db`` —— 只含 ``volumes``/``files`` 两表，卷 ID 与 dataset_id
  可配置；
* ``<dest>/config.yaml`` —— 指向以上绝对路径的实验配置。

合成数字**没有物理意义**，只验证链路、单位/权重/部分列口径与可复现机制。

用法::

    .venv/bin/python scripts/demo/make_clwc_fixture.py [dest]
    PYTHONPATH=src:. .venv/bin/python -m experiments.cloud_water_strict.compute \\
        --config <dest>/config.yaml --run-id fixture
"""
from __future__ import annotations

import argparse
import hashlib
import sqlite3
import time
from pathlib import Path

import netCDF4
import numpy as np
import yaml

DEFAULT_LEVELS = (500.0, 400.0, 300.0)
VALID_TIME = "2024-01-01 00:00:00"
# 用 datetime64 计算，避免手写小时数偏移（曾误写成 1084800 → 2023-10-03）。
HOURS_SINCE_1900 = int(
    (np.datetime64(VALID_TIME) - np.datetime64("1900-01-01T00:00:00"))
    / np.timedelta64(1, "h"))


def _spatial_pattern(lat: np.ndarray, lon: np.ndarray, level_scale: float) -> np.ndarray:
    """确定性 2D 空间形态（0.35–1.0），让场不是常数以便检验 cosφ 加权。"""
    lat_norm = (lat - lat.min()) / max(float(lat.max() - lat.min()), 1e-12)
    lon_norm = (lon - lon.min()) / max(float(lon.max() - lon.min()), 1e-12)
    ridge = 0.55 + 0.45 * np.sin(np.pi * lat_norm)[:, None]
    wave = 0.65 + 0.35 * np.cos(2.0 * np.pi * lon_norm)[None, :]
    return np.clip(ridge * wave * level_scale, 0.05, 1.5)


def _fields(levels: np.ndarray, lat: np.ndarray, lon: np.ndarray,
            n_times: int = 1) -> tuple[np.ndarray, np.ndarray]:
    """合成 clwc/ciwc (n_times, nlev, nlat, nlon)，单位 kg·kg⁻¹。

    每个时次乘一个确定性因子，便于测试多时次快照统计（数字仍无物理意义）。
    """
    pressure = levels[:, None, None].astype("float64")
    liquid_level = 0.35 + 0.65 * np.exp(-(((pressure - 450.0) / 160.0) ** 2))
    ice_level = 0.25 + 0.45 * np.exp(-(((pressure - 380.0) / 150.0) ** 2))
    liquid = 1.2e-4 * liquid_level * _spatial_pattern(lat, lon, 1.0)
    ice = 3.0e-5 * ice_level * _spatial_pattern(lat, lon, 0.8)
    time_factor = (np.ones(1) if n_times == 1 else
                   0.75 + 0.25 * np.sin(np.arange(n_times, dtype="float64") * 0.9))
    liquid = liquid[None, :, :, :] * time_factor[:, None, None, None]
    ice = ice[None, :, :, :] * time_factor[:, None, None, None]
    return liquid, ice


def _hours(n_times: int) -> np.ndarray:
    base = np.datetime64(VALID_TIME)
    return (base + np.arange(n_times) * np.timedelta64(1, "D") -
            np.datetime64("1900-01-01T00:00:00")) / np.timedelta64(1, "h")


def _write_variable(path: Path, variable: str, values: np.ndarray, *,
                    levels: np.ndarray, lat: np.ndarray, lon: np.ndarray,
                    units: str) -> None:
    dataset = netCDF4.Dataset(path, "w", format="NETCDF4")
    try:
        dataset.createDimension("valid_time", values.shape[0])
        dataset.createDimension("pressure_level", levels.size)
        dataset.createDimension("latitude", lat.size)
        dataset.createDimension("longitude", lon.size)
        time_var = dataset.createVariable("valid_time", "f8", ("valid_time",))
        time_var.units = "hours since 1900-01-01 00:00:00"
        time_var.calendar = "standard"
        time_var[:] = _hours(values.shape[0])
        level_var = dataset.createVariable("pressure_level", "f8", ("pressure_level",))
        level_var.units = "hPa"
        level_var.long_name = "pressure_level"
        level_var[:] = levels
        var_lat = dataset.createVariable("latitude", "f8", ("latitude",))
        var_lat.units = "degrees_north"
        var_lat[:] = lat
        var_lon = dataset.createVariable("longitude", "f8", ("longitude",))
        var_lon.units = "degrees_east"
        var_lon[:] = lon
        data = dataset.createVariable(
            variable, "f4",
            ("valid_time", "pressure_level", "latitude", "longitude"))
        data.units = units
        data.long_name = {"clwc": "Specific cloud liquid water content",
                          "ciwc": "Specific cloud ice water content"}[variable]
        data[:] = values.astype("float32")
        dataset.title = "synthetic cloud_water_strict fixture (no physical meaning)"
    finally:
        dataset.close()


def _sha1(volume_id: str, rel_path: str) -> str:
    return hashlib.sha1(f"{volume_id}/{rel_path}".encode()).hexdigest()


def _write_catalog(db_path: Path, volume_id: str, root: Path,
                   rel_paths: list[str], dataset_id: str) -> None:
    connection = sqlite3.connect(db_path)
    try:
        connection.executescript("""
            CREATE TABLE volumes (
                volume_id TEXT PRIMARY KEY,
                label TEXT,
                root_path TEXT NOT NULL,
                last_mount_path TEXT,
                status TEXT NOT NULL DEFAULT 'unknown'
            );
            CREATE TABLE files (
                file_id TEXT PRIMARY KEY,
                volume_id TEXT NOT NULL,
                rel_path TEXT NOT NULL,
                file_name TEXT NOT NULL,
                size_bytes INTEGER,
                mtime REAL,
                status TEXT NOT NULL DEFAULT 'active',
                dataset_id TEXT
            );
        """)
        connection.execute(
            "INSERT INTO volumes(volume_id,label,root_path,last_mount_path,status) "
            "VALUES (?,?,?,?,?)",
            (volume_id, "fixture", str(root), str(root), "online"))
        now = time.time()
        for rel_path in rel_paths:
            path = root / rel_path
            connection.execute(
                "INSERT INTO files(file_id,volume_id,rel_path,file_name,size_bytes,"
                "mtime,status,dataset_id) VALUES (?,?,?,?,?,?,?,?)",
                (_sha1(volume_id, rel_path), volume_id, rel_path, path.name,
                 path.stat().st_size, now, "active", dataset_id))
        connection.commit()
    finally:
        connection.close()


def build(dest: Path, *, volume_id: str = "fixture", dataset_id: str = "era5_cloud_water",
          levels: tuple[float, ...] = DEFAULT_LEVELS,
          lat_range: tuple[float, float] = (25.0, 40.0),
          lon_range: tuple[float, float] = (70.0, 105.0),
          resolution: float = 0.25, separate_files: bool = False,
          drop_ice: bool = False, units: str = "kg kg**-1",
          n_times: int = 1) -> Path:
    """生成 fixture，返回 config.yaml 路径。"""
    dest = dest.expanduser().resolve()
    volume_root = dest / "volume"
    volume_root.mkdir(parents=True, exist_ok=True)
    levels_array = np.asarray(sorted(levels, reverse=True), dtype="float64")
    lat = np.arange(lat_range[0], lat_range[1] + resolution / 2.0, resolution,
                    dtype="float64")
    lon = np.arange(lon_range[0], lon_range[1] + resolution / 2.0, resolution,
                    dtype="float64")
    if n_times < 1:
        raise ValueError("n_times 必须 ≥ 1")
    liquid, ice = _fields(levels_array, lat, lon, n_times=n_times)
    unit_key = units.replace(" ", "").replace("**", "^").lower()
    factor = 1.0e-3 if unit_key in {"gkg^-1", "gkg-1", "g/kg"} else 1.0
    if factor != 1.0:
        liquid = liquid / factor
        ice = ice / factor

    rel_paths: list[str] = []
    if separate_files:
        for variable, values in (("clwc", liquid), ("ciwc", ice)):
            if variable == "ciwc" and drop_ice:
                continue
            rel_path = f"{variable}_2024_cloud_water.nc"
            _write_variable(volume_root / rel_path, variable, values, levels=levels_array,
                            lat=lat, lon=lon, units=units)
            rel_paths.append(rel_path)
    else:
        rel_path = "ERA5_2024_cloud_water.nc"
        path = volume_root / rel_path
        dataset = netCDF4.Dataset(path, "w", format="NETCDF4")
        try:
            dataset.createDimension("valid_time", liquid.shape[0])
            dataset.createDimension("pressure_level", levels_array.size)
            dataset.createDimension("latitude", lat.size)
            dataset.createDimension("longitude", lon.size)
            time_var = dataset.createVariable("valid_time", "f8", ("valid_time",))
            time_var.units = "hours since 1900-01-01 00:00:00"
            time_var.calendar = "standard"
            time_var[:] = _hours(liquid.shape[0])
            level_var = dataset.createVariable("pressure_level", "f8", ("pressure_level",))
            level_var.units = "hPa"
            level_var[:] = levels_array
            var_lat = dataset.createVariable("latitude", "f8", ("latitude",))
            var_lat.units = "degrees_north"
            var_lat[:] = lat
            var_lon = dataset.createVariable("longitude", "f8", ("longitude",))
            var_lon.units = "degrees_east"
            var_lon[:] = lon
            for variable, values, long_name in (
                    ("clwc", liquid, "Specific cloud liquid water content"),
                    ("ciwc", ice, "Specific cloud ice water content")):
                if variable == "ciwc" and drop_ice:
                    continue
                data = dataset.createVariable(
                    variable, "f4",
                    ("valid_time", "pressure_level", "latitude", "longitude"))
                data.units = units
                data.long_name = long_name
                data[:] = values.astype("float32")
            dataset.title = "synthetic cloud_water_strict fixture (no physical meaning)"
        finally:
            dataset.close()
        rel_paths.append(rel_path)

    catalog_path = dest / "catalog.db"
    if catalog_path.exists():
        catalog_path.unlink()
    _write_catalog(catalog_path, volume_id, volume_root, rel_paths, dataset_id)
    config = {
        "experiment": "cloud_water_strict",
        "catalog": str(catalog_path),
        "volume_id": volume_id,
        "dataset_id": dataset_id,
        "variables": {"liquid": "clwc", "ice": "ciwc"},
        "region": {"lat_min": lat_range[0], "lat_max": lat_range[1],
                   "lon_min": lon_range[0], "lon_max": lon_range[1]},
        "pressure": {"full_column_hpa": [1.0, 1000.0],
                     "partial_tolerance_hpa": 1.0, "units": None},
        "time": {"index": 0},
        "constants": {"g_m_s2": 9.80665, "earth_radius_m": 6371000.0},
        "input_file": None,
        "output_dir": str(dest / "analysis"),
    }
    config_path = dest / "config.yaml"
    config_path.write_text(
        "# 由 scripts/demo/make_clwc_fixture.py 生成；合成数据无物理意义。\n"
        + yaml.safe_dump(config, allow_unicode=True, sort_keys=False),
        encoding="utf-8")
    return config_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="生成 cloud_water_strict 合成 fixture")
    parser.add_argument("dest", nargs="?", default="/tmp/cloud_water_fixture")
    parser.add_argument("--levels", default="500,400,300",
                        help="逗号分隔的气压层 hPa（默认 500,400,300）")
    parser.add_argument("--resolution", type=float, default=0.25)
    parser.add_argument("--separate-files", action="store_true",
                        help="clwc/ciwc 分成两个 NetCDF（检验多文件合并）")
    parser.add_argument("--drop-ciwc", action="store_true", help="不写 ciwc（缺失变量测试）")
    parser.add_argument("--mixing-ratio-units", default="kg kg**-1",
                        choices=("kg kg**-1", "g kg**-1"))
    parser.add_argument("--times", type=int, default=1,
                        help="时次数（默认 1；用于多时次快照统计测试）")
    args = parser.parse_args(argv)
    levels = tuple(float(item) for item in args.levels.split(",") if item.strip())
    config_path = build(
        Path(args.dest), levels=levels, resolution=args.resolution,
        separate_files=args.separate_files, drop_ice=args.drop_ciwc,
        units=args.mixing_ratio_units, n_times=args.times)
    print(f"fixture config: {config_path}")
    print(f"catalog: {config_path.parent / 'catalog.db'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
