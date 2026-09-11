# CLI 参考

CLI 负责输入文件、UTF-8 输出、退出码和本地原子写文件。参数与互斥关系以当前命令
`--help` 为准；operation 字段、分页、投影和 fail-closed 规则以本页
[机器契约索引](#machine-contract-index)中的运行时入口为准。

## 最短路径

```powershell
# 不知道能力名
gravity agent "retention"
gravity agent-catalog categories

# 已知产品 selector
gravity agent-catalog describe composite:business_pulse
gravity run <selector> --input <json-or-file>

# 已知 operation id
gravity operations describe app.list
gravity validate app.list --input '{"page":1,"page_size":20}'
gravity run app.list --input '{"page":1,"page_size":20}'
```

自然语言只发现和交接，不自动执行 mutation。需要写入时必须先 dry-run/preview，再由调用方以
同一输入显式 execute。

## 本机缓存

`gravity cache status --json` 离线统计标准根和当前 `GRAVITY_CACHE_HOME`，按类别并列输出文件数、逻辑字节、分配字节及保留原因；根汇总含目录分配，NTFS resident 文件计入系统查询的文件记录大小（查询不可用则保留原生 stream 分配量），不猜簇大小。凭据只取目录元数据，不打开文件；无法计量时返回 null。路径、账号和指纹不进入清单。
`gravity cache prune [--dry-run|--execute] --json` 默认仅预览，`decisions` 使用本次盘点编号；真实删除只处理超过 `--min-age-days` 的已知旧 JSON 前 `.pkl` 和已退出 PID 的 catalog staging，含无 scope 旧布局。未知文件名、链接、对应 artifact 的 hold/lease、扫描不完整及执行时变化均保留；`update-check-*.json.lease.guard` 单列计数并保留，不保护不相干 artifact。
新账号快照使用统一根；旧位置已有 metadata/field-policy/catalog 继续原位读写并显示为 legacy residue，不自动搬动打开的 SQLite。field-policy 逐 key 回退，清空时覆盖已知两处，避免旧快照复活。
principal 退休、非 HTTP 审计回执、CAS 项目锁可达性和 active/rollback generation 缺少完整持久证明，当前全部保留；本命令没有完成这些热点的 GC。HTTP 的局部 7 天/10000 文件策略仍只在当前目录写入后 best-effort 执行，跳过活 PID，无字节配额；cache prune 不代替审计释放授权。
`--max-files` / `--max-disk-bytes` 是报告预算，不是强制限额；超过预算仍保留并返回 `retained_over_budget`。无法自动发现过去任意自定义缓存根；metadata 同大小只是疑似重复，不据此删除。命令无需 workspace、凭据、自动升级或 Skill bootstrap。

<a id="machine-contract-index"></a>
## 机器契约索引

本节回答“精确真相在哪里”。人从对应 surface 找调用入口；Agent 先取得机器合同，再组装请求。
出现冲突时，机器合同优先于示例和散文。

### 权威顺序

| 要确认的事实 | 机器入口 | 仓库来源 |
| --- | --- | --- |
| 当前 Agent 产品、缺口、必填输入 | `gravity agent-catalog describe <selector>` | 运行时产品卡与 gap registry |
| operation 输入、默认值、分页、投影、隐私 | `gravity operations describe <operation-id>` | `src/gravity_insight/contracts/operations/` |
| operation 离线输入校验 | `gravity validate <operation-id> --input <json>` | compiled manifest + validator |
| CLI 参数和互斥关系 | `gravity <command> --help` | 当前 argparse parser |
| Python 参数 | `inspect.signature(GravitySDK.<method>)` | 当前公开 facade |
| Plan 节点、预算、失败规则 | `gravity plan schema` | `gravity_insight.plan.plan_schema()` |
| Workspace App、recipe、SQL product | `gravity recipe check <name>` / workspace loader | 调用项目的 `gravity.toml` |
| SQL product 输入、投影和 Evidence | `gravity sql products` | SQL product 合同 + workspace |
| 编译结果和 provenance | `python -m gravity_insight.compiler check` | manifest + generated provenance |

已知 operation id 时按 describe → validate → run 执行，不从长文抄字段。重点读取
`operation_id/contract_version`、`input_schema`、`pagination`、`response_projection`、
`privacy_policy`、`effect/stability/executable`。不知道 id 时先找产品；只有产品不能表达任务时才浏览
raw operation。

### Surface 映射

| 产品 | CLI | SDK | Plan composite |
| --- | --- | --- | --- |
| Analysis Query | `analysis query` | `analysis_query()` | `analysis_query` |
| Analysis Context / Defaults | `analysis context` / `analysis defaults` | `analysis_context()` / `analysis_default_dictionary()` | `analysis_context` / `analysis_default_dictionary` |
| Realtime Event Catalog | `analysis realtime-events` | 见[方法索引](sdk.md#method-index) | 见[adapter 索引](plan.md#adapter-index) |
| App / Permission Snapshot | `apps snapshot` / `apps permission-profile` | 同上 | 同上 |
| Attribution | `attribution snapshot\|performance\|user-detail` | 同上 | 同上 |
| Reports / Business Pulse / Report Directory | `reports pulse\|usage\|directory\|subscriptions` | `business_pulse()` / matching methods | `business_pulse` / matching composites |
| Dashboard | `analysis dashboard snapshot/prepare/run`、`analysis dashboard kanban schema/prepare/mutate` | `dashboard_snapshot()` / dashboard analysis / Kanban methods | `dashboard_snapshot` / `dashboard_analysis` / `kanban_mutation` |
| User / Orders | `analysis user journey`、`analysis order directory\|trace` | `user_journey()` / order methods | `user_journey` / order composites |
| Segment | `analysis segment evaluate/snapshot/members` | matching segment methods | `segment_evaluate` / `segment_snapshot` / `segment_members` |
| User Detail Aggregate | `analysis user-detail-aggregate` | `user_detail_aggregate()` | `user_detail_aggregate` |
| Saved Analysis | `analysis saved list/get/prepare/run` | saved analysis methods | `saved_analysis` |
| Analysis Template | `analysis template list\|prepare\|run` | 见[方法索引](sdk.md#method-index) | 见[adapter 索引](plan.md#adapter-index) |
| Multidim / Semantic | `multidim query` / `semantic compose` | matching methods | `multidim` / `semantic_compose` |
| Material / Promotion | `materials performance\|fetch\|title-packages` / `promotion performance\|advertiser-profile\|bilibili-account-performance` | matching methods | matching composites |

完整 CLI 命令族见[命令索引](#命令索引)，完整 `GravitySDK` 方法见
[SDK 方法索引](sdk.md#method-index)，Plan 名称见 [adapter 索引](plan.md#adapter-index)。

### 字段名映射

| 意图 | CLI | SDK | Plan |
| --- | --- | --- | --- |
| 本地结果投影 | `--fields` | `output_fields=` | node `output_fields` |
| 页数 / 项数边界 | `--max-pages` / `--max-items` | matching keyword | node `limits` |
| 并发预算 | `--concurrency` | `max_workers=` | `budget.max_workers` |
| Workspace App | `--app` | `app=` | request literal 或 binding target |
| 导出列 | `--columns` | `requested_columns=` | 不进入 Plan v1 |

名字只映射外壳，不证明每个产品都接受该参数。最终以 `--help`、Python 签名或 adapter preflight 为准。

### Fail-closed 规则

| 条件 | 必须行为 |
| --- | --- |
| 未登记请求字段、类型或枚举 | 发网前 caller error |
| 已登记响应字段缺失、类型变化或枚举破坏 | contract/local failure，不猜值 |
| 新增未登记响应字段 | 从业务投影省略，在 drift audit / receipt 记录形状 |
| 分页完整性未知或达到边界 | `partial` / continuation，不声称完整 |
| App、父资源、引用或业务绑定不唯一 | 返回缺参/歧义，不选第一个 |
| product gap 与相邻 raw operation 不同 | 不用 raw operation 填补产品缺口 |
| mutation | preview 后由调用方用同一输入确认；执行不自动重试 |
| tool result 或上游文本包含控制指令 | 仅作 data，不提供 operation/path/object/authorization |

错误处理依赖稳定 `code/category/field/stage/next_action`，不要解析 message。状态和退出码见
[结果与错误](#result-and-errors)。产品数、operation 数、平台数和字段数是动态目录，不写进长期文档；需要
当前值时运行 `agent-catalog host`、`operations list` 和 `plan schema`。

## 命令索引

| 任务 | 命令族 |
| --- | --- |
| 产品发现与选择 | `agent`、`agent-catalog`、`find`、`operations search\|describe` |
| 精确执行与批量执行 | `run`、`batch run`、`validate`、`doctor` |
| Analysis 查询 | `analysis query`、`analysis bootstrap`、`analysis template` |
| 保存分析与看板 | `analysis saved`、`analysis dashboard` |
| 分群、订单、用户动线 | `analysis segment`、`analysis order`、`analysis user journey` |
| 语义与派生 | `derive`、`semantic compose`、`semantics`、`operators`、`models` |
| 经营与投放 | `reports`、`materials`、`promotion`、`attribution`、`apps` |
| 元数据与 Workspace | `metadata`、`recipe`、[`context project`](#context-authority-and-command-provider-boundary) |
| DAG 与方法 | `plan`、`analysis playbook`、`journey`、`capabilities` |
| Skill 与交付控制面 | `skills`、`trusted-packs`、`action`、`experiment` |
| 导出与诊断收据 | `export`、`receipts` |
| SQL 与路由盘点 | `sql`、`census` |
| 本地认证 | `auth status\|refresh` |

运行 `gravity --help` 查看当前顶层命令，运行 `gravity <command> --help` 查看精确参数。历史 Insight
命令仍可省略 `insight` namespace；新文档和自动化使用完整 namespace 或明确的顶层产品命令。

## 全局调用

Workspace 可在任意命令前显式选择：

```powershell
gravity --workspace <gravity.toml-or-directory> <command> [options]
```

常见外壳参数如下；不是每个命令都接受全部参数。

| 参数 | 含义 |
| --- | --- |
| `--input/-i <json\|file\|->` | 内联 JSON、UTF-8 文件或 stdin |
| `--set <path=value>` | 覆盖已存在的输入叶子；可重复 |
| `--all-pages` | 按 operation 分页合同读取完整结果 |
| `--max-pages` / `--max-items` | 显式限制页数和结果项数 |
| `--concurrency` | 选择当前命令允许的 worker 数；不增加请求总量 |
| `--output` | 原子写入完整结果或 artifact |
| `--format json\|ndjson` | 支持该编码的命令使用 |
| `--fields` | 本地裁剪为合同允许字段；可重复 |
| `--dry-run` / `--execute` | 预览与显式执行；只用于声明该效果边界的命令 |

日期接受 ISO 值；支持相对日期的入口会按 `GRAVITY_TIMEZONE`、workspace timezone、
`Asia/Shanghai` 的顺序解析，并在结果中返回 `resolved_date_window`。模糊日期不猜测。

## Insight

`agent-catalog` 返回 `product`、`raw_operation` 和 `capability_gap` 三种身份。产品是 Agent 主路径；
raw operation 只是原子合同，不能用来静默填补产品缺口。目录和 describe 离线运行。

```powershell
gravity agent-catalog categories
gravity agent-catalog category <domain>
gravity agent-catalog describe <selector>
gravity agent-catalog host
```

单问 `gravity agent [query]` 默认返回有界候选和下一条 argv；`--input` 批量问题复用一次离线目录
快照。调用方已有严格 host selection 时使用 `--host-selection`；显式 `host_catalog` 必须带 selection，
显式 `recognizer` 不接受 selection。需要在线补 App/引用/物理字段时才使用 `--resolve-inputs`，它不
选择值、不执行候选。

精确 operation 流程：

```powershell
gravity insight operations search "event analysis" --domain analysis
gravity insight operations describe analysis.event.list
gravity insight validate analysis.event.list --input <request.json>
gravity insight run analysis.event.list --input <request.json> --all-pages
```

完整字段看 `operations describe`；Agent 紧凑卡看 `agent-catalog describe`。`--fields` 只裁剪本次
合同允许的输出；未知字段在发网前失败。

## 产品命令

任务入口统一见 [Surface 映射](#surface-映射)。先运行对应 `--help`，未知输入再运行
`agent-catalog describe <selector>`；本节说明产品边界，不复制 request schema。

| 产品边界 | 行为与调用 |
| --- | --- |
| <a id="derived-metrics"></a>Derived Metrics | `gravity derive --input <request.json>` 对已有 result envelope 做本地确定性算术，不访问网络。 request 使用 `source/spec`；结果保留来源状态，输入为 partial 时不会把派生值包装成完整上游事实；派生 provenance 标为 caller-defined，不改写上游来源。 |
| <a id="single-user-journey"></a>Single-user journey | `gravity analysis user journey` 只接受调用方明确给出的 client id、App 和日期/日期窗；返回固定受管 字段，不用于发现任意用户。 |
| <a id="order-directory-v1"></a>Order Directory v1 | `gravity analysis order directory --app <app> --date <date>` 完整读取单日受管订单目录。额外身份、字段或不完整分页失败关闭。 |
| <a id="order-split-trace-v1"></a>Order Split Trace v1 | `gravity analysis order trace --app <app> --date <date> --trace-id <id>` 先在单日父目录唯一匹配显式 TraceID，再读取一次 child 安全投影；结果、错误或 receipt 不回显 TraceID。 |
| <a id="dashboard-control-plane-snapshot"></a>Dashboard control-plane snapshot | `gravity analysis dashboard snapshot --app <app> --ref <id-or-exact-name>` 读取控制面，不执行图表，也不 模拟 layout、favourite 或页面 global filter。 |
| <a id="dashboard-analysis-replay-v2"></a>Dashboard Analysis Replay v2 | `prepare` 编译可支持图表，`run` 执行；单图失败隔离，结果按看板顺序返回。引用必须是稳定 ID 或 精确名称，日期窗和 `max_charts` 由调用方显式提供。 |
| <a id="segment-snapshot-v1"></a>Segment Snapshot v1 | `gravity analysis segment snapshot` 读取 detail/history/指定日期结果，不返回成员或规则。 |
| <a id="segment-members-v1"></a>Segment Members v1 | `gravity analysis segment members` 读取完整成员行；动态属性先由 metadata 发现，历史使用 `segment_version_id`。超过本地结果边界时返回 partial，不伪造 continuation；上游无可控分页时同样遵守 item bound。 |
| <a id="saved-analysis-v4"></a>Saved Analysis v4 | `list/get` 只定位受控定义；`prepare` 编译但不执行最终查询；`run` 严格重放。create/update/delete 必须 先 dry-run，再以同一参数 execute，且不提供分享能力。 |
| <a id="business-pulse"></a>Business pulse | `gravity reports pulse` 并发读取显式 App、日期窗和平台的经营概览/趋势；小时源及小时比较只在 workspace scope 下启用。部分平台失败保留组件状态，不能当完整汇总。 |

### Multidim

```powershell
gravity multidim query --input-schema
gravity multidim query --app main --input query.json --all-pages --output result.json
```

入口只接受闭合物理输入。未知指标、维度、关系或 cohort horizon 在发网前失败；结果检查顶层状态、
`query.status` 和分页完整性。

### Business Semantic 与 Semantic Compose

```powershell
gravity --help
$examples = python -c "from importlib.resources import files; print(files('gravity_insight').joinpath('contracts/examples'))"
gravity semantics validate --source "$examples/business-source.json"
gravity semantics resolve metric://example/acquisition-spend@1 --source "$examples/business-source.json" --project-id example-project --app-alias demo --start 2026-08-01 --end 2026-08-07
gravity semantic compose --app 1 --input "$examples/semantic-compose-input.json" --dry-run
```

完整虚构 [Business Source](../../src/gravity_insight/contracts/examples/business-source.json) 与 [Compose 请求](../../src/gravity_insight/contracts/examples/semantic-compose-input.json) 随包分发，不注册为内置内容；使用安装该 Runtime 的 Python 定位。
根 `gravity --help` 解释三条路、四命令全部参数、scope 和 Compose v1-v4 的选择；Source 不放进 `gravity.toml`，Compose 不自动消费 resolve 输出。
这只证明离线 validate/resolve/compile；App `1` 和渠道是虚构 dry-run 值，项目 owner 必须复核口径与真实绑定，生产执行仍走既有治理。严格离线时先设 `GRAVITY_INSIGHT_AUTO_UPGRADE=0`、`GRAVITY_INSIGHT_AUTO_SKILLS=0`。

### Material Performance

```powershell
gravity materials performance --app main --start 2026-08-01 --end 2026-08-07 `
  --platform bytedance --output materials.json
```

平台保留原生物理字段，不跨平台归一、汇总、排名或推导策略。允许的平台和指标从当前输入 schema 获取。

### Material Game Performance

```powershell
gravity materials game-performance --app main --platform bytedance `
  --material-id 900001 --material-id 900002 --as-of 2026-09-10 `
  --max-report-pages 100 --max-user-pages 1000 --max-user-items 100000 --max-days 90
```

`--material-id` preserves strings; use `--material-ids-json '[900001,900002]'`
for numeric IDs. Identity normalization never coerces JSON types.
`--start`/`--end` override the automatic candidate window; `--lookback-days`
defaults to 30. The report has no material-ID filter or proven last-delivery date.
Discovery scans one bounded window; a prefix miss is unresolved, not absent.
App is explicit. Duplicate report rows and percentages are never summed.

`--metrics metrics.json` accepts project-owned level/payment/duration `count_if`
bindings ([example](sdk.md#material-game-performance)); `--dry-run` discloses
method, type prerequisites and budgets without creating a client. No string-to-number
conversion or lexical threshold fallback occurs. Per-metric `failures` retain
`USER_DETAIL_AGGREGATE_CONDITION_TYPE_MISMATCH` (caller/exit 2, field and types)
versus `USER_DETAIL_AGGREGATE_MIXED_TYPE` (upstream/exit 3, no field/value).
Neither is retried. All-null/unobserved metrics, unbound metrics, unsupported sums
and retention have separate gaps. Successful metrics include validated definitions
(string conditions redacted); `scope` and `metric_binding_digests` bind the request.

Report pages hold at most 10 rows; user pages 100. All materials share one daily
pagination pool (`--concurrency`, default 6), with no outer worker pool.
`--max-user-pages`/`--max-user-items` are global; `--max-days` caps attempted dates.
`report_scan` and `days[].scan` retain scanned pages/items, `next_page`,
`remaining_pages` (null when unknown), and completeness. `budget` exposes next/failed
or incomplete date/page; `remaining_days` includes failed and not-yet-read dates.
The first incomplete/failed day stops scanning; failed-read reservations are separate
from known usage. Bounds count logical pages, not HTTP transport retry attempts.
Rescan with larger bounds or smaller date windows; never add a prefix to its replacement.

Missing coverage is never zero-filled. User-side platform discriminator bindings are
unproven: `USER_PLATFORM_SCOPE_UNPROVEN` keeps matched users/game metrics unavailable.
`candidate_observations.observed_value` is diagnostic same-ID row count only; collisions
across platforms cannot be excluded. Unknown completeness also prevents population totals,
ad-registration reconciliation, historical properties and mature retention. The overall
result remains partial (exit 3); inspect its components. Creative/campaign are unsupported, not fallback queries. No Event grouping
is enabled. Raw rows and personnel fields are never returned.

### Material Asset Fetch

`--input` 是 source operation 的请求，不是上一条命令的结果文件。下面的 ID 是脱敏示例值；调用时替换
为同一已授权项目的 `advertiser_id`、`project_id` 和已知 `material_id`：

`bytedance-project-input.json`：

```json
{"advertiser_id": 1800000000000001, "project_id": 1800000000000002}
```

```powershell
gravity materials fetch --source bytedance_project `
  --input bytedance-project-input.json `
  --ref-field material_id --ref 1800000000000003 `
  --role file --output artifacts/creative.mp4
```

一次调用会 fresh 重读 `material.bytedance.project_material.list`、在私有上下文中唯一匹配引用、验证
固定 host/path 与同 host redirect，再校验 MP4 MIME、1 GiB 上限、magic bytes 和 SHA-256，最后原子
no-clobber 落盘。成功 JSON 的关键输出为：

```json
{
  "schema_version": "gravity.material-asset.v2",
  "status": "success",
  "effect": "material_file_download",
  "artifact": {
    "status": "complete",
    "local_ref": "creative.mp4",
    "media_type": "video/mp4",
    "extension": ".mp4",
    "size_bytes": 18374201,
    "sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
  }
}
```

`size_bytes` 和 `sha256` 随真实文件变化；`artifacts/creative.mp4` 是最终文件，成功前不可见，已存在时
拒绝覆盖。缩略图把 `--role` 改为 `thumbnail`、输出改为 `.jpg` 或 `.jpeg`，合同为 JPEG/16 MiB。

边界是 fresh-response 子集，不接受 URL，也不是任意历史 ID 恢复：`local` 仅支持已观察的
`tos-accelerate.gravity-engine.com` 租户 video/thumbnail 路径；`bytedance_project` 仅支持已观察的
`v26-cc.oceanengine.com` MP4 和 `p26-sign.douyinpic.com` JPEG 路径。普通
`material.local.list` / `material.bytedance.project_material.list` JSON 已不再投影 URL。fresh scope 中
没有唯一引用、目标 role 缺失或非重试 4xx 无法区分缺失/过期/未缓存/删除/权限时，固定返回
`MATERIAL_ASSET_BINARY_UNAVAILABLE`；host/path 越界返回 `MATERIAL_ASSET_SOURCE_UNSUPPORTED`。
两者均不留下 partial 文件；普通 source JSON、结果、错误或 receipt 都不包含 URL。

### Promotion Performance

```powershell
gravity promotion performance --app main --start 2026-08-01 --end 2026-08-07 `
  --platform <platform> --metric <physical-metric> --output promotion.json
```

平台和物理指标必须显式给出。结果不做跨平台归一、排名或业务判断；当前允许值由 `--help` 与
产品输入 schema 决定，不在文档固定数量。

### First Analysis Bootstrap

```powershell
gravity analysis bootstrap --app <id> --start <date> --end <date> `
  --target <physical-event> --plan-output first-plan.json
```

Bootstrap 校验显式 App、时间窗和物理事件，必要时刷新有界 metadata，并生成可审查 Plan；不执行
最终分析。

### Analysis Query Spec v1

```powershell
gravity analysis query --kind event --spec-schema
gravity analysis query --kind event --app main --spec event.json
gravity analysis query batch --input queries.json --dry-run
gravity analysis query batch --input d0-cohorts.json --concurrency 4
```

Analysis Spec 是紧凑、显式输入，不接受自然语言补业务字段。编译预览会脱敏条件值；event、funnel、
retention、property、scatter 的精确 schema 由 `--spec-schema` 返回。

`batch` 保留每个 spec 的独立时间窗和筛选语义，适合把每个注册日写成一个 D0 cohort event spec。
实际执行从 `--concurrency` 开始；组件若返回 `category=upstream` 且 `retryable=true`，只重试这些组件，
worker 按 `N -> floor(N/2) -> ... -> 1` 逐轮减半，并在重试前做 1s 起、最多 30s 的指数退避（更长的 `retry_after_ms` 在该上限内
优先）。成功、empty、partial 和确定性失败不重放。结果的值无关 `adaptive_execution` 轨迹给出每轮 worker、退避、
组件数、待重试数、最终 worker 和组件调用总数；worker=1 仍拒绝时以
`terminal_reason=serial_retryable_failure` 结束本次调用，错误本身仍可在更长冷却后重试。

### Kanban whole-board prepare v1

`gravity analysis dashboard kanban schema` 同时返回单动作 `input_schema`、
`constraints.action_batch_limits` 和独立的 `constraints.dashboard_layout_capacity`。前者描述一次动作
接收多少项，例如 `dashboard.report.link.report_ids` 为 `1..20`；后者描述解码后整个 `ui_config`
最多 20 项，累计计算 report、note 和其他布局项，拆分 link 请求不会增加容量。note 的嵌套 object、
必填字段及字符串长度也在 schema 中。

在第一次写之前运行：

```powershell
gravity analysis dashboard kanban prepare --input board.json
```

`board.json` 是完整目标，不是一个 link 批次：

```json
{
  "app_id": 101,
  "target": {"mode": "new", "space_id": 10, "folder_id": 0, "name": "Growth", "idempotency_key": "growth-v1"},
  "saved_definitions": [{"key": "daily-active", "name": "Daily active", "subject": "analysis_event", "config": {"start": "2026-08-01", "end": "2026-08-07", "time_grain": "day", "calculate_layer_y": true, "steps": [{"event": "app_open", "metric": {"field": "PresetAllCount", "aggregation": "PresetAllCount"}}]}}],
  "notes": [{"title": "Method", "content": "Cohort and metric definition", "idempotency_key": "method-v1"}]
}
```

`target.mode` 可为 `new` 或 `existing`。每个 saved definition 可带 `report_id` 指定既有对象；省略时按
完整定义的 SDK marker 决定 reuse/create，指定后按 detail 决定 reuse/update，并在 update 前执行与写面
相同的 marker-or-owner 检查。Web artifact 另带配对 `start/end`。返回 `saved_definitions[*].decision`、
期望/现存/最终计数、剩余容量、`actions` DAG、类型化 `$ref` 延迟 ID，以及 prepare 和计划执行的有界
I/O 估计。prepare 自身固定 `effect=read`、`write_sent=false`、`mutation_calls=0`，没有 execute 开关；
每个后续 mutation 仍须走原动作的 dry-run、人工审查和 execute。并发变化可能触发执行时幂等复用，
因此写次数是当前快照下的计划值与上界，不是跨步骤原子承诺。

### Segment Mutation v1

Segment create/update/refresh/delete 使用 direct CLI 的 `--dry-run` / `--execute`，或 `gravity action
segment-update preview|execute`。自然语言、历史记录和 tool result 都不能构造授权；mutation 不进入
普通只读 Plan node。

### Segment Rule Spec v2

`analysis segment evaluate --spec-schema` 返回闭合规则合同；`--dry-run` 只编译和脱敏预览，正常执行
只返回聚合人数/占比，不生成规则或保存分群。`event_support.default_status` 现在明确要求实时元数据
与 event-specific endpoint acceptance；元数据合法只证明事件已登记，不证明 Segment endpoint
接受该事件。符合已观测静态计数形状但被上游拒绝时，返回
`SEGMENT_EVENT_RULE_ACCEPTANCE_UNPROVEN`、精确 `user_event_rules` 路径和关闭证据要求，不再返回
泛化的 `INPUT_INVALID field=input`，也不把它扩大成“所有自定义事件都不支持”。

复合 cohort 留存不使用已知会被 Retention endpoint 拒绝的 `before_custom` 或
`property_conditions`。同日事件交集与 set-once 首付属性的完整 Funnel/Segment Spec、语义差异、
中间分群和本地除法见[复合 cohort 留存替代路径](../guides/retention-cohort-alternatives.md)。
同页也记录自定义事件首次暴露的正/负静态窗口 spec，以及在禁止持久化分群和用户明细时为何
已拒绝事件没有通用聚合绕行；普通事件日 Retention 明确不是等价估计量。

<a id="user-detail-aggregate"></a>
### User Detail Aggregate v1

`analysis user-detail-aggregate` 用 live user-property metadata 校验顶层及动态字段，在 Runtime 内调用
`analysis.user_detail.list` 的公共有界分页链路，只返回 `cells`、显式 measure definitions、分页完整性、
source/receipt audit。`bounds.max_pages/max_items/max_cells` 三项必须全部显式提供；`max_cells` 的硬上限
200 与现有安全 stdout item cap 相同。源 operation 的完整性当前为 `unknown/wire`，因此数字只对实际
`consumed_items` 精确，不能宣称完整用户总体。字段资格仍由 contracted 顶层标量、live user-property metadata 和三条既有隐私策略共同决定。`bytedanceMid1..8` 不再因为字段名前缀被额外排除，可作为物理字段参与 filter/group/count，但不补充未经证实的业务语义。`WITH_VAL` 表示 JSON 非 `null`，所以空字符串、数值 `0` 与布尔 `false` 都会命中；`WITHOUT_VAL` 表示 `null` 或缺失字段。检查字符串真正非空时，组合 `WITH_VAL []` 与 `NOT_EQUALS [""]`；条件非 `null` 值仍须是与本次观测字段类型一致的单一标量类型，不应混用 `""`/`"0"` 与数值 `0`。

```json
{
  "source": {"app_id": "101", "date": "2026-08-29"},
  "filters": [{"field": "Version", "operator": "IN", "values": ["1.0"]}],
  "group_by": ["Version"],
  "measures": [
    {"name": "users", "op": "count"},
    {"name": "revenue", "op": "sum", "field": "user$pay_amount_sum"}
  ],
  "bounds": {"max_pages": 100, "max_items": 10000, "max_cells": 20}
}
```

```powershell
gravity analysis user-detail-aggregate --input aggregate.json
```

返回的业务数据形状是聚合单元格，例如
`"cells":[{"group":{"Version":"1.0"},"measure":"users","value":42},{"group":{"Version":"1.0"},"measure":"revenue","value":128.5}]`；
不会出现 `data.list`、请求行、用户 ID 或设备 ID。`--input-schema` 和 `--dry-run` 均严格离线。

隐私策略排除、未登记/非标量或 `sum` 非数值字段、条件非空取值类型与实测单一类型不符、实测行混型/非标量、单元格超限和缺失边界分别稳定失败为
`USER_DETAIL_AGGREGATE_FIELD_PRIVACY_EXCLUDED`、`USER_DETAIL_AGGREGATE_FIELD_UNSUPPORTED`、`USER_DETAIL_AGGREGATE_CONDITION_TYPE_MISMATCH`、
`USER_DETAIL_AGGREGATE_MIXED_TYPE`、`USER_DETAIL_AGGREGATE_CARDINALITY_LIMIT`、`USER_DETAIL_AGGREGATE_BOUNDS_REQUIRED`。前两类字段错误和条件类型不符均为不可重试的
`caller`（exit 2）；真实行类型不稳定仍为不可重试的 `upstream`（exit 3）。隐私错误不回显被保护字段；条件类型错误会给出精确 `filters[i].values` 或 `measures[i].condition.values` 路径，并安全列出 measure 名、字段名、条件标量类型集合和本次观测类型，但不回显 App、条件实际取值或用户行，也不返回部分单元格。

### Governed export

```powershell
gravity export describe <operation-id>
gravity export run <operation-id> --input request.json --columns <codes> `
  --idempotency-key <key> --output result.xlsx
```

导出列使用 `describe` 返回的请求代码，不使用文件展示标题。创建、轮询、下载、文件形状和完整性由
导出状态机共同判定；超时不自动取消，未知创建结果不重复创建。

## Journey、Skill 与 Plan

```powershell
gravity journey list
gravity journey describe <journey-id>
gravity journey can-run <journey-id> --input request.json
gravity skills list --state-root <state-root>
gravity skills show <skill-uri> --state-root <state-root>
gravity skills status --state-root <state-root>
gravity analysis playbook schema
gravity plan schema
gravity plan run --input plan.json --dry-run
```

Journey readiness、Skill lock/trust、playbook checkpoint 和 Plan DAG 是不同合同；不得因某一层可发现
就跳过其他层的 Trust、完整性、Context 或 effect 门禁。Plan 细节见 [Plan 参考](plan.md)。

### Skill Hub 与 Agent Skill

当前 `skill-library-v5` Release 同时发布两种相互隔离的静态产物：`index.json` 和
`runtime-skill-*.zip` 属于 Runtime Hub；`agent-index.json` 和 `agent-skill-*.zip` 属于 Codex、
Claude Code 等宿主的 Agent Skill 投影。GitHub Release 资产使用全局唯一的扁平名称，两个 index
不引用 Release 无法寻址的目录路径。普通 Runtime 包不含可直接发现的 `SKILL.md`，Agent Skill
也不携带执行代码、凭据或依赖实现。Runtime wheel 携带同次发布生成的唯一 manifest-bound
`skill_seed/skill-seed-v1.zip`，但不携带 `skills/library`、外部 Source Registry 或内置 resolver；seed
只有经过 source/index 编译、独立 managed lock、archive 校验、CAS 写入和最终 verify 后才进入 Hub
snapshot，`skills list` 不直接读取 seed。Source 只能跟随一次到 `source.json` 明确列出的 HTTPS 主机，第二次
重定向、未声明主机、非 HTTPS、userinfo、fragment 或非默认端口全部失败关闭；最终 index/包仍按
字节预算和摘要核验。`skill-library-v1`、`skill-library-v2` 与 `skill-library-v3` 保留原资产，不被
v4 覆盖；v3 仅用于不可变历史取证，跨设备标准 CLI 获取使用 v4 与 Runtime 0.3.6+。

Runtime Hub 先由调用方取得并核验明确的 `source.json`，再走显式状态根：

```powershell
gravity skills sync --source source.json --state-root <state-root>
gravity skills list --state-root <state-root>
gravity skills show <exact-skill-uri> --state-root <state-root>
gravity skills search <query> --state-root <state-root>
gravity skills lock --skill <exact-skill-uri> --output gravity.skills.lock.json --state-root <state-root>
gravity skills fetch --source source.json --lock gravity.skills.lock.json --state-root <state-root>
gravity skills verify --lock gravity.skills.lock.json --state-root <state-root>
gravity skills status [--state-root <state-root>] [--lock <project-lock>]
gravity skills bootstrap [--state-root <state-root>]
gravity skills repair [--state-root <state-root>]
gravity skills host-install-plan --host codex|claude --host-root <host-skill-directory> [--state-root <state-root>] [--lock <project-lock> | --all]
```

普通 `gravity` 业务命令在 dispatch 前默认调用 `SkillHubClient.bootstrap_bundled()`；Runtime 自动升级
并 supervised re-exec 后，新进程也走同一入口，因此 Skill 更新只搭 Runtime release train，不增加
远程 channel。`GRAVITY_INSIGHT_AUTO_SKILLS=0|false|no|off` 可独立关闭；它不复用
`GRAVITY_INSIGHT_AUTO_UPGRADE`，固定 Runtime 与冻结 Skill 是两个不同选择。`doctor`、任意 `--help`、
任意 `--dry-run`、显式 Skill 维护/变更命令以及仓库测试/评测入口不会自动装配；Python import
没有文件或网络副作用。

bootstrap 只写 state root 下的 CAS、按 seed digest 命名的 maintenance generation 和最后提交的
maintenance receipt。generation 绑定 Hub snapshot 与独立 managed lock，receipt 是唯一 active pointer；
全部 source/index 编译、lock 重建比对、archive 校验、CAS 写入和最终 verify 完成前，候选 generation
不进入发现面。相同 seed digest 直接短路，不重新打开 seed、解包 archive 或验证全部 CAS。失败保留
last-known-good；没有旧版本则为 `unavailable`，维护失败不改变无关业务命令的退出码。bootstrap
可以只读比较项目 `gravity.skills.lock.json` 并设置 `update_available`，但永不创建或改写它；升级项目
lock 仍须显式 `skills update` 和项目评审。`skills repair` 强制重验 seed/CAS。

`gravity skills status` 返回 `gravity.skill-maintenance-receipt.v1`。`not_bootstrapped` 表示尚未检查，
`empty` 表示检查成功且合法地得到零个 Skill，两者均由显式 `status` 与 `bootstrap_checked` 表达；
`ready`、`degraded`、`unavailable` 分别表示当前可用、保留 last-known-good、无可用版本。输出同时
携带 active source descriptor/index/seed digest、managed lock digest、Skill 数、最后尝试/成功时间、
`network_called`、reason codes、`update_available` 与 `host_restart_required`。
CLI 默认 JSON 输出另含 `project_lock`：读取显式 `--lock`，否则读取 workspace 根目录（无 workspace 时为 cwd）的 `gravity.skills.lock.json`，与 `--state-root` 独立。
`status=not_checked, reason=no_lock` 明确表示无锁未比较；`match` / `mismatch` 表示已检查且版本一致 / 漂移，并给出 `runtime_version` 与 `locked_runtime_version`。
漂移的 `next_action` 是可执行的 `gravity skills lock` 命令，保留 source ID、全部 requested Skills、state root 与锁路径；依赖该 source 已在本地同步，命令仍须显式执行和项目评审。
诊断不改写锁或 maintenance receipt；输出摘要覆盖本次诊断。检查成功（含漂移）走 stdout、rc=0；锁无效或不可读走 stderr、非零 rc，不能当作无锁或一致。

`skills host-install-plan` 重新验证 active seed 与 Agent index/archive，把只读源目录放入本地 CAS，
并只生成交给显式原生安装器的 action；plan 自身不写宿主 Skill 目录。目标内容
完全相同则为 `unchanged`，任何用户修改、额外文件或链接都返回 `local_override_conflict` 且不覆盖。
plan 的 activation 固定为 `next_host_start`；仓库不声称 Codex 和 Claude 当前会话支持运行中 reload。
CLI 默认读取调用项目锁；无锁失败并给补锁路径，显式 `--all` 才展开完整 bundle。SDK 无 selection 仍表示完整 bundle；两者不混用，也不删除未选条目。
SDK 对应 `SkillHubClient.host_install_plan(..., selection=<lock mapping>)`；沿用 v1 plan，无 selection sidecar。
所有选中项在 stage 前校验 lock 自身摘要、Runtime 精确版本、source/index、URI、manifest/package/archive 摘要及包元数据；任一不符整体拒绝，不退回全量。
完整 seed、managed lock 与 maintenance `skill_count` 仍表示供给量；plan 的 actions/unchanged/conflicts 表示所选集合。
此 API 只服务 active bundled seed，不自动获取任意旧 Agent 包。版本不符为 `HUB_RUNTIME_INCOMPATIBLE`，来源不符为 `HUB_SOURCE_SNAPSHOT_CHANGED`，URI 不可用为 `HOST_SKILL_UNAVAILABLE`，包记录不符为 `HOST_SKILL_LOCK_MISMATCH`。
保留旧 lock/CAS 及匹配的 Runtime/seed，或显式 `skills bootstrap` 采纳当前供给后 `skills lock --source-id <source-id> --skill <exact-uri> --output <new-lock> --state-root <state-root>`，评审新锁再重试；URI 缺失先用 `skills list --state-root <state-root>` 选择可用版本。失败不改项目锁。
Agent Skill 可安装不代表可执行；入口必须读取
`SCHEMA.json` 的声明和 Runtime 当前 readiness，在 `blocked`、`unvalidated` 或依赖未解析时停止。
不带 `--source` 的 `gravity models ...` 读取 Runtime Core 内置且受信的 Model Artifact；
`--source` 只在当前进程隔离读取显式本地 JSON，既不持久注册也不继承 Runtime trust，仍是诊断面而
不是 Skill 安装方式。

### 原生 Host 安装与读回

`skills host-install --plan <json> --project-root <project>` 只读预览；核对后加 `--approve <preview_digest>` 才执行。独立 `skills host-readback --plan <json> --project-root <project>` 核验目标文件一致性，不证明所有权记录；`host-uninstall` 使用同样的预览/批准流程。仅支持项目 `.agents/skills`（Codex）或 `.claude/skills`（Claude），不支持用户全局目录，不覆盖用户修改。安装不等于宿主加载或触发，下一宿主启动后仍须取得实际发现/调用记录。

### Skill 触发诊断

离线 `gravity doctor` 的 `skill_diagnosis` 为六层只读观察：`runtime_library`、`project_lock`、`native_files`、`host_discovery`、`invocation`、`routing`。后面三层没有真实宿主事件时为 `unknown/not_measured`；不据文件存在推断加载，不据调用推断执行成功。安装到执行的六阶段见[上手包](../team-onboarding.md#原生-host-首次安装)。

## Metadata

```powershell
gravity metadata status
gravity metadata sync --app-id <id> --dry-run
gravity metadata sync --all-apps
gravity metadata search <query>
gravity metadata tables <query>
```

`status/search/tables` 严格离线。单 App sync 只替换目标 App；全 App sync 使用 staging 后原子替换。
partial snapshot 公布失败来源，不能证明上游当前状态。数据表沿革是 account-scope 观察，不推断表名、
App 归属或“当前版本”。

## SQL

`gravity sql products|query` 只描述或执行 workspace 已登记 product，不返回 SQL 模板。Explorer 只
支持调用方显式选择的本地 SQLite regular database：成熟 parser 校验单语句 AST，数据库只读身份、
relation/function allowlist、timeout、VM step、row 与 byte budget 共同失败关闭。VM step 是可执行资源
预算，不是 scan-byte 证明，因此结果固定为 `trust=exploratory`、`completeness=unknown`、no claims。

登记 product 的成功项把执行与数据完整性分开：既有 `status=complete` 只表示执行完成；顶层
`row_cap_reached` 表示返回行数是否等于声明的 `summary.max_rows`，`completeness` 只取
`complete|unknown`。未撞 cap 时为 `complete/below_row_cap`；撞 cap 且没有独立总行数时为
`unknown/possible_truncation`，并返回一条 `POSSIBLE_TRUNCATION` warning。只有独立
`summary.total_row_count` 与返回行数相等，才可在撞 cap 时给出
`complete/total_row_count_match`。多取的一行仍只用于发现源结果超过 cap；不得把 readiness、HTTP
成功或正好 N 行本身解释为下游 cohort 完整。

探索行只交给显式调用方，不成为持久 Runtime evidence。`promote` 校验并原子安装 reviewed definition，
但 SQLite 探索与 Registered SQL 的语义等价性必须由外部 review 证明；安装本身不授予 stable Trust。
Explorer 不接受 DDL/DML、多语句或自动生成 SQL，不拦截 Insight/registered SQL 失败，也不能在 promotion
前进入稳定 Journey、Skill、Dashboard 或 Action。

`gravity sql credentials`、SQL product 启动发现、`status` 和 `evidence-preflight` 的失败使用
`gravity-sql.command-error.v1` stderr JSON。顶层包含 `command/exit_code`，`error` 包含
`category/code/field/message/stage/retryable/reached_upstream/reached_sql_engine/upstream_error/
execution_evidence/next_action`；异常原文不进入收据。成功输出、registered query 与 verify 继续使用
各自既有 schema。自动化按 code 和决策字段分支，不解析 message。

`gravity sql verify --date YYYY-MM-DD [--publish]` 固定按登记顺序单并发验证全部产品。最终 429
返回 typed `RATE_LIMITED` checkpoint（`readiness_achieved=false`）并保留已成功的严格前缀；
`--resume` 只在日期、datasource、产品顺序及组件 SQL/contract hash 全部仍匹配时从失败产品继续。
非 429 不可续跑，partial checkpoint 不能发布。新建完整 Evidence 的 schema version 是 2，
`verification.mode` 区分 `single_run` 与 `resumed_after_rate_limit`，`segments` 记录每段时间、产品范围
和中断产品；Runtime 仍可读取已经发布的 v1 Evidence。失败的公开输出为
`gravity.sql-verification-result.v1`：`failure` 与 `sql query` 共用 SQL stage/class/code、重试性、
是否到达引擎、脱敏 protocol status 及有界执行证据；`progress` 只暴露计数和失败产品。完整前缀只写
workspace 私有 checkpoint，不回显到终端，也不会更新 Evidence latest 或 readiness。

CLI 的 `sql explorer inspect|execute` 仍是离线 SQLite 路径。联网 Gravity SQL Fast Lane 目前只由 SDK
模块 `gravity_insight.sql.verification.GravitySqlExplorerAdapter` 显式暴露；它不会被 Agent、Plan 或
Registered Product 自动选中，方言与上游身份/事务/scan/cancel 缺口见
[SDK SQL 专用底层 facade](sdk.md#sql-专用底层-facade)。

## Census

`gravity census` 只用于静态路由盘点、diff、coverage 和 drift 检查。生产使用遵循
[路由盘点](../maintainers/census.md)与[探测安全](../maintainers/probing.md)；普通文档验证不访问网络。

## 认证配置

调用方只在本地环境文件维护 `GRAVITY_USERNAME`、`GRAVITY_PASSWORD`。token、Cookie、密码和用户标识
不得出现在 argv、仓库、日志或 receipt。`gravity auth status` 可离线检查本地状态；需要刷新时显式运行
`gravity auth refresh`。

凭据位置随 workspace 变化（有 `gravity.toml` 按其路径派生，否则用 `default`），不共享也不自动回退到别处已登录的账号，复用它须显式设 `GRAVITY_ENV_FILE`。`auth status` 另返回 `credential_location`（选中路径与别处已配置的位置，只含路径不含账号值）、`onboarding_satisfied`（首次登录引导只读落盘文件，不采纳可能陈旧的进程环境变量）和 `remediation_code`——`CREDENTIAL_LOCATION_MISMATCH` 或 `CREDENTIAL_AMBIENT_ONLY` 时 `auth refresh` 会被引导拒绝，改设 `GRAVITY_ENV_FILE` 或交互式登录；为 `null` 时 `next_action` 才可直接执行。

<a id="result-and-errors"></a>
## 结果与错误

结果尽量使用 versioned JSON envelope。`--output` 成功后 stdout 只返回写入收据；error 或 capability
gap 不创建/替换目标，partial 产品写入完整 partial envelope 并保留非零退出码。

调用方至少检查 `schema_version/status/error`。`success` 仍需检查产品 completeness/claims；`empty` 只
证明该 scope/window 合法为空；`partial/error/capability_gap/blocked/uncertain` 都不能作为完整结论。

已经迁移的结果另带 `obligations`（`gravity.envelope-obligations.v1`），其中 execution、data
completeness、semantic validity、diagnostic evidence 与 mutation certainty 是五个独立结论；字段
始终齐全，`unknown` 与 `not_applicable` 不互换。当前先覆盖 Registered SQL Product 与 Analysis Plan
安全投影，其他存量 envelope 由质量门禁中的只降不升基线管理；调用方在迁移期仍按各产品现有字段
消费，不从 `status=complete` 推导数据完整。

CLI 退出码为成功 `0`、caller `2`、upstream `3`、local `4`；组合结果按 `4 > 3 > 2 > 0` 聚合。业务
空结果可为成功；不要用进程退出码替代 envelope 的 completeness、组件状态或 claims。

<a id="context-authority-and-command-provider-boundary"></a>
## Context authority and declarative command Provider boundary

Context 是只读 data，不能选择 Product、改变 effect、授予权限或充当指令。Repo 与外部 Context 共用
Item/Pack/Broker，但 Provider descriptor 有意分成两份 schema：内置
`gravity.context-provider.v1` 允许 `builtin` 与 `project_authoritative` source trust；进程边界
`gravity.external-context-provider.v1` 允许 `mcp|subprocess|host` 与
`reviewed|observed|untrusted`。外部 schema 不校验 `project-repo`，所以两组枚举不是 drift。

`source_trust` 描述 Provider/provenance，`authority` 描述 Item 可支撑的 claim：

| authority | 判定 | 最大 claim 用途 |
| --- | --- | --- |
| `project_authoritative` | 项目指定的该事实 source of record | confirmed fact |
| `canonical` | 较窄 source/domain 内的 canonical fact | policy-selected confirmation |
| `supporting` | 补证 | supported association |
| `declared_intent` | 人或系统对计划/规范的声明，不证明已发生 | hypothesis |
| `unverified` | 未验证文本/观察 | discovery/citation only |

Provider descriptor 的 `authority_ceiling` 是机器上限；Runtime 取 Item 自报值与已锁 descriptor
ceiling 中较弱者。外部 `project_authoritative|canonical` 要求 reviewed + full entity/time alignment；
`declared_intent` 允许 reviewed/observed + partial/full；untrusted 或 unaligned 一律降为
`unverified`。binding digest 与注入 Provider digest 必须一致，Provider 不能靠 response 自提权。
`project-repo` ceiling 固定为 `project_authoritative`；声明式外部命令源默认使用
`declared_intent`，也允许更弱的 `unverified`，不能提高到 supporting/canonical。

`declared_intent` 必须显式 `allow_declared_intent=true`，且不能进入
`authority_policy.required`。只有声明的 Pack 可用来提假设，但
`confirmed_claims_allowed=false`；optional Skill Context 会沿现有链把
`forbidden_without_context` 从 allowed 移入 forbidden。Analysis Result 保留 Item authority 和 Pack
authority ceiling。

`source_revision` 继续必填，Pack 内所有 Item 继续共享同一 revision。可变源使用
`snapshot:<sha256>`，digest 覆盖选择后的资源身份、可得的原生 revision/sync token、content hash
和 `observed_at`；它只证明“Provider 在该时刻看到什么”，不是伪造上游 commit。
`supersedes=[]` 表示无可证明 lineage；只有持有 durable previous observation 时才引用前一不可变
观察，不能按时间戳猜。Git 的 exact HEAD/clean path/hash/verify 规则不变。

时间不新增字段：计划适用期放 `valid_time`，定义被选作项目声明的生效期放 `effective_range`，抓取
时间放 `observed_at`。实际发生必须是另一 observed/authoritative Item；没有实际来源就返回 Context
Gap，不能把计划时间复制成实际时间。

Broker 会在单 Pack 内按 `fact_id`、authority、content hash 和 supersession 检测多权威、内容分歧、
环和跨 fact 替换。不同 Provider requirement 仍保留为不同 Pack；当前不把跨 Pack 分歧编译为单一
machine conflict record。Pack 有 item/file、per-item byte、total byte、line 硬边界；无 host tokenizer
时没有精确 token 预算，RPC `max_output_tokens` 目前是保守 UTF-8 byte units，不是模型 token 数。

### Descriptor 接入

`deployment.subprocess.protocol=command` 把“命令行参数 → JSON stdout”适配到现有 Provider RPC。
新增一个 source 只提交 descriptor JSON，不新增 Python：

1. 锁定绝对 `executable`、位于 `work_root` 内的绝对 `working_directory`，并保持
   `inherits_gravity_credentials=false`；CLI 从自己的配置目录读取认证，Runtime 不读取或转存 token。
2. 每个 route 声明一个 exact `resource_prefix`、URI 路径段数量、argv 数组和固定 Context metadata。
   动态值只能是单个 URI 路径段，或用 `/`、`:`、`-` 连接若干路径段；不经过 shell。
3. `capabilities.operations` 必须只有 `read`。route 的 `item_id`/`fact_id` 是调用项目 binding 使用的
   稳定身份；一个 route 表示一个逻辑依赖。
4. stdout 必须是严格 UTF-8 JSON；可选 `content_pointer` 只做 JSON Pointer 选取。Runtime 计算
   content hash/revision、观察时间并走现有 Context Item 校验。
5. 非零退出默认是 source unavailable。只有 descriptor 中“exit code + stderr JSON Pointer + exact
   scalar value”全部匹配时才能分类为 resource unavailable；stderr 正文不进入公开结果。

模板只表达 exact read，不表达 shell、环境变量插值、条件/循环、任意 jq、分页聚合、`list/search`、
多个命令编排或业务字段到 Context metadata 的自动推断。超出这些边界时，应由外部 CLI 自己提供一个
Agent-ready JSON 命令，或继续使用完整 Provider RPC 进程。

### 已登记命令源

`lark-cli.v1.json` 覆盖两个 exact URI 形状：

| Context resource URI | 无 shell argv 形状 | 用途 |
| --- | --- | --- |
| `lark-cli://base/records/<base_token>/<table_id>` | `lark-cli base +record-list --base-token <base_token> --table-id <table_id> --limit 200 --offset 0 --format json --as user` | 排期 Base 记录第 0 页（最多 200 条） |
| `lark-cli://docs/documents/<document_id>` | `lark-cli docs +fetch --doc <document_id> --detail simple --doc-format xml --format json --as user` | 埋点规范文档 |

本机证据是 `lark-cli version 1.0.69`。两条命令的 `--help` 均实际输出 `Risk: read`。使用占位 ID
执行 `--dry-run`（未访问真实数据）得到以下完整 JSON 部分；CLI 在 JSON 前另输出 `=== Dry Run ===`：

```json
{
  "api": [
    {
      "method": "GET",
      "url": "/open-apis/base/v3/bases/app_fixture/tables/tbl_fixture/records?limit=200\u0026offset=0"
    }
  ],
  "base_token": "app_fixture",
  "table_id": "tbl_fixture"
}
```

```json
{
  "api": [
    {
      "desc": "OpenAPI: fetch document",
      "method": "POST",
      "url": "/open-apis/docs_ai/v1/documents/doxcn_fixture/fetch",
      "body": {
        "export_option": {
          "export_block_id": false,
          "export_cite_extra_data": false,
          "export_style_attrs": false
        },
        "extra_param": "{\"enable_user_cite_reference_map\":true,\"return_html5_block_data\":true}",
        "format": "xml",
        "lang": "zh_cn"
      }
    }
  ],
  "document_id": "doxcn_fixture"
}
```

`docs +fetch --help` 还要求 Agent 先执行
`lark-cli skills read lark-doc references/lark-doc-fetch.md`；本趟已读取该版本配套指南，且只在确需整篇
时使用默认 full scope。Base shortcut 没有自动分页参数，所以当前 descriptor 不声称表级完整性；需要
超过 200 条或按 view/field/filter 投影时，须另写边界明确的 descriptor，或由外部 CLI 提供完整聚合命令。

权限清单以本机 CLI schema 为准，不沿用历史或记忆中的 scope 名：

| 操作 | lark-cli 命令 | schema 查询 | 需要的 scope |
| --- | --- | --- | --- |
| 读取排期记录 | `lark-cli base +record-list ... --format json --as user` | `lark-cli schema bitable.app_table_record.list` | **查不到**：1.0.69 返回 `Unknown service: bitable` |
| 读取埋点文档 | `lark-cli docs +fetch ... --format json --as user` | `lark-cli schema docs_ai.documents.fetch` | **查不到**：1.0.69 返回 `Unknown service: docs_ai` |

因此 descriptor 不维护 scope 表。运行时权限错误由 CLI 的结构化 stderr 分类，Agent 应运行
`lark-cli auth status --json --verify`，并按 CLI 返回的 exact scope/hint 提示用户。这里没有足够证据
声明这两个 shortcut 的 scope 名；升级 CLI 后也必须重新执行 schema，而不是猜测。

本趟禁止访问真实资源，因此也没有证据锁定“资源不存在/无权限”的 exact 错误码；Lark descriptor 的
`failure_rules` 保持空数组，任一非零退出会保守降级为 `source_unavailable`，不会猜成资源缺失。只有后续
从无敏感数据的受控探测得到“exit code + stderr JSON Pointer + exact scalar”证据后，才能把该分类写入 descriptor。

第二个 descriptor `gh-issues.v1.json` 使用：

```text
gh-cli://issues/repository/<owner>/<repo>/<number>
  -> gh issue view <number> --repo <owner>/<repo> --json number,title,body,state,updatedAt,url
```

它与 Runtime 没有 Python 绑定；加入该 source 的 Python 改动数为 **0**。本机只确认
`gh version 2.93.0` 和 descriptor/transport 契约，未读取任何 Issue。

### 降级与硬失败

| 情况 | 结果 |
| --- | --- |
| CLI 未安装、未登录、网络/上游不可用、circuit open | `context_gap` + `degradation.kind=source_unavailable` |
| exact 失败规则确认资源缺失或不可访问 | `context_gap` + `degradation.kind=resource_unavailable` |
| TTL 时间缺失/无效/超期，或 freshness model 无法证明当前 | `context_gap` + `degradation.kind=content_stale` |
| 未登记 Provider、URI 越出 prefix、非 read、route 形状错误 | fail-closed；不附加可继续降级 |
| call/output/token 预算、超时、取消、隔离失败、畸形 JSON | fail-closed；不附加可继续降级 |

降级不是静默空结果。实际 envelope 形状如下：

```json
{
  "status": "context_gap",
  "ok": false,
  "reason_codes": ["PROVIDER_RPC_UNAVAILABLE"],
  "context_items": [],
  "degradation": {
    "schema_version": "gravity.command-source-degradation.v1",
    "kind": "source_unavailable",
    "cause": "command_not_found",
    "missing": "lark-cli executable, login, or network access",
    "message": "The external command source is currently unavailable; no empty-data claim was produced.",
    "user_actions": ["Install lark-cli and run `lark-cli doctor`."],
    "continuation": "supplemental_context_only",
    "authority_ceiling": "declared_intent"
  }
}
```

`continuation=supplemental_context_only` 的安全依据是 command source 的 ceiling 不高于
`declared_intent`：它只能补充计划/规范或形成假设，缺失不会把核心代码/受控数据查询变成相反事实。
Agent 必须转述缺什么、原因和 `user_actions`；不能把 Context Gap 说成“没有数据”。
