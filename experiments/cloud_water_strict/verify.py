"""cloud_water_strict 的验收模块：代数恒等式自检 + 量级核对 + 五态判定报告。

三个层次刻意分开，避免「有数字就报 PASS」：

1. **代数/实现层**：用 ``tp_cloud_water.budget`` 的 ``BudgetTerms`` 构造一组
   内部自洽量，检验式 (20)(21)(22) 三种 GCWR 写法的相对残差 ≤ 1e-12；再用
   常数场解析解检验柱积分的梯形权重。二者通过只证明「实现与公式一致」，
   **不构成物理检验**（论文原文也强调：任何一组合数都能让代数恒等式成立）。
2. **量级层**：把区域平均 LWP/IWP 与文献给出的青藏高原云水路径量级带比对。
   单时次 + 部分列样本只能得出 CONDITIONAL_PASS / INSUFFICIENT_EVIDENCE。
3. **未运行层**：GCWR 收支闭合（缺 P、E、u/v 边界通量与更长时段）与年度/
   气候态结论标 NOT_RUN；NOT_RUN 不是 PASS。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np

from experiments.cloud_water_strict import common, compute
from experiments.tp_cloud_water import budget as B

PASS = "PASS"
CONDITIONAL_PASS = "CONDITIONAL_PASS"
FAIL = "FAIL"
INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
NOT_RUN = "NOT_RUN"
_ALL_STATES = (PASS, CONDITIONAL_PASS, FAIL, INSUFFICIENT_EVIDENCE, NOT_RUN)

IDENTITY_THRESHOLD = 1e-12

# 图件由 plot.py 生成；verify.py 在 e2e 里可能先于 plot.py 运行，所以报告按
# 「预期文件名」列出图件，plot.py 之后再补 sha256（summary.json 由 plot.py 更新）。
FIGURE_NAMES = (
    "fig_lwp_field.png",
    "fig_iwp_field.png",
    "fig_vertical_profile.png",
    "fig_lwp_iwp_relation.png",
    "fig_identity_residual.png",
)

# 文献量级带：只用于「数量级是否荒谬」核对，不是逐格点气候态，也不是本仓结论。
MAGNITUDE_BANDS: dict[str, dict[str, Any]] = {
    # 文献给出的青藏高原云水路径量级是 10^1–10^2 g·m⁻²（整列）。本样本是
    # 300–500 hPa 部分列、数值天然小于整列，因此按 ±1 个数量级放宽成
    # 「数量级荒谬性带」：只回答「是否离谱一个量级以上」，不回答气候态是否匹配。
    "LWP": {
        "band_g_m2": (1.0, 2000.0),
        "reported": "高原西部月 44–92 g·m⁻²；九龙夏季非降水云整层均值 433（低云 665/高云 102）"
                    "；四川盆地 150–200 g·m⁻²",
        "sources": ["cuit2025", "byzh2024"],
    },
    "IWP": {
        "band_g_m2": (1.0, 1000.0),
        "reported": "高原西部月 63–155 g·m⁻²；恒河平原 206/57 g·m⁻²",
        "sources": ["cuit2025", "li2018"],
    },
}

REFERENCES: dict[str, dict[str, str]] = {
    "cuit2025": {
        "citation": "韦成强, 赵鹏国 (2025) 青藏高原及其临近区域云特性及云垂直结构分布特征，成都信息工程大学学报 40(5):643-651",
        "url": "http://xb.cuit.edu.cn/oa/pdfdow.aspx?Sid=202505011",
        "reported": "高原西部 LWP 月最大/最小 92/44 g·m⁻²、IWP 155/63 g·m⁻²；四川盆地 LWP 150–200 g·m⁻²",
        "read_status": "已下载 PDF 并抽取正文数值",
    },
    "byzh2024": {
        "citation": "徐桂荣等 (2024) 青藏高原东侧九龙夏季非降水云的观测特征，暴雨灾害 43(2):135-145",
        "url": "http://www.byzh.org.cn/cn/article/pdf/preview/10.12406/byzh.2023-148.pdf",
        "reported": "九龙夏季非降水云 LWP 整层均值 0.433 kg·m⁻²（低云 0.665、中云 0.240、高云 0.102）",
        "read_status": "已下载 PDF 并抽取摘要数值",
    },
    "li2018": {
        "citation": "Li Wentao et al. (2018) Climatic Characteristic Analysis of Cloud Water "
                    "over the Tibetan Plateau, Climatic and Environmental Research 23(5)",
        "url": "https://www.iapjournals.ac.cn/qhhj/en/article/doi/10.3878/j.issn.1006-9585.2018.18039",
        "reported": "MODIS+ERA-Interim 2001–2016 高原 LWP/IWP 气候态与季节变化（摘要未给逐月数值）",
        "read_status": "已读摘要（全文未读）",
    },
    "era5": {
        "citation": "Copernicus Climate Data Store: ERA5 total column cloud liquid water variable",
        "url": "https://eqc.climate.copernicus.eu/node/1325",
        "reported": "ERA5 柱云水量为 clwc/ciwc 整层积分，单位 kg·m⁻²；本实验积分口径与之同量纲",
        "read_status": "网页元数据（未读正文）",
    },
}

NOT_RUN_ITEMS = [
    {"item": "GCWR 收支闭合（论文式 30/31/32）",
     "missing": "降水 P、地面蒸发 E、边界通量 u/v 的同一控制体累计量，以及更长时段库存变化",
     "why": "本样本只有单时次 clwc/ciwc，无法构造收支方程任何一项"},
    {"item": "年度/气候态尺度结论",
     "missing": "多年逐日（或逐月）样本与季节循环",
     "why": "单时次快照不能外推年尺度云水资源量或趋势"},
    {"item": "与文献逐格点气候态定量比对",
     "missing": "同一区域/季节/层的文献格点场与完整气压柱",
     "why": "本样本仅覆盖 300–500 hPa（partial column），不可当整列气候态"},
]


# ------------------------------------------------------------ 代数/实现自检

def _consistent_terms() -> B.BudgetTerms:
    """内部自洽的合成收支量（数字只为数值稳定，无物理含义）。"""
    return B.BudgetTerms(
        qv_init=8.0e14, qv_final=8.2e14,
        qh_init=1.0e12, qh_final=1.2e12,
        qv_in=5.0e15, qv_out=5.02e15,
        qh_in=5.0e11, qh_out=6.0e11,
        rain_kg=1.0e12, duration_s=30.0 * B.SECONDS_PER_DAY,
    )


def identity_residual_evidence() -> dict[str, Any]:
    """式 (20)(21)(22) 三式恒等的相对残差证据 + 负控制（证明检验非空转）。"""
    terms = _consistent_terms()
    c_net = B.net_condensation(terms)
    a, b, c, spread = B.gcwr(terms, c_net=c_net)
    scale = float(max(abs(a), abs(b), abs(c)))
    relative = float(spread / scale) if scale > 0 else float("nan")

    wrong = B.gcwr(terms, c_net=c_net * 1.001)
    wrong_scale = float(max(abs(value) for value in wrong[:3]))
    wrong_relative = float(wrong[3] / wrong_scale) if wrong_scale > 0 else float("nan")

    report = B.evaluate(terms)
    residuals = B.residuals(terms)
    return {
        "terms": {
            "qv_init": terms.qv_init, "qv_final": terms.qv_final,
            "qh_init": terms.qh_init, "qh_final": terms.qh_final,
            "qv_in": terms.qv_in, "qv_out": terms.qv_out,
            "qh_in": terms.qh_in, "qh_out": terms.qh_out,
            "rain_kg": terms.rain_kg, "duration_s": terms.duration_s,
        },
        "net_condensation_kg": float(c_net),
        "gcwr_from_total_kg": float(a),
        "gcwr_from_terminal_kg": float(b),
        "gcwr_from_initial_kg": float(c),
        "spread_kg": float(spread),
        "scale_kg": scale,
        "relative_residual": relative,
        "threshold_relative": IDENTITY_THRESHOLD,
        "passed": bool(relative <= IDENTITY_THRESHOLD),
        "negative_control": {
            "description": "把净凝结故意偏置 0.1% 后，同一检验必须失败（说明检验有灵敏度）",
            "spread_kg": float(wrong[3]),
            "relative_residual": wrong_relative,
            "detected": bool(wrong_relative > IDENTITY_THRESHOLD),
        },
        "inventory_identity_ok": bool(report["inventory_identity_ok"]),
        "residuals_kg": {key: float(value) for key, value in residuals.items()},
        "note": "算术恒等式检验：只证明代数实现与论文式(20)(21)(22)一致，不构成物理检验",
    }


def analytic_column_check() -> dict[str, Any]:
    """常数混合比场的柱积分解析解：LWP = q/g·Δp，检验梯形权重与单位。"""
    g = B.G_STANDARD
    q_kgkg = 1.0e-4
    pressure_pa = np.array([300.0, 400.0, 500.0]) * 100.0
    q = np.full((3, 2, 3), q_kgkg)
    lwp = compute.column_water_path(q, pressure_pa, g=g)
    expected = q_kgkg / g * (pressure_pa[-1] - pressure_pa[0])
    error = np.abs(lwp - expected)
    relative = float(np.max(error / abs(expected)))
    coverage = compute.coverage_metadata(pressure_pa, {
        "pressure": {"full_column_hpa": [1.0, 1000.0],
                     "partial_tolerance_hpa": 1.0}})
    return {
        "q_kgkg": q_kgkg,
        "pressure_levels_hpa": (pressure_pa / 100.0).tolist(),
        "lwp_computed_kg_m2": float(lwp.flat[0]),
        "lwp_expected_kg_m2": float(expected),
        "relative_error": relative,
        "threshold_relative": IDENTITY_THRESHOLD,
        "passed": bool(relative <= IDENTITY_THRESHOLD),
        "coverage_hpa": coverage["coverage_hpa"],
        "partial_column": coverage["partial_column"],
        "note": "常数场梯形积分应严格等于 q/g·Δp（无外推）",
    }


# ---------------------------------------------------------------- 量级核对

def magnitude_check(stats: dict[str, Any]) -> dict[str, Any]:
    """区域平均 LWP/IWP 与文献量级带比对；只允许 CONDITIONAL_PASS / 不足证据。"""
    entries: dict[str, dict[str, Any]] = {}
    for name, band in MAGNITUDE_BANDS.items():
        key = "lwp" if name == "LWP" else "iwp"
        value = float(stats["fields"][key]["mean_g_m2"])
        low, high = band["band_g_m2"]
        finite = bool(np.isfinite(value))
        within = bool(finite and low <= value <= high)
        if not finite:
            state, reason = INSUFFICIENT_EVIDENCE, "区域平均为 NaN，无法核对"
        elif within:
            state = CONDITIONAL_PASS
            reason = (f"落在文献量级带 {low:g}–{high:g} g·m⁻² 内；但单时次 + "
                      "partial column 不能建立气候态结论")
        elif value < low:
            state = INSUFFICIENT_EVIDENCE
            reason = (f"低于文献量级带下界 {low:g} g·m⁻²；部分列/单时次样本可偏低，"
                      "不能据此判 PASS 或 FAIL")
        else:
            state = INSUFFICIENT_EVIDENCE
            reason = (f"高于文献量级带上界 {high:g} g·m⁻²；优先排查单位/权重/分层口径，"
                      "不把它当气候态结论")
        entries[name] = {
            "mean_g_m2": value,
            "band_g_m2": [low, high],
            "within_band": within,
            "state": state,
            "reason": reason,
            "reported": band["reported"],
            "sources": band["sources"],
        }
    states = [entry["state"] for entry in entries.values()]
    combined = CONDITIONAL_PASS if all(state == CONDITIONAL_PASS for state in states) \
        else INSUFFICIENT_EVIDENCE
    return {
        "entries": entries,
        "combined_state": combined,
        "caveat": "文献值为整列（LWP/IWP 全柱）月尺度量级；本样本仅 300–500 hPa 部分列",
        "references": {key: REFERENCES[key] for key in
                       {source for entry in entries.values() for source in entry["sources"]}},
    }


# ---------------------------------------------------------------- 数据口径

def data_quality_check(stats: dict[str, Any]) -> dict[str, Any]:
    """变量/单位/坐标/partial_column 标记的实现口径检查（可判 PASS/FAIL）。"""
    units = stats["units"]
    factors = [float(units.get("clwc_conversion_factor", np.nan)),
               float(units.get("ciwc_conversion_factor", np.nan))]
    variables_ok = stats["input"]["source_mode"] in {"catalog", "local_override"}
    unit_ok = all(factor in (1.0, 1.0e-3) for factor in factors)
    pressure_ok = units.get("pressure_interpreted_as") in {"Pa", "hPa"}
    column = stats["column"]
    span = column["full_column_hpa"][1] - column["full_column_hpa"][0]
    tolerance = 1.0e-6
    expected_partial = bool(
        column["coverage_hpa"] < span - tolerance
        or column["covered_top_hpa"] > column["full_column_hpa"][0] + tolerance
        or column["covered_bottom_hpa"] < column["full_column_hpa"][1] - tolerance)
    partial_consistent = bool(column["partial_column"]) == expected_partial
    passed = bool(variables_ok and unit_ok and pressure_ok and partial_consistent)
    return {
        "liquid_variable": stats.get("variables", {}).get("liquid", "clwc"),
        "ice_variable": stats.get("variables", {}).get("ice", "ciwc"),
        "clwc_raw_unit": units.get("clwc_raw_unit"),
        "ciwc_raw_unit": units.get("ciwc_raw_unit"),
        "clwc_conversion_factor": units.get("clwc_conversion_factor"),
        "ciwc_conversion_factor": units.get("ciwc_conversion_factor"),
        "pressure_raw_unit": units.get("pressure_raw_unit"),
        "pressure_interpreted_as": units.get("pressure_interpreted_as"),
        "pressure_conversion_factor": units.get("pressure_conversion_factor", 1.0),
        "partial_column": column["partial_column"],
        "expected_partial_column": expected_partial,
        "partial_consistency": partial_consistent,
        "passed": passed,
    }


# ---------------------------------------------------------------- 五态判定

def verdict_rows(identity: dict[str, Any], analytic: dict[str, Any],
                 quality: dict[str, Any], magnitude: dict[str, Any],
                 stats: dict[str, Any]) -> list[dict[str, str]]:
    column = stats["column"]
    return [
        {
            "check": "式(20)(21)(22) GCWR 三式恒等（相对残差 ≤ 1e-12）",
            "state": PASS if identity["passed"] else FAIL,
            "evidence": (f"三式值={identity['gcwr_from_total_kg']:.6e}/"
                         f"{identity['gcwr_from_terminal_kg']:.6e}/"
                         f"{identity['gcwr_from_initial_kg']:.6e} kg；"
                         f"spread={identity['spread_kg']:.3e} kg；"
                         f"相对残差={identity['relative_residual']:.3e}；"
                         f"负控制={identity['negative_control']['relative_residual']:.3e}"
                         f"（{'已检出' if identity['negative_control']['detected'] else '未检出'}）"),
        },
        {
            "check": "柱积分梯形权重（常数场解析解）",
            "state": PASS if analytic["passed"] else FAIL,
            "evidence": (f"LWP={analytic['lwp_computed_kg_m2']:.12f} vs 解析 "
                         f"{analytic['lwp_expected_kg_m2']:.12f} kg·m⁻²；"
                         f"相对误差={analytic['relative_error']:.3e}"),
        },
        {
            "check": "clwc/ciwc 变量·单位·坐标口径",
            "state": PASS if quality["passed"] else FAIL,
            "evidence": (f"clwc={quality['clwc_raw_unit']}→kg/kg×{quality['clwc_conversion_factor']}；"
                         f"ciwc={quality['ciwc_raw_unit']}→kg/kg×{quality['ciwc_conversion_factor']}；"
                         f"气压层 {quality['pressure_raw_unit']}×{quality.get('pressure_conversion_factor', 1.0)}→Pa"),
        },
        {
            "check": "partial_column 标记与覆盖厚度",
            "state": PASS if quality["partial_consistency"] else FAIL,
            "evidence": (f"partial_column={str(column['partial_column']).lower()}；覆盖 "
                         f"{column['covered_top_hpa']:.0f}–{column['covered_bottom_hpa']:.0f} hPa，"
                         f"厚度 {column['coverage_hpa']:.0f} hPa（名义整列 {column['full_column_hpa'][0]:.0f}–"
                         f"{column['full_column_hpa'][1]:.0f} hPa 的 {column['coverage_fraction']:.1%}），"
                         f"未做外推"),
        },
        {
            "check": "区域平均 LWP/IWP 量级 vs 文献/ERA5 气候态",
            "state": magnitude["combined_state"],
            "evidence": "；".join(
                f"{name} 均值 {entry['mean_g_m2']:.3g} g·m⁻² vs 带 "
                f"[{entry['band_g_m2'][0]:g},{entry['band_g_m2'][1]:g}] → {entry['state']}"
                for name, entry in magnitude["entries"].items()),
        },
        {
            "check": "GCWR 收支闭合（式 30/31/32）",
            "state": NOT_RUN,
            "evidence": "缺 P、E、u/v 边界通量与更长时段库存变化，无法构造收支方程",
        },
        {
            "check": "年度/气候态尺度结论",
            "state": NOT_RUN,
            "evidence": "单时次快照，不能外推动年尺度云水资源量或趋势",
        },
    ]


def overall_state(rows: list[dict[str, str]]) -> str:
    """总体判定取「已评估项」的最弱状态；NOT_RUN 单列，不冒充 PASS。"""
    evaluated = [row["state"] for row in rows if row["state"] != NOT_RUN]
    for state in (FAIL, INSUFFICIENT_EVIDENCE, CONDITIONAL_PASS, PASS):
        if state in evaluated:
            return state
    return NOT_RUN


# ------------------------------------------------------------------ 报告

def _load_optional_json(path: Path) -> dict[str, Any] | None:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def _figure_records(target: Path) -> list[dict[str, Any]]:
    figures_path = target / "figures.json"
    if figures_path.exists():
        data = json.loads(figures_path.read_text(encoding="utf-8"))
        return list(data.get("figures", []))
    return []


def _figure_lines(target: Path, figures: list[dict[str, Any]]) -> str:
    by_name = {item.get("name"): item for item in figures}
    lines = []
    for name in FIGURE_NAMES:
        path = target / name
        item = by_name.get(name)
        if item and item.get("sha256"):
            lines.append(f"- `{path}` — sha256 `{item['sha256']}`")
        else:
            lines.append(f"- `{path}`（由 plot.py 生成；本报告若先于 plot.py 运行则暂无 sha256）")
    return "\n".join(lines)


def _sha_line(files: list[dict[str, Any]]) -> str:
    return "<br>".join(f"`{item['sha256']}` `{item['rel_path']}`" for item in files)


def render_report(*, run_id: str, stats: dict[str, Any], identity: dict[str, Any],
                  analytic: dict[str, Any], quality: dict[str, Any],
                  magnitude: dict[str, Any], rows: list[dict[str, str]],
                  overall: str, figures: list[dict[str, Any]], target: Path) -> str:
    column = stats["column"]
    lwp = stats["fields"]["lwp"]
    iwp = stats["fields"]["iwp"]
    source = stats["input"]
    lineage = (
        "**interim 本地真实文件覆盖（catalog_imported=false）**：尚未经 RDH 交付链"
        "导入 DBAS catalog；最终版待 lead 提供 `volume_id=downloads`、"
        "`dataset_id=era5_cloud_water` 的 catalog 路径后重跑。"
        if not source.get("catalog_imported") else
        "DBAS catalog 路径（`volume_id`/`dataset_id` 已登记，文件来自 catalog 索引）。")
    figure_lines = _figure_lines(target, figures)
    rows_table = "\n".join(
        f"| {row['check']} | **{row['state']}** | {row['evidence']} |" for row in rows)
    not_run_table = "\n".join(
        f"| {item['item']} | {item['missing']} | {item['why']} |" for item in NOT_RUN_ITEMS)
    refs = "\n".join(
        f"- [{item['citation']}]({item['url']}) — {item['reported']}（{item['read_status']}）"
        for item in REFERENCES.values())
    input_rows = "\n".join(
        f"| `{item['rel_path']}` | {item['size_bytes']} B | `{item['sha256']}` |"
        for item in source["files"])
    multi_time = stats.get("multi_time")
    if multi_time:
        lwp_multi = multi_time["lwp"]
        iwp_multi = multi_time["iwp"]
        multi_time_section = f"""### 4.1 多时次快照（可选补充，与单时次口径严格分开）

