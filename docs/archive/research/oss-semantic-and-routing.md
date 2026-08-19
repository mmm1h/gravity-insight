> 归档材料：保留历史决策与取证，不代表当前接口或状态；当前入口见 docs/index.md。

# GitHub 开源调研：语义层与能力路由

> 调研日期：2026-08-16。本文只研究开源实现如何表达语义、校验引用、选择能力和组织大工具集；不把外部项目的接口当作 Gravity SDK 的行为合同。

## 结论先行

[实证] 开源语义层的主流不是“同义词指向对象”的独立注册表，而是把 `description`、`label`、自由文本 AI hint 或任意 metadata 附着在模型、字段或 view 上。Cube 的 `ai_context` 甚至明确是 view/member 作用域；MetricFlow、Malloy、Boring Semantic Layer（BSL）都没有一等公民的自然语言同义词字段。`gravity.semantic-context.v1` 的 `terms[].phrases → typed target` 因而不是照抄主流，而是更强类型、也更需要处理冲突和演进的选择。[Cube AI context 源文档](https://github.com/cube-js/cube/blob/9d391ab6391fee9d8a6e3ce06452e6afaa3bffca/docs-mintlify/docs/data-modeling/ai-context.mdx)、[MetricFlow Dimension](https://github.com/dbt-labs/metricflow/blob/d57390c2fbc23e1297f3a9928e956d551734c92c/metricflow_semantic_interfaces/implementations/elements/dimension.py)、[Malloy annotations](https://github.com/malloydata/malloy/blob/cfd1828472b5bbf26bf87b1158bdc6d28ad6e207/packages/malloy/src/api/foundation/annotation.ts)、[BSL ops](https://github.com/boringdata/boring-semantic-layer/blob/57170db6419f5e68d3b68631f0ef164422720dc9/src/boring_semantic_layer/ops.py)

[实证] 对已登记对象的引用，Cube、MetricFlow 和 Malloy 都在编译或 manifest 校验阶段报错；MetricFlow 还把多个合法 join path 明确建模为歧义错误，而不是任选一个。BSL 的部分名称解析发生在查询期，但未知模型、字段和歧义同样 fail-closed。Gravity 的“workspace 加载 + Agent preflight”两段校验比这些实现并不松，反而对依赖本地 metadata 的目标多了一道运行前闸门。[Cube validator](https://github.com/cube-js/cube/blob/9d391ab6391fee9d8a6e3ce06452e6afaa3bffca/packages/cubejs-schema-compiler/src/compiler/CubeValidator.ts)、[MetricFlow saved-query validation](https://github.com/dbt-labs/metricflow/blob/d57390c2fbc23e1297f3a9928e956d551734c92c/metricflow_semantic_interfaces/validations/saved_query.py)、[Malloy query reference](https://github.com/malloydata/malloy/blob/cfd1828472b5bbf26bf87b1158bdc6d28ad6e207/packages/malloy/src/lang/ast/query-elements/query-reference.ts)、[BSL resolution](https://github.com/boringdata/boring-semantic-layer/blob/57170db6419f5e68d3b68631f0ef164422720dc9/src/boring_semantic_layer/ops.py)

[实证] 没有在所查语义层中找到与 `verified_queries[].question` 同形的“整句精确命中后执行完整调用”。MetricFlow saved query 和 Malloy named query 保存的是结构化查询；Semantic Router 的 `utterances` 是 embedding 训练/检索样例，不是精确字符串快捷键。因此现有 verified query 不是已被证明错误，但它是最偏离开源常见形态、最容易退化成句子表的一处。[MetricFlow saved query](https://github.com/dbt-labs/metricflow/blob/d57390c2fbc23e1297f3a9928e956d551734c92c/metricflow_semantic_interfaces/implementations/saved_query.py)、[Malloy define query](https://github.com/malloydata/malloy/blob/cfd1828472b5bbf26bf87b1158bdc6d28ad6e207/packages/malloy/src/lang/ast/statements/define-query.ts)、[Semantic Router route](https://github.com/aurelio-labs/semantic-router/blob/a4576168d9589397a7e0c6ff77f5d05469a56e2e/semantic_router/route.py)

[实证] 开源能力路由没有单一赢家。LangChain 当前提供“先让一个 LLM 结构化选出若干工具，再把子集交给主模型”的两段式；LlamaIndex 同时保留 embedding top-1、LLM single/multi selector 和 tool retriever；Semantic Router 用多条 utterance 的 dense/hybrid 检索、每 route 阈值、abstain 和可选多结果。共同点是候选描述/样例被当成数据，确定性代码负责阈值、合法名称和失败策略，而不是持续扩张手写关键词分支。[LangChain LLM tool selector](https://github.com/langchain-ai/langchain/blob/9a5810712658bdb9ad91925d3242032822f54a5e/libs/langchain_v1/langchain/agents/middleware/tool_selection.py)、[LlamaIndex selectors](https://github.com/run-llama/llama_index/blob/afd0fef371831f9bda13e5af7167cf4e981278ab/llama-index-core/llama_index/core/selectors/embedding_selectors.py)、[Semantic Router](https://github.com/aurelio-labs/semantic-router/blob/a4576168d9589397a7e0c6ff77f5d05469a56e2e/semantic_router/routers/base.py)

[厂商宣称] “大工具集必然在 30 个处断崖”没有可复用的公开阈值证据。MCP-Atlas 论文称总目录有 220 个工具，但每题实际只暴露 6–37 个、均值 15.2 个；它不能证明模型在 220 个同时可见时的选择能力。[MCP-Atlas](https://arxiv.org/html/2602.00933#S3.SS2)

[实证] GitHub MCP Server 的源码注释称全量约 90 个工具，却靠 toolset、read-only 和显式单工具过滤缩小暴露面；AWS Labs 更直接拆成 60 多个领域 server。源码能证明的是“主动约束候选面”的实现存在，不是一个普适数量阈值。[GitHub inventory](https://github.com/github/github-mcp-server/blob/0ea1f775a7c73eff1bd2e25904d01136756bbfe2/pkg/inventory/registry.go)、[AWS Labs 源码树](https://github.com/awslabs/mcp/tree/6d289e1281fb20512b0fc7db7a917c4bccdaf53c/src)

[厂商宣称] 唯一直接给出“关键词 → embedding 检索”效果差的资料是 RAG-MCP 论文：作者报告同一实验中 keyword actual match 为 18.20%、retrieval 为 43.13%、全量为 13.62%。但论文没有链接可复现实验代码；社区同名仓库也不是论文作者仓库，其测试装置与 README 数字互相对不上。因此它只能作为方向性证据，不能据此直接替换 Gravity recognizer。[RAG-MCP 论文](https://arxiv.org/abs/2505.03275)、[社区评测代码](https://github.com/memoverflow/rag-mcp/blob/5fc52e9ddfb27690002342c715655999100e8cae/test/evaluator.py)

[推测] 对 193/240（80.4%）的结论应是“证据支持把 embedding 与结构化 LLM selector 纳入冻结题集 A/B，但证据不足以支持无对照地撤掉 recognizer”。替代方案的代价包括模型/embedding 版本依赖、阈值校准、额外延迟与费用、非确定性、候选索引同步，以及新的 malformed-output/低置信失败面；确定性的 schema、引用、权限和执行前校验仍应保留。

[实证] C 节找到两个比上一轮更完整的第三方先例，但仍没有找到“成熟且完整”的同类客户端：`navikt/amplitude-data-wrapper` 是活跃但仅 9 个顶层函数的 Amplitude 多 API wrapper；`Drakkar-Software/posthog-openapi-clients` 生成了 58 个 service、782 个 model 的广覆盖 PostHog TypeScript facade，却是 `0.0.12`、仓库无测试。另一个 Mixpanel Ruby client 只是接受任意 resource 字符串的薄 HTTP 层，最后更新于 2023 年。故“存在完整生成面”成立，“找到成熟第三方完整客户端”仍不成立。[Amplitude wrapper](https://github.com/navikt/amplitude-data-wrapper/blob/7768c2b08d58d56fed9466c4572cc2e01d71cda6/src/amplitude_data_wrapper/analytics_api.py)、[PostHog client](https://github.com/Drakkar-Software/posthog-openapi-clients/blob/e41454edf4e644c0848fb36050818fc1d2fa811c/client/typescript/PosthogAPIClient.ts)、[Mixpanel client](https://github.com/keolo/mixpanel_client/blob/c3c3a73c82d760e522233cf5be9abed1047995f2/lib/mixpanel/client.rb)

## 方法、范围与证据边界

[实证] 本次先读取本仓库 `dev` 上已经落地的 `gravity.semantic-context.v1` 实现与 workspace 文档，只用于建立内部比较基线；没有读取或运行留出集，也没有改动源码。外部取证使用公开网页、GitHub issue/PR、论文原文和 15 个浅克隆源码快照；搜索摘要只用于定位，未作为证据。

[实证] 源码快照固定在以下 commit，文中源码链接均指向这些 immutable revision：Cube `9d391ab`、MetricFlow `d57390c`、Malloy `cfd1828`、BSL `57170db`、Lightdash `afab963`、LangChain `9a58107`、LlamaIndex `afd0fef`、Semantic Router `a457616`、MCP-Atlas `f24ba3f`、GitHub MCP Server `0ea1f77`、AWS Labs MCP `6d289e1`、RAG-MCP 社区实现 `5fc52e9`、Amplitude wrapper `7768c2b`、PostHog client `e41454e`、Mixpanel client `c3c3a73`。

[实证] 标签口径比此前文档更严格：只有实际读过源码、测试、issue 或 PR 的项目事实标为 `[实证]`；README、项目主页和未附可复现代码的论文自报效果一律降为 `[厂商宣称]`；跨项目推导及对 Gravity 的建议标为 `[推测]`。

[实证] A 节覆盖用户指定的 Cube、dbt MetricFlow、Malloy、Boring Semantic Layer，并补充 Lightdash；B 节覆盖 LangChain、LlamaIndex、Semantic Router、Toolshed、RAG-MCP、MCP-Atlas，以及 GitHub/AWS 的大工具集组织；C 节对 Amplitude、Mixpanel、PostHog、Heap 关键词做 GitHub repository 检索，并深入阅读三个最接近的候选。

[实证] 没有登录 GitHub、没有写 issue/PR、没有调用任何分析生产 operation。论文数字被保留只是为了说明公开声称与证据强弱，不会与源码可复核结果混写。

## A. 语义层 / 指标层开源实现

### 横向答案

[实证] 下表把用户提出的五个问题压到同一口径；“未找到”表示在固定 commit 的 schema、实现、测试和定向 issue/PR 检索中未发现，不等价于证明所有历史版本都不存在。

| 项目 | 同义词 / 别名 | 不存在引用 | verified query 同类物 | 冲突优先级 | 最有价值的坑 |
| --- | --- | --- | --- | --- | --- |
| [实证] [Cube](https://github.com/cube-js/cube/tree/9d391ab6391fee9d8a6e3ce06452e6afaa3bffca) | `description` 与自由文本 `meta.ai_context`；view include 可覆盖 member 上下文。没有语言、数值优先级或 typed synonym target | schema compile 聚合错误并抛出；未解析 view/member 失败 | 未找到一等公民的自然语言整句绑定 | view override 赢；除此没有调用方/内置规则总表 | cube-level `ai_context` 不会自动传播到 view；alias 间接引用曾崩溃或静默丢计算维度 |
| [实证] [MetricFlow](https://github.com/dbt-labs/metricflow/tree/d57390c2fbc23e1297f3a9928e956d551734c92c) | element 有 `label`/`description`；`alias` 是查询输出名，不是 NL 同义词 | manifest validation 报 missing measure/metric；多 join path 报 ambiguity | `saved_query` 保存 metrics/group-by/filter/order/limit，不保存问句 | 没有 caller-vs-built-in 概念；歧义要求更具体输入 | 同名维度经不同 join path 会歧义；逻辑等价的 primary/foreign 路径仍可能失败 |
| [实证] [Malloy](https://github.com/malloydata/malloy/tree/cfd1828472b5bbf26bf87b1158bdc6d28ad6e207) | 任意 `#(route)` annotation，由消费应用解释；无内置 synonym schema | undefined named query / field 在翻译期记 error | named query 是结构化查询；不是问句 | annotation 继承，但应用自定义 route 的业务优先级不由 Malloy 定义 | annotation API 重命名迁移涉及约 60 个文件，回归测试还抓到一次静默对象简写错误 |
| [实证] [BSL](https://github.com/boringdata/boring-semantic-layer/tree/57170db6419f5e68d3b68631f0ef164422720dc9) | description + 任意 metadata；无 synonym 字段 | 解析模型/字段/分组键时 fail-closed；歧义报错 | 无运行时问句绑定；eval questions 只是测试 | 声明 dimension 覆盖 raw column；其他 caller conflict 未定义 | 旧序列化遗漏 join cardinality 后默认成 `one`，升级可静默改变聚合结果 |
| [实证] [Lightdash](https://github.com/lightdash/lightdash/tree/afab9635481dd3e32a9f1895f37ca83bde08a920) | table/field `aiHint` 转为 `string[]`；无 typed target、语言或优先级 | 当前 explore 已删但 catalog 尚存的 table/field 被返回 `null` 静默跳过 | 未找到问句绑定 | 继承 explore hint；未找到通用冲突规则 | catalog 与当前模型短暂不一致时选择容忍 stale entry，而不是令整个加载失败 |

### Cube：自由文本有作用域，作用域会成为真实故障面

[实证] Cube validator 给 measure/dimension 提供 `title`、`description` 和任意 `meta`；`ai_context` 并非独立 schema，而是约定放在 `meta` 里的自由文本。view include 的生成代码会用 include override 覆盖原 member 的 title、description、format、meta 等，因此作用域是“同一 member 在不同 view 可拥有不同解释”。[Cube validator](https://github.com/cube-js/cube/blob/9d391ab6391fee9d8a6e3ce06452e6afaa3bffca/packages/cubejs-schema-compiler/src/compiler/CubeValidator.ts)、[Cube symbols](https://github.com/cube-js/cube/blob/9d391ab6391fee9d8a6e3ce06452e6afaa3bffca/packages/cubejs-schema-compiler/src/compiler/CubeSymbols.ts)

[实证] PR #10715 专门修正文档，说明 cube-level `ai_context` 不会传播到 view；维护者把“同义词/缩写写在 cube 上，但 Agent 只看 view”称为常见误配。这直接证明“语义配置有了继承层次后，作者以为生效、实际不可见”是现实风险。[Cube PR #10715](https://github.com/cube-js/cube/pull/10715)

[实证] Issue #10856 记录 multi-stage measure 通过 aliased view 引用 `order_by` 时编译崩溃；讨论还指出旧路径会静默丢掉 `reduce_by`/`group_by`，从而产生错误数值。别名不是纯展示字段：一旦能参与引用，它就进入编译器、所有权和计算正确性边界。[Cube issue #10856](https://github.com/cube-js/cube/issues/10856)

[推测] 对 Gravity 的警示不是“也要照搬 view scope”，而是如果未来给 `terms` 加 app/domain/locale 作用域，必须让最终可见语义可检查，并把继承/覆盖纳入编译产物；仅在配置上增加 `scope` 字段不够。

### MetricFlow：saved query 是结构，不是句子；歧义被保留为错误

[实证] MetricFlow 的 Dimension/Entity/Measure 接口只有 name、label、description、metadata/config 等字段，没有一等公民 synonym 列表；metric input 的 `alias` 用于聚合后的 SQL/引用名称，不是用户问法。[Dimension](https://github.com/dbt-labs/metricflow/blob/d57390c2fbc23e1297f3a9928e956d551734c92c/metricflow_semantic_interfaces/implementations/elements/dimension.py)、[Metric](https://github.com/dbt-labs/metricflow/blob/d57390c2fbc23e1297f3a9928e956d551734c92c/metricflow_semantic_interfaces/implementations/metric.py)

[实证] `SavedQuery` 明确保存 metrics、group_by、where、order_by、limit 及 export；validator 在 manifest 阶段检查 metric 是否存在、group-by 名称是否合法、order-by 是否来自查询项、limit 是否非负。它解决的是“已验证查询结构的复用”，而非“哪一句话触发它”。[SavedQuery](https://github.com/dbt-labs/metricflow/blob/d57390c2fbc23e1297f3a9928e956d551734c92c/metricflow_semantic_interfaces/implementations/saved_query.py)、[validation](https://github.com/dbt-labs/metricflow/blob/d57390c2fbc23e1297f3a9928e956d551734c92c/metricflow_semantic_interfaces/validations/saved_query.py)

[实证] group-by resolver 对多个候选返回带候选列表的 ambiguity error；multiple-join-path error 要求调用者提供更具体输入。Issue #963 的维护者暂行建议甚至是隐藏存在歧义 join path 的维度，而不是猜一条；Issue #1780 又显示“语义上等价”的 primary/foreign 路径仍可能被实现判成不可查询。[Ambiguous group-by](https://github.com/dbt-labs/metricflow/blob/d57390c2fbc23e1297f3a9928e956d551734c92c/metricflow_semantics/query/issues/group_by_item_resolver/ambiguous_group_by_item.py)、[multiple join paths](https://github.com/dbt-labs/metricflow/blob/d57390c2fbc23e1297f3a9928e956d551734c92c/metricflow_semantics/query/issues/group_by_item_resolver/multiple_join_paths.py)、[issue #963](https://github.com/dbt-labs/metricflow/issues/963)、[issue #1780](https://github.com/dbt-labs/metricflow/issues/1780)

[推测] 这支持 Gravity 保留 `MULTIPLE_INTENTS`，但也提示要区分“真的有两种业务含义”和“同一含义通过两条物理路径到达”；后者若全交给用户消歧，会把实现限制暴露成业务问题。

### Malloy：开放 annotation 把语义所有权交给消费应用

[实证] Malloy annotation 允许 `#(myApp)` 这类任意 route，并提供继承、解析与按 route 读取；内置只理解少量 route，应用 route 的 payload 和优先级由消费方解释。格式错误可产生 warn/error，但 Malloy 不替应用判断“这个词是否应覆盖内置规则”。[Annotation API](https://github.com/malloydata/malloy/blob/cfd1828472b5bbf26bf87b1158bdc6d28ad6e207/packages/malloy/src/api/foundation/annotation.ts)

[实证] undefined named query 在翻译期记录 `query-reference-not-found`；duplicate named query 也是错误。named query 本身携带的是已编译查询定义及 annotation，不携带一组自然语言触发句。[Query reference](https://github.com/malloydata/malloy/blob/cfd1828472b5bbf26bf87b1158bdc6d28ad6e207/packages/malloy/src/lang/ast/query-elements/query-reference.ts)、[Define query](https://github.com/malloydata/malloy/blob/cfd1828472b5bbf26bf87b1158bdc6d28ad6e207/packages/malloy/src/lang/ast/statements/define-query.ts)

[实证] PR #2838 把多年并存的 deprecated annotation free functions 与含糊的单数 `Annotation` bundle 迁到 `Annotations`/`AnnotationsDef`，改动约 60 个文件；测试还发现一次对象字面量简写导致的数据静默错误。这是“开放 metadata API 很容易形成长期命名债和大范围迁移”的实证。[Malloy PR #2838](https://github.com/malloydata/malloy/pull/2838)

### Boring Semantic Layer：最小渐进发现很好，但序列化默认值曾改变数值

[实证] BSL 给 Agent 只暴露 `list_models`、`get_model`、`query_model`、`get_documentation` 四个通用工具；先列模型、再读取选中模型的字段描述、最后查询，属于显式 progressive discovery，而不是为每个指标注册一个工具。[BSL agent tools](https://github.com/boringdata/boring-semantic-layer/blob/57170db6419f5e68d3b68631f0ef164422720dc9/src/boring_semantic_layer/agents/tools.py)

[实证] BSL 的字段解析刻意拒绝未知模型/字段、非法 group key 和歧义；源码注释还解释，声明 dimension 会覆盖同名 raw column，因为让 raw column 悄悄穿透可能改变 measure 数值。这是优先级显式存在的少数例子，但它是“已声明语义对象 > 自动合成物理字段”，不是 caller > system。[BSL ops](https://github.com/boringdata/boring-semantic-layer/blob/57170db6419f5e68d3b68631f0ef164422720dc9/src/boring_semantic_layer/ops.py)

[实证] Issue #223 证明默认值可能比缺失引用更危险：旧序列化未写 join cardinality，重建器把缺失值默认成 `one`，导致旧 `join_many/cross` 模型升级后可能静默改变聚合；修复把缺失默认改为更保守的 `many`。当前重建源码保留了该 issue 的注释。[BSL issue #223](https://github.com/boringdata/boring-semantic-layer/issues/223)、[reconstruct.py](https://github.com/boringdata/boring-semantic-layer/blob/57170db6419f5e68d3b68631f0ef164422720dc9/src/boring_semantic_layer/serialization/reconstruct.py)

[实证] BSL 的 eval harness 虽会记录 question、transcript、token 和 tool call，但其“通过”主要等于没有 error，或出错后最终出现 success；它不验证答案语义正确。因此仓库中的 pass 不能当 tool-selection accuracy。[BSL eval](https://github.com/boringdata/boring-semantic-layer/blob/57170db6419f5e68d3b68631f0ef164422720dc9/src/boring_semantic_layer/agents/eval/eval.py)

### Lightdash：AI hint 是轻 schema，stale catalog 选择容忍

[实证] Lightdash 数据库迁移把 `ai_hints` 存为 nullable `TEXT[]`，catalog 类型暴露 `string[] | null`；parser 从 table/field 的 `aiHint` 转换，而没有 target kind/ref、locale 或 priority。[Migration](https://github.com/lightdash/lightdash/blob/afab9635481dd3e32a9f1895f37ca83bde08a920/packages/backend/src/database/migrations/20250725132323_add_ai_hints_to_catalog_search.ts)、[Catalog types](https://github.com/lightdash/lightdash/blob/afab9635481dd3e32a9f1895f37ca83bde08a920/packages/common/src/types/catalog.ts)

[实证] 当 catalog 中的 table/field 已不在当前 explore，parser 明确返回 `null` 跳过 stale entry。这是与 Gravity 两段 fail-closed 不同的工程选择：Lightdash 在索引最终一致性窗口里保可用，Gravity 对 workspace 声明的目标保确定性。[Lightdash parser](https://github.com/lightdash/lightdash/blob/afab9635481dd3e32a9f1895f37ca83bde08a920/packages/backend/src/models/CatalogModel/utils/parser.ts)

## B. 能力路由 / 工具选择开源实现

### 机制与歧义处理

[实证] 下表只描述源码实际控制流；“准确率”一栏没有数字时就是没有找到可归因到该机制的公开实测。

| 项目 | 选择机制 | 歧义 / 无匹配 | 可核查准确率 | 规模证据 |
| --- | --- | --- | --- | --- |
| [实证] [LangChain](https://github.com/langchain-ai/langchain/tree/9a5810712658bdb9ad91925d3242032822f54a5e) | legacy embedding top-1；当前 LLM middleware 先结构化选多个，再把子集给主模型 | LLM 可返回多个/零个；`max_tools` 截断；malformed 默认重试后报错，可配置 none/all/list fallback | 未找到该 middleware 的公开准确率 | 源码只说 many tools 时过滤；未给阈值 |
| [实证] [LlamaIndex](https://github.com/run-llama/llama_index/tree/afd0fef371831f9bda13e5af7167cf4e981278ab) | embedding top-1；LLM/function-calling single/multi；object retriever | multi selector 执行全部并汇总；embedding selector没有 abstain；tool retriever 取回即执行 | notebook 仅有 30 条 single-tool 的 Gemini 0.93/0.97，不是 selector 对照 | 未找到工具数退化曲线 |
| [实证] [Semantic Router](https://github.com/aurelio-labs/semantic-router/tree/a4576168d9589397a7e0c6ff77f5d05469a56e2e) | utterance embedding；dense/hybrid；按 route 聚合和阈值 | 阈值以下空 route；`limit=None` 可返回所有过阈值 route | notebook 有 34.85%→90.91%，但 fit/eval 同集 | 未找到独立 holdout 的数量阈值 |
| [厂商宣称] [Toolshed](https://arxiv.org/abs/2410.14594) | enriched tool document + query decomposition/rewriting + retrieval + rerank/self-reflection | top-k 候选；论文摘要未定义产品级追问策略 | 作者报告三个数据集 Recall@5 绝对提升 46/56/47 pp | 论文改变 tool-M/top-k；未找到官方代码仓库 |
| [厂商宣称] [RAG-MCP](https://arxiv.org/abs/2505.03275) | server-level embedding 检索，top-k 后可验证，最终只给 LLM 最佳 server | top-1，未见多意图返回 | 作者报告 43.13% vs keyword 18.20% vs all 13.62% | 作者称 <30 多数成功、>100 明显退化；无官方代码复现 |
| [实证] [MCP-Atlas harness](https://github.com/scaleapi/mcp-atlas/blob/f24ba3fb0bfa484c86acb28431fad6d7282455f9/services/agent-harness/src/mcp-agent/agent-evals/agent-eval.ts) | 不做外部 router；把任务环境列出的工具全部给模型循环调用 | 工具错误回填模型恢复；无调用可自然结束 | [厂商宣称] 论文报的是端到端 pass，不是独立选工具准确率 | [厂商宣称] 每题 6–37 工具、均值 15.2；不是同时 220 |

### LangChain：从单选 router 转向“两次模型调用 + 有界失败策略”

[实证] legacy `EmbeddingRouterChain` 为每个 destination 建多个 description 文档，查询时固定 `similarity_search(k=1)` 并直接取第一个结果；没有 threshold、空结果或多候选语义。旧 `LLMRouterChain` 已 deprecated，源码建议使用 agent/structured output，而不是维护旧 router chain。[Embedding router](https://github.com/langchain-ai/langchain/blob/9a5810712658bdb9ad91925d3242032822f54a5e/libs/langchain/langchain_classic/chains/router/embedding_router.py)、[LLM router](https://github.com/langchain-ai/langchain/blob/9a5810712658bdb9ad91925d3242032822f54a5e/libs/langchain/langchain_classic/chains/router/llm_router.py)

[实证] 当前 `LLMToolSelectorMiddleware` 把每个 tool name 做成带 description 的 Literal union，让 selector LLM 返回按相关性排序的 `tools[]`，可设 `max_tools` 和 `always_include`，随后才调用主模型。非法 tool name fail-closed；malformed 结构默认重试一次后报错，也能显式配置 none/all/固定列表 fallback。[Tool selector source](https://github.com/langchain-ai/langchain/blob/9a5810712658bdb9ad91925d3242032822f54a5e/libs/langchain_v1/langchain/agents/middleware/tool_selection.py)

[实证] Issue #34358 记录早期实现遇到模型偶发漏掉 `tools` key 时抛 `KeyError`、中断下游；当前源码才增加结构检查、重试和显式失败策略。这证明 structured output 仍需作为不可信输入处理，不能把“模型支持 schema”当成不会 malformed。[LangChain issue #34358](https://github.com/langchain-ai/langchain/issues/34358)

[实证] 没有在 LangChain 仓库找到该 selector 相对“不筛选”或手写规则的公开准确率，也没有工具数从 N 到 N+1 的退化曲线。

### LlamaIndex：允许多选，但 embedding top-1 默认会猜

[实证] `EmbeddingSingleSelector` 只 embedding `ToolMetadata.description`，固定 `similarity_top_k=1`，无 score threshold；因此任何非空 choices 都会产生一个答案。Pydantic multi selector 则让 function-calling model 返回多个索引，可用 `max_outputs` 限制。[Embedding selector](https://github.com/run-llama/llama_index/blob/afd0fef371831f9bda13e5af7167cf4e981278ab/llama-index-core/llama_index/core/selectors/embedding_selectors.py)、[Pydantic selectors](https://github.com/run-llama/llama_index/blob/afd0fef371831f9bda13e5af7167cf4e981278ab/llama-index-core/llama_index/core/selectors/pydantic_selectors.py)

[实证] `RouterQueryEngine` 对多个 selection 逐个执行并汇总；`ToolRetrieverRouterQueryEngine` 则把 retriever 返回的所有 tool 直接执行并汇总，没有“检索后再由 LLM 确认”这一段。也就是说 LlamaIndex 提供了多种组合原语，但没有强制一个统一的歧义政策。[Router query engine](https://github.com/run-llama/llama_index/blob/afd0fef371831f9bda13e5af7167cf4e981278ab/llama-index-core/llama_index/core/query_engine/router_query_engine.py)

[实证] 仓库 notebook 在 Galileo `xlam_single_tool_single_call` test split 只取前 30 条，让 ReActAgent 直接看当题 tools；提交输出显示 Gemini 2.5 Flash/Pro 的 tool-name 分数 0.93/0.97，argument-key 0.63/0.73，argument-value 0.36/0.31。它证明“选对工具名远早于填对参数”，但样本太小、只含 single-tool，也没有 manual/embedding baseline。[LlamaIndex benchmark notebook](https://github.com/run-llama/llama_index/blob/afd0fef371831f9bda13e5af7167cf4e981278ab/docs/examples/benchmarks/gemini_tool_selection_eval.ipynb)

[实证] Issue #14415 记录 `FunctionCallingProgram` 曾接收 `tool_choice` 参数却没有传下去，导致模型不调用工具而报零 tool call，直到后续 PR 修复。控制面参数若只是 schema 上存在、没有贯穿 adapter，也会形成假保证。[LlamaIndex issue #14415](https://github.com/run-llama/llama_index/issues/14415)

### Semantic Router：最接近可本地 A/B 的实现，也展示了错误评测示范

[实证] `Route` 包含 name、多个 utterance、description、可选 function schemas、LLM、每 route threshold 和 metadata。静态路由由 embedding 完成；function schema 存在时，选中 route 后才由 LLM 提取参数。动态 route 甚至可让 LLM 从函数 schema 生成每函数五条 utterance。[Route source](https://github.com/aurelio-labs/semantic-router/blob/a4576168d9589397a7e0c6ff77f5d05469a56e2e/semantic_router/route.py)

[实证] router 默认取 top-k=5 的 utterance，再按 route 聚合；每条 route 可有独立 threshold。默认 `limit=1` 返回最高通过者，`limit=None` 返回所有过阈值 route，没有任何通过者时返回空 `RouteChoice`。这比“永远 top-1”多了 abstain 和显式多结果，但并不自动判断多结果是不是需要追问。[BaseRouter](https://github.com/aurelio-labs/semantic-router/blob/a4576168d9589397a7e0c6ff77f5d05469a56e2e/semantic_router/routers/base.py)

[实证] `fit` 通过随机搜索每 route threshold 最大化 label accuracy；提交的 threshold notebook 先在较大集合得到 34.85%，随后对同一个 `X, y` 调 `fit`，又在同一个 `X, y` 上 `evaluate` 得 90.91%。这不是 unseen generalization，不能拿来与 Gravity 80.4% 留出集比较。[Threshold notebook](https://github.com/aurelio-labs/semantic-router/blob/a4576168d9589397a7e0c6ff77f5d05469a56e2e/docs/06-threshold-optimization.ipynb)

[实证] 没有找到 Semantic Router 在公开、独立 holdout 上按工具数量报告的 accuracy，也没有与 LLM selector 的同题对照。

### 检索工作：有方向性数字，但复现链断裂

[厂商宣称] Toolshed 论文把工具文档扩充为 name、description、argument schema、hypothetical questions、topics/intents，再做 query decomposition/rewriting、多查询检索、rerank/self-reflection；作者报告 ToolE single/multi 与 Seal-Tools 的 Recall@5 绝对提升 46/56/47 个百分点。没有找到作者提供的官方代码仓库，因此不能检查数据拆分、失败策略或成本实现。[Toolshed](https://arxiv.org/abs/2410.14594)

[厂商宣称] RAG-MCP 作者报告：先用 embedding 在 server 层取 top-k，可选 synthetic-query validation，最终只把最佳 server schema 给执行 LLM；在 MCPBench web-search subset 上，embedding 43.13%、keyword 18.20%、全量 13.62%。论文另称 20 个 web-search task、候选位置 1–11100；这些描述与 4400+ registry 规模、表中非 5% 倍数的准确率之间缺少公开逐样本结果解释。[RAG-MCP](https://arxiv.org/abs/2505.03275)

[实证] `memoverflow/rag-mcp` 并非论文作者仓库。其 evaluator 把四个 enum baseline 实际压成 `use_kb_tools=True/False` 两种行为，accuracy 用 selected/expected tool 集合 Jaccard；默认只有 9 个 filesystem 问题，仓库没有提交结果文件。README 一处称 retrieval 43.13% vs 13.62%，另一处自己的表却是 61.1% vs 66.7%，不能当复现。[Evaluator](https://github.com/memoverflow/rag-mcp/blob/5fc52e9ddfb27690002342c715655999100e8cae/test/evaluator.py)、[comparison test](https://github.com/memoverflow/rag-mcp/blob/5fc52e9ddfb27690002342c715655999100e8cae/test/comprehensive_mcp_comparison_test.py)

[实证] 未找到可调用的 “ScaleMCP” 开源实现；名称最接近且有代码的是 Scale AI 的 MCP-Atlas benchmark，但它是评测 harness，不是检索 router。本文没有把两者混为同一项目。

### 工具数增长与大 server 如何组织

[厂商宣称] MCP-Atlas 论文总目录为 36 servers/220 tools/1000 tasks，但每题实际只给 6–37 tools、均值 15.2，required 2–8、均值 4.1，其余均值 11.1 是相似 distractor。论文报告的端到端 pass 与 wrong-tool failure 有价值，但不是“220 选 1”的准确率。[MCP-Atlas task structure](https://arxiv.org/html/2602.00933#S3.SS2)

[实证] MCP-Atlas harness 源码对当前 task 环境调用 `listTools()`，把返回的工具全量转换后交给每次 completion；工具调用错误会作为 tool message 回填，模型可恢复，默认最多 256 turns/100 tool calls。它没有 embedding/关键词预路由。[Agent harness](https://github.com/scaleapi/mcp-atlas/blob/f24ba3fb0bfa484c86acb28431fad6d7282455f9/services/agent-harness/src/mcp-agent/agent-evals/agent-eval.ts)

[实证] GitHub MCP Server 的 inventory 源码称全量约 90 tools；工具声明所属 toolset，默认只开 context/repos/issues/pull_requests/users/copilot，另可按 read-only、toolset、additional tool 和 feature flag 过滤。远程请求还会为一次具体 `tools/call` 只注册被点名工具。它解决的是“配置/协议层缩面”，不是运行时自然语言 router。[GitHub toolsets](https://github.com/github/github-mcp-server/blob/0ea1f775a7c73eff1bd2e25904d01136756bbfe2/pkg/github/tools.go)、[inventory filters](https://github.com/github/github-mcp-server/blob/0ea1f775a7c73eff1bd2e25904d01136756bbfe2/pkg/inventory/registry.go)

[实证] AWS Labs 仓库在 `src/` 下不是一个巨型 server，而是 60 多个独立领域包，例如 pricing、documentation、DynamoDB、CloudWatch、Redshift、IAM、EKS；每个有独立 `pyproject.toml` 和 server 入口。这是按领域拆 surface 的实例，不是公开的 selection accuracy 证据。[AWS Labs source tree](https://github.com/awslabs/mcp/tree/6d289e1281fb20512b0fc7db7a917c4bccdaf53c/src)

[推测] 上述实例支持“先缩小合法候选域，再做语义选择”，但不能推导出 Gravity 应采用任何 MCP 交付面；这里只把它们当大能力目录的组织实现。

### 有没有从关键词换成 LLM / embedding 的可信前后对照

[实证] 在读过源码的 LangChain、LlamaIndex、Semantic Router 中，未找到同一冻结 unseen 题集上“手写关键词 recognizer vs embedding vs LLM”的三臂结果。

[厂商宣称] RAG-MCP 是唯一公开声称做 keyword vs embedding 同题对照的来源，方向支持 embedding，但复现链不足；Toolshed 报告的是增强 retrieval 对 baseline 的 Recall@5 改善，不是手写 recognizer 迁移。

[实证] LlamaIndex 的 30 条结果是模型间比较；Semantic Router 的 34.85%→90.91% 是同集调阈值；BSL 的 eval 只判运行成功。三者都不能回答 Gravity 的 80.4% 是否能被替代方案稳定超过。

[推测] 因而证据等级是“支持做替代实验，证据不足以直接换掉”。任何更强结论都会把框架采用率、训练集分数或论文自报误当作本仓库的 unseen 泛化证据。

## C. 包分析 SaaS 的第三方开源客户端

### 判定标准

[实证] 本节把候选分成三层：采集 SDK 只写事件，不算分析客户端；单一 export/query wrapper 算部分客户端；覆盖查询、元数据、保存对象、分页/导出等多个 read surface 才算“完整候选”。“成熟”还至少需要可见测试、稳定版本/维护、实际采用信号，不能只按生成文件数量判断。

### 最接近的候选

| 候选 | 源码实情 | 是否推翻“没有成熟完整先例” |
| --- | --- | --- |
| [实证] [navikt/amplitude-data-wrapper](https://github.com/navikt/amplitude-data-wrapper/tree/7768c2b08d58d56fed9466c4572cc2e01d71cda6) | `0.6.2`；`analytics_api.py` 只有 9 个顶层函数，覆盖 chart、user search、cohort、privacy deletion、raw export、taxonomy event 和 event segmentation；有 EU/US 与 async chart 支持 | 否。它是活跃、跨多个 API 家族的真实第三方 wrapper，但仍是小型部分面，不覆盖完整分析产品与统一 contracts |
| [实证] [Drakkar-Software/posthog-openapi-clients](https://github.com/Drakkar-Software/posthog-openapi-clients/tree/e41454edf4e644c0848fb36050818fc1d2fa811c) | OpenAPI 生成的 TypeScript `0.0.12`；58 service、782 model，含 query、insights、dashboards、cohorts、events、exports、warehouse 等；仓库没有测试文件 | 部分推翻“没有完整 facade”，不推翻“没有成熟先例”。覆盖宽，但低版本、无测试、2-star，且是 schema 直生成，不证明行为治理/分页/漂移闭环成熟 |
| [实证] [keolo/mixpanel_client](https://github.com/keolo/mixpanel_client/tree/c3c3a73c82d760e522233cf5be9abed1047995f2) | Ruby Data API client，历史 changelog 有 breaking v3、export/import；核心只有 `request(resource, options)`，resource/参数字符串交给调用方，最后提交 2023-09 | 否。它是有较长维护历史的薄 transport client，不提供现代完整能力目录、typed schema 或机器可判定错误 |

[实证] GitHub 搜索的其他高位候选大多是官方 ingestion SDK、只写事件的第三方 SDK、单 endpoint export client 或多年未维护包；Heap 搜索只找到 2014 年的 server-side ingestion client。没有找到同时满足“第三方维护、分析读取面广、typed contract、分页/错误治理、有测试与持续维护”的项目。

[推测] C 节对上一轮结论的精确修正应是：开源里存在“广覆盖自动生成 facade”，也存在“有采用历史的薄 transport”；仍没有找到 Gravity 这种把能力登记、读取、分页、错误分类、隐私/投影与漂移门禁一起交付的成熟第三方先例。

## 对本仓库的意义

### `gravity.semantic-context.v1` 与开源主流的差异

[实证] 比较基线取自本轮已落地的 workspace contract：`terms[]` 把 phrases 指向 typed registered target，`exclusions[]` 提供负向语义，`verified_queries[]` 把 normalized exact question 指向 operation + complete input；workspace-load 校验本地静态对象，Agent preflight 再校验 metadata-backed target；冲突时 exclusion/既有多意图边界优先，verified query 不越过安全与歧义规则。[Workspace 参考](../../reference/workspace.md)

| 差异 | 与开源主流相比 | 严 / 松 / 选择差异 | 风险判断 |
| --- | --- | --- | --- |
| [实证] typed `term → target` | 主流多是 description/free-text hint/metadata；Cube 才有 view scope override | **更严**于自由文本；同时在 scope/locale/priority 表达力上**更少** | target 可校验是优点；未来若加 scope，必须编译最终可见结果 |
| [实证] load + preflight dangling-ref check | Cube/MetricFlow/Malloy 编译期 fail；BSL 查询解析 fail；Lightdash stale catalog 可跳过 | 总体**更严**，但符合 fail-closed 主流 | 没有被证明错误；应保持 |
| [实证] `exclusions[]` 为一等公民 | 所查语义层未见同形负向词典；工具描述通常用 prose 写“不适用” | **选择差异**，不是松严可直接比较 | 需防 exclusion 过宽吞掉合法问法；必须有冲突/命中可观测性 |
| [实证] exact `verified_queries[].question` | 主流 saved/named query 保存结构；Semantic Router utterance 只作相似样例 | 触发层面**更严**（精确），维护层面更脆 | 最可能变成句子表；应限制为少量稳定回归/固定业务口径，不承担泛化 |
| [实证] verified query 带完整 input | MetricFlow saved query 也是结构化、可验证输入；Malloy named query 同类 | 与主流**一致** | 结构复用本身合理；问题在 NL 触发绑定，不在 complete input |
| [实证] caller 语义不静默覆盖 authoritative conflict | Cube view override 明确“局部赢”；BSL declared dimension 赢 raw column；MetricFlow ambiguity 报错；多数项目无通用规则 | Gravity **更保守/更严** | 没有外部证据要求 caller 必须赢；`MULTIPLE_INTENTS` 合理 |
| [实证] 无 locale / 显式 priority | Cube/Lightdash 也没有 locale/数值 priority；Cube 有 view scope | 目前主要是**选择差异** | 暂无证据证明必须加；多语言和跨 app 冲突数据出现前不要预建复杂层级 |

[实证] 没有一处被开源实践证明“设计错误”。最明确的坑有三类：Cube 证明语义作用域的可见性会误配；BSL 证明缺省/版本迁移可静默改语义；MetricFlow 证明多个物理路径不能靠任取一个解决。这三类分别对应未来 scope 编译、contract 版本/默认值和歧义分类，并不要求推翻现有 v1。

[推测] v1 最值得收紧的使用纪律是：`verified_queries` 不以覆盖问法数量为目标，不用同一句的几十个改写冲准确率；把 verified binding 看成“稳定问句入口 + 已验证结构”的稀疏例外，并单独统计其覆盖率、冲突率和失效引用。更广的 paraphrase 泛化应由路由实验承担。

### 80.4% 天花板：换掉手写 recognizer 吗

[实证] 开源代码足以证明替代架构是可实现的：embedding route 可本地、可阈值 abstain、可返回多个；LLM selector 可输出受 schema 限制的多个候选；两段式可把最终主模型看到的工具数限制住。它们不是概念 PPT。[Semantic Router](https://github.com/aurelio-labs/semantic-router/blob/a4576168d9589397a7e0c6ff77f5d05469a56e2e/semantic_router/routers/base.py)、[LangChain selector](https://github.com/langchain-ai/langchain/blob/9a5810712658bdb9ad91925d3242032822f54a5e/libs/langchain_v1/langchain/agents/middleware/tool_selection.py)

[实证] 开源证据也暴露代价：embedding top-1 会在无匹配时仍猜；threshold 在训练集上可被调得很好而不代表 unseen；LLM structured output 会 malformed；tool name 正确率高不代表参数值正确；检索论文的数字缺官方代码复现。[LlamaIndex embedding selector](https://github.com/run-llama/llama_index/blob/afd0fef371831f9bda13e5af7167cf4e981278ab/llama-index-core/llama_index/core/selectors/embedding_selectors.py)、[Semantic Router notebook](https://github.com/aurelio-labs/semantic-router/blob/a4576168d9589397a7e0c6ff77f5d05469a56e2e/docs/06-threshold-optimization.ipynb)、[LangChain issue #34358](https://github.com/langchain-ai/langchain/issues/34358)、[LlamaIndex notebook](https://github.com/run-llama/llama_index/blob/afd0fef371831f9bda13e5af7167cf4e981278ab/docs/examples/benchmarks/gemini_tool_selection_eval.ipynb)

[推测] 决策不是“继续手写”与“一次性换掉”二选一。下一步应锁定三臂：现有 recognizer；基于现有 capability description + 少量 route utterance 的 embedding/hybrid selector；结构化 LLM multi-selector。三臂共享同一 development/offline/由用户持钥运行的 holdout，禁止用测试集调 threshold 或 prompt。

[推测] 首要门槛应仍是首次产品选择正确率，另报 abstain、`MULTIPLE_INTENTS` 候选召回、错误单选、参数完整率、重复运行方差、P50/P95 延迟、token/费用和不可用时降级。只有替代臂在 unseen 上超过 80.4%，且没有用“多返回/全 abstain”虚增分数，才有证据谈迁移。

[推测] 即使某个替代臂胜出，也只替换开放式语义选择，不替换 operation manifest、workspace target validation、exclusion、安全边界、参数 schema 和执行前 fail-closed。开源案例的共同失败正说明生成式/相似度层不能兼任这些确定性职责。

## 最可能出错的判断与未决清单

[推测] **最高风险判断：把“项目采用 embedding/LLM”误读为“在 Gravity 题集上一定超过 80.4%”。** 目前没有同题、同候选、同指标的开源对照；RAG-MCP 只是未复现的方向性数字。

[推测] **第二风险判断：把 exact verified query 等同于 MetricFlow saved query。** 两者都保存结构，但只有 Gravity v1 把一条 normalized 自然语言整句作为 runtime trigger；维护成本和泛化行为不同。

[推测] **第三风险判断：认为 typed target 越严格就天然越安全。** Cube 与 BSL 的 issue 表明 alias/scope/default/version 都能让“合法引用”产生错误语义；引用存在校验不能替代编译后的语义一致性检查。

[实证] 未决：没有找到 Cube、MetricFlow、Malloy、BSL 或 Lightdash 对 synonym locale、数值 priority、caller-vs-system 全局优先级的成熟统一设计。

[实证] 未决：没有找到开源项目在冻结 unseen 题集上公开“手写关键词 → embedding/LLM”迁移前后的完整对照；RAG-MCP 缺官方代码，Semantic Router 使用训练集回评。

[实证] 未决：没有找到可复核的通用工具数量临界值。公开 benchmark 每题候选面不同，MCP-Atlas 的 220 是总目录而非同时暴露数。

[实证] 未决：没有找到官方 Toolshed 代码仓库，也没有找到可调用的 ScaleMCP OSS router；不能审计它们的 ambiguity、fallback 和运行成本。

[实证] 未决：C 节找到广覆盖 PostHog 生成 client，但没有测试与成熟采用证据；无法仅凭生成的 58 services 断言所有 endpoint 实际可用或分页正确。

[推测] 未决：`verified_queries` 应允许参数模板、只保存结构化 query ID，还是继续 complete input exact binding，需要由真实重复问法与变参需求决定；本次外部证据只足以限制滥用，不足以替 v1 选择新 contract。

## 交回判断

[实证] **1A，最有价值证据：** BSL issue #223——序列化漏掉 join cardinality 后默认成 `one`，会在升级时静默改变聚合；它比“引用不存在会报错”更接近语义层最危险的失败。[Issue #223](https://github.com/boringdata/boring-semantic-layer/issues/223)

[实证] **1B，最有价值证据：** Semantic Router 的 34.85%→90.91% notebook 实际在同一 `X,y` 上 fit/evaluate，说明漂亮路由数字若没有严格 unseen split，恰好会掩盖 Gravity 当前的泛化问题。[Notebook](https://github.com/aurelio-labs/semantic-router/blob/a4576168d9589397a7e0c6ff77f5d05469a56e2e/docs/06-threshold-optimization.ipynb)

[实证] **1C，最有价值证据：** 第三方 PostHog client 确实能通过 OpenAPI 生成 58 services/782 models 的宽 facade，但 `0.0.12` 且零测试；“生成得全”与“成熟可依赖”是两件事。[Client](https://github.com/Drakkar-Software/posthog-openapi-clients/blob/e41454edf4e644c0848fb36050818fc1d2fa811c/client/typescript/PosthogAPIClient.ts)

[实证] **2，语义层有没有被证明错误：没有。** dangling-ref 两段 fail-closed 得到主流实践支持；最有坑的是 exact verified question 容易变句子表、未来 scope 可能发生“声明了但不可见”、contract 默认值/迁移可能静默改语义。这些是需要门禁的风险，不是 v1 已被证伪。

[推测] **3，换掉 recognizer 的证据：不足。** 证据支持做 embedding/LLM 替代臂并要求 unseen A/B，不支持现在直接撤掉手写 recognizer。若把“换掉”理解为“开始受控替代实验”，方向是支持；若理解为“立即迁移生产路径”，答案是不足。

[实证] **4，预期能找到却没找到：** 没找到可复现的关键词→embedding/LLM 同题迁移对照、通用工具数阈值、官方 Toolshed/RAG-MCP 代码链，也没找到成熟完整的第三方分析 SaaS 客户端。最意外的是找到了宽覆盖 PostHog 生成 facade，却仍缺测试与成熟度证据。

## 标注统计

[实证] 本文正文（含表格与本节）共标注 `[实证]` 83 条、`[厂商宣称]` 10 条、`[推测]` 15 条，共 108 条。统计口径为 Markdown 源文件中作为结论前缀、表格行前缀或表格单元格前缀的标签；方法和本句中用于解释标签名称的字面量不计。
