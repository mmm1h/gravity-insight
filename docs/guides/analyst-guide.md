# Gravity Insight 数据分析上手指南

本指南面向只想拿到分析结果、不了解仓库实现的分析师。请从仓库根目录运行命令。
Gravity Insight 不是任意 HTTP 或 SQL 客户端：先从能力目录找到 operation，再按它的
输入契约读取。当前真正默认可调用的是 138 个 `stable` operation；298 个 `draft`
只是可发现的候选，不能执行。

## 5 分钟上手

### 1. 确认本地环境和凭据

```powershell
python --version
gravity insight --dry-run
gravity insight auth status
```

`--dry-run` 应返回 `status: pass`、`operations: 146`、`network_called: false`。
认证状态的含义：

- `valid_token`：`token_valid=true`，可以直接查询，不要再次刷新。
- `credentials_available`：已有用户名和密码，但当前 token 不可用；运行下面的刷新命令一次。
- `missing`：本机没有可用凭据，找工程或数据平台管理员配置。

`auth status` 只读本地元数据，不联网。用脱敏的 `account_hint` 确认当前账号，用
`token_source` 确认 token 来自受控凭据文件还是进程环境；两者都不会暴露 token、密码或
完整 Cookie。

```powershell
gravity insight auth refresh
```

该命令需联网；文档一致性校对不执行刷新。

`auth refresh` 会联网换取 token，并更新受控凭据文件和用户环境；返回结果里的 `auth`
是刷新后的重新判定。看到 `auth.token_valid=true` 后直接查询，不要循环 refresh。不要把
token、Cookie、用户名或密码粘进请求 JSON、报告或聊天记录。

### 2. 找到能力，不猜 operation ID

```powershell
gravity insight capabilities search "经营 报表" --stability stable --limit 10
gravity insight capabilities describe report.business.query
```

搜索结果重点看 `operation_id`、`stability`、`executable`、`health`、
`required_parent`。`describe` 重点看 `input_schema`、`examples`、
`required_parent`、`pagination` 和 `privacy`。`stable` 表示契约已达到可执行层级；
`contract_changed_additive` 表示未知新增字段已被安全省略，可以继续但只能消费登记 projection；
若 `health.status` 是 `upstream_changed` 或 `blocked`，仍应停止执行。`suspect` 携 warning 限量
执行；`degraded` 只按 retryable 重试一次；认证和权限状态分别处理，不当成契约变化。

不加 `--stability` 的搜索会先显示可调用 stable，并只预览 1 条不可调用候选；
`presentation.non_callable_total` 和 `continuation_token` 表示仍有 draft 可继续查看。draft
没有被过滤掉。精确搜索完整 operation ID 时，即使是 draft 也会优先返回。

### 3. 跑第一个查询

先取当前账号可见 App。这个结果中的 `data.list[].id` 是后续示例的 App ID。
`read` 会联网；先完成授权并确认当前账号，再执行本节和后续分析任务中的读取命令。

```powershell
gravity insight capabilities describe app.list
gravity insight validate app.list --input tmp/codex/gi-delivery/app-list.example.json --render-wire
gravity insight read app.list --input tmp/codex/gi-delivery/app-list.example.json --max-pages 1 --max-items 20
```

把示例请求中的 `replace-with-app-id` 换成真实 ID，先离线校验，再查询：

```powershell
gravity insight validate report.business.query --input tmp/codex/gi-delivery/business-paid-conversion.example.json --render-wire
gravity insight read report.business.query --input tmp/codex/gi-delivery/business-paid-conversion.example.json --max-pages 5 --max-items 100
```

`valid_offline` 表示输入结构可执行；`needs_live_metadata` 表示本地检查已过，但执行时还要
在线核验字段或指标。两者都不证明当前租户一定有数据。

### 查询为空时先发现可用筛选组合

```powershell
gravity insight discover-nonempty <operation-id>
gravity insight discover-nonempty <operation-id> --input <seed.json> --request-budget 12
```

这不是重复同一个空请求。命令从该 operation 自己的 App/父资源、enum、默认输入和日期占位符
生成候选，按更可能非空的顺序串行尝试，命中第一组后停止；默认最多 12 个 HTTP 请求。结果：

- `unblocked`：把返回的 `inputs` 保存到 `tmp/`，先 `validate`，再执行正常 read。
- `confirmed_empty`：当前契约可表达的合理组合已全部返回空；报告里同时记录
  `attempted_combinations`、`search.dimensions` 和请求预算。
- `undetermined`：预算不足或契约没有描述 filters/object 内部候选等搜索空间；把
  `search.unresolved_dimensions` 发给工程，不要宣称账号无数据。

候选缓存位于 `tmp/codex/gi-nonempty/cache/`，可能含真实 App 或业务 ID，不要复制进仓库、报告
或聊天记录。分析师不要使用维护用途的 `--apply-draft`。

## 按分析任务使用

### 查某 App 活动窗口的付费转化

