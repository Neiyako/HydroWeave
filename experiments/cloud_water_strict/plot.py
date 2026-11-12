"""cloud_water_strict 图件：LWP/IWP 场、垂直剖面、LWP–IWP 关系、恒等式残差面板。

视觉语言与 ``experiments/figure_studio`` 完全一致（Nature 双栏 180 mm、
Albers 等积投影 + 山体阴影底图、感知均匀色表、横向色标、粗体小写面板字母），
真实数据链路与仿真数据链路共用同一套渲染器，避免两套图长得不一样。

图件标签统一用英文（仓库默认字体无 CJK 字形）。所有图都写标题、单位、色标，
落盘到 run 目录并登记 sha256。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import xarray as xr

from experiments.cloud_water_strict import common, verify
from experiments.figure_studio import figures, style

FIGURE_NAMES = verify.FIGURE_NAMES

style.use_nature_style()


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


def _records(specs: list[figures.FigureSpec], target: Path) -> list[dict[str, Any]]:
    return [
        {
            "name": spec.name,
            "path": str(spec.path),
            "sha256": common.file_sha256(spec.path),
            "size_bytes": spec.path.stat().st_size,
            "title": spec.title,
        }
        for spec in specs
    ]


def plot_all(config_path: str | Path, run_id: str) -> list[dict[str, Any]]:
    """生成全部 5 张 PNG，写 figures.json 并登记到 manifest。"""
    target, stats, fields = _load_run(config_path, run_id)
    note = _partial_note(stats)
    latitude = np.asarray(fields["latitude"].values, dtype="float64")
    longitude = np.asarray(fields["longitude"].values, dtype="float64")
    lwp = np.asarray(fields["lwp"].values, dtype="float64") * 1000.0   # g m-2
    iwp = np.asarray(fields["iwp"].values, dtype="float64") * 1000.0
    source_note = (f"ERA5 clwc/ciwc, run {run_id}. {note}. "
                   "Colour scale is logarithmic; hillshade from GTOPO30.")

    specs = [
        figures.figure_map_field(
            latitude, longitude, lwp, path=target / FIGURE_NAMES[0],
            title="ERA5 liquid water path over the Tibetan Plateau",
            units="LWP (g m$^{-2}$)", note=source_note,
            cmap=figures.CMAP_LIQUID, seed=11),
        figures.figure_map_field(
            latitude, longitude, iwp, path=target / FIGURE_NAMES[1],
            title="ERA5 ice water path over the Tibetan Plateau",
            units="IWP (g m$^{-2}$)", note=source_note,
            cmap=figures.CMAP_ICE, seed=23),
        figures.figure_profile_panel(
            np.asarray(stats["profiles"]["pressure_hpa"], dtype="float64"),
            {"clwc": stats["profiles"]["clwc"], "ciwc": stats["profiles"]["ciwc"]},
            path=target / FIGURE_NAMES[2],
            title="Domain-mean clwc and ciwc vertical profile",
            note=(f"ERA5 clwc/ciwc, run {run_id}. {note}. "
                  "Solid: cos-latitude weighted mean; band: P10-P90 of grid cells.")),
        figures.figure_relation_panel(
            lwp, iwp, path=target / FIGURE_NAMES[3],
            title="Joint distribution of liquid and ice water path",
            note=(f"ERA5 clwc/ciwc, run {run_id}. {note}. "
                  "Colour shows the number of grid cells (log scale).")),
        _identity_figure(target / FIGURE_NAMES[4]),
    ]

    records = _records(specs, target)
    figures_path = target / "figures.json"
    common.atomic_write_json(figures_path, {
        "run_id": run_id,
        "generated_at": common.utc_now(),
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


def _identity_figure(path: Path) -> figures.FigureSpec:
    """恒等式残差面板：算术恒等式检查，不是物理检验。"""
    identity = verify.identity_residual_evidence()
    analytic = verify.analytic_column_check()
    a = identity["gcwr_from_total_kg"]
    scale = max(abs(a), 1e-30)
    relative_terminal = abs(identity["gcwr_from_terminal_kg"] - a) / scale
    relative_initial = abs(identity["gcwr_from_initial_kg"] - a) / scale
    items = [
        ("eq.(21) vs eq.(20)", relative_terminal),
        ("eq.(22) vs eq.(20)", relative_initial),
        ("column integral\n(analytic)", analytic["relative_error"]),
        ("negative control\n(c_net off 0.1%)", identity["negative_control"]["relative_residual"]),
    ]
    return figures.figure_identity_panel(
        items, identity["threshold_relative"], path=path,
        title="GCWR identity residual check (algebraic only)",
        note=("Arithmetic identity check of eqs. (20)-(22): it verifies that the code "
              "implements the paper's algebra, not that the physics is correct. "
              "The negative control shifts net condensation by 0.1 % and must fail."))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="cloud_water_strict 图件生成")
    parser.add_argument("--config", default=str(Path(__file__).with_name("config.yaml")))
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args(argv)
    plot_all(args.config, args.run_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
