#!/usr/bin/env python3
"""图件工作台：用仿真数据渲染期刊级云水图件（仅用于制图方案验证）。

用法：
    python scripts/analysis/figure_studio_demo.py --run-id sim-20240715
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

import numpy as np

from experiments.figure_studio import figures, style
from experiments.figure_studio.synth import build_run
from experiments.figure_studio.terrain import DEFAULT_CHINA_SHP, DEFAULT_DEM, load_elevation, tibet_boundary

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ROOT / "data" / "analysis" / "figure_studio"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _stats(values: np.ndarray) -> dict[str, float]:
    finite = np.asarray(values)[np.isfinite(values)]
    return {
        "mean": float(finite.mean()),
        "p05": float(np.percentile(finite, 5)),
        "median": float(np.percentile(finite, 50)),
        "p95": float(np.percentile(finite, 95)),
        "max": float(finite.max()),
    }


def _write_fields(run, path: Path) -> None:
    """落盘合成场，便于复核与二次绘图（自描述：来源写进全局属性）。"""
    import xarray as xr

    dataset = xr.Dataset(
        {
            "clwc_truth": (("time", "level", "latitude", "longitude"), run.clwc_truth),
            "ciwc_truth": (("time", "level", "latitude", "longitude"), run.ciwc_truth),
            "clwc_product": (("time", "level", "latitude", "longitude"), run.clwc_product),
            "ciwc_product": (("time", "level", "latitude", "longitude"), run.ciwc_product),
            "lwp_truth": (("time", "latitude", "longitude"), run.lwp_truth),
            "iwp_truth": (("time", "latitude", "longitude"), run.iwp_truth),
            "lwp_product": (("time", "latitude", "longitude"), run.lwp_product),
            "iwp_product": (("time", "latitude", "longitude"), run.iwp_product),
            "temperature": (("level", "latitude", "longitude"), run.temperature),
            "surface_pressure": (("latitude", "longitude"), run.surface_pressure),
            "elevation": (("latitude", "longitude"), run.grid.elevation),
        },
        coords={
            "time": ("time", run.times),
            "level": ("level", run.levels_hpa),
            "latitude": ("latitude", run.grid.latitude),
            "longitude": ("longitude", run.grid.longitude),
        },
        attrs={
            "title": "Synthetic clwc/ciwc fields for figure-style validation",
            "source": "synthetic; not observational data",
            "clwc_units": "kg kg-1",
            "ciwc_units": "kg kg-1",
            "lwp_units": "kg m-2",
            "iwp_units": "kg m-2",
            "seed": run.meta["seed"],
        },
    )
    dataset.to_netcdf(path)
    dataset.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="仿真数据 + 期刊级图件")
    parser.add_argument("--run-id", default="sim-20240715")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--seed", type=int, default=20240715)
    parser.add_argument("--dem", default=str(DEFAULT_DEM))
    parser.add_argument("--shp-dir", default=str(DEFAULT_CHINA_SHP))
    args = parser.parse_args(argv)

    style.use_nature_style()
    target = Path(args.output_dir) / args.run_id
    target.mkdir(parents=True, exist_ok=True)

    started = time.time()
    grid = load_elevation(args.dem)
    boundary = tibet_boundary(args.shp_dir)
    run = build_run(grid, seed=args.seed)

    specs = [
        figures.figure_spatial(run, boundary=boundary, path=target / "fig1_spatial.png"),
        figures.figure_vertical(run, path=target / "fig2_vertical.png"),
        figures.figure_error(run, path=target / "fig3_error.png"),
        figures.figure_synoptic(run, path=target / "fig4_synoptic.png", boundary=boundary),
    ]

    _write_fields(run, target / "fields.nc")

    truth_cwp = (run.lwp_truth + run.iwp_truth) * 1000.0
    product_cwp = (run.lwp_product + run.iwp_product) * 1000.0
    mask = truth_cwp[2] > 1.0
    summary = {
        "run_id": args.run_id,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "data_source": "synthetic (figure-style validation only)",
        "seed": args.seed,
        "grid": {
            "latitude": [float(grid.latitude[0]), float(grid.latitude[-1]), 0.25],
            "longitude": [float(grid.longitude[0]), float(grid.longitude[-1]), 0.25],
            "levels_hpa": run.levels_hpa.tolist(),
        },
        "lwp_g_m2": _stats(run.lwp_truth[2] * 1000.0),
        "iwp_g_m2": _stats(run.iwp_truth[2] * 1000.0),
        "cwp_g_m2": _stats(truth_cwp[2]),
        "product_error_g_m2": {
            "bias": float(np.mean(product_cwp[2][mask] - truth_cwp[2][mask])),
            "rmse": float(np.sqrt(np.mean((product_cwp[2][mask] - truth_cwp[2][mask]) ** 2))),
            "r": float(np.corrcoef(truth_cwp[2][mask], product_cwp[2][mask])[0, 1]),
        },
        "figures": [
            {
                "name": spec.name,
                "path": str(spec.path),
                "title": spec.title,
                "sha256": _sha256(spec.path),
                "size_bytes": spec.path.stat().st_size,
            }
            for spec in specs
        ],
        "elapsed_s": round(time.time() - started, 2),
    }
    (target / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2),
                                         encoding="utf-8")
    print(json.dumps({"run_dir": str(target),
                      "figures": [str(spec.path) for spec in specs]},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
