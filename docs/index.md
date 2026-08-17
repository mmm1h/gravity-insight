# Gravity SDK 文档

本文档按任务组织。不要从目录开始逐文件通读；先选择当前任务，只阅读对应路径。

## 我现在要做什么

| 任务 | 先读 | 需要时再读 |
| --- | --- | --- |
| 安装、登录、跑第一个查询 | [快速上手](getting-started.md) | [CLI 参考](reference/cli.md) |
| 让 Agent 浏览完整目录并查询 Gravity | [Agent 工作流](agent-workflow.md) | [Agent 任务指南](agent-skills/index.md) |
| 十分钟内取得首次真实 Agent 分析结果 | [十分钟路径](agent-skills/ten-minute-path.md) | [快速上手](getting-started.md) |
| 构造事件、漏斗、留存、属性或分布查询 | [Agent 工作流](agent-workflow.md) | [CLI 参考：Analysis Spec](reference/cli.md#analysis-query-spec-v1) |
| 对已有结果计算调用方绑定的比率、占比、变化或集合对账 | [Agent 工作流](agent-workflow.md#1-业务语义先在调用项目解析) | [CLI 参考：Derived Metrics](reference/cli.md#derived-metrics) |
| 执行多维报表查询 | [Agent 工作流：Multidim](agent-workflow.md#multidim) | [CLI 参考：Multidim](reference/cli.md#multidim) |
| 用已登记语义成员组合指标、维度与粒度 | [Agent 工作流：报表入口](agent-workflow.md#multidim) | [CLI 参考：Semantic Compose](reference/cli.md#semantic-compose) |
| 读取单日订单目录 | [Agent 工作流](agent-workflow.md) | [CLI 参考：Order Directory](reference/cli.md#order-directory-v1) |
| 按 TraceID 读取单日拆单明细 | [Agent 工作流](agent-workflow.md) | [CLI 参考：Order Split Trace](reference/cli.md#order-split-trace-v1) |
| 读取单日完整已登记变现明细 | [Agent 工作流](agent-workflow.md) | [维护者边界](maintainers/monetization-discovery-guard.md) |
| 读取跨平台素材表现 | [Agent 工作流](agent-workflow.md) | [CLI 参考：Material Performance](reference/cli.md#material-performance) |
| 按精确素材引用下载图片或视频 | [Agent 工作流](agent-workflow.md) | [CLI 参考：Material Asset Fetch](reference/cli.md#material-asset-fetch) |
| 读取跨平台推广表现 | [Agent 工作流](agent-workflow.md) | [CLI 参考：Promotion Performance](reference/cli.md#promotion-performance) |
| 查看自定义人群覆盖与状态 | [Agent 工作流](agent-workflow.md) | [CLI 参考](reference/cli.md#custom-audiences) |
| 从漏斗/规则创建、更新、刷新或安全删除分群 | [Agent 工作流](agent-workflow.md) | [CLI 参考：Segment Mutation](reference/cli.md#segment-mutation-v1)、[分群删除能力调查](research/segment-delete-capability.md) |
| 创建或安全删除报表与报表订阅 | [Agent 工作流：受治理写入](agent-workflow.md#受治理写入统一两步确认) | [CLI 参考：报表目录与订阅](reference/cli.md#报表目录与订阅) |
| 创建、更新、查询或安全删除自定义指标口径 | [Agent 工作流：受治理写入](agent-workflow.md#受治理写入统一两步确认) | [CLI 参考：自定义指标](reference/cli.md#自定义指标口径-crud) |
| 声明调用方业务词和派生指标公式 | [调用方语义任务指南](agent-skills/caller-semantics.md) | [Workspace 参考：调用方语义上下文](reference/workspace.md#调用方语义上下文) |
| 批量发现并执行交叉查询 | [Agent 工作流：显式 Plan](agent-workflow.md#3-交叉查询一个显式-plan) | [CLI Plan 参考](reference/cli.md#plan-v1) |
| 运行或续跑固定的指标异常定位调查 | [Plan 参考：可恢复 playbook](reference/plan.md#metric-anomaly-localization1) | [CLI 参考：Analysis playbook](reference/cli.md#analysis-playbook) |
| 在 Python 中集成 SDK | [Python SDK 参考](reference/sdk.md) | [架构与概念](architecture.md) |
| 把 SDK/CLI 输出交给 LLM | [LLM 输出安全指南](guides/llm-output-safety.md) | [Agent 工作流](agent-workflow.md) |
| 判断用 Insight 还是 SQL | [架构与概念](architecture.md#查询路由) | [Agent 工作流](agent-workflow.md#选择-insight-还是-sql) |
| 检查本地 metadata 状态或有界同步一个 App | [快速上手](getting-started.md#同步本地元数据目录) | [CLI 参考](reference/cli.md#metadata) |
| 配置项目 App、SQL 产品或 recipe | [Workspace 参考](reference/workspace.md) | [架构与概念](architecture.md#发现workspace-与-resolver) |
| 创建或下载异步导出 | [导出指南](guides/export.md) | [CLI 参考](reference/cli.md) |
| 新增或升级 operation | [新增受控能力](maintainers/operations.md) | [维护者入口](maintainers/index.md) |
| 判断能力应扩展到哪一层 | [扩展地图](maintainers/extending.md) | [新增受控能力](maintainers/operations.md) |
| 判断是否建设 MCP 交付面 | [MCP 可行性报告](mcp-feasibility.md) | [路线图](roadmap.md) |
| 复核外部调研证据（可用性 / 安全 / 协议 / 语义层 / 厂商） | [外部调研索引](#外部调研) | [Agent 可用性方法](research/agent-usability-methods.md)、[安全治理](research/agent-security-governance.md) |
| 了解本租户引力原生 AI 的真实行为 | [本租户能力摸底](#本租户能力摸底) | [路线图](roadmap.md#引力原生-ai-事件分析对话摸底2026-08-16) |
| 了解当前排期、并行约束与不做的事 | [路线图](roadmap.md) | [分析动线台账](analysis-journeys.md) |
| 查阅某一趟开发的完整结论与证据 | [每趟结论归档](roadmap.d/README.md) | [路线图](roadmap.md) |
| 查看每条分析动线的完成度、四面入口与证据阻塞 | [分析动线台账](analysis-journeys.md) | [能力覆盖与缺口](capability-coverage.md) |
| 查看架构热点与清理条件 | [技术债清单](maintainers/technical-debt.md) | [维护者入口](maintainers/index.md) |
| 查看当前平台覆盖和不能直接上线的缺口 | [能力覆盖与缺口](capability-coverage.md) | [路由盘点](maintainers/census.md) |
| 查看本轮 17 个候选的真实状态 | [候选能力证据矩阵](candidate-capability-matrix.md) | [探测安全](maintainers/probing.md) |
| 探测生产接口 | [探测安全](maintainers/probing.md) | [路由盘点](maintainers/census.md) |
| 刷新 Evidence | [Evidence 运行手册](maintainers/evidence.md) | [维护者入口](maintainers/index.md) |

## 三个必须先知道的边界

1. **Insight-first。** 能由 stable Insight operation 等价表达的查询，不走 SQL。
2. **只执行已登记能力。** SDK 不接受任意 URL、HTTP 方法或未登记请求字段；未登记响应字段不投影，但以结构化审计记录。Agent 面向的 SQL 只执行 workspace 已登记聚合产品。底层 `GravityClient` 不是 Agent 产品入口。
3. **SDK 不维护业务语义。** “幸运礼包”等模块名称、活动 ID、SKU、投放窗口和埋点关联由业务知识库维护；SDK 只校验和读取真实 Gravity 元数据。

## Agent 最短路径

- 第一次盘点仓库能力：离线执行 `agent-catalog categories → category → describe`；先选产品卡，再读完整输入合同。raw operation 只作专家入口，精确 gap 不可执行。
- 已知 selector 或已有 Plan：一次 `gravity run` / `gravity plan run`。
- 未知问题：一次 `gravity agent --input` 批量发现，再一次 `gravity plan run`，总共两次。
- 多个独立 Analysis spec，或同一事件/漏斗/留存/属性 spec 的显式多 App 数组：一次 `gravity analysis query batch`；单用户明细链用一次 `gravity analysis user journey`，不手工串行三条 operation。
- 已知 Multidim 物理输入：一次 `gravity multidim query`；未知能力：一次 Agent 发现加一次 Plan 执行。CLI 显式要求 `--app`，Plan 显式要求当前 `input_schema_version`，结果行读取 `query.data.list`。多个独立查询放进同一个 Plan，不逐条启动命令。
- 已知 App 与单日：一次 `gravity analysis order directory`；需要拆单明细时再提供 TraceID，执行 `gravity analysis order trace`。未知入口由 Agent 返回待填写节点，再执行一次 Plan；自然语言中的 TraceID 不会被复制或执行。
- 已知推广 App、日期、平台和物理指标：一次 `gravity promotion performance`；未知入口由 Agent 返回待填写的 `promotion_performance` 节点，再执行一次 Plan。
- 已知归因 App 与日期：一次 `gravity attribution performance`；它固定读取四组前端已证明的归因
  表现画像。未知入口由 Agent 返回待填写的 `attribution_performance` 节点。
- 已知漏斗 spec 或分群 ID：先运行 `gravity analysis segment ... --dry-run`，人工审查后运行同一
  命令的 `--execute`。create 会写可见 SDK 标记并读回；delete 只删读回仍带标记的对象。Agent 不自动写，
  Segment mutation 不进入 Plan v1。
- 已知报表/订阅写输入：同样先运行 `gravity reports create|delete|subscribe|unsubscribe ... --dry-run`，
  人工审查后只把确认开关改为 `--execute`。create 写 marker；delete/unsubscribe 执行时重读 marker；
  订阅固定 disabled、无收件人，不调用 test route，也不进入 Plan v1。
- 发现只返回候选以及 Plan node 或受控编译交接，不会从自然语言自动执行。

当前安装时目录为 330 个 selector：233 个 operation、93 张产品卡与 7 个精确 gap，扣除
`app.list`、`app.app_info.get`、`report.get.query` 三组产品卡/raw operation 的同身份重复；224 个 stable operation 由 187 read + 37 governed
mutation 组成。17 个候选中 `analysis.default_val.list`、`app.app_info.get`、D28、D35、F40、报表目录与
订阅清单已晋升；不要把其余 `draft` 能力写入生产 Plan。
逐项 blocker 以[候选能力证据矩阵](candidate-capability-matrix.md)为准。

## 文档层级

- 第 0 层：[README](../README.md)——项目定位和入口。
- 第 1 层：本页、[快速上手](getting-started.md)、[Agent 工作流](agent-workflow.md)。
- 第 2 层：[架构与概念](architecture.md)、[CLI 参考](reference/cli.md)、专项指南。
- 第 3 层：[维护者文档](maintainers/index.md)、包内 manifest、contract 与源码。
- 旁支：[外部调研](#外部调研)——同类产品与方法学的取证记录，不是本 SDK 的行为合同。

## 本租户能力摸底

- [引力原生 AI 事件分析对话摸底](research/gravity-native-ai.md)

## 外部调研

2026-08-15 对同类分析平台 Agent 形态、协议与方法学的调研。**这些是外部事实记录，
不构成本仓库的行为承诺**；每条结论标注了 `[实证]` / `[厂商宣称]` / `[推测]`。

- [调研索引](research/index.md) — 七份外部调研、两份本租户调查，以及把它们变成排期的
  [借鉴规划](research/borrow-roadmap.md)（含「明确不做」一档）。

历史验收数字、临时业务裁决和 Merge 业务埋点字典不属于当前 SDK 文档。历史可以从 Git 追溯；业务口径由 `work-dashboard` 维护；机器运行合同位于 `src/gravity_sdk/contracts`。
