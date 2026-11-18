from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

import process_month as pm  # noqa: E402


def test_physical_range_rejects_corrupt_ciwc():
    values = np.array([0.0, 2.3e-4, 25.05], dtype='float64')
    with pytest.raises(ValueError, match='超出物理合理范围'):
        pm._validate_physical_range('CIWC', values, Path('corrupt_ciwc.nc'))


def test_physical_range_accepts_tiny_negative_packing_noise():
    pm._validate_physical_range(
        'Q', np.array([-2.0e-5, 0.0, 1.0e-3]), Path('packing_noise.nc'))


def test_pressure_layer_mass_clips_at_surface():
    levels_pa = np.array([100.0, 500.0, 1000.0]) * 100.0
    sp_pa = np.full((2, 3), 70_000.0)
    layer = pm._pressure_layer_kg_m2(levels_pa, sp_pa)
    assert layer.shape == (3, 2, 3)
    assert np.allclose(layer.sum(axis=0), 60_000.0 / pm.G)
    assert np.allclose(layer[-1], 0.0)


def test_pressure_layer_mass_rejects_descending_levels():
    with pytest.raises(ValueError, match='严格递增'):
        pm._pressure_layer_kg_m2(
            np.array([100_000.0, 50_000.0, 100.0]),
            np.full((1, 1), 100_000.0),
        )


def test_profile_excludes_zero_mass_below_surface():
    field = np.array([[[[2.0, 100.0], [2.0, 100.0]]]], dtype='float64')
    layer_kg = np.array([[[[1.0, 0.0], [1.0, 0.0]]]], dtype='float64')
    area = np.ones((2, 2), dtype='float64')
    profile = pm._mass_weighted_profile(field, layer_kg, area)
    assert profile == pytest.approx(np.array([2.0]))


def test_positive_omega_is_downward_top_inflow():
    lat = np.array([25.0, 25.25])
    lon = np.array([70.0, 70.25])
    shape = (1, 1, 2, 2)
    zero = np.zeros(shape, dtype='float64')
    q = np.full(shape, 1.0e-3, dtype='float64')
    fields = {
        'level': np.array([100.0]),
        'q': q,
        'u': zero,
        'v': zero,
        'w': np.full(shape, 0.1, dtype='float64'),
        'clwc': zero,
        'ciwc': zero,
        'crwc': zero,
        'cswc': zero,
    }
    flux = pm._boundary_flux_one_time(
        fields, np.zeros((1, 2, 2), dtype='float64'), pm._cell_area(lat, lon),
        lat, lon, 0)
    assert flux['qv_top_in'] > 0.0
    assert flux['qv_top_out'] == pytest.approx(0.0)
