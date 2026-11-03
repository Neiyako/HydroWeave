"""收支模型与误差分析的单元测试（合成数字，不碰外接盘）。"""
from __future__ import annotations

import numpy as np
import pytest

from experiments.tp_cloud_water import budget as B
from experiments.tp_cloud_water import error_analysis as E

DAY = B.SECONDS_PER_DAY


def _terms(**kw):
    base = dict(qv_init=1.0e12, qv_final=1.1e12, qh_init=2.0e10, qh_final=2.1e10,
                qv_in=5.0e13, qv_out=5.01e13, qh_in=1.0e11, qh_out=1.1e11,
                rain_kg=9.0e13, duration_s=30 * DAY)
    base.update(kw)
    return B.BudgetTerms(**base)


# ------------------------------------------------------------ 边界通量分解

def test_boundary_flux_all_outgoing():
    t = _terms()
    assert t.qv_out > t.qv_in
    signed = np.array([1.0, 2.0, 3.0])
    inbound, outbound = B.boundary_flux_mass(signed)
    assert (inbound, outbound) == (0.0, 6.0)


def test_boundary_flux_all_incoming():
    inbound, outbound = B.boundary_flux_mass(np.array([-1.0, -2.0, -3.0]))
    assert (inbound, outbound) == (6.0, 0.0)


def test_boundary_flux_split_matches_signed_sum():
    signed = np.array([-4.0, 1.0, 7.0, -2.5])
    inbound, outbound = B.boundary_flux_mass(signed)
    assert inbound == pytest.approx(6.5)
    assert outbound == pytest.approx(8.0)
    # 输出减输入必须等于带符号通量之和（正值为净流出）
    assert outbound - inbound == pytest.approx(signed.sum())


def test_boundary_signed_mass_formula():
    # ΔM = ρ·q·un·ΔS·Δt
    m = B.boundary_signed_mass(1.2, 0.001, 5.0, 1.0e4, 3600.0)
    assert m == pytest.approx(1.2 * 0.001 * 5.0 * 1.0e4 * 3600.0)


# ------------------------------------------------------------ 收支反算

def test_net_condensation_formula_10():
    t = _terms()
    expected = t.qh_final - t.qh_init - t.qh_in + t.qh_out + t.rain_kg
    assert B.net_condensation(t) == pytest.approx(expected)


def test_gcwr_three_expressions_agree():
    """式 (20)(21)(22) 必须给出同一个 GCWR（论文明确要求交叉核算）。"""
    t = _terms()
    a, b, c, spread = B.gcwr(t)
    assert a == pytest.approx(b)
    assert a == pytest.approx(c)
    assert spread == pytest.approx(0.0, abs=1e-6 * abs(a))


def test_gcwr_equals_qh_total_minus_rain():
    t = _terms(c_net=None) if False else _terms()
    c_net = B.net_condensation(t)
    g_qh = B.totals(t, c_net=c_net)["GQh"]
    a, *_ = B.gcwr(t, c_net=c_net)
    assert a == pytest.approx(g_qh - t.rain_kg)


def test_evaporation_two_paths_consistent():
    """式 (11) 与式 (12) 反算的地面蒸发应一致（同一组自洽输入）。"""
    t = _terms()
    res = B.residuals(t)
    assert res["evap_vapor"] == pytest.approx(res["evap_total"])
    assert res["evap_consistency"] == pytest.approx(0.0, abs=1e-6)


def test_totals_self_consistency():
    t = _terms()
    c_net = B.net_condensation(t)
    tot = B.totals(t, c_net=c_net, evap=B.evaporation_from_total(t))
    # GQv = 初值+输入+蒸发 = 终值+输出+净凝结
    assert tot["GQv"] == pytest.approx(tot["check_qv"])
    assert tot["GQh"] == pytest.approx(tot["check_qh"])
    # 总水物质走自己的方程（式15），两端闭合
    assert tot["GQm"] == pytest.approx(tot["check_qm"])


