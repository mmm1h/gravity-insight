# Agent 工作流

本页是 Agent 的最短执行协议。目标不是把所有命令跑一遍，而是用最少调用得到一个可复核的结果或明确能力缺口。

## 0. 先选最短入口

| 已知信息 | 直接执行 | 正常命令数 |
| --- | --- | --- |
| 已知 workspace recipe | `gravity run @<recipe> ...` | 1 |
| 已知 operation 和输入 schema | `gravity run <operation-id> ...` | 1 |
| 已知 Analysis kind 和物理字段 | 单个 `analysis query`；多个用一个 `analysis_query` Plan | 1 |
| 已知 Analysis kind，指标未知 | `metadata vocabulary` → `analysis query --spec` | 2 |
| 已知保存分析引用 | `gravity analysis saved run --app ... --ref ...` | 1 |
| 不知道保存分析引用 | `gravity agent "saved report templates"` → 执行返回的 Plan 节点 | 2 |
| 已知 App 与经营时间窗 | `gravity reports pulse --app ... --start ... --end ...` | 1 |
| 已知多个 selector 或已有 Plan | `gravity plan run --input <plan.json>` | 1 |
| 已同步数据表沿革，目标未知 | `gravity agent "data table lineage"` → `plan run` | 2 |
| 已知 operation，不确定输入 | `gravity agent <operation-id>` → `run` | 2 |
| 只知道分析目标 | `gravity agent "<query>"` → 返回 argv | 2 |
| 多个未知分析问题 | `gravity agent --input <questions.json>` → `plan run` | 2 |
| 同时找 operation、recipe、metadata | `gravity find "<query>"` | 1 次发现 |
| 多个独立 operation | `gravity insight batch read ...` | 1 次批量执行 |

`run` 已经完成 bind、validate、parents、exec 和 diagnose。不要在每次调用前机械执行 `recipe check`、`validate`、`parents resolve` 和 `doctor`；只有 `run` 的 diagnostics 要求时再执行对应命令。

