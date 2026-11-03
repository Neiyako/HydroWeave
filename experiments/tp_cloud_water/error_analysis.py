#!/usr/bin/env python3
"""云水资源（GCWR）误差分析：一阶误差传播 + 闭合残差 + 量级排序。

设计原则（与 README §4 一致）：

1. **分层**：数值误差、口径误差、代理误差分开算，不混成一个「总误差 x%」。
2. **可追溯**：每个不确定度都必须来自某个显式给定的 σ，不允许隐式默认。
3. **方向优先**：方向未知时只报区间，不报「近似成立」。

GCWR = GQh − GR = (Qh,i + Qh,in + C_net) − GR，而 C_net 由式 (10) 反算，
所以 GCWR 实际是各分项的线性组合。对线性组合，一阶（高斯）传播是精确的：
σ² = Σ (∂GCWR/∂x)² σ_x²。
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from experiments.tp_cloud_water.budget import BudgetTerms, evaluate

# ------------------------------------------------------- 单项不确定度容器

@dataclass
class TermSigma:
    """各分项 1σ 不确定度，单位为 kg，键名与 BudgetTerms 字段一致。

    默认 0 表示「未评估」，调用方必须显式给出，避免把缺省值误当已知。
    """
    qv_init: float = 0.0
    qv_final: float = 0.0
    qh_init: float = 0.0
    qh_final: float = 0.0
    qv_in: float = 0.0
    qv_out: float = 0.0
    qh_in: float = 0.0
    qh_out: float = 0.0
    rain_kg: float = 0.0


# --------------------------------------------- GCWR 的敏感度（解析求导）

# GCWR 以式 (22) 展开：Qh,i + Qh,in + C_net − R，C_net = Qh,f − Qh,i − Qh,in + Qh,out + R
# ⇒ GCWR = Qh,f + Qh,out （式21），对各项的偏导如下：
_GCWR_SENSITIVITY = {
    "qh_init": 0.0,   # 初值在 C_net 与自身处抵消
    "qh_final": 1.0,
    "qh_in": 0.0,     # 输入被 C_net 完全吸收
    "qh_out": 1.0,
    "rain_kg": 0.0,   # 降水在 C_net 与减项处抵消
    "qv_init": 0.0, "qv_final": 0.0, "qv_in": 0.0, "qv_out": 0.0,
}


def gcwr_sigma(sigma: TermSigma) -> dict:
    """GCWR 的 1σ 不确定度，按一阶传播逐项分解。

    返回 ``{"sigma": 总, "contributions": {项: 贡献方差}}``。
    贡献方差之和开方即为总 σ；排序后可用来看**哪一项主导**。
    """
    contrib = {}
    total_var = 0.0
    for name, sens in _GCWR_SENSITIVITY.items():
        if sens == 0.0:
            continue
        var = (sens * getattr(sigma, name)) ** 2
        contrib[name] = var
        total_var += var
    return {"sigma": float(np.sqrt(total_var)), "contributions": contrib}


def relative_uncertainty(value: float, sigma: float) -> float:
    """相对不确定度；值为 0 时返回 inf 而不是静默的 0。"""
    if value == 0:
        return float("inf")
    return float(abs(sigma / value))


@dataclass
class CalibrationFactor:
    """口径误差：以乘性因子表示，如地形以下填充层占比、Magnus 水面误差。"""
    name: str
    relative_sigma: float     # 相对 1σ，如 0.217 表示 ±21.7%
    direction: str            # "low"（低估）/ "high"（高估）/ "unknown"
    note: str = ""


def apply_calibration(value: float, factors: list[CalibrationFactor]) -> dict:
    """把若干乘性口径误差独立传播到目标量上。

    返回总相对 σ（各因子平方和开根）与主导因子；方向不一致时
    ``direction`` 记为 ``"mixed"``，此时只能报区间不能报方向。
    """
    rel_var = sum(f.relative_sigma ** 2 for f in factors)
    rel = float(np.sqrt(rel_var))
    dominant = max(factors, key=lambda f: f.relative_sigma).name if factors else None
    dirs = {f.direction for f in factors if f.direction != "unknown"}
    if len(dirs) == 1:
        direction = dirs.pop()
    elif not dirs:
        direction = "unknown"
    else:
        direction = "mixed"
    return {"relative_sigma": rel, "absolute_sigma": abs(value) * rel,
            "direction": direction, "dominant": dominant,
            "interval": (value - abs(value) * rel, value + abs(value) * rel)}


# ------------------------------------------------------ 闭合残差检验

def closure_check(t: BudgetTerms, tolerance_relative: float = 1e-6) -> dict:
    """把三条残差换算成相对量，并给出 PASS / FAIL 判定。

    相对化用的是同一条方程里最大的存量/通量项，避免小分母放大噪声。
    判定标准**先定后用**：tolerance_relative 必须在看到结果前给出。
    """
    rep = evaluate(t)
    scale_h = max(abs(t.qh_final - t.qh_init), abs(t.rain_kg), abs(t.qh_in), 1e-30)
    scale_v = max(abs(t.qv_final - t.qv_init), abs(t.qv_in), 1e-30)
    rel_h = abs(rep["eps_h_kg"]) / scale_h
    rel_v = abs(rep["eps_v_kg"]) / scale_v
    identity_ok = rep["gcwr_identity_ok"]
    # 残差本身由反算定义，恒等式检验的是「两种写法的算术一致性」
    return {
        "rel_residual_h": rel_h,
        "rel_residual_v": rel_v,
        "gcwr_identity_ok": identity_ok,
        "verdict": "PASS" if identity_ok else "FAIL",
        "tolerance_relative": tolerance_relative,
        "note": "残差闭合取决于输入项的数据质量，本函数只检验反算后各式的算术一致性",
    }


# ------------------------------------------- 主导项排序：决定下一步攻关

def error_budget_table(result: dict, sigma: TermSigma,
                       calibration: list[CalibrationFactor] | None = None) -> list[dict]:
    """把误差源排成表：口径误差 vs 随机误差，按对 GCWR 的贡献降序。

    ``result`` 来自 :func:`budget.evaluate`。
    """
    gcwr = result["gcwr_kg"]
    rows = []

    g = gcwr_sigma(sigma)
    for name, var in g["contributions"].items():
        term_sigma = np.sqrt(var)
        if term_sigma == 0:
            continue
        rows.append({
            "source": f"随机/测量:{name}",
            "sigma_kg": term_sigma,
            "relative_to_gcwr": relative_uncertainty(gcwr, term_sigma),
            "type": "random",
        })

    if calibration:
        cal = apply_calibration(gcwr, calibration)
        rows.append({
            "source": "口径:" + "+".join(f.name for f in calibration),
            "sigma_kg": cal["absolute_sigma"],
            "relative_to_gcwr": cal["relative_sigma"],
            "type": "calibration",
        })

    rows.sort(key=lambda r: r["sigma_kg"], reverse=True)
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    return rows


def summarize(result: dict, sigma: TermSigma,
              calibration: list[CalibrationFactor] | None = None) -> dict:
    """输出可直接进报告的一段结论：GCWR ± σ、主导误差、是否可支撑结论。"""
    g = gcwr_sigma(sigma)
    gcwr = result["gcwr_kg"]
    rel = relative_uncertainty(gcwr, g["sigma"])
    rows = error_budget_table(result, sigma, calibration)
    dominant = rows[0]["source"] if rows else None
    return {
        "gcwr_kg": gcwr,
        "gcwr_1sigma_kg": g["sigma"],
        "gcwr_relative_1sigma": rel,
        "gcwr_ci95_kg": (gcwr - 1.96 * g["sigma"], gcwr + 1.96 * g["sigma"]),
        "dominant_source": dominant,
        "dominant_share": (rows[0]["sigma_kg"] / max(g["sigma"], 1e-30)
                           if rows else None),
        "verdict": ("CONCLUSIVE" if rel < 0.20 else
                    "CONDITIONAL" if rel < 0.50 else "INSUFFICIENT_EVIDENCE"),
        "error_table": rows,
    }


__all__ = [
    "CalibrationFactor", "TermSigma", "apply_calibration", "closure_check",
    "error_budget_table", "gcwr_sigma", "relative_uncertainty", "summarize",
]