def test_cumulative_gqm_is_not_sum_of_gqv_and_gqh():
    """口径红线：论文式(16) GQm=GQv+GQh 只对**瞬时库存**成立。

    累计算量下净凝结在 GQv 里是汇、在 GQh 里是源，相加会重复计入，
    因此 GQm 必须走式(15)独立核算，不能写成 GQv+GQh。
    """
    t = _terms()
    rep = B.evaluate(t)
    naive = rep["cumulative_sum_naive_kg"]
    assert rep["GQm_kg"] != pytest.approx(naive, rel=1e-3)
    # 守恒关系：GQm = GQv + GQh − C_net（净凝结只计一次）
    assert rep["GQm_kg"] == pytest.approx(rep["GQv_kg"] + rep["GQh_kg"]
                                         - rep["net_condensation_kg"])
    assert rep["inventory_identity_ok"] is True


def test_residual_closed_for_consistent_inputs():
    """净凝结与蒸发由反算得到时，三条残差恒为零（算术一致性）。"""
    t = _terms()
    res = B.residuals(t)
    for key in ("eps_h", "eps_v", "eps_m"):
        assert res[key] == pytest.approx(0.0, abs=1e-4)


def test_efficiency_not_infinite_on_zero_denominator():
    t = _terms(qh_init=0.0, qh_final=0.0, qh_in=0.0, qh_out=0.0, rain_kg=0.0)
    eff = B.efficiency(t, c_net=0.0)
    assert np.isnan(eff["Eh"])      # 分母为 0 → NaN，不是 inf
    assert np.isnan(eff["P"])       # 未给总凝结量 → NaN


def test_renewal_period_units():
    # 平均库存 1e12 kg，降水 1e13 kg / 10 天 → 速率 1e12 kg/天 → 周期 1 天
    tau = B.renewal_period(1e12, 1e13, 10 * DAY, unit="day")
    assert tau == pytest.approx(1.0)
    assert np.isnan(B.renewal_period(1e12, 0.0, 10 * DAY))


def test_invalid_terms_rejected():
    with pytest.raises(ValueError):
        _terms(duration_s=0)
    with pytest.raises(ValueError):
        _terms(rain_kg=float("nan"))


# ------------------------------------------------------------ 区域总量

def test_regional_mass_uses_cos_lat_area():
    lat = np.array([30.0, 40.0])
    lon = np.array([80.0, 81.0])
    area = B.cell_area_latlon(lat, lon)
    assert area.shape == (2, 2)
    # 高纬格点面积更小
    assert area[1, 0] < area[0, 0]
    mass = B.regional_mass(np.ones((2, 2)), area, np.ones((2, 2), dtype=bool))
    assert mass == pytest.approx(area.sum())


def test_regional_mass_ignores_nan_and_masked():
    area = np.ones((2, 2))
    data = np.array([[1.0, np.nan], [5.0, 5.0]])
    mask = np.array([[True, True], [True, False]])
    assert B.regional_mass(data, area, mask) == pytest.approx(6.0)  # 1 + 5，NaN 与掩膜外剔除


# ------------------------------------------------------------ 误差传播

def test_gcwr_sigma_linear_propagation():
    """GCWR 对 qh_final 与 qh_out 的偏导均为 1，σ 应为平方和开根。"""
    sigma = E.TermSigma(qh_final=3.0, qh_out=4.0)
    g = E.gcwr_sigma(sigma)
    assert g["sigma"] == pytest.approx(5.0)   # 3-4-5
    assert set(g["contributions"]) == {"qh_final", "qh_out"}


def test_terms_not_affecting_gcwr_have_zero_weight():
    """降水、水汽各项对 GCWR 的一阶敏感度为 0，不应进入误差表。"""
    g = E.gcwr_sigma(E.TermSigma(rain_kg=1e9, qv_in=1e9, qh_in=1e9))
    assert g["sigma"] == 0.0


