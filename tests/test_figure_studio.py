"""figure_studio 数值层自检：只测不依赖外部数据卷的纯函数。"""
from __future__ import annotations

import numpy as np

from experiments.figure_studio import synth
from experiments.figure_studio.terrain import (
    G_STANDARD,
    Grid,
    altitude_of_pressure,
    surface_pressure,
)


def _toy_grid(n_lat: int = 21, n_lon: int = 25) -> Grid:
    latitude = np.linspace(27.0, 37.0, n_lat)
    longitude = np.linspace(78.0, 100.0, n_lon)
    lon_grid, lat_grid = np.meshgrid(longitude, latitude)
    elevation = 1200.0 + 3600.0 * np.exp(
        -(((lat_grid - 33.0) / 4.0) ** 2 + ((lon_grid - 88.0) / 8.0) ** 2))
    shade = np.full_like(elevation, 0.7)
    return Grid(latitude=latitude, longitude=longitude, elevation=elevation, shade=shade)


def test_column_integral_matches_analytic():
    """常数场梯形积分应等于 q/g·Δp。"""
    levels = np.array([200.0, 400.0, 600.0, 800.0, 1000.0])
    q = np.full((levels.size, 2, 2), 1.0e-4)
    integral = synth._column_integral(q, levels)
    expected = 1.0e-4 * (1000.0 - 200.0) * 100.0 / G_STANDARD
    assert np.allclose(integral, expected)


def test_phase_split_conserves_condensate():
    """相态分割必须守恒：clwc + ciwc = 总凝结物。"""
    grid = _toy_grid()
    run = synth.build_run(grid, seed=7)
    total = run.clwc_truth + run.ciwc_truth
    assert np.all(total >= -1e-18)
    assert np.isfinite(total).all()


def test_build_run_is_reproducible():
    """同 seed 同输入 ⇒ 同输出（比特级）。"""
    grid = _toy_grid()
    first = synth.build_run(grid, seed=11)
    second = synth.build_run(grid, seed=11)
    assert np.array_equal(first.clwc_truth, second.clwc_truth)
    assert np.array_equal(first.lwp_truth, second.lwp_truth)


def test_lwp_iwp_have_plausible_magnitude():
    """标定后域平均 LWP/IWP 应落在合成设计的目标量级附近。"""
    grid = _toy_grid()
    run = synth.build_run(grid, seed=3)
    assert 0.05 < float(np.nanmean(run.lwp_truth[0])) < 2.0
    assert 0.10 < float(np.nanmean(run.iwp_truth[0])) < 5.0
    assert float(np.nanmean(run.iwp_truth[0])) > float(np.nanmean(run.lwp_truth[0]))


def test_product_noise_is_biased_low_for_ice():
    """「产品」的冰相必须系统性偏低（与图 3 的结论一致）。"""
    grid = _toy_grid()
    run = synth.build_run(grid, seed=5)
    truth = synth._column_integral(run.ciwc_truth[0], run.levels_hpa)
    product = synth._column_integral(run.ciwc_product[0], run.levels_hpa)
    assert float(np.nanmean(product)) < float(np.nanmean(truth))


def test_hypsometric_roundtrip():
    """斜压公式与高度反演互相自洽。"""
    elevation = np.array([0.0, 2000.0, 4500.0, 6500.0])
    pressure = surface_pressure(elevation)
    recovered = altitude_of_pressure(pressure)
    assert np.allclose(recovered, elevation, atol=5.0)
