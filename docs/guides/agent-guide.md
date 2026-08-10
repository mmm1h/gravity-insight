# Gravity Insight Agent 使用指南

AI agent 和自动化脚本必须使用 `search -> describe -> validate -> read/export`，不要扫描
manifest、拼 URL、猜 operation ID、父 ID、过滤符或动态字段。当前目录包含 138 个
stable read、298 个不可调用 draft、414 个 blocked-write reservation；目录可发现不等于可用。

## 1. 能力发现

```powershell
gravity insight capabilities search "变现 明细" --limit 10
gravity insight capabilities search "推广 报表" --platform tencent --stability stable --limit 20
```

`search` 返回 `gravity-insight.capability-search.v1`：

```json
{
  "ok": true,
  "status": "success",
  "query": "变现 明细",
  "count": 4,
  "total": 8,
  "limit": 10,
  "continuation_token": null,
  "capabilities": [
    {
      "operation_id": "analysis.monetization_detail.list",
      "stability": "stable",
      "executable": true,
      "health": "stable",
      "catalog_status": "registered",
      "required_parent": true,
      "matched_on": ["description", "operation_id", "resource"]
    }
  ]
}
```

单页最多 20 条。若 `continuation_token` 非空，把它原样传回；不要解析或修改 token。下面的
PowerShell 示例先取得真实 token，再请求下一页，可直接离线运行：

```powershell
$first = gravity insight capabilities search "变现 明细" --limit 2 | ConvertFrom-Json
gravity insight capabilities search "变现 明细" --limit 2 --continuation $first.continuation_token
```

不指定 `--stability` 时，默认首屏按 `callable stable -> 其他 executable -> draft` 分组排序，
并且在 callable stable 之后最多预览 1 条不可调用能力；`presentation.non_callable_total`
说明还有多少不可调用候选，全部候选仍可用 `continuation_token` 翻页查看。精确输入完整
operation ID 时，该 operation 始终优先返回，即使它是 draft。需要集中盘点 draft 时显式使用
`--stability experimental` 或继续翻页，不要把首屏条数当成总命中数。

搜索索引包含中英文描述、operation ID、domain、resource 和 platform。异步 export 使用独立
catalog，不混入同步 read 的 `capabilities search`。不知道有哪些顶层能力时先运行
`gravity insight --help`；其中会直接显示 export 发现入口：

```powershell
gravity insight export list-capabilities
gravity insight export describe export.material.report.start
```

第一条列出全部 22 个 effect 及 `currently_callable`，第二条返回输入 schema、列语义、规模控制、
经验证 example 和 start -> wait -> download 命令顺序。agent 不需要也不得扫描内部 contract。

## 2. Describe 是调用前权威

```powershell
gravity insight capabilities describe analysis.monetization_detail.list
```

返回 `gravity-insight.operation-description.v1`。agent 至少读取：

- `currently_callable`、`stability`、`executable`、`health.status`：现在是否允许调用。
- `input_schema`：type、required、default、enum、数组上下限和 sensitive。
- `wire`：固定 method/path，以及 query/body 使用哪些调用方字段；不要自己构造 wire。
- `response_projection`、`privacy`、`pagination`：可见输出、隐私等级和翻页协议。
- `examples` / `examples_status`：只有 `complete` 的 example 才能直接复用。
- `required_parent`：父 operation、`output_path`、`selection`、`target_input`。
- `blockers`、`promotion_gate`：draft 为什么不能调用、还缺什么证据。
- `health.probe`、`provenance`：最近 probe 状态与契约来源。

### Stable、draft 和 health 不是一回事

- `stable + executable=true`：契约达到默认可执行层级，但仍要检查 health。
- `health=stable|healthy`：没有活跃漂移证据，按 describe 契约调用。
- `health=suspect`：只有前端/观测疑点，当前仍可调用；记录 warning，并限制影响面。
- `health=contract_changed_additive`：上游只新增了未登记响应字段；SDK 已省略未知字段并保持
  安全 projection。允许继续调用，但必须记录 warning，且不得读取、猜测或传播投影外字段。
- `health=degraded`：按结构化 retry 策略对同一请求最多重试一次；不要当成契约变化。
- `health=auth_error|permission_unavailable`：停止当前调用，分别处理认证或权限；不要报
  `CONTRACT_CHANGED`。
