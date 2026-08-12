# Python SDK 参考

Python API 与 CLI 共享合同和运行时。长期服务、notebook 封装或需要在内存中组合结果时使用
SDK；Agent 和一次性分析优先使用 CLI，因为它已经处理输入文件、输出编码、退出码和诊断。

## 推荐统一入口

```python
from gravity_sdk import connect

gravity = connect(workspace="/path/to/gravity.toml")

# 与 `gravity agent` 相同的离线发现合同；一次得到 recipe/operation、输入 schema 和下一步。
capabilities = gravity.capabilities("event analysis")

# 多个未知问题只做一次目录快照；每个候选带可直接组装的 plan_node。
many = gravity.capabilities_many(
    [
        {"id": "apps", "query": "list apps", "domain": "app"},
        {"id": "events", "query": "event metadata", "domain": "analysis"},
    ]
)

# 选中后走与 `gravity run` 相同的绑定、校验、父依赖、诊断和有界读取流水线。
result = gravity.run(
    capabilities["candidates"][0]["selector"],
    {"app_id": 101},
)

# 多个 recipe/operation selector 走同一 Resolver，复用实例绑定的 workspace。
batch = gravity.run_many(
    {
        "requests": [
            {"selector": "@retention-weekly", "apps": "*", "request_id": "weekly"},
            {"selector": "app.list", "inputs": {"page": 1}, "request_id": "apps"},
        ]
    },
    max_workers=4,
)

# 首次 read 才构建 Insight client；以后复用同一实例。
result = gravity.read("app.list", {"page": 1, "page_size": 20})

# 本地、合同约束的字段裁剪；非法字段在联网前失败。
compact = gravity.read(
    "app.list",
    {"page": 1, "page_size": 20},
    output_fields=["id", "name"],
)

# 独立读取一次提交，保留 batch 的顺序和错误语义。
results = gravity.read_many(
    [
        {"operation_id": "app.list", "inputs": {"page": 1, "page_size": 1}},
        {"operation_id": "app.list", "inputs": {"page": 2, "page_size": 1}},
    ],
    max_workers=2,
)

# 治理后的 workspace SQL product；不会暴露或接受裸 SQL。
products = gravity.describe_sql_products()
sql_result = gravity.query_sql_products(
    {
        "product": "daily-event-summary",
        "start": "2026-08-01T00:00:00+08:00",
        "end": "2026-08-02T00:00:00+08:00",
    }
)

# 固定组合复用同一个 workspace App alias，并在组合外层并发。
analysis = gravity.analysis_context("main", max_workers=6)
app = gravity.app_snapshot("main", max_workers=6)
attribution = gravity.attribution_snapshot("main", max_workers=6)

# 用紧凑、显式的分析语义代替 Web wire 结构；编译阶段不发送网络请求。
event_spec = {
    "start": "2026-08-01",
    "end": "2026-08-07",
    "time_grain": "day",
    "steps": [
        {
            "event": "app_open",
            "metric": {
                "field": "PresetAllCount",
                "aggregation": "PresetAllCount",
            },
        }
    ],
}
compiled = gravity.compile_analysis_query("event", event_spec, app="main")
assert compiled["network_called"] is False
event_result = gravity.analysis_query("event", event_spec, app="main")

# 紧凑规则先做零网络脱敏预览，再执行聚合人数/占比评估。
segment_spec = {
    "name": "active users",
    "start": "2026-08-01",
}
segment_preview = gravity.prepare_segment_evaluation(segment_spec, app="main")
segment_result = gravity.segment_evaluate(
    segment_spec, app="main", output_fields=["part", "percent", "total"]
)

# 保存分析按显式引用读取；prepare 读取目录/详情但不执行最终查询。
saved = gravity.saved_analyses("main")
eligibility = gravity.get_saved_analysis("main", "daily purchases")
prepared = gravity.prepare_saved_analysis("main", "daily purchases")
replayed = gravity.run_saved_analysis("main", "daily purchases")

# 并发读取经营概览与趋势；小时对比明确属于 workspace scope。
pulse = gravity.business_pulse(
    ["main"], "2026-08-01", "2026-08-07",
    platforms=["bytedance"], include_hourly=True,
)

# 严格离线读取已同步的数据表沿革；不会构建 Insight/SQL client。
lineage = gravity.table_lineage("publish", limit=20)

# 已知治理导出一次完成创建、轮询、校验和原子下载。
exported = gravity.export_run(
    "export.material.report.start",
    material_request,
    "D:/exports/material.xlsx",
    requested_columns=["file_name", "gravity_material_id", "stat_cost"],
    idempotency_key="material-20260812-001",
    timeout_seconds=300,
)
```

