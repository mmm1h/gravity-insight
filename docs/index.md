# Gravity SDK 文档

本文档按任务组织。不要从目录开始逐文件通读；先选择当前任务，只阅读对应路径。

## 我现在要做什么

| 任务 | 先读 | 需要时再读 |
| --- | --- | --- |
| 安装、登录、跑第一个查询 | [快速上手](getting-started.md) | [CLI 参考](reference/cli.md) |
| 让 Agent 查询 Gravity | [Agent 工作流](agent-workflow.md) | [架构与概念](architecture.md) |
| 判断用 Insight 还是 SQL | [架构与概念](architecture.md#查询路由) | [Agent 工作流](agent-workflow.md#选择查询通道) |
| 同步全部 App 的埋点目录 | [快速上手](getting-started.md#同步本地元数据目录) | [CLI 参考](reference/cli.md#metadata) |
| 创建或下载异步导出 | [导出指南](guides/export.md) | [CLI 参考](reference/cli.md) |
| 新增或升级 operation | [新增受控能力](maintainers/operations.md) | [维护者入口](maintainers/index.md) |
| 探测生产接口 | [探测安全](maintainers/probing.md) | [路由盘点](maintainers/census.md) |
| 刷新 Evidence | [Evidence 运行手册](maintainers/evidence.md) | [维护者入口](maintainers/index.md) |

## 三个必须先知道的边界

1. **Insight-first。** 能由 stable Insight operation 等价表达的查询，不走 SQL。
2. **只执行已登记能力。** SDK 不接受任意 URL、HTTP 方法或未登记字段；SQL 也只有固定入口和固定产品。
3. **SDK 不维护业务语义。** “幸运礼包”等模块名称、活动 ID、SKU、投放窗口和埋点关联由业务知识库维护；SDK 只校验和读取真实 Gravity 元数据。

## 文档层级

- 第 0 层：[README](../README.md)——项目定位和入口。
- 第 1 层：本页、[快速上手](getting-started.md)、[Agent 工作流](agent-workflow.md)。
- 第 2 层：[架构与概念](architecture.md)、[CLI 参考](reference/cli.md)、专项指南。
- 第 3 层：[维护者文档](maintainers/index.md)、包内 manifest、contract 与源码。

历史验收数字、临时业务裁决和 Merge 业务埋点字典不属于当前 SDK 文档。历史可以从 Git 追溯；业务口径由 `work-dashboard` 维护；机器运行合同位于 `src/gravity_sdk/contracts`。