- `health=upstream_changed|blocked`：停止调用，返回或传播 `CONTRACT_CHANGED`。
- `draft_catalog_only` / `experimental + executable=false`：只可发现、不可调用。

遇到 draft 必须 describe：

```powershell
gravity insight capabilities describe app.monetization_app.list
```

读取 `blockers[].code/detail/evidence/status` 和 `promotion_gate.missing`。例如
`empty_sample` 只表示已记录的那组输入返回 HTTP 200 空结果，不证明当前租户下所有合法输入都空。
先使用下一节的受控发现命令。agent 不得绕过 `currently_callable=false`，也不得把 draft 输入送进
普通 `read`；`discover-nonempty` 是只返回组合、计数和 schema hash 的专用探测入口。读取 `next_action` 和
`user_can_unlock`：通常 SDK 使用者不能自行解锁，应把 operation ID、blocker codes 和所需的
数据/凭据条件发给 Gravity Insight SDK 维护方，请其完成验证并发布 executable 能力；当前任务
改用 stable executable 替代项。

### 发现有数据的输入组合

```powershell
gravity insight discover-nonempty material.report.query
gravity insight discover-nonempty <operation-id> --input <seed.json> --request-budget 12 --candidate-limit 5
```

该命令会真实联网，但串行执行且默认最多 12 个 HTTP 请求。它只从 operation 的
`input_fields`、`live_probe`、`required_parent`、默认值和 enum 生成候选：父 operation 最多取
5 个候选，随后以 weighted best-first 顺序懒展开 enum 与 30/7/1/90 日窗口；不会维护 App、平台、
状态等字段名白名单，也不会预先生成完整笛卡尔积。找到第一组非空输入立即停止。

读取 `resolution`：

- `unblocked`：`inputs` 是第一组非空组合，`nonempty.item_count` 是计数，不含响应行；再按正常
  `validate -> read/export` 流程使用。
- `confirmed_empty`：已穷尽当前契约能表达的合理组合，且每个目标请求都是语义成功的空结果。
- `undetermined`：预算不足、上游错误、父候选为空，或存在 `opaque_candidate_space` 等契约未描述
  的候选维度；不得写成“当前账号没有数据”。

`search.dimensions` 记录维度来源、候选数和优先级，`attempted_combinations`、
`planned_combinations` 与 `request_stats` 用于审计覆盖。完整候选值缓存到
`tmp/codex/gi-nonempty/cache/`，同一天、同契约、同 seed 和同预算再次调用时请求数为 0；缓存含
真实 App/业务 ID，禁止提交。SDK 维护者可用 `--apply-draft` 将命中的字段路径、类型、计数和 hash
写为 value-free evidence；该选项不会把命中输入写入契约或 evidence。
### 父资源候选解析

`required_parent` 非空时，不要自己猜父 list 或 ID 字段。先运行：

```powershell
gravity insight parents resolve promotion.honor.campaign_option.list
```

当前账号的真实输出为：

```json
{
  "bindings": [
    {
      "candidate_count": 0,
      "candidate_types": [],
      "candidates": [],
      "output_path": "data.list[].advertiser_id",
      "parent_operation_id": "promotion.honor.account.list",
      "selected": null,
      "selection": "caller_select",
      "status": "empty",
      "target_cardinality": "one",
      "target_input": "advertiser_id"
    }
  ],
  "ok": true,
  "operation_id": "promotion.honor.campaign_option.list",
  "schema_version": "gravity-insight.parent-resolution.v1",
  "status": "empty",
  "values_persisted": false
}
```

该命令可 describe draft 子 operation，但只执行其已声明的 stable 父 operation；父读取仍经过
SDK operation 授权、输入校验和 health 门禁，不能绕过 draft 的 `currently_callable=false`。
同一命令内重复引用的父 operation 只请求一次，缓存只在进程内存在。候选 ID 只写 stdout，
不写契约或仓库证据；确需跨进程缓存时只能写入 `tmp/`。

