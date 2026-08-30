# Python SDK 参考

Python API 与 CLI 共用合同和执行 owner。长期服务、notebook 封装或内存组合使用 SDK；一次性任务和
Agent 优先使用 CLI。产品边界、结果状态和 fail-closed 规则见[机器契约索引](cli.md#machine-contract-index)。

## 构造与最小调用

```python
from gravity_insight import connect

gravity = connect(workspace="/path/to/gravity.toml")

capabilities = gravity.capabilities("event analysis")
selected = capabilities["candidates"][0]["selector"]
result = gravity.run(selected, {"app_id": 101})
```

`connect()` / `GravitySDK.from_env()` 在构造时解析并绑定 workspace，之后不随 cwd 改变。Insight 与 SQL
client 惰性创建并在同一 Runtime 内复用认证、限流和 principal 隔离；它不会按字符串猜查询通道。

精确 operation 调用：

```python
result = gravity.read("app.list", {"page": 1, "page_size": 20})
all_rows = gravity.read_all("app.list", {"page": 1, "page_size": 100})
prefix = gravity.read_limited("app.list", {"page": 1, "page_size": 20})
```

完整 operation 输入、默认值和响应投影先由 CLI `gravity operations describe <operation-id>` 读取；
不要从本页示例推导其他 operation 的字段。

## 签名自检

运行时签名是方法参数的精确真相：

```python
import inspect
from gravity_insight import GravitySDK

print(inspect.signature(GravitySDK.analysis_query))
print(inspect.signature(GravitySDK.segment_members))
```

方法文档不固定动态 catalog 数量。需要当前成员时直接枚举：

```python
methods = sorted(
    name for name, value in inspect.getmembers(GravitySDK)
    if callable(value) and not name.startswith("_")
)
```

<a id="method-index"></a>
## 方法索引

下表覆盖当前 `GravitySDK` 的公开 callable；精确参数仍以 `inspect.signature()` 为准。

| 领域 | 方法 |
| --- | --- |
| 发现与执行 | `capabilities()`、`capabilities_many()`、`resolve_capabilities()`、`run()`、`run_many()` |
| 原子读取 | `read()`、`read_all()`、`read_limited()`、`read_many()` |
| Analysis Query | `compile_analysis_query()`、`analysis_query()`、`analysis_queries()`、`bootstrap_event_analysis()` |
| Analysis 目录与模板 | `analysis_context()`、`analysis_default_dictionary()`、`analysis_vocabulary()`、`analysis_templates()`、`prepare_analysis_template()`、`run_analysis_template()` |
| Saved Analysis | `saved_analyses()`、`get_saved_analysis()`、`prepare_saved_analysis()`、`run_saved_analysis()`、`create_saved_analysis()`、`update_saved_analysis()`、`delete_saved_analysis()` |
| Segment | `prepare_segment_evaluation()`、`segment_evaluate()`、`segment_snapshot()`、`segment_members()`、`segment_create_from_analysis()`、`segment_create_from_rule()`、`segment_create_from_history()`、`segment_create_from_tmp()`、`segment_update()`、`segment_update_rule()`、`segment_refresh()`、`segment_delete()` |
| Dashboard / Kanban | `dashboard_snapshot()`、`prepare_dashboard_analysis()`、`run_dashboard_analysis()`、`kanban_mutation_schema()`、`kanban_mutation()` |
| 用户、订单与变现 | `user_journey()`、`user_detail_aggregate_input_schema()`、`prepare_user_detail_aggregate()`、`user_detail_aggregate()`、`order_directory()`、`order_split_trace()`、`monetization_detail()` |
| App 与归因 | `app_snapshot()`、`account_permission_profile()`、`attribution_snapshot()`、`attribution_performance()`、`attribution_user_detail()` |
| 经营与投放 | `business_pulse()`、`company_usage()`、`advertiser_profile()`、`bilibili_account_performance()`、`custom_audiences()` |
| 素材 | `material_performance()`、`fetch_material_asset()`、`title_packages()` |
| Promotion | `promotion_performance()` |
| Multidim / Semantic | `multidim_input_schema()`、`prepare_multidim_query()`、`validate_multidim_query()`、`multidim_query()`、`semantic_compose_input_schema()`、`prepare_semantic_compose()`、`semantic_compose()` |
| 本地派生与 playbook | `derive_metrics()`、`metric_anomaly_playbook_schema()`、`prepare_metric_anomaly_playbook()`、`metric_anomaly_playbook()` |
| Metadata | `sync_metadata_app()`、`metadata_status()`、`table_lineage()`、`metadata_cache_stats()`、`clear_metadata_cache()`、`bypass_metadata_cache()` |
| Metadata template | `metadata_template_mutation_schema()`、`metadata_template_mutation()`、`create_metadata_template()`、`append_metadata_template_members()`、`remove_metadata_template_members()`、`delete_metadata_template()` |
| Realtime event | `realtime_event_catalog()`、`realtime_event_mutation_schema()`、`realtime_event_mutation()` |
| Reports | `report_directory()`、`report_subscriptions()`、`create_report()`、`delete_report()`、`create_report_subscription()`、`delete_report_subscription()` |
| Custom metric | `custom_metrics()`、`custom_metric_mutation_schema()`、`custom_metric_mutation()`、`create_custom_metric()`、`update_custom_metric()`、`delete_custom_metric()` |
| Export / receipt | `export_run()`、`list_http_receipts()`、`get_http_receipt()`、`export_http_receipts()` |
| SQL product | `describe_sql_products()`、`query_sql_products()` |
| Plan recipe / DAG | `expand_plan_recipe()`、`validate_plan_recipe()`、`execute_plan_recipe()`、`validate_plan()`、`execute_plan()` |
| 构造 | `from_env()` |

### Material Asset Fetch

```python
from pathlib import Path
from gravity_insight import GravitySDK

gravity = GravitySDK.from_env()
result = gravity.fetch_material_asset(
    "bytedance_project",
    {"advertiser_id": 1800000000000001, "project_id": 1800000000000002},
    "material_id",
    1800000000000003,
    "file",
    Path("artifacts/creative.mp4"),
)
assert result["artifact"]["status"] == "complete"
assert Path("artifacts/creative.mp4").is_file()
```

三个 ID 是脱敏示例值，必须替换为同一已授权项目的真实引用。方法只覆盖 fresh source 中唯一命中、
且 private URL 命中固定 host/path allowlist 的 JPEG 缩略图或 MP4；不接受 URL，也不把 URL 放入普通
source JSON、结果、错误或 receipt。无法区分的缺失/过期/未缓存/删除/权限统一抛
`MaterialAssetUnavailableError`（`code=MATERIAL_ASSET_BINARY_UNAVAILABLE`）；未登记 host/path 抛
`MaterialAssetSourceUnsupportedError`。完整边界和 CLI 输出见 [Material Asset Fetch](cli.md#material-asset-fetch)。
`analysis_queries(payload, max_workers=N)` 对独立 spec 使用一个 Plan worker 预算。可重试的 upstream 组件
拒绝会触发 `N -> floor(N/2) -> ... -> 1` 的有界自适应重试；已成功或确定性失败的组件不会重放。
live 结果的 `adaptive_execution` 是值无关执行轨迹，可据此读取最终并发、重试轮数、退避和总组件调用数。

非 callable 子服务保持独立职责：`gravity.insight`、`gravity.sql`、`gravity.sql_explorer`、
`gravity.actions`、`gravity.experiments`、`gravity.journeys`、`gravity.capability_trust`、
`gravity.analysis_artifacts`、`gravity.governor`、`gravity.execution_variants`、`gravity.prepared_plans`。

## 发现与执行

`capabilities()` 与 `gravity agent` 同源且默认离线。调用方已有严格 selection 时传
`host_selection=`；显式 recognizer 不接受 selection。`capabilities_many()` 对多个问题复用同一目录
快照并保序返回，单项失败不污染 sibling。

`resolve_capabilities()` 是显式在线补参入口，只接受声明的 known inputs；它读取完整安全目录但不选择
值、不执行候选。默认发现不联网。

`run()` 将 recipe 或 operation selector 交给同一 Resolver；`run_many()` 复用当前实例 workspace，
保序并隔离独立失败。原子 operation 已知时直接用 `read*`；产品已知时优先用对应高层方法。

`output_fields=` 是本地合同投影。动态字段必须同时由本次请求声明并被 operation/product 允许；未知
字段在发网前失败。

## Analysis 与产品方法

高层方法是现有产品 owner 的薄委托，不另造请求或结果合同：

```python
event_spec = {
    "start": "2026-08-01",
    "end": "2026-08-07",
    "time_grain": "day",
    "steps": [{
        "event": "app_open",
        "metric": {"field": "PresetAllCount", "aggregation": "PresetAllCount"},
    }],
}

preview = gravity.compile_analysis_query("event", event_spec, app="main")
result = gravity.analysis_query("event", event_spec, app="main")
```

编译入口不发送最终分析请求，带条件值的预览使用脱敏表示。Analysis、Segment Rule、Multidim 和
Semantic Compose 都要求显式结构化输入；自然语言不填业务字段。

产品之间不要互相替代：Dashboard snapshot 不执行图表；Segment snapshot 不返回成员；Saved Analysis
prepare 不执行最终查询；Order Split Trace 必须先唯一匹配父行；Material/Promotion 不跨平台归一或
生成业务判断。

## 写入与效果

所有 direct mutation 方法默认 `execute=False`。调用方先审查 preview，再用同一输入显式执行；未知
结果不自动重试。Segment、Saved Analysis、Report、Metadata Template、Realtime Event、Custom Metric
和 Kanban 各自保留 owner/marker/preimage/readback 规则，不能共用一个宽泛写入口。

`gravity.actions` 为显式 Action Plan：preview 绑定规范化请求和有效期，execute 还需用户确认同一 plan、
request digest 与 preview fingerprint。自然语言、Context、Skill、tool result 和历史记录都不能构造
authorization。Action 不等同于 Plan v1 普通节点。

## Plan v1

```python
plan = {
    "schema_version": "gravity.plan.v1",
    "budget": {"max_workers": 4, "max_total_items": 1000},
    "nodes": [{
        "id": "apps",
        "kind": "run",
        "request": {"selector": "app.list", "inputs": {"page": 1}},
        "limits": {"max_pages": 1, "max_items": 20},
    }],
}

checked = gravity.validate_plan(plan)
result = gravity.execute_plan(plan)
```

Workspace Plan recipe 使用 `expand_plan_recipe()`、`validate_plan_recipe()`、`execute_plan_recipe()`。
节点、adapter、binding、预算和失败合同见 [Plan 参考](plan.md)，不要在 SDK 调用方复制 Plan 规则。

## Export 与 receipt

`export_run(operation_id, payload, destination, *, requested_columns, idempotency_key,
timeout_seconds=...)` 执行已登记导出状态机。destination 是最终文件，不是 JSON 输出路径；timeout 不
自动取消。创建结果不确定且无可靠 job id 时先查询现有任务，不重复创建。

HTTP receipt 只保存 method、合同 path、operation、状态、时间、页/attempt/retry 和请求 shape
fingerprint，不保存请求值、响应体或凭据。使用 `list_http_receipts()`、`get_http_receipt()`、
`export_http_receipts()`；不要依赖磁盘目录布局。

## Metadata 与缓存

`metadata_status()`、`analysis_vocabulary()`、`table_lineage()` 严格离线。`sync_metadata_app()` 只更新
一个显式 App；失败不把 partial staging 冒充完整 catalog。lineage 是 account-scope 观察，不能据此
推断表名、App 归属或当前版本。

进程内 metadata cache 按 principal 和 credential generation 隔离，只缓存允许的 metadata snapshot。
需要最新值时调用 `clear_metadata_cache()`，或临时 `bypass_metadata_cache(True)`；mutation 成功会失效
相关缓存。CLI 每次新进程，不能假设命中同一内存 cache。

<a id="user-detail-aggregate"></a>
## User Detail Aggregate

```python
request = {
    "source": {"app_id": "101", "date": "2026-08-29"},
    "filters": [],
    "group_by": ["Version"],
    "measures": [{"name": "users", "op": "count"}],
    "bounds": {"max_pages": 100, "max_items": 10000, "max_cells": 20},
}
preview = gravity.prepare_user_detail_aggregate(request)  # zero network
result = gravity.user_detail_aggregate(request, max_workers=4)
```

`user_detail_aggregate_input_schema()` 返回闭合 machine schema。执行时动态字段先经 live metadata
白名单验证，分页和 receipts 由公共 Insight client 负责；返回信封没有用户行或用户标识。当前源合同
不能证明完整 collection，调用方必须检查 `pagination.completeness` 和 `claims.forbidden`。

## Insight 专用 facade

```python
from gravity_insight import GravityInsightClient

client = GravityInsightClient.from_env()
contract = client.describe("analysis.event.list")
validated = client.validate("analysis.event.list", {"app_id": "101"})
result = client.read("analysis.event.list", {"app_id": "101"})
```

`operations()` / `search_operations()` / `describe()` / `schema()` / `validate()` 离线运行；`read()`、
`read_all()`、`read_limited()`、`batch()` 才执行读取。`probe()` / `probe_all()` 只供遵循探测纪律的
维护者使用，不是普通查询前置步骤。

新增未登记响应字段从业务 `data` 省略并记入 `result_audit.response_drift`；已登记字段缺失、类型变化、
枚举破坏和未登记请求字段仍 fail closed。

<a id="app-id-wire-types"></a>
## App ID wire types

`app_id` 是标识，不是业务数值。不同 operation 可分别声明 string 或 integer；SDK 只在该 operation
合同已声明单一类型时，把正整数和十进制数字字符串归一化到声明类型。其他值不猜测，错误保留
`field=app_id` 与 remedy。

每条 route 的精确类型必须查看 `gravity operations describe <operation-id>`。不要使用文档中的全局
计数判断单条 operation，也不要把 `app_id` 与 `advertiser_id`、`dashboard_id`、`project_id` 互换。

## SQL 专用底层 facade

```python
from gravity_insight import GravityClient

sql = GravityClient.from_env()
rows = sql.execute_sql("SELECT count(*) AS total FROM governed_source")
```

`GravityClient` 是兼容专家调用方的低层 custom-SQL facade：它不读取 workspace product，不执行
Evidence、聚合隐私或输出投影。团队产品和 Agent 使用 `query_sql_products()` 或 `gravity sql query`；
不要把 `execute_sql()` 暴露为任意 SQL 工具。

`gravity.sql_explorer` 与 Gravity SQL client 隔离，仅处理显式 SQLite request，使用 AST、只读数据库
身份、authorizer 和资源预算。Explorer 的 promote 只编译 reviewed product definition，不自动安装、
路由或授予 Trust。

## 错误与输出

SDK 返回 versioned envelope，并从 `gravity_insight` 公开结构化异常。调用方按 `status`、`code`、
`category`、`field`、`stage`、`next_action` 处理，不解析 message。状态、partial 和 fail-closed 规则统一
见[结果与错误](cli.md#result-and-errors)。

统一构造不表示自动路由：高层 SQL 只执行 workspace product；裸 SQL 必须显式进入低层 facade。
测试注入 fake transport，普通单元测试不得连接生产 Gravity。