`GravitySDK` / `connect()` 惰性创建并分别缓存 Insight 与 SQL client，适合一个进程同时使用
两类能力。它复用 CLI 已有的 Agent 发现/执行合同，不再要求嵌入方自己拼接
search/describe/validate/read；它仍不根据字符串猜测 Insight/SQL 查询通道，也不改变底层
envelope 或异常。workspace 在构造时解析并绑定；之后即使进程切换 cwd，recipe、App alias、
SQL product 的描述和执行仍使用同一个 workspace。

| 统一方法 | 委托到 |
| --- | --- |
| `capabilities()` | `gravity agent` 同源的离线 recipe + stable operation 紧凑发现 |
| `capabilities_many()` | 一次快照批量发现多个问题，保序返回并给每个候选附 `plan_node` |
| `run()` | `gravity run` 同源的绑定、父依赖、校验、诊断、有界/全量读取流水线 |
| `run_many()` | `gravity batch run` 同源的 selector/App 展开、保序并发和失败隔离；支持批量默认 `output_fields`，绑定当前实例 workspace |
| `read()` | `GravityInsightClient.read()` |
| `read_all()` | `GravityInsightClient.read_all()` |
| `read_limited()` | Agent 安全前缀与显式 continuation，默认最多 5 页/200 项 |
| `read_many()` | `GravityInsightClient.batch()` |
| `export_run()` | 现有治理导出状态机：create、poll、download、隐私/schema 校验和原子提交 |
| `describe_sql_products()` | 安全描述 workspace 产品，不返回 SQL 模板 |
| `query_sql_products()` | `run_product_queries()`，支持单对象或批量、保序隔离失败 |
| `compile_analysis_query()` | 把 Analysis Spec v1 编译为稳定 operation input 并运行离线输入校验；带筛选值时预览脱敏且不返回 Plan node；零网络请求 |
| `analysis_query()` | 使用同一编译器执行 `event/funnel/retention/property/scatter` 稳定查询 |
| `prepare_segment_evaluation()` | 编译并离线校验紧凑 Segment Rule Spec，返回脱敏预览且不执行评估 |
| `segment_evaluate()` | 执行受治理的聚合人群规则人数/占比评估 |
| `saved_analyses()` | 列出一个 App 的安全保存分析身份，不读取 opaque config |
| `get_saved_analysis()` | 按 ID 或精确名称检查 Strict Replay 资格，不返回 config |
| `prepare_saved_analysis()` | 读取保存定义并严格编译，不执行最终 Analysis 查询 |
| `run_saved_analysis()` | 一次解析、严格编译并执行保存分析；不猜 Web 配置字段 |
| `analysis_vocabulary()` | 严格离线搜索已同步的 workspace 指标、标签、媒体枚举和模板目录 |
| `table_lineage()` | 严格离线查询已同步的 account-scope 数据表版本与操作观察 |
| `business_pulse()` | 并发读取 App 经营概览与趋势，可选 workspace scope 小时对比 |
| `analysis_context()` | 固定 13 个 Analysis 词汇/模板来源，外层并发、局部失败隔离 |
| `app_snapshot()` | 固定 6 个 App 治理来源，明确 company/App scope |
| `attribution_snapshot()` | 当前 8 个 stable attribution 配置来源，不包含 draft 查询 |
| `validate_plan()` | 离线校验 Plan schema、依赖、预算和 adapter 请求；不发网络请求 |
| `execute_plan()` | 使用内建四类受控 adapter 执行 Plan DAG |

需要完整 catalog、validate、probe、分阶段 export 恢复或测试注入时，使用公开属性 `gravity.insight`。
`gravity.sql` 是兼容专家调用方的低层入口，不应注册给程序化 Agent。

`capabilities_many()` 接受字符串或带稳定 `id` 的对象数组，也接受
`{"questions":[...]}` wrapper；每次最多 32 个问题，ID 必须唯一。它只扫描一次 Workspace、
stable operation、SQL product 和本地 metadata 目录，单项失败不影响其他项。

`analysis_vocabulary(query="", *, kind="vocabulary", database=None, limit=20, offset=0)` 只读一次 `metadata sync --all-apps` 生成的 SQLite 快照。同步对 9 个 workspace source 各请求一次，不随 App 数增加；搜索 kind 为 `metric/custom_metric/metric_tag/metric_tag_category/media_enum/template/vocabulary`，不接受 App 归属。partial 快照会公开失败来源；模板只有安全目录身份、不可回放。Agent 指标卡提供 `metrics_list` 或 `custom_metrics_list` 请求片段，但自然语言发现绝不自动执行分析。

