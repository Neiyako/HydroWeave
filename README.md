<div align="center">

# 🌀 Hydroweave

**青藏高原云水资源实验体系**

把「云水有多少、在哪、怎么变、能信到什么程度」变成可计算、可证伪的模型

[![CI](https://github.com/Neiyako/HydroWeave/actions/workflows/ci.yml/badge.svg)](https://github.com/Neiyako/HydroWeave/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Code style: ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

[**中文**](README.md) · [English](README.en.md) · [📘 上手文档](docs/ONBOARDING.md) · [📐 设计说明](docs/DESIGN.md)

</div>

---

## 📖 这是什么

**Hydroweave 是一套为青藏高原云水资源课题自行设计的实验体系。**

它把一个模糊的科学问题——「高原上到底有多少云水」——拆成可独立检验的实验环节，每一环都给出
**数学定义、经验公式、误差边界与实证结论**，并用统一的运行清单保证结论可复现。

> **一句话定位：Hydroweave 负责把云水资源问题变成可计算、可证伪的模型，并交付图与误差边界。**

### 为什么需要它

严格的云水资源评估需要云液水 `clwc`、云冰水 `ciwc` 等变量，而常用 ERA5 气压层数据只提供
`t / q / u / v`。面对这个约束有两条错误路径：

| ❌ 错误做法 | 后果 |
|---|---|
| 用可降水量（PW）冒充云水 | 系统性高估数十倍，结论作废 |
| 把「等数据」写进开发计划 | 项目停摆，且掩盖了本已能算的部分 |

Hydroweave 取第三条路：**先声明代理（proxy），再把代理算准，并把边界写清楚**——
同时把严格模型完整实现好，等数据到位即可接上。

---

## ✨ 特性

| | 特性 | 说明 |
|---|---|---|
| 🧮 | **公式可追溯** | 每个物理量都有明确的数学定义与离散化方式，公式编号可反查代码与文献来源 |
| 🎯 | **三层误差分析** | 数值误差 / 口径误差 / 代理误差分开量化，不笼统报「误差 5%」 |
| 🧪 | **独立重算验收** | 绕开实验代码，用另一条路径重算，单柱 PW 相对误差 **0.0000%** |
| 🔁 | **比特级可复现** | 同一配置 + 同一输入 ⇒ 同一产物，manifest 记录每个产物 SHA-256 |
| 🗺️ | **8 类制图** | 空间场、剖面、高程分层、冰川对比、时间序列，含底图与投影校正 |
| 🛡️ | **可证伪优先** | 误差连方向都给不出时，报 `INSUFFICIENT_EVIDENCE` 而不是报一个数 |
| ⚙️ | **CI 守护** | GitHub Actions 三层验证：lint + 多版本测试 + 合成链路端到端 |

---

## 🧭 体系结构：五个环节，一条证据链

```text
① 数学原理        物理量怎么定义、积分怎么离散化、掩膜怎么判定   → eda.py
      ▼
② 经验公式        本套数据的约束下，哪些量可算、哪些只能取代理   → 代理边界
      ▼
③ EDA 与规律分析  分年/分月/冰川-非冰川/高程分层，从场到结论     → eda.py + plot.py
      ▼
④ 误差分析        数值误差、口径误差、代理误差三层拆开算          → validate_real_eda.py
      ▼
⑤ 可复现契约      同一配置 + 同一输入 ⇒ 同一产物                 → repro/manifest.py
```

**为什么是这五个环节**：科研结论失效，绝大多数不是算错，而是**口径没定义清、误差没量化、复现没锁住**。
五个环节分别堵住这三类失效——①②固定「我在算什么」，④量化「我错多少」，⑤保证「别人能重算出同样的数」。

### 两条并行的技术路线

```text
路线 A（数据到位即可跑）：代理指标链
    ERA5 t/q  →  PW / RH500 / CFRAC  →  EDA 规律  →  8 类图件
                 ↑ 已实现，已在 2010–2013 真实卷上验收

路线 B（模型已就绪，等云水数据）：收支模型链
    各水分项  →  收支方程  →  GCWR / 效率 / 更新周期  →  误差预算
                 ↑ 已实现，已用论文数值回归，纯代数层不依赖数据
```

两条路线共享同一套口径约定（单位链、层序、地形掩膜、面积加权），
云水数据到位时路线 B 只需**替换输入**，不改模型结构。

---

## 🛠️ 技术栈

本项目以 **Python (≥3.11)** 实现，面向科学计算与可复现研究：

<p>
<img alt="Python" src="https://img.shields.io/badge/Python-3776AB?style=flat-square&logo=python&logoColor=white">
<img alt="NumPy" src="https://img.shields.io/badge/NumPy-013243?style=flat-square&logo=numpy&logoColor=white">
<img alt="Pandas" src="https://img.shields.io/badge/Pandas-150458?style=flat-square&logo=pandas&logoColor=white">
<img alt="xarray" src="https://img.shields.io/badge/xarray-2F4F4F?style=flat-square">
<img alt="Dask" src="https://img.shields.io/badge/Dask-FC6E6B?style=flat-square">
<img alt="Matplotlib" src="https://img.shields.io/badge/Matplotlib-11557C?style=flat-square">
</p>

| 功能组 | 技术选型 | 承担职责 |
|---|---|---|
| **数值计算** | `numpy` `xarray` `pandas` | 多维数组运算、标注数据、表格处理 |
| **气象数据 I/O** | `netCDF4` `xarray` | ERA5 气压层 NetCDF 读写、坐标与单位解析 |
| **分块并发** | `dask[array]` `flox` | 2 TB 数据卷按 10 天一批流式处理，不全量进内存 |
| **科学制图** | `matplotlib` `pyshp` | 空间场、剖面、色标、底图与投影校正 |
| **配置与契约** | `PyYAML` `hashlib` | 唯一配置入口、配置哈希、产物 SHA-256 指纹 |
| **质量保障** | `pytest` `ruff` `GitHub Actions` | 47 个测试用例、静态检查、三层 CI |

**工程约定**

- 数据按 **10 天一批、2 线程**流式处理，内存占用与数据卷大小解耦
- 全部实验口径由单一 `config.yaml` 决定，代码中无机器专属路径
- 产物先写 `.part` 再原子替换，支持断点续跑与失败日期落账

---

## 📦 项目结构

```text
Hydroweave/
│
├── README.md                    中文说明（本文件）
├── README.en.md                 English documentation
├── CHANGELOG.md                 版本变更记录（Keep a Changelog 格式）
├── CONTRIBUTING.md              贡献指南
├── CODE_OF_CONDUCT.md           行为准则
├── CITATION.cff                 学术引用信息
├── pyproject.toml               依赖声明 + ruff + pytest 配置
├── LICENSE                      MIT
│
├── docs/
│   ├── ONBOARDING.md            📘 上手文档：公式总账、误差分析、实验规范、绘图规范
│   ├── DESIGN.md                📐 设计说明：每个口径"为什么这样取"、实测结论
│   └── img/                     文档配图
│
├── experiments/tp_cloud_water/  核心实验代码（「算什么」）
│   ├── config.yaml              ⭐ 唯一配置入口（区域/年份/层带/阈值/时次）
│   ├── eda.py                   代理指标：柱积分、RH、地形掩膜、面积加权、断点续跑
│   ├── budget.py                收支模型：式(1)-(32) 的代数实现，含 GCWR
│   ├── error_analysis.py        GCWR 误差：一阶传播、口径因子、误差预算、判定
│   ├── plot.py                  8 类图件：空间场、剖面、高程、冰川对比、时间序列
│   └── common.py                配置加载、catalog 索引、run 目录与 manifest 交互
│
├── src/hydroweave/repro/        可复现契约（「凭什么可信」）
│   └── manifest.py              配置哈希 / 输入指纹 / 原子写 / 产物 SHA-256
│
├── scripts/
│   ├── demo/make_tp_cloud_water_fixture.py   合成试验台生成器（不依赖外接盘）
│   ├── dev/validate_real_eda.py              🔍 独立验收（对抗性，十条硬标准）
│   └── analysis/                             实验命令行的薄包装
│
├── tests/                       47 个用例
│   ├── test_cloud_water_budget.py            收支代数与误差分析（26）
│   ├── test_repro_manifest.py                运行清单机制（9）
│   ├── test_tp_cloud_water_experiment.py     合成链路端到端（3）
│   └── test_tp_cloud_water_real.py           真实卷契约（9，需外接盘）
│
├── .github/
│   ├── workflows/ci.yml         GitHub Actions：lint + test + repro
│   ├── ISSUE_TEMPLATE/          Issue 模板（Bug / 科学问题 / 功能建议）
│   └── PULL_REQUEST_TEMPLATE.md
│
└── data/                        实验产物（不入 Git，由 manifest 记录）
    └── analysis/tp_cloud_water/runs/<run_id>/
        ├── yearly/              月平均场 NetCDF
        ├── tables/              逐日表、逐月表、读取问题清单
        ├── figures/             8 类图件
        ├── summary/             EDA 摘要
        └── manifest.json        运行清单
```

**读目录时把握一条分界**：`experiments/` 放「算什么」，`src/hydroweave/repro/` 放「凭什么可信」，
`scripts/dev/` 放「谁来验」。三者分离是为了让验证方不依赖被验证方——
`validate_real_eda.py` 刻意**不复用** `eda.py` 的计算函数。

---

## 🚀 快速开始

### 1. 安装

```bash
git clone https://github.com/Neiyako/HydroWeave.git
cd HydroWeave
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
```

### 2. 合成数据自检（推荐！不需要 2 TB 外接卷）

```bash
# ① 生成自包含合成试验台（含 catalog、冰川掩膜、配置）
python3 scripts/demo/make_tp_cloud_water_fixture.py /tmp/tp_fixture --days 3

# ② 跑 EDA：输出逐日表、月平均场、manifest
PYTHONPATH=src:. .venv/bin/python -m experiments.tp_cloud_water.eda \
    --config /tmp/tp_fixture/config.yaml --run-id fixture

# ③ 跑制图：输出 8 类图件 + EDA 摘要
PYTHONPATH=src:. .venv/bin/python -m experiments.tp_cloud_water.plot \
    --config /tmp/tp_fixture/config.yaml --run-id fixture
```

> 合成数据的数字**没有物理意义**，它验证的是目录结构、清单机制、断点续跑与绘图链路。

### 3. 真实卷运行

需要外接 ERA5 卷在线，且 catalog 已由数据层 DBAS 登记（本仓只读消费）。

```bash
PYTHONPATH=src:. .venv/bin/python experiments/tp_cloud_water/eda.py \
    --config experiments/tp_cloud_water/config.yaml --run-id tp-2010-2013

PYTHONPATH=src:. .venv/bin/python experiments/tp_cloud_water/plot.py \
    --config experiments/tp_cloud_water/config.yaml --run-id tp-2010-2013
```

⚠️ **EDA 与制图必须使用同一个 `--run-id`**，否则图会配错场。

### 4. 收支模型（不依赖任何数据）

```python
from experiments.tp_cloud_water import budget as B, error_analysis as E

t = B.BudgetTerms(
    qv_init=2.03e14, qv_final=2.03e14,      # 水汽初/终值 (kg)
    qh_init=1.14e13, qh_final=1.14e13,      # 水凝物初/终值
    qv_in=2.05e16, qv_out=2.05e16,          # 水汽边界输入/输出
    qh_in=2.1e15, qh_out=1.9e15,            # 水凝物边界输入/输出
    rain_kg=6.58e15, duration_s=365 * B.SECONDS_PER_DAY,
)

rep = B.evaluate(t)                                              # 全部指标一张表
chk = B.sanity_check(rep)                                        # 量级体检
sig = E.summarize(rep, E.TermSigma(qh_final=2e9, qh_out=1e9))    # 误差预算 + 判定

print(f"GCWR = {rep['gcwr_kg']:.3e} kg")
print(f"Tv = {rep['Tv_days']:.1f} 天, Th = {rep['Th_hours']:.1f} 小时")
print(f"判定: {sig['verdict']}, 主导误差: {sig['dominant_source']}")
```

**顺序不能颠倒**：先 `evaluate` 验 S7–S10 恒等式，再看误差区间，最后才谈结论。

---

## 🧮 核心公式概览

> 完整的符号约定、代码位置与来源依据见 [📘 上手文档 §2](docs/ONBOARDING.md)。

### 路线 A：代理指标（现有数据可算）

```text
可降水量    PW = (1/g) ∫ q dp ≈ Σ_i q_i · w_i / g          [mm]
相对湿度    RH = 100 · e / e_s,  e = p·q/(0.622+q),  e_s 用 Magnus 水面式
云频率代理  CFRAC = n(RH≥80% 的层) / n(有效层)
地形掩膜    |q[i+1] − q[i]| ≤ atol + rtol·|q[i]|     自最底层向上找等值连段
面积加权    W(φ) = cos φ / Σ cos φ
```

### 路线 B：收支模型（依据蔡淼博士论文第 2 章）

```text
收支方程    Qv,终 − Qv,初 = Qv,入 − Qv,出 + 蒸发 − 净凝结        (1)
            Qh,终 − Qh,初 = Qh,入 − Qh,出 − 降水 + 净凝结        (2)
            Qm,终 − Qm,初 = Qm,入 − Qm,出 + 蒸发 − 降水          (3)

核心指标    GCWR = GQh − 降水                                     (20)
                 = Qh,终 + Qh,出                                  (21)
                 = Qh,初 + Qh,入 + C_net − 降水                   (22)

效率周期    Em = 降水/GQm,  Eh = 降水/GQh,  P = 总凝结/GQv        (17)(18)
            Tv = Qv,平均/(降水/T),  Th = Qh,平均/(降水/T)        (19)
```

### ⚠️ 两个必须知道的陷阱

| 陷阱 | 后果 | 正确做法 |
|---|---|---|
| 式(16) `GQm = GQv + GQh` 只对**瞬时库存**成立 | 累计量下重复计入净凝结，实测**高估约 60%** | `GQm = GQv + GQh − C_net`，且走式(15)独立核算 |
| 地形以下填充层无缺测标记 | 填充层占 **21.7%**，不掩膜则 PW 高估约 1/5 | 等值连段判定，自最底层向上找地面层 |

---

## 📊 误差分析

误差必须**分层拆开**，混在一起报「误差 5%」没有信息量。

### 三层误差

| 层级 | 来源 | 量化方式 | 实测 |
|---|---|---|---|
| **① 数值误差** | 积分离散、实现、对齐 | 独立重算对照 | 相对误差 **0.0000%** |
| **② 口径误差** | 地形填充、相态、时次、阈值 | 方向 + 量级 | 填充层 **21.7%** |
| **③ 代理误差** | 代理 ≠ 真实物理量 | 方向已知，界定适用范围 | 单向偏低/高估 |

### GCWR 的一阶误差传播

GCWR 是分项的**线性组合**，因此一阶（高斯）传播**精确成立**：

```text
GCWR = Qh,终 + Qh,出
∂GCWR/∂Qh,终 = 1,  ∂GCWR/∂Qh,出 = 1,  其余偏导 = 0
σ²_GCWR = σ²(Qh,终) + σ²(Qh,出)
```

> 💡 **反直觉但关键**：降水、初值、边界输入的观测误差对 GCWR **一阶无影响**
> （在反算中被吸收或抵消）。所以**改进降水观测不会降低 GCWR 的不确定度**，
> 只能靠测准水凝物场末值与边界输出。这条结论直接决定后续攻关优先级。

### 判定标准（先定后用）

| 相对 1σ | 判定 | 含义 |
|---|---|---|
| < 20% | `CONCLUSIVE` | 可支撑定量结论 |
| 20% – 50% | `CONDITIONAL` | 只支撑相对/定性结论 |
| ≥ 50% | `INSUFFICIENT_EVIDENCE` | 只能报区间，不能断言大小 |

### 十条验收标准

| 编号 | 标准 | 实测 |
|---|---|---|
| S1–S2 | catalog 文件齐全、每年 184 天 q/t 成对 | PASS（736 天） |
| S3 | 抽样日物理量在量级内 | PASS |
| S4 | 独立手工重算单柱 PW，相对误差 ≤0.5% | PASS（**0.0000%**） |
| S5 | 与旧实现产物逐比特一致 | PASS（max abs diff = 0） |
| S6 | manifest、逐日表、图件、摘要齐全 | PASS |
| S7–S10 | GCWR 三式一致、`GQm` 不误加、库存关系、边界通量分解 | 单元测试锁死 |

**最终判定：PASS**（2026-11-03 实测）

---

## 🗺️ 图件示例

### 年际对比（同一色标）

![年际对比](docs/img/fig_annual_comparison.png)

### 冰川 vs 非冰川 + 高程分层

![冰川与高程](docs/img/fig_glacier_elevation.png)

### 经向–气压剖面

![经向剖面](docs/img/fig_crosssection.png)

### 逐日时间序列

![时间序列](docs/img/fig_timeseries.png)

**绘图规范**：固定三色板、色标跨年共用、1%–99% 分位定界、`aspect=1/cos φ` 投影校正、
冰川金色叠加、地形以下不画、DPI 130。

---

## ✅ 已得到的结论

> 来自 2010–2013 真实卷（736 天暖季），按证据强度分级。

### 直接可用：暖季多年平均

| 月份 | PW (mm) | 冰川区 PW (mm) | RH500 (%) | CFRAC (%) |
|---|---|---|---|---|
| 5 月 | 16.6 | 5.9 | 47.0 | 2.6 |
| 6 月 | 24.9 | 8.8 | 59.9 | 5.3 |
| 7 月 | 31.7 | 12.3 | 68.3 | 7.9 |
| 8 月 | 30.9 | 13.2 | 67.1 | 6.9 |
| 9 月 | 24.3 | 9.1 | 57.3 | 4.7 |
| 10 月 | 14.2 | 4.4 | 39.7 | 1.7 |

**三条规律（按证据强度）**

1. **季节形态单峰、峰值在盛夏** — *数据事实*。PW 与 CFRAC 同步在 7–8 月达峰；
   「吻合」不等于「因果」，因果需等收支与环流诊断。
2. **CFRAC 量级小、年际稳定（4.7–5.0%）** — *数据事实*。因 RH 被单向压低，
   绝对值应读作**下限**；仅 4 年样本，**不足以支持趋势判断**。
3. **冰川区 PW 只有高原整体的约 1/3**（9 mm vs 24 mm）— *观察事实，机制待验*。
   这与「冰川区 = 水汽富集区」的朴素直觉相反，且四年方向稳定。
   候选解释尚未经收支分析证实——**水汽来源不能由 PW 场直接推断**。

### 尚未成立

**GCWR：`INSUFFICIENT_EVIDENCE`** —— 本卷缺 `clwc/ciwc`，水凝物三维场无法构造。
模型已就绪，数据到位即可接上。

---

## 🧪 测试与 CI

### 本地验证

```bash
PYTHONPATH=src:. python3 -m pytest -q                    # 38 passed, 9 skipped
PYTHONPATH=src:. python3 -m pytest -m real -q            # 真实卷（不在线则 skip）
python3 scripts/dev/validate_real_eda.py                 # 对抗性验收（需外接盘）
ruff check .                                             # 代码质量
```

**三条命令验证不同层次，不能互相替代**：

| 命令 | 验证什么 | 通过不代表 |
|---|---|---|
| `pytest -q` | 代码机制没坏 | ❌ 物理正确 |
| `pytest -m real` | 真实数据契约成立 | ❌ 结论可信 |
| `validate_real_eda.py` | 结论经得起重算 | — |

### GitHub Actions

[`.github/workflows/ci.yml`](.github/workflows/ci.yml) 三个 job：

| Job | 内容 | 触发 |
|---|---|---|
| **Lint** | `ruff check` 静态检查（规则集见 `pyproject.toml`） | push / PR |
| **Test** | Python 3.11 & 3.12 矩阵，47 个用例 | push / PR |
| **Repro** | 合成链路端到端：fixture → EDA → 绘图 → manifest 指纹校验 | push / PR |

CI 中**不运行**真实卷测试（需 2 TB 外接盘），`-m real` 会自动 skip 并显式记录为 **NOT_RUN**——
**跳过不等于通过**。

---

## 🤝 贡献

欢迎提交 Issue 与 Pull Request！

- 详细流程见 [CONTRIBUTING.md](CONTRIBUTING.md)
- 参与即表示同意遵守 [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)
- **对科学结论的质疑是最受欢迎的反馈** —— 请用 [科学问题模板](https://github.com/Neiyako/HydroWeave/issues/new/choose) 并附上推导

提交前请确保：

```bash
ruff check .                             # 静态检查通过
PYTHONPATH=src:. python3 -m pytest -q     # 测试通过
```

新增实验请遵循 [📘 上手文档 §4.6](docs/ONBOARDING.md) 的标准动作：
配置加参数 → 实现口径并注明公式来源 → 补单元测试（含反例）→ 跑合成链路 → 跑真实卷 → 补文档。

**代码规范**：单文件单职责；`experiments/` 放「算什么」，`repro/` 放「凭什么可信」，`dev/` 放「谁来验」；
不允许为让方程闭合而静默改数据。

---

## 📚 参考文献

1. **蔡淼**. 中国空中云水资源和降水效率的评估研究 [D]. 学位论文.
   *本仓收支模型（式 1–32）的主要依据，对应第 2 章。*
2. **李颖, 苏凤阁, 汤秋鸿, 等**. 青藏高原主要流域的降水水汽来源 [J]. 中国科学: 地球科学, 2022, 52(7): 1328–1344.
   [DOI: 10.1360/SSTe-2021-0217](https://doi.org/10.1360/SSTe-2021-0217)
   *水汽来源追踪，与 GCWR 属不同框架，不代入收支公式。*

---

## 📌 引用

如果 Hydroweave 对你的研究有帮助，请引用：

```bibtex
@software{hydroweave2026,
  title   = {Hydroweave: A Tibetan Plateau Cloud Water Resources Toolkit},
  author  = {Neiyako},
  year    = {2026},
  version = {1.0.0},
  url     = {https://github.com/Neiyako/HydroWeave},
  license = {MIT}
}
```

引用格式由 [CITATION.cff](CITATION.cff) 提供，GitHub 会自动生成 APA / BibTeX。
若引用了具体的收支模型公式，请同时引用上文参考文献 1。

---

## ⚖️ 边界与免责

**本仓负责**：数学模型的建立与实现、代码计算、误差分析、绘图出图。

**本仓不负责**：数据获取与补齐（属数据侧）、比特级数据校验、水汽来源追踪。

**数据**：原始 ERA5 数据不随本仓分发，仅以只读方式引用本地卷。
复现实验需自备同源数据卷，数据许可遵循发布方条款。

**结论使用**：`GCWR` 是云水资源的**粗估**，其中仅一部分具备人工增雨开发条件，
**不等于可开发水资源**。引用绝对量级时请连同误差区间与阈值条件一起引用。

---

## 📄 许可

[MIT License](LICENSE) © 2026 qiu-yuyi

<div align="center">

**[⬆ 回到顶部](#-hydroweave)** · [📘 上手文档](docs/ONBOARDING.md) · [English](README.en.md)

</div>
