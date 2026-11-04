# 真实 ERA5 clwc/ciwc 云水柱含量验证（cloud_water_strict）

> **状态：三端 e2e 已完成（PASS）**。最终 run：`real-catalog-20240101`，输入来自
> DBAS catalog（`volume_id=downloads`、`dataset_id=era5_cloud_water`），输入 sha256
> 与 RDH 交付清单、DBAS 落盘文件三方一致。
>
> **数据来源如实标注**：本次数据由 **RDH 重放通道**交付（`plan=plan-36f331c13fd1237f`、
> `delivery=delivery-e448aa88fd0d4f35`）；RDH 的传输、完整性校验与交付链路是真实的；
> **CDS 生成阶段因服务端队列阻塞未重新提交**，详见三端 e2e 报告
> `/Users/apple/Desktop/era5数据dbas/data/reports/e2e/real-catalog-20240101/e2e.md`。
> 本次交付为**单时次 canary 文件**（2024-01-01 00Z，`n_times=1`），不是 31 个时次的
> 月度样本；多时次快照统计本次不适用（代码已支持，见 §3 末）。
>
> 对照 run：interim 本地真实文件 `real-interim-20240101`（`catalog_imported=false`）保留，
> 二者输入内容相同（sha256 一致），用于证明“catalog 路径与本地文件路径结果一致”。

## 1. 结论（五态判定，最终 run）

| 检查项 | 判定 | 证据 |
|---|---|---|
| 式 (20)(21)(22) GCWR 三式恒等 | **PASS** | 三式均 1.800000e+12 kg；spread 0.0 kg；相对残差 0.0 ≤ 1e-12；负控制 7.217e-04（可检出 0.1% 偏置） |
| 柱积分梯形权重（常数场解析解） | **PASS** | 0.203943242596 vs 0.203943242596 kg·m⁻²，相对误差 0.0 |
| clwc/ciwc 变量·单位·坐标口径 | **PASS** | 两变量单位 `kg kg**-1`（×1.0）；气压层 `hPa`×100→Pa；区域 25–40°N/70–105°E，61×141 |
| partial_column 标记与覆盖厚度 | **PASS** | 覆盖 300–500 hPa（200 hPa，名义 1–1000 hPa 的 20.0%），`partial_column=true`，未外推 |
| 区域平均 LWP/IWP 量级 vs 文献/ERA5 气候态 | **INSUFFICIENT_EVIDENCE** | LWP 0.113 g·m⁻² 低于整列文献量级带下界 1 g·m⁻²；IWP 2.180 g·m⁻² 在带内（CONDITIONAL_PASS） |
| GCWR 收支闭合（式 30/31/32） | **NOT_RUN** | 缺 P、E、u/v 边界通量与长时段库存变化 |
| 年度/气候态尺度结论 | **NOT_RUN** | 单时次快照，不能外推年尺度云水资源量/趋势 |

**总体：INSUFFICIENT_EVIDENCE。** 即：代数实现、柱积分权重、单位与部分列口径全部
通过；但“真实云水量级是否与气候态一致”这一物理结论**尚未被该样本证明**。
不得因为“算出了数字”就报 PASS（论文本身也强调式 (20)(21)(22) 是算术恒等式，
不构成物理检验）。

## 2. 数据与可追溯性

| 项 | 值 |
|---|---|
| 最终 run | `real-catalog-20240101` |
| 文件（catalog 内） | `era5_cloud_water/canary_clwc_ciwc.nc` |
| 卷 / 数据集 | `downloads` / `era5_cloud_water`（`source_mode=catalog`，`catalog_imported=true`） |
| catalog | `/Users/apple/Desktop/era5数据dbas/data/catalog.db` |
| 落盘路径 | `/Users/apple/Desktop/era5数据dbas/data/downloads/era5_cloud_water/canary_clwc_ciwc.nc` |
| sha256 / 大小 | `d1b96325daa20adf342f60002a2d654ec41e9a835eee5a4acecea3ba6ab4cc39` / 45855 B |
| 时次 / 区域 / 网格 | 2024-01-01 00 UTC，`n_times=1`（canary）；25–40°N，70–105°E；0.25°，61×141 |
| 气压层 | 500/400/300 hPa（3 层，仅部分列） |
| 校验链 | RDH 交付清单 sha256 = DBAS 落盘文件 sha256 = Hydroweave `inputs.json` sha256（三者一致，e2e 报告 `sha256_all_match=True`、`input_sha256_chain=True`） |

