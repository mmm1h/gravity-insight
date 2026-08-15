# CLI 参考

本页只提供命令地图。参数细节以相应 `--help` 输出为准，输入 schema 以 `describe` 为准。

## 顶层命名空间

```text
gravity insight <command>     结构化读取和导出
gravity export <command>      一键治理导出及分阶段恢复
gravity agent [query]         单问题发现；--input 批量发现并返回 Plan 节点
gravity plan schema|run       预检或执行受控跨能力 DAG
gravity metadata <command>    本地物理元数据目录
gravity find <query>          跨 operation、recipe 与 metadata 检索
gravity recipe <command>      离线校验 workspace recipe
gravity run <selector>        单进程解析并执行 recipe 或 operation
gravity sql <command>         受控 SQL 产品
gravity census <command>      前端路由盘点
gravity analysis context      并发读取一个 App 的分析上下文
gravity analysis dashboard snapshot  读取一个看板的控制面快照
gravity analysis dashboard prepare|run  编译或执行一个看板的受支持图表
gravity analysis segment snapshot  读取一个分群的详情、历史与单日计算结果
gravity analysis saved ...    列出、读取、准备或严格重放保存分析
gravity analysis order directory  读取无标识的单日普通订单目录
gravity analysis order trace  按显式 TraceID 读取单日拆单明细
gravity apps snapshot         并发读取一个 App 的治理快照
gravity attribution snapshot  并发读取一个 App 的归因配置快照
gravity reports pulse         并发读取 App 经营概览与趋势
gravity reports usage         完整读取公司级按日资源用量趋势
gravity materials performance 读取稳定的跨平台素材表现
```

任意命令都可在顶层显式选择项目配置：

```powershell
gravity --workspace <gravity.toml-or-directory> <command> [options]
```

历史 Insight 命令可以省略 `insight`，但新文档和自动化应使用完整命名空间。

## Insight

Agent 优先从顶层机器协议开始：

```powershell
gravity agent
gravity agent "retention" --limit 3
gravity agent --input questions.json
gravity agent "run saved analysis" --resolve-inputs '{"app":"main"}' --output catalog.json
```

无 query 时返回两步协议；有 query 时优先返回匹配的 workspace recipe，再用 stable operation
补足 capability cards；可由 Plan 执行的卡含必填输入、下一条 `argv` 和 `plan_node`，默认 3 个、
最多 5 个，不访问网络。`--input` 接受最多 32 个唯一 ID 问题的 `{"questions":[...]}`，为
多个问题复用一次离线目录快照并按输入顺序返回；不能与 positional query、continuation、
domain 或 platform 组合。需要完整 catalog 或 blocked 覆盖信息时再进入
`operations search/describe`。

`--resolve-inputs JSON|FILE|-` 是显式在线模式，只用于 App/平台等依赖上下文已知、引用或物理字段
未知的场景。它把能力发现和完整 live catalog 读取放在第一条顶层命令中；不选择值、不执行候选。
该模式要求 `--output <local-file>` 和 JSON 格式，保证目录不受 stdout 安全摘要上限影响。调用方从
文件按稳定 ID（模板按 scope + ID）或物理名精确选择，再执行原命令/Plan，合计两次。响应中的
`input_resolution.internal_http_calls_reduced=false` 明确表示目录 HTTP 没减少。冷 metadata/table
catalog 使用 `{"catalog_policy":"refresh"}`；任一来源失败时不发布 staging catalog。默认 Agent
和 `--input` batch 仍离线；App 或 Promotion 平台也未知时不能套用两次下界。

| 命令组 | 用途 |
| --- | --- |
| `operations list/search/describe/schema` | 发现 operation 和输入合同 |
| `validate` | 离线校验输入，可选渲染脱敏 wire |
| `read` | 执行一个 operation，支持受控分页和文件输出 |
| `run` | 执行 `@recipe` 或 operation 的 Resolver 管线，并产出脱敏 Receipt |
| `recipe validate/check` | 离线检查 recipe 格式或 operation 漂移 |
| `discover-nonempty` | 在严格 HTTP 预算内发现非空组合；输出和缓存只保留输入字段名、脱敏语义错误码及字段提示，不保留值或响应消息 |
| `batch` | 批量执行独立的受控读取 |
| `parents resolve` | 解析 operation 需要的父资源 |
| `auth status/refresh` | 查看或刷新认证状态 |
| `export ...` | 一键创建/轮询/下载治理导出，或分阶段恢复 |
| `doctor` | 离线检查；`--live` 执行最小在线探针 |

领域命令如 `analysis`、`multidim`、`promotion`、`materials` 是受控 operation 的易用门面；不确定时从 `operations search` 开始。

`operations search` 会把可调用 stable 结果排在前面，也会展示部分 draft/blocked catalog
条目来说明覆盖缺口。执行前检查 `executable`、`stability` 和 `block_reason`，再以 `describe`
返回的 input schema 和 example 为准。

例如，先发现并审阅巨量标题素材合同，再执行受控分页读取：

```powershell
gravity insight operations search "巨量 标题 素材" --domain material
gravity insight operations describe material.bytedance_asset_text_title.list
gravity run material.bytedance_asset_text_title.list --set page_size=100 `
  --all-pages --output tmp/material-titles.ndjson --format ndjson
