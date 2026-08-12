# CLI 参考

本页只提供命令地图。参数细节以相应 `--help` 输出为准，输入 schema 以 `describe` 为准。

## 顶层命名空间

```text
gravity insight <command>     结构化读取和导出
gravity agent [query]         单问题发现；--input 批量发现并返回 Plan 节点
gravity plan schema|run       预检或执行受控跨能力 DAG
gravity metadata <command>    本地物理元数据目录
gravity find <query>          跨 operation、recipe 与 metadata 检索
gravity recipe <command>      离线校验 workspace recipe
gravity run <selector>        单进程解析并执行 recipe 或 operation
gravity sql <command>         受控 SQL 产品
gravity census <command>      前端路由盘点
gravity analysis context      并发读取一个 App 的分析上下文
gravity analysis saved ...    列出、读取、准备或严格重放保存分析
gravity apps snapshot         并发读取一个 App 的治理快照
gravity attribution snapshot  并发读取一个 App 的归因配置快照
gravity reports pulse         并发读取 App 经营概览与趋势
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
```

无 query 时返回两步协议；有 query 时优先返回匹配的 workspace recipe，再用 stable operation
补足 capability cards；可由 Plan 执行的卡含必填输入、下一条 `argv` 和 `plan_node`，默认 3 个、
最多 5 个，不访问网络。`--input` 接受最多 32 个唯一 ID 问题的 `{"questions":[...]}`，为
多个问题复用一次离线目录快照并按输入顺序返回；不能与 positional query、continuation、
domain 或 platform 组合。需要完整 catalog 或 blocked 覆盖信息时再进入
`operations search/describe`。

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
| `export ...` | 创建、等待、下载或取消治理导出 |
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

Insight 普通批量读取默认并发为 6，显式上限为 24；Metadata 同步允许 `1..24`。单次分页
读取在首页有明确总页数时按小窗口并发并保持页序，未知总页数时串行；batch 内的分页读取
强制单分页 worker，防止嵌套放大。这些是 worker 上限，实际请求仍受每 host 限流、重试和
共享冷却约束。

多维查询需要同时得到明细和合计时，使用一次组合调用；默认不加该参数时仍返回原有查询
envelope：

```powershell
gravity insight multidim query --input <query.json> --include-total `
  --all-pages --max-pages 20 --max-items 5000 --concurrency 6
```

组合调用先用在线指标元数据校验维度约束，再读取明细并把安全投影后的行交给 calc-total；分页
边界和 worker 上限与普通 `--all-pages` 完全一致。

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
gravity apps snapshot --app main --concurrency 6
gravity attribution snapshot --app main --concurrency 6
```

`--app` 接受 workspace alias 或正整数；归因命令继续接受 `--app-id` 兼容别名。Analysis
context 固定 13 个词汇/模板来源，App snapshot 固定 6 个治理来源；Attribution snapshot 固定
覆盖当前 8 个 stable attribution operation，其中两个 postback map 自动读取全部页。三者均
默认并发 6、上限 24，按固定来源顺序返回并隔离局部失败。Attribution snapshot 不包含仍为
draft 的聚合归因和用户/设备级明细查询。

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

需要把多个 Analysis 查询放入一个并发 DAG 时，继续使用现有 `gravity plan run`，不增加新的
CLI 子命令。Plan composite request 是 `name="analysis_query"` 加
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

### Saved Analysis v1

保存分析入口把稳定的保存目录、详情读取和现有 Analysis Spec 编译器连成一条受控路径。已知
引用时不要手工执行 `operations search/describe`，直接运行：

```powershell
# 浏览目录；list 不需要 --ref
gravity analysis saved list --app main

# 按稳定 ID 或精确名称查看受控定义摘要
gravity analysis saved get --app main --ref <id-or-exact-name>

# 读取定义并编译，但不执行最终分析查询
gravity analysis saved prepare --app main --ref <id-or-exact-name>

# 本地 definition 直接严格编译，零网络且不需要 Gravity 凭据
gravity analysis saved prepare --app main --definition <json-object-or-file>

# 一次解析、严格编译并执行
gravity analysis saved run --app main --ref <id-or-exact-name>
```

`--app` 接受 workspace alias 或正整数。`--ref` 只接受稳定 ID 或精确名称；精确名称命中
多个项目会以 caller/2 失败，要求改用稳定 ID，不会静默选择第一项。分析 kind 由保存定义
中已登记的 subject 决定，调用方不能覆盖。

Strict Replay 不是通用 Web 配置翻译器。只有定义中的紧凑 spec 能被当前 Analysis Spec
编译器原样验证时，`prepare/run` 才继续；未知字段、无法证明的 opaque config 或不支持的
分析 kind 均结构化失败，不降级为裸请求。`prepare --ref` 为解析引用会读取在线目录以及必要
详情，所以它不是离线 dry-run；它与 `run` 的区别是不会发送最终分析查询。`list/get` 也会
访问已登记的 stable 只读 operation。

Agent 查询 `saved report templates`、`保存分析`，包括 `--domain report`，唯一强候选是
`composite:saved_analysis`。卡片必填 `app/ref`，可选 `mode`，并提供可复制的 Plan
节点；发现本身完全离线，也不会基于自然语言自动执行。

### Business pulse

一个命令并发读取 App 概览和经营趋势；`--app` 可重复或用逗号分隔，支持 workspace alias 或
正整数。平台默认包含 `bytedance/tencent/kuaishou`，可重复指定 `--platform`：

```powershell
gravity reports pulse --app main --start 2026-08-01 --end 2026-08-07 `
  --platform bytedance --include-hourly
```

基础结果按 `overview`、`business` 顺序；`--include-hourly` 才追加
`hourly_comparison`。前两项是 `scope=app`，小时对比受上游合同限制并明确标记
`scope=workspace`，不能解释为单个 App 的小时结果。组合复用现有 stable operation、批量并发、
分页和局部失败合同；不推导业务结论或指标别名。

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
| `composite` | `name`、组合所需 App/查询输入 | 仅登记的 analysis query/context、App/attribution snapshot、business pulse、multidim |

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
管理并发。

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

SQL CLI 不是任意查询入口。它只实现 `custom-sql` 这一种受治理的聚合产品机制；具体产品名称、SQL、App、数据源、输出字段和禁止结论全部由调用项目的 `gravity.toml` 维护。产品层校验固定占位符、聚合隐私、输出投影和行数上限，但不内置任何业务事件、属性或口径。

未知产品时先运行一次 `gravity sql products`；已知产品直接 `gravity sql query`。query 支持
单个参数、`--input` 对象、数组或 `requests` wrapper，并以 `--concurrency 1..2` 保序并发。
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

Resolver Receipt 写在 workspace 对应的私有缓存 `state_root/receipts/`。`input_shape_fingerprint` 只哈希字段、容器结构和标量类型；相同结构换筛选值仍得到同一指纹。

## 输出与退出码

CLI 尽量输出带 `schema_version`、`status`、计数和结构化错误的 JSON envelope。业务数据是否为空与请求是否成功是两个维度。

| 退出码 | 类别 |
| --- | --- |
| `0` | 成功，包括合同允许的 empty |
| `2` | 输入、认证缺失等调用方问题 |
| `3` | 上游、权限或限流问题 |
| `4` | 本地合同、隐私或策略问题 |
