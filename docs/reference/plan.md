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

`app/inputs` 必填，`include_total/read_all` 显式布尔且默认 false。动态 target 兼容 `/app` 和
当前 `report.multidim.query` schema 登记的 `/inputs/<field>`；后者覆盖八个 product 字段以及仍在
operation 合同中的 legacy 字段，不硬编码成一份会漂移的名单。通用标量 binding/foreach 规则
仍然适用，`include_total/read_all/metadata_inputs` 不可绑定。Agent 不创建 binding，也不生成指标、
维度、日期或 filter 值。adapter 内部 worker 固定 1；多个独立查询作为同层节点交给 Plan 全局
pool，并保持声明顺序。一次执行的 HTTP
数为去重 metadata `M` + query 页数 `P` + 可选一次 total；total 依赖 query，不能并发提前执行。

Agent 对明确的中英文多维查询意图返回唯一 `composite:multidim` 卡，完整展开闭合 input schema
以及可机械填写的 `name/app/inputs/include_total/read_all` request。已知完整输入一次执行；未知
入口是 Agent + Plan 两次。模板、layout、收藏、权限、经营 pulse 和五类 Analysis 查询均不由
本 composite 接管。

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
