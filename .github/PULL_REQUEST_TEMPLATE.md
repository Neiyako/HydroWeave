## 这个 PR 做了什么

<!-- 一两句话说明变更内容与动机 -->

## 变更类型

- [ ] 🐛 Bug 修复
- [ ] ✨ 新功能 / 新口径
- [ ] 📊 误差分析方法改进
- [ ] 🗺️ 图件
- [ ] 📝 文档
- [ ] ♻️ 重构（不改变行为）
- [ ] ⚙️ 工程 / CI

## 涉及的环节

- [ ] 数学原理 / 公式实现
- [ ] 代理指标（PW / RH / CFRAC）
- [ ] 收支模型（budget.py / GCWR）
- [ ] 误差分析（error_analysis.py）
- [ ] 制图（plot.py）
- [ ] 可复现契约（manifest）
- [ ] 独立验收（validate_real_eda.py）
- [ ] CI / 工程配置

## 验证情况

**请粘贴实际执行的命令与结果**（不要只写"已测试"）：

```bash
ruff check .
PYTHONPATH=src:. python3 -m pytest -q
```

<!-- 粘贴输出摘要，例如：All checks passed! / 38 passed, 9 skipped -->

- [ ] `ruff check .` 通过
- [ ] `pytest -q` 通过
- [ ] 合成链路自检通过（fixture → EDA → plot）
- [ ] 若改动真实卷相关逻辑：已本地运行 `validate_real_eda.py`（结果粘贴于下）

<details>
<summary>真实卷验收结果（如适用）</summary>

<!-- 粘贴 validate_real_eda.py 的关键输出或判定 -->

</details>

## 对误差边界与结论的影响

<!--
本项目核心价值是"说清能信到什么程度"。请务必回答：
- 本次改动是否改变已有结论？
- 是否改变误差量级或方向？
- 是否使某个原先 INSUFFICIENT_EVIDENCE 的量变得可判定，或反之？
-->

| 问题 | 回答 |
|---|---|
| 是否改变已有结论 | |
| 误差量级/方向是否变化 | |
| 是否需要更新文档 | |

## 检查清单

- [ ] 新增公式已在代码注释中注明**公式编号与文献来源**
- [ ] 新增逻辑有对应**单元测试**（含边界情况与反例）
- [ ] 新增配置项已加入 `config.yaml`，未硬编码
- [ ] 已更新 `CHANGELOG.md` 的 `[Unreleased]` 段
- [ ] 相关文档（README / ONBOARDING / DESIGN）已同步
- [ ] **未**为让方程闭合而静默修改数据
- [ ] **未**用其他量替代算不出的量
- [ ] **未**事后调整验收标准

## 相关 Issue

<!-- 例如：Closes #12 -->
