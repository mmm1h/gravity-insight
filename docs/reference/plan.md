# Plan v1 参考

Plan v1 把已登记 operation/recipe、受治理 SQL product、本地 metadata、receipt 查询和 allowlisted
composite 组织为有界 DAG。产品契约不在本页复制；精确 operation 与结果规则见
[机器契约索引](cli.md#machine-contract-index)。

## 最小 Plan

```json
{
  "schema_version": "gravity.plan.v1",
  "budget": {"max_workers": 4, "max_total_items": 1000},
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

```powershell
gravity plan schema
gravity plan run --input plan.json --dry-run
gravity plan run --input plan.json --concurrency 4
```

`--dry-run` 走完整结构校验和 adapter preflight，但不执行节点请求。

## 机器 schema 的范围

`gravity plan schema` 是 Plan 顶层、节点、binding、预算、失败优先级和 Host effect boundary 的机器
合同。当前 `composites` 字段只公开 `analysis_query` 的专项 request/binding 形状，**不是完整 composite
catalog**。其余当前 allowlisted composite 由 adapter preflight 验证，并在下方提供稳定名称索引。

这是一项当前可发现性限制：Agent 不应从 `plan schema.composites` 只有一个成员推断其他 composite
不存在，也不应把本页表格当作 request schema。组装请求时先由 `gravity agent-catalog describe
<selector>` 取得产品卡和 Plan node，再由 dry-run 验证。

## 节点合同

节点 required 字段为 `id/kind/request`，可选 `depends_on/bindings/foreach/limits/output_fields/call_bound`。
当前 node kinds：

| kind | request 身份 | 边界 |
| --- | --- | --- |
| `run` | `selector` + operation/recipe inputs | 只执行 Resolver 可接受的稳定身份 |
| `sql_product` | workspace product + 参数 | 不接受裸 SQL |
| `metadata_search` | allowlisted 本地 metadata kind | 严格离线 |
| `composite` | allowlisted `name` + 专用字段 | adapter 预检 request、binding target 和投影 |
| `receipt_query` | receipt list/get/export 查询 | 只读、值无关，不暴露磁盘布局 |

Plan 不接受任意 HTTP、Python、表达式、join/reduce、条件或循环。业务组合必须先成为受治理 product、
composite 或 SQL product。

## 依赖、binding 与 foreach

`depends_on` 声明 DAG 边。`bindings` 只把已完成节点结果中的 RFC 6901 JSON Pointer **标量**复制到
目标 request leaf；source/target 必须由 adapter allowlist 接受。`foreach` 从一个数组 source 展开
同一节点，每节点最多一个，不支持嵌套或笛卡尔积。

```json
{
  "id": "details",
  "kind": "run",
  "request": {"selector": "app.app_info.get", "inputs": {"url": "placeholder"}},
  "depends_on": ["apps"],
  "foreach": {
    "from": "apps",
    "source": "/result/data/list",
    "target": "/inputs/url",
    "max_items": 8
  },
  "limits": {"max_pages": 1, "max_items": 8}
}
```

动态值不会在 preflight 错误、Plan result 或 receipt 中回显。

## 预算与调度

当前机器上限由 `gravity plan schema` 返回：声明节点、展开执行、aggregate items、foreach、outer
concurrency 和 adapter concurrency 都受界。默认 outer worker pool 为 6、最大 24；adapter 内部 worker
固定 1，只能借用同一全局预算，不能叠加私有线程池。

Plan 先预检全部节点，再提交执行。同层就绪节点并发，依赖层顺序执行；结果按 Plan 声明顺序，
foreach 实例按 source 数组顺序。提高 worker 数不能增加请求总量或绕过分页/结果预算。

<a id="adapter-index"></a>
## Adapter 索引

以下名称是当前 runtime 接受的 composite identity。request 字段和允许 binding targets 由对应 adapter
preflight 决定；先用 Agent 产品卡生成节点，不手写猜测。

下表同时列出 identity 与边界，旧 composite 小节锚点保留在对应行。

| composite `request.name` | 边界 |
| --- | --- |
| <a id="derived-metrics-composite"></a>`derived_metrics` | 产品行为见 [Derived Metrics](cli.md#derived-metrics)。 |
| <a id="analysis-query-composite"></a>`analysis_query` | 接受显式 `kind/app/spec` 和可选日期覆盖；只允许 `/app` binding，不允许绑定 spec 内 业务值。adapter 先编译、脱敏和离线校验，再执行对应稳定 Analysis operation。结果保留产品 envelope， 不回显 literal spec 或 compiled input。 |
| <a id="business-pulse-composite"></a>`business_pulse` | 产品行为见 [Business pulse](cli.md#business-pulse)。 |
| <a id="dashboard-snapshot-composite"></a>`dashboard_snapshot` | 产品行为见 [Dashboard snapshot](cli.md#dashboard-control-plane-snapshot)。 |
| <a id="dashboard-analysis-composite"></a>`dashboard_analysis` | 产品行为见 [Dashboard Analysis Replay v2](cli.md#dashboard-analysis-replay-v2)。 |
| <a id="user-journey-composite"></a>`user_journey` | 产品行为见 [Single-user journey](cli.md#single-user-journey)。 |
| <a id="order-directory-composite"></a>`order_directory` | 产品行为见 [Order Directory v1](cli.md#order-directory-v1)。 |
| <a id="order-split-trace-composite"></a>`order_split_trace` | 产品行为见 [Order Split Trace v1](cli.md#order-split-trace-v1)。 |
| <a id="segment-rule-composite"></a>`segment_evaluate` | 接受显式 Segment Rule Spec；聚合人数/占比、自然语言和不保存分群的边界见 [Segment Rule Spec v2](cli.md#segment-rule-spec-v2)。 |
| <a id="multidim-composite"></a>`multidim` | 要求 `input_schema_version`；闭合物理输入、预检和结果状态规则见 [Multidim](cli.md#multidim)。 |
| <a id="user-detail-aggregate-composite"></a>`user_detail_aggregate` | request 只接受 `name/input_schema_version/inputs`，不接受 binding 或 foreach 目标；`inputs` 与 CLI 的闭合 schema 相同。adapter 内部固定 `max_workers=1`，要求请求 `bounds.max_pages <= node.limits.max_pages`、`bounds.max_cells <= node.limits.max_items`。结果 projector 从闭合单元格、分页/source/audit 白名单重新构造信封，原始 `data/request/next_page_input` 或未知容器 不会穿过 Plan 边界。 |
| <a id="material-performance-composite"></a>`material_performance` | 按 App、日期窗和平台读取；原生字段与跨平台边界见 [Material Performance](cli.md#material-performance)。 |
| <a id="promotion-performance-composite"></a>`promotion_performance` | 要求显式 App、日期窗、平台和物理指标；每个平台独立受预算约束，未用份额不能 借给 sibling。 |
| <a id="saved-analysis-composite"></a>`saved_analysis` | 使用稳定 ID 或精确名称与显式日期窗严格编译和执行；不解释 template/layout/favourite， 不从模糊引用选择第一个。 |
| <a id="segment-snapshot-composite"></a>`segment_snapshot` | 产品行为见 [Segment Snapshot v1](cli.md#segment-snapshot-v1)。 |
| <a id="segment-members-composite"></a>`segment_members` | 产品行为见 [Segment Members v1](cli.md#segment-members-v1)。 |
| <a id="analysis-default-dictionary-composite"></a>Analysis Default Dictionary (`analysis_default_dictionary`) | 只接受显式 App 或 `/app` binding，返回受治理的默认值字典。新增未登记键 按响应漂移处理，不能自动成为调用方配置。 |
| `analysis_context`、`analysis_template`、`monetization_detail`、`realtime_event_catalog`、`metadata_sync` | 其他 Analysis |
| `app_snapshot`、`attribution_snapshot`、`attribution_performance`、`attribution_user_detail` | App / Attribution |
| `title_package`、`bilibili_account_performance`、`advertiser_profile` | 其他 Material / Promotion |
| `company_usage`、`report_directory`、`report_subscriptions`、`custom_audience` | 其他 Reports |
| `kanban_mutation`、`custom_metric_mutation`、`metadata_template_mutation` | Governed mutation |

Plan `schema` 当前不枚举这张表的全部成员，因此每次升级后以运行时 dry-run 为最终接收判据。

## 宿主生成 Plan 的效果边界

普通调用方提交 `gravity.plan.v1` 走 `execute_plan`。把 tool result 与宿主模型放在同一上下文时，使用
`execute_host_plan(sdk, host_plan, sources)`；来源表由模型外宿主建立。tool result 只能是 data，
operation/path 等控制身份来自 SDK contract 或用户 instruction，对象/目的地/permission/confirmation
来自用户 instruction 或 authorization。

Mutation preview 绑定规范化 Plan/request digest；execute 还需用户确认相同 preview fingerprint。
模型不能创建或改写来源表。可选 prepared-plan 只为 `from_env()` 的 read-only stable `run` host Plan
保存私有限时绑定，执行仍重入同一来源边界。

### Prepared Analysis Plan

Prepared Analysis Plan 是 Plan-backed 路径可选的私有、不可变 Artifact，不适用于 Direct Composite，
也不建立新 executor、binder 或 scheduler。其字段真相由
`gravity.prepared-analysis-plan.v1` schema 拥有；公开面只暴露 opaque ID 与安全摘要。

prepare 必须绑定 source authority、identity、输入、合同 fingerprint、digest、expiry 与 stale 条件；
execute 重新进入原 `execute_host_plan` 或同等 source-aware owner。tamper、expiry、identity、contract
或 catalog 漂移必须在目标调用前失败。PAP 不改变现有请求数、完整性、错误、隐私或输出形状，禁用
后直接回到原 source-aware 路径，不留下第二条公开路由。

## metric-anomaly-localization@1

```powershell
gravity analysis playbook schema
gravity analysis playbook run --input anomaly.json --dry-run
gravity analysis playbook run --input anomaly.json --output result.json
gravity analysis playbook run --input changed.json --checkpoint result.json --output resumed.json
```

Playbook 使用现有 composite 组成固定 DAG，不新增 node kind。checkpoint 绑定 definition、规范化输入、
步骤输入和结果 fingerprint；变化只复用未失效且仍匹配的步骤。任一步 partial/gap/error/skipped/empty，
或 identity/数值/slice 不一致时，结论保持 `evidence_incomplete`、`conclusion=null`、
`allowed_claims=[]`。

## Effect 边界：Segment mutation 不进入 Plan v1

Segment create/update/refresh/delete 需要人工确认、执行时 preimage、写后 readback 和一次性授权，不是
可安全重放的数据节点。调用方使用 CLI/SDK direct mutation 或 Action Plan；缺少普通 Plan node 不减少
该任务的可完成性，也不能推广为其他未登记写的豁免。

## Workspace 参数化 Plan

Workspace 可在 `plan_recipes.<name>` 保存完整 literal Plan，并把变化的 request scalar 叶子声明为 typed
参数：

```powershell
gravity plan run --recipe example --param date=2026-08-14 --param app=main --dry-run
gravity plan run --recipe example --param date=2026-08-14 --param app=main
```

参数 binding 使用 RFC 6901 pointer，只替换已存在的非空 scalar，不做字符串插值，也不能改变节点、
依赖、foreach、budget 或 limits。展开后仍进入同一个 `validate_plan` 和执行器。完整 TOML 形状见
[Workspace 参考](workspace.md#参数化-plan)。

## 失败与结果

Plan 失败结果 `result=null` 并使用结构化 ErrorDetail。绑定失败为 `BINDING_FAILED`；依赖失败的下游为
`skipped/DEPENDENCY_FAILED`；独立 sibling 继续。adapter 输出超过节点 item bound 时返回
`PAGINATION_LIMIT` 与稳定 stage/cause。未知 adapter 异常使用脱敏 `PLAN_ADAPTER_EXCEPTION`，不暴露
异常文本或请求值。

顶层退出优先级为 local `4` > upstream `3` > caller `2` > success `0`。支持 partial 的 adapter 保留
安全结果但节点仍失败；调用方不能因为 `result` 非空就忽略状态。通用状态和 fail-closed 行为见
[机器契约索引](cli.md#result-and-errors)。