```

常用读取参数：

```text
--input/-i <json|file>   内联 JSON 或 JSON 文件；'-' 表示 stdin
--set <path=value>       点路径覆盖，可重复
--all-pages              遵循 manifest 分页合同
--max-pages <n>          最大页数
--max-items <n>          最大返回条数
--concurrency <1..24>    已知总页数时的分页 worker（默认 6）
--output <path>          写入本地文件
--format json|ndjson     输出编码
--fields <a,b>           本地裁剪为合同允许字段；可重复
```

`--fields` 也适用于 `run` 和 `batch run`；批量 item 与 Plan 节点也可单独使用
`output_fields`（item 值优先于批量默认值）。默认不指定时输出完全不变；未知字段会在联网前返回 caller/2。动态字段只能
选择请求已经声明且合同允许的字段。

结果型 `--output` 在同目录写临时文件并原子替换目标；写入成功后 stdout 只返回收据，不再混排结果：

```json
{
  "format": "json",
  "ok": true,
  "output": "tmp/result.json",
  "size_bytes": 1234,
  "status": "written"
}
```

`size_bytes` 是实际 UTF-8 文件字节数。已有 NDJSON 编码的行数继续由文件末尾
`_gravity_insight.rows_written` 表示，外层收据不另加字段。纯 `error`/`capability_gap` 不创建或替换
目标；支持 partial 的新产品写入完整 partial envelope，并原样返回非零退出码。

Insight 普通批量读取默认并发为 6，显式上限为 24；Metadata 同步允许 `1..24`。单次分页
读取在首页有明确总页数时按小窗口并发并保持页序，未知总页数时串行；batch 内的分页读取
强制单分页 worker，防止嵌套放大。这些是 worker 上限，实际请求仍受每 host 限流、重试和
共享冷却约束。

## Multidim

公开入口直接接受稳定的闭合物理输入，不增加一套字段改名后的 Spec DSL。App 单独绑定；
`--input-schema` 可离线取得机器合同，`--dry-run` 在构造 client 前完成本地预检：

```powershell
gravity multidim query --input-schema
gravity multidim query --app main --input <query.json> --include-total `
  --all-pages --max-pages 20 --max-items 5000 --concurrency 6
gravity multidim query --app main --input <query.json> `
  --filter click_company IN bytedance,tencent `
  --custom-metric roi_after_tax --relate-dim advertiser_name
```

产品 dry-run 必须显式写在子命令后并提供 App：`gravity multidim query --app main --input ... --dry-run`。
根级 `gravity --dry-run` 是全仓合同自检，不能与任何命令组合。除纯离线
`--input-schema` 外，缺少 `--app` 的专用 query 会在构造 client 前失败；不会使用 workspace 默认
App，也不会回退到 raw operation。

input 只含 `date_list/time_dims/metrics_list/custom_metrics_list/data_dims/relate_dims/filters/multi_keys`。
三个新增便利层直接复用物理字段：`--custom-metric NAME[,NAME...]` 覆盖
`custom_metrics_list`，`--relate-dim NAME[,NAME...]` 覆盖 `relate_dims`，
`--filter FIELD OPERATOR VALUE[,VALUE...]` 覆盖 `filters`。快捷参数优先于 `--set`，`--set`
优先于 `--input`；未出现的快捷参数不修改对应物理字段。filter value 按 JSON scalar 解析，
不能用快捷参数表达的字面值继续使用 `--input`/`--set`。

真实 artifact 未提供多 filter 组合语义证据，因此当前 `--filter` 最多出现一次，且不能和
`--media` 同用；重复条件在联网前拒绝。该边界也由 `--input-schema` 的
`x-cli-shortcuts.filter` 机器字段声明。已有版本化物理 `filters[]` 合同不收缩：专家仍可通过
`--input`/`--set` 使用原合同形状，其语义与优先级不变。
`--app` 接受 workspace alias 或正整数；专用入口不再接受 `--app-id` 或 `--parent-id`。Agent 不会填
App、日期或 filter value；物理指标/维度未知时可在 App 和其余业务输入已知的前提下用在线输入解析
取得闭合 schema 与 live catalog，调用方仍精确选择。直接执行默认 6 workers、最大 24；Plan adapter 固定 1。`--include-total`
才会在 query 后串行计算 total，`--all-pages` 使用受控分页。HTTP 数为去重 metadata `M` + query
页数 `P` + 可选一次 total。已知输入一调用；能力/物理字段未知时是一次在线 Agent 解析加一次 Plan。多个查询
应放进一个 Plan，不新增 batch wrapper。

产品结果固定为 `gravity-insight.composite.multidim.v1`；业务行读取
`query.data.list`，并同时校验顶层 `status/exit_code` 和 `query.status`。`partial` 不是成功明细的
同义词，调用方必须按结构化状态处理。独立的 `multidim calc-total` 子命令已删除；合计只通过
`query --include-total` 请求。需要精确 raw operation 的专家流程继续使用
`gravity run report.multidim.query` 或 `gravity run report.multidim.calc_total`。

Multidim 不回放 template，不处理图表/透视、layout、收藏、拖拽、成员权限或业务指标语义；这些
边界也不会通过 `--input` 扩张。

## Material Performance

`materials list/tags/reviews` 保持原有兼容入口；新产品使用独立子命令：

```powershell
gravity materials performance --app main --app secondary `
  --start 2026-08-01 --end 2026-08-07 `
  --platform bytedance --platform tencent `
  --concurrency 6 --max-pages 20 --max-items 5000 `
  --output tmp/material-performance.json
```

`--app` 可重复或逗号分隔，接受 workspace alias 或正整数；平台省略时为
`bytedance/tencent/kuaishou/bilibili`。所有本地输入和输出路径先校验，之后才构造 client。
命令只写完整 JSON，不提供 NDJSON，以免破坏平台分组、分页收据和 partial 失败信息。

每个平台调用一次现有 stable `material.report.query` 并读取受控分页，多个 App 合并进该平台的
`app_list`；HTTP 数为 `Σ P_platform`。direct worker 范围 1..24、默认 6，实际池不超过平台数且
最多 4；每个平台分页 worker 固定 1。`max_items` 是共享声明预算，batch 实际给每个平台
`floor(max_items/platform_count)` 的不可借用份额。结果按平台声明序，物理指标保持原名；不生成
归一指标、总计、排名或业务结论。

## Promotion Performance

21 个合同同构的平台使用一个显式只读产品入口；App、日期、平台和物理指标都必须给出：

```powershell
gravity promotion performance --app main --start 2026-08-01 --end 2026-08-07 `
  --platform bytedance --metric stat_cost --concurrency 6
