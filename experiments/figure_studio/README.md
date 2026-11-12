# figure_studio · 期刊级图件工作台

用**仿真数据**渲染期刊规格（Nature 双栏 180 mm）的青藏高原云水图件，
目的是把「制图方案」与「真实数据」解耦：先在已知真值、已知误差结构的场上
把版式、配色、投影、配色标规则定死，再把同一套渲染器接到真实 ERA5 clwc/ciwc 上。

> **数据性质**：本模块产出的图**不是观测结果**。场由解析大气廓线 + 真实
> GTOPO30 地形 + 季风水汽/地形抬升/中尺度对流构造；「产品」场是真值叠加
> 相关对数正态噪声与冰相系统偏差。所有图的脚注都写明了这一点。

## 模块

| 文件 | 职责 |
|---|---|
| `terrain.py` | GTOPO30 高程子集（0.25°）、0.05° 山体阴影、青藏边界与省界 |
| `synth.py` | 合成 clwc/ciwc：地面气压 → 环境温度 → 相态分割 → LWP/IWP → 含噪产品 |
| `style.py` | Nature 风格基线：字体、线宽、脊线、面板字母、横向色标 |
| `figures.py` | 四张成图：空间结构 / 垂直结构 / 误差结构 / 天气演变 |

## 出图

```bash
PYTHONPATH=. python scripts/analysis/figure_studio_demo.py --run-id sim-20240715
# → data/analysis/figure_studio/<run_id>/{fig1..fig4}.png + fields.nc + summary.json
```

| 图 | 面板 |
|---|---|
| Figure 1 | a 地形与高原范围 · b LWP 场 · c IWP 场 · d LWP–IWP 联合分布 · e LWP–地形关系 |
| Figure 2 | a 域平均垂直廓线（P10–P90）· b 云相态占比 · c 30°N 剖面（CWP + 地形） |
| Figure 3 | a 真值 vs 产品 · b CWP 相对误差空间分布 · c 误差分布 · d 分层偏差 · e 误差随云水量增长 |
| Figure 4 | 4 个时次的 CWP 场（中尺度对流系统过境） |

## 渲染层的三个关键处理（决定了「像不像期刊图」）

1. **投影与底图**：Albers 等积圆锥（95°E，25°/47°N 标准纬线），
   Natural Earth 50m 海岸线/河流/湖泊/国界 + 1:4M 省界 + 3000 m 等高线。
2. **去马赛克**：0.25° 物理场 → 线性插值到 0.025° → 高斯平滑 → 叠加极弱分形纹理
   （幅度随场值衰减，近零区不加纹理）→ 研究域矩形边界用 alpha 渐隐溶进底图。
3. **色标语言**：cmcrameri 感知均匀色表（batlow/roma/vik），对数色标，
   横向色标贴在面板正下方，面板字母为粗体小写。

## 依赖

```bash
pip install -e ".[dev]"   # cartopy + cmcrameri 已在主依赖里
```
