"""读取真实 ERA5 clwc/ciwc，做气压层梯形积分与 cosφ 区域平均。

物理口径（与 README §2 对齐）：

    LWP = ∫_{p_top}^{p_bottom} (clwc / g) dp        [kg·m⁻²]
    IWP = ∫_{p_top}^{p_bottom} (ciwc / g) dp        [kg·m⁻²]

离散化：对相邻气压层 p_k < p_{k+1} 用梯形权重 0.5·(q_k+q_{k+1})·Δp / g。
**不做顶层/底层外推**：只覆盖数据实际给出的气压层区间；区间小于名义整列
（config.pressure.full_column_hpa）时显式写 ``partial_column=true`` 并给出
覆盖层数与厚度，绝不把部分列当整列。缺测（NaN）不会被当作 0 参与积分：
任一端点缺测的区间使该格点柱含量为 NaN。
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import numpy as np
import xarray as xr

from experiments.cloud_water_strict import common
from experiments.tp_cloud_water.budget import G_STANDARD, cell_area_latlon

# 坐标别名：ERA5 单时次 NetCDF 常见 valid_time/pressure_level/latitude/longitude。
_COORD_ALIASES = {
    "time": ("time", "valid_time", "datetime"),
    "pressure_level": ("pressure_level", "level", "isobaricInhPa", "plev", "pressure"),
    "latitude": ("latitude", "lat"),
    "longitude": ("longitude", "lon"),
}
_HPA_UNITS = frozenset({"hpa", "hectopascal", "hectopascals", "mb", "millibar", "millibars"})
_PA_UNITS = frozenset({"pa", "pascal", "pascals"})
_KGKG_UNITS = frozenset({"kgkg-1", "kgkg^-1", "kg/kg", "kgkg⁻¹", "kgkg**-1"})
_GKG_UNITS = frozenset({"gkg-1", "gkg^-1", "g/kg", "gkg⁻¹", "gkg**-1"})


# ------------------------------------------------------------- 单位与坐标口径

def _unit_key(units: Any) -> str:
    return str(units or "").strip().lower().replace(" ", "").replace("**", "^")


def pressure_to_pa(values: np.ndarray, units: Any, *, coord_name: str = "pressure_level",
                   explicit_units: str | None = None) -> tuple[np.ndarray, str]:
    """气压层转 Pa；单位缺失或未知直接报错，不做静默猜测。"""
    raw = explicit_units if explicit_units else units
    key = _unit_key(raw)
    values = np.asarray(values, dtype="float64")
    if key in _PA_UNITS:
        return values, "Pa"
    if key in _HPA_UNITS:
        return values * 100.0, "hPa"
    if not key:
        raise ValueError(
            f"气压层坐标 {coord_name!r} 缺少 units 属性，无法确定 hPa/Pa；"
            "请在 config.pressure.units 显式声明")
    raise ValueError(f"不支持的气压层单位 {raw!r}（坐标 {coord_name!r}）")


def convert_mixing_ratio(values: np.ndarray, units: Any, var_name: str) -> tuple[np.ndarray, float, str]:
    """云水混合比统一为 kg·kg⁻¹；返回 (数值, 换算因子, 原始单位)。"""
    key = _unit_key(units)
    values = np.asarray(values, dtype="float64")
    if key in _KGKG_UNITS:
        return values, 1.0, str(units or "")
    if key in _GKG_UNITS:
        return values * 1.0e-3, 1.0e-3, str(units or "")
    if not key:
        raise ValueError(
            f"变量 {var_name} 缺少 units 属性，无法确认是否为 kg·kg⁻¹；拒绝静默换算")
    raise ValueError(f"变量 {var_name} 的单位 {units!r} 不是 kg·kg⁻¹ 或 g·kg⁻¹")


# ---------------------------------------------------------------- 柱积分与平均

def column_water_path(q: np.ndarray, p_pa: np.ndarray, *, g: float = G_STANDARD) -> np.ndarray:
    """气压层梯形积分 ∫(q/g)dp，返回 kg·m⁻²；NaN 传播为 NaN（不当 0）。"""
    q_arr = np.asarray(q, dtype="float64")
    p_arr = np.asarray(p_pa, dtype="float64").ravel()
    if q_arr.ndim < 1 or q_arr.shape[0] != p_arr.size:
        raise ValueError(
            f"q 首维({q_arr.shape[0] if q_arr.ndim else 0}) 必须等于气压层数({p_arr.size})")
    if p_arr.size < 2:
        raise ValueError("至少需要 2 个气压层才能做梯形积分")
    if not np.all(np.isfinite(p_arr)):
        raise ValueError("气压层存在非有限值")
    order = np.argsort(p_arr, kind="stable")
    p_sorted = p_arr[order]
    q_sorted = q_arr[order]
    dp = np.diff(p_sorted)
    if np.any(dp <= 0):
        raise ValueError("气压层必须严格单调（排序后仍出现重复层）")
    shape = (dp.size,) + (1,) * (q_sorted.ndim - 1)
    contribution = 0.5 * (q_sorted[:-1] + q_sorted[1:]) * dp.reshape(shape) / float(g)
    return contribution.sum(axis=0)


def region_mean(field: np.ndarray, latitude: np.ndarray) -> tuple[float, int]:
    """cosφ 面积加权区域平均；返回 (均值, 有效格点数)。全缺测时返回 NaN。"""
    values = np.asarray(field, dtype="float64")
    lat = np.asarray(latitude, dtype="float64").ravel()
    if values.ndim != 2 or values.shape[0] != lat.size:
        raise ValueError(f"field 形状 {values.shape} 与纬度长度 {lat.size} 不匹配")
    weights = np.cos(np.deg2rad(lat))[:, None] * np.ones((1, values.shape[1]))
    finite = np.isfinite(values)
    weight_sum = float(np.sum(weights * finite))
    if weight_sum <= 0:
        return float("nan"), 0
    weighted = float(np.sum(np.where(finite, values, 0.0) * weights))
    return weighted / weight_sum, int(finite.sum())


def coverage_metadata(p_pa: np.ndarray, config: dict[str, Any]) -> dict[str, Any]:
    """柱积分覆盖范围与 partial_column 判定（不含外推）。"""
    levels_hpa = np.asarray(p_pa, dtype="float64").ravel() / 100.0
    levels_hpa = np.sort(levels_hpa)
    pressure_cfg = config["pressure"]
    full = [float(value) for value in pressure_cfg["full_column_hpa"]]
    full_min, full_max = min(full), max(full)
    tolerance = float(pressure_cfg.get("partial_tolerance_hpa", 1.0))
    coverage = float(levels_hpa[-1] - levels_hpa[0])
    full_span = full_max - full_min
    partial = bool(
        levels_hpa[0] > full_min + tolerance
        or levels_hpa[-1] < full_max - tolerance
        or coverage < full_span - tolerance
    )
    expected = [float(value) for value in pressure_cfg.get("expected_levels_hpa", [])]
    inside = [value for value in expected
              if levels_hpa[0] - tolerance <= value <= levels_hpa[-1] + tolerance]
    missing = [value for value in inside
               if not np.any(np.abs(levels_hpa - value) <= tolerance)]
    return {
        "partial_column": partial,
        "covered_layers_hpa": [float(value) for value in levels_hpa],
        "covered_bottom_hpa": float(levels_hpa[-1]),
        "covered_top_hpa": float(levels_hpa[0]),
        "coverage_hpa": coverage,
        "coverage_fraction": float(coverage / full_span) if full_span > 0 else float("nan"),
        "full_column_hpa": [full_min, full_max],
        "missing_expected_levels_hpa": missing,
        "intervals_hpa": [float(value) for value in np.diff(levels_hpa)],
    }


# ---------------------------------------------------------- 数据集打开与规范

def _find_coord(dataset: xr.Dataset, aliases: tuple[str, ...]) -> str | None:
    for name in aliases:
        if name in dataset.coords or name in dataset.dims or name in dataset.variables:
            return name
    return None


def normalize_dataset(dataset: xr.Dataset) -> xr.Dataset:
    """把坐标名统一为 time/pressure_level/latitude/longitude。"""
    rename: dict[str, str] = {}
    for canonical, aliases in _COORD_ALIASES.items():
        found = _find_coord(dataset, aliases)
        if found is None:
            raise ValueError(f"数据缺少坐标 {canonical}（已尝试别名 {aliases}）")
        if found != canonical:
            rename[found] = canonical
    result = dataset.rename(rename) if rename else dataset
    for canonical in _COORD_ALIASES:
        if canonical not in result.coords and canonical not in result.variables:
            raise ValueError(f"坐标规范化后仍缺少 {canonical}")
    return result


def _open_variable(files: list[common.InputFile], var: str) -> xr.Dataset:
    """从 catalog 文件里取指定变量；多个文件按 time 维拼接。"""
    found: list[xr.Dataset] = []
    for item in files:
        with xr.open_dataset(item.path, decode_times=True) as raw:
            if var not in raw.variables:
                continue
            found.append(raw[[var]].load())
    if not found:
        raise ValueError(f"输入文件中缺少变量 {var!r}（catalog 共 {len(files)} 个 .nc）")
    if len(found) == 1:
        return found[0]
    # 多文件：容忍每文件只有标量 time 坐标的情况，先升成 time 维再拼接。
    normalized: list[xr.Dataset] = []
    for item in found:
        if "time" in item.dims:
            normalized.append(item)
        elif "time" in item.coords:
            value = item["time"].values
            normalized.append(item.drop_vars("time").expand_dims(time=[value]))
        else:
            raise ValueError(f"变量 {var!r} 分多个文件但缺少 time 维/坐标，无法安全拼接")
    return xr.concat(normalized, dim="time")


def load_cloud_water(config: dict[str, Any], inputs: dict[str, Any]
                     ) -> tuple[xr.Dataset, dict[str, Any]]:
    """读取 clwc/ciwc → 规范坐标 → 区域裁剪 → 单位换算 → 时次选择。"""
    files: list[common.InputFile] = inputs["files"]
    liquid_name = str(config["variables"]["liquid"])
    ice_name = str(config["variables"]["ice"])
    liquid_raw = _open_variable(files, liquid_name)
    ice_raw = _open_variable(files, ice_name)
    dataset = xr.merge([liquid_raw, ice_raw], compat="override")
    dataset = normalize_dataset(dataset)

    # 气压层：hPa/Pa → Pa，并升序排列
    pressure_coord = dataset["pressure_level"]
    explicit = config["pressure"].get("units")
    p_pa, pressure_unit = pressure_to_pa(
        np.asarray(pressure_coord.values), pressure_coord.attrs.get("units"),
        coord_name="pressure_level", explicit_units=explicit)
    order = np.argsort(p_pa, kind="stable")
    dataset = dataset.isel(pressure_level=order)
    dataset = dataset.assign_coords(pressure_level=("pressure_level", p_pa[order] / 100.0))

    # 变量单位：统一 kg·kg⁻¹（只接受 kg/kg 与 g/kg，异常单位报错）
    unit_notes: dict[str, Any] = {
        "pressure_raw_unit": str(pressure_coord.attrs.get("units") or explicit or ""),
        "pressure_interpreted_as": pressure_unit,
        "pressure_conversion_factor": 100.0 if pressure_unit == "hPa" else 1.0,
    }
    for name in (liquid_name, ice_name):
        values, factor, raw_unit = convert_mixing_ratio(
            np.asarray(dataset[name].values), dataset[name].attrs.get("units"), name)
        dataset[name].values = values
        dataset[name].attrs["units"] = "kg kg**-1"
        unit_notes[f"{name}_raw_unit"] = raw_unit
        unit_notes[f"{name}_conversion_factor"] = factor

    # 时次：保留全部时次，由 run() 选 config.time.index 的时次做场/统计；
    # 其余时次只用于可选的「多时次快照范围」，与单时次口径分开报告。
    n_times = int(dataset.sizes.get("time", 1)) if "time" in dataset.dims else 1
    selected_index = int(config.get("time", {}).get("index", 0)) % max(n_times, 1)
    time_values = ([str(value) for value in dataset["time"].values]
                   if "time" in dataset.coords else ["unknown"])
    selected_time = time_values[selected_index]

    # 区域裁剪：先升序再 slice，避免 ERA5 纬度降序导致空切片
    dataset = dataset.sortby("latitude").sortby("longitude")
    region = config["region"]
    dataset = dataset.sel(
        latitude=slice(float(region["lat_min"]), float(region["lat_max"])),
        longitude=slice(float(region["lon_min"]), float(region["lon_max"])),
    )
    if dataset.sizes["latitude"] == 0 or dataset.sizes["longitude"] == 0:
        raise ValueError(f"区域裁剪后为空: {region}")
    dataset = dataset.load()
    meta = {
        "n_times": n_times,
        "selected_time_index": selected_index,
        "selected_time": selected_time,
        "times": time_values,
        "units": unit_notes,
        "liquid_variable": liquid_name,
        "ice_variable": ice_name,
        "region": dict(region),
    }
    return dataset, meta


# ---------------------------------------------------------------- 统计与产物

def _field_stats(field: np.ndarray, latitude: np.ndarray) -> dict[str, Any]:
    mean, valid = region_mean(field, latitude)
    values = np.asarray(field, dtype="float64")
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return {"mean_kg_m2": float("nan"), "mean_g_m2": float("nan"),
                "valid_cells": 0, "total_cells": int(values.size)}
    return {
        "mean_kg_m2": float(mean),
        "mean_g_m2": float(mean * 1000.0),
        "median_g_m2": float(np.median(finite) * 1000.0),
        "p10_g_m2": float(np.percentile(finite, 10) * 1000.0),
        "p90_g_m2": float(np.percentile(finite, 90) * 1000.0),
        "min_g_m2": float(np.min(finite) * 1000.0),
        "max_g_m2": float(np.max(finite) * 1000.0),
        "valid_cells": int(valid),
        "total_cells": int(values.size),
        "valid_fraction": float(valid / values.size),
    }


def _profile_stats(values: np.ndarray, latitude: np.ndarray) -> dict[str, list[float]]:
    """逐层区域平均与 10/90 分位（用于垂直剖面图）。"""
    means, p10, p90 = [], [], []
    for level in values:
        mean, _ = region_mean(level, latitude)
        finite = level[np.isfinite(level)]
        # kg·kg⁻¹ → mg·kg⁻¹（×1e6）
        means.append(float(mean * 1.0e6) if np.isfinite(mean) else float("nan"))
        p10.append(float(np.percentile(finite, 10) * 1.0e6) if finite.size else float("nan"))
        p90.append(float(np.percentile(finite, 90) * 1.0e6) if finite.size else float("nan"))
    return {"mean_mg_kg": means, "p10_mg_kg": p10, "p90_mg_kg": p90}


def build_fields_dataset(dataset: xr.Dataset, lwp: np.ndarray, iwp: np.ndarray,
                         coverage: dict[str, Any], liquid_name: str,
                         ice_name: str) -> xr.Dataset:
    """逐格点 LWP/IWP 场 + 垂直剖面，落盘为 run 目录的 fields.nc。"""
    latitude = np.asarray(dataset["latitude"].values, dtype="float64")
    longitude = np.asarray(dataset["longitude"].values, dtype="float64")
    levels_hpa = np.asarray(coverage["covered_layers_hpa"], dtype="float64")
    fields = xr.Dataset(
        {
            "lwp": (("latitude", "longitude"), np.asarray(lwp, dtype="float64")),
            "iwp": (("latitude", "longitude"), np.asarray(iwp, dtype="float64")),
            "clwc_profile": (("pressure_level",),
                             dataset[liquid_name].mean(dim=("latitude", "longitude")).values),
            "ciwc_profile": (("pressure_level",),
                             dataset[ice_name].mean(dim=("latitude", "longitude")).values),
        },
        coords={"latitude": latitude, "longitude": longitude,
                "pressure_level_hpa": ("pressure_level", levels_hpa)},
        attrs={
            "title": "ERA5 clwc/ciwc strict column water path",
            "lwp_units": "kg m-2",
            "iwp_units": "kg m-2",
            "partial_column": int(bool(coverage["partial_column"])),
            "coverage_hpa": float(coverage["coverage_hpa"]),
            "covered_layers_hpa": json.dumps(coverage["covered_layers_hpa"]),
            "g_m_s2": float(G_STANDARD),
            "integration": "trapezoid over pressure_level levels; no extrapolation",
        },
    )
    fields["lwp"].attrs.update({"long_name": "liquid water path", "units": "kg m-2"})
    fields["iwp"].attrs.update({"long_name": "ice water path", "units": "kg m-2"})
    fields["clwc_profile"].attrs.update({"long_name": "regional mean clwc", "units": "kg kg-1"})
    fields["ciwc_profile"].attrs.update({"long_name": "regional mean ciwc", "units": "kg kg-1"})
    return fields


def _find_variable(dataset: xr.Dataset, names: tuple[str, ...]) -> str:
    for name in names:
        if name in dataset.variables:
            return name
    raise ValueError(f"数据集中缺少变量 {names}")


def multi_time_snapshot(dataset: xr.Dataset, config: dict[str, Any],
                        coverage: dict[str, Any]) -> dict[str, Any] | None:
    """多时次快照范围：逐时次算区域平均 LWP/IWP，只报快照范围。

    与单时次口径**严格分开**：逐格点场、剖面、五态判定都只用 config.time.index
    指定的那一个时次；本函数不改变单时次结论，也不做时间平均场。
    """
    if "time" not in dataset.dims:
        return None
    n_times = int(dataset.sizes["time"])
    if n_times <= 1:
        return None
    g = float(config["constants"]["g_m_s2"])
    pressure_pa = np.asarray(dataset["pressure_level"].values, dtype="float64") * 100.0
    latitude = np.asarray(dataset["latitude"].values, dtype="float64")
    liquid_name = str(config["variables"]["liquid"])
    ice_name = str(config["variables"]["ice"])
    liquid_means: list[float] = []
    ice_means: list[float] = []
    for index in range(n_times):
        single = dataset.isel(time=index)
        liquid_means.append(float(region_mean(
            column_water_path(single[liquid_name].values, pressure_pa, g=g),
            latitude)[0] * 1000.0))
        ice_means.append(float(region_mean(
            column_water_path(single[ice_name].values, pressure_pa, g=g),
            latitude)[0] * 1000.0))

    def summarize(values: list[float]) -> dict[str, Any]:
        array = np.asarray(values, dtype="float64")
        return {
            "per_time_mean_g_m2": [float(value) for value in array],
            "mean_g_m2": float(np.nanmean(array)),
            "median_g_m2": float(np.nanmedian(array)),
            "min_g_m2": float(np.nanmin(array)),
            "max_g_m2": float(np.nanmax(array)),
            "n_times": int(array.size),
        }

    return {
        "n_times": n_times,
        "times": [str(value) for value in dataset["time"].values],
        "usage": ("逐时次快照统计；不是时间平均场，不替代 config.time.index "
                  "指定的单时次口径，也不构成气候态结论"),
        "column": {
            "partial_column": bool(coverage["partial_column"]),
            "coverage_hpa": float(coverage["coverage_hpa"]),
        },
        "lwp": summarize(liquid_means),
        "iwp": summarize(ice_means),
    }


def _atomic_netcdf(dataset: xr.Dataset, path: Path) -> Path:
    tmp = path.with_name(f".{path.name}.part")
    dataset.to_netcdf(tmp, engine="netcdf4")
    os.replace(tmp, path)
    return path


def run(config_path: str | Path, run_id: str, *, force: bool = False,
        input_file: str | None = None) -> dict[str, Any]:
    """完整计算一次并落盘 fields.nc / stats.json / inputs.json。

    ``input_file`` 仅用于 interim 本地真实文件的显式覆盖（等价于 config 的
    ``input_file`` 键），不会改变 catalog 模式的正式口径。
    """
    config = common.load_config(config_path)
    if input_file:
        config["input_file"] = str(input_file)
    inputs = common.catalog_inputs(config)
    manifest_path, _manifest = common.prepare_manifest(
        config, run_id, inputs["files"], force=force)
    target = common.run_dir(config, run_id)
    dataset, meta = load_cloud_water(config, inputs)
    g = float(config["constants"]["g_m_s2"])
    radius = float(config["constants"]["earth_radius_m"])
    single = (dataset.isel(time=meta["selected_time_index"])
              if "time" in dataset.dims else dataset)
    pressure_pa = np.asarray(single["pressure_level"].values, dtype="float64") * 100.0
    coverage = coverage_metadata(pressure_pa, config)
    multi_time = multi_time_snapshot(dataset, config, coverage)

    liquid = np.asarray(single[str(config["variables"]["liquid"])].values, dtype="float64")
    ice = np.asarray(single[str(config["variables"]["ice"])].values, dtype="float64")
    lwp = column_water_path(liquid, pressure_pa, g=g)
    iwp = column_water_path(ice, pressure_pa, g=g)

    latitude = np.asarray(single["latitude"].values, dtype="float64")
    longitude = np.asarray(single["longitude"].values, dtype="float64")
    area_m2 = cell_area_latlon(latitude, longitude, radius_earth=radius)
    area_total_m2 = float(np.sum(area_m2))
    lwp_stats = _field_stats(lwp, latitude)
    iwp_stats = _field_stats(iwp, latitude)
    profiles = {
        "pressure_hpa": [float(value) for value in coverage["covered_layers_hpa"]],
        "clwc": _profile_stats(liquid, latitude),
        "ciwc": _profile_stats(ice, latitude),
    }

    fields = build_fields_dataset(
        single, lwp, iwp, coverage,
        str(config["variables"]["liquid"]), str(config["variables"]["ice"]))
    fields_path = _atomic_netcdf(fields, target / "fields.nc")
    inputs_path = target / "inputs.json"
    common.atomic_write_json(inputs_path, {
        "volume_id": inputs["volume_id"],
        "dataset_id": inputs["dataset_id"],
        "volume_root": inputs["volume_root"],
        "volume_status": inputs["volume_status"],
        "catalog_imported": bool(inputs.get("catalog_imported", False)),
        "note": inputs.get("note", ""),
        "files": [file.as_record() for file in inputs["files"]],
        "input_fingerprint": common.input_fingerprint(
            [file.as_record() for file in inputs["files"]]),
    })
    stats = {
        "run_id": run_id,
        "experiment": "cloud_water_strict",
        "generated_at": common.utc_now(),
        "config_path": str(config["_config_path"]),
        "input": {
            "volume_id": inputs["volume_id"],
            "dataset_id": inputs["dataset_id"],
            "volume_root": inputs["volume_root"],
            "source_mode": "catalog" if inputs.get("catalog_imported", False)
            else "local_override",
            "catalog_imported": bool(inputs.get("catalog_imported", False)),
            "note": inputs.get("note", ""),
            "files": [{"rel_path": file.rel_path, "sha256": file.sha256,
                       "size_bytes": file.size_bytes} for file in inputs["files"]],
        },
        "grid": {
            "n_latitude": int(single.sizes["latitude"]),
            "n_longitude": int(single.sizes["longitude"]),
            "n_pressure_levels": int(single.sizes["pressure_level"]),
            "region": meta["region"],
            "area_m2": area_total_m2,
        },
        "units": meta["units"],
        "variables": {
            "liquid": str(config["variables"]["liquid"]),
            "ice": str(config["variables"]["ice"]),
        },
        "time": {
            "n_times": meta["n_times"],
            "selected_time_index": meta["selected_time_index"],
            "selected_time": meta["selected_time"],
        },
        "multi_time": multi_time,
        "column": coverage,
        "fields": {"lwp": lwp_stats, "iwp": iwp_stats},
        "profiles": profiles,
        "regional_total": {
            "lwp_kg": float(lwp_stats["mean_kg_m2"] * area_total_m2),
            "iwp_kg": float(iwp_stats["mean_kg_m2"] * area_total_m2),
        },
        "constants": {"g_m_s2": g, "earth_radius_m": radius},
        "method": (
            "LWP=∫(clwc/g)dp, IWP=∫(ciwc/g)dp; trapezoid on pressure levels; "
            "cosφ area weighting; no extrapolation beyond covered levels"),
    }
    stats_path = target / "stats.json"
    common.atomic_write_json(stats_path, stats)

    for path in (fields_path, inputs_path, stats_path):
        common.record_artifact(manifest_path, path)
    print(json.dumps({
        "run_id": run_id,
        "run_dir": str(target),
        "partial_column": coverage["partial_column"],
        "coverage_hpa": coverage["coverage_hpa"],
        "lwp_mean_g_m2": lwp_stats["mean_g_m2"],
        "iwp_mean_g_m2": iwp_stats["mean_g_m2"],
        "figures": "next: plot.py",
    }, ensure_ascii=False, indent=2))
    return stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="真实 ERA5 clwc/ciwc 柱水路径计算")
    parser.add_argument("--config", default=str(Path(__file__).with_name("config.yaml")))
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--input-file", default=None,
                        help="interim 本地真实文件覆盖；正式 run 留空走 catalog")
    args = parser.parse_args(argv)
    run(args.config, args.run_id, force=args.force, input_file=args.input_file)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
