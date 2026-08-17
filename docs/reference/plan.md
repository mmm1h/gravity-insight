# Plan v1 参考

Plan v1 把 Insight operation/recipe、受治理 SQL product、本地 metadata 与登记 composite 放进
一次有界 DAG 执行。以下示例保存为 `plan.json`：

```json
{
  "schema_version": "gravity.plan.v1",
  "budget": {"max_workers": 6, "max_total_items": 10000},
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
    },
    {
      "id": "app_contexts",
      "kind": "composite",
      "request": {"name": "analysis_context", "app": "main"},
      "depends_on": ["apps"],
      "foreach": {
        "from": "apps",
        "source": "/result/data/list",
        "target": "/app",
        "max_items": 8
      },
      "limits": {"max_pages": 1, "max_items": 200}
    },
    {
      "id": "local_events",
      "kind": "metadata_search",
      "request": {"query": "purchase", "kind": "event", "limit": 20}
    }
  ]
}
```

```powershell
gravity plan schema
gravity plan run --input plan.json --dry-run
gravity plan run --input plan.json --concurrency 6
```

## 宿主生成 Plan 的效果边界

直接调用方提交的普通 `gravity.plan.v1` 仍走 `execute_plan`。把工具结果和宿主 LLM 放在同一上下文时，
必须改走 Python `execute_host_plan(sdk, host_plan, sources)`；`gravity plan schema` 的
`host_effect_boundary` 给出 `gravity.host-source.v1`、action 和 wrapper 合同。来源表由模型外宿主建立：
tool result 只能是 data，Plan 控制身份只能来自 SDK contract，对象 ID/目的地只能来自用户。mutation
preview 需要用户授权绑定规范化 Plan SHA-256；execute 另需用户确认绑定同一请求和 preview fingerprint。
模型不能创建或改写来源表，只能引用已有 source ID。

该入口不检测注入文本。它允许上游名称、备注和错误消息原样进入结果，但在 adapter 前拒绝由这些 data
来源派生的 tool/operation/path、对象、目的地、permission 或 confirmation。raw CLI、普通
`execute_plan` 和其他外部工具不在该宿主边界内；P0-1 的默认宿主接线不得绕过它。

## Effect 边界：Segment mutation 不进入 Plan v1

