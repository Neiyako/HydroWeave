"""合成云水场：给出与 ERA5 同量纲、可物理解释的 clwc/ciwc 场。

用途是「图件风格验证」——用已知真值与已知误差结构的仿真数据，
检验制图方案在信息密度、配色、版式上能否达到期刊级别；不是真实观测结果。

构造链条（全部自洽、可复现）：

    地形高程 → 地面气压 p_s → 环境温度 T(p) → 自由大气温度 + 边界层修正
    湿度场 M（季风水汽输送） × 地形抬升 O → 层状云 A_strat
    对流单体 C(t)（MCS 路径 + 随机中尺度团） → 对流塔 + 砧状云 A_conv
    q_c(p) → 按温度相态分割 → clwc = q_c·(1−f_ice)，ciwc = q_c·f_ice
    再叠加 ERA5 类格点产品的相关噪声与偏差 → 「产品」与「真值」两套场
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from experiments.figure_studio.terrain import (
    G_STANDARD,
    Grid,
    altitude_of_pressure,
    surface_pressure,
)

# ERA5 风格气压层（1–1000 hPa 的子集，含对流层关键层）
LEVELS_HPA = np.array(
    [100, 125, 150, 175, 200, 225, 250, 275, 300, 325, 350, 375, 400, 425,
     450, 475, 500, 525, 550, 575, 600, 625, 650, 675, 700, 750, 800, 850,
     900, 925, 950, 975, 1000.0]
)

# 7 月自由大气温度廓线 (hPa → °C)，高原上空量级
_FREE_T_KNOTS_P = np.array([1000, 925, 850, 750, 700, 600, 500, 400, 300, 200, 150, 100.0])
_FREE_T_KNOTS_T = np.array([16.0, 7.0, 0.0, -5.5, -11.0, -19.0, -27.0, -38.0,
                             -51.0, -65.0, -73.0, -80.0])


@dataclass
class SyntheticRun:
    """一次仿真实验的全部场。"""

    grid: Grid
    levels_hpa: np.ndarray
    times: np.ndarray
    clwc_truth: np.ndarray        # (time, level, lat, lon) kg kg-1
    ciwc_truth: np.ndarray
    clwc_product: np.ndarray      # 含噪声与偏差的「ERA5 类产品」
    ciwc_product: np.ndarray
    lwp_truth: np.ndarray         # (time, lat, lon) kg m-2
    iwp_truth: np.ndarray
    lwp_product: np.ndarray
    iwp_product: np.ndarray
    temperature: np.ndarray       # (level, lat, lon) K
    surface_pressure: np.ndarray  # (lat, lon) hPa
    meta: dict = field(default_factory=dict)


def _free_temperature(pressure_hpa: np.ndarray) -> np.ndarray:
    return np.interp(pressure_hpa, _FREE_T_KNOTS_P[::-1], _FREE_T_KNOTS_T[::-1])


def _smooth(field: np.ndarray, sigma: float) -> np.ndarray:
    from scipy.ndimage import gaussian_filter

    return gaussian_filter(field, sigma=sigma, mode="nearest")


def _normalized(field: np.ndarray, percentile: float = 95.0) -> np.ndarray:
    scale = float(np.percentile(field, percentile))
    if scale <= 0:
        return np.zeros_like(field)
    return np.clip(field / scale, 0.0, 1.5)


def _moisture_field(longitude: np.ndarray, latitude: np.ndarray) -> np.ndarray:
    """季风水汽可用度 M∈[0,1]：东南高、西北低。"""
    lon_grid, lat_grid = np.meshgrid(longitude, latitude)
    core = np.exp(-(((lat_grid - 29.5) / 5.0) ** 2 + ((lon_grid - 93.0) / 16.0) ** 2))
    source = np.exp(-(((lat_grid - 25.5) / 3.0) ** 2 + ((lon_grid - 92.0) / 12.0) ** 2))
    field = 0.72 * core + 0.28 * source
    return _normalized(_smooth(field, 2.0), 99.0)


def _orographic_field(grid: Grid, wind_u: float = 2.0, wind_v: float = 3.0) -> np.ndarray:
    """西南风抬升强迫 O∈[0,1]：地形迎风坡抬升强。"""
    dy = abs(float(np.diff(grid.latitude).mean())) * 111320.0
    dx = (abs(float(np.diff(grid.longitude).mean())) * 111320.0
          * np.cos(np.deg2rad(grid.latitude.mean())))
    gy, gx = np.gradient(grid.elevation, dy, dx)
    uplift = -(wind_u * gx + wind_v * gy)
    return _normalized(_smooth(np.clip(uplift, 0.0, None), 2.0), 97.0)


def _convection_field(times: np.ndarray, longitude: np.ndarray,
                      latitude: np.ndarray, elevation: np.ndarray,
                      rng: np.random.Generator) -> np.ndarray:
    """对流活动场 C(t, lat, lon)：一条 MCS 路径 + 若干随机中尺度单体。"""
    lon_grid, lat_grid = np.meshgrid(longitude, latitude)
    n_times = len(times)
    field = np.zeros((n_times, latitude.size, longitude.size))
    # 主 MCS：自西向东、自南向北移动
    track = np.linspace(0.0, 1.0, n_times)
    for index in range(n_times):
        cx = 90.0 + 9.0 * track[index]
        cy = 28.5 + 4.5 * track[index]
        sigma = 2.2 + 0.6 * np.sin(np.pi * track[index])
        field[index] += np.exp(-(((lon_grid - cx) / (2.2 * sigma)) ** 2
                                + ((lat_grid - cy) / (1.6 * sigma)) ** 2))
    # 背景随机单体
    for _ in range(6):
        cx = rng.uniform(78.0, 101.0)
        cy = rng.uniform(27.0, 36.0)
        sigma = rng.uniform(0.8, 2.0)
        weight = rng.uniform(0.25, 0.7)
        phase = rng.uniform(0.0, 2 * np.pi)
        blob = np.exp(-(((lon_grid - cx) / (1.4 * sigma)) ** 2
                        + ((lat_grid - cy) / (1.2 * sigma)) ** 2))
        for index in range(n_times):
            shift = 1.2 * np.sin(phase + index * 0.8)
            field[index] += weight * np.exp(-(((lon_grid - cx - shift) / (1.4 * sigma)) ** 2
                                             + ((lat_grid - cy) / (1.2 * sigma)) ** 2))
        del blob
    # 高海拔不利于深对流
    suppression = 1.0 - 0.45 * np.clip(elevation, 0.0, 6000.0) / 6000.0
    return np.clip(field * suppression[None, :, :], 0.0, 1.6)


def _cloud_gate(rng: np.random.Generator, shape: tuple[int, int],
                seed_offset: int) -> np.ndarray:
    """云量门限场：0 → 晴空，1 → 满云。"""
    noise = rng.standard_normal(shape)
    field = _smooth(noise, 2.5)
    field = (field - field.mean()) / (field.std() + 1e-12)
    return np.clip((field + 1.15) / 1.6, 0.0, 1.0)


def _temperature(levels_hpa: np.ndarray, grid: Grid) -> np.ndarray:
    """环境温度场 T(level, lat, lon)（K）。"""
    p_s = surface_pressure(grid.elevation)
    t_surface = 32.0 - 0.0055 * grid.elevation            # °C，7 月量级
    free_surface = _free_temperature(p_s)
    boundary_layer_delta = t_surface - free_surface       # K
    z_free = altitude_of_pressure(levels_hpa)[:, None, None]
    z_surface = grid.elevation[None, :, :]
    decay = np.exp(-(z_free - z_surface) / 1500.0)
    profile = _free_temperature(levels_hpa)[:, None, None] + decay * boundary_layer_delta[None]
    return profile + 273.15


def _ice_fraction(temperature_k: np.ndarray) -> np.ndarray:
    """冰相份额 f_ice：0 °C 附近过渡，−20 °C 以上基本全冰。"""
    t_c = temperature_k - 273.15
    return 1.0 / (1.0 + np.exp((t_c + 5.0) / 6.0))


def _column_integral(profile: np.ndarray, levels_hpa: np.ndarray) -> np.ndarray:
    """∫ q dp / g（kg m-2），梯形积分。"""
    pressure = levels_hpa[:, None, None]
    dp = np.diff(pressure, axis=0) * 100.0  # hPa → Pa
    integral = np.sum((profile[:-1] + profile[1:]) / 2.0 * dp, axis=0)
    return integral / G_STANDARD


def build_run(
    grid: Grid,
    *,
    times: np.ndarray | None = None,
    seed: int = 20240715,
    target_lwp: float = 0.22,
    target_iwp: float = 0.80,
) -> SyntheticRun:
    """生成一整套仿真云水场与对应的带噪「产品」场。"""
    rng = np.random.default_rng(seed)
    if times is None:
        times = np.array([0.0, 6.0, 12.0, 18.0])
    levels = LEVELS_HPA
    latitude, longitude = grid.latitude, grid.longitude

    temperature = _temperature(levels, grid)
    f_ice = _ice_fraction(temperature)
    moisture = _moisture_field(longitude, latitude)
    orographic = _orographic_field(grid)
    convection = _convection_field(times, longitude, latitude, grid.elevation, rng)

    shape_conv = (0.70 * np.exp(-0.5 * ((np.log(levels) - np.log(430.0)) / 0.28) ** 2)
                  + 0.30 * np.exp(-0.5 * ((np.log(levels) - np.log(240.0)) / 0.18) ** 2))
    shape_strat = np.exp(-0.5 * ((np.log(levels) - np.log(580.0)) / 0.25) ** 2)

    n_times = len(times)
    shape_lat, shape_lon = latitude.size, longitude.size
    q_convective = np.zeros((n_times, levels.size, shape_lat, shape_lon))
    q_stratiform = np.zeros((n_times, levels.size, shape_lat, shape_lon))

    amp_convective = 5.2e-4 * (1.0 - 0.45 * np.clip(grid.elevation, 0.0, 6000.0) / 6000.0)
    amp_stratiform = 1.05e-4 * moisture * (0.45 + 0.55 * orographic)

    for index in range(n_times):
        gate = _cloud_gate(rng, (shape_lat, shape_lon), index)
        conv = convection[index][None, :, :]
        q_convective[index] = amp_convective[None] * conv * shape_conv[:, None, None]
        q_stratiform[index] = (amp_stratiform[None] * gate[None] * shape_strat[:, None, None])

    total = q_convective + q_stratiform
    clwc = total * (1.0 - f_ice[None])
    ciwc = total * f_ice[None]

    # 标定：整体缩放使域平均 LWP/IWP 命中目标量级
    lwp_raw = _column_integral(clwc[0], levels)
    iwp_raw = _column_integral(ciwc[0], levels)
    scale_liquid = target_lwp / max(float(np.nanmean(lwp_raw)), 1e-12)
    scale_ice = target_iwp / max(float(np.nanmean(iwp_raw)), 1e-12)
    clwc *= scale_liquid
    ciwc *= scale_ice

    lwp_truth = np.stack([_column_integral(clwc[i], levels) for i in range(n_times)])
    iwp_truth = np.stack([_column_integral(ciwc[i], levels) for i in range(n_times)])

    # ERA5 类格点产品：乘性对数正态噪声 + 冰相系统性偏低
    clwc_product, ciwc_product = _add_product_noise(clwc, ciwc, rng)

    lwp_product = np.stack([_column_integral(clwc_product[i], levels) for i in range(n_times)])
    iwp_product = np.stack([_column_integral(ciwc_product[i], levels) for i in range(n_times)])

    meta = {
        "seed": seed,
        "target_lwp_kg_m2": target_lwp,
        "target_iwp_kg_m2": target_iwp,
        "scale_liquid": float(scale_liquid),
        "scale_ice": float(scale_ice),
        "levels_hpa": levels.tolist(),
        "times_h": times.tolist(),
        "source": "synthetic (figure-style validation only, not observation)",
    }
    return SyntheticRun(
        grid=grid,
        levels_hpa=levels,
        times=times,
        clwc_truth=clwc,
        ciwc_truth=ciwc,
        clwc_product=clwc_product,
        ciwc_product=ciwc_product,
        lwp_truth=lwp_truth,
        iwp_truth=iwp_truth,
        lwp_product=lwp_product,
        iwp_product=iwp_product,
        temperature=temperature,
        surface_pressure=surface_pressure(grid.elevation),
        meta=meta,
    )


def _add_product_noise(clwc: np.ndarray, ciwc: np.ndarray,
                       rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray]:
    """给真值场叠加 ERA5 类产品噪声（空间相关 + 相态依赖偏差）。"""
    def noise(shape: tuple[int, ...], sigma_cells: float) -> np.ndarray:
        from scipy.ndimage import gaussian_filter

        white = rng.standard_normal(shape)
        smooth = gaussian_filter(white, sigma=(0.0, 0.0, sigma_cells, sigma_cells),
                                 mode="nearest")
        return (smooth - smooth.mean(axis=(2, 3), keepdims=True)) / (
            smooth.std(axis=(2, 3), keepdims=True) + 1e-12)

    liquid_noise = noise(clwc.shape, 1.6)
    ice_noise = noise(ciwc.shape, 1.9)
    clwc_product = clwc * np.exp(0.02 + 0.26 * liquid_noise)
    ciwc_product = ciwc * np.exp(-0.14 + 0.34 * ice_noise)
    return clwc_product, ciwc_product


def weighted_profile(profile: np.ndarray, latitude: np.ndarray) -> np.ndarray:
    """纬向余弦加权平均的垂直廓线。profile: (level, lat, lon) → (level,)"""
    weights = np.cos(np.deg2rad(latitude))
    lon_count = profile.shape[2]
    zonal = (profile * weights[None, :, None]).sum(axis=2) / lon_count  # (level, lat)
    return zonal.sum(axis=1) / float(weights.sum())


def percentile_profile(profile: np.ndarray, latitude: np.ndarray,
                       lower: float = 10.0, upper: float = 90.0) -> tuple[np.ndarray, np.ndarray]:
    """按格点分布取分位数廓线。"""
    flat = profile.reshape(profile.shape[0], -1)
    return (np.percentile(flat, lower, axis=1), np.percentile(flat, upper, axis=1))