文件共 {multi_time['n_times']} 个时次。本节**逐时次分别积分**后只报区域平均的
快照范围；逐格点场、剖面与五态判定仍只使用 {stats['time']['selected_time']}
（索引 {stats['time']['selected_time_index']}）这一个时次，**不是**时间平均场，
也不构成气候态结论。

| 指标 | 区域平均范围（g·m⁻²） | 快照均值 | 中位数 |
|---|---:|---:|---:|
| LWP | {lwp_multi['min_g_m2']:.3f} – {lwp_multi['max_g_m2']:.3f} | {lwp_multi['mean_g_m2']:.3f} | {lwp_multi['median_g_m2']:.3f} |
| IWP | {iwp_multi['min_g_m2']:.3f} – {iwp_multi['max_g_m2']:.3f} | {iwp_multi['mean_g_m2']:.3f} | {iwp_multi['median_g_m2']:.3f} |

口径说明：{multi_time['usage']}；覆盖 {multi_time['column']['coverage_hpa']:.0f} hPa
（partial_column={str(multi_time['column']['partial_column']).lower()}）。
"""
    else:
        multi_time_section = ""
    unit_notes = stats["units"]
    return f"""# ERA5 clwc/ciwc 云水柱含量验证报告（{run_id}）

- 实验：`cloud_water_strict`；run-id：`{run_id}`；生成时间：{stats['generated_at']}
- 总体判定：**{overall}**
- 输入：{lineage}

