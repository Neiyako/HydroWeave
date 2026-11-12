"""地形与地理参照层：GTOPO30 高程子集、山体阴影、高原边界。

只读外部卷上的真实高程（USGS GTOPO30 30″）与中国 1:4,000,000 矢量边界，
仅作为图的地理参照与合成分布的地形强迫，不参与任何物理量反演。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

DEFAULT_DEM = Path("/Volumes/Untitled/DATA/USGS-30s-Terrain/DEM_ptpe_Gtopo30.nc")
DEFAULT_CHINA_SHP = Path("/Volumes/Untitled/DATA/China_shp/1")

G_STANDARD = 9.80665
EARTH_RADIUS_M = 6371000.0

# 高程场与阴影场的分辨率分离：物理量用 0.25°，阴影用 0.05° 再插值回 0.25°
FINE_STEP_DEG = 0.05


@dataclass(frozen=True)
class Grid:
    """规则经纬网格。"""

    latitude: np.ndarray
    longitude: np.ndarray
    elevation: np.ndarray
    shade: np.ndarray

    @property
    def shape(self) -> tuple[int, int]:
        return self.elevation.shape


def _read_subset(dataset, lat_targets: np.ndarray, lon_targets: np.ndarray,
                 stride: int) -> np.ndarray:
    """按目标经纬度取出源 DEM 子集（源 lat 递减、lon 递增）。"""
    lat = np.asarray(dataset["lat"][:], dtype="float64")
    lon = np.asarray(dataset["lon"][:], dtype="float64")
    rows = np.round((lat[0] - lat_targets) / (lat[0] - lat[1])).astype(int)
    cols = np.round((lon_targets - lon[0]) / (lon[1] - lon[0])).astype(int)
    rows = np.clip(rows, 0, len(lat) - 1)
    cols = np.clip(cols, 0, len(lon) - 1)
    stride_rows = np.arange(len(lat_targets)) * stride
    stride_cols = np.arange(len(lon_targets)) * stride
    out = np.empty((len(lat_targets), len(lon_targets)), dtype="float64")
    r0, r1 = rows.min(), rows.max()
    block = np.ma.filled(dataset["elev"][r0:r1 + 1:1, :].astype("float64"), np.nan)
    for a, r in enumerate(rows):
        out[a, :] = block[r - r0, cols]
    del stride_rows, stride_cols
    return out


def _hillshade_from_elev(elev: np.ndarray, lat: np.ndarray, lon: np.ndarray,
                         *, azimuth_deg: float = 315.0,
                         altitude_deg: float = 45.0) -> np.ndarray:
    dy = abs(float(np.diff(lat).mean())) * 111320.0
    dx = (abs(float(np.diff(lon).mean())) * 111320.0
          * np.cos(np.deg2rad(lat.mean())))
    gy, gx = np.gradient(elev, dy, dx)
    slope = np.arctan(np.hypot(gx, gy))
    aspect = np.arctan2(-gx, gy)
    azimuth = np.deg2rad(360.0 - azimuth_deg + 90.0)
    altitude = np.deg2rad(altitude_deg)
    shaded = (np.sin(altitude) * np.cos(slope)
              + np.cos(altitude) * np.sin(slope) * np.cos(azimuth - aspect))
    return np.clip(shaded, 0.0, 1.0)


def load_elevation(
    dem_path: str | Path = DEFAULT_DEM,
    *,
    lat_min: float = 25.0,
    lat_max: float = 40.0,
    lon_min: float = 70.0,
    lon_max: float = 105.0,
    step_deg: float = 0.25,
    smooth_sigma: float = 1.0,
) -> Grid:
    """读取 GTOPO30 高程（0.25° 目标网格）与 0.05° 计算的山体阴影。"""
    import netCDF4
    from scipy.interpolate import RegularGridInterpolator
    from scipy.ndimage import gaussian_filter

    lat_targets = np.round(np.arange(lat_min, lat_max + 1e-6, step_deg), 6)
    lon_targets = np.round(np.arange(lon_min, lon_max + 1e-6, step_deg), 6)
    lat_fine = np.round(np.arange(lat_max, lat_min - 1e-6, -FINE_STEP_DEG), 6)
    lon_fine = np.round(np.arange(lon_min, lon_max + 1e-6, FINE_STEP_DEG), 6)

    with netCDF4.Dataset(str(dem_path)) as dataset:
        coarse, fine = _read_subsets(dataset, lat_targets, lon_targets, lat_fine, lon_fine)

    elev = np.where(np.isfinite(coarse) & (coarse > -1000.0), coarse, np.nan)
    if np.isnan(elev).any():
        elev = _fill_nan(elev)
    if smooth_sigma > 0:
        elev = gaussian_filter(elev, sigma=smooth_sigma, mode="nearest")

    fine = np.where(np.isfinite(fine) & (fine > -1000.0), fine, np.nan)
    if np.isnan(fine).any():
        fine = _fill_nan(fine)
    shade_fine = _hillshade_from_elev(fine, lat_fine, lon_fine)
    interpolator = RegularGridInterpolator(
        (lat_fine[::-1], lon_fine), shade_fine[::-1], bounds_error=False, fill_value=None)
    lon_grid, lat_grid = np.meshgrid(lon_targets, lat_targets)
    shade = interpolator(np.column_stack([lat_grid.ravel(), lon_grid.ravel()]))
    shade = np.clip(shade, 0.0, 1.0).reshape(lat_grid.shape)
    shade = gaussian_filter(shade, sigma=0.8, mode="nearest")
    return Grid(latitude=lat_targets, longitude=lon_targets, elevation=elev, shade=shade)


def _read_subsets(dataset, lat_targets, lon_targets, lat_fine, lon_fine):
    """一次读入源 DEM 行段，分别取出粗网格与细网格子集。"""
    lat = np.asarray(dataset["lat"][:], dtype="float64")
    lon = np.asarray(dataset["lon"][:], dtype="float64")
    lat_all = np.concatenate([lat_targets, lat_fine])
    lon_all = np.concatenate([lon_targets, lon_fine])
    rows = np.round((lat[0] - lat_all) / (lat[0] - lat[1])).astype(int)
    cols = np.round((lon_all - lon[0]) / (lon[1] - lon[0])).astype(int)
    rows = np.clip(rows, 0, len(lat) - 1)
    cols = np.clip(cols, 0, len(lon) - 1)
    r0, r1 = int(rows.min()), int(rows.max())
    block = np.ma.filled(dataset["elev"][r0:r1 + 1:1, :].astype("float64"), np.nan)

    def pick(rows_sel, cols_sel):
        out = np.empty((len(rows_sel), len(cols_sel)), dtype="float64")
        for a, r in enumerate(rows_sel):
            out[a, :] = block[r - r0, cols_sel]
        return out

    n_coarse = len(lat_targets)
    n_lon_coarse = len(lon_targets)
    coarse = pick(rows[:n_coarse], cols[:n_lon_coarse])
    fine = pick(rows[n_coarse:], cols[n_lon_coarse:])
    return coarse, fine


def _fill_nan(field: np.ndarray) -> np.ndarray:
    """最近邻填补 DEM 空洞。"""
    from scipy.ndimage import distance_transform_edt

    mask = np.isnan(field)
    if not mask.any():
        return field
    _, indices = distance_transform_edt(mask, return_distances=True, return_indices=True)
    return field[tuple(indices)]


def surface_pressure(elevation: np.ndarray) -> np.ndarray:
    """标准大气斜压公式反演地面气压（hPa）。"""
    ratio = np.clip(1.0 - 2.25577e-5 * elevation, 0.05, 1.0)
    return 1013.25 * ratio ** 5.25588


def altitude_of_pressure(pressure_hpa) -> np.ndarray:
    """标准大气高度–气压反演（m）。"""
    ratio = np.clip(np.asarray(pressure_hpa, dtype="float64") / 1013.25, 1e-3, 1.5)
    return 44330.0 * (1.0 - ratio ** 0.1903)


def tibet_boundary(shp_dir: str | Path = DEFAULT_CHINA_SHP) -> np.ndarray:
    """西藏自治区行政边界外环坐标 (lon, lat)，来自 1:4M 省级面图层。"""
    import shapefile
    from shapely.geometry import shape

    path = Path(shp_dir) / "bou2_4p.shp"
    if not path.exists():
        raise FileNotFoundError(path)
    reader = shapefile.Reader(str(path), encoding="gbk")
    best = None
    for record in reader.iterShapeRecords():
        if "西藏" not in str(record.record[-1]):
            continue
        geometry = shape(record.shape.__geo_interface__)
        if geometry.geom_type.startswith("Multi"):
            geometry = max(geometry.geoms, key=lambda g: g.area)
        best = np.asarray(geometry.exterior.coords, dtype="float64")
    if best is None:
        raise LookupError("未找到西藏自治区边界")
    return best


def polygon_mask(boundary: np.ndarray, latitude: np.ndarray,
                 longitude: np.ndarray) -> np.ndarray:
    """网格点是否落在多边形内（经纬度平面判定，TP 尺度足够）。"""
    from matplotlib.path import Path

    path = Path(boundary)
    lon_grid, lat_grid = np.meshgrid(longitude, latitude)
    points = np.column_stack([lon_grid.ravel(), lat_grid.ravel()])
    return path.contains_points(points).reshape(lon_grid.shape)
