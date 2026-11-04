"""cloud_water_strict 图件：LWP/IWP 场、垂直剖面、LWP–IWP 关系、恒等式残差面板。

图件标签统一用英文（仓库默认 DejaVu Sans 无 CJK 字形；缺字体时不拿方框乱码
冒充中文）。所有图都写标题、单位、色标，落盘到 run 目录并登记 sha256。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import xarray as xr

from experiments.cloud_water_strict import common, verify
from experiments.tp_cloud_water.budget import G_STANDARD

FIGURE_NAMES = verify.FIGURE_NAMES

plt.rcParams.update({
    "figure.dpi": 150,
    "savefig.dpi": 150,
    "font.size": 9,
    "axes.titlesize": 10,
    "axes.labelsize": 9,
    "axes.grid": False,
    "axes.unicode_minus": False,
    "figure.autolayout": False,
})


def _partial_note(stats: dict[str, Any]) -> str:
    column = stats["column"]
    full = column["full_column_hpa"]
    partial = "partial column" if column["partial_column"] else "full column"
    return (f"{partial}: {column['covered_top_hpa']:.0f}-"
            f"{column['covered_bottom_hpa']:.0f} hPa "
            f"({column['coverage_fraction']:.1%} of nominal "
            f"{full[0]:.0f}-{full[1]:.0f} hPa); no extrapolation")


def _load_run(config_path: str | Path, run_id: str) -> tuple[Path, dict[str, Any], xr.Dataset]:
    config = common.load_config(config_path)
    target = common.run_dir(config, run_id, create=False)
    stats_path = target / "stats.json"
    fields_path = target / "fields.nc"
    for path in (stats_path, fields_path, target / "manifest.json"):
        if not path.exists():
            raise FileNotFoundError(f"缺少 {path}；先运行 compute.py")
    stats = json.loads(stats_path.read_text(encoding="utf-8"))
    with xr.open_dataset(fields_path) as raw:
        fields = raw.load()
    return target, stats, fields


def _save(figure: plt.Figure, path: Path, title: str) -> dict[str, Any]:
    figure.tight_layout()
    figure.savefig(path, bbox_inches="tight")
    plt.close(figure)
    return {
        "name": path.name,
        "path": str(path),
        "sha256": common.file_sha256(path),
        "size_bytes": path.stat().st_size,
        "title": title,
    }


def _field_figure(field: np.ndarray, latitude: np.ndarray, longitude: np.ndarray,
                  *, title: str, units: str, note: str, path: Path) -> dict[str, Any]:
    data = np.asarray(field, dtype="float64") * 1000.0  # kg·m⁻² → g·m⁻²
    figure, axis = plt.subplots(figsize=(7.8, 4.6))
    if np.any(np.isfinite(data)):
        mesh = axis.pcolormesh(longitude, latitude, data, cmap="viridis", shading="auto")
        colorbar = figure.colorbar(mesh, ax=axis, pad=0.02)
        colorbar.set_label(units)
    else:
        axis.text(0.5, 0.5, "all grid cells are NaN", ha="center", va="center",
                  transform=axis.transAxes)
    axis.set_xlabel("Longitude (°E)")
    axis.set_ylabel("Latitude (°N)")
    axis.set_title(f"{title}\n{note}", fontsize=9)
    return _save(figure, path, title)


def _profile_figure(profile: dict[str, Any], *, note: str, path: Path) -> dict[str, Any]:
    pressure = np.asarray(profile["pressure_hpa"], dtype="float64")
    figure, axis = plt.subplots(figsize=(5.8, 4.6))
    series = (("clwc", "tab:blue", "clwc (liquid)"),
              ("ciwc", "tab:orange", "ciwc (ice)"))
    for key, color, label in series:
        values = np.asarray(profile[key]["mean_mg_kg"], dtype="float64")
        low = np.asarray(profile[key]["p10_mg_kg"], dtype="float64")
        high = np.asarray(profile[key]["p90_mg_kg"], dtype="float64")
        axis.plot(values, pressure, "o-", color=color, label=label)
        axis.fill_betweenx(pressure, low, high, color=color, alpha=0.16, linewidth=0)
    axis.set_ylim(float(pressure.max()), float(pressure.min()))
    axis.set_xlabel("Cloud water mixing ratio (mg kg$^{-1}$)")
    axis.set_ylabel("Pressure (hPa)")
    axis.set_title("Regional mean clwc/ciwc vertical profile\n"
                   f"solid = cos-weighted mean, band = P10-P90\n{note}", fontsize=9)
    axis.legend(loc="best", fontsize=8)
    axis.grid(True, linestyle=":", linewidth=0.5, alpha=0.7)
    return _save(figure, path, "clwc/ciwc vertical profile")


def _relation_figure(fields: xr.Dataset, *, note: str, path: Path) -> dict[str, Any]:
    lwp = np.asarray(fields["lwp"].values, dtype="float64") * 1000.0
    iwp = np.asarray(fields["iwp"].values, dtype="float64") * 1000.0
    latitude = np.asarray(fields["latitude"].values, dtype="float64")
    lat2d = np.broadcast_to(latitude[:, None], lwp.shape)
    mask = np.isfinite(lwp) & np.isfinite(iwp) & (lwp > 0.0) & (iwp > 0.0)
    figure, axis = plt.subplots(figsize=(6.4, 4.8))
    if int(mask.sum()) >= 2:
        scatter = axis.scatter(lwp[mask], iwp[mask], c=lat2d[mask], s=10, alpha=0.7,
                               cmap="plasma", edgecolors="none")
        colorbar = figure.colorbar(scatter, ax=axis, pad=0.02)
        colorbar.set_label("Latitude (°N)")
        axis.set_xscale("log")
        axis.set_yscale("log")
        low = max(min(lwp[mask].min(), iwp[mask].min()) * 0.7, 1e-3)
        high = max(lwp[mask].max(), iwp[mask].max()) * 1.4
        axis.plot([low, high], [low, high], "k--", linewidth=0.8, label="1:1")
        r_linear = float(np.corrcoef(lwp[mask], iwp[mask])[0, 1])
        r_log = float(np.corrcoef(np.log10(lwp[mask]), np.log10(iwp[mask]))[0, 1])
        axis.set_title("LWP vs IWP per grid cell\n"
                       f"n={int(mask.sum())}, Pearson r={r_linear:.2f} (linear), "
                       f"r={r_log:.2f} (log10)", fontsize=9)
        axis.legend(loc="upper left", fontsize=8)
    else:
        axis.text(0.5, 0.5, "not enough positive LWP/IWP pairs", ha="center",
                  va="center", transform=axis.transAxes)
        axis.set_title("LWP vs IWP per grid cell", fontsize=9)
    axis.set_xlabel("LWP (g m$^{-2}$)")
    axis.set_ylabel("IWP (g m$^{-2}$)")
    figure.text(0.5, -0.02, note, ha="center", fontsize=7.5, color="0.35")
    return _save(figure, path, "LWP-IWP relation")


def _identity_figure(path: Path) -> dict[str, Any]:
    identity = verify.identity_residual_evidence()
    analytic = verify.analytic_column_check()
    a = identity["gcwr_from_total_kg"]
    scale = max(abs(a), 1e-30)
    relative_terminal = abs(identity["gcwr_from_terminal_kg"] - a) / scale
    relative_initial = abs(identity["gcwr_from_initial_kg"] - a) / scale
    values = [relative_terminal, relative_initial, analytic["relative_error"],
              identity["negative_control"]["relative_residual"]]
    labels = ["eq.(21) vs eq.(20)", "eq.(22) vs eq.(20)",
              "column integral\n(analytic check)", "negative control\n(c_net off 0.1%)"]
    floor = 1e-18
    heights = [max(float(value), floor) if np.isfinite(value) else floor for value in values]
    positions = np.arange(len(labels))
    figure, axis = plt.subplots(figsize=(7.2, 4.6))
    colors = ["tab:blue", "tab:blue", "tab:green", "tab:red"]
    bars = axis.bar(positions, heights, color=colors, width=0.6)
    axis.set_yscale("log")
    axis.set_ylim(1e-18, 1.0)
    axis.axhline(identity["threshold_relative"], color="black", linestyle="--",
                 linewidth=0.9, label=f"threshold = {identity['threshold_relative']:.0e}")
    axis.set_xticks(positions)
    axis.set_xticklabels(labels, fontsize=8)
    axis.set_ylabel("relative residual (dimensionless, log scale)")
    axis.set_title("GCWR identity (20)(21)(22) residual panel\n"
                   "arithmetic identity check only, not a physical test", fontsize=9)
    for bar, value, height in zip(bars, values, heights, strict=True):
        text = "0 (below 1e-18)" if value <= 0 else f"{value:.1e}"
        axis.annotate(text, (bar.get_x() + bar.get_width() / 2, height * 1.6),
                      ha="center", va="bottom", fontsize=7.5)
    axis.legend(loc="upper left", fontsize=8)
    return _save(figure, path, "GCWR identity residual panel")


def plot_all(config_path: str | Path, run_id: str) -> list[dict[str, Any]]:
    """生成全部 5 张 PNG，写 figures.json 并登记到 manifest。"""
    target, stats, fields = _load_run(config_path, run_id)
    note = _partial_note(stats)
    latitude = np.asarray(fields["latitude"].values, dtype="float64")
    longitude = np.asarray(fields["longitude"].values, dtype="float64")
    records = [
        _field_figure(
            np.asarray(fields["lwp"].values), latitude, longitude,
            title="ERA5 liquid water path (LWP)",
            units="LWP (g m$^{-2}$)", note=note, path=target / FIGURE_NAMES[0]),
        _field_figure(
            np.asarray(fields["iwp"].values), latitude, longitude,
            title="ERA5 ice water path (IWP)",
            units="IWP (g m$^{-2}$)", note=note, path=target / FIGURE_NAMES[1]),
        _profile_figure(stats["profiles"], note=note,
                        path=target / FIGURE_NAMES[2]),
        _relation_figure(fields, note=note, path=target / FIGURE_NAMES[3]),
        _identity_figure(target / FIGURE_NAMES[4]),
    ]
    figures_path = target / "figures.json"
    common.atomic_write_json(figures_path, {
        "run_id": run_id,
        "generated_at": common.utc_now(),
        "g_m_s2": G_STANDARD,
        "figures": records,
    })
    manifest_path = target / "manifest.json"
    manifest = common.load_json(manifest_path)
    for record in records:
        manifest = common.record_artifact(manifest_path, Path(record["path"]), manifest)
    manifest = common.record_artifact(manifest_path, figures_path, manifest)
    # e2e 顺序是 compute→verify→plot：verify 写 summary 时图件尚未生成，这里补回。
    summary_path = target / "summary.json"
    if summary_path.exists():
        summary = common.load_json(summary_path)
        summary["figures"] = records
        common.atomic_write_json(summary_path, summary)
        common.record_artifact(manifest_path, summary_path, manifest)
    print(json.dumps({"run_id": run_id, "figures": [item["path"] for item in records]},
                     ensure_ascii=False, indent=2))
    return records


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="cloud_water_strict 图件生成")
    parser.add_argument("--config", default=str(Path(__file__).with_name("config.yaml")))
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args(argv)
    plot_all(args.config, args.run_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