- `resolved`：所有绑定均拿到候选；继续按每条 binding 的 `selection` 处理。
- `empty`：绑定已证明，但当前账号没有父样本；停止子调用。
- `permission_unavailable`：绑定已证明，但父读取无权限；停止并申请权限。
- `undetermined`：至少一条绑定或父响应无法证明；停止并把 missing evidence 交给维护方。
- `not_required`：operation 没有声明父依赖。

`caller_select` 表示候选可能对应不同业务资源，agent 必须把候选连同业务上下文交给调用方选择，
不能默认取第一条；`all` 表示目标字段为列表，可传全部候选。维护 probe 为验证契约可临时使用
第一条候选，并在证据中标记 `probe_selection=first`，这不改变公开调用的选择责任。
## 3. 离线校验参数

```powershell
gravity insight validate report.business.query --input tmp/codex/gi-delivery/business-paid-conversion.example.json --render-wire
gravity insight validate export.material.report.start --input <export-request.json> --render-wire
```

`validate` 不登录、不读 metadata、不发 HTTP。返回 `gravity-insight.validation.v1`，状态只有：

- `valid_offline`：所有本地规则通过。
- `needs_live_metadata`：本地规则通过，但 `live_metadata_dependencies` 必须执行时核验。
- `invalid`：读取结构化 `error` 修复，不执行。

`normalized_input` 是实际默认值收敛后的输入；`wire` 可用于审计 method/path/query/body，
敏感值保持脱敏。export operation 同样支持 input schema 离线校验，并自动使用独立 export
catalog；`validation_scope` 会说明 `--columns` 和 `--idempotency-key` 仍由 `export start` 校验。
`needs_live_metadata` 不是成功证明，只允许进入一次受控执行。

## 4. 认证状态

```powershell
gravity insight auth status
```

`auth status` 只读取本地凭据元数据，不登录、不发业务请求。关键字段：

- `token_valid`：当前选中的 token 按本地过期声明是否仍可用；为 true 时直接执行 operation。
- `token_source`：`credential_file` 或 `process_environment`，不包含 token 值。
- `account_hint`：脱敏账号提示，例如 `a***@example.com`，用于确认当前账号。
- `can_exchange_credentials`：本地是否有账密可在 token 被拒绝或过期时换取新 token。

刷新会联网登录，并更新 `.env.gravity.local` 和受控的用户环境凭据：

```powershell
gravity insight auth refresh
```

该命令需联网；文档一致性校对不执行刷新。

刷新结果的 `auth` 是写入后的重新判定。父进程可能仍继承旧环境值；SDK 会选择更新时间更晚的
受控凭据文件，避免旧进程环境覆盖新 token。`auth.token_valid=true` 时不得再次循环 refresh；
执行所需 operation。不要输出 token、密码、完整 Cookie 或未脱敏账号。

## 5. 执行和分页的安全默认

```powershell
gravity insight read app.list --input tmp/codex/gi-delivery/app-list.example.json --max-pages 2 --max-items 50
```

stdout 默认最多 5 页、200 items。agent 每次先用更小的 `--max-pages 2 --max-items 50`；
只把本轮所需字段放进 context。达到限制时 envelope 返回 `truncated: true`、
`next_page_input`、`total` 和 `safety_limits`。后续请求应把 `next_page_input` 原样作为输入，
不要猜 cursor 或只递增 `page`。

大结果必须落盘或 NDJSON 流式处理：

```powershell
gravity insight read analysis.monetization_detail.list --input tmp/codex/gi-delivery/monetization-detail.example.json --all-pages --format ndjson > tmp/codex/gi-delivery/monetization-detail.ndjson
gravity insight read promotion.honor.campaign.list --input tmp/codex/gi-delivery/honor-campaign-spend.example.json --all-pages --output tmp/codex/gi-delivery/honor-campaign-spend.json
```

`--all-pages` 未配 `--output` 或 `--format ndjson` 会以 `INPUT_INVALID` 拒绝。JSON 文件仍有
1000 页/100000 条硬上限；不要要求解除上限。大字符串、opaque JSON 和二进制 stdout
只返回摘要、SHA-256 与 reference，按 reference 用 output 重跑。

### 多维报表动态多日指标

`multidim query` 支持用 `--multi-days` 指定 2～30 日的关键日。参数必须升序、不得重复；
SDK 会把它编码到上游 `data_conf.multi_keys`，并只公开已请求指标对应的数字后缀字段：

