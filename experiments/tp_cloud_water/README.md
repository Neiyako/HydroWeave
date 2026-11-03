# 青藏高原云水资源代理实验

本实验把 Hydroweave 体系的四个环节落到一套代码上：**数学原理 → 经验公式 → EDA 与规律 → 误差分析**。
它只使用现有 ERA5 气压层 `t/q` 计算三个**代理指标**，并在文档与产物里全程标注代理边界。

## 一、三个指标的定义

| 指标 | 定义 | 回答什么 | 不能回答什么 |
|---|---|---|---|
| `PW` | `(1/g)∫q dp`，层界面取中点、梯形权重 | 水汽资源总量（资源上限） | 不是云水量 |
| `RH500` | 500 hPa 相对湿度，Magnus 水上式 | 中层成云潜势 | 潜势≠发生 |
| `CFRAC` | 100–500 hPa 内 RH≥阈值的有效层占比 | 云发生频率的阈值代理 | 数值随阈值变，必须连阈值引用 |

完整推导、常数来源与离散化取舍见[根 README 的数学原理一节](../../README.md#一数学原理)。

**当前卷提供 `t/q/u/v`，不含 `clwc/ciwc`、云水路径或总云量**，因此不能把结果解释为严格云水含量。
严格 GCWR 在本体系中判定为 **INSUFFICIENT_EVIDENCE**，不以 PW/RH 代理替代。

这是**模型层面的划分**：可算集由物理量需求决定，与数据何时到位无关。
本实验的职责是把可算的三量按 §1 的口径算准，并把不可算者的判据写清楚。

## 二、口径实现要点

这三条是实现里最容易出错、也最影响结论的地方：

1. **地形以下填充层必须剔除**。ERA5 把地形以下气压层用地面值填充且不带缺测标记，
   本实验按"自最底层起的等值连段"反推地面气压（`rtol=1e-3, atol=1e-6`，容差为 int16 打包标定），
   地面层及以下置 NaN。实测填充层占 **21.7%**，不剔除会让 PW 高估约五分之一。
   该判定同时免费给出 `surf_p`，供高程折算复用。
2. **面积加权用 cos φ**。窗口 25–40°N，算术平均会系统性高估高纬格点，量级足以淹没年际信号。
3. **CFRAC 的分母用有效层数**，不是 37 或总层数——地形掩膜后各格点剩余层数不同，
   分母选错会让高原腹地与边缘不可比。

实现位置：[`eda.py`](eda.py) 的 `trapezoid_weights` / `sub_ground_mask` / `compute_day`。

## 三、目录与配置

```text
experiments/tp_cloud_water/
├── config.yaml   # 唯一配置入口：catalog/卷/年份/区域/时次/阈值/输出/basemap
├── common.py     # 配置加载、catalog 输入索引、run 目录与 manifest 交互
├── eda.py        # 数学原理实现 + 分年计算，年度断点续跑
└── plot.py       # EDA 规律分析：剖面/高程分层/冰川对比/时序 + 写摘要
```

真实卷路径**只从 catalog 的 `volume_id` 解析**，不写死在代码里；`basemap_dir`
不在线时自动跳过底图，不影响其余图件。`config.yaml` 里的 `glacier_mask` 必须
与裁切后的 TP 网格同形（当前 120 个冰川格点，占窗口 1.4%）。

## 四、运行

`eda.py` 的 import 同时需要 `src`（`hydroweave` 包）与项目根（`experiments` 包），
所以 `PYTHONPATH` 要写成 `src:.`。输入侧只需要 catalog 数据库文件，
**不需要在本仓安装数据层主包**：

```bash
PYTHONPATH=src:. .venv/bin/python experiments/tp_cloud_water/eda.py \
  --config experiments/tp_cloud_water/config.yaml --run-id tp-2010-2013

PYTHONPATH=src:. .venv/bin/python experiments/tp_cloud_water/plot.py \
  --config experiments/tp_cloud_water/config.yaml --run-id tp-2010-2013
```

旧命令仍可用（薄包装，参数相同）：

```bash
.venv/bin/python scripts/analysis/tp_cloud_water_eda.py --years 2010 2011
.venv/bin/python scripts/analysis/tp_cloud_water_plot.py
```

`--run-id` 省略时取 `run-<配置哈希>`，EDA 与制图必须用同一个 run-id。

## 五、合成数据自检（不接触外接盘）

```bash
.venv/bin/python scripts/demo/make_tp_cloud_water_fixture.py /tmp/tp_fixture --days 3
PYTHONPATH=src:. .venv/bin/python -m experiments.tp_cloud_water.eda \
  --config /tmp/tp_fixture/config.yaml --run-id fixture
PYTHONPATH=src:. .venv/bin/python -m experiments.tp_cloud_water.plot \
  --config /tmp/tp_fixture/config.yaml --run-id fixture
```

合成数据复刻了 37 个气压层、纬度降序、地形以下等值填充和 mini catalog；
`tests/test_tp_cloud_water_experiment.py` 用同一 fixture 验证整条链路。
**合成数据只验机制，不验物理**——其数值无物理意义，不能进任何结论。

## 六、产物布局

```text
data/analysis/tp_cloud_water/runs/<run_id>/
├── manifest.json                        # 配置哈希/输入指纹/Git/包版本/产物指纹
├── yearly/tp_monthly_<year>.nc          # 月平均场（pw/rh500/cfrac/surf_p/rh_z）
├── tables/tp_daily_<year>.csv           # 逐日面积加权记录
├── tables/tp_monthly_<year>.csv         # 逐年逐月汇总
├── tables/tp_read_problems_<year>.csv   # 读取/计算失败清单（零失败为空文件）
├── tables/tp_daily.csv ...              # 全批次汇总（EDA 结束时重建）
├── figures/                             # 图件（plot.py 写出并登记指纹）
└── summary/tp_eda_summary.md            # EDA 摘要
```

产物分三层，用途不同，不要混读：

- **`yearly/*.nc`** 是**场**（month × lat × lon，以及 rh_z 的 month × level × lat）。做空间分析、
  重绘任意图件只依赖它，不需要重跑 EDA——这是本实验最昂贵的计算，必须可复用。
- **`tables/*.csv`** 是**标量序列**（逐日 736 行 / 逐年逐月）。做时间统计、年际对比只需读表，
  不必打开 NetCDF；`tp_read_problems_*.csv` 是零失败时留空的证据文件，**空≠缺失**。
- **`tables/tp_daily.csv` 等全批次文件在 EDA 结束时按已完成年份重建**，不是增量追加，
  因此续跑后不会出现重复行或字段错位。

`manifest.json` 位于三层之上，登记全部 28 个产物的 SHA-256。要判断"这份 run 是否完整"，
只需核对 manifest 的 `completed_years` 与 `failed_dates`，不必逐个打开产物。

## 七、规律分析产出的四条切面

| 切面 | 图件 | 判据 |
|---|---|---|
| 时间结构 | `fig_timeseries.png` | 15 日滑动平均后仍见天气尺度过程 |
| 空间形态 | `fig_maps_<year>.png`、`fig_annual_comparison.png` | 跨年同一色标，1–99% 分位定界 |
| 垂直结构 | `fig_crosssection.png` | RH=80% 等值线 + 地形顶轮廓，地形以下不画 |
| 冰川/高程 | `fig_glacier_elevation.png` | RGI 冰川格点 vs 其余；500 m 分层，每档 ≥30 格点 |

实测结论（2010–2013 暖季）：**冰川区 PW 仅约高原整体的三分之一**（9 mm vs 24 mm），
四年稳定；PW 与 CFRAC 同步在 7–8 月达峰，RH500 峰值更早更平缓。
详见[根 README 的规律总结](../../README.md#35-汇总20102013-暖季实测多年平均)。

## 八、断点续跑与一致性

- 年度结果先写 `.part`、落盘后原子替换，manifest 记录每个产物的 SHA-256。
- 同一 `--run-id` 重跑会跳过 manifest 中已完成的年份，只补未完成年份；
  `--force` 才重算已有年度，并允许配置/输入指纹变化（会覆盖同 run 目录）。
- 配置哈希或输入指纹（卷 ID、相对路径、大小、mtime）变化时，同 run-id 直接
  报错，避免把两套配置的产物混在一个目录；换 `--run-id` 或 `--force`。
- `plot.py` 只画已完成年份，并把图件/摘要指纹登记回 manifest。
- 某年即使有个别日期读取/计算失败，只要年度产物写出仍会记入 `completed_years`，
  失败明细在 `tables/tp_read_problems_<year>.csv`（manifest 的 `failed_dates`
  汇总）。要重算这一年并重试失败日期，用 `--force`；否则续跑会跳过它。

## 九、误差分析与验收

误差分三类，混在一起说没有意义：

- **数值误差**（可精确度量）：独立手工重算 4 个单柱，相对误差 **0.0000%**；新旧实现 16 组 diff = 0；
- **口径误差**（影响最大）：地形填充层 21.7% ⇒ 不剔除则 PW 高估约 1/5；Magnus 水上式 ⇒ 高空 RH 偏低；
- **代理误差**（方向已知、不可标定）：代理量与真实云水的偏差**方向**可定（PW 高估、RH/CFRAC 偏低），
  因此相对差异可引用、绝对量级读作上/下限；连方向都给不出的量（GCWR）才判 INSUFFICIENT_EVIDENCE。

误差分析的完成态不是"把误差降到零"，而是**说清方向与结论成立范围**——这一条已做到。

两条入口：

```bash
# 真实卷 pytest（外接盘不在线时自动 skip）
.venv/bin/python -m pytest -m real -q

# 独立验收报告（绕开实验代码重算，避免自证）
.venv/bin/python scripts/dev/validate_real_eda.py
```

`scripts/dev/validate_real_eda.py` 的六条硬标准**执行前固定在脚本 `STANDARDS` 里**：
S1 catalog 与盘上文件一致；S2 每年 5–10 月 184 天且 q/t 成对；S3 12 个抽样日物理量在合理量级；
S4 4 个单柱 PW 独立重算相对误差 ≤0.5%；S5 与旧实现产物逐比特一致；S6 manifest/736 行逐日表/8 张图/摘要齐全。
判定只有 PASS / CONDITIONAL_PASS / FAIL。**2026-11-03 实测：六项全 PASS**，
独立重算相对误差 0.0000%，4 年 × 4 变量 max abs diff = 0。

**验收覆盖不到的**（均属本仓实现与验证手段的已知局限，已声明不掩盖）：
S5 证明新旧实现等价但共用同一物理口径，不证明口径正确——口径判定落在误差方向分析上；
12 个抽样日未覆盖全部 736 天；只读挂载未测损坏文件。

## 十、复现边界

`manifest.json` 的输入指纹是 catalog 的逻辑指纹，不是全量 SHA-256；需要比特级
归档证据时，先用 `./bin/dbas checksum --volume <id>` 分批生成 catalog 校验和。
实验只读原始数据，输出写入 `data/analysis`。若外接卷不在线，真实 EDA 不能宣称
完成；可以先用合成数据验证目录、清单和恢复逻辑。