```

`--platform`、`--metric` 可重复或逗号分隔。每个平台一个 batch item，分页 worker 固定 1；direct
平台池默认 6、最大 24。`max_pages` 按平台生效，`max_items` 按平台数等额 floor 分配且不可借用。
输出保留原生物理字段和平台声明序，不做跨平台归一、总计、排名或策略。
完整结果可用 `--output <path>` 写入 JSON；该产品不提供 NDJSON，以免拆散平台 component、分页
收据和 partial 失败信息。
同一个指标数组会发给每个所选平台；多个平台只有在各自实时元数据都证明该同名物理指标时才应
放进同一请求。平台原生指标名不同则使用同层 Plan 节点并发，SDK 不猜字段映射。
平台已知而指标未知时，可先用
`gravity agent "promotion performance" --resolve-inputs '{"platforms":["bytedance"]}' --output metrics.json`；
调用方精确选择后第二次执行上面的产品命令，执行端仍由 FieldPolicy live 复验。平台也未知时不适用。
`bing/xiaohongshu/taptap/wechat_video` 不满足共同合同，继续使用兼容的 `promotion query/snapshot`。

批量 wrapper 可由机器自描述，不需要猜 JSON 字段：

```powershell
gravity insight batch schema
gravity insight batch read --input <batch.json> --concurrency 6
gravity insight batch schema --mode run
gravity insight batch run --input <resolver-batch.json> --concurrency 6
```

`batch read` 接受 operation；`batch run` 接受 recipe 或 operation selector，并为每项执行完整
Resolver 流水线。run item 可含 `selector`、`input`/`inputs`、`parameters`、`app`/`apps`、
`start/end`、`request_id` 和 `all_pages`。`apps` 数组保持声明顺序；`apps: "*"` 只展开当前
workspace 已绑定的 App alias，并按 alias 排序。外层并发保序且隔离错误，内层分页 worker
固定为 1；默认每项最多 5 页/200 项，可用 `--max-pages/--max-items` 显式调整。两种 batch
分别用自己的 schema 自描述，并按最高严重级别聚合退出码。

固定组合能力避免 Agent 手工执行一串独立命令：

```powershell
gravity analysis context --app main --concurrency 6
gravity analysis dashboard snapshot --app main --ref <id-or-exact-name> --concurrency 5
gravity analysis segment snapshot --app main --ref <id-or-exact-name> --date <YYYY-MM-DD> --concurrency 3
gravity apps snapshot --app main --concurrency 6
gravity attribution snapshot --app main --concurrency 6
```

`--app` 接受 workspace alias 或正整数；归因命令继续接受 `--app-id` 兼容别名。Analysis
context 固定 13 个词汇/模板来源，App snapshot 固定 6 个治理来源；Attribution snapshot 固定
覆盖当前 8 个 stable attribution operation，其中两个 postback map 自动读取全部页。这三者
默认并发 6；Dashboard snapshot 默认 5，Segment snapshot 默认 3；所有组合上限均为 24，按固定来源顺序返回并隔离局部
失败。Attribution snapshot 不包含仍为 draft 的聚合归因和用户/设备级明细查询。

### Governed export

已知 operation 和完整输入时，默认一次调用：

```powershell
gravity export run export.material.report.start --input material-export.json `
  --columns file_name,gravity_material_id,stat_cost `
  --idempotency-key material-20260812-001 `
  --output D:\exports\material.xlsx --timeout 300
```

`run` 接受 `<operation-id> --input <json|file|-> [--set PATH=VALUE] --columns <csv>
--idempotency-key <key> --output <file> [--timeout 300]`，复用现有状态机完成创建、轮询、下载、
隐私/schema 验证和原子提交。`--output` 只指定导出文件；JSON envelope 继续写 stdout，不覆盖
目标文件。未知导出先一次 `gravity agent "material report export"`，审阅卡片并补齐
`input/columns/idempotency_key/output` 后执行 `next.argv`，总共两次且不自动执行自然语言。

Agent 只为 `currently_callable=true` 的 `export_job_create` 返回 executable 卡；当前唯一操作是
`export.material.report.start`。status/cancel 路由和 blocked Analysis exports 不作为创建候选。
卡片明确 `natural_language_auto_execute=false`、`plan_executable=false` 和 `plan_node=null`；导出
不进入 Plan v1。

`start/status/wait/download/cancel/list` 是人工和恢复命令。run 或 wait 超时不会自动取消；已有
`job_id` 时用 status/wait 后在 READY 时 download 到同一显式路径。创建结果不确定且没有可靠
ID 时先 `gravity export list --page 1 --page-size 100`，不要直接重跑。详见
[导出指南](../guides/export.md)。

### Analysis Query Spec v1

`analysis query` 支持五种稳定分析：`event`、`funnel`、`retention`、`property`、`scatter`。
使用 `--spec` 时，调用方只声明事件、指标、日期、分组、窗口和条件等分析语义；编译器负责
生成 `query_id`、`query_item_list`、`group_by_list` 等上游 wire 结构。先查看机器合同：

```powershell
gravity analysis query --kind event --spec-schema
```

`--spec-schema` 完全离线，不创建客户端。`--spec` 接受内联 JSON、JSON 文件路径或 `-`
（stdin）；`--app <alias|id>` 选择 workspace App，`--workspace <file|directory>` 显式选择
workspace。`--start/--end` 必须成对使用，并覆盖 spec 中的日期。

下面的事件分析按天统计 `app_open` 的总次数。执行前应确认 `app_open` 是目标 App 的真实物理
事件名；如果不确定，先运行一次 `gravity metadata search "app_open" --app-id 1001`：

```powershell
gravity analysis query --kind event --app 1001 --spec '{
  "start": "2026-08-01",
  "end": "2026-08-07",
  "time_grain": "day",
  "steps": [
    {
      "event": "app_open",
      "metric": {
        "field": "PresetAllCount",
        "aggregation": "PresetAllCount"
      }
    }
  ]
}'
```

下面的漏斗查询使用 workspace 的 `main` App，并通过 CLI 日期覆盖指定时间；窗口是一天：