```powershell
gravity insight multidim query `
  --app-id 29034827 --media bytedance `
  --start 2026-08-03 --end 2026-08-09 --time-dim day `
  --metrics multi_day_roi_all --multi-days 2,3,4,5,6,7
```

结果字段形如 `multi_day_roi_all_2` 至 `multi_day_roi_all_7`；`data.total` 是当前查询范围的
汇总值。多日指标计算会附带未请求的依赖字段，SDK 会省略这些字段并返回
`contract_changed_additive`；调用方可以继续消费已登记的请求指标字段，但不得消费 warning
中被省略的字段。

### Batch wrapper

batch 是 read 的并发 wrapper，不接受每项 `max_pages` 或 `max_items`。调用前先取公开 schema：

```powershell
gravity insight batch schema
gravity insight batch read --help
```

`batch schema` 给出可复制的 `requests[]` example。每项只允许 `operation_id`、`input` 或
`inputs`（二选一）、`request_id`、`read_all`；未知字段错误会列出这五个名字。成功输出是
`gravity-insight.batch.v1` 顶层 envelope，包含 `total_count/success_count/failure_count/results`。
全部成功退出 0；有失败时按 item category 取最高退出码：local 4 > upstream 3 > caller 2。

## 6. 结构化错误处理

所有 CLI、read envelope 和 batch item 统一返回：

```json
{
  "ok": false,
  "status": "error",
  "operation_id": "report.business.query",
  "schema_version": "gravity-insight.error.v1",
  "error": {
    "code": "INPUT_INVALID",
    "category": "caller",
    "message": "...",
    "field": "date_list",
    "retryable": false,
    "retry_after_ms": null,
    "next_action": "Run `gravity insight capabilities describe ...` ..."
  }
}
```

决策优先级：

1. 按 `error.code` 分支，不匹配 `message` 文本。
2. `retryable=false` 时绝不自动重试，执行 `next_action` 或升级给人。
3. `retryable=true` 时尊重 `retry_after_ms`，同一请求最多重试一次。
4. 未知大写扩展 code 按 `category/retryable/next_action` 处理，不当成 SDK 崩溃。

固定 14 个 code：`UNKNOWN_OPERATION`、`INPUT_INVALID`、`PARENT_REQUIRED`、
`AUTH_MISSING`、`AUTH_REJECTED`、`PERMISSION_UNAVAILABLE`、`RATE_LIMITED`、
`UPSTREAM_UNAVAILABLE`、`CONTRACT_CHANGED`、`UNSUPPORTED`、`NOT_IMPLEMENTED`、
`PAGINATION_LIMIT`、`EXPORT_TIMEOUT`、`LOCAL_IO_ERROR`。退出码 `2/3/4` 分别对应
caller/upstream/local；退出码 0 才是成功。

`INPUT_INVALID` 必须读取结构化 `error.field`，不得从 message 正则提取字段。caller、local、
auth、permission 错误不改变 capability health；只有成功 read 或真实 upstream/contract 证据
可以更新 health。修正输入后不需要用成功 read “恢复”被错误污染的 health。

父依赖错误的处理：执行 `required_parent.operation_id`，从 `output_path` 取候选，并按
`selection` 选择后写入 `target_input`。任何字段是 `null`，或 selection 是
`caller_select`，都停止自动代选并请求调用方决策。

## 7. 异步导出

当前唯一可创建的是 `export.material.report.start`。创建、轮询、下载、取消是四种独立 effect；
create 不自动重试，timeout 不自动 cancel。先从公开目录发现，再 describe：

```powershell
gravity insight export list-capabilities
gravity insight export describe export.material.report.start
```

`describe.input_schema` 逐字段给出 required/optional/type/default，`columns` 给出 `--columns`
与 `export_col_list` 必须同序一致及列码到 XLSX 表头的映射，`pagination_and_scale` 明确
`page_size` 不限制总行数，`examples[0]` 是已在线验证的真实请求构造。example 中 App 与日期
是显式 caller selection。`app.list` 的 projection 已登记 `data.list[].platform`，但上游当前返回的
App 行省略该字段，不是 SDK projection 漏字段；不要据此猜平台。用调用方业务上下文确定平台，或先以
`capabilities search "app list" --platform <platform>` 找平台专属 App operation，再按
`examples[0].preflight` 用发现命令选择 App/平台/日期：

```powershell
gravity insight discover-nonempty material.report.query --request-budget 12
```

只有 `resolution=unblocked` 才用返回的 `inputs` 执行 `material.report.query` 1 行 read，并在公开
`data.list` 非空后替换三个 placeholder、继续 start；空结果禁止创建。此 preflight 仅在 warning
说明“未登记的 list item 字段已省略”且 `status=contract_changed_additive` 时允许继续，且只用于
判断候选行是否存在、只消费公开投影。其他 warning、非零退出、错误 envelope 或
`health=upstream_changed|blocked` 均须停止。禁止代猜。

构造 export input 后也执行通用离线校验：

```powershell
gravity insight validate export.material.report.start --input <request.json> --render-wire
```

这一步不创建任务；成功只证明 input schema 与 create wire。`--columns` 和 idempotency key 仍在
随后唯一一次 `export start` 中校验。

以下三条会访问 Gravity；只有在已授权联网、把 describe example 保存为请求文件并替换
App/date，且从 start 返回真实 job ID 后继续：

```powershell
gravity insight export start export.material.report.start --input <request.json> --columns file_name,gravity_material_id,stat_cost,ctr,convert_rate,AppRealRegisterCnt,AppGamePayUserCntStandardAtv --idempotency-key agent-material-<yyyymmdd>-<unique-suffix>
gravity insight export wait <job-id> --operation-id export.material.report.start --interval 2 --timeout 300
gravity insight export download <job-id> --operation-id export.material.report.start --output <material-report.xlsx> --timeout 300
```

`page_size` 不限制导出总行数；用窄过滤控制作业。`EXPORT_TIMEOUT` 时恢复同一 job。
`cancel` 只返回 `CANCEL_REQUESTED`，不是终态，继续 status/wait。SDK 只下载 READY 状态
返回并通过 host/path/MIME/magic/header/privacy/hash 校验的文件，不接受调用方自带 URL。
断线后运行 `export list --page 1 --page-size 100`；v2 列表包含 `operation_id`、task type、
任务名指纹和只含字段名的 `request_summary`，参数值始终脱敏。

## 8. 完整 agent 决策流程

```text
收到数据需求
  -> --help 判断同步 read 或异步 export
  -> read: capabilities search（业务词；最多 20 条）
  -> export: export list-capabilities -> export describe
  -> 无结果：换同义词一次；仍无结果则报告能力缺口
  -> 对候选逐个 describe
      -> draft/executable=false 且含 empty_sample：先 discover-nonempty，只消费组合/计数/schema hash
      -> 其他 draft/executable=false：返回 blockers，不调用
      -> health contract_changed_additive：记录 warning，只消费登记 projection，继续
      -> health suspect：限制影响面并携带 warning，继续
      -> health degraded：按 retryable 对同一请求最多重试一次
      -> health auth_error/permission_unavailable：分别处理认证/权限，不报契约变化
      -> health upstream_changed/blocked：停止并升级工程
      -> 父依赖不完整或 caller_select：请求人类选择
  -> 选取 privacy 最低、粒度足够、stable 且健康的 operation
  -> 生成最小 input，read/export 均执行 validate --render-wire
      -> invalid：按 error/field 修复一次
      -> needs_live_metadata：标记在线仍可能失败
  -> auth status；只在 AUTH 场景刷新一次
  -> 小页 read（默认 2 页/50 条）或按 describe example 显式 export start
      -> success：只消费投影字段
      -> truncated：保存 continuation，按需逐页继续
      -> retryable：等待后同请求最多重试一次
      -> non-retryable：执行 next_action，禁止盲重试
  -> 大结果写 output/NDJSON，context 只放摘要、行数、hash、artifact path
  -> 返回 operation_id、输入窗口、分页/截断、health warning 和未证明边界
```

最终回答不得把 `accounted=987` 表述成 987 个可调用能力，也不得把 draft、reservation、
export catalog route 计入 stable read。导出细节见 `docs/guides/export-guide.md`。
