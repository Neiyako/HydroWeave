#!/usr/bin/env python3
"""Publication-style plots for the three-year NCAR GCWR experiment."""
from __future__ import annotations

import calendar
import hashlib
import json
import os
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import numpy as np
import xarray as xr

ROOT = Path(__file__).resolve().parents[1]
HW = Path(os.environ.get('HYDROWEAVE_ROOT', '/Users/apple/Desktop/Hydroweave'))
import sys
if str(HW) not in sys.path:
    sys.path.insert(0, str(HW))

from experiments.figure_studio import figures, style  # noqa: E402

style.use_nature_style()
YEARS = (2012, 2015, 2019)
SPECIES = ('clwc', 'ciwc', 'crwc', 'cswc', 'qh')
LABELS = {
    'clwc': 'cloud liquid water', 'ciwc': 'cloud ice water',
    'crwc': 'rain water', 'cswc': 'snow water', 'qh': 'total cloud water',
}
COLORS = {'2012': '#2b6cb0', '2015': '#c05621', '2019': '#2f855a'}


def _annual_mean_maps(year: int) -> tuple[np.ndarray, np.ndarray, dict[str, np.ndarray]]:
    path = ROOT / 'annual' / f'{year:04d}_fields.nc'
    with xr.open_dataset(path) as ds:
        lat = ds.latitude.values.astype('float64')
        lon = ds.longitude.values.astype('float64')
        month = ds.month.values.astype(int)
        days = np.array([calendar.monthrange(year, int(m))[1] for m in month], dtype='float64')
        weights = days / days.sum()
        out = {}
        for s in SPECIES:
            arr = ds[f'{s}_col'].values.astype('float64')
            out[s] = np.sum(arr * weights[:, None, None], axis=0)
        profiles = {}
        for s in SPECIES:
            arr = ds[f'{s}_profile'].values.astype('float64')
            profiles[s] = np.sum(arr * weights[:, None], axis=0)
        level = ds.level.values.astype('float64')
    return lat, lon, out | {'profiles': profiles, 'level': level}