```powershell
gravity analysis query --kind funnel --workspace . --app main `
  --start 2026-08-01 --end 2026-08-07 --spec '{
  "steps": [
    {
      "event": "app_open",
      "metric": {
        "field": "PresetAllCount",
        "aggregation": "PresetAllCount"
      }
    },
    {
      "event": "purchase",
      "metric": {
        "field": "PresetAllCount",
        "aggregation": "PresetAllCount"
      }
    }
  ],
  "window": {"unit": "day", "value": 1}
}'
```

在上述命令末尾加 `--dry-run` 会离线编译并运行现有输入校验，保证
`network_called=false`，同时返回 `operation_id`、`compiled_input` 和可放入 Plan 的
`plan_node`。带条件值时预览会用占位符脱敏并把 `plan_node` 设为 `null`，避免同一敏感值在机器输出中重复；仍可直接执行原始 compact spec。正常执行已经包含相同编译与校验，不需要每次先跑 dry-run。

Spec 不接受自然语言，也不会猜测事件、属性、指标、窗口或筛选条件。物理字段未知时，先用
本地 metadata 目录确认，再执行一次 spec；自然语言能力发现仍只返回候选，不会自动联网执行。
原始 `--input` 入口继续兼容，但不能与 `--spec` 同时使用。

多个彼此独立的 compact spec 直接使用一次批量入口；它先编译全部 1–32 项，再交给同一个
Plan 全局 worker pool，并按输入顺序返回：

```powershell
gravity analysis query batch --input queries.json --concurrency 6 --dry-run
gravity analysis query batch --input queries.json --concurrency 6 `
  --output tmp/analysis-batch.json
```

`queries.json` 使用 `gravity.analysis-query-batch.v1`，每项必填唯一 `id/kind/app/spec`，可选
`start/end/output_fields/limits.max_items`。`--dry-run` 对整批完成零网络编译与 Plan 预检；任一
wrapper、预算或 literal spec 错误都会在执行前失败。正常执行保序、隔离 sibling 失败，且不回显
spec、compiled input 或筛选值。不要为批量查询再创建外层线程池。标量 query、batch 与下述多 App
入口都可用 `--output <path>` 原子写入完整 JSON；不提供 `--format`。

```json
{
  "schema_version": "gravity.analysis-query-batch.v1",
  "queries": [
    {
      "id": "daily_opens",
      "kind": "event",
      "app": "main",
      "spec": {
        "start": "2026-08-01",
        "end": "2026-08-07",
        "steps": [{"event": "app_open", "metric": {"field": "PresetAllCount", "aggregation": "PresetAllCount"}}]
      },
      "limits": {"max_items": 200}
    }
  ]
}
```

同一 spec 跑多个 App 时只把合同版本和 App 参数改为 v2 的显式数组；当前支持
`event/funnel/retention/property`：

```powershell
gravity analysis query --kind retention --spec retention.json `
  --apps main,overseas,103 --concurrency 6 --output tmp/retention.json
```

`--apps` 可重复；它与 `--app`、跨期对比互斥。`--dry-run` 会编译每个 App 并完成 Plan 预检，
但不执行查询。Agent 或 SDK 需要直接生成机器输入时使用同一 v2 合同：

```json
{
  "schema_version": "gravity.analysis-query-batch.v2",
  "queries": [{
    "id": "weekly_retention",
    "kind": "retention",
    "apps": ["main", "overseas", 103],
    "spec": {"start": "2026-08-01", "end": "2026-08-07", "steps": ["<explicit-steps>"]},
    "limits": {"max_items": 200}
  }]
}
```

`apps` 必须是非空、唯一的 workspace alias/正整数数组；不支持 `"*"`，alias 与 ID 解析到同一
App 也视为重复。所有 query 展开后合计最多 32 个组件，超限在 Plan 前失败且零执行。每个组件
在 v2 result 中带原始 `query_id` 和提交的 `app`，保留自己的 `ok/status/result/error/exit_code`；
顶层沿用 Plan 的 success/empty/failure 计数与退出码优先级，并固定
`cross_app_aggregation=false`。SDK 不跨 App 合并行，不计算排序、TopN、汇总、差异或比率。

v1 的 `app`、节点 ID、`gravity.analysis-query-batch-result.v1` 和结果字段完全不变。v2 只做机械
展开：每个 App 仍是一个现有 `analysis_query` Plan 节点，adapter worker 固定 1，唯一并发预算是
`--concurrency` 对应的 Plan 全局预算。总请求集合等于各 App 单独执行的并集，不增加 metadata、
重试或探测请求；只可能把峰值在途数从 1 提高到该全局预算允许的值。

有依赖、binding 或需要混合 SQL/metadata/composite 时使用 `gravity plan run`。Plan composite
request 是 `name="analysis_query"` 加
`kind/app/spec`，可选成对的 `start/end`；`output_fields` 放在节点级：

```json
{
  "id": "daily_opens",
  "kind": "composite",
  "request": {
    "name": "analysis_query",
    "kind": "event",
    "app": "main",
    "spec": {
      "start": "2026-08-01",
      "end": "2026-08-07",
      "steps": [{"event": "app_open", "metric": {"field": "PresetAllCount", "aggregation": "PresetAllCount"}}]
    }
  },
  "limits": {"max_pages": 1, "max_items": 200}
}
```

节点 `output_fields` 按底层 Analysis operation 的 data-relative FieldPolicy 选择，例如 event
可选 `list/target_list/date_list`；它不是 composite wrapper 字段。

五种 kind 与 `analysis query` 相同：`event/funnel/retention/property/scatter`。已知 kind、App
和 literal spec 时，一次 `gravity plan run --input plan.json`；未知时一次 `gravity agent`
发现候选、一次 `plan run` 执行。自然语言不会自动执行。`/app` 可以接受既有标量 binding；
`/spec/...` binding 和 spec 内部引用不受支持。完整事件示例及 event+funnel 同层并发示例见
[Plan v1 参考](plan.md#analysis-query-composite)。

### Single-user journey

已知 App、用户标识和时间窗时，一次并发读取受控 profile、event timeline 与 postback：

```powershell
gravity analysis user journey --app main --client-id <explicit-id> `
  --start 2026-08-01 --end 2026-08-07 --page 1 --page-size 20
```

也可用单个 `--date`；`--event/--field` 可重复，`--concurrency` 默认 3。结果固定按
`profile/events/postbacks` 排序并隔离局部失败，不回显 client ID、request 或凭据。上游
user-event 尚无已证明的 `page_info`，因此 v1 只读取显式页并返回
`continuation.automatic=false`；调用方根据下一页提示显式重试，不伪造自动分页。

### Order Directory v1

已知 App 和严格单日时，一次完整读取无标识的普通订单目录：

```powershell
gravity analysis order directory --app main --date 2026-08-08 `
  --concurrency 6 --max-pages 1000 --max-items 100000 --output <file.json>
