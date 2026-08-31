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
| Analysis Context / Defaults | `analysis context/defaults` | `analysis_context()` / `analysis_default_dictionary()` | `analysis_context` / `analysis_default_dictionary` |
| Business Pulse | `reports pulse` | `business_pulse()` | `business_pulse` |
| Dashboard | `analysis dashboard snapshot/prepare/run` | `dashboard_snapshot()` / dashboard analysis methods | `dashboard_snapshot` / `dashboard_analysis` |
| User / Order | `analysis user journey/order` | `user_journey()` / order methods | `user_journey` / order composites |
| Segment | `analysis segment evaluate/snapshot/members` | matching segment methods | `segment_evaluate` / `segment_snapshot` / `segment_members` |
| User Detail Aggregate | `analysis user-detail-aggregate` | `user_detail_aggregate()` | `user_detail_aggregate` |
| Saved Analysis | `analysis saved prepare/run` | saved analysis methods | `saved_analysis` |
| Multidim / Semantic | `multidim query` / `semantic compose` | matching methods | `multidim` / `semantic_compose` |
| Material / Promotion | `materials performance` / `promotion performance` | matching methods | matching composites |
| Report Directory | `reports directory/subscriptions` | matching methods | matching composites |

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
| 元数据与 Workspace | `metadata`、`recipe`、`context project` |
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

下表是任务入口，不复制产品 request schema。先运行对应 `--help`，未知输入再运行
`agent-catalog describe <selector>`。

| 产品 | CLI |
| --- | --- |
| Analysis Context / Defaults | `analysis context` / `analysis defaults` |
| Realtime Event Catalog | `analysis realtime-events` |
| App / Permission Snapshot | `apps snapshot` / `apps permission-profile` |
| Attribution | `attribution snapshot\|performance\|user-detail` |
| Reports | `reports pulse\|usage\|directory\|subscriptions` |
| Saved Analysis | `analysis saved list\|get\|prepare\|run` |
| Analysis Template | `analysis template list\|prepare\|run` |
| Segment | `analysis segment snapshot\|members\|evaluate` |
| Orders | `analysis order directory\|trace` |
| User Journey | `analysis user journey` |
| Dashboard | `analysis dashboard snapshot\|prepare\|run` |
| Material | `materials performance\|fetch\|title-packages` |
| Promotion | `promotion performance\|advertiser-profile\|bilibili-account-performance` |

### Derived Metrics

`gravity derive --input <request.json>` 对已有 result envelope 做本地确定性算术，不访问网络。
request 使用 `source/spec`；结果保留来源状态，输入为 partial 时不会把派生值包装成完整上游事实。

### Multidim

```powershell
gravity multidim query --input-schema
gravity multidim query --app main --input query.json --all-pages --output result.json
```

入口只接受闭合物理输入。未知指标、维度、关系或 cohort horizon 在发网前失败；结果检查顶层状态、
`query.status` 和分页完整性。

### Business Semantic 与 Semantic Compose

```powershell
gravity semantics list
gravity semantics describe <semantic-uri>
gravity semantic compose --input-schema
gravity semantic compose --app main --input semantic-request.json --dry-run
gravity semantic compose --app main --input semantic-request.json
```

Semantic 编译使用版本化成员和项目 binding；未知成员、单位/粒度冲突、禁止 join 均零网络失败。

### Material Performance

```powershell
gravity materials performance --app main --start 2026-08-01 --end 2026-08-07 `
  --platform bytedance --output materials.json