## 1. 结论先行

- **代数实现层 PASS**：式 (20)(21)(22) 三式相对残差 {identity['relative_residual']:.3e}
  ≤ 1e-12；常数场柱积分相对误差 {analytic['relative_error']:.3e}。这两项只证明
  「实现与论文公式一致」，不是物理检验。
- **口径层 PASS**：clwc/ciwc 单位换算与气压层单位显式记录；本样本仅覆盖
  {column['covered_top_hpa']:.0f}–{column['covered_bottom_hpa']:.0f} hPa，
  已显式标注 `partial_column={str(column['partial_column']).lower()}`，未外推整列。
- **量级层 {magnitude['combined_state']}**：区域平均 LWP={lwp['mean_g_m2']:.3g} g·m⁻²、
  IWP={iwp['mean_g_m2']:.3g} g·m⁻²；仅与文献量级带做宽区间核对。单时次 +
  部分列，**不能**据此得出气候态或云水资源量结论。
- **NOT_RUN**：GCWR 收支闭合（式 30/31/32）与年度尺度结论均未运行（缺 P/E/
  边界通量/长时段），NOT_RUN ≠ PASS。

## 2. 输入与可追溯性

| 文件 | 大小 | sha256 |
|---|---:|---|
{input_rows}

- 数据来源：`volume_id={source['volume_id']}`、`dataset_id={source['dataset_id']}`
  （`source_mode={source.get('source_mode', 'catalog')}`、`catalog_imported={source['catalog_imported']}`）