```

命令固定调用 `analysis.order_detail.list`，使用 `page_size=100`、空 conditions/order 和四个静态
字段。成功的每行严格只含 `Amount/BackAmount/Status/CreateTime`；任何额外订单、用户、拆单或
归因标识，畸形 scalar、不完整分页收据、continuation 或预算越界都会使整个结果 fail closed，
不会裁剪前缀后冒充完整目录。它不接受任意 fields/filter/sort 或跨日窗口，也不解释退款、净收入
或订单成功。

有效请求实测为 `P` 个目录 POST、0 metadata、0 child；最小空日为 1 HTTP，7 个同层空日 Plan
节点为 7 HTTP。direct 分页 worker 默认 6、最大 24；
Plan adapter 固定 1。省略 `--output` 时输出安全 stdout 前缀；指定它时写入完整 JSON。
产品不提供 NDJSON 或 `--format`。未知入口时 Agent 返回唯一
`order_directory` Plan 节点及待填写的 `app/date`，不从自然语言取值或自动执行；否定、导出、
写入及相邻分析产品会安全报缺口且不扫描 operation inventory。精确 raw selector
`analysis.order_detail.list` 与 `analysis.order_split_detail.list` 仍保留专家兼容入口。

### Monetization Detail v1

`gravity analysis monetization detail --app main --date 2026-08-08` 固定使用已批准的无标识字段
allowlist 和严格单日，不接受动态 fields/conditions/group。有效请求实测为 `P` 个明细 POST、
0 metadata；最小空日为 1 HTTP。未知上游字段默认隐藏，永久排除字段与隐私投影边界见
[路线图](../roadmap.md#已批准的隐私投影边界变现明细d27)。

### Order Split Trace v1

已知 App、单日和显式 TraceID 时，使用一次受控 parent-child 读取：

```powershell
gravity analysis order trace --app main --date 2026-08-08 `
  --trace-id <explicit-sensitive-trace-id> --concurrency 6 `
  --max-pages 1000 --max-items 100000
```

命令固定以 `page_size=100` 和四个静态父字段完整读取受限单日目录，再在本地对 TraceID 做
大小写敏感的精确匹配。它不会把 TraceID 作为未经证明的上游 filter；零条、多条、截断、畸形
分页收据或预算不足都在 child 前 fail closed。唯一父行才触发一次严格后置的
`analysis.order_split_detail.list`，有效请求数为 `P + 1`。

direct 父分页 worker 默认 6、最大 24；`max_items` 由父扫描行和 child 行共享。产品只输出完整
JSON，不提供 NDJSON；成功行只保留 `Amount/BackAmount/Status/CreateTime`，结果和错误均不含
TraceID、ClientID、拆单 ID、PayEventTime、request 或原始异常。未知入口时 Agent 只给待填写的
`order_split_trace` Plan 节点，不提取、显示或执行自然语言中的 TraceID；精确 raw selector
`analysis.order_split_detail.list` 保持专家兼容。

### Dashboard control-plane snapshot

已知 App 和看板稳定 ID/精确名称时，一次调用读取看板控制面，不需要在 Web 中逐页检查：

```powershell
gravity analysis dashboard snapshot --app main --ref <id-or-exact-name> `
  --concurrency 5 --max-pages 5 --max-items 200
```

命令先用看板目录精确解析 `--ref`；名称歧义或不存在时 fail closed，不选择相似名称。解析后按
固定顺序读取 detail、dashboard members、space members、condition favourites 和 default
favourite 五个来源，保留 scope、operation identity 与局部失败。目录树仅用于精确解析引用，
不计入结果来源；detail 中未被合同证明的 opaque
config 会被裁剪；本产品不编译该 config，也不运行、重放或渲染看板图表。

CLI/SDK 外层并发默认 5、上限 24。Plan 使用 `{"name":"dashboard_snapshot","app":...,"ref":...}`；
adapter 内部固定 1 worker，由 Plan 全局 pool 管理并发。引用已知时直接执行是一次调用；App 已知、
引用未知时先用 `agent --resolve-inputs '{"app":"main"}' --output dashboards.json` 取得完整 live tree，
调用方精确选择稳定 ID 后执行 Plan，共两次。自然语言发现不会猜引用或自动执行。

结果较大时可把 `--output <path> --format json|ndjson` 放在 `snapshot` 子命令参数末尾；不指定
`--output` 时 JSON 输出仍受统一 stdout 裁剪保护，`--format ndjson` 可流式写到 stdout。

### Dashboard Analysis Replay v2

已知 App、看板引用和时间窗时，一次调用即可编译或执行声明的图表：

```powershell
gravity analysis dashboard prepare --app main --ref "Growth Overview" `
  --start 2026-08-01 --end 2026-08-08 --max-charts 32
gravity analysis dashboard run --app main --ref "Growth Overview" `
  --start 2026-08-01 --end 2026-08-08 --concurrency 6 `
  --max-charts 32 --max-items 100000
```

`prepare` 读取目录和详情、编译支持的 chart，但不执行最终查询；`run` 使用同一编译结果并发
执行，默认 6、上限 24，默认最多 32 个 chart，显式 `--max-charts` 硬上限 64。结果严格按看板
声明顺序返回，单图不支持或失败不会取消 sibling。start/end 都包含在 Gravity `date_list` 内，
允许同一天，最长 90 天；`--max-items` 同时约束目录、图表和结果规模。

编译器边界来自公开静态 Web artifact 中已证明的 event/funnel/retention/property/scatter
配置构造。它不是浏览器模拟器：不解释布局，不应用 favourite，也不模拟页面级 global filter；
无法证明的 subject/config 以结构化 unsupported chart 返回，不猜字段或改用任意 HTTP。

引用已知时 CLI/SDK 是一次顶层调用。App/窗口已知、引用或能力未知时先运行带
`--resolve-inputs` 的 Agent，精确选择 live tree 中的稳定 ID 后执行其 Plan node，总共两次；
自然语言卡永远不自动执行。

### Segment Snapshot v1

已知 App、分群稳定 ID/精确名称和单日日期时，一次调用替代 Web 中的目录、详情、历史和当日
结果页面切换：

```powershell
gravity analysis segment snapshot --app main --ref <id-or-exact-name> `
  --date 2026-08-01 --concurrency 3 --max-pages 5 --max-items 200
```

