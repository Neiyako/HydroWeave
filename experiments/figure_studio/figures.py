"""仿真云水场的期刊级图件：空间结构、垂直结构、误差结构、天气演变。

版式规则（Nature 双栏 180 mm）：
- 所有面板用英寸矩形精确定位，地图面板按投影纵横比锁定高度，色标贴在地图正下方；
- 面板字母为粗体小写，置于面板左上角外侧；坐标轴只保留左/下脊线；
- 图面文字一律英文（仓库默认字体无 CJK 字形），图注在 JSON 里给中文对照。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import cartopy.crs as ccrs
import cartopy.feature as cfeature
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.collections import LineCollection
from matplotlib.colors import LogNorm, TwoSlopeNorm
from matplotlib.ticker import FuncFormatter, NullFormatter

from experiments.figure_studio import style
from experiments.figure_studio.synth import SyntheticRun, weighted_profile
from experiments.figure_studio.terrain import DEFAULT_CHINA_SHP, Grid

try:  # cmcrameri：感知均匀、色盲友好
    from cmcrameri import cm as _cmc

    CMAP_LIQUID = _cmc.batlow
    CMAP_ICE = _cmc.roma
    CMAP_BIAS = _cmc.vik
    CMAP_TERRAIN = _cmc.broc
    CMAP_DENSITY = plt.get_cmap("Blues")
except ImportError:  # pragma: no cover
    CMAP_LIQUID = plt.get_cmap("viridis")
    CMAP_ICE = plt.get_cmap("magma")
    CMAP_BIAS = plt.get_cmap("RdBu_r")
    CMAP_TERRAIN = plt.get_cmap("terrain")
    CMAP_DENSITY = plt.get_cmap("Blues")

PROJECTION = ccrs.AlbersEqualArea(
    central_longitude=95.0, central_latitude=35.0, standard_parallels=(25.0, 47.0))
PLATE = ccrs.PlateCarree()
DOMAIN = [70.0, 105.0, 25.0, 40.0]
MAP_ASPECT = 1.847          # Albers 下研究域的宽高比（宽 / 高）
MAP_WIDTH_IN = 2.10
MAP_HEIGHT_IN = MAP_WIDTH_IN / MAP_ASPECT


@dataclass
class FigureSpec:
    """一张成图的落盘信息。"""

    name: str
    path: Path
    title: str
    sha256: str = ""
    size_bytes: int = 0


# --------------------------------------------------------------------------- #
# 版式工具
# --------------------------------------------------------------------------- #
def _rect(x_in: float, y_in: float, width_in: float, height_in: float,
          fig_width_in: float, fig_height_in: float) -> list[float]:
    """英寸坐标（左上原点）→ figure 分数坐标。"""
    return [x_in / fig_width_in,
            1.0 - (y_in + height_in) / fig_height_in,
            width_in / fig_width_in,
            height_in / fig_height_in]


def _axes(figure, rect: list[float], *, projection=None):
    return figure.add_axes(rect, projection=projection)


def _panel(axis, letter: str, *, dx: float = -0.06, dy: float = 1.015,
           size: float = 8.0) -> None:
    axis.text(dx, dy, letter, transform=axis.transAxes, fontsize=size,
              fontweight="bold", ha="left", va="bottom", color="0.0")


def _add_cbar(figure, axis, mappable, label: str, *, height_in: float = 0.135,
              gap_in: float = 0.05, ticks=None, formatter=None,
              log_ticks: bool = False):
    """在面板正下方贴一条横向色标（不改变面板尺寸）。"""
    figure.canvas.draw()
    position = axis.get_position()
    fig_height = figure.get_figheight()
    cax = figure.add_axes([position.x0,
                            position.y0 - (height_in + gap_in) / fig_height,
                            position.width, height_in / fig_height])
    colorbar = figure.colorbar(mappable, cax=cax, orientation="horizontal")
    colorbar.set_label(label, fontsize=6.3, labelpad=2.0)
    colorbar.ax.tick_params(labelsize=5.8, length=2.0, width=0.45, direction="in")
    colorbar.outline.set_linewidth(0.45)
    if log_ticks:
        def _log_formatter(value, _position):
            if value <= 0:
                return ""
            return f"$10^{{{round(np.log10(value))}}}$"

        limits = mappable.norm.vmin, mappable.norm.vmax
        if np.isfinite(limits[0]) and limits[0] > 0:
            decades = np.arange(np.floor(np.log10(limits[0])),
                                np.ceil(np.log10(limits[1])) + 1)
            colorbar.set_ticks([10 ** exponent for exponent in decades])
        colorbar.ax.xaxis.set_major_formatter(FuncFormatter(_log_formatter))
        colorbar.ax.xaxis.set_minor_formatter(NullFormatter())
    if ticks is not None:
        colorbar.set_ticks(ticks)
    if formatter is not None:
        colorbar.ax.xaxis.set_major_formatter(formatter)
    return colorbar


def _safe_feature(draw, *args, **kwargs) -> None:
    """Natural Earth 底图离线不可下载时降级为无底图，不阻断出图。"""
    import contextlib
    from urllib.error import URLError

    with contextlib.suppress(OSError, URLError, RuntimeError, ValueError):
        draw(*args, **kwargs)


def decorate_map_axis(axis, grid: Grid, *, boundary=None,
                      shade_alpha: float = 0.22, provinces: bool = False,
                      labels: bool = False, shade: bool = True):
    """给现成的 GeoAxes 铺统一底图：陆地/湖泊/河流/国界/省界/边界/山体阴影。"""
    axis.set_extent(DOMAIN, crs=PLATE)
    _safe_feature(axis.add_feature, cfeature.LAND.with_scale("50m"),
                  facecolor="#f7f7f5", zorder=0)
    _safe_feature(axis.add_feature, cfeature.OCEAN.with_scale("50m"),
                  facecolor="white", zorder=0)
    _safe_feature(axis.add_feature, cfeature.LAKES.with_scale("50m"),
                  facecolor="white", edgecolor="0.78", linewidth=0.2, zorder=0)
    _safe_feature(axis.add_feature, cfeature.RIVERS.with_scale("50m"),
                  edgecolor="#bcc8d6", linewidth=0.22, zorder=1)
    _safe_feature(axis.add_feature, cfeature.BORDERS.with_scale("50m"),
                  edgecolor="0.45", linewidth=0.3, zorder=3)
    _safe_feature(axis.coastlines, resolution="50m", linewidth=0.3, color="0.45")
    if provinces:
        segments = _province_lines()
        if segments:
            axis.add_collection(LineCollection(segments, transform=PLATE,
                                               linewidths=0.22, colors="0.80", zorder=2))
    if shade and grid.shade is not None:
        axis.imshow(grid.shade, extent=DOMAIN, transform=PLATE, origin="lower",
                    cmap="Greys_r", vmin=0.30, vmax=1.0, alpha=shade_alpha,
                    interpolation="bilinear", zorder=1.5)
    if boundary is not None:
        axis.plot(boundary[:, 0], boundary[:, 1], transform=PLATE, color="#1a202c",
                  linewidth=0.7, zorder=4)
    gridlines = axis.gridlines(draw_labels=labels, linewidth=0.28, color="0.85",
                               linestyle=(0, (2, 3)), zorder=5)
    if labels:
        gridlines.top_labels = False
        gridlines.right_labels = False
        gridlines.xlabel_style = {"size": 5.6}
        gridlines.ylabel_style = {"size": 5.6}
        gridlines.xlocator = matplotlib.ticker.FixedLocator(np.arange(70, 106, 5))
        gridlines.ylocator = matplotlib.ticker.FixedLocator(np.arange(25, 41, 5))
    for spine in axis.spines.values():
        spine.set_linewidth(0.4)
    return axis


def _map_axes(figure, rect: list[float], grid: Grid, *, boundary=None,
              shade_alpha: float = 0.22, provinces: bool = False,
              labels: bool = False, shade: bool = True):
    """新建 GeoAxes 并铺好统一底图。"""
    axis = _axes(figure, rect, projection=PROJECTION)
    return decorate_map_axis(axis, grid, boundary=boundary, shade_alpha=shade_alpha,
                             provinces=provinces, labels=labels, shade=shade)


def _province_lines(shp_dir: str | Path = DEFAULT_CHINA_SHP) -> list[np.ndarray]:
    """读省级界线（1:4M），裁到研究域。"""
    import shapefile

    path = Path(shp_dir) / "bou2_4l.shp"
    if not path.exists():
        return []
    reader = shapefile.Reader(str(path), encoding="gbk")
    segments: list[np.ndarray] = []
    for shape_ in reader.shapes():
        points = np.asarray(shape_.points, dtype="float64")
        if points.size == 0:
            continue
        parts = list(shape_.parts) + [len(points)]
        for start, stop in zip(parts[:-1], parts[1:], strict=False):
            piece = points[start:stop]
            if piece.shape[0] < 2:
                continue
            if (piece[:, 0].max() < DOMAIN[0] or piece[:, 0].min() > DOMAIN[1]
                    or piece[:, 1].max() < DOMAIN[2] or piece[:, 1].min() > DOMAIN[3]):
                continue
            segments.append(piece)
    return segments


def _refine(values: np.ndarray, grid: Grid, *, step_deg: float = 0.025,
            sigma: float = 1.0, edge_fade_deg: float = 0.75,
            texture: float = 0.06, seed: int = 0):
    """把 0.25° 场细化到 0.025° 并平滑，同时给出边缘渐隐的 alpha。

    三件事：1) 线性插值 + 高斯平滑消掉网格马赛克；2) 叠加极弱的分形纹理，
    让图面像真实格点产品而不是喷绘；3) 研究域矩形边界用 alpha 渐隐溶进底图。
    纹理只用于渲染，落盘的真值场不受影响（脚注已注明）。
    """
    from scipy.interpolate import RegularGridInterpolator
    from scipy.ndimage import gaussian_filter

    from experiments.figure_studio.terrain import _fill_nan

    fine_lat = np.round(np.arange(grid.latitude[0], grid.latitude[-1] + 1e-9,
                                   step_deg), 6)
    fine_lon = np.round(np.arange(grid.longitude[0], grid.longitude[-1] + 1e-9,
                                   step_deg), 6)
    interpolator = RegularGridInterpolator(
        (grid.latitude, grid.longitude), np.asarray(values, dtype="float64"),
        bounds_error=False, fill_value=np.nan)
    lon_grid, lat_grid = np.meshgrid(fine_lon, fine_lat)
    fine = interpolator(np.column_stack([lat_grid.ravel(), lon_grid.ravel()]))
    fine = _fill_nan(fine.reshape(lat_grid.shape))
    fine = gaussian_filter(fine, sigma=sigma, mode="nearest")

    if texture > 0:
        rng = np.random.default_rng(seed)
        noise = rng.standard_normal(fine.shape)
        for octave, weight in ((0.6, 1.0), (1.6, 0.6), (4.0, 0.3)):
            noise = noise + weight * gaussian_filter(
                rng.standard_normal(fine.shape), sigma=octave, mode="nearest")
        noise /= float(noise.std() + 1e-12)
        # 纹理幅度随场值衰减：近零区不加纹理，否则「无云」边界会出现麻点
        positive = fine[fine > 0]
        reference = float(np.percentile(positive, 20)) if positive.size else 1.0
        taper = np.clip(fine / (0.30 * max(reference, 1e-30)), 0.0, 1.0)
        fine = fine * (1.0 + texture * noise * taper)

    lat_distance = np.minimum(lat_grid - fine_lat[0], fine_lat[-1] - lat_grid)
    lon_distance = np.minimum(lon_grid - fine_lon[0], fine_lon[-1] - lon_grid)
    alpha = np.clip(np.minimum(lat_distance, lon_distance) / edge_fade_deg, 0.0, 1.0)
    return fine_lat, fine_lon, fine, alpha


def _field_on_map(axis, grid: Grid, values: np.ndarray, *, cmap, norm=None,
                  alpha: float = 1.0, zorder: float = 2.0, refine: bool = True,
                  seed: int = 0, texture: float = 0.06):
    values = np.asarray(values, dtype="float64")
    values = np.where(np.isfinite(values) & (values > 0), values, np.nan)
    if not refine:
        return axis.pcolormesh(grid.longitude, grid.latitude, values, transform=PLATE,
                               cmap=cmap, norm=norm, shading="auto", alpha=alpha,
                               zorder=zorder, rasterized=True)
    fine_lat, fine_lon, fine, edge_alpha = _refine(values, grid, seed=seed,
                                                     texture=texture)
    return axis.pcolormesh(fine_lon, fine_lat, fine, transform=PLATE, cmap=cmap,
                           norm=norm, shading="auto", alpha=edge_alpha * alpha,
                           zorder=zorder, rasterized=True)


def _cmap_with_under(cmap, color: str = "#f7f7f5"):
    """复制色表并指定「低于下限」的填充色（避免出现黑块）。"""
    copied = plt.get_cmap(cmap).copy()
    copied.set_under(color)
    copied.set_bad(color)
    return copied


def _log_cmap(cmap):
    """对数色标：把 0 值渲染成色表最暗端，保持连续场观感。"""
    base = plt.get_cmap(cmap)
    copied = base.copy()
    copied.set_under((1.0, 1.0, 1.0, 0.0))   # 0 值透明，露出底图
    copied.set_bad((1.0, 1.0, 1.0, 0.0))
    return copied


# --------------------------------------------------------------------------- #
# 图 1：空间结构
# --------------------------------------------------------------------------- #
def figure_spatial(run: SyntheticRun, *, boundary: np.ndarray,
                   path: Path, time_index: int = 2) -> FigureSpec:
    grid = run.grid
    lwp = run.lwp_truth[time_index] * 1000.0     # g m-2
    iwp = run.iwp_truth[time_index] * 1000.0
    time_label = f"{int(run.times[time_index]):02d} UTC"

    fig_w, fig_h = 7.09, 4.95
    figure = plt.figure(figsize=(fig_w, fig_h))
    left, gap = 0.42, 0.115
    top_map_y = 0.46
    bottom_w = 4.05
    scatter_w = 2.30

    # (a) 地形与高原范围
    axis_a = _map_axes(figure, _rect(left, top_map_y, MAP_WIDTH_IN, MAP_HEIGHT_IN,
                                     fig_w, fig_h), grid, boundary=boundary,
                       shade_alpha=0.85, provinces=True, labels=True)
    scratch = plt.figure()
    contour_set = scratch.add_subplot(111).contour(
        grid.longitude, grid.latitude, grid.elevation,
        levels=[1000.0, 2000.0, 3000.0, 4000.0, 5000.0])
    contour_segments = [(seg, level) for level, parts in
                        zip(contour_set.levels, contour_set.allsegs, strict=True)
                        for seg in parts]
    plt.close(scratch)
    for segment, level in contour_segments:
        axis_a.plot(segment[:, 0], segment[:, 1], transform=PLATE,
                    color="#111827" if level == 3000.0 else "#64748b",
                    linewidth=0.75 if level == 3000.0 else 0.3,
                    linestyle="-" if level == 3000.0 else (0, (3, 3)), zorder=4)
    _panel(axis_a, "a", dx=-0.13)
    axis_a.set_title("Terrain and plateau extent", fontsize=7.0, pad=2.5)

    # (b) 液态水路径
    axis_b = _map_axes(figure, _rect(left + MAP_WIDTH_IN + gap, top_map_y,
                                     MAP_WIDTH_IN, MAP_HEIGHT_IN, fig_w, fig_h),
                       grid, shade_alpha=0.14)
    mesh_b = _field_on_map(axis_b, grid, lwp, cmap=_log_cmap(CMAP_LIQUID),
                           norm=LogNorm(vmin=max(float(np.percentile(lwp[lwp > 0], 5)), 0.3),
                                        vmax=float(np.percentile(lwp, 98))))
    _panel(axis_b, "b", dx=-0.13)
    axis_b.set_title(f"Liquid water path ({time_label})", fontsize=7.0, pad=2.5)

    # (c) 冰水路径
    axis_c = _map_axes(figure, _rect(left + 2 * (MAP_WIDTH_IN + gap), top_map_y,
                                     MAP_WIDTH_IN, MAP_HEIGHT_IN, fig_w, fig_h),
                       grid, shade_alpha=0.14)
    mesh_c = _field_on_map(axis_c, grid, iwp, cmap=_log_cmap(CMAP_ICE),
                           norm=LogNorm(vmin=max(float(np.percentile(iwp[iwp > 0], 5)), 0.3),
                                        vmax=float(np.percentile(iwp, 98))))
    _panel(axis_c, "c", dx=-0.13)
    axis_c.set_title(f"Ice water path ({time_label})", fontsize=7.0, pad=2.5)

    # (d) LWP–IWP 联合分布
    axis_d = _axes(figure, _rect(left, 2.42, bottom_w, 1.45, fig_w, fig_h))
    mask = (lwp > 0.5) & (iwp > 0.5)
    x_edges = 10 ** np.linspace(np.log10(float(lwp[mask].min())),
                                 np.log10(float(lwp[mask].max())), 45)
    y_edges = 10 ** np.linspace(np.log10(float(iwp[mask].min())),
                                 np.log10(float(iwp[mask].max())), 45)
    counts, _, _ = np.histogram2d(lwp[mask], iwp[mask], bins=[x_edges, y_edges])
    density = axis_d.pcolormesh(x_edges, y_edges, counts.T, cmap=CMAP_DENSITY,
                                shading="auto", rasterized=True,
                                norm=LogNorm(vmin=1.0, vmax=max(
                                    float(np.percentile(counts[counts > 0], 97)), 2.0)))
    lo = float(min(lwp[mask].min(), iwp[mask].min()))
    hi = float(max(lwp[mask].max(), iwp[mask].max()))
    axis_d.plot([lo, hi], [lo, hi], "--", color="#c53030", linewidth=0.7, label="1 : 1")
    axis_d.set_xscale("log")
    axis_d.set_yscale("log")
    axis_d.set_xlim(float(lwp[mask].min()), float(lwp[mask].max()))
    axis_d.set_ylim(float(iwp[mask].min()), float(iwp[mask].max()))
    axis_d.set_xticks([1, 10, 100, 1000])
    axis_d.set_yticks([1, 10, 100, 1000])
    axis_d.set_xticklabels(["1", "10", "100", "1000"])
    axis_d.set_yticklabels(["1", "10", "100", "1000"])
    axis_d.set_xlabel("LWP (g m$^{-2}$)")
    axis_d.set_ylabel("IWP (g m$^{-2}$)")
    axis_d.grid(True, which="major", linewidth=0.3, color="0.9")
    r_value = float(np.corrcoef(np.log10(lwp[mask]), np.log10(iwp[mask]))[0, 1])
    axis_d.text(0.035, 0.95, f"log-log r = {r_value:.2f}\nn = {int(mask.sum())} cells",
                transform=axis_d.transAxes, va="top", ha="left", fontsize=6.0)
    axis_d.legend(loc="lower right", fontsize=6.0)
    _panel(axis_d, "d", dx=-0.055)
    axis_d.set_title("Joint distribution of LWP and IWP", fontsize=7.0, pad=2.5)

    # (e) LWP 与地形
    axis_e = _axes(figure, _rect(left + bottom_w + gap, 2.42, scatter_w, 1.45,
                                 fig_w, fig_h))
    elevation = grid.elevation.ravel()
    scatter = axis_e.scatter(elevation, lwp.ravel(), s=0.7, c=elevation,
                              cmap="terrain", vmin=0.0, vmax=6000.0,
                              linewidths=0, alpha=0.5)
    bin_edges = np.arange(0, 6200, 250.0)
    centers, medians = [], []
    for low, high in zip(bin_edges[:-1], bin_edges[1:], strict=False):
        selection = (elevation >= low) & (elevation < high)
        if selection.sum() > 8:
            centers.append(0.5 * (low + high))
            medians.append(float(np.median(lwp.ravel()[selection])))
    axis_e.plot(centers, medians, color="#111827", linewidth=1.0, marker="o",
                markersize=2.0, label="median")
    axis_e.set_xlabel("Surface elevation (m)")
    axis_e.set_ylabel("LWP (g m$^{-2}$)")
    axis_e.set_yscale("log")
    axis_e.grid(True, linewidth=0.3, color="0.9")
    axis_e.legend(loc="upper right", fontsize=6.0)
    _panel(axis_e, "e", dx=-0.085)
    axis_e.set_title("LWP versus elevation", fontsize=7.0, pad=2.5)

    figure.suptitle("Figure 1 | Spatial structure of simulated cloud water over the "
                    "Tibetan Plateau", fontsize=8.2, y=0.982)

    figure.canvas.draw()
    _add_cbar(figure, axis_b, mesh_b, "LWP (g m$^{-2}$)", log_ticks=True)
    _add_cbar(figure, axis_c, mesh_c, "IWP (g m$^{-2}$)", log_ticks=True)
    _add_cbar(figure, axis_d, density, "grid cells (log density)", gap_in=0.42)
    _add_cbar(figure, axis_e, scatter, "Elevation (m)", gap_in=0.42,
              ticks=[0, 1500, 3000, 4500, 6000])
    style.add_scale_note(figure,
                         "Synthetic data (figure-style validation only): GTOPO30 topography, "
                         "analytic thermodynamic profile, monsoon moisture, orographic forcing "
                         "and mesoscale convection. Not an observational result. "
                         "LWP and IWP are trapezoidal integrals of clwc and ciwc over pressure.")
    figure.savefig(path)
    plt.close(figure)
    return FigureSpec(name=path.name, path=path, title="spatial structure")


# --------------------------------------------------------------------------- #
# 图 2：垂直结构与相态
# --------------------------------------------------------------------------- #
def figure_vertical(run: SyntheticRun, *, path: Path, time_index: int = 2) -> FigureSpec:
    grid = run.grid
    levels = run.levels_hpa
    clwc = run.clwc_truth[time_index] * 1e6      # mg kg-1
    ciwc = run.ciwc_truth[time_index] * 1e6

    fig_w, fig_h = 7.09, 3.30
    figure = plt.figure(figsize=(fig_w, fig_h))
    left, gap = 0.55, 0.30
    width_a = 1.85
    width_b = 1.85
    width_c = 2.25
    top_y = 0.52

    # (a) 廓线
    axis_a = _axes(figure, _rect(left, top_y, width_a, 1.95, fig_w, fig_h))
    for profile, color, label in (
            (clwc, style.COLORS["liquid"], "clwc (liquid)"),
            (ciwc, style.COLORS["ice"], "ciwc (ice)")):
        mean_profile = weighted_profile(profile, grid.latitude)
        flat = profile.reshape(profile.shape[0], -1)
        with np.errstate(invalid="ignore"):
            low = np.nanpercentile(np.where(flat > 0, flat, np.nan), 10, axis=1)
            high = np.nanpercentile(np.where(flat > 0, flat, np.nan), 90, axis=1)
        low = np.nan_to_num(low, nan=0.0)
        high = np.nan_to_num(high, nan=0.0)
        axis_a.fill_betweenx(levels, np.maximum(low, 1e-2), np.maximum(high, 1e-2),
                             color=color, alpha=0.15, linewidth=0)
        axis_a.plot(mean_profile, levels, color=color, linewidth=1.0, label=label)
    axis_a.set_xscale("log")
    axis_a.set_xlim(0.03, 2000)
    axis_a.set_ylim(levels.max(), levels.min())
    axis_a.set_xlabel("Cloud water mixing ratio (mg kg$^{-1}$)")
    axis_a.set_ylabel("Pressure (hPa)")
    axis_a.set_yticks([100, 200, 300, 400, 500, 600, 700, 850, 1000])
    axis_a.grid(True, linewidth=0.3, color="0.9")
    axis_a.legend(loc="upper left", fontsize=6.0)
    _panel(axis_a, "a", dx=-0.16)
    axis_a.set_title("Domain-mean profiles (P10-P90)", fontsize=7.0, pad=2.5)

    # (b) 相态占比
    axis_b = _axes(figure, _rect(left + width_a + gap, top_y, width_b, 1.95,
                                 fig_w, fig_h))
    total = clwc + ciwc
    cloudy = total > 1e-9
    f_ice = np.where(total > 1e-9, ciwc / np.maximum(total, 1e-30), 0.0)
    weight = np.broadcast_to(np.cos(np.deg2rad(grid.latitude))[None, :, None],
                             total.shape)
    def share(mask):
        return (mask * weight).sum(axis=(1, 2)) / weight[0].sum()
    cloud_weight = share(cloudy)
    fractions = {
        "Clear": 1.0 - cloud_weight,
        "Liquid only": share(cloudy & (f_ice < 0.1)),
        "Mixed phase": share(cloudy & (f_ice >= 0.1) & (f_ice <= 0.9)),
        "Ice only": share(cloudy & (f_ice > 0.9)),
    }
    palette = {"Clear": "#eef2f7", "Liquid only": style.COLORS["liquid"],
               "Mixed phase": style.COLORS["mixed"], "Ice only": style.COLORS["ice"]}
    bottom = np.zeros(levels.size)
    for name, values in fractions.items():
        axis_b.fill_betweenx(levels, bottom, bottom + values, color=palette[name],
                             linewidth=0.3, edgecolor="#ffffff" if name == "Clear" else "none",
                             label=name)
        bottom = bottom + values
    axis_b.set_ylim(levels.max(), levels.min())
    axis_b.set_xlim(0, 1)
    axis_b.set_yticks([100, 200, 300, 400, 500, 600, 700, 850, 1000])
    axis_b.set_xlabel("Area fraction")
    axis_b.set_ylabel("Pressure (hPa)")
    axis_b.legend(loc="upper center", bbox_to_anchor=(0.5, -0.16), fontsize=5.6,
                  ncol=4, handlelength=1.0, columnspacing=0.8, labelspacing=0.2)
    _panel(axis_b, "b", dx=-0.16)
    axis_b.set_title("Cloud phase fraction (area weighted)", fontsize=7.0, pad=2.5)

    # (c) 30°N 剖面（CWP 上、地下）
    x0 = left + width_a + width_b + 2 * gap
    axis_c = _axes(figure, _rect(x0, top_y, width_c, 1.42, fig_w, fig_h))
    row = int(np.argmin(np.abs(grid.latitude - 30.0)))
    cwp = (run.lwp_truth[time_index] + run.iwp_truth[time_index])[row] * 1000.0
    axis_c.fill_between(grid.longitude, 0, cwp, color="#4a5568", alpha=0.5, linewidth=0)
    axis_c.plot(grid.longitude, cwp, color="#1a202c", linewidth=0.6)
    axis_c.set_ylabel("CWP (g m$^{-2}$)")
    axis_c.set_xlim(grid.longitude[0], grid.longitude[-1])
    axis_c.set_ylim(0, float(cwp.max()) * 1.12)
    axis_c.grid(True, axis="y", linewidth=0.3, color="0.9")
    axis_c.tick_params(labelbottom=False)
    _panel(axis_c, "c", dx=-0.10)
    axis_c.set_title("Cross-section at 30$\\degree$N", fontsize=7.0, pad=2.5)

    axis_c2 = _axes(figure, _rect(x0, top_y + 1.50, width_c, 0.45, fig_w, fig_h))
    axis_c2.fill_between(grid.longitude, 0, grid.elevation[row] / 1000.0,
                         color="#c05621", alpha=0.35, linewidth=0)
    axis_c2.plot(grid.longitude, grid.elevation[row] / 1000.0, color="#7b341e",
                 linewidth=0.55)
    axis_c2.set_xlim(grid.longitude[0], grid.longitude[-1])
    axis_c2.set_ylim(0, 8.0)
    axis_c2.set_yticks([0, 4, 8])
    axis_c2.set_xlabel("Longitude (°E)")
    axis_c2.set_ylabel("Elevation (km)", fontsize=6.5)
    axis_c2.grid(True, axis="y", linewidth=0.3, color="0.9")

    figure.suptitle("Figure 2 | Vertical structure and phase partition of cloud water",
                    fontsize=8.2, y=0.975)
    style.add_scale_note(figure,
                         "Synthetic data. Phase is diagnosed from the environmental "
                         "temperature: T > -5 degC liquid-dominated, -5 to -20 degC mixed "
                         "phase, T < -20 degC ice-dominated; fractions are area weighted. "
                         "Shading shows P10-P90 of cloudy grid cells.")
    figure.savefig(path)
    plt.close(figure)
    return FigureSpec(name=path.name, path=path, title="vertical structure")


# --------------------------------------------------------------------------- #
# 图 3：误差结构
# --------------------------------------------------------------------------- #
def figure_error(run: SyntheticRun, *, path: Path, time_index: int = 2) -> FigureSpec:
    grid = run.grid
    truth = (run.lwp_truth[time_index] + run.iwp_truth[time_index]) * 1000.0
    product = (run.lwp_product[time_index] + run.iwp_product[time_index]) * 1000.0
    mask = truth > 1.0
    error = np.full_like(truth, np.nan)
    error[mask] = (product[mask] - truth[mask]) / truth[mask] * 100.0

    fig_w, fig_h = 7.09, 4.75
    figure = plt.figure(figsize=(fig_w, fig_h))
    left, gap = 0.50, 0.42
    panel_w = 2.02
    top_y = 0.58
    map_w = panel_w

    # (a) 真值 vs 产品
    axis_a = _axes(figure, _rect(left, top_y, panel_w, 1.60, fig_w, fig_h))
    t_edges = 10 ** np.linspace(np.log10(max(float(truth[mask].min()), 1.0)),
                                np.log10(float(truth[mask].max())), 35)
    p_edges = 10 ** np.linspace(np.log10(max(float(product[mask].min()), 1.0)),
                                np.log10(float(product[mask].max())), 35)
    counts, _, _ = np.histogram2d(truth[mask], product[mask],
                                  bins=[t_edges, p_edges])
    axis_a.pcolormesh(t_edges, p_edges, counts.T, cmap=CMAP_DENSITY,
                                shading="auto", rasterized=True,
                                norm=LogNorm(vmin=1.0, vmax=max(
                                    float(np.percentile(counts[counts > 0], 97)), 2.0)))
    hi = float(np.percentile(truth[mask], 99.0))
    axis_a.plot([0, hi], [0, hi], "--", color="#c53030", linewidth=0.7, label="1 : 1")
    slope, intercept = (float(value) for value in
                         np.polyfit(truth[mask], product[mask], 1))
    axis_a.plot([0, hi], slope * np.array([0.0, hi]) + intercept, "-",
                color="#1a202c", linewidth=0.7, label="OLS")
    axis_a.set_xlim(0, hi)
    axis_a.set_ylim(0, hi)
    axis_a.set_xlabel("Truth CWP (g m$^{-2}$)")
    axis_a.set_ylabel("Product CWP (g m$^{-2}$)")
    axis_a.grid(True, linewidth=0.3, color="0.88")
    bias = float(np.mean(product[mask] - truth[mask]))
    rmse = float(np.sqrt(np.mean((product[mask] - truth[mask]) ** 2)))
    r_value = float(np.corrcoef(truth[mask], product[mask])[0, 1])
    axis_a.text(0.05, 0.95, f"bias = {bias:+.1f} g m$^{{-2}}$\nRMSE = {rmse:.1f}\n"
                           f"r = {r_value:.3f}\ncolour: log number of cells",
                transform=axis_a.transAxes, va="top", fontsize=5.9)
    axis_a.legend(loc="lower right", fontsize=5.8)
    _panel(axis_a, "a", dx=-0.11)
    axis_a.set_title("Truth versus simulated product", fontsize=7.0, pad=2.5)

    # (b) 相对误差地图
    axis_b = _map_axes(figure, _rect(left + panel_w + gap, top_y, map_w,
                                     map_w / MAP_ASPECT, fig_w, fig_h),
                       grid, shade_alpha=0.12)
    limit = style.symmetric_log_limits(error, 98.0)
    mesh_b = _field_on_map(axis_b, grid, error, cmap=CMAP_BIAS,
                           norm=TwoSlopeNorm(vmin=-limit, vcenter=0.0, vmax=limit))
    _panel(axis_b, "b", dx=-0.13)
    axis_b.set_title("Relative error of CWP", fontsize=7.0, pad=2.5)

    # (c) 误差直方图
    axis_c = _axes(figure, _rect(left + 2 * (panel_w + gap), top_y, panel_w, 1.60,
                                 fig_w, fig_h))
    residual = product[mask] - truth[mask]
    axis_c.hist(residual, bins=46, color="#4a5568", linewidth=0)
    axis_c.set_yscale("log")
    axis_c.axvline(0, color="#c53030", linewidth=0.7)
    axis_c.set_xlabel("CWP error (g m$^{-2}$)")
    axis_c.set_ylabel("Grid cells")
    axis_c.text(0.95, 0.94, f"sigma = {float(np.std(residual)):.1f}\nbias = {bias:+.1f}",
                ha="right", va="top", transform=axis_c.transAxes, fontsize=5.9)
    _panel(axis_c, "c", dx=-0.11)
    axis_c.set_title("Error distribution", fontsize=7.0, pad=2.5)

    # (d) 分层相对误差
    axis_d = _axes(figure, _rect(left, 2.78, 3.10, 1.15, fig_w, fig_h))
    liquid_ratio = _level_relative_error(run.clwc_truth[time_index],
                                          run.clwc_product[time_index], grid.latitude)
    ice_ratio = _level_relative_error(run.ciwc_truth[time_index],
                                      run.ciwc_product[time_index], grid.latitude)
    axis_d.plot(liquid_ratio * 100, run.levels_hpa, color=style.COLORS["liquid"],
                linewidth=1.0, label="clwc")
    axis_d.plot(ice_ratio * 100, run.levels_hpa, color=style.COLORS["ice"],
                linewidth=1.0, label="ciwc")
    axis_d.axvline(0, color="0.35", linewidth=0.5)
    axis_d.set_ylim(run.levels_hpa.max(), run.levels_hpa.min())
    span = float(max(np.abs(liquid_ratio).max(), np.abs(ice_ratio).max()) * 100 * 1.6)
    axis_d.set_xlim(-span, span)
    axis_d.set_yticks([100, 200, 300, 400, 500, 600, 700, 850, 1000])
    axis_d.set_xlabel("Mean relative error (%)")
    axis_d.set_ylabel("Pressure (hPa)")
    axis_d.grid(True, linewidth=0.3, color="0.9")
    axis_d.legend(loc="lower left", fontsize=5.8)
    _panel(axis_d, "d", dx=-0.06)
    axis_d.set_title("Layered bias", fontsize=7.0, pad=2.5)

    # (e) 误差随量级变化
    axis_e = _axes(figure, _rect(left + 3.10 + gap, 2.78, 3.10, 1.15, fig_w, fig_h))
    edges = np.logspace(np.log10(max(truth[mask].min(), 1.0)),
                        np.log10(truth[mask].max()), 13)
    centers, means = [], []
    for low, high in zip(edges[:-1], edges[1:], strict=False):
        selection = (truth[mask] >= low) & (truth[mask] < high)
        if selection.sum() > 10:
            centers.append(float(np.sqrt(low * high)))
            means.append(float(np.mean(error[mask][selection])))
    axis_e.plot(centers, means, color="#1a202c", linewidth=0.9, marker="o",
                markersize=2.0)
    axis_e.axhline(0, color="0.35", linewidth=0.5)
    axis_e.set_xscale("log")
    axis_e.set_xlabel("Truth CWP (g m$^{-2}$)")
    axis_e.set_ylabel("Mean relative error (%)")
    axis_e.grid(True, linewidth=0.3, color="0.9")
    _panel(axis_e, "e", dx=-0.06)
    axis_e.set_title("Error growth with cloud-water amount", fontsize=7.0, pad=2.5)

    figure.suptitle("Figure 3 | Error structure of a simulated ERA5-like cloud-water "
                    "product", fontsize=8.2, y=0.975)

    figure.canvas.draw()
    _add_cbar(figure, axis_b, mesh_b, "Relative error (%)",
              ticks=[-int(limit), -int(limit / 2), 0, int(limit / 2), int(limit)])
    style.add_scale_note(figure,
                         "Synthetic data. The 'product' is the truth multiplied by correlated "
                         "log-normal noise (sigma = 0.26 for liquid, 0.34 for ice) plus a "
                         "-14 % systematic ice bias, used to test whether the figure language "
                         "can express error structure.")
    figure.savefig(path)
    plt.close(figure)
    return FigureSpec(name=path.name, path=path, title="error structure")


def _level_relative_error(truth: np.ndarray, product: np.ndarray,
                           latitude: np.ndarray) -> np.ndarray:
    """逐层相对误差（面积加权平均）。"""
    weight = np.broadcast_to(np.cos(np.deg2rad(latitude))[None, :, None], truth.shape)
    numerator = np.where(truth > 0, (product - truth) / np.maximum(truth, 1e-30), 0.0)
    denominator = np.where(truth > 0, 1.0, 0.0)
    num = (numerator * weight).sum(axis=(1, 2))
    den = (denominator * weight).sum(axis=(1, 2))
    return np.divide(num, den, out=np.zeros_like(num), where=den > 0)


# --------------------------------------------------------------------------- #
# 图 4：天气演变
# --------------------------------------------------------------------------- #
def figure_synoptic(run: SyntheticRun, *, path: Path,
                    boundary: np.ndarray | None = None) -> FigureSpec:
    grid = run.grid
    fig_w, fig_h = 7.09, 5.60
    figure = plt.figure(figsize=(fig_w, fig_h))
    left, gap_x = 0.45, 0.16
    map_w = 3.20
    map_h = map_w / MAP_ASPECT
    cwp = (run.lwp_truth + run.iwp_truth) * 1000.0
    vmax = float(np.percentile(cwp, 99))
    vmin = max(float(np.percentile(cwp[cwp > 0], 10)), 1.0)

    positions = [(left, 0.52), (left + map_w + gap_x, 0.52),
                 (left, 0.52 + map_h + 0.58), (left + map_w + gap_x, 0.52 + map_h + 0.58)]
    mesh = None
    for index, (x_in, y_in) in enumerate(positions):
        axis = _map_axes(figure, _rect(x_in, y_in, map_w, map_h, fig_w, fig_h), grid,
                         boundary=boundary if index == 0 else None,
                         shade_alpha=0.10, labels=(index in (0, 2)))
        mesh = _field_on_map(axis, grid, cwp[index], cmap=_log_cmap(CMAP_LIQUID),
                             norm=LogNorm(vmin=vmin, vmax=vmax))
        _panel(axis, "abcd"[index], dx=-0.06)
        axis.set_title(f"{int(run.times[index]):02d} UTC", fontsize=7.0, pad=2.0)

    figure.suptitle("Figure 4 | Cloud-water evolution during the passage of a mesoscale "
                    "convective system", fontsize=8.2, y=0.975)

    if mesh is not None:
        cax = figure.add_axes(_rect(left, fig_h - 0.55, 2.30, 0.13, fig_w, fig_h))
        colorbar = figure.colorbar(mesh, cax=cax, orientation="horizontal")
        colorbar.set_label("CWP (g m$^{-2}$)", fontsize=6.3, labelpad=2.0)
        colorbar.ax.tick_params(labelsize=5.8, length=2.0, width=0.45, direction="in")
        colorbar.outline.set_linewidth(0.45)

        def _log_formatter(value, _position):
            if value <= 0:
                return ""
            return f"$10^{{{round(np.log10(value))}}}$"

        colorbar.ax.yaxis.set_major_formatter(FuncFormatter(_log_formatter))
        colorbar.ax.yaxis.set_minor_formatter(NullFormatter())

    style.add_scale_note(figure, "Synthetic data. The convective cell travels from "
                                 "90 degE to 99 degE, superimposed on six random mesoscale "
                                 "clusters; all panels share one logarithmic colour scale.")
    figure.savefig(path)
    plt.close(figure)
    return FigureSpec(name=path.name, path=path, title="synoptic evolution")


# --------------------------------------------------------------------------- #
# 通用构件（真实数据链路复用同一套视觉语言）
# --------------------------------------------------------------------------- #
def grid_for(latitude: np.ndarray, longitude: np.ndarray) -> Grid:
    """按给定经纬网构造绘图用 Grid；外部 DEM 不可用时山体阴影置 None。"""
    shade = _hillshade_for(np.asarray(latitude), np.asarray(longitude))
    return Grid(latitude=np.asarray(latitude), longitude=np.asarray(longitude),
                elevation=np.zeros(np.size(latitude) * np.size(longitude)).reshape(
                    np.size(latitude), np.size(longitude)),
                shade=shade)


def _hillshade_for(latitude: np.ndarray, longitude: np.ndarray) -> np.ndarray | None:
    """取研究域山体阴影；外部数据卷不在时降级为无阴影（不报错）。"""
    try:
        from experiments.figure_studio.terrain import load_elevation

        grid = load_elevation()
    except (OSError, FileNotFoundError, ImportError):
        return None
    if grid.shape != (latitude.size, longitude.size):
        return None
    return grid.shade


def figure_map_field(latitude: np.ndarray, longitude: np.ndarray, values: np.ndarray,
                      *, path: Path, title: str, units: str, note: str,
                      cmap=None, seed: int = 0, label: str | None = None) -> FigureSpec:
    """单幅期刊规格场图：Albers 底图 + 山体阴影 + 对数色标 + 横向色标。"""
    from experiments.figure_studio.terrain import Grid

    shade = _hillshade_for(latitude, longitude)
    grid = Grid(latitude=latitude, longitude=longitude,
                elevation=np.zeros((latitude.size, longitude.size)),
                shade=shade if shade is not None else np.zeros(
                    (latitude.size, longitude.size)))
    fig_w, fig_h = 7.09, 3.65
    figure = plt.figure(figsize=(fig_w, fig_h))
    map_w = 4.60
    map_h = map_w / MAP_ASPECT
    x_in = (fig_w - map_w) / 2
    axis = _map_axes(figure, _rect(x_in, 0.52, map_w, map_h, fig_w, fig_h), grid,
                     shade_alpha=0.20, labels=True, shade=shade is not None)
    data = np.asarray(values, dtype="float64")
    positive = data[np.isfinite(data) & (data > 0)]
    if positive.size:
        vmin = max(float(np.percentile(positive, 5)), 1e-6)
        vmax = float(np.percentile(positive, 98))
        norm = LogNorm(vmin=vmin, vmax=max(vmax, vmin * 1.01))
    else:
        norm = None
    base = cmap if cmap is not None else CMAP_LIQUID
    finite = np.isfinite(data)
    positive = finite & (data > 0)
    positive_coverage = float(positive.sum()) / max(data.size, 1)
    if positive_coverage < 0.5:
        # 对数色标无法映射零值；正值格点少于一半时按格点画标记，避免把
        # 晴空零值经连续插值伪造为微弱云水。零值不是缺测，因此文案明确区分。
        lon_grid, lat_grid = np.meshgrid(longitude, latitude)
        mesh = axis.scatter(lon_grid[positive], lat_grid[positive], c=data[positive],
                            s=9.0, marker="s", cmap=_log_cmap(base), norm=norm,
                            linewidths=0.15, edgecolors="#ffffff", transform=PLATE,
                            zorder=3, rasterized=True)
        sparse_note = (f" {int(positive.sum())} of {data.size} grid cells contain positive "
                       "values; zero/clear-sky cells are left unmapped on the logarithmic "
                       "scale. Positive cells are shown as grid-cell markers, not interpolated.")
    else:
        mesh = _field_on_map(axis, grid, data, cmap=_log_cmap(base), norm=norm, seed=seed)
        sparse_note = ""
    if label:
        _panel(axis, label, dx=-0.09)
    figure.suptitle(title, fontsize=8.2, y=0.975)
    figure.canvas.draw()
    _add_cbar(figure, axis, mesh, units, log_ticks=norm is not None)
    terrain_note = (
        " Hillshade from GTOPO30."
        if shade is not None
        else " Hillshade unavailable; basemap-only fallback."
    )
    style.add_scale_note(figure, note + sparse_note + terrain_note)
    figure.savefig(path)
    plt.close(figure)
    return FigureSpec(name=path.name, path=path, title=title)


def figure_profile_panel(levels_hpa: np.ndarray, profiles: dict[str, dict[str, Any]],
                         *, path: Path, title: str, note: str) -> FigureSpec:
    """垂直廓线期刊图：多变量廓线 + P10–P90 带 + 坐标轴单位齐全。"""
    fig_w, fig_h = 7.09, 3.30
    figure = plt.figure(figsize=(fig_w, fig_h))
    axis = _axes(figure, _rect(0.95, 0.60, 4.20, 2.05, fig_w, fig_h))
    palette = {"clwc": style.COLORS["liquid"], "ciwc": style.COLORS["ice"]}
    labels = {"clwc": "clwc (liquid)", "ciwc": "ciwc (ice)"}
    peak = max(float(np.nanmax(np.asarray(profile["mean_mg_kg"], dtype="float64")))
               for profile in profiles.values())
    use_log = peak > 10.0
    for key, profile in profiles.items():
        values = np.asarray(profile["mean_mg_kg"], dtype="float64")
        color = palette.get(key, style.COLORS["neutral"])
        axis.plot(values, levels_hpa, color=color, linewidth=1.0,
                  label=labels.get(key, key))
        low = profile.get("p10_mg_kg")
        high = profile.get("p90_mg_kg")
        if low is not None and high is not None:
            low_values = np.asarray(low, dtype="float64")
            high_values = np.asarray(high, dtype="float64")
            floor = 1e-3 if use_log else 0.0
            axis.fill_betweenx(levels_hpa,
                               np.maximum(low_values, floor),
                               np.maximum(high_values, floor),
                               color=color, alpha=0.16, linewidth=0)
    if use_log:
        axis.set_xscale("log")
        axis.set_xlim(left=1e-3)
    else:
        axis.set_xlim(left=0.0)
        axis.set_xlim(right=max(peak * 1.35, 1e-6))
    axis.set_xlabel("Cloud water mixing ratio (mg kg$^{-1}$)")
    axis.set_ylabel("Pressure (hPa)")
    axis.set_ylim(float(levels_hpa.max()), float(levels_hpa.min()))
    axis.grid(True, linewidth=0.3, color="0.9")
    axis.legend(loc="best", fontsize=6.2)
    figure.suptitle(title, fontsize=8.2, y=0.975)
    style.add_scale_note(figure, note)
    figure.savefig(path)
    plt.close(figure)
    return FigureSpec(name=path.name, path=path, title=title)


def figure_relation_panel(lwp: np.ndarray, iwp: np.ndarray, *, path: Path,
                          title: str, note: str) -> FigureSpec:
    """LWP–IWP 关系期刊图：对数坐标 2D 直方图 + 1:1 线 + 统计量标注。"""
    fig_w, fig_h = 7.09, 3.45
    figure = plt.figure(figsize=(fig_w, fig_h))
    axis = _axes(figure, _rect(0.85, 0.62, 4.60, 2.15, fig_w, fig_h))
    lwp = np.asarray(lwp, dtype="float64")
    iwp = np.asarray(iwp, dtype="float64")
    mask = np.isfinite(lwp) & np.isfinite(iwp) & (lwp > 0) & (iwp > 0)
    if int(mask.sum()) >= 2:
        x_edges = 10 ** np.linspace(np.log10(float(lwp[mask].min())),
                                    np.log10(float(lwp[mask].max())), 40)
        y_edges = 10 ** np.linspace(np.log10(float(iwp[mask].min())),
                                    np.log10(float(iwp[mask].max())), 40)
        counts, _, _ = np.histogram2d(lwp[mask], iwp[mask], bins=[x_edges, y_edges])
        axis.pcolormesh(x_edges, y_edges, counts.T, cmap=CMAP_DENSITY,
                               shading="auto", rasterized=True,
                               norm=LogNorm(vmin=1.0, vmax=max(float(np.percentile(
                                   counts[counts > 0], 97)), 2.0)))
        axis.set_xscale("log")
        axis.set_yscale("log")
        axis.plot([float(lwp[mask].min()), float(lwp[mask].max())],
                  [float(iwp[mask].min()), float(iwp[mask].max())],
                  "--", color="#c53030", linewidth=0.7, label="1 : 1")
        r_value = float(np.corrcoef(np.log10(lwp[mask]), np.log10(iwp[mask]))[0, 1])
        axis.text(0.035, 0.95, f"log-log r = {r_value:.2f}\nn = {int(mask.sum())} cells",
                  transform=axis.transAxes, va="top", fontsize=6.2)
        axis.legend(loc="lower right", fontsize=6.2)
    axis.set_xlabel("LWP (g m$^{-2}$)")
    axis.set_ylabel("IWP (g m$^{-2}$)")
    axis.grid(True, which="major", linewidth=0.3, color="0.9")
    figure.suptitle(title, fontsize=8.2, y=0.975)
    style.add_scale_note(figure, note)
    figure.savefig(path)
    plt.close(figure)
    return FigureSpec(name=path.name, path=path, title=title)


def figure_identity_panel(items: list[tuple[str, float]], threshold: float, *,
                          path: Path, title: str, note: str) -> FigureSpec:
    """恒等式残差期刊图：对数柱状 + 阈值线 + 逐项数值标注。"""
    fig_w, fig_h = 7.09, 3.30
    figure = plt.figure(figsize=(fig_w, fig_h))
    axis = _axes(figure, _rect(0.95, 0.62, 4.60, 2.05, fig_w, fig_h))
    floor = 1e-18
    heights = [max(float(value), floor) if np.isfinite(value) else floor
               for _, value in items]
    positions = np.arange(len(items))
    colors = [style.COLORS["liquid"], style.COLORS["liquid"], style.COLORS["accent"],
              style.COLORS["bias"]]
    axis.bar(positions, heights, color=colors[:len(items)], width=0.6)
    axis.set_yscale("log")
    axis.set_ylim(1e-18, 1.0)
    axis.axhline(threshold, color="black", linestyle="--", linewidth=0.9,
                 label=f"threshold = {threshold:.0e}")
    axis.set_xticks(positions)
    axis.set_xticklabels([label for label, _ in items], fontsize=6.0)
    axis.set_ylabel("Relative residual (dimensionless, log scale)")
    axis.grid(True, axis="y", linewidth=0.3, color="0.9")
    axis.legend(loc="upper left", fontsize=6.2)
    for position, value, height in zip(positions, [v for _, v in items], heights,
                                       strict=True):
        text = "0 (below 1e-18)" if value <= 0 else f"{value:.1e}"
        axis.annotate(text, (position + 0.3, height * 1.6), ha="center", va="bottom",
                      fontsize=6.2, rotation=90)
    figure.suptitle(title, fontsize=8.2, y=0.975)
    style.add_scale_note(figure, note)
    figure.savefig(path)
    plt.close(figure)
    return FigureSpec(name=path.name, path=path, title=title)
