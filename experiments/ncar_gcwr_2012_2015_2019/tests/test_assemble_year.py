from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

import assemble_year as ay  # noqa: E402


def test_time_weighted_inventory_uses_all_months_not_only_boundaries():
    months = []
    for month in range(1, 13):
        value = 100.0 if month < 12 else 1_000.0
        months.append({'qv_start_kg': value, 'qv_end_kg': value})

    annual_mean = ay._time_weighted_inventory(months, 2015, 'qv')

    assert 100.0 < annual_mean < 200.0
    assert annual_mean < 0.5 * (100.0 + 1_000.0)
