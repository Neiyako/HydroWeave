"""期刊级（Nature 风格）绘图基线：字体、线宽、脊线、面板字母、横向色标。

设计取舍：
- 版心 180 mm（双栏），正文 7 pt，图中文字一律不小于 5.5 pt；
- 只保留左/下脊线，刻度朝内，色标置于图下方（横向），符合 Nature 图注惯例；
- 配色用 cmcrameri 的感知均匀色表（batlow/roma/haline），明暗单调、色盲友好；
- 面板字母用粗体小写，置于面板左上角外侧。
"""
from __future__ import annotations

import matplotlib as mpl
import numpy as np

MM_PER_INCH = 25.4
FIGURE_WIDTH_MM = 180.0
FIGURE_HEIGHT_MM = 142.0

NATURE_RC: dict[str, object] = {
    "figure.dpi": 150,
    "savefig.dpi": 600,
    "figure.figsize": (FIGURE_WIDTH_MM / MM_PER_INCH, FIGURE_HEIGHT_MM / MM_PER_INCH),
    "font.family": "sans-serif",
    "font.sans-serif": ["Helvetica Neue", "Helvetica", "Arial", "DejaVu Sans"],
    "font.size": 7.0,
    "axes.labelsize": 7.0,
    "axes.titlesize": 7.5,
    "xtick.labelsize": 6.5,
    "ytick.labelsize": 6.5,
    "legend.fontsize": 6.5,
    "legend.frameon": False,
    "axes.linewidth": 0.5,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "xtick.major.width": 0.5,
    "ytick.major.width": 0.5,
    "xtick.minor.width": 0.4,
    "ytick.minor.width": 0.4,
    "xtick.major.size": 2.0,
    "ytick.major.size": 2.0,
    "xtick.minor.size": 1.2,
    "ytick.minor.size": 1.2,
    "xtick.direction": "in",
    "ytick.direction": "in",
    "lines.linewidth": 0.8,
    "lines.markersize": 2.6,
    "grid.linewidth": 0.4,
    "grid.color": "0.85",
    "pdf.fonttype": 42,
    "ps.fonttype": 42,
    "axes.unicode_minus": False,
    "savefig.bbox": "tight",
    "savefig.pad_inches": 0.02,
    "mathtext.fontset": "dejavusans",
}

# Nature 风格常用配色（感知均匀，明度单调）
COLORS = {
    "liquid": "#2b6cb0",     # 蓝：液态
    "ice": "#c05621",        # 橙红：冰相
    "mixed": "#805ad5",      # 紫：混合相
    "neutral": "#4a5568",
    "accent": "#2f855a",
    "bias": "#c53030",
}


def use_nature_style() -> None:
    """应用 Nature 风格 rcParams。"""
    mpl.rcParams.update(NATURE_RC)


def panel_label(axis, text: str, *, dx: float = -0.075, dy: float = 1.02,
                size: float = 8.0) -> None:
    """在面板左上角外侧放置粗体小写面板字母。"""
    axis.text(dx, dy, text, transform=axis.transAxes, fontsize=size,
              fontweight="bold", ha="left", va="bottom", color="0.0")


def horizontal_colorbar(figure, axis, mappable, label: str, *, pad: float = 0.035,
                        fraction: float = 0.035, labelpad: float = 2.0,
                        ticks=None) -> mpl.colorbar.Colorbar:
    """在面板下方放置细横向色标（Nature 惯例）。"""
    cbar = figure.colorbar(mappable, ax=axis, orientation="horizontal",
                            location="bottom", pad=pad, fraction=fraction,
                            aspect=28, shrink=0.92)
    cbar.set_label(label, fontsize=6.5, labelpad=labelpad)
    cbar.ax.tick_params(labelsize=6.0, length=2.0, width=0.5, direction="in")
    cbar.outline.set_linewidth(0.5)
    if ticks is not None:
        cbar.set_ticks(ticks)
    return cbar


def despine_all(axis) -> None:
    """去掉全部脊线（用于无边框插图）。"""
    for spine in axis.spines.values():
        spine.set_visible(False)


def add_scale_note(figure, text: str) -> None:
    """图脚注：说明数据性质与口径。"""
    figure.text(0.004, 0.004, text, ha="left", va="bottom", fontsize=5.6, color="0.35")


def percentile_levels(values: np.ndarray, count: int = 8) -> np.ndarray:
    """按分位数给出等距色标刻度。"""
    finite = np.asarray(values)[np.isfinite(values)]
    if finite.size == 0:
        return np.linspace(0, 1, count)
    return np.percentile(finite, np.linspace(0, 100, count))


def symmetric_log_limits(values: np.ndarray, percentile: float = 98.0) -> float:
    """对称色标上限（用于偏差图）。"""
    finite = np.asarray(values)[np.isfinite(values)]
    if finite.size == 0:
        return 1.0
    return float(np.percentile(np.abs(finite), percentile))


def quantile_bounds(values: np.ndarray, lower: float = 2.0,
                    upper: float = 98.0) -> tuple[float, float]:
    """稳健色标上下限。"""
    finite = np.asarray(values)[np.isfinite(values)]
    if finite.size == 0:
        return 0.0, 1.0
    return (float(np.percentile(finite, lower)), float(np.percentile(finite, upper)))