- 时次：{stats['time']['selected_time']}（文件共 {stats['time']['n_times']} 个时次；
  **仅使用索引 {stats['time']['selected_time_index']} 的这一个时次**做逐格点场与区域统计，
  其余时次未参与本节任何数值）
- 区域：{stats['grid']['region']}；网格 {stats['grid']['n_latitude']}×{stats['grid']['n_longitude']}，
  气压层 {stats['grid']['n_pressure_levels']} 层

## 3. 方法与离散化

- 连续定义：LWP = ∫(clwc/g)dp，IWP = ∫(ciwc/g)dp，单位 kg·m⁻²。
- 离散化：相邻气压层用梯形权重 0.5·(q_{{k}}+q_{{k+1}})·Δp/g；g = {stats['constants']['g_m_s2']} m·s⁻²。
- **不做顶层/底层外推**：只积分数据实际覆盖的 {column['coverage_hpa']:.0f} hPa；
  覆盖为名义整列（{column['full_column_hpa'][0]:.0f}–{column['full_column_hpa'][1]:.0f} hPa）
  的 {column['coverage_fraction']:.1%} 时标记 `partial_column=true`。
- 区域平均：cosφ 面积权重，w(φ)=cosφ / Σcosφ。
- 缺测：NaN 不会被当作 0；任一端点缺测的区间使该格点柱含量为 NaN。