`report.business.query` 可按 App、日期和广告平台输出消耗、付费人数和 ROI。它不能按
任意 campaign ID 过滤，所以不要把这个结果写成“某广告计划”的独立效果。

1. 编辑 `tmp/codex/gi-delivery/business-paid-conversion.example.json` 中的 App ID、日期和平台。
2. 运行：

```powershell
gravity insight capabilities describe report.business.query
gravity insight validate report.business.query --input tmp/codex/gi-delivery/business-paid-conversion.example.json --render-wire
gravity insight read report.business.query --input tmp/codex/gi-delivery/business-paid-conversion.example.json --max-pages 5 --max-items 100
```

示例指标为 `AdCost`、`AppGamePayUserCntReportingStandard`、`AppROI`，维度为
`stat_datetime`、`ad_platform`、`app_id`。指标的业务解释仍应以团队现行口径为准；
SDK 只保证请求和响应契约。

### 导出某日的变现明细到 NDJSON

这是用户级明细读取，不是异步任务中心导出。先确认使用权限和落盘位置符合数据治理要求。

1. 编辑 `tmp/codex/gi-delivery/monetization-detail.example.json` 的 App ID 和日期。
2. 运行：

```powershell
gravity insight capabilities describe analysis.monetization_detail.list
gravity insight validate analysis.monetization_detail.list --input tmp/codex/gi-delivery/monetization-detail.example.json --render-wire
gravity insight read analysis.monetization_detail.list --input tmp/codex/gi-delivery/monetization-detail.example.json --all-pages --format ndjson > tmp/codex/gi-delivery/monetization-detail.ndjson
```

离线校验通常返回 `needs_live_metadata`，因为字段需要在线元数据确认。`--all-pages` 只有
配 `--output` 或 `--format ndjson` 才允许执行；不要把大结果直接塞进终端或 AI 对话。

### 看某荣耀广告计划的消耗趋势

当前已登记的计划层 stable 示例是荣耀平台。SDK 没有证明字符串 `EQUALS` 是该 operation
的合法服务端过滤符，因此示例读取计划层结果，不伪造服务端 campaign 过滤；取得文件后
再按 `campaign_id` 本地筛选。

1. 编辑 `tmp/codex/gi-delivery/honor-campaign-spend.example.json` 的日期。
2. 运行：

```powershell
gravity insight capabilities describe promotion.honor.campaign.list
gravity insight validate promotion.honor.campaign.list --input tmp/codex/gi-delivery/honor-campaign-spend.example.json --render-wire
gravity insight read promotion.honor.campaign.list --input tmp/codex/gi-delivery/honor-campaign-spend.example.json --all-pages --output tmp/codex/gi-delivery/honor-campaign-spend.json
```

`query_fields` 只请求 `date`、`campaign_id`、`campaign_name`、`stat_cost`。其他平台先运行
`capabilities search "campaign report" --platform bytedance`，只有搜索结果同时满足
`stability=stable`、`executable=true` 且 health 未阻断时才能替换。

## 异步导出：创建、等待、下载

当前 22 条导出 route 是 census 契约规模，不等于 22 条都可创建。现在已在线确认并开放
创建的是 `export.material.report.start`，输出 XLSX 素材聚合报表。异步导出保持独立 catalog，
但已可完全从 CLI 发现和描述：

```powershell
gravity insight export list-capabilities
gravity insight export describe export.material.report.start
```

这两条纯离线命令返回可调用状态、完整 input schema、列码/表头、规模控制、经验证 example 和
调用顺序。先让发现器选择一组真实非空的 App、平台和日期，不得猜 App：

```powershell
gravity insight discover-nonempty material.report.query --request-budget 12
```

全局 `app.list` 的 projection 已登记 `data.list[].platform`，但上游当前
返回的 App 行省略该字段，不是 projection 漏字段；平台来自业务上下文，或用
`capabilities search "app list" --platform <platform>`
发现平台专属 App operation，再由同条件 preflight 验证。只有发现结果为 `unblocked`，才用返回
的 `inputs` 执行 `material.report.query` 1 行读取；公开 `data.list` 非空后才可创建，空结果禁止
start。仅当 warning 说明未登记字段已
省略且 `status=contract_changed_additive` 时才允许继续；不得消费公开投影以外的字段。创建前先
离线执行 `validate export.material.report.start --input <request.json> --render-wire`；它校验 input，
不创建任务，`--columns` 和 idempotency key 留给 start 校验。随后联网创建；`--columns` 必须与
JSON 的 `export_col_list` 同序一致：

```powershell
gravity insight export start export.material.report.start --input <request.json> --columns file_name,gravity_material_id,stat_cost,ctr,convert_rate,AppRealRegisterCnt,AppGamePayUserCntStandardAtv --idempotency-key analyst-material-<yyyymmdd>-<unique-suffix>
```

从返回 envelope 记录 `job_id`，等待 READY：

```powershell
gravity insight export wait <job-id> --operation-id export.material.report.start --interval 2 --timeout 300
```

