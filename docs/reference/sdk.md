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

## 多账号鉴权失效切换（高级、默认关闭）

只支持完整只读边界：`read`、`read_all`、`read_limited`、`run`、`execute_plan`、
`query_sql_products`。一个 Plan、composite 或分页读取固定到同一槽位和世代；401 时先由原
Runtime 刷新一次，世代改变后取消待发页、等待已发请求结束、丢弃结果并从头重跑。刷新后仍鉴权
失败才推进到下一个兼容槽位。裸 `sdk.insight` / `sdk.sql`、其他未接入边界和 workspace 覆盖
会明确拒绝，不自动降为单账号，也不自动重放 mutation。关闭功能不改变原单账号行为。

```python
from gravity_insight import connect
from gravity_insight.account_pool import AccountPoolConfig

gravity = connect(
    workspace="/path/to/gravity.toml",
    account_pool=AccountPoolConfig(
        enabled=True,
        env_paths=("/protected/account-a.env", "/protected/account-b.env"),
        max_accounts=2,
    ),
)
status = gravity.account_pool_status
```

`enabled=False` 为默认值。显式提供关闭的配置覆盖环境开关；关闭时不解析、不 stat、不打开备用
源。每个槽位仍通过 `connect(env_path=...)` 创建独立 SDK/Runtime，未增加凭据格式或共享 session。
全部账号源及 session 必须位于仓库外、无 symlink/junction、可收紧到当前用户及系统管理员访问；
不能把备用账号加入主 `.env`。`max_accounts=2` 是配置默认值，不是固定数组长度；显式调大即可
允许更多槽位，但账号之间仍顺序执行，不增加 host/global 并发。

环境配置为 `GRAVITY_ACCOUNT_FAILOVER=0|1`（默认 `0`）、`GRAVITY_ACCOUNT_ENV_FILES`
（有序 JSON 路径数组）、`GRAVITY_ACCOUNT_MAX_ACCOUNTS`（默认 `2`）。名称特意使用
`FAILOVER`，不叫 `PARALLEL` 或 `POOL_ENABLED`，以免误解为吞吐或调度功能。
CLI/Agent 显式使用 `gravity account-pool`，例如
`gravity account-pool --enable --account-env <a> --account-env <b> read-all <operation> --input '{}'`。
`plan` / `sql-products` 的 `--input` 接受 JSON 对象；SDK 与 CLI 复用同一边界。配置了环境开关后，
统一 `gravity` 的普通命名空间拒绝执行并引导到显式命令。独立的 `gravity-insight` /
`gravity-sql` 专用入口不支持账号池；需要切换时必须改用上述入口，不能只设置环境开关。

**429 不触发切换**：Owner 于 2026-09-07 的 382 + 7 次生产请求、两轮独立进程复现表明，
同 IP 的不同 principal 在 A 被限流时 B 也返回 429，否定账号隔离。429（即使响应体含鉴权码）
仍使用原 host limiter / Retry-After 退避；403、5xx、网络错误也不作为换号信号。本实现只以离线
夹具验证这些规则，不声称完成生产实测，也不实现需求 2。

### 准入与状态

凭据可读不等于权限兼容。每个槽位需要当前世代私有根目录下的
`agent-runtime/account-failover-admission.v1.json`，字段由
[`account-admission-v1.schema.json`](../../src/gravity_insight/contracts/schema/account-admission-v1.schema.json)
拥有。`principal` 是上游 principal ID 的 SHA-256（仅私有准入比较，不对外输出）；
`generation_ref` 复用 #174 的随机 opaque marker，不能用可反推的凭据摘要替代。
`permission_scope` / `data_scope` 是调用方审定的规范化权限和数据范围证据摘要，必须有证据引用且
两账号相同。TTL 最多一天；缺失、过期、世代不匹配、重复 principal 或范围不一致均拒绝。
角色名或菜单列表相同不能替代此证明。Runtime 不自动签发这些权限等价声明。