## 4. 结果

> 口径：单时次 {stats['time']['selected_time']} 的快照统计（共 {stats['time']['n_times']} 个时次，
> 未做多时次平均），且为部分列——不是月/季气候态。

| 指标 | LWP | IWP |
|---|---:|---:|
| 区域平均 | {lwp['mean_g_m2']:.3f} g·m⁻² | {iwp['mean_g_m2']:.3f} g·m⁻² |
| 中位数 | {lwp['median_g_m2']:.3f} | {iwp['median_g_m2']:.3f} |
| P10 / P90 | {lwp['p10_g_m2']:.3f} / {lwp['p90_g_m2']:.3f} | {iwp['p10_g_m2']:.3f} / {iwp['p90_g_m2']:.3f} |
| 最小 / 最大 | {lwp['min_g_m2']:.3f} / {lwp['max_g_m2']:.3f} | {iwp['min_g_m2']:.3f} / {iwp['max_g_m2']:.3f} |
| 有效格点 | {lwp['valid_cells']}/{lwp['total_cells']} | {iwp['valid_cells']}/{iwp['total_cells']} |

（单位 g·m⁻² = 10⁻³ kg·m⁻²；逐格点场见 `fields.nc`。）

{multi_time_section}
## 5. 五态判定表

| 检查项 | 判定 | 证据 |
|---|---|---|
{rows_table}