`table_lineage(query="", *, database=None, limit=20, offset=0)` 只读已经通过
`gravity metadata sync --all-apps --include-table-lineage` 建立的本地 catalog。结果是
`scope="account"`、`observed=true` 的有界快照，只含观察到的 `table_id`、版本、动作及时间；
不得据此声称表名、App 归属或当前版本。成功响应不回显 catalog 绝对路径，也不会惰性构建
Insight/SQL client。catalog 缺失或未同步 lineage 时返回结构化 caller/2 错误，仍为
`offline=true`、`observed=false`，不会联网补数据。

`read()`、`read_all()`、`read_limited()` 和 `run()` 都接受 `output_fields`。它只在本地裁剪合同
允许的输出字段；默认 `None` 时保持原 envelope。动态字段必须同时由本次请求声明并被合同
允许，不能用它请求未知上游字段。

`export_run(operation_id, payload, destination, *, requested_columns, idempotency_key,
timeout_seconds=300.0)` 原样委托 `GravityInsightClient.export_run()`。当前唯一 callable create 是
`export.material.report.start`；status/cancel 和 blocked Analysis exports 不会成为 Agent executable
卡。未知导出通过一次 `capabilities("material report export")` 加一次 `export_run()` 完成发现与
执行；卡片不自动执行自然语言、不生成 Plan node，导出也不进入 Plan v1。

`destination` 是最终文件路径，不是 JSON 输出路径。timeout 不自动取消；结果保留安全的
`job_id/resumable/error.next_action`。已有 job ID 时用 `gravity.insight.export_status()`、
`export_wait()` 和 `export_download()` 恢复；创建结果不确定且无可靠 ID 时先 `export_list()`，
不要重复创建。输入、列顺序、幂等键和目的路径都必须由调用方显式给出。

## Analysis Query Spec v1

`compile_analysis_query(kind, spec, *, app=None, start=None, end=None, workspace=None)` 与
`analysis_query(kind, spec, *, app=None, start=None, end=None, workspace=None,
output_fields=None)` 支持 `event`、`funnel`、`retention`、`property`、`scatter` 五种 kind。
`app` 接受绑定 workspace 中的别名或正整数；成对提供的 `start/end` 覆盖 spec 日期。

编译结果使用 `gravity-insight.analysis-query-compiled.v1`，包含现有稳定 `operation_id`、
`compiled_input`、`validation` 和无敏感筛选值时可直接加入 Plan 的 `plan_node`；`offline=true` 且
`network_called=false`。执行方法会先调用同一编译和离线校验，再通过公共 `read()` 执行，
因此不需要在每次查询前单独编译。

Spec 只简化结构，不替调用方决定语义：事件名、属性名、指标、聚合、日期、窗口、分组和条件
必须显式填写。物理字段未知时，先通过 `gravity metadata search` 或本地 metadata API 确认，
随后一次调用 `analysis_query()`；自然语言 capability discovery 不会自动执行查询。

## Segment Rule Spec v1

`prepare_segment_evaluation(spec, *, app=None, start=None, end=None, workspace=None)` 与
`segment_evaluate(spec, *, app=None, start=None, end=None, workspace=None,
output_fields=None)` 使用 `gravity-insight.segment-rule-spec.v1`。spec 顶层为
`app/name/remark/update_type/start/end/logic/property_rules/event_rules`；条件、事件目标和日期模式
的完整机器合同由 `segment_rule_spec_schema()` 返回。它不接受 FE_CONFIG、Web wire JSON、表达式
或自然语言规则。

prepare 只编译并调用现有离线 `validate()`，因此 `network_called=false`；名称、备注和规则值均
脱敏，value-bearing preview 不返回 Plan node。`validation.status=needs_live_metadata` 表示事件、
属性、分群或版本仍须执行阶段用实时元数据证明，不等于已完成语义验证。执行只返回 stable
operation 投影，`output_fields` 仅允许 `part/percent/total`。

Agent 只有在中英文意图同时明确“人群/受众规则、人数或占比、评估”时返回唯一
`analysis.segment.rule.spec` 卡；卡片包含完整紧凑 schema 和缺失的 `app/spec`，不会生成规则值
或自动执行。泛分群列表、成员、历史、详情与导出继续走各自产品。