READY 后下载并校验 XLSX：

```powershell
gravity insight export download <job-id> --operation-id export.material.report.start --output <material-report.xlsx> --timeout 300
```

重要限制：

- 上游忽略 create 请求里的 `page_size`，会导出过滤条件命中的完整结果。用单 App、单平台、
  窄日期范围控制规模。
- create wire 没有已证明的上游幂等字段。SDK 的 idempotency key 不能证明服务端去重；
  创建结果不确定时先运行 `export list`，不要直接再建一份。
- 等待超时不会取消任务。收到 `EXPORT_TIMEOUT` 后按 `next_action` 用原 job 恢复。
- `cancel` 成功只表示 `CANCEL_REQUESTED`，不是终态。上游任务可能随后变成 READY；必须继续
  `status` 或 `wait`，直到看到真实终态。

恢复命令：

```powershell
gravity insight export list --page 1 --page-size 100
gravity insight export status <job-id> --operation-id export.material.report.start
gravity insight export cancel <job-id> --operation-id export.material.report.start
```

`export list` 的 v2 job 包含公开 `operation_id`、task type、任务名指纹，以及只列字段名、不回显
参数值的 `request_summary`。创建结果不确定时用 operation、创建时间和任务名指纹恢复映射。

批量 read 的 wrapper 不靠错误探测：先运行 `gravity insight batch schema`。
每项只允许 `operation_id/input|inputs/request_id/read_all`；顶层 envelope 给出总数、成功/失败数。
退出码取失败 item 中最高类别：local 4 > upstream 3 > caller 2。

## 14 个错误码怎么处理

| code | 含义 | 处理 |
| --- | --- | --- |
| `UNKNOWN_OPERATION` | operation ID 不存在 | read 用 `capabilities search`；export 用 `export list-capabilities` |
| `INPUT_INVALID` | 字段、类型、枚举或组合不合法 | read 用 `capabilities describe/validate`；export 用 `export describe` 后重新 `validate` |
| `PARENT_REQUIRED` | 缺父资源 ID | 按 `required_parent` 先查父 operation |
| `AUTH_MISSING` | 没有 token 或账密 | `auth status`，请管理员配置凭据 |
| `AUTH_REJECTED` | 凭据被上游拒绝 | `auth refresh` 后最多重试一次 |
| `PERMISSION_UNAVAILABLE` | 当前账号缺权限 | 申请对应 Gravity 权限，不循环重试 |
| `RATE_LIMITED` | 被限流 | 等 `retry_after_ms`，原请求重试一次 |
| `UPSTREAM_UNAVAILABLE` | 上游超时或 5xx | 重试一次；仍失败再运行 `doctor --live` |
| `CONTRACT_CHANGED` | 已确认上游契约变化 | 停止自动化，等待工程重新核验 |
| `UNSUPPORTED` | 当前表面不支持该行为 | 按 `describe` 改用支持的入口 |
| `NOT_IMPLEMENTED` | 已登记但尚未实现 | 搜索可执行替代能力 |
| `PAGINATION_LIMIT` | 达到页数或条数保护 | 落盘/NDJSON，并用 `next_page_input` 续读 |
| `EXPORT_TIMEOUT` | 导出等待超时 | 恢复原 job，不重复创建 |
| `LOCAL_IO_ERROR` | 本地文件或目录错误 | 修正读写路径和权限 |

不要按 `message` 文本写自动化分支。先看 `retryable`；只有为 `true` 才考虑重试，并优先
执行 `next_action`。`INPUT_INVALID` 直接读取 `error.field` 定位字段。退出码 `2/3/4`
分别表示调用方、上游、本地错误。输入、认证、权限或本地文件错误不会改变 capability
health；health 只反映成功读取和真实上游/契约证据。

## 什么时候找工程

- 搜索结果是 `draft_catalog_only`、`experimental` 或 `executable=false`。先用 `describe`
  把 operation ID、`blockers` 和 `next_action` 一并发给 Gravity Insight SDK 维护方；普通
  SDK 使用者不能从 read 命令自行解锁，等待维护方验证并发布 executable 能力。
- `blockers` 是 `empty_sample`：先运行 `discover-nonempty`；只有 `confirmed_empty` 才能说契约可表达
  的合理组合都空，`undetermined` 需要工程补候选维度或父资源证据。
- blocker 要求父资源，但父 operation 在当前账号返回空：需要能看到父资源的账号或明确 ID。
- OpenAPI draft 提示 developer credential：现有网页登录态不能替代 `app_key/sign`。
- health 是 `upstream_changed`，或出现 `CONTRACT_CHANGED`。
- 需要的维度、指标、过滤符不在 `describe.input_schema`；不要私自塞额外字段。
- 需要 mutation。414 个 write reservation 只是防遗漏登记，Mutation SDK 尚未开放。

导出的协议、安全校验和恢复细节另见 `docs/guides/export-guide.md`。