def test_calibration_independent_combination():
    factors = [E.CalibrationFactor("subsurf", 0.217, "high"),
               E.CalibrationFactor("magnus", 0.10, "low")]
    out = E.apply_calibration(1000.0, factors)
    assert out["relative_sigma"] == pytest.approx(np.hypot(0.217, 0.10))
    assert out["direction"] == "mixed"      # 方向相反 → 只能说区间
    assert out["dominant"] == "subsurf"


def test_calibration_unique_direction():
    factors = [E.CalibrationFactor("subsurf", 0.2, "high")]
    out = E.apply_calibration(1000.0, factors)
    assert out["direction"] == "high"
    assert out["interval"] == pytest.approx((800.0, 1200.0))


def test_summarize_verdict_thresholds():
    t = _terms()
    rep = B.evaluate(t)
    good = E.summarize(rep, E.TermSigma(qh_final=abs(rep["gcwr_kg"]) * 0.05))
    assert good["verdict"] == "CONCLUSIVE"
    bad = E.summarize(rep, E.TermSigma(qh_final=abs(rep["gcwr_kg"]) * 0.8))
    assert bad["verdict"] == "INSUFFICIENT_EVIDENCE"


def test_closure_check_pass_on_consistent_input():
    assert E.closure_check(_terms())["verdict"] == "PASS"


# ------------------------------------------------------------ 量级体检

def test_sanity_check_catches_inconsistent_scale():
    """试算中真实踩到的坑：用年降水配瞬时库存，Tv/Th 会差两个数量级。"""
    t = _terms(rain_kg=1.0e8, duration_s=365 * DAY)
    rep = B.evaluate(t)
    chk = B.sanity_check(rep)
    assert chk["ok"] is False
    assert any("Tv_days" in f or "Th_hours" in f for f in chk["flags"])


def test_sanity_check_flags_negative_gcwr():
    t = _terms(qh_init=1.0, qh_final=1.0, qh_in=0.0, qh_out=0.0, rain_kg=9.0e13)
    rep = B.evaluate(t)
    assert B.sanity_check(rep)["ok"] is False


def test_sanity_check_accepts_reference_scale():
    """按论文 2011 年全国真实量级构造的自洽输入应通过体检。

    论文第 7 章：水汽瞬时平均 2.03e14 kg、水凝物 1.14e13 kg、
    地面降水 6.58e15 kg/年 → Tv=11 天、Th=15 小时、Eh=77%。
    """
    GR, DAYS = 6.58e15, 365.0
    t = _terms(qv_init=2.03e14, qv_final=2.03e14,
               qh_init=1.14e13, qh_final=1.14e13,
               qv_in=2.05e16, qv_out=2.05e16,
               qh_in=2.1e15, qh_out=1.9e15,
               rain_kg=GR, duration_s=DAYS * DAY)
    rep = B.evaluate(t)
    chk = B.sanity_check(rep)
    assert chk["ok"] is True, chk["flags"]
    # 与论文报告值交叉核对（容差放宽，因为边界通量是示意值）
    assert rep["Tv_days"] == pytest.approx(11.0, rel=0.15)
    assert rep["Th_hours"] == pytest.approx(15.0, rel=0.15)


def test_renewal_period_hour_unit_is_hours_not_seconds():
    """回归：unit="hour" 曾返回秒，使 Th 被放大 3600 倍。"""
    # 库存 1e12 kg，降水 1e13 kg / 10 天 → 速率 1e12 kg/天 → 周期 1 天 = 24 小时
    assert B.renewal_period(1e12, 1e13, 10 * DAY, unit="hour") == pytest.approx(24.0)
    assert B.renewal_period(1e12, 1e13, 10 * DAY, unit="day") == pytest.approx(1.0)
    assert B.renewal_period(1e12, 1e13, 10 * DAY, unit="second") == pytest.approx(86400.0)
    with pytest.raises(ValueError):
        B.renewal_period(1e12, 1e13, 10 * DAY, unit="minute")