命令先精确解析 `--ref`，歧义或不存在时 fail closed；随后固定按 `detail/history/daily_result`
顺序读取并隔离局部失败。`--date` 是单个 `YYYY-MM-DD`，不表示趋势时间窗。结果不包含成员、
用户标识、规则定义、request 或原始异常；结果 schema 是 `gravity-insight.segment-snapshot.v1`，
固定 `source_count=3`，最小 `max-items` 为 4（目录命中与三个来源）。

已知输入时 CLI/SDK 是一次调用。App/日期已知、引用未知时，只有明确包含“分群快照/检查 + 详情 +
历史 + 单日计算结果”的强意图才会在线返回完整分群目录；调用方精确选择稳定 ID 后执行 Plan，共两次。
泛分群、规则评估、成员/用户列表、导出和写操作不会命中，且自然语言不会自动执行。

### Segment Rule Spec v1

人群规则人数/占比评估使用紧凑 spec，不需要拼接 FE_CONFIG 或上游 Web JSON：

```powershell
gravity analysis segment evaluate --spec-schema
gravity analysis segment evaluate --app main --spec segment.json --dry-run
gravity analysis segment evaluate --app main --spec segment.json --fields part,percent,total
```

`--spec` 接受内联 JSON、文件或 `-`；`--start/--end` 可覆盖 spec 日期。顶层字段是
`app/name/remark/update_type/start/end/logic/property_rules/event_rules`，完整条件、事件目标、日期
模式和枚举以 `--spec-schema` 为准。`--dry-run` 只编译并执行离线校验，返回脱敏预览和
`needs_live_metadata` 依赖，不发最终查询；物理事件、属性、分群与版本仍需执行阶段的实时元数据
证明。旧 `analysis segment --kind evaluate --input ...` 继续兼容现有调用方。

明确询问“人群/受众规则命中人数或占比评估”时，`gravity agent` 唯一返回
`analysis.segment.rule.spec` 强卡，包含完整紧凑 schema、缺失的 `app/spec` 和可复制的
`segment_evaluate` composite Plan 节点；自然语言不生成规则或自动执行。泛分群、成员、历史、
详情和导出不会误配此卡。

### Saved Analysis v2

保存分析入口把稳定的保存目录、详情读取和现有 Analysis Spec 编译器连成一条受控路径。已知
引用时不要手工执行 `operations search/describe`，直接运行：

```powershell
# 浏览目录；list 不需要 --ref
gravity analysis saved list --app main --concurrency 6

# 按稳定 ID 或精确名称查看受控定义摘要
gravity analysis saved get --app main --ref <id-or-exact-name>

# reference Web artifact：读取定义并编译，但不执行最终分析查询
gravity analysis saved prepare --app main --ref <id-or-exact-name> `
  --start 2026-08-01 --end 2026-08-07

# 本地 definition 直接严格编译，零网络且不需要 Gravity 凭据
gravity analysis saved prepare --app main --definition <json-object-or-file>

# reference Web artifact：一次解析、严格编译并执行
gravity analysis saved run --app main --ref <id-or-exact-name> `
  --start 2026-08-01 --end 2026-08-07
```

`--app` 接受 workspace alias 或正整数。`--ref` 只接受稳定 ID 或精确名称；精确名称命中
多个项目会以 caller/2 失败，要求改用稳定 ID，不会静默选择第一项。分析 kind 由保存定义
中已登记的 subject 决定，调用方不能覆盖。若 reference 是 Web artifact，`prepare/run` 必须提供
成对 `--start/--end`；两端会包含在下发窗口中且 `end-start` 不超过 90 天，主路径建议
`YYYY-MM-DD`。旧 compact reference 可省略 window，并保留原定义的日期语义；只提供一端始终在
建客户端前失败。`list/get` 不要求日期窗，`get` 会明确报告该引用是否需要 window。

Strict Replay 不是通用 Web 配置翻译器。reference 模式只接受静态证据已证明的 Web artifact，
并直接复用现有 `event/funnel/retention/property/scatter` 五类编译器；未知字段、无法证明的
opaque config 或其他 kind 均结构化失败，不降级为裸请求。显式 `--definition` 的 compact spec
保留旧兼容模式。两种模式都不解释 template、layout、favourite、权限或页面状态。
`list/get/prepare/run` 均支持 `--output <path>` 与 `--format json|ndjson`；目录较大时应显式落盘，
避免 stdout 的安全摘要上限遮住后续条目。
四个命令也都接受 `--concurrency 1..24`（默认 6），只在目录首页证明总页数后并发读取后续页，
结果仍按页码保序；未知总页数保持串行。Plan adapter 固定分页 worker 为 1，避免与 Plan 全局并发相乘。
`prepare --ref` 为解析引用会读取在线目录以及必要详情，所以它不是离线 dry-run；它与 `run`
的区别是不会发送最终分析查询。`list/get` 也会访问已登记的 stable 只读 operation。

Agent 查询 `run saved analysis <ref>`、`运行保存分析 <引用>`，包括 `--domain report`，唯一
权威候选是 `composite:saved_analysis`。卡片明确缺失 `app/ref/start/end`，Plan request 为四项
提供可机械填写的槽位，可选 `mode=prepare|run`；发现本身完全离线，也不会从自然语言提取引用
或自动执行。已有引用和窗口但不知道能力时是离线 Agent + Plan 两次；App/窗口已知而引用未知时，
在线输入解析把能力卡和完整 safe catalog 放进第一调用，调用方按稳定 ID 选择后第二次执行。

### Business pulse

一个命令并发读取 App 概览和经营趋势；`--app` 可重复或用逗号分隔，支持 workspace alias 或
正整数。平台默认包含 `bytedance/tencent/kuaishou`，可重复指定 `--platform`：

```powershell
gravity reports pulse --app main --start 2026-08-01 --end 2026-08-07 `
  --platform bytedance --include-hourly --output tmp/business-pulse.json