| 对照 run | 输入模式 | 输入 sha256 | 说明 |
|---|---|---|---|
| `real-interim-20240101` | `local_override`（`catalog_imported=false`） | `d1b96325…4cc39` | interim 本地真实文件；与最终 run 内容相同、结果逐位一致 |
| `real-catalog-20240101` | `catalog`（`catalog_imported=true`） | `d1b96325…4cc39` | 三端 e2e 最终路径（本文结论以此为准） |

合成 fixture（`scripts/demo/make_clwc_fixture.py`）只验证链路、单位/权重/部分列口径与
可复现机制，其数字无物理意义；对应 run-id=`fixture`。

## 3. 方法

- 连续定义：LWP = ∫(clwc/g)dp，IWP = ∫(ciwc/g)dp，单位 kg·m⁻²，g = 9.80665 m·s⁻²。
- 离散化：相邻气压层梯形权重 0.5·(qₖ+qₖ₊₁)·Δp/g；3 层样本 → 2 个区间，
  总厚度 200 hPa。
- **不做顶层/底层外推**：只积分数据实际覆盖区间；覆盖小于名义整列（1–1000 hPa）时
  强制 `partial_column=true`，并输出覆盖层、厚度与占比。
- 区域平均：cosφ 面积权重，w(φ)=cosφ/Σcosφ（非等权平均）。
- 缺测：NaN 不当作 0；任一端点缺测的区间使该格点柱含量为 NaN。
- 时次口径：逐格点场、剖面与五态判定**只用 `config.time.index` 指定的一个时次**
  （本次即 2024-01-01 00Z）；若输入文件含多个时次，`report.md §4.1` 会另列
  **逐时次快照范围**，并明确标注“不是时间平均场、不替代单时次口径”。本次交付
  `n_times=1`，故无该节。

## 4. 结果

| 指标 | LWP | IWP |
|---|---:|---:|
| 区域平均 | 0.113 g·m⁻² | 2.180 g·m⁻² |
| 中位数 | 0.000 | 0.000 |
| P10 / P90 | 0.000 / 0.000 | 0.000 / 5.106 |
| 最小 / 最大 | 0.000 / 84.727 | 0.000 / 70.322 |
| 有效格点 | 8601/8601 | 8601/8601 |

逐层区域平均（mg·kg⁻¹，300/400/500 hPa）：clwc = 0.000/0.001/0.219；
ciwc = 0.968/1.557/0.194。逐格点场与剖面见 run 目录 `fields.nc`。

**独立重算（对抗性检查）**：直接读原始 NetCDF，手工按升序气压层做梯形积分
（0.5·(qₖ+qₖ₊₁)·Δp/g）与 cosφ 加权，得到 LWP = 0.11281350695698966 g·m⁻²、
IWP = 2.180179644668646 g·m⁻²，与 `stats.json` 逐位一致（相对差 < 1e-15）；
最大格点 LWP = 84.72707276888084、IWP = 70.32225480171817 g·m⁻² 亦一致。

> 冬季中层（300–500 hPa）液态云水极少、冰云为主，是 LWP 均值远低于整列气候态的
> 物理原因；这正是“部分列不能当整列”的直接例证。

## 5. 为什么不是 PASS / 不是 FAIL