def _area_weights(lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    return np.broadcast_to(np.cos(np.deg2rad(lat))[:, None], (lat.size, lon.size))


def _map_axis(fig, rect, lat, lon):
    from experiments.figure_studio.terrain import Grid

    grid = Grid(latitude=lat, longitude=lon,
                elevation=np.zeros((lat.size, lon.size)),
                shade=np.zeros((lat.size, lon.size)))
    axis = fig.add_axes(rect, projection=figures.PROJECTION)
    figures.decorate_map_axis(axis, grid, shade=False, labels=True)
    return axis


def _shared_map_figure(year_data, species: str, path: Path):
    lat, lon = year_data[YEARS[0]][:2]
    positive = np.concatenate([
        year_data[y][2][species][np.isfinite(year_data[y][2][species]) &
                              (year_data[y][2][species] > 0)].ravel()
        for y in YEARS
    ]) * 1000.0
    if positive.size:
        vmin = max(float(np.percentile(positive, 5)), 1e-4)
        vmax = max(float(np.percentile(positive, 98)), vmin * 1.01)
        norm = mcolors.LogNorm(vmin=vmin, vmax=vmax)
    else:
        norm = None
    fig = plt.figure(figsize=(7.09, 2.85))
    rects = [[0.08, 0.42, 0.24, 0.40], [0.38, 0.42, 0.24, 0.40], [0.68, 0.42, 0.24, 0.40]]
    axes = []
    mesh = None
    cmap = figures.CMAP_LIQUID if species in ('clwc', 'qh') else (
        figures.CMAP_ICE if species in ('ciwc', 'cswc') else figures.CMAP_TERRAIN)
    data_cmap = plt.get_cmap(cmap).copy()
    data_cmap.set_bad((1, 1, 1, 0))
    for i, year in enumerate(YEARS):
        ax = _map_axis(fig, rects[i], lat, lon)
        values = year_data[year][2][species] * 1000.0
        masked = np.ma.masked_where(~np.isfinite(values) | (values <= 0), values)
        mesh = ax.pcolormesh(lon, lat, masked, transform=figures.PLATE,
                             cmap=data_cmap, norm=norm, shading='auto', rasterized=True)
        ax.set_title(str(year), fontsize=7.5, pad=2)
        figures._panel(ax, chr(ord('a') + i), dx=-0.14)
        axes.append(ax)
    fig.suptitle(f'ERA5 annual mean {LABELS[species]} path (g m$^{{-2}}$)',
                 fontsize=8.2, y=0.965)
    fig.canvas.draw()
    cbar = fig.colorbar(mesh, ax=axes, orientation='horizontal', fraction=0.035,
                        pad=0.08, shrink=0.72)
    cbar.set_label(f'{LABELS[species].title()} path (g m$^{{-2}}$)', fontsize=6.5)
    cbar.ax.tick_params(labelsize=6.0, length=2, width=0.4)
    style.add_scale_note(
        fig,
        'NSF NCAR RDA d633000: 4 synoptic times/day, all days of the year; '
        'Qh = clwc + ciwc + crwc + cswc. Zero cells are transparent on the log scale. '
        'No CDS download.'
    )
    fig.savefig(path, dpi=600, bbox_inches='tight')
    plt.close(fig)


def _seasonal_plot(year_data, path: Path):
    fig, axes = plt.subplots(2, 2, figsize=(7.09, 4.2))
    months = np.arange(1, 13)
    for ax, s in zip(axes.ravel(), ('clwc', 'ciwc', 'crwc', 'cswc')):
        for year in YEARS:
            # Re-open monthly series; process_month saves monthly means only through annual fields,
            # so use the annual file's month axis directly here.
            with xr.open_dataset(ROOT / 'annual' / f'{year:04d}_fields.nc') as ds:
                area = _area_weights(ds.latitude.values.astype('float64'),
                                     ds.longitude.values.astype('float64'))
                f = ds[f'{s}_col'].values.astype('float64')
                vals = np.array([np.nansum(f[i] * area) / np.nansum(area) for i in range(12)])
            ax.plot(months, vals * 1000.0, marker='o', ms=2.3, lw=1.0,
                    color=COLORS[str(year)], label=str(year))
        ax.set_title(LABELS[s].title(), fontsize=7.5)
        ax.set_xlabel('Month (UTC)')
        ax.set_ylabel('Column mass (g m$^{-2}$)')
        ax.set_xticks(range(1, 13, 2))
        ax.grid(True, linewidth=0.3, alpha=0.5)
    axes[0, 0].legend(loc='best', fontsize=6)
    fig.suptitle('Seasonal cycle of atmospheric liquid and solid water', fontsize=8.2)
    fig.tight_layout(rect=(0, 0.04, 1, 0.95))
    style.add_scale_note(fig, 'All 12 months of each year; four synoptic times per day; '
                              'area-weighted over 25–40°N, 70–105°E.')
    fig.savefig(path, dpi=600, bbox_inches='tight')
    plt.close(fig)


def _profiles_plot(year_data, path: Path):
    fig, axes = plt.subplots(2, 2, figsize=(7.09, 4.4))
    level = year_data[YEARS[0]][2]['level']
    for ax, s in zip(axes.ravel(), ('clwc', 'ciwc', 'crwc', 'cswc')):
        for year in YEARS:
            vals = year_data[year][2]['profiles'][s] * 1e6
            ax.plot(np.maximum(vals, 1e-5), level, lw=1.0,
                    color=COLORS[str(year)], label=str(year))
        ax.set_yscale('log')
        ax.set_ylim(1000, 1)
        ax.set_xscale('log')
        ax.set_xlabel('Mixing ratio (mg kg$^{-1}$)')
        ax.set_ylabel('Pressure (hPa)')
        ax.set_title(LABELS[s].title(), fontsize=7.5)
        ax.grid(True, linewidth=0.3, alpha=0.5)
    axes[0, 0].legend(loc='best', fontsize=6)
    fig.suptitle('Annual mean vertical structure of liquid and solid water', fontsize=8.2)
    fig.tight_layout(rect=(0, 0.04, 1, 0.95))
    style.add_scale_note(fig, 'Domain-mean profiles; 37 pressure levels; '
                              'pressure-layer mass excludes below-surface layers without extrapolation.')
    fig.savefig(path, dpi=600, bbox_inches='tight')
    plt.close(fig)


def _anomaly_plot(year_data, path: Path):
    lat, lon = year_data[YEARS[0]][:2]
    qh = np.stack([year_data[y][2]['qh'] for y in YEARS])
    mean = np.nanmean(qh, axis=0)
    lim = max(float(np.nanpercentile(np.abs(qh - mean), 98)) * 1000.0, 1e-6)
    norm = mcolors.TwoSlopeNorm(vmin=-lim, vcenter=0.0, vmax=lim)
    fig = plt.figure(figsize=(7.09, 2.85))
    rects = [[0.08, 0.42, 0.24, 0.40], [0.38, 0.42, 0.24, 0.40], [0.68, 0.42, 0.24, 0.40]]
    axes, mesh = [], None
    for i, year in enumerate(YEARS):
        ax = _map_axis(fig, rects[i], lat, lon)
        values = (qh[i] - mean) * 1000.0
        mesh = ax.pcolormesh(lon, lat, values, transform=figures.PLATE,
                             cmap=figures.CMAP_BIAS, norm=norm, shading='auto')
        ax.set_title(str(year), fontsize=7.5, pad=2)
        figures._panel(ax, chr(ord('a') + i), dx=-0.14)
        axes.append(ax)
    fig.suptitle('Total cloud-water anomaly relative to the three-year mean', fontsize=8.2, y=0.965)
    fig.canvas.draw()
    cbar = fig.colorbar(mesh, ax=axes, orientation='horizontal', fraction=0.035,
                        pad=0.08, shrink=0.72)
    cbar.set_label('Qh anomaly (g m$^{-2}$)', fontsize=6.5)
    style.add_scale_note(fig, 'Anomaly = year mean − three-year mean; '
                              'same 25–40°N, 70–105°E control volume.')
    fig.savefig(path, dpi=600, bbox_inches='tight')
    plt.close(fig)


def _budget_plot(summaries, path: Path):
    years = list(summaries)
    g = np.array([summaries[y]['evaluation']['gcwr_kg'] / 1e12 for y in years])
    p = np.array([summaries[y]['terms_kg']['rain_kg'] / 1e12 for y in years])
    gqh = np.array([summaries[y]['evaluation']['GQh_kg'] / 1e12 for y in years])
    fig, (a, b) = plt.subplots(1, 2, figsize=(7.09, 2.9))
    x = np.arange(len(years))
    width = 0.25
    a.bar(x - width, gqh, width, color='#90cdf4', label='GQh')
    a.bar(x, p, width, color='#f6ad55', label='Precipitation')
    a.bar(x + width, g, width, color='#2f855a', label='GCWR')
    a.set_xticks(x, [str(y) for y in years])
    a.set_ylabel('Mass (10$^{12}$ kg)')
    a.set_title('Annual water budget', fontsize=7.5)
    a.legend(fontsize=6, ncol=1)
    a.grid(axis='y', linewidth=0.3, alpha=0.5)
    eh = [summaries[y]['evaluation']['Eh'] for y in years]
    tv = [summaries[y]['evaluation']['Tv_days'] for y in years]
    b.plot(x, eh, marker='o', color='#2f855a', label='Eh')
    b.set_ylabel('Precipitation efficiency Eh', color='#2f855a')
    b.set_ylim(0, 1)
    b2 = b.twinx()
    b2.plot(x, tv, marker='s', color='#2b6cb0', label='Tv')
    b2.set_ylabel('Water-vapour renewal (days)', color='#2b6cb0')
    b.set_xticks(x, [str(y) for y in years])
    b.set_title('Efficiency and renewal', fontsize=7.5)
    b.grid(axis='y', linewidth=0.3, alpha=0.5)
    fig.tight_layout(rect=(0, 0.04, 1, 0.94))
    style.add_scale_note(fig, 'Physical GCWR = Qh,terminal + Qh,out; '
                              'the three algebraic GCWR expressions are cross-checked in the report.')
    fig.savefig(path, dpi=600, bbox_inches='tight')
    plt.close(fig)


def _residual_plot(summaries, path: Path):
    years = list(summaries)
    names = ('eps_h', 'eps_v', 'eps_m')
    labels = ('hydrometeor', 'vapour', 'total water')
    fig, ax = plt.subplots(figsize=(7.09, 2.8))
    x = np.arange(len(years)); width = 0.22
    for i, (name, label) in enumerate(zip(names, labels)):
        vals = [max(abs(summaries[y]['residuals_kg'][name]), 1e-12) for y in years]
        ax.bar(x + (i - 1) * width, vals, width, label=label)
    ax.set_yscale('log')
    ax.set_xticks(x, [str(y) for y in years])
    ax.set_ylabel('|residual| (kg)')
    ax.set_title('Physical budget closure residuals', fontsize=7.5)
    ax.legend(fontsize=6)
    ax.grid(axis='y', linewidth=0.3, alpha=0.5)
    fig.tight_layout(rect=(0, 0.04, 1, 0.95))
    style.add_scale_note(fig, 'Residuals are computed from the same control volume and period; '
                              'zero is not claimed when data or covariance is missing.')
    fig.savefig(path, dpi=600, bbox_inches='tight')
    plt.close(fig)


def main():
    out = ROOT / 'figures'
    out.mkdir(parents=True, exist_ok=True)
    year_data = {y: _annual_mean_maps(y) for y in YEARS}
    for s in SPECIES:
        _shared_map_figure(year_data, s, out / f'fig01_{s}_annual_mean.png')
    _seasonal_plot(year_data, out / 'fig02_seasonal_cycle.png')
    _profiles_plot(year_data, out / 'fig03_vertical_profiles.png')
    _anomaly_plot(year_data, out / 'fig04_qh_anomaly.png')
    summaries = {y: json.loads((ROOT / 'annual' / f'{y:04d}_budget.json').read_text())
                 for y in YEARS}
    _budget_plot(summaries, out / 'fig05_gcwr_budget.png')
    _residual_plot(summaries, out / 'fig06_residuals.png')
    lines = []
    for p in sorted(out.glob('*.png')):
        lines.append(f'{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}')
    (out / 'SHA256SUMS.txt').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(json.dumps({'figures': [p.name for p in sorted(out.glob('*.png'))]}, ensure_ascii=False))


if __name__ == '__main__':
    main()