```

基础结果按 `overview`、`business` 顺序；`--include-hourly` 才追加
`hourly_comparison`。前两项是 `scope=app`，小时对比受上游合同限制并明确标记
`scope=workspace`，不能解释为单个 App 的小时结果。组合复用现有 stable operation、批量并发、
分页和局部失败合同；不推导业务结论或指标别名。

`--output` 原子写入完整 JSON，不提供 `--format`。`partial` 仍写文件并保留非零退出码，成功与失败
source 都留在 envelope 中；纯 `error` 或 `capability_gap` 不创建也不替换目标文件。

未知入口使用 `gravity agent "business pulse" --domain report`。明确 Pulse/脉搏或同时表达经营
概览与趋势的请求返回唯一 `composite:business_pulse`，且不扫描 operation inventory；卡片给出
完整的 `apps/start/end/platforms/include_hourly` Plan request。调用方显式替换占位值后执行，
自然语言不填值也不自动执行。泛 `business analysis/经营分析` 和多维、看板、保存分析、归因、
模板或导出意图不会被 Pulse 抢占。

同一 `reports` 命名空间还提供无 App 输入的公司资源用量趋势：

```powershell
gravity reports usage --max-pages 1000 --max-items 100000
```

命令完整分页读取已登记的广告、广告创建、点击、成本、事件、画像、存储、追踪和素材传输用量，
返回 `gravity-insight.company-usage.v1`；稳定投影固定排除 `user_count`，未知上游字段继续
fail closed。未知入口使用 `gravity agent "company resource usage" --domain report`，返回唯一
`composite:company_usage`，无需补 App、日期或引用，发现后执行共两次调用。

### Custom audiences

自定义人群覆盖与状态是独立 Promotion 产品，不属于 promotion performance：

```powershell
gravity promotion custom-audiences --max-pages 1000 --max-items 100000
```

命令完整分页读取可投人群的覆盖数、上传数、来源和状态，返回
`gravity-insight.custom-audience.v1`。`cid/company/create_user_*/tag/update_user_*` 固定省略，
未登记字段失败关闭。未知入口使用 `gravity agent "custom audience coverage status"
--domain promotion`，返回无缺失输入的唯一 `composite:custom_audience` 卡。

## Plan v1

```powershell
gravity plan schema
gravity plan run --input plan.json --dry-run
gravity plan run --input plan.json --concurrency 6
```

`schema` 输出 `gravity.plan-schema.v1`，包括节点类型、字段、预算和失败合同。`run` 的输入必须
是 `gravity.plan.v1` 对象。最小可复制示例：

```json
{
  "schema_version": "gravity.plan.v1",
  "nodes": [
    {
      "id": "apps",
      "kind": "run",
      "request": {
        "selector": "app.list",
        "inputs": {"page": 1, "page_size": 20}
      },
      "limits": {"max_pages": 1, "max_items": 20},
      "output_fields": ["id", "name"]
    }
  ]
}
```

四种节点：

| `kind` | `request` 核心字段 | 执行边界 |
| --- | --- | --- |
| `run` | `selector`、`inputs`/`parameters`、可选 `app/start/end/all_pages` | operation 或 `@recipe` |
| `sql_product` | `product` 及该 Workspace 产品的 App/时间输入 | 已登记产品，禁止裸 SQL |
| `metadata_search` | `query`、可选 `kind/app_id/limit/offset` | 已同步的本地 catalog |
| `composite` | `name`、组合所需 App/查询输入 | 仅登记的 analysis/segment query、context/dashboard/app/attribution snapshot、business pulse/company usage、multidim、material/promotion performance |

每个节点还可声明 `depends_on`、标量 `bindings`、一个有限 `foreach`、`limits` 和
`output_fields`。binding/foreach 的 `from` 必须显式位于 `depends_on`，路径使用 RFC 6901 JSON
Pointer。预检覆盖 schema、ID、依赖、环、pointer、adapter 输入和最坏预算；任一节点预检
失败时零网络请求。

Business pulse 的 Plan 节点使用同一实现；`apps/start/end` 必填：

```json
{
  "id": "pulse",
  "kind": "composite",
  "request": {
    "name": "business_pulse",
    "apps": ["main"],
    "start": "2026-08-01",
    "end": "2026-08-07",
    "include_hourly": true
  },
  "limits": {"max_pages": 20, "max_items": 5000}
}
```

Plan 中小时结果仍为 `scope=workspace`；adapter 内部 worker 固定为 1，由 Plan 全局 worker pool
管理并发。binding 只接受 `/start`、`/end`、`/include_hourly`；`apps/platforms` 必须在提交前
作为显式数组给出，Plan v1 不把 scalar binding 当作数组。

`analysis_query` 同样由全局 pool 调度；同层独立查询并发，adapter worker 固定 1。一个查询
失败不取消 sibling，结果仍按节点声明顺序返回。节点 `max_items` 和 Plan 总预算共同限制结果
规模；失败结果不回显 request、spec、binding 值或原始异常，筛选值遵守既有脱敏合同。

外层并发默认 6、上限 24，adapter 内分页 worker 固定 1；SQL 的进程级并发仍为 2。声明节点
最多 64、展开执行最多 256、总 `max_items` 不超过 100,000。每个 foreach 默认最多 32、硬
上限 64，不支持嵌套或笛卡尔积。独立失败不取消 sibling，依赖失败的下游标记
`skipped/DEPENDENCY_FAILED`。结果按 Plan 声明顺序、foreach 源数组顺序返回；失败项
`result=null`，且不会回显 request、SQL、绑定值或原始异常。

## Metadata

```powershell
gravity metadata sync --all-apps [--database <path>] [--concurrency 1..24]
gravity metadata search [query] [--app-id <id>] [--database <path>]
gravity metadata events [query] [--app-id <id>] [--database <path>]
gravity metadata properties [query] [--app-id <id>] [--database <path>]
gravity metadata vocabulary [query] [--kind vocabulary|metric|custom_metric|metric_tag|metric_tag_category|media_enum|template]
gravity metadata tables [query] [--database <path>]
gravity find <query> [--backend operations] [--backend metadata]
```

默认位置是用户私有缓存下的 `GravityInsight/metadata/catalog.sqlite3`。同步采用临时库构建和原子替换；除 App 目录外，固定读取 9 个 workspace Analysis 词汇来源各一次，请求数不随 App 增长。部分失败保留成功数据和失败来源；`status=partial` 不代表完整目录。
查询命令以 SQLite 只读模式运行，不创建客户端、不读取凭据、不访问网络。
`find` 对三个目录做稳定相关性排序；backend 是显式注册表。

冷目录的两调用 Agent 路径使用
`gravity agent <query> --resolve-inputs '{"catalog_policy":"refresh"}' --output catalog.json`。与普通
`metadata sync` 可保留 partial 快照不同，这个集成 refresh 只有全部成功才发布；失败时旧 catalog
原样保留且解析命令失败。第二调用执行 metadata/table Plan 节点，结果继续携带同步时刻和 observed
语义。此模式合并顶层命令，不减少 sync 内部请求数。

`vocabulary` 搜索物理/自定义指标、指标标签与分类、媒体枚举和 mine/shared/preset 模板。它们都是 workspace scope，不接受 `--app-id`。`gravity agent <query>` 对强匹配返回同 kind 的 `metadata_search` Plan node；指标卡的 `request_fragment` 可复制进显式 Analysis spec，但不会自动执行。模板只提供安全目录身份，标记 `catalog_only`，不包含配置且不可回放。

`find` 当前注册 `operations`、`recipes`、`metadata` 三个 backend。`recipe validate` 只验证 workspace 声明；`recipe check` 还检查 operation 存在性/废弃状态、输入和输出字段及合同指纹，仍不访问网络。

Resolver 常用形式：

```powershell
gravity run @retention-weekly --start 2026-08-01 --end 2026-08-07
gravity run <operation-id> --app <alias-or-id> --input <json> --set page_size=100
```

recipe 参数用 `--param name=value`，`start/end` 有同名快捷参数。`--app` 先查 workspace alias，未命中时只接受正整数 App id。Resolver 失败输出按输入合同、父资源、空结果和本地事件相似候选排序；相似候选只是字符串距离，不建立业务绑定。

workspace 的发现顺序、最小配置和 recipe 字段见 [Workspace 参考](workspace.md)。

`operations`、`validate`、`find`、`recipe validate/check`、`metadata search/events/properties/vocabulary/tables` 等 parser 标记为不需要网络客户端，因此不会触发首次凭据向导。新增离线命令必须在自己的 parser 上声明相同属性。

## SQL

| 命令 | 用途 |
| --- | --- |
| `gravity sql --dry-run` | 离线校验 SQL 产品合同 |
| `gravity sql products` | 一次描述全部可调用产品与 query 输入合同，不返回原始 SQL |
| `gravity sql status [--json]` | 查看最近 Evidence 与可查询状态 |
| `gravity sql evidence-preflight` | Evidence 刷新前离线检查 |
| `gravity sql verify [--date ...] [--publish]` | 验证最近安全自然日；显式发布才更新 Evidence |
| `gravity sql query <product> ...` | 执行一个或批量已登记聚合产品 |

SQL CLI 不是任意查询入口。它只实现 `custom-sql` 这一种受治理的聚合产品机制；具体产品名称、SQL、App、数据源、输出字段和禁止结论全部由调用项目的 `gravity.toml` 维护。产品层校验固定占位符、聚合隐私、输出投影和行数上限；可选 `output_semantics` 把字段口径带入目录、dry-run 与查询摘要，但不内置业务事件、属性、动态 warning 或指标好坏判断。

未知产品时先运行一次 `gravity sql products`；已知产品直接 `gravity sql query`。query 支持
单个参数、`--input` 对象、数组或 `requests` wrapper，并以 `--concurrency 1..2` 保序并发。
可加 `--output <path>` 原子写入完整 JSON envelope；stdout 只返回与 Insight 产品一致的
`written` 收据。SQL 公开结果还包含状态、错误、Evidence 与查询收据，即使内部 `rows` 是二维，
也不提供会丢失这些合同信息的 CSV/表格输出。
Evidence 可用时附 reference；缺失或过期时附 warning，不阻断已登记产品查询。`status`、
`evidence-preflight` 和 `verify` 是诊断/授权维护命令，不是每次查询前要串行执行的门禁。
Python 的底层 `GravityClient.execute_sql()` 只固定路由并限制并发，不执行 workspace/Evidence
产品治理；Agent 不应使用它绕过 CLI 产品。详见 [SDK 参考](sdk.md)。

SQL 进程级并发上限为 2。机制合同位于 `src/gravity_sdk/contracts/sql-products/catalog.json`；调用结果中的 `warnings` 和 `forbidden_claims` 必须保留。

## Census

| 命令 | 用途 |
| --- | --- |
| `fetch` | 下载公开前端 bundle |
| `parse` | 从 bundle 解析候选路由 |
| `params` | 提取请求参数候选 |
| `responses` / `apply-responses` | 提取并应用响应字段消费者 |
| `coverage` | 路由与 SDK manifest 对账 |
| `diff` / `impact` | 分析上游变化和 operation 影响 |
| `check-upstream` | 只读取 HTML 并比较入口 hash |

生产使用见 [路由盘点](../maintainers/census.md)。

## 认证配置

调用者只维护：

```dotenv
GRAVITY_USERNAME=...
GRAVITY_PASSWORD=...
```

token 由 SDK 私有缓存维护。不要把 token、Cookie 或密码作为命令行参数，也不要把本地凭据文件提交到 Git。

Resolver Receipt 写在 workspace 对应的私有缓存 `state_root/receipts/`。`input_shape_fingerprint` 只哈希字段、容器结构和标量类型；相同结构换筛选值仍得到同一指纹。每个真实 HTTP response 另在 `state_root/receipts/http/` 同步写入 `gravity.http-receipt.v1`；它只记录 method、合同 path、operation、status、完成时刻、页码、attempt/retry 和请求 shape fingerprint，不记录请求值、响应体或凭据。该逐请求账本先于本地投影、分页聚合与 composite/Plan envelope 组装完成。

## 输出与退出码

CLI 尽量输出带 `schema_version`、`status`、计数和结构化错误的 JSON envelope。业务数据是否为空与请求是否成功是两个维度。支持的 Windows shell 中，stdout/stderr 的文本 JSON 确定性地使用 UTF-8，不继承系统 ANSI code page；本地控制台或文件 I/O 失败属于 local/4。

| 退出码 | 类别 |
| --- | --- |
| `0` | 成功，包括合同允许的 empty |
| `2` | 输入、认证缺失等调用方问题 |
| `3` | 上游、权限或限流问题 |
| `4` | 本地合同、隐私或策略问题 |