- **不能 PASS**：单时次 + 部分列 + 冬季中层，无法与整列/月尺度气候态做等价比较；
  量级核对只能给 CONDITIONAL_PASS / INSUFFICIENT_EVIDENCE，且 NOT_RUN 项不得冒充通过。
- **不能 FAIL**：柱积分、单位、cosφ 加权、部分列标记均通过独立解析/恒等式检验；
  低 LWP 有明确物理与覆盖解释，不是数值口径错误。
- LWP 低于文献带下界的解释：文献值（如高原西部月 44–92 g·m⁻²、九龙整层 102–665 g·m⁻²）
  是**整列**量级；本样本只覆盖 300–500 hPa（名义整列的 20%），且冬季中层液水近零。

## 6. NOT_RUN（明确未运行，不是通过）

1. GCWR 收支闭合（式 30/31/32）：缺降水 P、地面蒸发 E、边界通量 u/v 的同一控制体累计量，
   以及更长时段的库存变化。
2. 年度/气候态结论：本次仅单时次 canary 样本，缺多年逐日/逐月与季节循环。
3. 多时次/月度快照统计：本次交付 `n_times=1`，不适用；代码已支持多时次逐时次快照
   （report.md §4.1），但必须与单时次口径分开，且不能替代气候态结论。
4. 与文献逐格点气候态定量比对：缺同区域/同季节/同层的文献格点场与完整气压柱。

## 7. 复现命令

```bash
cd /Users/apple/Desktop/Hydroweave

# 0) 环境（无 .venv 时）
uv venv --python 3.13 .venv
.venv/bin/python -m pip install pytest ruff numpy pandas xarray netCDF4 matplotlib pyyaml pyshp dask flox

# 1) 离线 fixture：合成卷 → 计算 → 出图 → 五态报告
.venv/bin/python scripts/demo/make_clwc_fixture.py /tmp/cw_fixture
PYTHONPATH=src:. .venv/bin/python -m experiments.cloud_water_strict.compute \
  --config /tmp/cw_fixture/config.yaml --run-id fixture
PYTHONPATH=src:. .venv/bin/python -m experiments.cloud_water_strict.plot \
  --config /tmp/cw_fixture/config.yaml --run-id fixture
PYTHONPATH=src:. .venv/bin/python -m experiments.cloud_water_strict.verify \
  --config /tmp/cw_fixture/config.yaml --run-id fixture

# 2) 最终 catalog run（本页结论；先由 DBAS 导入 volume=downloads / dataset=era5_cloud_water）
PYTHONPATH=src:. .venv/bin/python -m experiments.cloud_water_strict.compute \
  --config experiments/cloud_water_strict/config.yaml --run-id real-catalog-20240101
PYTHONPATH=src:. .venv/bin/python -m experiments.cloud_water_strict.plot \
  --config experiments/cloud_water_strict/config.yaml --run-id real-catalog-20240101
PYTHONPATH=src:. .venv/bin/python -m experiments.cloud_water_strict.verify \
  --config experiments/cloud_water_strict/config.yaml --run-id real-catalog-20240101

# 3) interim 对照（可选，保留历史证据）
PYTHONPATH=src:. .venv/bin/python -m experiments.cloud_water_strict.compute \
  --config experiments/cloud_water_strict/config.yaml \
  --input-file /Users/apple/Desktop/era5数据dbas/data/downloads/reanalysis-era5-pressure-levels/202401_multi.nc \
  --run-id real-interim-20240101

# 4) 门禁
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check experiments tests scripts
```

## 8. 产物与复现机制

最终 run 目录：`data/analysis/cloud_water_strict/runs/real-catalog-20240101/`；
interim 对照：`data/analysis/cloud_water_strict/runs/real-interim-20240101/`。

