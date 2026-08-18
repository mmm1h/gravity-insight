# 同类产品调研：别人怎么让 agent 独立完成数据分析

- 日期：2026-08-19
- 任务：#221
- 结论：别人真正多出来、且还没被我们收进信封的，不是「再做一个 BI agent」，而是三件事——结果信封上声明数字能不能加/有没有率、弃权时给出「系统答得了的问题」、产品卡上把「不能做什么」写成字段而不是从描述里正则抠。

本趟 **0 次引力生产请求**，不改 `src/` / `tests/` / 评测 / 既有文档（本文件与 README 归档清单自己那一行除外）。未读 `docs/roadmap.md`。未跑 holdout / final。未把仓库代码或业务数据发到外部服务。

---

## 方法与证据边界

### 确凿（本机核对过）

- 工作目录 `D:/git-pjt/wt-prior-art`，分支 `grok/prior-art`，`HEAD=53f3d86`（`merge: grok/group-labels`）。
- 读过：`docs/team-onboarding.md`、`AGENTS.md`、`README.md` 前 150 行、`docs/roadmap.d/README.md`、近期结论（`routing-arms-paired-holdout.md`、`selection-residual.md`、`upstream-selfcorrect.md`、`advertised-vs-real.md`、`group-labels.md`、`routing-provenance.md`、`semantics-errors-and-discovery.md`、`borrow-roadmap.md` 的 P0/P3）。
- 用 `grep` 定位后再窄读：`errors.py`、`actionable_error_values.py`、`agent_gap.py`、`agent_host_catalog.py`、`agent_host_selection.py`、`agent_discovery_support.py`、`analysis_spec_schema.py`、`dimension_sum_audit.py`、`result_source.py`、`semantic_compose.py`、`executor.py`、`export_completion.py`、`scripts/audit_actionable_errors.py`。
- 8 月中旬已有调研底稿仍有效的部分直接引用，不重写清单：`docs/research/vendor-agent-landscape.md`、`oss-semantic-and-routing.md`、`semantic-layer-and-text2sql.md`、`agent-usability-methods.md`、`mcp-protocol-and-servers.md`。

### 确凿（本趟联网、拉过官方页）

