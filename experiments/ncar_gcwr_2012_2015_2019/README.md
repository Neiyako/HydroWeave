# NCAR ERA5 GCWR three-year experiment

青藏高原（25–40°N，70–105°E）2012、2015、2019 三个年份、共 36 个月的 ERA5
大气水物质收支与 GCWR 可复现实验。数据只来自 NSF NCAR GDEX/RDA
`d633000`/`d633001`，不经过 CDS。

## 科学口径

- 空间范围：25–40°N，70–105°E，0.25° 规则经纬网格。
- 垂直范围：37 个气压层，1–1000 hPa；低于地表的层按实际地面气压屏蔽，不外推。
- 时间采样：每天 00/06/12/18 UTC 四个时次；月度场为日平均，月收支按完整月长累计。
- 云水定义：`Qh = clwc + ciwc + crwc + cswc`。
- 年度更新周期：逐月 `(start+end)/2` 库存按月份天数加权，再除以年降水率。

## 目录

| 路径 | 内容 |
|---|---|
| `scripts/fetch_month.py` | 通过 RDH 获取单月 NCAR 切片并导入 DBAS |
| `scripts/process_month.py` | 单位校验、垂直积分、边界通量和月收支 |
| `scripts/audit_outputs.py` | 36 个月的科学与文件完整性审计 |
| `scripts/assemble_year.py` | 年度收支、时间加权更新周期和年度场 |
| `scripts/plot_results.py` | 年度空间场、季节循环、廓线、异常和收支图 |
| `scripts/final_acceptance.py` | 最终 36/36、年度、图件和哈希门禁 |
| `monthly/`、`annual/`、`figures/` | 本地产物，不进入版本库 |

## 依赖

默认使用以下本地仓库；可通过环境变量覆盖路径：

- `RDH_ROOT`（默认 `~/Desktop/ResearchDataHub`）
- `DBAS_ROOT`（默认 `~/Desktop/era5数据dbas`）
- `HYDROWEAVE_ROOT`（默认 `~/Desktop/Hydroweave`）

## 运行

```bash
cd /Users/apple/Desktop/绘图/ncar_gcwr_2012_2015_2019

# 单月断点续跑（建议并发 8，16 并发曾在 NCAR 慢响应下触发连接池重试）
PYTHONPATH="$RDH_ROOT/src:$DBAS_ROOT/src:scripts" \
  python scripts/run_months.py --year 2012 --months 12 --workers 8

# 最终链路
python scripts/audit_outputs.py
python scripts/assemble_year.py --year 2012
python scripts/assemble_year.py --year 2015
python scripts/assemble_year.py --year 2019
python scripts/plot_results.py
python scripts/final_acceptance.py
```

完整三年的本地编排入口是 `scripts/run_all.py`。所有完成状态以 `audit_outputs.py` 和
`final_acceptance.py` 的审计结果为准，不以文件是否存在或 RDH 单次运行计数为准。

## 结果

最终证据见 `evidence/final_acceptance.json`，结果解读见 `RESULTS_REPORT.md`。
数据完整性为 **36/36 月 PASS**；科学解释边界为 **CONDITIONAL_PASS**，原因是
2012、2019 年的 `Th` 略低于全国参照区间下限 1 h，不能据此推断长期气候态或趋势。