Plan v1 节点是可预检、可调度的无副作用数据节点。Segment create/update/refresh/delete 是不可安全
重放的 effect，还要求人工确认、执行时 preimage、写后 list/detail 读回和一次性授权，因此不接受
mutation operation ID，也没有 `segment_mutation` node kind。调用方使用
`gravity analysis segment ... --dry-run`，审查后再运行同一命令的 `--execute`；Agent 卡只交接这两步，
不返回 Plan node。该“设计不适用”窄例外已按三条件登记在[路线图](../roadmap.md#写操作范围裁决与-segment-crud2026-08-16)：缺 Plan 不减少可完成任务，且不能推广到其他未登记写。

## Workspace 参数化 Plan

调用项目可在 `gravity.toml` 的 `plan_recipes.<name>` 保存一份完整 literal Plan，并给会变化的
request 叶子声明 typed 参数。执行时不再重复提交完整 JSON：

```powershell
gravity plan run --recipe example --param date=2026-08-14 --param app=main --dry-run
gravity plan run --recipe example --param date=2026-08-14 --param app=main
```

参数合同为 `{type, format?, required, bindings[]}`；`bindings` 是一个或多个
`/nodes/<index>/request/...` RFC 6901 JSON Pointer。参数只替换已存在的非空 scalar 叶子，
不做字符串插值，也不能改变节点、依赖、foreach、budget 或 limits。完整 TOML 形状、类型与格式
见 [Workspace 参考](workspace.md#参数化-plan)。

展开严格发生在 Plan v1 之前：workspace 合同与绑定路径本地校验，调用参数完成类型/格式校验，
生成普通 `gravity.plan.v1` object，随后原样进入本页唯一的 `validate_plan`、adapter preflight 和
`execute_plan`。因此 DAG、并发预算、部分失败、envelope、上游请求集合与手写等价 Plan 完全相同。
`--dry-run` 也复用同一路径并保持零网络。

缺 required 参数、类型/格式错误或绑定路径不存在统一返回
`PLAN_RECIPE_INVALID` / `local` / exit `4`，不构造执行请求。Python 调用方可用
`sdk.expand_plan_recipe()` 查看普通 Plan，或用 `sdk.validate_plan_recipe()` /
`sdk.execute_plan_recipe()`；后两者分别委托现有 dry-run 与执行方法。

原入口 `gravity plan run --input <plan.json> [--set PATH=VALUE]` 未改变：仍解析同一 Plan JSON，
走同一校验、adapter 与结果 envelope；`--recipe` 只是互斥的 Plan 来源。workspace Plan recipe
实例不进入 Agent capability card：它是调用项目私有内容，而 Agent 卡发现的是仓库能力。

数据表沿革复用 `metadata_search`，不增加新的节点类型：

```json
{
  "id": "table_history",
  "kind": "metadata_search",
  "request": {"kind": "table_lineage", "query": "publish", "limit": 20},
  "limits": {"max_pages": 1, "max_items": 20}
}
```

这个节点只读本地 catalog；执行前需至少一次运行
`gravity metadata sync --all-apps --include-table-lineage`。`table_lineage` 是 account scope，
不接受用 `app_id` 推断归属。结果只包含同步时观察到的 `table_id`、版本 ID、动作类型及时间；
没有证据时不会补出表名、App 归属或“当前版本”。`limit` 受节点 `max_items` 和 Plan 总预算
共同约束，`offset` 仅用于本地有界分页。

同一 `metadata_search` 节点也执行离线 Analysis 词汇搜索，不增加新节点类型：

```json
{"id":"metric","kind":"metadata_search","request":{"kind":"metric","query":"revenue","limit":20}}
```

词汇 kind 为 `metric/custom_metric/metric_tag/metric_tag_category/media_enum/template/vocabulary`，都是 workspace scope 且禁止 `app_id`。一次同步固定请求 9 个来源各一次；partial 结果保留成功行与失败来源。节点只返回安全投影；Agent 指标卡可附显式查询请求片段，模板仍是 `catalog_only`，不会从目录配置伪造回放或自动执行 Analysis 查询。

metadata status 复用同一个离线 `metadata_search` kind：

```json
{
  "id": "metadata_status",
  "kind": "metadata_search",
  "request": {"kind": "status", "app_id": "1001", "max_age_hours": 24},
  "limits": {"max_pages": 1, "max_items": 20}
}
```

它不构造生产 client；结果报告 catalog 存在/兼容、App 同步时间、对象/失败数和 freshness。单 App
有界同步复用已登记 `composite` kind：

```json
{
  "id": "sync_metadata",
  "kind": "composite",
  "request": {"name": "metadata_sync", "app": "main"},
  "limits": {"max_pages": 2, "max_items": 100000}
}
```

`request.app` 接受 workspace alias 或 App ID；只有 `/app` 可作标量 binding。`limits.max_pages` 只能为
1..8，并直接形成 `3 * max_pages + 1` 的逻辑请求上限；adapter 从 Plan 全局 worker pool 借用最多 4 个
worker，不叠加独立池。执行结果报告实际页/对象/请求与 partial；Plan dry-run 只做合同和最坏预算预检，
不会执行同步。

## Derived Metrics composite

本地派生复用现有 `composite` kind，并经 Analysis family router 执行；不增加 Plan node kind，也不调用
网络。request 固定为 `name/source/spec`，不接受 binding 或 output_fields。Plan v1 只绑定 JSON scalar，
因此 source envelope 必须由调用方显式放入 request；本产品没有把对象/数组 binding 扩进通用 Plan。

```json
{
  "id": "orion_derive",
  "kind": "composite",
  "request": {
    "name": "derived_metrics",
    "source": {
      "schema_version": "fictional.result.v1",
      "status": "success",
      "ok": true,
      "data": {"list": [{"orion_a": 1, "orion_b": 8}]}
    },
    "spec": {
      "schema_version": "gravity.derived-metrics-spec.v1",
      "rows_path": "/data/list",
      "decimal_places": 3,
      "calculations": [{
        "operator": "ratio",
        "result_name": "orion_ratio",
        "numerator": "orion_a",
        "denominator": "orion_b"
      }]
    }
  }
}
```

Plan node 的 `result_source` 为 caller_defined。若 source 顶层已经是 partial，既有 Plan partial 保留规则
继续生效；成功 source 中只有个别派生单元不可算时，节点 result 内的 derived sub-contract 明确为
partial，但原 source 顶层字段仍按纯加法合同不变。

## Analysis Query composite

五种稳定 Analysis 查询都可直接放进现有 `composite` 节点：`event`、`funnel`、
`retention`、`property`、`scatter`。request 合同固定为
`name/kind/app/spec`，可选 `start/end`；`start/end` 必须成对出现并覆盖 spec 日期。
`output_fields` 仍是 Plan 节点字段，不属于 composite request；它按所选底层 Analysis
operation 的 data-relative FieldPolicy 校验。

下面是一个完整、可直接保存为 `event-plan.json` 的事件查询。`spec` 是 literal JSON 对象，
不会从自然语言推断事件、指标或聚合：

```json
{
  "schema_version": "gravity.plan.v1",
  "budget": {"max_workers": 6, "max_total_items": 200},
  "nodes": [
    {
      "id": "daily_app_opens",
      "kind": "composite",
      "request": {
        "name": "analysis_query",
        "kind": "event",
        "app": "main",
        "start": "2026-08-01",
        "end": "2026-08-07",
        "spec": {
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
        }
      },
      "limits": {"max_pages": 1, "max_items": 200},
      "output_fields": ["list", "target_list", "date_list"]
    }
  ]
}
```

如果 event 与 funnel 互不依赖，把它们声明为同层 sibling；不要在外部串行启动两次 CLI：

```json
{
  "schema_version": "gravity.plan.v1",
  "budget": {"max_workers": 6, "max_total_items": 400},
  "nodes": [
    {
      "id": "opens",
      "kind": "composite",
      "request": {
        "name": "analysis_query",
        "kind": "event",
        "app": "main",
        "spec": {
          "start": "2026-08-01",
          "end": "2026-08-07",
          "time_grain": "day",
          "steps": [{"event": "app_open", "metric": {"field": "PresetAllCount", "aggregation": "PresetAllCount"}}]
        }
      },
      "limits": {"max_pages": 1, "max_items": 200}
    },
    {
      "id": "open_to_purchase",
      "kind": "composite",
      "request": {
        "name": "analysis_query",
        "kind": "funnel",
        "app": "main",
        "spec": {
          "start": "2026-08-01",
          "end": "2026-08-07",
          "steps": [
            {"event": "app_open", "metric": {"field": "PresetAllCount", "aggregation": "PresetAllCount"}},
            {"event": "purchase", "metric": {"field": "PresetAllCount", "aggregation": "PresetAllCount"}}
          ],
          "window": {"unit": "day", "value": 1}
        }
      },
      "limits": {"max_pages": 1, "max_items": 200}
    }
  ]
}
```

已知 kind、App 和 literal spec 时，直接一次 `gravity plan run --input event-plan.json`。
未知物理字段时，先用 `gravity agent "<analysis question>"` 得到候选并由调用方补齐/确认 spec，
再执行返回的 Plan 节点，总共两次调用。自然语言发现永远不自动执行查询。

Plan binding 只作用于 request 边界：`/app` 可从上游复制一个标量，并且 `from` 必须列入
`depends_on`；v1 不支持写入 `/spec/...`，也不解释 spec 内部引用或表达式。需要变化的事件、
指标、过滤条件必须在提交 Plan 前生成完整 literal spec。

多个无依赖 literal spec 可以直接包装成 `gravity.analysis-query-batch.v1` 并运行
`gravity analysis query batch --input queries.json`；它机械生成同层 `analysis_query` 节点，
仍由本页的 Plan 引擎调度。需要依赖、跨引擎节点或 foreach 时才手写完整 Plan。

事件、漏斗、留存、属性的“同一 spec 跑多个 App”使用
`gravity.analysis-query-batch.v2`：每项把 `app` 改为显式 `apps` 数组。batch 在 Plan 预检前按
数组顺序生成同层 scalar-`app` 节点；Plan composite request 本身没有新增数组字段。展开总上限
32，不接受 `"*"` 或解析后重复 App。结果仍是一 App 一组件，只额外标注 `query_id/app`，不做
跨 App reduce/join/sort。adapter 内 worker 仍为 1，同层节点共享 Plan 的
`PlanConcurrencyBudget`；因此 N 个 App 的上游请求集合与 N 次单独执行相同，只有峰值在途数可从
1 增至全局预算允许值。scatter 及其他 composite 继续使用显式同层节点。

## Business Pulse composite

经营概览与趋势使用登记的 `business_pulse` composite。调用方必须显式给出 App 数组和日期窗；
平台数组与 hourly 开关有中性默认值：

```json
{
  "id": "pulse",
  "kind": "composite",
  "request": {
    "name": "business_pulse",
    "apps": ["main"],
    "start": "2026-08-01",
    "end": "2026-08-07",
    "platforms": ["bytedance", "tencent", "kuaishou"],
    "include_hourly": false
  },
  "limits": {"max_pages": 5, "max_items": 200}
}
```

基础节点一次 batch 读取 `overview/business`；显式启用 hourly 时仍是一次 batch，并追加
`scope=workspace` 的 `hourly_comparison`。直接 CLI/SDK 默认 6 workers、上限 24；Plan adapter
固定为 1，独立节点由全局 pool 并发。binding 只允许 `/start`、`/end`、`/include_hourly`，
`apps/platforms` 必须是提交前确定的 literal 数组。

`gravity agent "business pulse"` 返回同形状的五字段占位节点，调用方替换后执行，共两次调用；
Agent 不填写任何业务值，也不自动执行。泛 `business analysis/经营分析` 不选择本 composite，
多维、看板、保存分析、归因、模板、权限与导出意图同样被严格排除。

公司资源用量使用同一 Report family router，request 只有固定名称：

```json
{
  "id": "company_usage",
  "kind": "composite",
  "request": {"name": "company_usage"},
  "limits": {"max_pages": 1000, "max_items": 100000}
}
```

该节点没有 binding target，也不接受 App、日期或筛选；一次完整分页读取返回
`gravity-insight.company-usage.v1`。Agent 卡通过 `gravity.agent-call-bound.v1` 声明已知输入 1 次、
未知能力 2 次，Plan adapter 固定使用一个上游 worker。

自定义人群节点同样没有 binding target，也不接受 App、日期或筛选：

```json
{
  "id": "custom_audiences",
  "kind": "composite",
  "request": {"name": "custom_audience"},
  "limits": {"max_pages": 1000, "max_items": 100000}
}
```

该节点一次完整分页返回 `gravity-insight.custom-audience.v1`，adapter 内固定一个上游 worker；
空、分页截断、能力缺口和合同漂移保持不同结构化状态。

## Dashboard Snapshot composite

看板控制面使用登记的 `dashboard_snapshot` composite。调用方必须给出 Workspace App 和看板
稳定 ID 或精确名称；Plan 不从自然语言、相似名称或 Web URL 猜测引用：

```json
{
  "id": "dashboard_control_plane",
  "kind": "composite",
  "request": {
    "name": "dashboard_snapshot",
    "app": "main",
    "ref": "Growth Overview"
  },
  "limits": {"max_pages": 5, "max_items": 200},
  "output_fields": ["dashboard", "results", "scopes"]
}
```

节点先在受治理目录中精确解析 `ref`，再固定读取 detail、dashboard members、space members、
condition favourites 与当前账号的 default favourite。目录节点和五源结果共同受
`limits.max_items` 约束；收藏分页受 `limits.max_pages` 约束。五源保持声明顺序并隔离局部失败，
breaking contract drift 仍是 upstream failure，不会伪装成空结果。

`/app` 与 `/ref` 都可接受一个显式标量 binding，且来源节点必须列入 `depends_on`；不允许把
binding 写入 opaque dashboard config。`output_fields` 只允许 `app_id/dashboard/results/scopes/`
`source_count`，结构与错误字段始终保留。adapter 内 worker 固定为 1，跨节点并发继续由 Plan
全局 pool 控制。

本 composite 只返回裁剪后的控制面摘要。它不返回或解释 `ui_config`、report/favourite config、
condition、成员 uid/name，也不运行、重放或渲染看板图表。已知 App/ref 时直接一次 `plan run`；
未知时 `gravity agent "inspect dashboard members and saved filters"` 返回带 `app/ref` 占位符的
非自动执行节点，调用方补齐后再运行，总共两次调用。

## Dashboard Analysis composite

看板图表编译/重放使用独立的 `dashboard_analysis` composite，不会改变控制面 snapshot：

```json
{
  "id": "dashboard_charts",
  "kind": "composite",
  "request": {
    "name": "dashboard_analysis",
    "app": "main",
    "ref": "Growth Overview",
    "mode": "run",
    "start": "2026-08-01",
    "end": "2026-08-08"
  },
  "limits": {"max_pages": 1, "max_items": 200},
  "output_fields": ["dashboard", "date_range", "charts"]
}
```

`mode` 为 `prepare|run`，默认 run。只有 `/app` 可接受动态 binding；`ref/start/end/mode` 必须是
literal；start/end 是首尾均包含的 ISO 日期，最长 90 天。因而名称、日期顺序、字段和最坏静态
预算在任何网络请求前完成预检。节点至少预留 3 个
item（目录根、看板和一个 chart）；实际目录或结果超出 `max_items` 时运行时 fail closed。Plan
最多准备 `min(32, max_items-2)` 个 chart，adapter 内部 worker 固定 1，由全局 pool 管理跨节点并发。

结果只允许投影 `app_id/dashboard/mode/date_range/charts/chart_count/supported_count/`
`unsupported_count/success_count/failure_count`。chart 保留身份、kind、operation、状态、安全
ErrorDetail 和原生受治理 result，不返回 config、compiled request、binding 值或原始异常。

该 adapter 调用静态 Web artifact 编译器，只覆盖已证明的 event/funnel/retention/property/scatter
构造；不模拟 layout、favourite 或页面 global filter。无法证明的 chart 按声明顺序标记
unsupported，其他 sibling 继续。已知 selector 是一次 `plan run`；未知时
`gravity agent "run dashboard charts"` 返回缺失 `app/ref/start/end` 的占位节点，补齐并执行共两次，
自然语言永远不自动执行。

## User Journey composite

单用户 profile、event timeline 与 postback 使用一个登记节点，不需要调用方手工拼三条 run：

```json
{
  "id": "user_journey",
  "kind": "composite",
  "request": {
    "name": "user_journey",
    "app": "main",
    "client_id": "<explicit-sensitive-id>",
    "start": "2026-08-01",
    "end": "2026-08-07",
    "page": 1,
    "page_size": 20
  },
  "limits": {"max_pages": 1, "max_items": 200}
}
```

`/app` 与 `/client_id` 是仅有的动态 target；Plan 不从自然语言产生用户标识。三路结果固定顺序、
局部失败隔离，输出不含 client ID/request。user-event 没有已证明的 page-info，因此节点不自动
翻页；`continuation` 只告诉调用方下一显式 page。adapter 内 worker 固定 1，外层并发仍由 Plan
的单一 worker pool 控制。

## Order Directory composite

单日普通订单目录使用登记的 `order_directory` 节点。Agent 只返回完整、value-free 的节点，调用方
必须在执行前替换两个占位值：

```json
{
  "id": "order_directory",
  "kind": "composite",
  "request": {
    "name": "order_directory",
    "app": "<workspace-app-alias-or-positive-id>",
    "date": "<date:YYYY-MM-DD>"
  },
  "limits": {"max_pages": 1000, "max_items": 100000}
}
```

`/app` 与 `/date` 是仅有的动态 target，只接受有限 JSON scalar；每次 binding 后重新校验 App 和
严格单日。本节点不接受 fields/conditions/order、跨日窗口或状态筛选。Agent 不从自然语言填值，
不解释退款、净收入或订单成功，也不自动执行。

adapter 内分页 worker 固定 1；有效网络调用严格为 `P` 个 `analysis.order_detail.list` 分页，
0 metadata、0 child。专用 projector 重新核对 operation identity、App/日期、limits、完整页/行收据
和终止状态；成功行只允许 `Amount/BackAmount/Status/CreateTime`。额外字段或标识、continuation、
截断、预算漂移及 raw exception 都 fail closed，结果与错误不含订单/用户/拆单/归因标识、request
或 binding 值。多个独立 App/日期使用同层节点，由 Plan 全局 pool 并发。

## Order Split Trace composite

按 TraceID 读取单日拆单明细使用登记的 `order_split_trace` 节点。Agent 返回的节点完整但不含
任何业务值，调用方必须在执行前替换三个占位值：

```json
{
  "id": "order_split_trace",
  "kind": "composite",
  "request": {
    "name": "order_split_trace",
    "app": "<workspace-app-alias-or-positive-id>",
    "date": "<date:YYYY-MM-DD>",
    "trace_id": "<explicit-sensitive-trace-id>"
  },
  "limits": {"max_pages": 1000, "max_items": 100000}
}
```

`/app`、`/date`、`/trace_id` 是仅有的动态 target，且只接受有限 JSON scalar；每次 binding 后都
重新校验正整数/alias、严格日期和长度 1..256 的非空敏感 TraceID。本节点不接受父行敏感数组
binding，也不扩展通用 Plan DSL。Agent 不从自然语言抽取、显示或执行 TraceID。

adapter 内父分页 worker 固定 1；它必须先完整读取受 `max_pages` 约束的单日父目录并在本地精确
匹配唯一父行，之后才允许一次 child，网络调用数为 `P + 1`。`max_items` 是父扫描行与 child 行
共享的总预算，child 前先保留最坏空间。专用 sanitizer/projector 重新核对阶段状态、页/行收据和
预算，成功明细只允许 `Amount/BackAmount/Status/CreateTime`；结果与错误不得包含 TraceID、
ClientID、拆单 ID、PayEventTime、request、binding 值或原始异常。

多个独立 TraceID 使用同层节点，由 Plan 全局 pool 并发；不使用 `foreach` 生成敏感数组、不新增
batch wrapper，也不形成节点并发与父分页的乘法放大。精确 raw
`analysis.order_split_detail.list` 仍可作为专家 operation selector，但不是该产品的 Agent 回退。

## Segment Rule composite

人群规则人数/占比评估复用 `composite` 节点，request 固定为 `name="segment_evaluate"`、
`app` 和完整 literal `spec`：

```json
{
  "schema_version": "gravity.plan.v1",
  "budget": {"max_workers": 6, "max_total_items": 1},
  "nodes": [
    {
      "id": "eligible_audience",
      "kind": "composite",
      "request": {
        "name": "segment_evaluate",
        "app": 101,
        "spec": {
          "name": "CN users",
          "start": "2026-08-01",
          "property_rules": {
            "logic": "AND",
            "groups": [
              {
                "logic": "AND",
                "rules": [
                  {"field": "country", "source": "user", "operator": "EQUALS", "values": ["CN"]}
                ]
              }
            ]
          },
          "event_rules": {"logic": "AND", "groups": []}
        }
      },
      "limits": {"max_pages": 1, "max_items": 1},
      "output_fields": ["part", "percent", "total"]
    }
  ]
}
```

先用 metadata 确认示例中的物理字段，再提交规则。预检完整编译 spec 且零网络；真实事件、属性、
分群与版本仍在执行阶段由现有 FieldPolicy 元数据校验。binding/foreach 只能写 `/app`，禁止
`/spec/...`、名称或规则值；`output_fields` 是节点级、data-relative 字段，只允许
`part/percent/total`。结果与错误均不回显 request、spec、binding 值或原始异常。

已知 app/spec 时一次 `plan run`。未知合同则一次 `gravity agent "评估人群规则命中人数"`，
调用方按卡片 schema 填写 `app/spec`，再执行 Plan，总共两次；自然语言不会生成规则或自动执行。

## Multidim composite

Multidim 继续使用登记的 `name="multidim"`，不新增 composite 名或 Spec DSL：

```json
{
  "schema_version": "gravity.plan.v1",
  "budget": {"max_workers": 6, "max_total_items": 5000},
  "nodes": [
    {
      "id": "daily_cost",
      "kind": "composite",
      "request": {
        "name": "multidim",
        "input_schema_version": "gravity-insight.multidim-input.v1",
        "app": "main",
        "inputs": {
          "date_list": ["2026-08-01", "2026-08-07"],
          "time_dims": "day",
          "metrics_list": ["ap_cost"],
          "custom_metrics_list": [],
          "data_dims": ["day"],
          "relate_dims": [],
          "filters": []
        },
        "include_total": true,
        "read_all": true
      },
      "limits": {"max_pages": 20, "max_items": 5000}
    }
  ]
}
```

Multidim request 必须显式提供当前
`input_schema_version="gravity-insight.multidim-input.v1"`；缺失或未知版本会在 Plan 预检阶段零网络
fail closed，不再回退到 raw Plan 语义。`app/inputs` 必填，
`include_total/read_all` 为显式布尔且默认 false。动态 target 只接受 `/app`、两个布尔开关和
真正标量的输入字段 `/inputs/time_dims`。数组或对象不能接收 Plan 的标量 binding/foreach，预检会直接拒绝。Agent
不创建 binding，也不生成指标、
维度、日期或 filter 值。adapter 内部 worker 固定 1；多个独立查询作为同层节点交给 Plan 全局
pool，并保持声明顺序。一次执行的 HTTP
数为去重 metadata `M` + query 页数 `P` + 可选一次 total；total 依赖 query，不能并发提前执行。

Agent 对明确的中英文多维查询意图返回唯一 `composite:multidim` 卡，完整展开闭合 input schema
以及可机械填写的 `name/input_schema_version/app/inputs/include_total/read_all` request。已知完整输入一次执行；未知
入口是 Agent + Plan 两次。模板、layout、收藏、权限、经营 pulse 和五类 Analysis 查询均不由
本 composite 接管。

安全结果保留产品 envelope，明细固定在 `query.data.list`。Plan 调用方必须同时检查顶层
`status/exit_code` 与 `query.status`；`partial/error/contract_changed` 不得按空数据或成功处理。
精确 raw operation 不放入 `name="multidim"` request；专家需要时改用独立的
`gravity run report.multidim.*` 节点/调用。

## Material Performance composite

跨平台素材表现使用登记的 `name="material_performance"`，数组必须在 Plan 提交前显式完成：

```json
{
  "id": "materials",
  "kind": "composite",
  "request": {
    "name": "material_performance",
    "apps": ["main", "secondary"],
    "start": "2026-08-01",
    "end": "2026-08-07",
    "platforms": ["bytedance", "tencent", "kuaishou", "bilibili"]
  },
  "limits": {"max_pages": 20, "max_items": 5000},
  "output_fields": ["date_range", "platforms", "results", "limits"]
}
```

只有标量 `/start`、`/end` 可接受 binding；`/apps`、`/platforms` 或其元素都不是动态 target，
本轮不新增数组 DSL。adapter 内强制 worker 1，并把结果自报的 pages/items/workers 与节点 context
精确核对。每个平台分页也固定 worker 1；多个独立节点由 Plan 全局 pool 并发。

每个平台使用一次 stable `material.report.query` batch item，HTTP 数为 `Σ P_platform`。多个 App
合并进每个平台的 `app_list`，不展开笛卡尔积。节点 `max_items` 由 batch 按平台等额 floor 分配，
未用份额不可借用。safe projector 只保留白名单物理行、平台身份、计数、安全错误和分页收据；
结果不包含 App id/binding 值、原始请求或异常，也不做跨平台归一、排名或业务判断。

## Promotion Performance composite

推广表现使用登记的 `name="promotion_performance"`；一个节点只绑定一个 App，平台和物理指标数组
必须在提交前完成：

```json
{
  "id": "promotion",
  "kind": "composite",
  "request": {
    "name": "promotion_performance",
    "app": "main",
    "start": "2026-08-01",
    "end": "2026-08-07",
    "platforms": ["bytedance"],
    "metrics": ["stat_cost"]
  },
  "limits": {"max_pages": 5, "max_items": 200},
  "output_fields": ["app_id", "date_range", "platform_count", "metric_count", "results", "limits"]
}
```

只有标量 `/app`、`/start`、`/end` 可接受 binding；`platforms/metrics` 及其元素不是动态 target。
adapter 内平台与分页 worker 都固定为 1，多个 App 使用同层节点或 `foreach /app`，由 Plan 全局池
并发。`max_pages` 按平台生效，`max_items` 按平台等额 floor 分配且不可借用；safe projector 对
平台身份、顺序、预算、分页收据和结果计数重新核对。`platforms/metrics` 是 request 字段，不是
可投影的结果字段；结果只公开它们的数量，具体平台身份随每个受控 component 返回。
同一 `metrics` 数组必须由每个所选平台的实时元数据分别证明；原生指标名不同时用同层独立节点，
不要在一个节点里假设不同名称具有相同业务语义。

Agent 的唯一卡包含五个待填写字段与同形状 request，不选择任何业务值或自动执行。否定、导出、
写入、策略、相邻产品、raw snapshot 以及 `bing/xiaohongshu/taptap/wechat_video` 请求不会回落为
generic Promotion operation。结果保留平台原生字段，不做归一、汇总、排名或业务判断。

## Saved Analysis composite

保存分析 reference replay 使用 `saved_analysis` composite；Agent 主路径在提交前明确 App、稳定
ID/精确名称和日期窗：

```json
{
  "schema_version": "gravity.plan.v1",
  "budget": {"max_workers": 6, "max_total_items": 200},
  "nodes": [
    {
      "id": "saved_daily_purchases",
      "kind": "composite",
      "request": {
        "name": "saved_analysis",
        "app": "main",
        "ref": "Daily purchases",
        "start": "2026-08-01",
        "end": "2026-08-07",
        "mode": "run"
      },
      "limits": {"max_pages": 5, "max_items": 200}
    }
  ]
}
```

`start/end` 必须成对提供 ISO date/timestamp，两端下发且 `end-start` 不超过 90 天
（Agent 主路径使用 `YYYY-MM-DD`）。旧 compact reference 的无窗兼容只在直接 CLI/SDK 暴露，
Plan 保持可静态证明的显式窗口合同。
`mode` 只允许 `prepare/run`。只有 `/app`
可接受显式标量 binding，`ref/mode/start/end` 必须是提交前完成的 literal。reference Web artifact
严格复用 `event/funnel/retention/property/scatter` 五类编译器，不处理 template、layout、
favourite 或权限。多个互不依赖的保存分析应作为同层节点交给 Plan 全局 pool 并发；adapter 内
分页 worker 固定 1，避免并发相乘；直接 CLI/SDK 的目录分页才允许显式配置 1..24 worker。

Agent 卡的 request 保留 `app/ref/start/end` 可机械填写槽位且不会自动执行。已有引用和日期窗但
未知能力时是一次发现加一次 Plan；引用未知时必须先列目录并由调用方选择，因此若还需能力发现
至少三次。compact definition 旧模式是显式 SDK/CLI 兼容入口，不是 Agent Plan 自动翻译面。

## Segment Snapshot composite

分群详情、版本历史和指定日期的单日计算结果使用独立的 `segment_snapshot` composite：

```json
{
  "schema_version": "gravity.plan.v1",
  "budget": {"max_workers": 6, "max_total_items": 200},
  "nodes": [
    {
      "id": "segment_control_plane",
      "kind": "composite",
      "request": {
        "name": "segment_snapshot",
        "app": "main",
        "ref": "High-value users",
        "date": "2026-08-01"
      },
      "limits": {"max_pages": 5, "max_items": 200},
      "output_fields": ["segment", "results", "scopes"]
    }
  ]
}
```

`ref` 只接受稳定 ID 或精确名称，`date` 只接受一个 `YYYY-MM-DD`；名称歧义或日期无效均在
受控边界失败。节点至少预留 4 items，并固定按 `detail/history/daily_result` 顺序返回，局部失败
不取消 sibling。adapter 内部 worker 固定 1，由 Plan 全局 pool 管理跨节点并发。

只有 `/app` 可接受显式标量 binding；`ref/date` 是提交前完成的 literal。输出不包含成员、用户
标识、规则定义、request、binding 值或原始异常。已知输入时一次 `plan run`；未知时 Agent 强
意图卡给出 `app/ref/date` 占位符，调用方补齐并执行，仍是“发现一次 + Plan 一次”。

## Segment Members composite

成员名单与逐人属性使用同一 Segment family router 下的 `segment_members`：

```json
{
  "id": "segment_members",
  "kind": "composite",
  "request": {
    "name": "segment_members",
    "app": "main",
    "ref": "High-value users",
    "fields": ["Name", "ClientID", "user$level"]
  },
  "limits": {"max_pages": 5, "max_items": 100000},
  "output_fields": ["segment", "fields", "complete", "data"]
}
```

`fields` 省略时交付完整登记 profile；动态项必须来自 live user-property metadata。可选
`segment_version_id` 选择历史版本，日期不是此 route 的输入。上游忽略分页输入，因此 adapter
固定 1 worker，只把 `max_pages` 用于精确名称目录解析；成员数触及 `max_items` 时返回
`partial` / exit 3。只有 `/app` 可 binding，`ref/fields/segment_version_id` 必须是 literal。

## Analysis Default Dictionary composite

一个 App 的 Analysis SDK 默认值使用单请求 `analysis_default_dictionary` composite：

```json
{
  "id": "analysis_defaults",
  "kind": "composite",
  "request": {"name": "analysis_default_dictionary", "app": "main"},
  "limits": {"max_pages": 1, "max_items": 10},
  "output_fields": ["operation_id", "dictionary_count", "value_count", "data"]
}
```

只有 `/app` 可接受标量 binding；route 无分页，adapter 不创建内部 worker。结果 schema 为
`gravity-insight.analysis-default-dictionary.v1`，只交付登记的 `api/cocoscreator` string array；
新增字典键 fail-closed。已知 App 时一次 Plan；能力未知但 App 已知时是一次 Agent 发现加一次 Plan，
App 也未知时 `gravity.agent-call-bound.v1` 明确声明三次下界。

预检完整验证 schema、依赖、环、pointer、kind、动态 target 与最坏预算；失败时零网络请求。
节点仅限 `run`、`sql_product`、`metadata_search`、`composite`，不接受裸 SQL、任意
HTTP/Python、表达式、join/reduce、条件或循环。

binding 只复制 JSON Pointer 标量。每节点最多一个 `foreach`，默认 32、硬上限 64；不支持
嵌套扇出或笛卡尔积。声明节点最多 64、展开最多 256，总 `max_items` 不超过 100,000。

同层节点共享一个默认 6、最大 24 的 worker pool；adapter 内分页 worker 固定为 1，SQL 仍受
进程级并发 2 限制。独立分支失败不取消兄弟分支；下游返回 `skipped/DEPENDENCY_FAILED`。
结果按 Plan 声明顺序，fan-out 实例按源数组顺序。

`analysis_query` 也遵守同一调度合同：同层查询由全局 pool 并发，每个 adapter 调用的内部
worker 固定为 1，避免嵌套并发。一个查询失败时独立 sibling 继续；最终数组仍按声明顺序，
而不是完成顺序。节点 `limits.max_items` 与 Plan 总 `max_total_items` 同时生效。

错误结果 `result=null`，并使用完整 ErrorDetail。绑定失败为 `BINDING_FAILED`；顶层退出码保持
local 4 > upstream 3 > caller 2 > success 0。

成功结果保留受治理的原生 envelope（如 `operation_id/source/page/data/warnings`），但不会回显
request、literal spec、compiled input 或绑定值；失败也不回显原始异常。筛选值等敏感内容继续
遵守 Analysis 查询的脱敏合同。

本地 catalog 不存在或未包含 lineage snapshot 时，`table_lineage` 节点以 caller/2 失败且不发
网络请求；独立分支继续，依赖它的下游仍按 `skipped/DEPENDENCY_FAILED` 处理。
