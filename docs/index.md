# Gravity SDK 文档

本文档按任务组织。不要从目录开始逐文件通读；先选择当前任务，只阅读对应路径。

## 我现在要做什么

| 任务 | 先读 | 需要时再读 |
| --- | --- | --- |
| 安装、登录、跑第一个查询 | [快速上手](getting-started.md) | [CLI 参考](reference/cli.md) |
| 让 Agent 查询 Gravity | [Agent 工作流](agent-workflow.md) | [架构与概念](architecture.md) |
| 构造事件、漏斗、留存、属性或分布查询 | [Agent 工作流](agent-workflow.md) | [CLI 参考：Analysis Spec](reference/cli.md#analysis-query-spec-v1) |
| 执行多维报表查询 | [Agent 工作流：Multidim](agent-workflow.md#multidim) | [CLI 参考：Multidim](reference/cli.md#multidim) |
| 读取单日无标识订单目录 | [Agent 工作流](agent-workflow.md) | [CLI 参考：Order Directory](reference/cli.md#order-directory-v1) |
| 按 TraceID 读取单日拆单明细 | [Agent 工作流](agent-workflow.md) | [CLI 参考：Order Split Trace](reference/cli.md#order-split-trace-v1) |
| 读取单日无标识变现明细 | [Agent 工作流](agent-workflow.md) | [维护者边界](maintainers/monetization-discovery-guard.md) |
| 读取跨平台素材表现 | [Agent 工作流](agent-workflow.md) | [CLI 参考：Material Performance](reference/cli.md#material-performance) |
| 读取跨平台推广表现 | [Agent 工作流](agent-workflow.md) | [CLI 参考：Promotion Performance](reference/cli.md#promotion-performance) |
| 批量发现并执行交叉查询 | [Agent 工作流：显式 Plan](agent-workflow.md#3-交叉查询一个显式-plan) | [CLI Plan 参考](reference/cli.md#plan-v1) |
| 在 Python 中集成 SDK | [Python SDK 参考](reference/sdk.md) | [架构与概念](architecture.md) |
| 判断用 Insight 还是 SQL | [架构与概念](architecture.md#查询路由) | [Agent 工作流](agent-workflow.md#选择-insight-还是-sql) |
| 同步全部 App 的埋点目录 | [快速上手](getting-started.md#同步本地元数据目录) | [CLI 参考](reference/cli.md#metadata) |
| 配置项目 App、SQL 产品或 recipe | [Workspace 参考](reference/workspace.md) | [架构与概念](architecture.md#发现workspace-与-resolver) |
| 创建或下载异步导出 | [导出指南](guides/export.md) | [CLI 参考](reference/cli.md) |
| 新增或升级 operation | [新增受控能力](maintainers/operations.md) | [维护者入口](maintainers/index.md) |
| 判断能力应扩展到哪一层 | [扩展地图](maintainers/extending.md) | [新增受控能力](maintainers/operations.md) |
| 了解当前排期、并行约束与不做的事 | [路线图](roadmap.md) | [分析动线台账](analysis-journeys.md) |
| 查看每条分析动线的完成度、四面入口与证据阻塞 | [分析动线台账](analysis-journeys.md) | [能力覆盖与缺口](capability-coverage.md) |
| 查看架构热点与清理条件 | [技术债清单](maintainers/technical-debt.md) | [维护者入口](maintainers/index.md) |
| 查看当前平台覆盖和不能直接上线的缺口 | [能力覆盖与缺口](capability-coverage.md) | [路由盘点](maintainers/census.md) |
| 查看本轮 17 个候选的真实状态 | [候选能力证据矩阵](candidate-capability-matrix.md) | [探测安全](maintainers/probing.md) |
| 探测生产接口 | [探测安全](maintainers/probing.md) | [路由盘点](maintainers/census.md) |
| 刷新 Evidence | [Evidence 运行手册](maintainers/evidence.md) | [维护者入口](maintainers/index.md) |

## 三个必须先知道的边界

1. **Insight-first。** 能由 stable Insight operation 等价表达的查询，不走 SQL。
2. **只执行已登记能力。** SDK 不接受任意 URL、HTTP 方法或未登记字段；Agent 面向的 SQL
   只执行 workspace 已登记聚合产品。底层 `GravityClient` 不是 Agent 产品入口。
3. **SDK 不维护业务语义。** “幸运礼包”等模块名称、活动 ID、SKU、投放窗口和埋点关联由业务知识库维护；SDK 只校验和读取真实 Gravity 元数据。

## Agent 最短路径

- 已知 selector 或已有 Plan：一次 `gravity run` / `gravity plan run`。
- 未知问题：一次 `gravity agent --input` 批量发现，再一次 `gravity plan run`，总共两次。
- 多个独立 Analysis spec：一次 `gravity analysis query batch`；单用户明细链用一次
  `gravity analysis user journey`，不手工串行三条 operation。
- 已知 Multidim 物理输入：一次 `gravity multidim query`；未知能力：一次 Agent 发现加一次
  Plan 执行。CLI 显式要求 `--app`，Plan 显式要求当前 `input_schema_version`，结果行读取
  `query.data.list`。多个独立查询放进同一个 Plan，不逐条启动命令。
- 已知 App 与单日：一次 `gravity analysis order directory`；需要拆单明细时再提供 TraceID，执行
  `gravity analysis order trace`。未知入口由 Agent 返回待填写节点，再执行一次 Plan；自然语言中的
  TraceID 不会被复制或执行。
- 已知推广 App、日期、平台和物理指标：一次 `gravity promotion performance`；未知入口：Agent
  返回待填写的 `promotion_performance` 节点，再执行一次 Plan。
- 发现只返回候选以及 Plan node 或受控编译交接，不会从自然语言自动执行。

当前基线仍为 185 个 operation、176 个 stable。本轮 17 个候选新增 stable 数为 0；不要把
`draft` 能力写入生产 Plan。逐项 blocker 以[候选能力证据矩阵](candidate-capability-matrix.md)
为准。

## 文档层级

- 第 0 层：[README](../README.md)——项目定位和入口。
- 第 1 层：本页、[快速上手](getting-started.md)、[Agent 工作流](agent-workflow.md)。
- 第 2 层：[架构与概念](architecture.md)、[CLI 参考](reference/cli.md)、专项指南。
- 第 3 层：[维护者文档](maintainers/index.md)、包内 manifest、contract 与源码。

历史验收数字、临时业务裁决和 Merge 业务埋点字典不属于当前 SDK 文档。历史可以从 Git 追溯；业务口径由 `work-dashboard` 维护；机器运行合同位于 `src/gravity_sdk/contracts`。