五种 Analysis kind（`event/funnel/retention/property/scatter`）使用 `gravity analysis query --kind <kind> --spec <json|file|->`，完整示例见 [CLI 参考](reference/cli.md#analysis-query-spec-v1)。事件/属性用 `metadata search`，指标/标签/媒体枚举/模板用 `metadata vocabulary`；确认后一次执行 spec。`--dry-run` 返回零网络的安全编译预览。Spec 不接受自然语言自动执行。

经营概览和趋势直接一次调用 `gravity reports pulse --app main --start 2026-08-01 --end 2026-08-07 --include-hourly`；只有需要小时对比时加 `--include-hourly`，其结果是 `scope=workspace`。交叉 Plan 使用 composite `name=business_pulse` 和 `apps/start/end`，不要手工串行读取 overview/business。

保存分析已知稳定 ID/精确名称时直接 `gravity analysis saved run --app ... --ref ...`，不要先串行
list/get/prepare。Strict Replay 不猜 Web 配置；`prepare --ref` 会联网解析引用但不执行最终查询，
显式 `--definition` 才是零网络编译。自然语言发现只返回 `composite:saved_analysis` 和缺失的
`app/ref`，不会自动选择或执行。

## 1. 业务语义先在调用项目解析

如果用户说“幸运礼包”之类业务名称，先从业务知识库确定模块、活动 ID、SKU、时间窗和已审核埋点绑定。SDK 能验证某 App 有哪些物理事件/属性并执行受控分析，但不能从相似名称建立业务归属。

无法解析业务口径时先向用户报告缺失信息，不要用事件中文名或字段名猜测。

## 2. 未知能力：总共两次调用

```powershell
gravity agent "<英文或技术关键词>"
# 从 capability card 选择候选、填写 required_inputs，并执行 next.argv
gravity run <operation-id> --input <json-or-file>
```

`gravity agent` 完全离线，一次完成 bounded search + describe，优先返回匹配的 workspace recipe，再用 stable operation 补足默认 3 个、最多 5 个 capability cards。Recipe 卡片包含 `required_parameters`；operation 卡片包含压缩 input schema、`required_inputs`、父 operation、分页合同；两类都提供可直接调用的 `next.argv`。无 query 时运行 `gravity agent` 可取得 `gravity.agent.v1` 机器协议。

多个问题不要逐个执行 `gravity agent`。一次提交带稳定 ID 的问题数组：

```json
{
  "questions": [
    {"id": "apps", "query": "list apps", "domain": "app"},
    {"id": "events", "query": "event metadata", "domain": "analysis"},
    {"id": "reports", "query": "saved report templates", "domain": "report"}
  ]
}
```

```powershell
gravity agent --input questions.json
```

这次调用只加载一次 Workspace、operation inventory、SQL product 和本地 metadata catalog，按问题输入顺序返回结果。Plan 可执行候选带可复制的 `plan_node`；Analysis Spec 编译器卡则内嵌完整 kind schema 和可直接执行的 `argv`。单项发现失败不影响其他问题。自然语言发现不会自动执行。调用方选择节点、补齐输入并组成一个 Plan 后，第二次调用 `gravity plan run`；Spec 卡可直接执行其 compact spec。因此未知问题仍是“批量发现一次 + 执行一次”。

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

Analysis 查询复用 composite `name=analysis_query`，支持 `event/funnel/retention/property/scatter`。已知 kind/App/literal spec 时直接一次 `plan run`；未知时一次 `gravity agent` 发现、调用方确认补齐 spec、一次 Plan 执行，自然语言不自动执行。同层查询由全局 pool 并发、adapter worker 固定 1、保声明序并隔离失败；节点和总预算同时生效。binding 仅可写已有标量 `/app`，不支持 `/spec/...` 或 spec 内部引用；结果不回显 request/spec/binding 值并继续脱敏。完整事件、event+funnel 并发及其余 Plan 合同见 [Plan v1 参考](reference/plan.md#analysis-query-composite)。

## 4. 选择 Insight 还是 SQL

按以下顺序：

1. stable Insight operation；
2. 调用项目已经登记的 SQL 聚合产品；
3. 报告能力缺口。

即使 Insight 需要几项并发读取，只要能等价表达，也优先使用 Insight。只有跨表连接、窗口
函数、特殊计算或已审核 Evidence 口径无法由 Insight 表达时，才使用 SQL。

已知 SQL 产品时直接执行，不先跑维护命令链：

```powershell
gravity sql query <product> --start <inclusive-iso> --end <exclusive-iso>
```

`query` 自己校验 workspace product；Evidence 可用时附 reference，不可用或过期时附 warning，
不阻断产品查询。不要自动循环执行 `status`、`evidence-preflight`、`verify --publish`，也不要改用 Python
`GravityClient.execute_sql()` 绕过产品治理。Evidence 发布需要维护授权。

## 5. 独立任务一次并发

多个 App、日期段或 operation 彼此独立时，使用正式 batch，而不是逐条起 CLI 进程或临时
线程脚本。首次不确定 wrapper 时查看一次 schema：

```powershell
gravity insight batch schema
gravity insight batch read --input <batch.json> --concurrency 6
```

最小 `batch.json`：

```json
{
  "requests": [
    {
      "operation_id": "app.list",
      "request_id": "page-1",
      "input": {"page": 1, "page_size": 1}
    },
    {
      "operation_id": "app.list",
      "request_id": "page-2",
      "input": {"page": 2, "page_size": 1}
    }
  ]
}
```

batch 保持输入顺序、隔离单项失败并聚合退出码；默认并发 6、上限 24。单个 operation 的
`--all-pages` 会在首页返回明确 `total_page` 时按小窗口并发且保持页序；总页数未知时串行。
batch 内 `read_all` 固定单分页 worker，避免嵌套并发放大。不要在外层套线程池绕过
进程/host 限流。SQL query 也接受单个、数组或 requests wrapper，并发上限独立且为 2。

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

最短未知路径是 `sync` 一次，随后 `gravity agent "<指标或模板>"` 一次离线扫描并执行其 `metadata_search` Plan node；批量问题仍只加载 SQLite 一次。`events/properties` 是 App scope；`tables` 是 account scope，只陈述观察到的 ID/版本/动作/时间。所有本地词汇只提供物理候选，不自动执行或绑定业务查询。需要同时查 operation、recipe 和 metadata 时调用：

```powershell
gravity find "retention"
```

## 8. 只在诊断要求时分支

`stale` 才运行 `recipe check`；`PARENT_REQUIRED` 按 diagnostics 解析父资源；`INPUT_INVALID`
重新 describe。`empty` 先核对 App、时间、时区和父资源，不能解释成业务未发生。认证只刷新
一次，权限错误不循环；限流遵循 `retry_after_ms`；合同变化立即停止依赖新字段。任何分支都
只保留结构化摘要，不输出请求敏感信息。

只有在严格 HTTP 预算内寻找一个可用输入组合时使用 `discover-nonempty`。它不是空结果后的
默认重试器。

## 9. 导出

异步导出按 `list-capabilities → describe → start → wait/status → download`；创建任务会产生
服务端状态，下载会写本地文件。执行前阅读 [导出指南](guides/export.md)。

## 10. 交付
至少说明：业务口径、`operation_id` 或 SQL product、App、时间范围、选择 Insight/SQL 的
理由、成功/空/部分失败/能力缺口，以及不能支持的结论。不要把“没有查到”改写成“没有发生”。

CLI 退出码：`0` 成功（包括合同允许的 empty）、`2` 调用方错误、`3` 上游/权限错误、`4` 本地合同/隐私/策略错误。批量命令按最高严重级别聚合退出码，仍需读取每项结果。
