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

预检完整验证 schema、依赖、环、pointer、kind、动态 target 与最坏预算；失败时零网络请求。
节点仅限 `run`、`sql_product`、`metadata_search`、`composite`，不接受裸 SQL、任意
HTTP/Python、表达式、join/reduce、条件或循环。

binding 只复制 JSON Pointer 标量。每节点最多一个 `foreach`，默认 32、硬上限 64；不支持
嵌套扇出或笛卡尔积。声明节点最多 64、展开最多 256，总 `max_items` 不超过 100,000。

同层节点共享一个默认 6、最大 24 的 worker pool；adapter 内分页 worker 固定为 1，SQL 仍受
进程级并发 2 限制。独立分支失败不取消兄弟分支；下游返回 `skipped/DEPENDENCY_FAILED`。
结果按 Plan 声明顺序，fan-out 实例按源数组顺序。

错误结果 `result=null`，并使用完整 ErrorDetail。绑定失败为 `BINDING_FAILED`；顶层退出码保持
local 4 > upstream 3 > caller 2 > success 0。
