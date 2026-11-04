"""严格云水柱含量实验：用真实 ERA5 clwc/ciwc 验证云水数学模型的积分口径。

与 ``tp_cloud_water``（t/q 代理指标）不同，本实验直接消费 ERA5 气压层
液态/冰态云水混合比（``clwc``/``ciwc``，kg·kg⁻¹）：

- LWP = ∫ (clwc / g) dp，IWP = ∫ (ciwc / g) dp，气压层梯形积分，单位 kg·m⁻²；
- 区域平均按 cosφ 面积权重；
- 层不全时显式标记 ``partial_column=true``，绝不把部分列当整列；
- 用 ``tp_cloud_water.budget`` 的式 (20)(21)(22) 做代数恒等式自检；
- 量级与文献/ERA5 气候态比对只允许 CONDITIONAL_PASS / INSUFFICIENT_EVIDENCE；
- GCWR 收支闭合与年度结论因缺 P/E/边界通量/长时段标 NOT_RUN。

模块分工：``common``（配置/catalog/清单）、``compute``（读数据+积分+统计）、
``plot``（图件）、``verify``（恒等式自检+五态报告）。
"""