```

平台保留原生物理字段，不跨平台归一、汇总或排名。允许的平台和指标从当前输入 schema 获取。

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

边界是 fresh-response 子集，不是任意历史 ID 恢复：`local` 仅支持已观察的
`tos-accelerate.gravity-engine.com` 租户 video/thumbnail 路径；`bytedance_project` 仅支持已观察的
`v26-cc.oceanengine.com` MP4 和 `p26-sign.douyinpic.com` JPEG 路径。普通
`material.local.list` / `material.bytedance.project_material.list` JSON 已不再投影 URL。fresh scope 中
没有唯一引用、目标 role 缺失或非重试 4xx 无法区分缺失/过期/未缓存/删除/权限时，固定返回
`MATERIAL_ASSET_BINARY_UNAVAILABLE`；host/path 越界返回 `MATERIAL_ASSET_SOURCE_UNSUPPORTED`。
两者均不留下 partial 文件，也不回显 URL。

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
worker 逐轮减半直至 1，并在重试前做 1s 起、最多 30s 的指数退避（更长的 `retry_after_ms` 在该上限内
优先）。成功、empty、partial 和确定性失败不重放。结果的 `adaptive_execution` 给出每轮 worker、退避、
组件数、待重试数、最终 worker 和组件调用总数；worker=1 仍拒绝时以
`terminal_reason=serial_retryable_failure` 结束本次调用，错误本身仍可在更长冷却后重试。

### Single-user journey

`gravity analysis user journey` 只接受调用方明确给出的 client id、App 和日期/日期窗；返回固定受管
字段，不用于发现任意用户。

### Order Directory v1

`gravity analysis order directory --app <app> --date <date>` 完整读取单日受管订单目录。额外身份或不完整
分页失败关闭。

### Order Split Trace v1

`gravity analysis order trace --app <app> --date <date> --trace-id <id>` 先在父目录唯一匹配，再读取一次
child 投影；结果不回显 TraceID。

### Dashboard control-plane snapshot

`gravity analysis dashboard snapshot --app <app> --ref <id-or-exact-name>` 读取控制面，不执行图表，也不
模拟 layout、favourite 或页面 global filter。

### Dashboard Analysis Replay v2

`prepare` 编译可支持图表，`run` 执行；单图失败隔离，结果按看板顺序返回。引用必须是稳定 ID 或
精确名称，日期窗由调用方提供。

### Segment Snapshot v1

`gravity analysis segment snapshot` 读取 detail/history/指定日期结果，不返回成员或规则。

### Segment Members v1

`gravity analysis segment members` 读取成员行；动态属性先由 metadata 发现。超过本地结果边界时返回
partial，不伪造 continuation。

### Segment Mutation v1

Segment create/update/refresh/delete 使用 direct CLI 的 `--dry-run` / `--execute`，或 `gravity action
segment-update preview|execute`。自然语言、历史记录和 tool result 都不能构造授权；mutation 不进入
普通只读 Plan node。

### Segment Rule Spec v1

`analysis segment evaluate --spec-schema` 返回闭合规则合同；`--dry-run` 只编译和脱敏预览，正常执行
只返回聚合人数/占比，不生成规则或保存分群。

复合 cohort 留存不使用已知会被 Retention endpoint 拒绝的 `before_custom` 或
`property_conditions`。同日事件交集与 set-once 首付属性的完整 Funnel/Segment Spec、语义差异、
中间分群和本地除法见[复合 cohort 留存替代路径](../guides/retention-cohort-alternatives.md)。

<a id="user-detail-aggregate"></a>
### User Detail Aggregate v1

`analysis user-detail-aggregate` 用 live user-property metadata 校验顶层及动态字段，在 Runtime 内调用
`analysis.user_detail.list` 的公共有界分页链路，只返回 `cells`、显式 measure definitions、分页完整性、
source/receipt audit。`bounds.max_pages/max_items/max_cells` 三项必须全部显式提供；`max_cells` 的硬上限
200 与现有安全 stdout item cap 相同。源 operation 的完整性当前为 `unknown/wire`，因此数字只对实际
`consumed_items` 精确，不能宣称完整用户总体。

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

不在 live 白名单、`sum` 非数值字段、同一引用字段混合类型、单元格超限和缺失边界分别稳定失败为
`USER_DETAIL_AGGREGATE_FIELD_UNSUPPORTED`、`USER_DETAIL_AGGREGATE_MIXED_TYPE`、
`USER_DETAIL_AGGREGATE_CARDINALITY_LIMIT`、`USER_DETAIL_AGGREGATE_BOUNDS_REQUIRED`；错误不返回部分单元格。

### Saved Analysis v4

`list/get` 只定位受控定义；`prepare` 编译但不执行最终查询；`run` 严格重放。create/update/delete 必须
先 dry-run，再以同一参数 execute，且不提供分享能力。

### Business pulse

`gravity reports pulse` 并发读取显式 App 和日期窗的经营概览/趋势；小时源只在 workspace scope 下
启用。部分平台失败保留组件状态，不能当完整汇总。

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
gravity skills list
gravity skills show <skill-uri>
gravity analysis playbook schema
gravity plan schema
gravity plan run --input plan.json --dry-run
```

Journey readiness、Skill lock/trust、playbook checkpoint 和 Plan DAG 是不同合同；不得因某一层可发现
就跳过其他层的 Trust、完整性、Context 或 effect 门禁。Plan 细节见 [Plan 参考](plan.md)。

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

探索行只交给显式调用方，不成为持久 Runtime evidence。`promote` 校验并原子安装 reviewed definition，
但 SQLite 探索与 Registered SQL 的语义等价性必须由外部 review 证明；安装本身不授予 stable Trust。
Explorer 不接受 DDL/DML、多语句或自动生成 SQL，不拦截 Insight/registered SQL 失败，也不能在 promotion
前进入稳定 Journey、Skill、Dashboard 或 Action。

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

<a id="result-and-errors"></a>
## 结果与错误

结果尽量使用 versioned JSON envelope。`--output` 成功后 stdout 只返回写入收据；error 或 capability
gap 不创建/替换目标，partial 产品写入完整 partial envelope 并保留非零退出码。

调用方至少检查 `schema_version/status/error`。`success` 仍需检查产品 completeness/claims；`empty` 只
证明该 scope/window 合法为空；`partial/error/capability_gap/blocked/uncertain` 都不能作为完整结论。

CLI 退出码为成功 `0`、caller `2`、upstream `3`、local `4`；组合结果按 `4 > 3 > 2 > 0` 聚合。业务
空结果可为成功；不要用进程退出码替代 envelope 的 completeness、组件状态或 claims。