总体判定取「已评估项」的最弱状态；`NOT_RUN` 单列并保留在表中，不冒充 PASS。

## 6. 证据：恒等式与数值口径

- GCWR 三式：{identity['gcwr_from_total_kg']:.12e} / {identity['gcwr_from_terminal_kg']:.12e} /
  {identity['gcwr_from_initial_kg']:.12e} kg；spread = {identity['spread_kg']:.6e} kg；
  scale = {identity['scale_kg']:.6e} kg；相对残差 = {identity['relative_residual']:.6e}
  ≤ {identity['threshold_relative']:.1e}。
- 负控制（净凝结故意偏置 0.1%）：相对残差 {identity['negative_control']['relative_residual']:.3e}
  > {identity['threshold_relative']:.1e}，说明检验有灵敏度。
- 常数场柱积分：{analytic['lwp_computed_kg_m2']:.12f} vs 解析 {analytic['lwp_expected_kg_m2']:.12f}
  kg·m⁻²，相对误差 {analytic['relative_error']:.3e}。
- 单位换算：clwc `{unit_notes.get('clwc_raw_unit')}` × {unit_notes.get('clwc_conversion_factor')}；
  ciwc `{unit_notes.get('ciwc_raw_unit')}` × {unit_notes.get('ciwc_conversion_factor')}；
  气压层 `{unit_notes.get('pressure_raw_unit')}` × {unit_notes.get('pressure_conversion_factor', 1.0)} → Pa。

