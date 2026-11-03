# 贡献指南

感谢你对 Hydroweave 的关注！本项目是一套面向青藏高原云水资源研究的实验体系，
**可复现与可证伪**是它的核心价值。提交前请读完本文。

---

## 目录

- [行为准则](#行为准则)
- [开始之前](#开始之前)
- [开发环境](#开发环境)
- [提交前检查](#提交前检查)
- [新增实验的标准动作](#新增实验的标准动作)
- [代码规范](#代码规范)
- [提交信息规范](#提交信息规范)
- [报告问题](#报告问题)
- [提交 Pull Request](#提交-pull-request)

---

## 行为准则

参与本项目即表示你同意遵守 [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)。

---

## 开始之前

请先阅读：

| 文档 | 用途 |
|---|---|
| [README.md](README.md) | 项目定位、技术栈、项目结构 |
| [docs/ONBOARDING.md](docs/ONBOARDING.md) | 公式总账、误差分析、实验与绘图规范 |
| [docs/DESIGN.md](docs/DESIGN.md) | 每个数学口径「为什么这样取」 |

**理解项目的核心主张**：本仓不追求「算出一个数」，而是追求「说清这个数能信到什么程度」。
因此，**声明边界**与**实现功能**同样重要，甚至更重要。

---

## 开发环境

```bash
git clone https://github.com/Neiyako/HydroWeave.git
cd HydroWeave
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'

# 验证环境（不需要 2 TB 外接数据卷）
python3 scripts/demo/make_tp_cloud_water_fixture.py /tmp/tp_fixture --days 3
PYTHONPATH=src:. .venv/bin/python -m experiments.tp_cloud_water.eda \
    --config /tmp/tp_fixture/config.yaml --run-id dev
PYTHONPATH=src:. .venv/bin/python -m experiments.tp_cloud_water.plot \
    --config /tmp/tp_fixture/config.yaml --run-id dev
```

需要 Python ≥ 3.11。

---

## 提交前检查

**三项都必须通过**：

```bash
ruff check .                              # 静态检查
PYTHONPATH=src:. python3 -m pytest -q     # 全部测试（真实卷测试自动 skip）
```

CI 会额外跑 Python 3.11 / 3.12 矩阵与合成链路端到端自检，任一项失败将阻止合并。

> 真实 ERA5 卷测试（`-m real`）需要 2 TB 外接数据卷，CI 中不运行。
> 若你修改了真实卷相关逻辑，请在本地跑 `python3 scripts/dev/validate_real_eda.py` 并在 PR 中说明结果。

---

## 新增实验的标准动作

**顺序不可颠倒**：

1. **加配置**：在 `experiments/tp_cloud_water/config.yaml` 加参数，不硬编码
2. **实现口径**：在 `eda.py` / `budget.py` 实现，**注明公式编号与文献来源**
3. **补测试**：在 `tests/` 加单元测试，必须包含边界情况与**反例**
4. **跑合成链路**：确认产物与 manifest 正常
5. **跑真实卷**：更新验收标准，运行 `validate_real_eda.py`
6. **补文档**：在 `docs/DESIGN.md` 与 `docs/ONBOARDING.md` 对应章节写清公式与理由

### 硬性要求

- ❌ **不允许**为让方程闭合而静默修改数据
- ❌ **不允许**用可降水量、云冰量或云液水量替代算不出的量
- ❌ **不允许**事后按结果调整验收标准
- ✅ **必须**保留中间结果：每项的单位、缺测标记与收支残差
- ✅ **必须**在误差「连方向都给不出」时标记 `INSUFFICIENT_EVIDENCE`，而不是报一个数

---

## 代码规范

### 分层：一文件一职责

| 目录 | 职责 |
|---|---|
| `experiments/` | **算什么** —— 数学口径与计算 |
| `src/hydroweave/repro/` | **凭什么可信** —— 可复现契约 |
| `scripts/dev/` | **谁来验** —— 独立验收 |

三者故意分离，让验证方不依赖被验证方。**验收脚本不得复用被验收的计算函数。**

### 静态检查

项目使用 [`ruff`](https://github.com/astral-sh/ruff)，规则集见 `pyproject.toml`。
已刻意为中文全角标点、科学计算常见的盲式异常等配置了忽略并注明理由。

### 风格约定

- 中文注释与文档段落之间不加空格，保持与现有代码一致
- 数值常量需注明单位与来源
- 涉及物理口径的代码，注释里写清公式编号（如 `式 (21)`）

---

## 提交信息规范

采用 [Conventional Commits](https://www.conventionalcommits.org/zh-hans/)：

```text
<类型>(<范围>): <简短描述>

<可选正文>

<可选脚注>
```

| 类型 | 用途 |
|---|---|
| `feat` | 新功能 |
| `fix` | 修复缺陷 |
| `docs` | 仅文档变更 |
| `refactor` | 重构（不改变行为） |
| `test` | 测试相关 |
| `ci` | CI 配置 |
| `chore` | 构建、依赖等杂项 |

**示例**

```text
fix(budget): 修正 renewal_period 的 hour 单位换算

unit="hour" 时实际返回秒，使 Th 放大 3600 倍。
新增回归测试覆盖 day/hour/second 三种单位。

Closes #12
```

---

## 报告问题

提交 Issue 前请先搜索是否已有相同问题。请使用 Issue 模板，并尽可能提供：

- 复现命令与完整报错
- `python --version`、操作系统、关键依赖版本
- 若与数据相关：数据卷 ID、数据集名、时间范围（**不要上传原始数据**）

**关于科学结论的讨论**：如果你认为某个口径或结论有问题，请附上推导或反例，
这正是本项目最欢迎的一类反馈。

---

## 提交 Pull Request

1. Fork 仓库，从 `main` 切出功能分支：`git checkout -b feat/your-feature`
2. 完成开发，确保[提交前检查](#提交前检查)三项通过
3. 更新相关文档与 `CHANGELOG.md` 的 `[Unreleased]` 段
4. 提交 PR，填写 PR 模板，说明**改了什么、为什么改、如何验证**
5. 等待 CI 通过

**PR 会被优先考虑的情形**：

- 附带了测试，尤其是能暴露真实缺陷的反例
- 明确说明了对已有误差边界的影响
- 文档同步更新

---

## 许可

提交贡献即表示你同意将其以 [MIT 许可](LICENSE) 发布。
