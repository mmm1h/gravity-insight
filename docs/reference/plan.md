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
