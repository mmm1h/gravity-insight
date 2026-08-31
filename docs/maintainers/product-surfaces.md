# 已交付产品面

本页只回答“当前产品入口在哪里、由谁拥有”。参数、schema、默认值和返回形状不在这里复制；它们以 [CLI](../reference/cli.md)、[SDK](../reference/sdk.md)、[Plan](../reference/plan.md)、
运行时 catalog 和机器合同为准。

| 产品 | 当前入口 | 不变量 | 当前参考 |
| --- | --- | --- | --- |
| Business Pulse | `reports pulse` / `business_pulse()` / `business_pulse` composite | 多 App 趋势；小时源明确是 workspace scope | [CLI](../reference/cli.md#business-pulse)、[Plan](../reference/plan.md#business-pulse-composite) |
| Multidim | `multidim query` / `multidim_query()` / `multidim` composite | 直接使用闭合物理输入；不新增 Spec DSL，不解释业务指标 | [CLI](../reference/cli.md#multidim)、[Plan](../reference/plan.md#multidim-composite) |
| User Detail Aggregate | `analysis user-detail-aggregate` / `user_detail_aggregate()` / `user_detail_aggregate` composite | 内部消费有界 user-detail 分页；只交付聚合单元格和值无关证据，不交付用户行或用户标识 | [CLI](../reference/cli.md#user-detail-aggregate)、[SDK](../reference/sdk.md#user-detail-aggregate)、[Plan](../reference/plan.md#user-detail-aggregate-composite) |
| Material Performance | `materials performance` / `material_performance()` / 同名 composite | 按平台保留物理字段和分页收据，不跨平台归一 | [CLI](../reference/cli.md#material-performance)、[Plan](../reference/plan.md#material-performance-composite) |
| Promotion Performance | `promotion performance` / `promotion_performance()` / 同名 composite | 只覆盖共同合同平台；平台和指标由调用方显式选择 | [CLI](../reference/cli.md#promotion-performance)、[Plan](../reference/plan.md#promotion-performance-composite) |
| Dashboard Analysis | `analysis dashboard prepare|run` / dashboard analysis SDK / `dashboard_analysis` composite | 只编译已证明图表；不模拟 layout、favourite 或页面 global filter | [CLI](../reference/cli.md#dashboard-analysis-replay-v2)、[Plan](../reference/plan.md#dashboard-analysis-composite) |
| Order Directory | `analysis order directory` / `order_directory()` / `order_directory` composite | 严格单日、固定四字段、完整分页；额外标识 fail closed | [CLI](../reference/cli.md#order-directory-v1)、[Plan](../reference/plan.md#order-directory-composite) |
| Order Split Trace | `analysis order trace` / `order_split_trace()` / `order_split_trace` composite | 本地唯一父匹配后才读 child；结果不暴露 TraceID | [CLI](../reference/cli.md#order-split-trace-v1)、[Plan](../reference/plan.md#order-split-trace-composite) |
| Isolated SQL Explorer | `sql explorer inspect|execute|promote` / `sql_explorer` SDK | SQLite-only；AST + database read-only identity + budgets；exploratory 隔离且无 Agent/Plan fallback | [CLI](../reference/cli.md#sql)、[SDK](../reference/sdk.md#sql-专用底层-facade) |

## 维护规则

- 产品行为变化时先改 owner 模块和机器合同，再更新对应 reference；本页只在入口或所有权变化时改。
- Agent 卡只负责发现和 value-free 交接，不复制产品执行逻辑。
- Plan adapter 内部并发固定受全局预算约束；独立产品用同层节点并发，不叠加私有线程池。
- 新设计结论写入 roadmap、候选矩阵、动线或技术债；交付后不再维护一份平行设计说明。
