# 语义层 / 指标层与 text-to-SQL 的工程现状

> 调研截止：2026-08-15。这里的“准确率”均指相应榜单自己的指标与设置，不能直接当作生产正确率。

## 结论先行

[推测] **本仓库没有闭门造车，但它选择了正确性优先、覆盖面后置的最窄路线。** Cube、dbt、Snowflake、Looker、AtScale 都把指标、维度、连接和权限从 LLM 手里拿走；Uber Finch 甚至先做单表财务数据集再让 LLM 写 SQL。共同方向是“先缩小可犯错空间”，区别在于这些系统多在查询时组合指标，本仓库则把整条漏斗、留存、归因动线连同 envelope 一起预先固化。[Cube](https://docs.cube.dev/docs/introduction) [dbt](https://www.getdbt.com/blog/how-the-dbt-semantic-layer-works) [Snowflake](https://docs.snowflake.com/en/user-guide/views-semantic/overview) [Looker](https://docs.cloud.google.com/looker/docs/conversational-analytics-overview) [Finch](https://www.uber.com/hr/en/blog/unlocking-financial-insights-with-finch/)

[实证] **早期 Spider 2.0 的“21.3%”仍是重要历史证据，但已不是当前 SOTA。** 2024 论文报告 code agent 21.3%、Lite parser 5.7%，对照 Spider 1.0 的 91.2% 和当时 BIRD 的 73.0%；截至本次快照，Spider 2 官方榜单已是 Snow 96.70%、DBT 65.6%、Lite 76.23%。因此“真实企业场景显著更低”对 DBT 仍成立，对 Lite 已明显收窄，对 Snow 已不成立；三个赛道不能压成一个数字。[Spider 2.0 论文](https://arxiv.org/abs/2411.07763) [当前榜单](https://spider2-sql.github.io/)

[实证] **榜单数字本身也不是坚固地基。** 2026 年预印本由专家复核得到 BIRD Mini-Dev 52.8%、Spider 2.0-Snow 62.8% 的标注错误率；修正 BIRD 子集后，16 个开源 agent 的相对分数变化为 -7% 至 +31%，名次变化 -9 至 +9。[标注错误研究](https://arxiv.org/abs/2601.08778)

[实证] **企业 text-to-SQL 的危险错误确实常常不是报错，而是“能执行、数却不对”。** FLEX 证明 execution accuracy 会把碰巧返回相同结果的错误逻辑判对；Uber QueryGPT 记录了 `Finished` / `Completed` 枚举幻觉导致成功执行但无输出；生产代表性金融案例把错锚点、无意义 join、无依据过滤列为静默失败。[FLEX](https://aclanthology.org/2025.naacl-long.228/) [QueryGPT](https://www.uber.com/us/en/blog/query-gpt/) [金融案例](https://openreview.net/forum?id=e29unNZEhY)

[推测] **安全扩大覆盖的最佳借鉴不是把原始 SQL 混进同一个“可信答案”入口，而是分层路由并把来源写进机器可判定的响应。** Snowflake 已返回 `confidence.verified_query_used`；AWS 官方样例把回答标为 metric / semantic / advisory，并保留 `provenance.tier`。本仓库可沿用这一模式：现有动线保持强合同，长尾只进入受限探索层，并在 envelope 中显式标出 `resolution_tier`、`definition_version`、`generated_sql`、验证状态与禁止断言。[Snowflake REST](https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-analyst/rest-api) [AWS 样例](https://github.com/aws-samples/sample-semantic-layer-structured)

## 范围、方法与证据标记

[实证] 本次实际使用了内置网页搜索与页面展开、PowerShell `Invoke-WebRequest`、`curl`、本机已有的 `pdftotext`、以及 `rg` 检索仓库和下载快照；关键 HTML、PDF、纯文本和 README 快照存于 `tmp/codex/r3-semantic-layer/sources/`，抓取清单是该目录的 `manifest.md`，均不属于提交产物。仓库没有 `.codegraph/`，所以按项目规则没有使用 CodeGraph。[仓库调研规范](../../AGENTS.md)

[实证] 失败和限制：Uber 两页对直接下载返回 HTTP 406，只能由网页搜索索引读取，故本地清单保留失败记录；Cube 公共文档能确认 MCP 存在，但未找到公开的精确 MCP tool schema；Kyligence 当前公开材料主要是产品页/新闻稿；ThoughtSpot 的 TML 与 Search API 有公开技术材料，但 Spotter 的硬边界和响应血缘没有找到同等强度的公开 API 规范。没有登录、注册、试用、付费访问或访问授权内容。本地抓取清单位于 `tmp/codex/r3-semantic-layer/sources/manifest.md`。

本文把证据单元分为：实证（官方文档、源码、论文或可复现快照）、厂商宣称（产品页、新闻稿或只有厂商叙述的效果）、推测（基于已列证据的工程判断）。标签只计行首的方括号标记；末尾给出机械计数。

## 先把三条路线说清楚

[推测] **text-to-SQL** 把自然语言意图、schema 和上下文交给模型，在查询时生成 SQL；**语义层 / 指标层** 先声明指标、维度、实体、连接和访问规则，再把“选什么、怎么切片”交给模型；**上游预计算** 则把完整分析动线和输出合同做成已登记能力，模型只选择与填参。三者不是互斥产品类别，而是把不确定性放在不同层。[Google text-to-SQL 架构](https://cloud.google.com/blog/products/databases/techniques-for-improving-text-to-sql) [Cube 架构](https://docs.cube.dev/docs/introduction) [本仓库动线判据](../analysis-journeys.md)

[推测] “fail-closed”也必须说明边界：一个 `query_metrics` 工具可以对未定义指标 fail-closed，但如果同一 agent 还拿到 `text_to_sql`，整个 agent 就不是 fail-closed；同理，语义层只约束经它发出的查询，不能阻止另一个凭据直连仓库。[dbt MCP 工具表](https://github.com/dbt-labs/dbt-mcp#tools) [Cube Source SQL 旁路](https://docs.cube.dev/docs/explore-analyze/workbooks/index)

## A. text-to-SQL 的真实准确率

### A1. 当前公开 benchmark 快照

| Benchmark / 赛道 | 截止日官方最高可见分数 | 设置与不可忽略的限制 |
|---|---:|---|
| [实证] Spider 1.0 execution | 91.2% | 榜首 MiniSeek 为匿名提交，页面仍写着 code / paper coming soon；exact set match 的 test 榜首为 81.5%。[官方榜单](https://yale-lily.github.io/spider) |
| [实证] BIRD overall execution | 81.95% | AskData + GPT-4o；该行勾选 `Oracle Knowledge`。同页 human performance 为 92.96%，不是模型分数。[官方榜单](https://bird-bench.github.io/) |
| [实证] Spider 2.0-Snow | 96.70% | 547 题、Snowflake、准备好的 metadata / documentation；榜单提示分数会更新，特殊 oracle-table 设置不列入主榜。[官方榜单](https://spider2-sql.github.io/) |
| [实证] Spider 2.0-DBT | 65.6% | 68 个 code-agent 数据变换任务；这是当前三个 Spider 2 主赛道中最低者。[官方榜单](https://spider2-sql.github.io/) |
| [实证] Spider 2.0-Lite | 76.23% | 547 题，BigQuery / Snowflake / SQLite；与 Snow、DBT 的环境和任务不同。[官方榜单](https://spider2-sql.github.io/) |
| [实证] Spider 2.0 论文初始基线 | 21.3% / 5.7% | o1-preview code agent 为 21.3%；Lite 的传统 parser 为 5.7%。论文同时给出 Spider 1.0 91.2%、BIRD 73.0% 作当时对照。[论文](https://arxiv.org/abs/2411.07763) |

[实证] Spider 2.0 比早期 Spider 更贴近企业工作流并非只靠宣传：论文数据平均约 743.5 个 schema items、148.3 个 SQL token，85.98% 任务使用方言高级函数，部分任务还要读文档和 DBT 项目代码；Spider 1.0 的典型任务没有这些工作流上下文。[Spider 2.0 论文](https://arxiv.org/abs/2411.07763)

[推测] 当前答案不是“企业 benchmark 永远显著低”，而是：**复杂工作流仍低，准备充分且边界较窄的赛道已经可以很高。** Snow 96.70% 说明工程代理、上下文和迭代执行可大幅缩小差距；DBT 65.6% 说明代码库理解、跨步骤变换仍是硬问题。由于赛道、提交透明度和辅助信息不同，不能拿 96.70% 推导“任意企业仓库已接近 97%”。[Spider 2 榜单设置](https://spider2-sql.github.io/) [论文任务定义](https://arxiv.org/abs/2411.07763)

[实证] 这些数还有评测污染：FLEX 发现 execution accuracy 同时有假阳性和假阴性；2026 标注研究则指出 BIRD Mini-Dev 与 Spider 2.0-Snow 的高标注错误，并实测修正后排名大幅移动。因此榜单更适合比较一个固定设置内的系统，不足以单独批准生产自主查询。[FLEX](https://aclanthology.org/2025.naacl-long.228/) [标注错误研究](https://arxiv.org/abs/2601.08778)

### A2. 已知失败模式

[实证] Spider 2.0 对随机 300 个错误样本的分析给出：错误数据分析 35.5%（方言函数 10.3%、高级计算 7.5%、复杂规划 17.7%）、错误 schema linking 27.6%（列 16.6%、表 10.1%）、JOIN 错误 8.3%。其 JOIN 解释非常接近企业现实：BigQuery 数据库常没有显式外键，模型只能从列名和描述猜键。[Spider 2.0 论文 §4.2](https://arxiv.org/abs/2411.07763)

[实证] “指标口径”和“业务值”不是 schema 能自动告诉模型的。Google 的官方工程说明用“best-selling”举例：它可能指订单量、收入、是否排除退货等不同问题；另一个例子说明若没人告诉模型 `cat_id2='Footwear'` 的业务含义，再强的 DBA 或 LLM 也写不出正确查询。[Google Cloud](https://cloud.google.com/blog/products/databases/techniques-for-improving-text-to-sql)

[实证] 时间窗、聚合、去重和 NULL 不是一类“语法小错”，而是口径的一部分。Spider 2.0 的错误定义明确包含日期处理、`GROUP BY`、`AVG` / `SUM`、window function 和公式；Google 的示例则用 `COUNT(DISTINCT order_id)` 和退货是否计入展示同一句自然语言可对应不同语义。[Spider 2.0](https://arxiv.org/abs/2411.07763) [Google Cloud](https://cloud.google.com/blog/products/databases/techniques-for-improving-text-to-sql)

[推测] 本次没有找到一项公开、代表性足够的研究能分别量化“NULL、大小写、去重、自然周/月、时区”各自占生产错误的比例；把它们列为已知风险是基于 SQL 语义与上述聚合/日期/值映射证据，不应伪装成已量化的行业分布。[Spider 2.0 错误分类](https://arxiv.org/abs/2411.07763) [QueryGPT 枚举值案例](https://www.uber.com/us/en/blog/query-gpt/)

### A3. 缓解方式与代价

| 手段 | 能缓解什么 | 不能保证什么 / 代价 |
|---|---|---|
| [实证] schema linking、检索与数据采样 | 先找相关数据集、表、列和值，减少大 schema 噪声。 | 要维护索引、描述与访问边界；检索错会把后续生成锁在错误子集。[Google Cloud](https://cloud.google.com/blog/products/databases/techniques-for-improving-text-to-sql) |
| [实证] few-shot、golden SQL、query history | 把业务规则、方言和已知正确路径放进上下文。 | 示例要持续随 schema / 口径维护；只能覆盖相似问题。[Google Cloud](https://cloud.google.com/blog/products/databases/techniques-for-improving-text-to-sql) [Uber QueryGPT](https://www.uber.com/us/en/blog/query-gpt/) |
| [实证] 澄清问题 | 在“销量还是收入”等歧义处暂停，不强行猜。 | 增加交互轮次；如果 agent 没识别出歧义仍会直接回答。[Google Cloud](https://cloud.google.com/blog/products/databases/techniques-for-improving-text-to-sql) |
| [实证] parser / dry-run / 执行反馈重试 | 确定性抓语法、缺列、部分方言和运行错误，再把错误反馈给模型。 | 增加模型调用、延迟和可能的仓库请求；合法但语义错误的 SQL 可顺利通过。[Google Cloud](https://cloud.google.com/blog/products/databases/techniques-for-improving-text-to-sql) [FLEX](https://aclanthology.org/2025.naacl-long.228/) |
| [实证] self-consistency / 多候选 | 多次生成后择优，降低单次采样偶然性。 | 成本近似随候选数增长；2026 预印本中，字符串/结构/执行 self-consistency 的正确性判别 AUROC 仍约 0.61–0.68，未找到可靠低风险子集。[Google Cloud](https://cloud.google.com/blog/products/databases/techniques-for-improving-text-to-sql) [选择性预测研究](https://arxiv.org/abs/2607.06799) |
| [实证] 只读、SELECT-only、允许过滤器和行数上限 | 限制破坏性和数据外泄半径；AWS 样例在写入时用 sqlglot 验证 SELECT-only，并仅 AST 添加允许的过滤器。 | 这是安全控制，不是数字正确性证明。[AWS 样例](https://github.com/aws-samples/sample-semantic-layer-structured) |
| [实证] 用户 / 专家确认 | Uber QueryGPT 让用户确认选表并展示 SQL 与解释；Finch 对高风险答案规划按需专家验证。 | 人工成本与等待时间重新进入链路，不再是完全自治。[QueryGPT](https://www.uber.com/us/en/blog/query-gpt/) [Finch](https://www.uber.com/hr/en/blog/unlocking-financial-insights-with-finch/) |
| [推测] 语义层或上游宽表 | 预先固化 join、指标和值语义，从根上减少生成自由度。 | 把成本移到建模、变更评审和覆盖维护；长尾仍要旁路或明确拒绝。[Cube](https://docs.cube.dev/docs/introduction) [Finch](https://www.uber.com/hr/en/blog/unlocking-financial-insights-with-finch/) |

### A4. 错误究竟是报错还是错数

[实证] 两者都有，但**语义错误天然倾向于静默**：只要列、函数和权限都合法，数据库没有能力判断 SQL 是否回答了用户原意。FLEX 的假阳性示例在查询里多加 `age < 19`，因当前数据恰好无人超过 18 岁而返回与 gold 相同结果；这说明连 benchmark 的“结果相同”都可能掩盖逻辑错误。[FLEX](https://aclanthology.org/2025.naacl-long.228/)

[实证] Uber QueryGPT 把 `Successful Run` 与 `Run Has Output` 分开评估，原因正是错误过滤值可以成功执行却没有输出；它还把生成 SQL、错误原因和与 golden SQL 的定性相似度单独展示。成功执行在其生产评估中从来没有被当作正确性的充分条件。[Uber QueryGPT](https://www.uber.com/us/en/blog/query-gpt/)

[实证] Uber Finch 的公开总结更直接：日常财务使用已“good enough”，但不是 100% 可靠且会 hallucinate；对高管关键问题规划 `Request validation`，由主题专家确认后再通知用户。[Uber Finch](https://www.uber.com/hr/en/blog/unlocking-financial-insights-with-finch/)

[实证] 2026 年的生产代表性金融案例把“SQL 可执行但回答错意图”列为企业部署的静默失败，并定位到术语落错、锚点错、无意义 join、无依据 filter；不过它是 workshop 案例研究，不是公开事故复盘。[OpenReview](https://openreview.net/forum?id=e29unNZEhY)

[实证] 本次没有找到一份可独立审计、公开披露影响金额/决策/根因/修复的企业 text-to-SQL 错数事故。能找到的是厂商工程团队对失败模式与护栏的公开讨论，以及论文中的生产代表性快照；报告不把它们冒充真实损失事故。检索到的 Uber 讨论与案例清单位于本地 `tmp/codex/r3-semantic-layer/sources/manifest.md`。

## B. 语义层 / 指标层到底做了什么

### B1. Cube

[实证] Cube 用 YAML 或 JavaScript 定义 cube、measure、dimension、join、view；view 是给人和 agent 的精选查询面。agent 可经 MCP / Chat，程序可经 Postgres-compatible Semantic SQL、REST、GraphQL 查询，`/v1/meta` 用于模型发现。所有语义查询在到仓库前按模型与 access policy 校验。[模型与 API](https://docs.cube.dev/docs/introduction) [Core Data APIs](https://docs.cube.dev/reference/core-data-apis)

[实证] 真实的预聚合配置不是“自动缓存”四个字，而是可声明的 rollup：[Cube pre-aggregations](https://docs.cube.dev/docs/pre-aggregations/using-pre-aggregations)

```yaml
pre_aggregations:
  - name: orders_by_day
    measures: [count, total_amount]
    time_dimension: created_at
    granularity: day
    refresh_key:
      every: 1 hour
```

字段形态来自 Cube 的 [`pre_aggregations` 文档](https://docs.cube.dev/docs/pre-aggregations/using-pre-aggregations)；运行时由 aggregate awareness 选匹配 rollup。可选 rollup-only 模式在没有匹配预聚合时直接报错，而默认模式可回源查询。

[实证] 访问控制覆盖 member、row 与 masking；多租户还可把已签名 JWT 的 `securityContext.tenant` 映射到不同 app / driver。它约束的是查询者可见的语义成员和行，而不是靠 LLM 自律。[访问策略](https://docs.cube.dev/docs/data-modeling/data-access-policies) [多租户 recipe](https://docs.cube.dev/recipes/configuration/multiple-sources-same-schema)

[实证] Cube 不是“只能查预定义指标”：Semantic SQL 允许在受治理 metric 上做 ad-hoc derived calculation；Workbench 还另有 `Source SQL Query`，可由 AI 直接查原始数据并明确 bypass semantic layer。故语义 API 对未建模成员 fail-closed，但整个 Cube 产品是否 fail-closed 取决于是否向 agent 开放 Source SQL。[Semantic SQL](https://docs.cube.dev/docs/introduction) [Workbook 两种 tab](https://docs.cube.dev/docs/explore-analyze/workbooks/index)

[实证] 口径配置作为代码进入 Git、code review、CI 和隔离环境；本次没有在查询响应文档中找到与本仓库 `schema_version` 等价的“本次答案使用哪一版指标定义”。[Cube code-first](https://docs.cube.dev/docs/introduction)

### B2. dbt Semantic Layer / MetricFlow

[实证] dbt 的语义模型和指标是声明式 YAML，MetricFlow 在查询时构造 SQL。真实示例的关键字段如下：[dbt 官方示例](https://www.getdbt.com/blog/how-the-dbt-semantic-layer-works)

```yaml
semantic_models:
  - name: order_item
    defaults:
      agg_time_dimension: ordered_at
    model: ref('order_items')

metrics:
  - name: revenue
    type: simple
    type_params:
      measure: revenue
```

[实证] entity 的 primary / foreign / unique 关系组成语义图，MetricFlow 据此动态 join，并生成 `semantic_manifest.json`；消费者可经 JDBC / GraphQL 请求 metric、dimension 和 filter，而不是自己给 join path。[dbt 架构](https://www.getdbt.com/blog/how-the-dbt-semantic-layer-works) [MetricFlow 源码](https://github.com/dbt-labs/metricflow)

[实证] dbt MCP 给出了很清楚的 agent 消费面：`list_metrics`、`get_dimensions`、`get_entities`、`get_metrics_compiled_sql`、`query_metrics`、`list_saved_queries`。但同一 server 的 SQL 组也有 `execute_sql` 与 `text_to_sql`，Discovery 还能读 model / source。单看 `query_metrics` 是指标目录式、未定义 metric 不可查；整套 MCP 默认能力不是指标层硬 fail-closed，部署者必须禁用或隔离 raw SQL 工具。[dbt-mcp README](https://github.com/dbt-labs/dbt-mcp#tools)

[实证] 指标定义随 dbt 项目进入版本控制，manifest 也有 artifact schema；本次没有找到 `query_metrics` 结果携带具体 metric definition version 的公开合同。Git 历史能审计变更，但不自动告诉下游一份旧结果用了哪次定义。[dbt Semantic Layer](https://www.getdbt.com/blog/how-the-dbt-semantic-layer-works) [dbt artifacts](https://docs.getdbt.com/reference/artifacts/manifest-json)

### B3. Snowflake Semantic Views / Cortex Analyst

[实证] Snowflake 当前推荐原生 Semantic View，仍支持 stage 上的 semantic model YAML。下面是官方 VQR 页面中真实 YAML 的缩短摘录：[Verified Query Repository](https://docs.snowflake.com/en/user-guide/views-semantic/verified-query-repository)

```yaml
name: Sales Data
tables:
- name: sales_data
  base_table:
    database: sales
    schema: public
    table: sd_data
  time_dimensions:
    - name: sale_timestamp
      expr: dt
  measures:
    - name: profit
      expr: amt - cst
      default_aggregation: sum
verified_queries:
  - name: "California profit"
    question: "What was the profit from California last month?"
    verified_at: 1714497970
    verified_by: Jane Doe
    sql: |
      SELECT sum(profit)
      FROM __sales_data
      WHERE state = 'CA'
```

[实证] Cortex Analyst 的 `POST /api/v2/cortex/analyst/message` 接收 question 与 semantic model / semantic view，响应 content 类型为 `text`、`suggestions` 或 `sql`；问题歧义且无法生成 SQL 时返回 suggestions。多模型请求还返回 `semantic_model_selection`。[REST API](https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-analyst/rest-api)

[实证] Agent 拿到的是逻辑 table、dimension、time dimension、fact、metric、relationship、synonym 和 verified query，不必看原始 DDL。通过 `SEMANTIC_VIEW(...)` 查询时只能引用视图公开对象，private fact / metric 不可见；但可在公开 fact / dimension 上临时定义 ad-hoc metric，所以它是“成员 fail-closed、组合较开放”。[查询 Semantic View](https://docs.snowflake.com/en/user-guide/views-semantic/querying)

[实证] Snowflake 是本次找到的最明确“可信来源标签”：SQL content 的 `confidence.verified_query_used` 为对象或 `null`，对象包含 `name`、`question`、`sql`、`verified_at`、`verified_by`。它没有宣称非 null 就等于结果正确，但调用方能机械区分是否使用了已验证查询。[REST response](https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-analyst/rest-api)

[实证] Semantic View 可 `CREATE OR ALTER`，stage YAML 可替换；VQR 单条有 `verified_at/by`。本次没有找到每次查询返回 semantic view definition version 的字段，所以定义版本与答案血缘仍不等同。[Semantic View DDL](https://docs.snowflake.com/en/user-guide/views-semantic/sql)

### B4. Looker LookML

[实证] LookML 是代码式声明语言：view 中写 dimension / measure，Explore 决定可查起点和 join。API 查询对象提交 `model`、`view`、`fields[]`、filters、sorts、limit，消费者选 LookML 字段而不是提交原始表 join。[LookML 示例](https://docs.cloud.google.com/looker/docs/lookml-terms-and-concepts) [Query API](https://docs.cloud.google.com/looker/docs/reference/looker-api/latest/methods/Query/create_query)

[实证] Conversational Analytics 先取附着 Explore 的 LookML schema，模型只决定 field / filter / sort / limit，SQL 由 Looker 按 LookML 的 join、aggregation 和 permission 组合；hidden field 被忽略。一个数据 agent 最多连接五个 Explore，也可带 verified queries。[工作原理](https://docs.cloud.google.com/looker/docs/conversational-analytics-overview)

[实证] 标准查询面不能访问 LookML 未暴露字段，因此在这个边界内接近 fail-closed；但可选 Advanced Analytics 会把自然语言翻译成 Python 并在查询结果上继续计算。它扩大的是“对已返回结果做什么”，不是绕过 LookML 直接读仓库。[Advanced Analytics](https://docs.cloud.google.com/looker/docs/conversational-analytics-overview)

[实证] LookML project 由 Git 分支、review 和 deploy 管理；本次没有找到 Conversational Analytics 回答中携带 commit SHA / model version 的合同。[Looker 版本控制](https://docs.cloud.google.com/looker/docs/version-control-and-deploying-changes)

### B5. ThoughtSpot、AtScale、Kyligence

| 产品 | 定义形态与 agent 消费 | 未定义查询边界 | 变更与版本证据 |
|---|---|---|---|
| [实证] ThoughtSpot | TML 是 ThoughtSpot 对象的 YAML 表示，含 Table / Worksheet / View / Answer / Liveboard；Search API 示例以 `worksheetID` 加搜索表达式查询，说明主要消费 worksheet 逻辑面。[TML](https://developers.thoughtspot.com/codespot/tml-python-library) [Search API 示例](https://developers.thoughtspot.com/guides/creating-custom-charts-with-tse-and-d3) | 公开材料能证明 worksheet 是查询边界和仍支持 ad-hoc search，但本次未找到 Spotter 对“未建模公式/字段”硬拒绝的公开 API 规范，不能判定全产品 fail-closed。 | TML 可导出 / 导入并用于 CI；没有找到回答级模型版本字段。[TML](https://developers.thoughtspot.com/codespot/tml-python-library) |
| [厂商宣称] ThoughtSpot Spotter | 厂商称 Spotter 生成 TML 结构化查询，再由平台转 SQL 并执行行列安全；模型说明、business term 与 reference question 用于约束公式。[厂商说明](https://www.thoughtspot.com/blog/spotter-for-industries) | “deterministic / governed”是厂商说法；没有足够公开合同证明任意未定义查询都会机械拒绝。 | 厂商称 TML 可版本控制；未找到答案携带定义版本的证据。[厂商说明](https://www.thoughtspot.com/blog/spotter-semantics) |
| [实证] AtScale | SML 是存于 Git 的 YAML；每个 dataset / dimension / metric 有对象文件。模型发布后可由 JDBC / SQL、MDX / XMLA 使用。[SML](https://documentation.atscale.com/container/creating-and-sharing-cubes/working-with-models-programmatically/sml) [Git](https://documentation.atscale.com/container/managing-atscale/managing-git/about-git) | 经 AtScale 逻辑模型查询时只能消费已建模对象，但 SQL/MDX 可自由组合这些对象；本次未找到公开 MCP tool schema 足以证明硬拒绝细节。[AI 连接文档](https://documentation.atscale.com/container/connecting-with-ai) | Git 记录模型变更，SML 有格式版本（如 1.3）；格式版本不等于每个 metric 的业务口径版本。[release notes](https://documentation.atscale.com/container/release-notes/C2025.8/new-features-and-improvements) |
| [厂商宣称] AtScale MCP | 厂商博客把工具描述为 List models / Describe model / Run query，agent 看 dimension、metric、hierarchy、description、synonym 而非物理 join。[厂商博客](https://www.atscale.com/blog/autonomous-ai-semantic-layer-governance/) | “deterministic”与性能效果缺少本次可复现实测，只能作为产品主张。 | 未见回答级 definition version。 |
| [厂商宣称] Kyligence | 产品页称语义模型含 dimension / measure / hierarchy，经 ODBC / JDBC SQL 或 XMLA / MDX 暴露，并做自动预计算；新闻稿称 ZenML 是 YAML。[产品页](https://kyligence.io/unified-semantic-layer/) [ZenML 新闻稿](https://kyligence.io/news/kyligence-announces-the-general-availability-of-its-intelligent-metrics-platform/) | 当前公开材料不足以回答 agent 拿目录还是表结构、未定义内容是否拒绝。 | 当前公开材料不足以确认 metric 口径版本和回答血缘；不能用“通常用 Git”补齐。 |

### B6. 横向答案

[推测] 声明式配置是主流：YAML / LookML / SML / TML 加少量 JS/代码扩展；真正差异不在“配置还是代码”，而在配置约束到哪一级——成员、指标，还是完整分析产品。[Cube](https://docs.cube.dev/docs/introduction) [dbt](https://www.getdbt.com/blog/how-the-dbt-semantic-layer-works) [Looker](https://docs.cloud.google.com/looker/docs/lookml-terms-and-concepts) [AtScale](https://documentation.atscale.com/container/creating-and-sharing-cubes/working-with-models-programmatically/sml)

[推测] Agent 通常拿的是“带业务元数据的逻辑目录”，但目录粒度不同：dbt MCP 有明确 metric tools，Looker 是 Explore fields，Snowflake 和 Cube 同时暴露逻辑 table / dimension / metric。它们没有普遍收敛为一种标准 agent contract。[dbt MCP](https://github.com/dbt-labs/dbt-mcp#tools) [Looker](https://docs.cloud.google.com/looker/docs/conversational-analytics-overview) [Snowflake YAML](https://docs.snowflake.com/en/user-guide/views-semantic/semantic-view-yaml-spec) [Cube Meta API](https://docs.cube.dev/reference/rest-api#tag/Meta)

[推测] “未定义的东西能不能查”不能给厂商一个二元标签：语义成员通常 fail-closed，公开成员的组合/派生往往 fail-open，原始 SQL 旁路又可能完全开放。正确评估单位是**某个凭据下的一组 agent tools**，而不是厂商 logo。[Cube Workbooks](https://docs.cube.dev/docs/explore-analyze/workbooks/index) [dbt MCP](https://github.com/dbt-labs/dbt-mcp#tools) [Snowflake querying](https://docs.snowflake.com/en/user-guide/views-semantic/querying)

[推测] 口径变更普遍依赖 Git / DDL / deployment 审计，却很少把定义版本带进每个答案；这一点本仓库的 versioned envelope 更强，但前提是 `schema_version` 真正随语义变化升级，而不只是结构版本。[Cube](https://docs.cube.dev/docs/introduction) [Looker](https://docs.cloud.google.com/looker/docs/version-control-and-deploying-changes) [本仓库闭环判据](../analysis-journeys.md)

## C. 三条路线对比

下表是工程判断，不是 benchmark；每行依据是上文公开实现与失败证据。

| 维度 | text-to-SQL | 语义层 / 指标层 | 上游预计算（本仓库） |
|---|---|---|---|
| [推测] 正确性保证 | 最弱；语法可验证，意图正确难证明，且会静默错。[FLEX](https://aclanthology.org/2025.naacl-long.228/) | 中；join / metric / ACL 可确定，NL 到成员及临时组合仍会错。[Looker](https://docs.cloud.google.com/looker/docs/conversational-analytics-overview) | 已建动线最强；字段投影和 envelope 可 fail-closed，但上游算法/合同本身仍需证据。[本仓库判据](../analysis-journeys.md) |
| [推测] 口径一致性 | 低，除非把规则塞进上下文 / golden SQL。 | 高；中心化 metric / dimension / join。 | 最高但最窄；完整分析产品固化。[Google](https://cloud.google.com/blog/products/databases/techniques-for-improving-text-to-sql) [Cube](https://docs.cube.dev/docs/introduction) |
| [推测] 新问题覆盖 | 最广，理论上 schema 能表达就可尝试。 | 中高；可组合已公开成员，必要时加 metric / view。 | 最低；未建动线就是 capability gap。[Snowflake](https://docs.snowflake.com/en/user-guide/views-semantic/querying) [本仓库](../analysis-journeys.md) |
| [推测] 实现成本 | 原型低，生产高：检索、评测、重试、安全、人工验证持续叠加。[Google Cloud](https://cloud.google.com/blog/products/databases/techniques-for-improving-text-to-sql) | 前期建模高，随后复用；还要治理口径与权限。 | 每条动线前期和维护成本最高，还要合同、投影、四交付面与证据。 |
| [推测] 上游请求成本 | 候选、dry-run、重试会放大请求；难给固定上界。 | 通常一次逻辑查询；复杂 NL 可能多查询，预聚合可降仓库成本。[Cube](https://docs.cube.dev/docs/introduction) | 已知输入可声明固定调用数，缓存/上游产品若存在可复用；新能力建设成本不计入单次调用。 |
| [推测] 出错表现 | 语法错会报错，语义错常静默。 | 未建模成员多报错；选错已建模成员仍会静默错。 | 未登记字段/动线应明确 gap；已登记错误更容易分类，但陈旧或错误口径仍可能稳定地给错数。[FLEX](https://aclanthology.org/2025.naacl-long.228/) [本仓库](../analysis-journeys.md) |
| [推测] 调用方心智负担 | 最高：要看 SQL、表、方言、可信度。 | 中：要理解 metric / dimension、允许组合和 freshness。 | 主干最低：选产品、填参、读 envelope；长尾则直接面对 gap。[dbt MCP](https://github.com/dbt-labs/dbt-mcp#tools) [本仓库](../analysis-journeys.md) |

### 覆盖广度：本仓库真正落后的地方

[实证] 本仓库当前权威台账是 47 条产品动线：32 闭环、0 部分、15 完全缺失；多数缺口受数据、合同或安全证据阻塞。闭环要求 CLI / SDK / Plan / Agent 卡可达、带 `schema_version`、区分空/部分失败/能力缺口、未登记字段 fail-closed。[分析动线台账](../analysis-journeys.md)

[推测] 这意味着覆盖不是“慢一点”，而是离散的：一个新问题若不能映射到 32 条已闭环动线，即使仓库已有相关原始字段，调用方仍可能拿到明确 capability gap。相对语义层可在已建 dimension / metric 上组合新切片，本仓库目前缺少中间层的组合自由度。[分析动线台账](../analysis-journeys.md) [Snowflake ad-hoc metric](https://docs.snowflake.com/en/user-guide/views-semantic/querying)

[实证] 别人的长尾处理主要有四种：Cube 在受治理 metric 上允许 Semantic SQL 派生，另设 Source SQL；dbt MCP 同时给 `query_metrics` 与 `text_to_sql`；Snowflake 用语义模型 + VQR 生成 SQL，歧义时返回 suggestions；AWS 样例让 Tier 1 已发布 metric 命中失败后落到 Tier 2 的 ontology / metadata SQL 生成与验证图。[Cube](https://docs.cube.dev/docs/explore-analyze/workbooks/index) [dbt](https://github.com/dbt-labs/dbt-mcp#tools) [Snowflake](https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-analyst/rest-api) [AWS](https://github.com/aws-samples/sample-semantic-layer-structured)

[推测] 共同代价是主干和长尾不再同等可信。若响应不保存“走了哪条路”，用户会把动态生成答案误认成治理指标；因此扩大覆盖必须与来源分级一起做，不能只新增一个更自由的工具。[Snowflake `verified_query_used`](https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-analyst/rest-api) [AWS `provenance.tier`](https://github.com/aws-samples/sample-semantic-layer-structured)

## D. 混合形态已经存在

[实证] **Snowflake** 把 semantic model / view、Verified Query Repository 和动态 text-to-SQL 组合在同一 Cortex Analyst 响应中；`confidence.verified_query_used` 明确为对象或 `null`，是目前最接近“调用方知道这次是否用了已验证路径”的正式 API。[Snowflake REST](https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-analyst/rest-api)

[实证] **AWS 官方样例**更明确地分层：Tier 1 对已发布 metric 做 embedding 匹配（阈值 0.85），命中后执行预验证 `compiled_sql`；否则 fail-soft 到 Tier 2 的检索、澄清、SQL/SPARQL 生成、grounding gate 与有界执行。Metric 有 `metric_id`、`supported_dimensions` / `supported_filters`、DRAFT → APPROVED → PUBLISHED、`version`；每个回答持久化 `provenance.tier`，监控按 metric / semantic / advisory / agentic 分类。它是样例架构，不是成熟度或生产效果证明。[AWS sample README](https://github.com/aws-samples/sample-semantic-layer-structured)

[实证] **dbt MCP** 的混合最简单：工具名本身区分 `query_metrics` 和 `text_to_sql` / `execute_sql`。如果宿主保留 MCP tool-call provenance，调用方可以知道路径；README 没有定义一个统一结果 envelope 来保证该血缘永远保留。[dbt-mcp](https://github.com/dbt-labs/dbt-mcp#tools)

[实证] **Cube** 在同一 Workbook 明确区分 Semantic Query 与 Source SQL Query，后者文档直说 bypass semantic layer；这是 UI / tab 级来源区分，不是本次找到的回答级机器合同。[Cube Workbooks](https://docs.cube.dev/docs/explore-analyze/workbooks/index)

[实证] **Uber Finch** 是“受控数据面 + 动态 SQL”的实际内部形态：领域化单表 data mart、semantic metadata、别名检索之后才让 LLM 生成和执行 SQL，并给用户 SQL details / result link；高风险答案仍规划人工验证。它没有公开统一可信度字段。[Uber Finch](https://www.uber.com/hr/en/blog/unlocking-financial-insights-with-finch/)

[推测] 混合产品已很多，**标准化可信度血缘仍很少**。最可借鉴的不是一个概率分，而是离散且可审计的来源：命中哪个已发布定义、定义版本、是否动态生成、执行了什么、验证到哪一级、是否允许据此作业务断言。近期选择性预测研究即使用两家 LLM judge，回答 27% 问题时 selective risk 仍为 24%，不支持把“模型自信度”当成硬合同。[选择性预测研究](https://arxiv.org/abs/2607.06799)

## 对本仓库的意义

### 1. 有没有同路人

[推测] **有同方向，没有完全同形态。** Looker、Cube、Snowflake、dbt、AtScale 都证明“让 agent 选受治理逻辑对象而非物理 join”是主流工程路线；Uber Finch 证明财务场景会主动上推到领域单表 data mart；AWS 样例甚至有已发布 metric、预验证 SQL、version 和 provenance tier。没有找到另一家公开产品同时做到“完整分析动线上游算好 + 每条输出投影登记 + 未登记字段 fail-closed + 每个结果带本仓库式 schema_version”。[Looker](https://docs.cloud.google.com/looker/docs/conversational-analytics-overview) [Finch](https://www.uber.com/hr/en/blog/unlocking-financial-insights-with-finch/) [AWS](https://github.com/aws-samples/sample-semantic-layer-structured)

[推测] 本仓库比通用语义层强的地方是闭环动线的可判定失败、固定交付面和输出合同；弱的地方是把新问题覆盖也绑定到“先造完整产品”，边际扩展比增加一个 metric / saved query 更重。[本仓库闭环判据](../analysis-journeys.md) [dbt saved queries / metrics](https://github.com/dbt-labs/dbt-mcp#tools)

### 2. 长尾有什么可安全借鉴

[推测] 第一优先是**受治理的组合层**，不是自由 text-to-SQL：允许 Agent 在已登记 metric、dimension、time grain、filter operator、join path 白名单内组成查询，编译器继续拒绝未登记成员。它能覆盖“同指标换切片/时间粒度/过滤”的长尾，又不把原始表暴露给模型。[Snowflake ad-hoc metric](https://docs.snowflake.com/en/user-guide/views-semantic/querying) [Looker field-selection](https://docs.cloud.google.com/looker/docs/conversational-analytics-overview)

[推测] 第二优先是**已验证查询 / saved query**：给常见但尚不值得做完整 composite 的问题一个有 owner、输入 schema、输出投影、版本和测试的中间产品；不能只是存一段 SQL 字符串。[Snowflake VQR](https://docs.snowflake.com/en/user-guide/views-semantic/verified-query-repository) [dbt `list_saved_queries`](https://github.com/dbt-labs/dbt-mcp#tools)

[推测] 第三优先才是**隔离的探索层**：复用现有 `gravity sql query` 的注册、只读、投影、行数与禁止断言机制；探索层不得伪装成 Insight 产品，默认不进入自动决策，且须返回生成 SQL、上游请求数、验证步骤和人工确认要求。[CLI SQL 产品](../reference/cli.md) [AWS SELECT-only 与 tier](https://github.com/aws-samples/sample-semantic-layer-structured)

### 3. 能否不放弃 fail-closed 而扩大覆盖

[推测] 可以，但要把 fail-closed 从“只有完整动线”细化为三层合同；分层依据是 Snowflake 的 verified-query 来源字段、AWS 的 provenance tier 和本仓库现有的动线合同：[Snowflake](https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-analyst/rest-api) [AWS](https://github.com/aws-samples/sample-semantic-layer-structured) [本仓库](../analysis-journeys.md)

1. **Tier A — governed journey**：现有 32 条闭环；`schema_version`、字段投影、错误分类和调用数不变。
2. **Tier B — governed composition**：只允许已登记 metric / dimension / filter / grain / join path；编译出计划，未知成员或不安全组合直接 `capability_gap`。
3. **Tier C — governed exploration**：只允许注册 custom-SQL 产品和批准的数据面；明确 `generated`、不得内置业务口径、不得自动升级为 Tier A/B 结论。

这一分层借鉴了 Snowflake 的 `verified_query_used`、AWS 的 `provenance.tier` 和 dbt 的工具分组，但保留本仓库“未知即拒绝”的合同边界。[Snowflake](https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-analyst/rest-api) [AWS](https://github.com/aws-samples/sample-semantic-layer-structured) [dbt](https://github.com/dbt-labs/dbt-mcp#tools)

[推测] 建议的最小机器字段是：`resolution_tier`、`definition_id`、`definition_version`、`semantic_members`、`generated_sql`（可空）、`validation`（syntax / projection / execution / human）、`allowed_claims`、`call_count`。其中 `definition_version` 解决本次横向调研普遍缺失的“结果用了哪版口径”；`allowed_claims` 防止探索结果被误作受治理业务结论。[Snowflake confidence](https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-analyst/rest-api) [AWS metric version / provenance](https://github.com/aws-samples/sample-semantic-layer-structured)

[推测] 明确不建议三件事：不给现有 Agent 卡静默增加 raw `text_to_sql`；不把“SQL 执行成功”升级成“分析正确”；不以一个未经校准的 confidence 数字替代来源等级和 fail-closed。三者分别会破坏工具边界、混淆运行与语义正确、以及制造伪精确。[dbt 双路径](https://github.com/dbt-labs/dbt-mcp#tools) [FLEX](https://aclanthology.org/2025.naacl-long.228/) [选择性预测研究](https://arxiv.org/abs/2607.06799)

## 没能查到的关键问题

[实证] 没有找到独立、公开、可审计的企业 text-to-SQL 错数事故复盘；公开材料只能证明静默失败机制和内部团队的防护设计，不能量化真实业务损失。本次来源与失败记录位于本地 `tmp/codex/r3-semantic-layer/sources/manifest.md`。

[实证] 没有找到能把 NULL、大小写、去重、时区、自然周/月等单项错误按生产频率拆开的代表性数据集或事故统计。本次论文来源清单位于本地 `tmp/codex/r3-semantic-layer/sources/manifest.md`。

[实证] 没有找到 Cube 公共 MCP 的精确 tool 名称 / JSON schema；只确认官方支持 MCP、Chat 和 Meta API。[Cube Core Data APIs](https://docs.cube.dev/reference/core-data-apis)

[实证] 没有找到 ThoughtSpot Spotter 对未定义字段/公式的硬拒绝合同，也没有找到回答级模型版本或来源字段；现有“deterministic”主要是厂商主张。[TML 公开技术面](https://developers.thoughtspot.com/codespot/tml-python-library) [Spotter 厂商说明](https://www.thoughtspot.com/blog/spotter-semantics)

[实证] 没有找到 Kyligence 当前公开、无需身份的 agent API、fail-open / fail-closed 规则和 metric 版本血缘文档。[当前公开产品页](https://kyligence.io/unified-semantic-layer/)

[实证] 没有找到 Cube、dbt、Looker、AtScale 在每个查询结果中携带业务定义版本的统一合同；能确认的是 Git / deployment / artifact 格式版本。[Cube](https://docs.cube.dev/docs/introduction) [dbt](https://docs.getdbt.com/reference/artifacts/manifest-json) [Looker](https://docs.cloud.google.com/looker/docs/version-control-and-deploying-changes) [AtScale](https://documentation.atscale.com/container/managing-atscale/managing-git/about-git)

[推测] 最可能出错的判断是“Snow 96.70% 表明准备充分的企业 text-to-SQL 已接近饱和”。原因是该榜单动态变化、提交透明度不一，而新研究又报告 Snow 标注错误率很高；当前分数是真实页面事实，但它对生产成熟度的外推非常脆弱。[Spider 2 榜单](https://spider2-sql.github.io/) [标注错误研究](https://arxiv.org/abs/2601.08778)

## 证据单元计数

全文方括号标签由命令 `rg -o '\[(实证|厂商宣称|推测)\]'` 机械计数：**实证 61 条、厂商宣称 3 条、推测 30 条，共 94 条**（64.9% / 3.2% / 31.9%）。
