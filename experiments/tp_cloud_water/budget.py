#!/usr/bin/env python3
"""云水资源收支模型：蔡淼（学位论文）第 2 章公式的可计算实现。

本模块只做**给定各分项后的代数**：不诊断云场、不构造水凝物三维场。
输入项必须已按同一控制体（区域 × 时段）算出并统一为 kg / kg·m⁻²。

公式编号与本仓 README §2 一致，均对应论文原文：

- 收支方程 (1)(2)(3)   水汽 / 水凝物 / 总水物质
- 反算 (10)(11)(12)    净凝结、地面蒸发（两条路径）
- 总量 (13)(14)(15)    各水物质总量
- 效率 (17)(18)        降水效率 / 凝结效率
- 更新周期 (19)        水汽、水凝物
- GCWR (20)(21)(22)    空中留存云水量，两种核算表达
- 残差 (30)(31)(32)    收支闭合检验

约定（与论文一致）：输入、输出均为**非负累计质量**；带符号通量在分解处
按 ``max(∆M,0)`` 记为输出、``max(-∆M,0)`` 记为输入（论文 §2.2 边界平流）。

**输入的物理自洽性是使用者的责任，本模块无法替你检验。** 代数上任何一组合数
都能算出结果、且式 (20)(21)(22) 恒等成立（那是算术恒等式，不构成物理检验）。
真正的检验是量级合理性：以蔡淼 2011 年全国评估为参照，水汽更新周期约 11 天、
水凝物更新周期约 15 小时、`Eh≈77%`。若试算得出 `Tv≈555 天`、`Th≈5 万小时`，
说明分项不在同一控制体或时间尺度上（典型错误：用年降水配瞬时库存、
或把柱含量当区域累计量），此时所有效率与 GCWR 都无意义。
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

G_STANDARD = 9.80665  # m·s⁻²
SECONDS_PER_DAY = 86400.0
SECONDS_PER_HOUR = 3600.0
_SECONDS_PER_UNIT = {"second": 1.0, "hour": SECONDS_PER_HOUR, "day": SECONDS_PER_DAY}


# ---------------------------------------------------------------- 基础换算

def regional_mass(column_mass, cell_area_m2, mask):
    """由柱质量 [kg·m⁻²] 与格点面积 [m²] 求区域总量 [kg]。公式 (6)。"""
    column_mass = np.asarray(column_mass, dtype="float64")
    cell_area_m2 = np.asarray(cell_area_m2, dtype="float64")
    mask = np.asarray(mask, dtype=bool)
    if column_mass.shape != cell_area_m2.shape:
        raise ValueError("column_mass 与 cell_area 形状必须一致")
    valid = mask & np.isfinite(column_mass)
    return float(np.sum(column_mass[valid] * cell_area_m2[valid]))


def cell_area_latlon(lat, lon, radius_earth=6371000.0):
    """规则经纬网格格点面积 [m²]，按球面近似 dA = R²·cosφ·dφ·dλ。"""
    lat = np.deg2rad(np.asarray(lat, dtype="float64"))
    lon = np.asarray(lon, dtype="float64")
    dlat = abs(lat[1] - lat[0]) if lat.size > 1 else np.deg2rad(0.25)
    dlon = abs(np.deg2rad(lon[1] - lon[0])) if lon.size > 1 else np.deg2rad(0.25)
    return (radius_earth ** 2) * np.cos(lat)[:, None] * dlat * dlon * np.ones((1, lon.size))


def rain_mass_from_mm(rain_mm, cell_area_m2, mask):
    """降水累计质量 [kg]；1 mm = 1 kg·m⁻²。公式 (26)。"""
    return regional_mass(rain_mm, cell_area_m2, mask)


def rain_mass_from_rate(rate_kg_m2_s, cell_area_m2, mask, dt_seconds):
    """降水率 [kg·m⁻²·s⁻¹] 逐时步累加。公式 (27)。"""
    return regional_mass(np.asarray(rate_kg_m2_s) * dt_seconds, cell_area_m2, mask)


# ------------------------------------------------------ 边界平流（论文 §2.2）

def boundary_flux_mass(signed_mass):
    """把带符号边界通量分解为 (输入, 输出)，两者均非负。公式 (23)(24)(25)。

    ``signed_mass`` 中正值表示离开控制体（输出），负值表示进入（输入）。
    """
    x = np.asarray(signed_mass, dtype="float64")
    out_kg = float(np.nansum(np.maximum(x, 0.0)))
    in_kg = float(np.nansum(np.maximum(-x, 0.0)))
    return in_kg, out_kg


def boundary_signed_mass(rho, qmix, normal_wind, face_area_m2, dt_seconds):
    """单个边界面单层单时步的带符号质量 [kg]。公式 (23)。

    ``normal_wind`` 以指向控制体外部为正。密度、含量、层面法向风与面积
    必须同形（按边界 × 层 × 时步铺开）。
    """
    return (np.asarray(rho, dtype="float64") * np.asarray(qmix, dtype="float64")
            * np.asarray(normal_wind, dtype="float64")
            * np.asarray(face_area_m2, dtype="float64") * float(dt_seconds))


# ------------------------------------------------------------- 收支分项容器

@dataclass
class BudgetTerms:
    """一个控制体一个时段的全部分项，单位统一为 kg。

    缺失项用 ``None`` 表示，相关派生量返回 NaN 而不是假装为 0——
    这与 README §2「不做数值替代」的口径一致。
    """
    qv_init: float
    qv_final: float
    qh_init: float
    qh_final: float
    qv_in: float
    qv_out: float
    qh_in: float
    qh_out: float
    rain_kg: float
    duration_s: float

    def __post_init__(self):
        if self.duration_s <= 0:
            raise ValueError("duration_s 必须为正")
        for name in ("qv_init", "qv_final", "qh_init", "qh_final",
                     "qv_in", "qv_out", "qh_in", "qh_out", "rain_kg"):
            value = getattr(self, name)
            if not np.isfinite(value):
                raise ValueError(f"{name} 必须为有限值，缺测请改入口径而不是置零")

    # 总水物质由水汽与水凝物相加得到（公式 (16)）
    @property
    def qm_init(self):
        return self.qv_init + self.qh_init

    @property
    def qm_final(self):
        return self.qv_final + self.qh_final

    @property
    def qm_in(self):
        return self.qv_in + self.qh_in

    @property
    def qm_out(self):
        return self.qv_out + self.qh_out


# --------------------------------------------------------- 反算与总量（式4-6）

def net_condensation(t: BudgetTerms):
    """净凝结，公式 (10)：由水凝物收支方程移项。

    C_net = Qh,f − Qh,i − Qh,in + Qh,out + R
    """
    return t.qh_final - t.qh_init - t.qh_in + t.qh_out + t.rain_kg


def evaporation_from_vapor(t: BudgetTerms, c_net=None):
    """地面蒸发，公式 (11)：由水汽收支方程反算。"""
    if c_net is None:
        c_net = net_condensation(t)
    return t.qv_final - t.qv_init - t.qv_in + t.qv_out + c_net


def evaporation_from_total(t: BudgetTerms):
    """地面蒸发，公式 (12)：由总水物质收支方程反算，用于交叉校核。"""
    return t.qm_final - t.qm_init - t.qm_in + t.qm_out + t.rain_kg


def totals(t: BudgetTerms, c_net=None, evap=None):
    """水汽 / 水凝物 / 总水物质总量，公式 (13)(14)(15)。

    返回 dict；每项都是「初值 + 输入 + 源项」=「终值 + 输出 + 汇项」的合计。

    **口径警告**：论文式 (16) ``GQm = GQv + GQh`` 说的是**瞬时库存**关系
    （``qm_init == qv_init + qh_init`` 恒成立）。本节返回的是**累计算量**，
    累计算量下 ``GQm ≠ GQv + GQh``——因为净凝结在水汽方程里是汇、在水凝物
    方程里是源，二者相加时抵消，但在总水物质方程里根本不出现。把累计的
    ``GQv + GQh`` 当作 ``GQm`` 会重复计入一次净凝结（本仓试算中该误差达
    ``GQv`` 的 60% 量级）。这是实现时最容易写错的一处，验收脚本对此单独设标准。
    """
    if c_net is None:
        c_net = net_condensation(t)
    if evap is None:
        evap = evaporation_from_total(t)
    g_qv = t.qv_init + t.qv_in + evap
    g_qh = t.qh_init + t.qh_in + c_net
    g_qm = t.qm_init + t.qm_in + evap
    return {"GQv": g_qv, "GQh": g_qh, "GQm": g_qm,
            "check_qv": t.qv_final + t.qv_out + c_net,
            "check_qh": t.qh_final + t.qh_out + t.rain_kg,
            "check_qm": t.qm_final + t.qm_out + t.rain_kg}


# ----------------------------------------------------- GCWR 与效率（式20-22）

def gcwr(t: BudgetTerms, c_net=None):
    """空中留存云水量 GCWR 的两种等价核算。公式 (20)(21)(22)。

    返回 ``(gcwr_from_total, gcwr_from_terminal, gcwr_from_initial, spread)``：

    - ``from_total``    = GQh − GR                （论文原始定义，式20）
    - ``from_terminal`` = Qh,f + Qh,out           （式21）
    - ``from_initial``  = Qh,i + Qh,in + C_net − R（式22）

    ``spread`` 是三者极差，正常应为机器精度量级；显著不为零说明各分项
    口径不一致（典型原因：净凝结由别的方程反算时用了不同时段）。
    """
    if c_net is None:
        c_net = net_condensation(t)
    g_qh = totals(t, c_net=c_net)["GQh"]
    a = g_qh - t.rain_kg
    b = t.qh_final + t.qh_out
    c = t.qh_init + t.qh_in + c_net - t.rain_kg
    return a, b, c, float(max(a, b, c) - min(a, b, c))


def efficiency(t: BudgetTerms, total_condensation=None, c_net=None):
    """效率三项。公式 (17)(18)。

    ``Em = GR/GQm``、``Eh = GR/GQh``、``P = 总凝结量/GQv``。
    分母非正或缺测时返回 NaN，不返回 inf（论文 §2.3 明确要求）。
    """
    if c_net is None:
        c_net = net_condensation(t)
    tot = totals(t, c_net=c_net)
    em = t.rain_kg / tot["GQm"] if tot["GQm"] > 0 else np.nan
    eh = t.rain_kg / tot["GQh"] if tot["GQh"] > 0 else np.nan
    if total_condensation is None or tot["GQv"] <= 0:
        p_eff = np.nan
    else:
        p_eff = total_condensation / tot["GQv"]
    return {"Em": em, "Eh": eh, "P": p_eff}


def renewal_period(mean_storage_kg, rain_kg, duration_s, unit="day"):
    """更新周期。公式 (19)：T = 平均库存 / 平均降水质量速率。

    ``unit`` 决定返回单位（"day" / "hour" / "second"）；未知单位直接报错，
    不静默按秒返回（早期版本的 bug：unit="hour" 实际返回秒，Th 被放大 3600 倍）。
    分母为 0 或缺测时返回 NaN（不返回 inf）。
    """
    if unit not in _SECONDS_PER_UNIT:
        raise ValueError(f"unit 必须是 {sorted(_SECONDS_PER_UNIT)}，收到 {unit!r}")
    if rain_kg <= 0 or duration_s <= 0 or not np.isfinite(mean_storage_kg):
        return np.nan
    tau_s = mean_storage_kg / (rain_kg / duration_s)
    return tau_s / _SECONDS_PER_UNIT[unit]


# ------------------------------------------------------------- 闭合残差 (30-32)

def residuals(t: BudgetTerms, c_net=None, evap_vapor=None, evap_total=None):
    """三条收支残差，公式 (30)(31)(32)。

    残差定义为「实际存量变化 − 方程预测变化」，理论上为 0。
    残差显著不为零时**先查口径**（边界符号、步长、降水累计起点、地形以下层、
    格点面积、单位、缺测处理），不允许为了让方程闭合而改数据。
    """
    if c_net is None:
        c_net = net_condensation(t)
    if evap_vapor is None:
        evap_vapor = evaporation_from_vapor(t, c_net)
    if evap_total is None:
        evap_total = evaporation_from_total(t)
    eps_h = (t.qh_final - t.qh_init) - (t.qh_in - t.qh_out - t.rain_kg + c_net)
    eps_v = (t.qv_final - t.qv_init) - (t.qv_in - t.qv_out + evap_vapor - c_net)
    eps_m = (t.qm_final - t.qm_init) - (t.qm_in - t.qm_out + evap_total - t.rain_kg)
    return {"eps_h": eps_h, "eps_v": eps_v, "eps_m": eps_m,
            "evap_vapor": evap_vapor, "evap_total": evap_total,
            "evap_consistency": evap_vapor - evap_total}


# --------------------------------------------------------------- 汇总报告

def evaluate(t: BudgetTerms, total_condensation=None) -> dict:
    """一次算全，返回可直接写表的 dict（含单位标注）。"""
    c_net = net_condensation(t)
    res = residuals(t, c_net=c_net)
    tot = totals(t, c_net=c_net, evap=res["evap_total"])
    gcwr_total, gcwr_term, gcwr_init, spread = gcwr(t, c_net=c_net)
    eff = efficiency(t, total_condensation=total_condensation, c_net=c_net)
    area_denom = t.duration_s
    scale = min(abs(t.qh_init), abs(t.rain_kg), abs(t.qh_in), 1.0)
    return {
        "duration_days": t.duration_s / SECONDS_PER_DAY,
        "GQv_kg": tot["GQv"], "GQh_kg": tot["GQh"], "GQm_kg": tot["GQm"],
        "rain_kg": t.rain_kg,
        "net_condensation_kg": c_net,
        "evaporation_kg": res["evap_total"],
        "evaporation_vapor_kg": res["evap_vapor"],
        "evap_disagreement_kg": res["evap_consistency"],
        "gcwr_kg": gcwr_total,
        "gcwr_terminal_kg": gcwr_term,
        "gcwr_initial_kg": gcwr_init,
        "gcwr_identity_spread_kg": spread,
        "gcwr_identity_ok": bool(spread <= 1e-9 * max(scale, 1.0)),
        "Em": eff["Em"], "Eh": eff["Eh"], "P": eff["P"],
        "Tv_days": renewal_period((t.qv_init + t.qv_final) / 2, t.rain_kg,
                                  t.duration_s, unit="day"),
        "Th_hours": renewal_period((t.qh_init + t.qh_final) / 2, t.rain_kg,
                                   t.duration_s, unit="hour"),
        "eps_h_kg": res["eps_h"], "eps_v_kg": res["eps_v"], "eps_m_kg": res["eps_m"],
        "rain_rate_kg_per_s": t.rain_kg / area_denom,
        # 论文式(16) 是库存关系，必须成立；累计量下 GQm≠GQv+GQh，见 totals() 警告
        "inventory_identity_ok": bool(
            np.isclose(t.qm_init, t.qv_init + t.qh_init)
            and np.isclose(t.qm_final, t.qv_final + t.qh_final)),
        "cumulative_sum_naive_kg": tot["GQv"] + tot["GQh"],
        "units": field(default="kg（除效率为无量纲、周期为天/小时）"),
    }


# --------------------------------------------------------- 量级体检（防误用）

# 参照区间：蔡淼 2011 年全国评估（数量级判断用，不是本仓结论）
REFERENCE_BANDS = {
    "Tv_days": (0.5, 60.0),      # 论文约 11 天；大气水汽周转在数小时到数十天
    "Th_hours": (1.0, 200.0),    # 论文约 15 小时
    "Eh": (0.0, 1.0),            # 效率必在 [0,1]
    "Em": (0.0, 1.0),
}


def sanity_check(rep: dict) -> dict:
    """对 :func:`evaluate` 的输出做量级合理性体检。

    这是**物理自洽**检验，与恒等式的算术检验互补：恒等式只证明代数没写错，
    证明不了分项是否来自同一控制体。``ok=False`` 时不要解释任何结论。
    """
    flags = []
    for key, (lo, hi) in REFERENCE_BANDS.items():
        value = rep.get(key)
        if value is None or not np.isfinite(value):
            flags.append(f"{key} 为 NaN，无法判断")
            continue
        if not (lo <= value <= hi):
            flags.append(f"{key}={value:.4g} 超出合理区间 [{lo}, {hi}]")
    if not rep.get("gcwr_identity_ok", True):
        flags.append("GCWR 三种写法不一致：分项口径互相矛盾")
    if not rep.get("inventory_identity_ok", True):
        flags.append("库存关系 Qm=Qv+Qh 不成立：实现错误")
    if rep.get("gcwr_kg", 0) < 0:
        flags.append("GCWR 为负：降水超过水凝物总量，物理上不可能")
    return {"ok": not flags, "flags": flags,
            "hint": ("分项须来自同一控制体与同一时段；典型错误是用年降水配瞬时库存、"
                     "或把 kg·m⁻² 柱含量当作区域累计量") if flags else ""}


__all__ = [
    "G_STANDARD",
    "REFERENCE_BANDS",
    "BudgetTerms",
    "boundary_flux_mass",
    "boundary_signed_mass",
    "cell_area_latlon",
    "efficiency",
    "evaluate",
    "evaporation_from_total",
    "evaporation_from_vapor",
    "gcwr",
    "net_condensation",
    "rain_mass_from_mm",
    "rain_mass_from_rate",
    "regional_mass",
    "renewal_period",
    "residuals",
    "sanity_check",
    "totals",
]