| 页 | 核对到什么 |
| --- | --- |
| [Amplitude MCP](https://amplitude.com/docs/amplitude-ai/amplitude-mcp) | 渐进发现：`get_amplitude_context` → `list_tool_categories` → `get_category_tools` → `describe_tool`；`?discovery=progressive` 时 `tools/list` 先只给发现工具。 |
| [Amplitude official events](https://amplitude.com/docs/data/official-events-and-properties) | official 是选择器过滤 + AI 加权，**不挡、不藏、不改数据**。 |
| [Snowflake Cortex Analyst REST](https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-analyst/rest-api) | 响应 content type `text` / `suggestion` / `sql` 互斥；歧义只出 `suggestion`（语义模型答得了的问题），不出 SQL。`confidence.verified_query_used` 为对象或 `null`（name / question / sql / verified_at / verified_by）。`response_metadata.question_category` 存在；公开示例值为 `CLEAR_SQL`。 |
| [Databricks Genie Conversation API](https://docs.databricks.com/aws/en/genie/conversation-api) | `attachments` 里有 `query` / `text` / `attachment_id`；`query.parameters` 出现表示 trusted asset。推理痕迹在 `GenieQueryAttachments`。API **没有** UI 那套「先给初答再改」两阶段。 |
| [Looker Conversational Analytics](https://docs.cloud.google.com/looker/docs/conversational-analytics-looker-data) | 「How was this calculated?」给出所用字段、计算、过滤、排序；可展开 reasoning；可请求澄清。这是 Web UI 合同，不是本趟看到的公开 JSON schema。 |
| [Mixpanel Headless](https://mixpanel.github.io/mixpanel-headless/) | 四个 typed primitive（`Filter` / `Metric` / `CohortDefinition` / `CohortCriteria`）跨 Insights / Funnels / Retention / Flows / Profiles。`query_funnel(...).overall_conversion_rate` 由引擎算。CLI 与 SDK 同一能力面。 |
| [Cube 非可加](https://docs.cube.dev/recipes/pre-aggregations/non-additivity) | `count_distinct` / `avg` / percentile 是一等 `type`；预聚合不能在缺维时静默重聚合。 |
| [dbt Measures](https://docs.getdbt.com/docs/build/measures) | `non_additive_dimension` + `window_choice`（min/max）；`count_distinct` 是 `agg` 枚举。新 spec 把 measure 收成 `type: simple` metric。 |
| [Anthropic writing tools](https://www.anthropic.com/engineering/writing-tools-for-agents) | 错误要写「怎么改」而不是 opaque code；描述按评测改；截断响应要带下一步策略。效果数字是厂商内部评测，不当证明。 |
| [OpenAI tool search](https://developers.openai.com/api/docs/guides/tools-tool-search) | 先只暴露 namespace/server 名和描述，完整参数 schema 延后加载。 |

### 文档里这么写、本趟没复现接口

- ThinkingAI MCP：8-15 调研时 npm 404、无 `tools/list`。本趟未再打 registry。
- ThoughtSpot MCP tool schema、Tableau Pulse 对外 agent API：公开页仍看不到调用合同。
- AWS `sample-semantic-layer-structured`：GitHub 抓取被 robots 挡住；分层（metric / semantic / advisory + `provenance.tier`）只引用 8-15 已读过的 [调研](../research/semantic-layer-and-text2sql.md)，本趟标「文档里这么写」。
- dbt Measures 页后半（`non_additive_dimension` 的 YAML 实例）第二次 fetch 因 robots.txt 失败；字段名以第一次成功抓取的参数表为准。

### 推测栏（单独放，不与上表混写）

- 公开厂商几乎都把「语义对象 + 上游引擎算好」放在模型和 SQL 之间。这支持我们继续以产品动线为主干，不支持再开一条自由 text-to-SQL 当可信答案。
- 「模型自信度」没有可校准的公开合同。Snowflake 的 `confidence` 实际是「用了哪条已验证查询」，不是 0–1 分。
- Mixpanel 博客称 MCP 固定菜单不适合无人值守、Headless typed code 才适合；这是厂商工程访谈，不是对照实验。

---

## 我们现在到底是什么（对照基线，避免把已做的当缺口）

形态：CLI + Python SDK，消费方是 agent，不是人点 Web。agent 靠信封里的 `next.argv`、能力卡、`capability_gaps` 决定下一步。上游是引力。

已经做成、调研时不要再当「别人有我们没有」的：

| 问题 | 我们现在 |
| --- | --- |
| 路由 | 离线识别器留出集首选 **195/240 = 81.25%**；宿主目录臂 **235/240 = 97.92%**（`routing-arms-paired-holdout.md`，ledger ordinal 5/6）。默认仍是 recognizer，因为 `host_catalog` 缺 `--host-selection` 会让现存调用方当场失败（`routing-provenance.md`）。 |
| 发现 | `categories → category → describe` + `host` 紧凑产品/gap 投影；0 候选固定 gap，1 个才 describe，多个 `MULTIPLE_INTENTS`。`UNRANKED_OPERATIONS` 交宿主臂。 |
| 可信度 | `unreliable_item_keys` + 结果 `warnings`（`reason` / `use_instead`）；可加指标分维和对不上写 `dimension_sum_mismatch`（UV 不参与，见 `dimension_sum_audit.py` / `test_resolver.py`）；漏斗 spec notes 声明不返率；导出 `truncated` + 已知总量；分维组标签 2026-08-19 已留下。 |
| 错误 | `ErrorDetail`：`code` / `category` / `field` / `retryable` / `next_action`。审计钉 `1268 / A896 / B372 / C0`。上游拒绝走受审查映射，不回传未审查 `extra.error`。 |
| 缺口 | `unavailable_gap(code, reason, next_action, argv)`；`NO_CANDIDATE` 指向 `agent-catalog categories`，禁止执行 weak match。 |
| 口径 | 窄语义组合已有 `resolution_tier` / definition 版本 / `allowed_claims` / 生成查询（`semantic_compose.py`）。普通 Insight 读结果只有 `result_source`，没有「这个数能不能加、有没有率」。 |

已知产品边界（撞上就放弃）：

- 上游授权即产品边界，不建访问控制 / 字段过滤 / 敏感内容检测（`projection-and-privacy.md`）。
- 不做 MCP 为第五交付面（`mcp-feasibility.md`：要第二个真实消费者 + 冻结题集门槛）。
- 自然语言永不自动写；不做投放策略执行。
- 业务语义不进 SDK；`gravity.semantic-context.v1` 由调用方 workspace 维护。

---

## 发现对照表

「值不值得借」只填：**该借 / 不该借 / 需要先验证**。

| 别人的做法 | 出处 | 对应我们哪个问题 | 我们现在怎么做的 | 值不值得借 | 为什么 |
| --- | --- | --- | --- | --- | --- |
| 渐进发现：先类别、再工具、再 schema | Amplitude MCP 官方页（本趟拉过） | 路由 / 能力发现 | `agent-catalog categories → category → describe`，`host` 再瘦一档 | **不该借** | 已经是同一形状。再包一层 MCP 撞「不做 MCP」边界，不增加选对率。 |
| 宿主只返回 0..N 个结构化选择，仓库负责校验和执行 | LangChain structured tool selector；我们自己的 host 臂 | 路由 | `gravity.host-product-selection.v1`：`selected` / `multiple_intents` / `abstained`，指纹过期整份拒绝 | **不该借** | 已经落地。该做的是让调用方走这条臂，不是再造选择器。 |
| 歧义时 **不出查询**，只出 `suggestion`（系统答得了的问题） | Snowflake Cortex Analyst REST：`suggestion` 与 `sql` 互斥 | 路由残余 + 诚实缺口 | `NO_CANDIDATE` / `UNRANKED_OPERATIONS` 指向「去逛目录」；不给可答问题清单 | **该借** | 识别器残余主要是 `no_candidate`（selection-residual：39/336）。逛 10 个领域仍容易让 agent 编一个邻近产品。弃权信封里给有界、已登记的可答问法 / `catalog_ref`，比扩关键词表安全。 |
| `question_category`（公开示例 `CLEAR_SQL`） | 同上，`response_metadata` | 路由可观测性 | 只有 `routing_mode` + `routing.floor`，没有「这句被判成清晰 / 歧义 / 不可答」 | **需要先验证** | 字段有用，但公开文档没给出枚举全集。先在离线发现信封加离散类（清晰选中 / 多意图 / 登记 gap / 无候选），不要抄一个未公开的分类器。 |
| 延后加载参数 schema，先只给名字和描述 | OpenAI tool search | 发现成本 | `host` 已不投影 raw operation 和完整 wire；`describe` 才给 input_schema | **不该借** | 已经分层。OpenAI 那套是模型上下文里的 tool 列表，我们是 CLI 两次调用，机制不同。 |
| 四个 typed primitive 跨五种查询引擎；漏斗率由引擎给出 | Mixpanel Headless SDK 文档（本趟拉过） | 路由（少选一次产品）+ 可信度（率谁算） | 事件/漏斗/留存是不同 spec kind / 产品卡；漏斗**故意不代算率** | **不该借**（primitive 平台）；**该借**（率的归属声明） | 再造一套跨引擎 primitive 等于第二套语义层，越出「复用 composite / plan adapter / agent card」。该借的是：漏斗结果信封写明「本结果只有人数、没有率、两个合法分母」，别让 agent 自己除完当官方率。 |
| measure 的 `type`/`agg` 声明可加性；`count_distinct` 不能当 sum 预聚合 | Cube 非可加 recipe；dbt `non_additive_dimension` | 可信度：UV 不可跨维加总 | 事后对 4 个登记可加指标做 `dimension_sum_mismatch`；UV 明确不参与，**也不在结果上标记「不可加」** | **该借**（声明，不是引擎） | 我们包的是上游产品，建不了 MetricFlow。缺的是 describe + **结果信封**上的 `additivity=non_additive` / `sum_is_not_total`。没有它，跳过 describe 的 agent 会把各组 UV 加起来。 |
| 漏斗率由引擎按 Uniques / Totals / Sessions 算出 | Mixpanel 社区/文档（本趟检索；计数方法页未整份拉） | 可信度：漏斗不返率 | spec notes：`returns_conversion_rate: false`，两个分母写在 schema，**结果信封没有这对字段** | **该借**（把 notes 抬到结果）；**不该借**（让 SDK 代算率） | 上游 `window_funnel_mode=4` 只返人数（`upstream-selfcorrect.md`）。代算会假装上游给了率。该借的是机读「没有这个字段」。 |
| 死字段 / 不可靠字段标出来并给替代 | 我们自己踩过；厂商侧少见公开合同 | 可信度 | `unreliable_item_keys` + warnings | **不该借** | 已经比公开 MCP 文档严。继续按证据加键，不要改成「删掉上游 0」。 |
| 超限导出诚实截断 | 我们已生产确认 100 万行 | 可信度 | `completion_status=truncated` + `known_total_items` + `file.rows` | **不该借** | 已闭环。公开 Headless/MCP 页没看到同级 completeness 枚举。 |
| `verified_query_used`（谁、何时、哪条 SQL） | Snowflake REST | 可信度：这数从哪条已审查询来 | 语义组合有 definition 版本 + `allowed_claims`；普通读只有 `result_source.tier` | **不该借**（整句 VQR 当主路径）；**需要先验证**（把 `result_source` 扩到「是否命中 verified semantic-context」） | 8-16 已判定 verified question 是整句快捷键、最容易退化成句子表（`oss-semantic-and-routing.md`）。精确问句绑定继续当 P2，不升级成默认答案来源。 |
| 「How was this calculated?」字段 / 过滤 / 排序 | Looker UI 文档 | 可信度 | 语义组合有 `generated_query`；普通 analysis 有 receipt 和 `resolved_date_window`，没有「人数不是率」 | **该借**（机读计算声明，不是 Web 折叠面板） | 目标消费者是 agent。把 funnel notes、可加性、截断、死字段放进结果，比再做一个解释 UI 有用。 |
| `query.parameters` 出现 = trusted asset | Databricks Genie API | 可信度分层 | `result_source.tier`：`governed_product` / `caller_defined` / `raw_operation`… | **不该借** | 我们已经有离散来源层。不要再加一个「有无 parameters 对象」这种隐式信号。 |
| official 事件/属性：AI 更爱用，数据仍全部可见 | Amplitude official 页 | 能力发现 / 诚实 | 未登记字段 fail-closed；死字段留下并警告 | **不该借** | 软加权会让未审查字段混进「可以信」。撞 fail-closed。调用方可在 workspace semantic-context 里自己标偏好。 |
| 错误 = 路径 + 实际值 + 可接受替代 | Structured Feedback（arXiv 2607.14167，8-15 已读）；Anthropic 工程文 | 错误自纠 | A = path+actual+remedy；C=0；替代超过 20 必须带 discovery_action | **不该借**（合同外形）；**该借**（继续把 B 收成 A） | 论文说 keyed JSON 和 prose 成功率接近。我们缺的不是新 schema，是 B372 里那批没有 `actual value` 的 raise。 |
| 工具业务失败放进 result（`isError: true`），不升级成协议错 | MCP tools 规范（8-15 已读） | 错误自纠 | 业务失败是带 `error` 的信封，exit 2/3/4 可分；gap 不是 empty | **不该借** | 已经是这个模型。引入 MCP `isError` 要第五面。 |
| 缺参就追问，缺工具就不调用 | BFCL v3 / OpenAI 指南（8-15） | 错误 / 缺口 | `missing_inputs` + `next.argv` 占位；自然语言不猜 App/事件 | **不该借** | 已经是产品 SLO（已知 1 次 / 未知 2 次）。 |
| 产品卡写「做什么 / 适用目标 / 不要用于 / 前置条件」 | Anthropic + 我们自己的可用性调研 | 能力发现 | `host` 条目有 `does_and_returns` / `goals` / `boundaries` / `prerequisites`，但 `boundaries` 是从描述里按「不/只/不能/never/only」**正则切句**（`agent_host_catalog.py` `_boundaries`） | **该借** | 形状有了，来源不对。相邻产品边界应是卡上的显式字段，由 owner 写，编译进 host 投影；不要靠中文标点。 |
| `get_amplitude_context` 注入组织口径 | Amplitude MCP | 能力发现 | `gravity.semantic-context.v1` workspace | **不该借** | 同一职责，已在调用方 workspace。SDK 不维护业务词。 |
| `list_metrics` / `get_dimensions` / `query_metrics` | dbt MCP（8-15） | 长尾组合 | 窄语义组合 + metadata search；不是通用成员目录 | **需要先验证** | 方向已在 P0-3。本趟不新开通用指标平台。先看现有 compose 成员面够不够宿主选「换一刀」，再决定要不要独立 `list_metrics`。 |
| 多 join path = 歧义错误，不猜一条 | MetricFlow（8-16 源码调研） | 歧义 | `MULTIPLE_INTENTS`；编译期未知成员失败 | **不该借** | 已经 fail-closed。要区分的是「两个业务含义」和「两条物理路径」，那是语义组合扩面时的编译器问题，不是选路问题。 |
| 协调器 + 多 sub-agent | PostHog 复盘（8-15，厂商文） | 多步任务 | Plan DAG + 有界 worker；playbook 是确定性步骤 | **不该借** | PostHog 自己写过上下文丢失。撞「不多 agent 编排」P3。 |
| 远程 OAuth MCP 当对外主入口 | Amplitude / Mixpanel / PostHog | 发现 | CLI / SDK / Plan / Agent 卡 | **不该借** | 明确不做 MCP。要标准接入等两个真实消费者（`borrow-roadmap.md` P2）。 |
| 行列 ACL / 字段掩码做在 agent 层 | Snowflake / Cube / Looker 其实是**复用上游** | 安全 | 上游授权即边界 | **不该借** | 撞硬边界。外部也是继承上游身份，不是在客户端再做一份。 |
| 自由 text-to-SQL 与受治理查询同一入口 | dbt MCP 同时有 `query_metrics` 和 `text_to_sql` | 可信度 | Insight-first；SQL 是隔离产品 | **不该借** | 8-15 已裁：探索层必须自带 `resolution_tier`，不得并进 Agent 卡。 |

---

## 如果只能挑三件

按「对 agent 独立做完分析」的影响排序。

### 1. 把「这个数字能不能信」写进结果信封

现在漏斗不返率、UV 不可加、导出截断、死字段，分别写在 spec notes、`dimension_sum_audit` 白名单、export completion、`unreliable_item_keys`。agent 走 `plan run` / `gravity run` 拿到数时，**不必再读 describe**。这正是我们踩过的坑会再次发生的位置。

该落的最小机读字段（沿用已有 envelope，不新开入口）：

- `returns_conversion_rate: false` + `rate_denominators`（已在 `analysis_spec_schema.py`，抬到漏斗结果）
- `additivity: additive | non_additive | unknown`（Cube/dbt 的声明，不是新引擎）
- 已有 `warnings` / `diagnostics` / `truncated` 保持

不做：SDK 代算转化率；对 UV 做假的「各组之和」验收。

### 2. 弃权时返回「系统答得了什么」，而不是「去逛目录」

Snowflake 在歧义时只给 `suggestion`。我们的 `NO_CANDIDATE` / 部分 `UNRANKED_OPERATIONS` 把球踢回 `agent-catalog categories`。目录浏览对分析师冷启动成立，对要独立收工的 agent 不够：它仍可能执行邻近 raw operation 或编一个数。

该落：弃权信封增加有界列表（已登记产品问法或 `catalog_ref`，条数封顶，来自现有 caller language / host entries），`next.argv` 仍指向 host 臂。0 个可答项才是真正的「能力没有」。

不做：对着题集加词；切默认路由。

### 3. 产品卡的「不能做什么」改成 owner 写的字段

`host` 已经有 `boundaries`，但 `_boundaries()` 用「不/只/不能/never/only」从描述切句。选路 97.9% 的宿主臂吃的就是这份投影；残余错产品（development 上 `wrong_product` 等）有一部分是相邻卡边界靠运气。

该落：卡合同增加显式 `do_not_use_for`（或等价字段），编译进 host 投影；regex 只做缺省回退。这直接加厚「诚实缺口」——做不到的时候说的是卡上的句子，不是模型补的邻近能力。

不做：第二套 registry；把 raw operation 重新塞进 host。

---

## 明确放弃（撞边界或我们已经更好）

| 想法 | 撞哪条边界 / 为什么放弃 |
| --- | --- |
| 现在做 MCP 第五面 | 仓库非目标；`mcp-feasibility.md` 要第二个消费者。Amplitude 渐进发现我们已有 CLI 形态。 |
| 客户端字段 ACL / DLP | 「上游授权即产品边界」。Snowflake/Cube 也是继承上游，不是在 agent 再做一份。 |
| 通用语义层 / MetricFlow 克隆 | 超出「复用 triad、不建平台」。可加性声明可以挂在现有 describe/结果上。 |
| 自由 NL2SQL 当可信答案 | 已裁。企业失败模式是「SQL 跑通、数不对」（FLEX / QueryGPT）。 |
| official 软加权未审查对象 | 削弱 fail-closed。 |
| 多 agent 编排、自动写投放 | P3；自然语言不自动写。 |
| 把默认臂切成 `host_catalog` | `routing-provenance.md` 已判：会打断所有未传 selection 的调用方。本趟调研不推翻。 |

---

## 动线台账

本趟不改 `docs/analysis-journeys.md`，不改表头 `56 = x / y / z`。这是调研，没有产品闭环变化，冻结 case 无需对题。

---

## 本趟没做的验证

- 没有跑 unittest / pytest / 可用性评测（纯文档产出；避免 32 MiB 顶）。
- 没有复现 Snowflake / Amplitude 的 live API，只核对公开文档字段。
- 没有打开引力 Web，没有打生产。