保存分析四个方法都接受 workspace App alias 或正整数。列表只返回受合同允许的身份字段；
`get/prepare/run` 的 reference 只接受稳定 ID 或精确名称，歧义时失败。Strict Replay 仅支持
`analysis_event/funnel/retention/scatter/user_property`，并要求保存 config 原样通过
Analysis Spec v1 与 FieldPolicy。按 reference prepare 会读取在线目录和详情；只有直接调用
公开 `compile_saved_analysis_definition()` 并提供本地 definition 才是零网络编译。

`business_pulse(apps, start, end, *, platforms=(...), include_hourly=False,
max_workers=6, max_pages=1000, max_items=100000, workspace=None)` 接受一个 App 或 App 序列；
每项是 workspace alias 或正整数。结果固定按 `overview/business/hourly_comparison` 排序，最后一项
只在 `include_hourly=True` 时存在，且始终标记 `scope=workspace`，不能当作某个 App 的小时
数据。对应 Plan composite 使用 `name="business_pulse"` 以及必填 `apps/start/end`。

## Plan v1

Analysis Query 不增加新的 SDK 方法：通过现有 `validate_plan()` / `execute_plan()` 执行
`composite` 节点。request 固定接受 `name="analysis_query"`、`kind/app/spec` 和可选的成对
`start/end`；五种 kind 是 `event/funnel/retention/property/scatter`。`output_fields` 属于 Plan
节点、不放进 request，并按底层 operation 的 data-relative FieldPolicy 校验。

Segment Rule 使用同一公开 `validate_plan()` / `execute_plan()`，composite request 为
`name="segment_evaluate"`、`app/spec` 和可选 `start/end`。只有 `/app` 可绑定；规则必须是提交前
完成的 literal spec，节点级 `output_fields` 仅允许 `part/percent/total`。

下面是一个完整的进程内 Plan 示例。Analysis event 与本地 metadata 分支没有依赖，交给同一个
全局 worker pool，同时保持声明顺序：

```python
from gravity_sdk import connect

gravity = connect(workspace="/path/to/gravity.toml")
plan = {
    "schema_version": "gravity.plan.v1",
    "budget": {"max_workers": 6, "max_total_items": 10000},
    "nodes": [
        {
            "id": "apps",
            "kind": "run",
            "request": {
                "selector": "app.list",
                "inputs": {"page": 1, "page_size": 20},
            },
            "limits": {"max_pages": 1, "max_items": 20},
            "output_fields": ["id", "name"],
        },
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
                    "time_grain": "day",
                    "steps": [
                        {
                            "event": "app_open",
                            "metric": {
                                "field": "PresetAllCount",
                                "aggregation": "PresetAllCount",
                            },
                        }
                    ],
                },
            },
            "limits": {"max_pages": 1, "max_items": 200},
            "output_fields": ["list", "target_list", "date_list"],
        },
        {
            "id": "events",
            "kind": "metadata_search",
            "request": {"query": "purchase", "kind": "event", "limit": 20},
        },
        {
            "id": "table_history",
            "kind": "metadata_search",
            "request": {"query": "publish", "kind": "table_lineage", "limit": 20},
            "limits": {"max_pages": 1, "max_items": 20},
        },
    ],
}

gravity.validate_plan(plan)                    # 全离线；失败时零网络请求
preview = gravity.execute_plan(plan, dry_run=True)
result = gravity.execute_plan(plan, max_workers=6)
```

已知 kind、App 和完整 literal spec 时直接执行 Plan，一次调用完成；未知时先用现有 Agent
capability discovery 得到候选，由调用方确认/补齐 spec，再执行 Plan，总共两次。自然语言不会
自动执行。多个独立 Analysis 查询应声明为同层 sibling；无需在 SDK 外再建线程池。

Plan v1 binding 只能把既有上游标量写入 `/app`，且来源必须列入 `depends_on`。它不允许
`/spec/...` target，也不解析 spec 内的表达式、引用或模板；调用方必须在提交前生成完整 literal
spec。

公开 Plan schema 可由 `gravity plan schema` 获取。四种节点是 `run`、`sql_product`、
`metadata_search` 和 `composite`；SDK 自动构造对应的内建 adapter，不接受裸 SQL、任意 HTTP 或
Python callback。若需要测试一个自定义 adapter，应直接使用 `gravity_sdk.plan.execute_plan`
的依赖注入接口，而不是把自定义执行器注册到 Agent facade。

`metadata_search` 的 `table_lineage` 请求仅接受 `query/kind/limit/offset`；它是 account scope，
因此禁止 `app_id`。节点结果保留 `scope/observed` 与有界的版本、操作 rows，不回显本地
database 路径。`limit` 同时受节点 `max_items` 和 Plan 总 `max_items` 预算约束。