## 7. 图件

{figure_lines}

## 8. NOT_RUN（明确不运行，不是通过）

| 项目 | 缺什么 | 为什么不能算 |
|---|---|---|
{not_run_table}

## 9. 文献来源

{refs}

## 10. 局限

- 单时次快照：无日变化、无季节循环，不能代表气候态。
- 部分列（{column['covered_top_hpa']:.0f}–{column['covered_bottom_hpa']:.0f} hPa）：
  积分只覆盖该层，且未做地面以下/顶层外推；与整列气候态数值不可直接等价。
- 量级核对是宽区间日志度检查，不替代逐格点/逐月气候态比对。
- 真实物理闭合（GCWR 收支）需要 P、E、u/v 边界通量与同一控制体的长时段数据。

## 11. 复现命令

```bash
# 0) 依赖（仓库根目录）
uv venv --python 3.13 .venv
.venv/bin/python -m pip install pytest ruff numpy pandas xarray netCDF4 matplotlib pyyaml pyshp dask flox

# 1) 合成 fixture（离线，数字无物理意义）
.venv/bin/python scripts/demo/make_clwc_fixture.py /tmp/cw_fixture
PYTHONPATH=src:. .venv/bin/python -m experiments.cloud_water_strict.compute \\
  --config /tmp/cw_fixture/config.yaml --run-id fixture
PYTHONPATH=src:. .venv/bin/python -m experiments.cloud_water_strict.plot \\
  --config /tmp/cw_fixture/config.yaml --run-id fixture
PYTHONPATH=src:. .venv/bin/python -m experiments.cloud_water_strict.verify \\
  --config /tmp/cw_fixture/config.yaml --run-id fixture

# 2) interim 真实文件（本报告的口径）
PYTHONPATH=src:. .venv/bin/python -m experiments.cloud_water_strict.compute \\
  --config experiments/cloud_water_strict/config.yaml \\
  --input-file /Users/apple/Desktop/era5数据dbas/data/downloads/reanalysis-era5-pressure-levels/202401_multi.nc \\
  --run-id real-interim-20240101
PYTHONPATH=src:. .venv/bin/python -m experiments.cloud_water_strict.plot \\
  --config experiments/cloud_water_strict/config.yaml --run-id real-interim-20240101
PYTHONPATH=src:. .venv/bin/python -m experiments.cloud_water_strict.verify \\
  --config experiments/cloud_water_strict/config.yaml --run-id real-interim-20240101

# 3) 正式 catalog 路径（RDH 交付后）
PYTHONPATH=src:. .venv/bin/python -m experiments.cloud_water_strict.compute \\
  --config experiments/cloud_water_strict/config.yaml --run-id real-catalog-20240101
```
"""


def run(config_path: str | Path, run_id: str) -> dict[str, Any]:
    """读取 compute/plot 产物，写 report.md + summary.json + 最终清单。"""
    config = common.load_config(config_path)
    target = common.run_dir(config, run_id, create=False)
    if not target.exists():
        raise FileNotFoundError(f"run 目录不存在: {target}；先运行 compute.py")
    stats_path = target / "stats.json"
    if not stats_path.exists():
        raise FileNotFoundError(f"缺少 {stats_path}；先运行 compute.py")
    stats = json.loads(stats_path.read_text(encoding="utf-8"))

    identity = identity_residual_evidence()
    analytic = analytic_column_check()
    quality = data_quality_check(stats)
    magnitude = magnitude_check(stats)
    rows = verdict_rows(identity, analytic, quality, magnitude, stats)
    overall = overall_state(rows)
    figures = _figure_records(target)
    report = render_report(run_id=run_id, stats=stats, identity=identity,
                           analytic=analytic, quality=quality, magnitude=magnitude,
                           rows=rows, overall=overall, figures=figures, target=target)

    identity_path = target / "identity_check.json"
    report_path = target / "report.md"
    summary_path = target / "summary.json"
    common.atomic_write_json(identity_path, identity)
    common.atomic_write_text(report_path, report)
    summary = {
        "schema_version": 1,
        "experiment": "cloud_water_strict",
        "run_id": run_id,
        "generated_at": common.utc_now(),
        "overall_state": overall,
        "verdicts": rows,
        "not_run": NOT_RUN_ITEMS,
        "identity": identity,
        "analytic": analytic,
        "data_quality": quality,
        "magnitude": magnitude,
        "references": list(REFERENCES.values()),
        "input": stats["input"],
        "time": stats["time"],
        "grid": stats["grid"],
        "column": stats["column"],
        "units": stats["units"],
        "fields": stats["fields"],
        "multi_time": stats.get("multi_time"),
        "figures": figures,
        "expected_figures": list(FIGURE_NAMES),
        "report": report_path.name,
    }
    common.atomic_write_json(summary_path, summary)

    manifest_path = target / "manifest.json"
    if manifest_path.exists():
        manifest = common.load_json(manifest_path)
        for path in (identity_path, report_path, summary_path):
            manifest = common.record_artifact(manifest_path, path, manifest)
        for item in figures:
            path = Path(item["path"])
            if not path.is_absolute():
                path = common.ROOT / path
            if path.exists():
                manifest = common.record_artifact(manifest_path, path, manifest)
        counts = {state: sum(1 for row in rows if row["state"] == state)
                  for state in _ALL_STATES}
        common.finalize_manifest(manifest_path, "completed",
                                 overall_state=overall, verdict_counts=counts,
                                 partial_column=stats["column"]["partial_column"])
    print(json.dumps({"run_id": run_id, "overall_state": overall,
                      "verdicts": {row["check"]: row["state"] for row in rows},
                      "report": str(report_path), "summary": str(summary_path)},
                     ensure_ascii=False, indent=2))
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="cloud_water_strict 五态验收与报告")
    parser.add_argument("--config", default=str(Path(__file__).with_name("config.yaml")))
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args(argv)
    run(args.config, args.run_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