`capabilities` 引用同一私有根目录的现有 Capability Validation store。Insight 复用同层 Trust
检查；登记 SQL 产品使用 `product` / `sql-product:<登记名>`，以现有 `contract_hash()` 同时校验
`contract_digest` 与 `provider_fingerprint`，并要求版本、有效期、stable、complete、DQ pass 和证据引用；
每次请求前重新核验冻结证据的有效期和依赖 trust，长读取不会越过验证期限。
未准入的 SQL 产品不能因另一个产品通过就执行。一次读取内同 principal 刷新后可以沿用冻结准入
的剩余有效期，但不会将旧验证伪造成新验证写入新世代；后续独立读取需要当前世代的准入记录。

`account_pool_status` 区分备用槽位 `not_configured`、`configured_unavailable`、`configured_healthy`；
未校验时为 `configured_unavailable/ADMISSION_PENDING`，拒绝凭据为 `configured_unavailable/AUTH_REJECTED`。
切换态为 `never_switched`、`switching`、`switched_success`、`switched_failed`、`exhausted`。
所有可选槽位失效或不可用时抛出 `ACCOUNT_POOL_EXHAUSTED`，池终止，需修复后显式重新 connect。
收据和 `gravity_account_failover` 日志只记录槽位序号、原因、累计切换次数和随机世代标识。
HTTP attempt/page 使用当前槽位 Runtime 的世代根；切换事件也写在该根的 `account-failover/`，不输出
env 路径、principal 值或凭据。`status` 不进行生产探测，也不会把待验证账号标成健康。

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
| Multidim / Semantic | `multidim_input_schema()`、`prepare_multidim_query()`、`validate_multidim_query()`、`multidim_query()`、`reconcile_standard_retention_denominators()`、`semantic_compose_input_schema()`、`prepare_semantic_compose()`、`semantic_compose()` |
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