Plan 先对所有节点完成离线预检，再提交任何执行。DAG 同层并发、依赖层顺序执行；一个全局
worker pool 默认 6、上限 24，adapter 内分页 worker 固定 1。独立失败不会取消 sibling，下游
依赖失败返回 `skipped/DEPENDENCY_FAILED`。声明最多 64 个节点、运行时最多展开 256 次、
聚合 `max_items` 预算不超过 100,000；单节点最多一个 foreach，默认 32、硬上限 64。

Analysis Query adapter 同样固定内部 worker 为 1；节点结果按 Plan 声明顺序而不是完成顺序。
节点 `limits.max_items` 与总预算共同生效。成功保留安全原生 envelope；成功与失败都不回显
request、literal spec、compiled input 或 binding 值，失败也不回显原始异常；条件/筛选值继续
使用 Analysis 查询的脱敏合同。

## Insight 专用 facade

```python
from gravity_sdk import GravityInsightClient

client = GravityInsightClient.from_env()

# 发现和描述不访问 Gravity。
candidates = client.search_operations("event analysis")
description = client.describe("analysis.event.list")
validation = client.validate("analysis.event.list", {"app_id": "101"})

# read 才访问 Gravity；返回结构化 envelope，而不是裸 response。
result = client.read("analysis.event.list", {"app_id": "101"})
```

主要方法：

| 方法 | 用途 |
| --- | --- |
| `operations()` / `search_operations()` | 列出或搜索 catalog |
| `describe()` / `schema()` | 获取调用合同 |
| `validate()` | 离线输入校验；某些字段会报告需要 live metadata |
| `read()` | 读取一页或一个非分页结果 |
| `read_all()` | 有明确总页数时按小窗口并发；未知总页数时串行；执行规模上限 |
| `read_limited()` | 读取 Agent 安全前缀，返回 `next_page_input`；分页策略同 `read_all()` |
| `batch()` | 并发执行独立读取，保持输入顺序并隔离失败 |
| `probe()` / `probe_all()` | 维护者的最小线上验证，不是普通查询前置步骤 |

批量读取应一次提交，不要在外层再建线程池：

```python
results = client.batch(
    [
        {
            "operation_id": "app.list",
            "request_id": "first",
            "inputs": {"page": 1, "page_size": 1},
        },
        {
            "operation_id": "app.list",
            "request_id": "second",
            "inputs": {"page": 2, "page_size": 1},
        },
    ],
    max_workers=2,
)
```

`from_env()` 默认加载包内编译 manifest，并让 Insight 与 SQL 复用同一个按
`timeout/attempts` 配置的进程级 HTTP runtime；先访问哪一侧不会改变配置。
测试必须注入显式 fake transport；普通单元测试不得连接生产 Gravity。

`read_all()` 和 `read_limited()` 的 `max_workers` 默认 6、上限 24，结果始终按页码顺序合并。
只有首页明确给出 `total_page` 才会并发；未知长度由每页响应决定是否继续，因此保持串行。
`batch()` 里的 `read_all` 会把分页 worker 固定为 1，避免两层线程池相乘。

## SQL 专用底层 facade

```python
from gravity_sdk import GravityClient

sql = GravityClient.from_env()
rows = sql.execute_sql("SELECT count(*) AS total FROM governed_source")
batch = sql.execute_batch(
    ["SELECT 1 AS value", "SELECT 2 AS value"],
    max_workers=2,
)
```

`GravityClient` 固定 custom-SQL 路由、复用认证、返回表格行并把并发限制为最多 2；它当前
只检查 SQL 是非空字符串。它不读取 workspace product，不校验 Evidence，也不替调用方执行
聚合隐私或输出投影。团队产品和 Agent 应使用 `gravity sql query <product>`；直接 SDK 调用方
必须自己拥有并审核 SQL 模板，不能把 `execute_sql()` 暴露为任意 SQL 工具。

## 错误与输出

Insight 的正常调用返回带 `schema_version`、`status`、`data`、`warnings` 和可选 `error` 的
envelope。SDK 异常均从 `gravity_sdk` 公开导出，常见基类是 `GravityInsightError`；调用方应
按结构化错误码处理，不解析英文错误文本。

不要把统一构造误解为自动路由：`GravitySDK` 不会根据字符串猜 Insight/SQL。高层 SQL
方法只执行 workspace product；如确需裸 SQL，必须显式进入 `gravity.sql` 或构造
`GravityClient`。Metadata sync 和 Census 仍有独立 facade/命令，并只在共享 runtime 或
合同层汇合。
