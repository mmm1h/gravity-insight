# Agent 工作流

本页是 Agent 的最短执行协议。目标不是把所有命令跑一遍，而是用最少调用得到一个可复核的结果或明确能力缺口。

## 0. 先选最短入口

| 已知信息 | 直接执行 | 正常命令数 |
| --- | --- | --- |
| 已知 recipe / operation | `gravity run @<recipe> ...` / `gravity run <operation-id> ...` | 1 |
| Analysis 编译/跨期对比（kind/字段已知或指标未知） | `analysis query [batch]`；指标未知先 `metadata vocabulary`；同 spec 两个日期窗加 `--compare-start/--compare-end`，一次调用返回双窗状态与已登记物理指标 delta | 1 / 2 |
| 报表产品（Multidim / Business Pulse） | 已知输入：`multidim query` / `reports pulse`；Multidim 物理指标/维度未知可用在线输入解析后精确选择；再 `plan run` | 1 / 2 |
| 跨平台投放/素材表现 | 已知输入：`materials performance` / `promotion performance`；推广平台已知而指标未知时用在线输入解析；再 `plan run` | 1 / 2 |
| 自定义人群覆盖与状态 | 已知输入：`promotion custom-audiences`；未知：对应 Agent 卡 → `plan run` | 1 / 2 |
| 订单目录/拆单追踪/变现明细 | 已知 App/单日[/TraceID]：`analysis order directory` / `analysis order trace` / `analysis monetization detail`；未知：对应 Agent 卡 → `plan run` | 1 / 2 |
| 人群规则/分群快照/成员明细 | 已知 spec 或精确引用：`analysis segment evaluate` / `analysis segment snapshot` / `analysis segment members`；未知能力且输入已知时发现后执行 | 1 / 2 |
| Analysis 默认值字典 | 已知 App：`analysis defaults --app ...`；未知能力但 App 已知：对应 Agent 卡 → `plan run` | 1 / 2 |
| 创建、更新、刷新或删除分群 | Agent 只交接明确的 `analysis segment ... --dry-run`；人确认后把同一命令改为 `--execute` | 2（预览 / 执行） |
| 保存分析/分析模板 | 引用已知：`analysis saved run` / `analysis template run`；引用未知时在线输入解析后按稳定 ID（模板为 scope + ID）精确选择。模板仍只执行 compact Spec 或已证明 artifact | 1 / 2 |
| 看板控制面/图表重放 | 已知引用：`analysis dashboard snapshot` / `analysis dashboard run`；引用未知时在线输入解析后精确选稳定 ID，再执行 | 1 / 2 |
| Governed 文件 effect | 输入已知：报表 `export run`，精确素材 `materials fetch`；未知入口：Agent 卡 → `next.argv` | 1 / 2 |
| 多 selector / 已有 Plan | `gravity plan run --input <plan.json>` | 1 |
| 用户旅程/数据表沿革 | `analysis user journey`；lineage catalog 冷机时用在线输入解析完成原子 refresh，再离线查询 | 1 / 2 |
| 单个未知目标/operation 输入 | `gravity agent "<query>"` / `gravity agent <operation-id>` → 执行卡片 argv | 2 |
| 多个未知分析问题 | `gravity agent --input <questions.json>` → `plan run` | 2 |
| 同时找 operation、recipe、metadata | `gravity find "<query>"` | 1 次发现 |
| 多个独立 operation | `gravity insight batch read ...` | 1 次批量执行 |
`run` 已经完成 bind、validate、parents、exec 和 diagnose。不要在每次调用前机械执行 `recipe check`、`validate`、`parents resolve` 和 `doctor`；只有 `run` 的 diagnostics 要求时再执行对应命令。
五种 Analysis kind（`event/funnel/retention/property/scatter`）使用 `gravity analysis query --kind <kind> --spec <json|file|->`；多个独立 spec 一次交给 `analysis query batch`，复用 Plan 并发。事件/属性用 `metadata search`，指标/标签/媒体枚举/模板用 `metadata vocabulary`；确认后执行。`--dry-run` 返回零网络安全预览，Spec 不接受自然语言自动执行。完整示例见 [CLI 参考](reference/cli.md#analysis-query-spec-v1)。
经营概览和趋势直接一次调用 `gravity reports pulse --app main --start 2026-08-01 --end 2026-08-07 --include-hourly`；只有需要小时对比时加 `--include-hourly`，其结果是 `scope=workspace`。不知道入口时，明确的 `business pulse/经营脉搏` 意图离线返回唯一 composite，并展开 `apps/start/end/platforms/include_hourly`；调用方补齐后执行一次 Plan。泛 `business analysis/经营分析` 不由 Pulse 抢占，Agent 也不从自然语言填写 App、日期或平台。交叉 Plan 不要手工串行读取 overview/business。
保存分析已知稳定 ID/精确名称和日期窗时直接 `gravity analysis saved run --app ... --ref ... --start ... --end ...`，不要先串行 list/get/prepare。reference Strict Replay 只接受已证明的五类 Web artifact，并严格复用现有编译器；`prepare --ref` 会联网解析引用但不执行最终查询。旧 compact reference/显式 `--definition` 可保留原日期语义，但 Agent 主路径仍要求窗口以覆盖 Web artifact。自然语言发现不会猜引用或自动执行。App 和窗口已知、引用未知时，第一次用 `agent --resolve-inputs` 取得完整 safe catalog，调用方精确选择稳定 ID，第二次 run；执行会重读目录和详情。
看板控制面仍用 `dashboard_snapshot`；图表执行用 `analysis dashboard run --app ... --ref ... --start ... --end ...`。后者只编译静态 Web artifact 中已证明的五类 Analysis 图表，不模拟布局、收藏或页面全局筛选，单图不支持时隔离报告。引用未知且 App/窗口已知时，`agent --resolve-inputs` 在第一调用返回完整 live tree 和 `dashboard_analysis` 节点；调用方精确选择 ID 后第二次执行。自然语言不自动执行，Plan 内固定 1 worker。

人群规则只接受显式紧凑 spec：Agent 强意图卡给完整 schema 和缺失的 `app/spec`，不会从自然语言生成规则。已知 spec 可直接 evaluate；交叉查询用 `segment_evaluate` composite，只有 `/app` 可绑定，结果仅 `part/percent/total`。
分群检查已知精确 ID/名称与日期时直接 `gravity analysis segment snapshot --app ... --ref ... --date ...`；固定返回 detail/history/daily_result，不读取规则或成员。引用未知且 App/日期已知时，强意图在线解析在第一调用返回完整分群目录；调用方精确选择 ID 后第二次执行。自然语言不自动执行。
分群成员与逐人属性用 `gravity analysis segment members --app ... --ref ...`。不传 fields 返回完整登记 profile；动态 fields 先由 `metadata properties/search` 发现，执行时 live 复验并在完整成员行上本地选列。历史成员只用 `segment_version_id`，不接收日期。规模/占比/历史/单日问法仍走 snapshot，成员/名单/逐人属性走 members；同一句显式要求两者返回 `MULTIPLE_INTENTS`。分群写必须把 preview 和执行拆成两次人工可见步骤：`create-from-analysis` 持久化已验证漏斗的一步命中/流失，另有 `create-from-rule/history/tmp`、`update`、`update-rule`、`refresh`、`delete`。命令显式二选一 `--dry-run` / `--execute`；create 写入可见 `GSDK-…` remark 并读回，delete 执行时再读 detail 且只删带标记对象。Agent 卡不生成 Plan node、不从自然语言填 spec 或自动执行，只返回 dry-run argv 和确认后的 execute argv。
### Multidim

Multidim 使用物理输入，不新增 Spec。它直接使用闭合的 `date_list/time_dims/metrics_list/custom_metrics_list/data_dims/relate_dims/filters/multi_keys` 物理输入；已知 App 和完整输入时直接一次 CLI/SDK 调用。物理指标或维度未知而其余业务输入已知时，第一调用用在线输入解析取得闭合 schema 与完整 live Multidim metadata，调用方精确选择物理名，第二调用由 FieldPolicy 再次 live 校验成员关系及维度排除。Agent 生成的 Plan request 总是带当前 `input_schema_version`；调用方不得删除或改写。在线解析不生成 App、日期、filter value 或业务口径，也不会把模板、布局、收藏、权限、经营 pulse 或 event/funnel Analysis 路由到这里。

### Order Directory 与 Order Split Trace

普通目录与变现明细已知 App 和严格单日时分别一次 `analysis order directory` / `analysis monetization detail` 完整读取 `P` 个分页，实测均为每页 1 POST、0 metadata；7 个同层空日订单节点为 7 POST。订单行严格只含 `Amount/BackAmount/Status/CreateTime`，完整结果使用可选 `--output <file.json>`，不支持 NDJSON/format。未知入口只返回 value-free composite，调用方补齐 `app/date`。已知 App、单日和显式 TraceID 时，一次 `analysis order trace` 完整读取有界父目录，本地精确匹配唯一父行后读取一次拆单明细。这些产品都不从自然语言选值或自动执行；否定、导出、写入、退款/净收入/成功解释、归因、旅程、相邻产品、推广/素材、模板/看板、分群/保存分析、UI/权限等冲突意图安全报缺口且不扫描 raw inventory。精确 raw selector 保持专家兼容；selector 后附任何自然语言则不再视为 exact，并安全报缺口。

推广表现要求调用方先明确一个 App、日期和平台数组；物理指标未知时，第一调用用在线输入解析读取每个已选平台的完整 live 指标目录，调用方精确选择，第二调用由 FieldPolicy 再次逐平台校验后执行。Agent 只对明确的 `promotion performance/跨平台推广报表` 返回 `promotion_performance` 节点，不从自然语言选值。平台也未知时不属于两次路径。否定、导出、写入、策略及相邻产品不会回落为 generic Promotion operation。

自定义人群覆盖与状态是独立无输入产品：已知入口一次
`gravity promotion custom-audiences` 完整分页；未知入口由明确的
`custom audience coverage status/自定义人群覆盖与状态` 意图返回 value-free
`custom_audience` 节点，再执行一次 Plan。它不接受 App、日期、筛选或用户字段，也不路由到
promotion performance；已登记的人员、公司、租户和自由标签字段随结果返回。

多个独立多维查询作为同层 Plan 节点由全局 worker pool 并发，不建 batch wrapper 或逐条启动进程。direct 默认 6、最大 24 workers，Plan adapter 内固定 1，避免与分页/metadata 并发相乘；HTTP 数量为 `M + P + optional total`，其中 `M` 是去重指标 metadata 请求数、`P` 是 query 页数。

## 1. 业务语义先在调用项目解析

调用项目可在 workspace 的 `gravity.semantic-context.v1` 中声明术语到已登记对象的字面映射、说明、排除和 verified question→operation input；完整形状见 [Workspace 参考](reference/workspace.md#调用方语义上下文)。Agent 只消费明确声明，不按相似名称选值；未知引用本地失败。没有声明时从业务知识库解析，无法确定就报告缺失信息。

派生比率、占比、跨期变化和集合对账使用 `gravity derive --input` / `sdk.derive_metrics(source, spec)`；算子只保证 Decimal、精确键对齐和显式 null/partial。未声明公式返回 `DERIVED_METRIC_BINDING_REQUIRED`；`[[semantic_context.derived_metrics]]` 可声明 phrases/spec，命中后只缺 source，绝不从列名补分子、分母、总体、时期或 expected。

## 2. 未知能力：总共两次调用

```powershell
gravity agent "<英文或技术关键词>"
# 从 capability card 选择候选、填写 required_inputs，并执行 next.argv
gravity run <operation-id> --input <json-or-file>
```

`gravity agent` 完全离线，一次完成 bounded search + describe，优先返回匹配的 workspace recipe，再用 stable operation 补足默认 3 个、最多 5 个 capability cards。Recipe 卡片包含 `required_parameters`；operation 卡片包含压缩 input schema、`required_inputs`、父 operation、分页合同；两类都提供可直接调用的 `next.argv`。无 query 时运行 `gravity agent` 可取得 `gravity.agent.v1` 机器协议。明确且无冲突的 `monetization details/变现明细` 返回 value-free `monetization_detail` 卡；调用方只填 App/单日。用户/设备字段、筛选、分组或排序意图转到 `analysis.monetization_detail.list` raw discovery，并由 live metadata 校验；跨日、聚合、导出/写入、raw-like 后缀和相邻产品仍由本地 Guard 报 gap。
明确的 `attribution performance/归因表现/归因汇总` 返回 value-free `attribution_performance` 卡；调用方只填 App、日期，执行四组已证明画像，不接收任意指标/维度或单用户明细；`gravity.agent-call-bound.v1` 声明已知输入 1 次、未知 capability 2 次、未知 App 默认 3 次。
当能力和目录值都未知、但 App/平台等依赖上下文已知时，显式使用在线输入解析；必须写 JSON 文件，避免完整目录被 stdout 的 200 项安全上限截断：

```powershell
gravity agent "run saved analysis" --resolve-inputs '{"app":"main"}' --output catalog.json
# 调用方从 catalog.json 精确选择稳定 ID
gravity analysis saved run --app main --ref <selected-id> --start 2026-08-01 --end 2026-08-07
```

第一条会联网读取目录，但不执行候选、不选择值。响应明确标记内部 HTTP 未减少；只有完整目录才把动态卡的对应 `call_bound` scenario 降到 2。若还不知道 App，先解析 App 的依赖仍存在，不得套用该次数。SDK 使用同形 `resolve_capabilities()`；默认 `capabilities()` 与 batch Agent 继续完全离线。

多个问题不要逐个执行 `gravity agent`。一次提交带稳定 ID 的问题数组：

```json
{"questions":[{"id":"apps","query":"list apps","domain":"app"},{"id":"events","query":"event metadata","domain":"analysis"},{"id":"reports","query":"run saved analysis report-42","domain":"report"}]}
```

```powershell
gravity agent --input questions.json
```

这次调用只加载一次 Workspace、operation inventory、SQL product 和本地 metadata catalog，按问题输入顺序返回。Plan 候选带 `plan_node`；多个 Analysis Spec 卡只保留所选 kind 的合同引用，并附一个可复制的 `analysis_query_batch`，不重复整份 schema。自然业务问题只给本地物理候选和缺失决策，不选择字段或自动执行。调用方补齐后第二次执行 Plan/batch，因此仍是“发现一次 + 执行一次”。

选择卡片时检查：

- recipe 优先确认 `required_parameters` 已全部填写；
- operation 确认 `executable: true`、`stability: stable`，且 `required_inputs` 已全部填写；
- `next.argv` 中的 placeholder 已替换。

需要完整浏览 catalog 或查看 draft/blocked 覆盖缺口时，再使用 `operations search/describe`；这时再检查 `block_reason`、`currently_callable`、完整 schema 和 example。不要执行 blocked 候选，也不要读取 manifest 猜 wire 字段。

`--input` 以 `{` 或 `[` 开头时是内联 JSON，`-` 从 stdin 读取，其他值是文件路径；`--set a.b=c` 支持点路径。输入合并优先级是 `flag > --set > --input > 合同默认值`。

已知稳定 recipe 时更短：

```powershell
gravity run @retention-weekly --start 2026-08-01 --end 2026-08-07
```

stale recipe 会在同一个 envelope 返回下一步；此时才运行：

```powershell
gravity recipe check retention-weekly
```

## 3. 交叉查询：一个显式 Plan

Plan v1 把四类登记能力放入一个有界 DAG；预检失败时零网络请求：

```powershell
gravity plan schema
gravity plan run --input plan.json --dry-run
gravity plan run --input plan.json --concurrency 6
```

Analysis 查询复用 `analysis_query`，默认值字典用 `analysis_default_dictionary`，完整已登记变现明细用 `monetization_detail`，Multidim 使用 `multidim`，普通订单目录/拆单追踪使用 `order_directory`/`order_split_trace`，素材/推广表现分别使用 `material_performance`/`promotion_performance`，保存分析用 `saved_analysis`，人群规则/快照用 `segment_evaluate`/`segment_snapshot`，看板控制面/图表用 `dashboard_snapshot`/`dashboard_analysis`。已知完整输入时一次 `plan run`；未知时 Agent 发现、调用方补齐再执行，自然语言不自动执行。同层查询由全局 pool 并发并保声明序；binding 仅可写登记目标，结果不回显 request/spec/binding 值。完整合同见 [Plan 参考](reference/plan.md)。

## 4. 选择 Insight 还是 SQL

按以下顺序：

1. stable Insight operation；
2. 调用项目已经登记的 SQL 聚合产品；
3. 报告能力缺口。

即使 Insight 需要几项并发读取，只要能等价表达，也优先使用 Insight。只有跨表连接、窗口函数、特殊计算或已审核 Evidence 口径无法由 Insight 表达时，才使用 SQL。

已知 SQL 产品时直接执行，不先跑维护命令链：

```powershell
gravity sql query <product> --start <inclusive-iso> --end <exclusive-iso>
```

`query` 自己校验 workspace product；Evidence 可用时附 reference，不可用或过期时附 warning，不阻断产品查询。不要自动循环执行 `status`、`evidence-preflight`、`verify --publish`，也不要改用 Python `GravityClient.execute_sql()` 绕过产品治理。Evidence 发布需要维护授权。

## 5. 独立任务一次并发

多个 App、日期段、Analysis spec 或 operation 彼此独立时，使用正式 batch，而不是逐条起 CLI 进程或临时
线程脚本。首次不确定 wrapper 时查看一次 schema：

```powershell
gravity insight batch schema
gravity insight batch read --input <batch.json> --concurrency 6
```

最小 `batch.json`：

```json
{"requests": [
  {"operation_id": "app.list", "request_id": "page-1", "input": {"page": 1, "page_size": 1}},
  {"operation_id": "app.list", "request_id": "page-2", "input": {"page": 2, "page_size": 1}}
]}
```

batch 保持输入顺序、隔离单项失败并聚合退出码；默认并发 6、上限 24。单个 operation 的 `--all-pages` 只在首页返回明确 `total_page` 时按小窗口并发并保持页序；未知总页数串行。batch 内 `read_all` 固定单分页 worker，避免嵌套并发放大；不要在外层套线程池绕过进程/host 限流；SQL query 也接受单个、数组或 requests wrapper，并发上限独立且为 2。

## 6. 控制结果规模

先小范围读取，再扩大时间、分页或维度。大结果写文件，不把用户级数据完整输出到终端或
对话：

```powershell
gravity run <operation-id> --input <input.json> `
  --all-pages --max-pages 20 --max-items 5000 --concurrency 6 `
  --output tmp/result.ndjson --format ndjson
```

只需要部分合同字段时使用本地输出裁剪，默认不变；非法字段会在联网前以 caller/2 失败：

```powershell
gravity read app.list --input '{"page":1,"page_size":20}' --fields id,name
gravity run app.list --input '{"page":1,"page_size":20}' --fields id,name
```

`--fields` 只能选择合同允许的输出字段；动态字段还必须由本次请求显式声明。它不是绕过响应
投影的方式，也不会让未登记上游字段进入结果。

`run` 写脱敏 Receipt 到 workspace 私有 `state_root/receipts/`。它不保存输入值或结果行；
交付时可引用 operation、合同指纹、状态和请求数。

## 7. 离线元数据与 Analysis 词汇

一次同步同时保存 App 事件/属性和 workspace Analysis 词汇；可选保存 account 数据表沿革：
```powershell
gravity metadata sync --all-apps --include-table-lineage
gravity metadata search "purchase"
gravity metadata vocabulary "revenue" --kind metric
gravity metadata tables "publish"
```

词汇同步固定读取 9 个 workspace source，各一次且不随 App 数增长；六类 kind 是 `metric/custom_metric/metric_tag/metric_tag_category/media_enum/template`，都不接受 `app_id`。指标卡只给可复制的 `request_fragment`，模板是 `catalog_only`，没有配置回放。`status=partial` 时必须保留并报告失败来源，不能宣称完整覆盖。

已同步时直接离线查询一次；冷目录的两调用路径是先显式运行 `gravity agent "<query>" --resolve-inputs '{"catalog_policy":"refresh"}' --output catalog.json`，再执行返回的 metadata search/table-lineage 节点。第一次只有在所有请求来源成功时才原子发布新 catalog；否则报错并保留旧库。第二次结果带同步时刻，只表示 observed snapshot。`events/properties` 是 App scope；`tables` 是 account scope，只陈述观察到的 ID/版本/动作/时间。所有本地词汇只提供物理候选，不自动执行或绑定业务查询。需要同时查 operation、recipe 和 metadata 时调用：

```powershell
gravity find "retention"
```

## 8. 只在诊断要求时分支

`stale` 才运行 `recipe check`；`PARENT_REQUIRED` 按 diagnostics 解析父资源；`INPUT_INVALID` 重新 describe。`empty` 先核对 App、时间、时区和父资源，不能解释成业务未发生。认证只刷新一次，权限错误不循环；限流遵循 `retry_after_ms`；合同变化立即停止依赖新字段。任何分支都只保留结构化摘要，不输出请求敏感信息。

只有在严格 HTTP 预算内寻找一个可用输入组合时使用 `discover-nonempty`。它不是空结果后的默认重试器。

## 9. 导出

已知完整输入直接一次 `gravity export run ... --output <file.xlsx>`；未知时一次 `gravity agent "material report export"` 或 `gravity agent "user event export"` 加一次卡片 `next.argv`，自然语言不自动执行。当前 callable creator 是 `export.material.report.start` 与 `export.analysis.user_event.start`；status/cancel 和其余请求/文件合同未闭合的 Analysis 导出不生成 executable 卡。`stream_event` 的前端按钮只做客户端导出，没有待探测的 server request。Analysis 的用户级投影已放开，不能再把它写成隐私 blocker。
`--output` 是最终文件而非 JSON envelope；超时不取消，拿 `job_id` 走 status/wait/download，无可靠 ID 先 `export list`。分阶段命令只用于恢复；导出不进入 Plan v1。详见[导出指南](guides/export.md)。

## 10. 交付
至少说明：业务口径、`operation_id` 或 SQL product、App、时间范围、选择 Insight/SQL 的理由、成功/空/部分失败/能力缺口，以及不能支持的结论。不要把“没有查到”改写成“没有发生”。
CLI 退出码：`0` 成功（包括合同允许的 empty）；`2` 调用方错误，改输入或 selector 后可重试；`3` 上游/权限错误，换账号或申请权限；`4` 本地合同/隐私/策略错误，请求未发出，不要改输入重试。批量命令按最高严重级别聚合退出码，仍需读取每项结果。
