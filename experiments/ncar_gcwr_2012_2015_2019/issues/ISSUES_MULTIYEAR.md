# 三年 GCWR 并行运行暴露问题

1. **RDH-HTTP-01：默认 HTTP 连接池仅 8 连接**
   `researchdatahub/transfer/http.py` 使用 `_DEFAULT_MAX_CONNECTIONS = 8`。64 个 worker 中大量任务在连接池等待后触发 `timeout_pool`，表面像 NCAR 限速。任务内用专用 transport 将池扩到 `workers*3` 并将 pool timeout 放宽到 60 s。

2. **RDH-HEARTBEAT-01：心跳会续租遗留 RUNNING 任务**
   中断一个 scheduler 后再次运行，新的心跳线程会刷新数据库中所有 RUNNING 任务的 `heartbeat_at/lease_expires_at`，包括不属于本轮 worker 的旧任务，使它们无法被 `release_expired` 回收。任务内通过停止全部进程、等待租约过期并精确重置目标任务规避。

3. **RDH-CLI-02：`task run <plan>` 的未完成计数包含无关计划任务**
   一个早期错误预检计划残留 282 个 PLANNED 任务时，正式计划已 282/282 COMPLETED，但 CLI 仍报告“未完成 282”并退出 1。清理该精确失败计划后恢复。应按 plan_id 统计，而不是全局任务表。

4. **RDH-SUMMARY-03：scheduler 本次运行计数不等于计划生命周期状态**
   已完成计划的断点续跑中 `summary.counts['completed']` 可能为 0，但计划任务全部 COMPLETED。任务内改为直接查询计划最终状态，完成后才生成报告和导入 DBAS。

5. **RDH-NCSS-01：NCSS HEAD 与 GET 同样昂贵**
   已知固定 shape 的子集仍会对每个资产做昂贵 HEAD。任务内使用预声明 shape、跳过 HEAD，但最终仍以 HTTP Content-Length、SHA-256、格式嗅探和 NetCDF 可打开性验收。

6. **NCAR-NCSS-02：偶发 404 / 截断响应**
   2019-01-24、2019-01-27 等 NCAR 文件在目录中存在，但 NCSS GET 偶尔返回 404；另有 2012-07-02 u 文件因 NetCDF 截断被隔离。处理方式是仅对对应 task 重置为 QUEUED 重试，不删除已成功文件，不修改源目录。

所有重试和隔离都有 RDH manifest 任务状态与日志可追溯；不会把 `NOT_RUN` 或截断文件当 PASS。