| 文件 | 内容 |
|---|---|
| `fields.nc` | 逐格点 LWP/IWP（kg·m⁻²）+ 逐层 clwc/ciwc 区域平均 |
| `stats.json` | 区域统计、覆盖/部分列元数据、单位换算、时间与输入 sha256 |
| `inputs.json` | catalog 记录 + 每文件 sha256（e2e 的 sha256 链核对用） |
| `identity_check.json` | 式 (20)(21)(22) 三式值、spread、相对残差、负控制 |
| `fig_lwp_field.png` / `fig_iwp_field.png` | LWP/IWP 场（g·m⁻²，标题含部分列说明） |
| `fig_vertical_profile.png` | clwc/ciwc 垂直剖面（均值 + P10–P90） |
| `fig_lwp_iwp_relation.png` | 逐格点 LWP–IWP 关系（log-log，1:1 线，相关系数） |
| `fig_identity_residual.png` | 恒等式相对残差面板（对数刻度，1e-12 阈值） |
| `report.md` / `summary.json` | 五态判定表 + 证据 + 机器可读摘要 |
| `manifest.json` | 配置哈希、输入指纹、Git revision、包版本、全部产物 sha256 |

产物一律“先写临时文件再原子替换”；同 run-id 的配置或输入指纹变化会直接报错，
防止两套口径混放。

## 9. 文献来源

- 韦成强, 赵鹏国 (2025) 青藏高原及其临近区域云特性及云垂直结构分布特征.
  成都信息工程大学学报 40(5): 643-651.
  [PDF](http://xb.cuit.edu.cn/oa/pdfdow.aspx?Sid=202505011)（已下载并抽取正文：
  高原西部 LWP 月 44–92 g·m⁻²、IWP 155/63 g·m⁻²；四川盆地 LWP 150–200 g·m⁻²）
- 徐桂荣等 (2024) 青藏高原东侧九龙夏季非降水云的观测特征. 暴雨灾害 43(2): 135-145.
  [PDF](http://www.byzh.org.cn/cn/article/pdf/preview/10.12406/byzh.2023-148.pdf)
  （已抽取摘要：九龙夏季非降水云 LWP 整层均值 0.433 kg·m⁻²，高云 0.102、低云 0.665）
- Li Wentao et al. (2018) Climatic Characteristic Analysis of Cloud Water over the Tibetan
  Plateau. Climatic and Environmental Research 23(5): 574-586.
  [摘要](https://www.iapjournals.ac.cn/qhhj/en/article/doi/10.3878/j.issn.1006-9585.2018.18039)
- Copernicus Climate Data Store: ERA5 total column cloud liquid water.
  [变量页](https://eqc.climate.copernicus.eu/node/1325)
  （柱云水量 = clwc/ciwc 整层积分，单位 kg·m⁻²）

## 10. 与现有 `tp_cloud_water` 的关系

`experiments/tp_cloud_water` 只做 t/q 代理指标（PW/RH500/CFRAC），README 已明确
GCWR=INSUFFICIENT_EVIDENCE（缺 clwc/ciwc）；本实验不改动其任何文件，新增的
`experiments/cloud_water_strict/` 直接消费真实 clwc/ciwc，把“代理指标”升级为
“真实云水柱含量 + 部分列显式口径”。两者结论不可互相替代。

## 11. 门禁与仓库边界（2026-11-04）

- `.venv/bin/python -m pytest`：**49 passed, 9 skipped**（新增
  `tests/test_cloud_water_strict.py` 11 例全过；9 个 skip 是既有的真实外接盘用例）。
- `.venv/bin/python -m ruff check experiments tests scripts`：**All checks passed**。
- 未做 git commit；未修改 `experiments/tp_cloud_water/` 任何现有文件
  （`git status` 仅显示新增路径）。
- 三端 e2e：`PASS`（①②③④ 全部 PASS，sha256 链一致，图件 5 张），
  报告 `/Users/apple/Desktop/era5数据dbas/data/reports/e2e/real-catalog-20240101/e2e.md`。
- 新增写作用域：`experiments/cloud_water_strict/`、`scripts/demo/make_clwc_fixture.py`、
  `tests/test_cloud_water_strict.py`、本页。
