"""cloud_water_strict 离线单测：合成 fixture 建卷 → compute → plot → verify。

不接触真实 ERA5/DBAS 外接盘；真实数据验证见 ``docs/CLOUD_WATER_VERIFICATION.md``。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
import xarray as xr
import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from experiments.cloud_water_strict import common, compute, plot, verify

FIXTURE_SCRIPT = ROOT / "scripts" / "demo" / "make_clwc_fixture.py"


def _env() -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(ROOT / "src"), str(ROOT)])
    env["MPLBACKEND"] = "Agg"
    return env


def _run(args: list[str], cwd: Path = ROOT) -> subprocess.CompletedProcess[str]:
    # 刻意 check=False：测试自己断言 returncode（含期望失败的情形）
    return subprocess.run([sys.executable, *args], cwd=cwd, env=_env(),
                          capture_output=True, text=True, timeout=300, check=False)


def _build_fixture(dest: Path, *extra: str) -> Path:
    result = _run([str(FIXTURE_SCRIPT), str(dest), *extra])
    assert result.returncode == 0, result.stderr
    config_path = dest / "config.yaml"
    assert config_path.exists()
    return config_path


def _run_module(name: str, config_path: Path, run_id: str, *extra: str) -> subprocess.CompletedProcess[str]:
    return _run(["-m", f"experiments.cloud_water_strict.{name}",
                 "--config", str(config_path), "--run-id", run_id, *extra])


# ------------------------------------------------------------ 恒等式与积分

def test_gcwr_identity_residual_machine_precision():
    """式 (20)(21)(22) 相对残差 ≤ 1e-12，且负控制能检出故意偏置。"""
    evidence = verify.identity_residual_evidence()
    assert evidence["passed"] is True
    assert evidence["relative_residual"] <= 1e-12
    assert evidence["inventory_identity_ok"] is True
    # 三种写法数值证据都要落盘（不是只给一个 bool）
    assert evidence["spread_kg"] >= 0.0
    assert evidence["negative_control"]["detected"] is True
    assert evidence["negative_control"]["relative_residual"] > 1e-12


def test_constant_field_column_integral_weight():
    """常数混合比场：LWP 必须严格等于 q/g·Δp（梯形权重与单位）。"""
    check = verify.analytic_column_check()
    assert check["passed"] is True
    assert check["relative_error"] <= 1e-12
    assert check["lwp_computed_kg_m2"] == pytest.approx(check["lwp_expected_kg_m2"], rel=1e-14)
    assert check["coverage_hpa"] == pytest.approx(200.0)
    assert check["partial_column"] is True


def test_partial_column_flag_and_coverage():
    """3 层 500/400/300 hPa 只能标 partial_column=true，并给出覆盖厚度。"""
    config = {"pressure": {"full_column_hpa": [1.0, 1000.0], "partial_tolerance_hpa": 1.0}}
    pressure_pa = np.array([300.0, 400.0, 500.0]) * 100.0
    coverage = compute.coverage_metadata(pressure_pa, config)
    assert coverage["partial_column"] is True
    assert coverage["coverage_hpa"] == pytest.approx(200.0)
    assert coverage["coverage_fraction"] == pytest.approx(200.0 / 999.0)
    assert coverage["covered_layers_hpa"] == [300.0, 400.0, 500.0]
    assert coverage["intervals_hpa"] == [100.0, 100.0]
    # 名义整列（覆盖 1–1000 hPa）不应被误标为 partial
    full = compute.coverage_metadata(
        np.array([1.0, 100.0, 500.0, 1000.0]) * 100.0, config)
    assert full["partial_column"] is False
    assert full["coverage_hpa"] == pytest.approx(999.0)


def test_region_mean_cos_latitude_weighting():
    """cosφ 面积加权：常数场均值仍为常数；cosφ 场均值等于 Σcos²/Σcos。"""
    latitude = np.array([25.0, 30.0, 35.0, 40.0])
    constant = np.ones((4, 5))
    mean, valid = compute.region_mean(constant, latitude)
    assert valid == 20
    assert mean == pytest.approx(1.0)
    field = np.repeat(np.cos(np.deg2rad(latitude))[:, None], 5, axis=1)
    weighted, _ = compute.region_mean(field, latitude)
    expected = np.sum(np.cos(np.deg2rad(latitude)) ** 2 * 5) / \
        np.sum(np.cos(np.deg2rad(latitude)) * 5)
    assert weighted == pytest.approx(expected)
    # 与未加权平均明显不同，说明权重真的生效
    assert weighted != pytest.approx(float(np.mean(field)), rel=1e-4)


def test_mixing_ratio_unit_conversion():
    """kg/kg 与 g/kg 都要收敛到同一 kg·kg⁻¹；未知单位必须报错。"""
    values = np.array([1.0e-4, 2.0e-4])
    kg, factor_kg, _ = compute.convert_mixing_ratio(values, "kg kg**-1", "clwc")
    assert factor_kg == 1.0
    assert np.allclose(kg, values)
    gram, factor_gram, _ = compute.convert_mixing_ratio(values, "g kg**-1", "clwc")
    assert factor_gram == 1.0e-3
    assert np.allclose(gram, values * 1.0e-3)
    with pytest.raises(ValueError, match="单位"):
        compute.convert_mixing_ratio(values, "%", "clwc")


# ---------------------------------------------------------------- 端到端

def test_fixture_end_to_end_compute_plot_verify(tmp_path):
    """合成 fixture 全流程：compute→plot→verify，产物/清单/报告都要对。"""
    fixture = tmp_path / "fixture"
    config_path = _build_fixture(fixture)
    run_dir = fixture / "analysis" / "runs" / "fixture"

    for module in ("compute", "plot", "verify"):
        result = _run_module(module, config_path, "fixture")
        assert result.returncode == 0, result.stderr

    stats = json.loads((run_dir / "stats.json").read_text(encoding="utf-8"))
    assert stats["column"]["partial_column"] is True
    assert stats["column"]["coverage_hpa"] == pytest.approx(200.0)
    assert stats["fields"]["lwp"]["mean_g_m2"] > 0
    assert stats["input"]["catalog_imported"] is True
    assert stats["units"]["clwc_raw_unit"] == "kg kg**-1"
    assert stats["time"]["selected_time"].startswith("2024-01-01")

    with xr.open_dataset(run_dir / "fields.nc") as fields:
        assert fields["lwp"].attrs["units"] == "kg m-2"
        assert fields["iwp"].attrs["units"] == "kg m-2"
        assert fields["lwp"].shape == (61, 141)
        assert np.isfinite(fields["lwp"].values).all()
        assert bool(fields.attrs["partial_column"]) is True

    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["identity"]["passed"] is True
    assert summary["analytic"]["passed"] is True
    assert summary["overall_state"] in {"CONDITIONAL_PASS", "INSUFFICIENT_EVIDENCE"}
    assert len(summary["figures"]) == len(plot.FIGURE_NAMES)

    for name in plot.FIGURE_NAMES:
        png = run_dir / name
        assert png.exists() and png.stat().st_size > 1000
    assert (run_dir / "report.md").exists()
    report = (run_dir / "report.md").read_text(encoding="utf-8")
    assert "NOT_RUN" in report
    assert "partial_column=true" in report
    assert "五态判定表" in report

    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "completed"
    assert manifest["partial_column"] is True
    assert manifest["verdict_counts"]["NOT_RUN"] == 2
    artifact_paths = {item["path"] for item in manifest["artifacts"]}
    for name in ("fields.nc", "stats.json", "report.md", "summary.json",
                 *plot.FIGURE_NAMES):
        assert any(path.endswith(name) for path in artifact_paths)

    inputs = json.loads((run_dir / "inputs.json").read_text(encoding="utf-8"))
    source = fixture / "volume" / "ERA5_2024_cloud_water.nc"
    assert inputs["files"][0]["sha256"] == common.file_sha256(source)


def test_separate_variable_files_merge(tmp_path):
    """clwc/ciwc 分文件时按坐标合并，结果与单文件一致（同合成场）。"""
    fixture = tmp_path / "fixture"
    config_path = _build_fixture(fixture, "--separate-files")
    result = _run_module("compute", config_path, "separate")
    assert result.returncode == 0, result.stderr
    stats = json.loads((fixture / "analysis" / "runs" / "separate" /
                        "stats.json").read_text(encoding="utf-8"))
    assert stats["fields"]["lwp"]["mean_g_m2"] == pytest.approx(114.21877, rel=1e-3)
    assert stats["fields"]["iwp"]["mean_g_m2"] == pytest.approx(16.34329, rel=1e-3)


def test_missing_ice_variable_fails(tmp_path):
    """缺 ciwc 必须报错并点名变量，绝不静默只算 LWP。"""
    fixture = tmp_path / "fixture"
    config_path = _build_fixture(fixture, "--drop-ciwc")
    result = _run_module("compute", config_path, "missing-ice")
    assert result.returncode != 0
    assert "ciwc" in (result.stderr + result.stdout)


def test_missing_dataset_in_catalog_fails(tmp_path):
    """catalog 没有该 dataset_id 时给出可操作的报错。"""
    fixture = tmp_path / "fixture"
    config_path = _build_fixture(fixture)
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    raw["dataset_id"] = "not_imported_dataset"
    wrong = fixture / "wrong.yaml"
    wrong.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    config = common.load_config(wrong)
    with pytest.raises(ValueError, match="dataset"):
        common.catalog_inputs(config)


def test_volume_offline_gives_clear_error(tmp_path):
    """卷挂载路径不可访问时报错信息要给出已检查的路径。"""
    fixture = tmp_path / "fixture"
    config_path = _build_fixture(fixture)
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    import sqlite3
    db = sqlite3.connect(raw["catalog"])
    db.execute("UPDATE volumes SET last_mount_path=?, root_path=? WHERE volume_id=?",
               (str(fixture / "no_such_mount"), str(fixture / "no_such_mount"),
                raw["volume_id"]))
    db.commit()
    db.close()
    config = common.load_config(config_path)
    with pytest.raises(FileNotFoundError, match="不可访问"):
        common.catalog_inputs(config)


def test_script_mode_e2e_order(tmp_path):
    """e2e 脚本以「python 文件路径」按 compute→verify→plot 调用，必须同样跑通。"""
    fixture = tmp_path / "fixture"
    config_path = _build_fixture(fixture, "--times", "4")
    run_dir = fixture / "analysis" / "runs" / "fixture"
    for script in ("compute.py", "verify.py", "plot.py"):
        result = _run([str(ROOT / "experiments" / "cloud_water_strict" / script),
                       "--config", str(config_path), "--run-id", "fixture"])
        assert result.returncode == 0, f"{script}: {result.stderr}"
    stats = json.loads((run_dir / "stats.json").read_text(encoding="utf-8"))
    assert stats["time"]["n_times"] == 4
    multi = stats["multi_time"]
    assert multi["n_times"] == 4
    assert len(multi["lwp"]["per_time_mean_g_m2"]) == 4
    assert multi["lwp"]["min_g_m2"] <= multi["lwp"]["max_g_m2"]
    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["multi_time"]["n_times"] == 4
    assert len(summary["figures"]) == len(plot.FIGURE_NAMES)
    assert summary["overall_state"] in {"CONDITIONAL_PASS", "INSUFFICIENT_EVIDENCE"}
    report = (run_dir / "report.md").read_text(encoding="utf-8")
    for name in plot.FIGURE_NAMES:
        assert name in report
    assert "多时次快照" in report
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "completed"
    assert sum(1 for item in manifest["artifacts"] if item["path"].endswith(".png")) == 5