示例 ID 的替换、fresh source 唯一匹配、JPEG/MP4 与 URL 隐私边界见 [Material Asset Fetch](cli.md#material-asset-fetch)。
SDK 的 `MaterialAssetUnavailableError` 对应 `MATERIAL_ASSET_BINARY_UNAVAILABLE`，
`MaterialAssetSourceUnsupportedError` 对应 `MATERIAL_ASSET_SOURCE_UNSUPPORTED`。

`analysis_queries(payload, max_workers=N)` 共用一个 Plan worker 预算；自适应重试和
`adaptive_execution` 轨迹见 [Analysis Query Spec v1](cli.md#analysis-query-spec-v1)。

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

### 投放到用户的 join key

issue #154 将跨 operation 的物理 join 收口为逐平台机器契约，不从字段名猜测。调用方先用
`gravity_insight.contracts.join_key.resolve_proven_join_key()` 按 `platform`、`object_type` 和可选
`object_subtype` 解析；返回值给出精确左右 operation/path、规范化规则和观测证据。只有未超过
`revalidate_after` 的 `namespace_status=proven` 可解析，`disproven`、`insufficient_evidence`、过期证据
和素材子类型歧义全部抛 `JoinKeyContractError`。机器真相位于
`contracts/join-keys/registry.v1.json`，结构由 `join-key-registry-v1.schema.json` 校验。

### 普通留存分母对账

`reconcile_standard_retention_denominators()` 只接收两侧已取得的聚合读数：`status`、`value`、
`fetched_at`，以及共同的 `cohort_date` 和 `offset`。它不访问网络，也不接收 App、账号或明细行。
结果用 `status=match|drift|unknown` 区分算术相等、非零有符号差值和证据不足；两侧成功但空的
cohort 也是 `unknown`，另以 `cohort_status=empty` 和 `EMPTY_COHORT` 标明，绝不补成 0。

每条结果都保留 `standard_activate_cnt`、`init_num` 及各自 `fetched_at`，并携带
`STANDARD_RETENTION_DENOMINATOR_COHORT_RULE_UNVERIFIED` capability gap。当前合同和脱敏探针只证明
字段存在，未证明两者共享同一 cohort 纳入、日界线、归因和迟到回补语义；因此即使
`status=match`，`semantic_equivalence` 仍是 `unknown`，不得用 Retention `values[0]` 替代
`init_num`。稳定输出合同是 `gravity.retention-denominator-reconciliation.v1`。

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

`user_detail_aggregate_input_schema()` 返回闭合 machine schema（含 `WITH_VAL` 与非空字符串写法）。
动态字段、公共分页/receipts、隐私和错误分类统一见 [User Detail Aggregate 合同](cli.md#user-detail-aggregate)；
源合同不证明完整 collection，调用方必须检查 `pagination.completeness` 和 `claims.forbidden`，按错误码而非文本判断重试或修复 owner。

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

`query_sql_products()` 的成功项仍须检查 `row_cap_reached`、`completeness` 和
`completeness_reason`；执行状态、readiness 与独立 `summary.total_row_count` 的判据统一见
[CLI SQL 完整性合同](cli.md#sql)。readiness 只证明当前登记合同及不可变 Evidence 可用，不证明下游 cohort 完整。

该结果同时携带 `obligations`：`execution_status` 来自 SQL 执行结论，`data_completeness` 来自 row-cap/
独立总行数判定；`semantic_validity` 在本层未评估时明确为 `unknown`，读路径的
`mutation_certainty` 为 `not_applicable`。这些值由内层类型对象序列化，调用方不得用旧顶层状态覆盖。

`gravity.sql_explorer.inspect()` / `execute()` 保留为显式本地 SQLite 合同测试路径，使用 AST、只读数据库
身份、authorizer 和资源预算。联网 SQL Fast Lane 的 owner 是
`gravity_insight.sql.verification.GravitySqlExplorerAdapter`；调用方用 `runtime_factory` 延迟提供既有
governed HTTP Runtime。Adapter 在调用该 factory、读取凭据或创建 session 前校验已登记的精确
`POST /custom_sql/api/sql/execute` 路由与人工 read
confirmation，再用固定版本 sqlglot 对单条 `SELECT` / `WITH ... SELECT` 执行关系、函数、输出列和
字面量 `LIMIT` 检查。请求 schema 是 `gravity.sql-fast-lane-request.v1`；结果固定为
`trust=exploratory`、`completeness=unknown`、`allowed_claims=[]`，不能成为 Stable Journey 依赖。

上游 bundle 没有公开数据库方言，Fast Lane 因而明确报告 `dialect=unknown`，generic AST 只作为保守
语法门。当前 Web session 也不是独立只读身份；上游没有可验证的只读事务、scan row/byte budget 或
在途取消合同。这些项在结果 `safety` 中保持 `unavailable_*`，由精确 AST/allowlist、一次请求、timeout
和输出 row/byte/cell/column budget 补偿，但补偿控制不等同于身份或服务端资源隔离。

两种 Explorer 的成功执行都只生成 reviewed promotion source；把 Fast Lane source 交给
`SqlExplorerService.promote()` 时仍要求显式 approval，并复用现有 Registered SQL Product 安装器。
Promotion 不会授予 stable identity 或
`stable_dependency_allowed`，登记产品继续从 `query_sql_products()` 进入，不会回退到 Explorer。

## 错误与输出

SDK 返回 versioned envelope，并从 `gravity_insight` 公开结构化异常。调用方按 `status`、`code`、
`category`、`field`、`stage`、`next_action` 处理，不解析 message。状态、partial 和 fail-closed 规则统一
见[结果与错误](cli.md#result-and-errors)。

统一构造不表示自动路由：高层 SQL 只执行 workspace product；裸 SQL 必须显式进入低层 facade。
测试注入 fake transport，普通单元测试不得连接生产 Gravity。
