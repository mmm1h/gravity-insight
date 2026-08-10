# Gravity Insight 导出指南

Gravity Insight 导出使用独立 effect，不经过只读 PolicyEngine 的路径例外。契约共登记 22 条路由；截至 2026-08-09，8 条完成在线验证，其中 5 条来自首轮，新增完成 `origin_event_data/evaluate_data`、`segment/download_result` 和 `user/event/list/download`。另有 7 条取得部分或失败证据，7 条因副作用或契约不确定而未调用。调用方以 `gravity insight export list-capabilities` 和 `export describe <operation-id>` 为公开权威，不读取仓库内部 contract。

## 可执行范围

生产 SDK 当前只开放素材聚合报表创建，以及任务列表、进度、取消和任务类型查询。新增完整跑通的两个用户级文件导出已补齐 XLSX 表头 allowlist，但仍保持 `executable=false`，必须经过明确的隐私批准后才能开放。只完成创建、得到 FAILED 或返回 `code=1004` 的路由继续保持 unverified 和 fail-closed。

从不知道导出存在开始，只需：

```powershell
gravity insight --help
gravity insight export list-capabilities
gravity insight export describe export.material.report.start
gravity insight validate export.material.report.start --input <request.json> --render-wire
```

顶层 help 暴露独立 export catalog；list 显示 effect/可调用状态；describe 显示字段 required/optional/
type/default、columns 语义、规模控制、已验证 example 与完整 workflow；通用 `validate` 会自动委派
到 export catalog，离线校验 create input 和 wire，不创建任务。

任务中心 effect：

- `export_job_create`：创建一次任务；上游没有已知幂等字段，创建请求不自动重试。
- `export_status`：估算、列表、任务类型和进度查询。
- `export_download`：由一次已消费的 READY 状态 receipt 派生，只绑定一个 job、URL、路径和 5 分钟本地授权期。
- `export_cancel`：仅请求取消；上游接受不等于任务最终停止。

## 副作用风险顺序

首轮 5 条之外的 17 条由 15 个 `export_job_create`、1 个 `export_status` 和 1 个
`export_download` effect 组成；其中 3 条后来完成在线验证，因此这 17 条不能再统称为
“未完成”。它们按“是否创建任务、输出敏感度、过滤边界是否明确、是否可能通知外部或
产生凭据型结果”从低到高排序如下：

1. `origin_event.evaluate`：只返回估算总数，不创建任务。
2. `openapi.event.result`：语义上读取既有结果，但 method、认证和结果协议未知，未调用。
3. `material.review.start`：可收窄到一个素材 ID。
4. `admin.company_amount.start`：内部业务数据，管理员上下文与请求体不明确。
5. `report.config.start`：多种报表共用一路由，无法证明单次请求的范围。
6. `segment.result.start`：单分群/版本，但输出用户标识。
7. `segment_user_detail.start`：单分群和字段投影，仍是用户级数据。
8. `user_detail.start`：单 App/单日用户详情。
9. `monetization_detail.start`：单 App/单日变现明细。
10. `user_event.start`：单用户/单日/单事件，内容敏感但范围最窄。
11. `pay_event.start`：用户级支付事件，敏感度高于一般行为事件。
12. `origin_event.start`：原始事件数据任务，可能包含广泛事件属性。
13. `stream_event.start`：实时事件范围无法可靠界定。
14. `user.open_app.start`：账号/App 开通信息，字段和权限边界未确认。
15. `openapi.event.submit`：method、开发者认证和请求体均未知。
16. `promotion.click_url.start`：结果可能包含凭据型跟踪 URL，未获准投影。
17. `subscribe.start`：可能发送邮件或推送，绝对禁止在线探测。

## 22 条路由状态

| 路由 | 本轮是否调用 | 实测 method / 响应与状态 | 文件或未调用原因 |
|---|---:|---|---|
| `openapi/event/submit_task` | 否 | method/认证未知 | 未知请求可能创建用户级任务 |
| `openapi/event/query_result` | 否 | method/认证未知 | 结果文件协议未知 |
| `admin_report/query_company_amount/export` | 否 | 登记为 POST | 管理员上下文和请求体不能安全界定 |
| `origin_event_data/evaluate_data` | 是 | POST；ISO 日期返回 `code=0,data.total` | 不生成文件；时间戳格式返回 `code=1004` |
| `origin_event_data/submit_task` | 是 | POST；HTTP 200/`code=1004`，无 task_id | 参数不成立，不是无数据或无权限 |
| `monetization_detail/download` | 是 | POST；`code=0,data.task_id`；首次轮询状态 3 FAILED | 未产生可下载文件 |
| `segment/download_result` | 是 | POST；`code=0,data.task_id`；状态 2 READY | XLSX，4,939 字节，1 行，1 列 `用户ID` |
| `segment/user/detail/download` | 是 | POST；`code=0,data.task_id`；状态 3 FAILED | 未产生可下载文件 |
| `stream/event/list/download` | 否 | 登记为 POST | 前端绑定和请求体未解析，实时范围不可控 |
| `user/detail/download` | 是 | POST；`field_map` 对象后 `code=0,data.task_id`；状态 3 FAILED | 未产生可下载文件 |
| `user/event/list/download` | 是 | POST；`code=0,data.task_id`；状态 2 READY | XLSX，4,999 字节，0 行，5 个固定表头 |
| `user/pay_event/download` | 是 | POST；`field_map` 对象后 `code=0,data.task_id`；状态 3 FAILED | 未产生可下载文件 |
| `datareport/material_get/export` | 上轮已验证 | POST；`data.task_id`；状态 2 READY | XLSX，21,728 字节，361 行，7 列 |
| `asset/material/media/review_list/export` | 是 | POST；单素材 ID 返回 `code=0,data.task_id`；状态 3 FAILED | 未产生可下载文件 |
| `task/download/list` | 上轮已验证 | POST；`data.list/data.page_info` | 元数据，无文件 |
| `task/download/progress` | 上轮已验证 | GET query `task_id`；返回状态和 download_url | 元数据；GET JSON body 会 `code=1004` |
| `task/download/cancel` | 上轮已验证 | GET query `task_id`；`code=0` | 仅 CANCEL_REQUESTED，不是终态 |
| `task/download/task_type/list` | 上轮已验证 | GET；返回 13 项列表 | 元数据，无文件 |
| `user/open_app/download` | 是 | POST；HTTP 200/`code=1004`，无 task_id | 参数不成立，请求体仍未验证 |
| `user/promoted_object/click_url/export` | 否 | 登记为 POST | 跟踪 URL 可能具有凭据性质，缺少获准投影 |
| `datamanageconfig/report/export` | 否 | 登记为 POST | 多报表家族共用，无法绑定唯一 payload |
| `subscribe/export` | 否 | 登记为 POST | 可能触发对外通知，禁止调用 |

`code=1004` 明确归类为参数错误；状态 3 明确归类为任务创建成功后处理失败。两者都不能写成“无数据”。空 XLSX 且 READY 才能归类为“查询成功但无数据”。

## 已确认请求形状

`origin_event.evaluate` 与 `origin_event.start` 使用 `app_id/task_name/task_type/time_range/event_name_list/cond_logic/conditions`；日期必须为 ISO calendar date。只有 evaluate 的该形状在线成功，start 当前仍未验证。

`segment.result.start` 使用 `app_id/segment_id/version_id/task_name`。`segment_user_detail.start` 使用 `field_map/task_name/app_id/tmp_segment_id/segment_id`。

`user_detail.start`、`monetization_detail.start` 和 `pay_event.start` 的 `field_map` 必须是“字段码到展示名”的对象，不是字段码数组。修正后创建响应均为 `code=0,data.task_id`，但三条任务都在首次轮询进入状态 3，因此不能据此推定实际文件表头。

`user_event.start` 使用 `app_id/client_id/desc/group_by/event_list/date_list/page_info/query_item_list/task_name`。`page_info.page_size` 只属于查询形状，不应当作导出规模上限。

素材聚合报表的已验证最小请求：

```json
{
  "data_dims": ["material"],
  "date_dims": "total",
  "metrics_list": ["stat_cost", "ctr", "convert_rate"],
  "gravity_metrics_list": ["AppRealRegisterCnt", "AppGamePayUserCntStandardAtv"],
  "stat_list": [],
  "filters": [
    {"field": "ad_platform", "operator": "EQUALS", "values": ["bytedance"]},
    {"field": "app_id", "operator": "IN", "values": ["<app-id>"]}
  ],
  "date_list": ["<start-date>", "<end-date>"],
  "relate_dims": [],
  "order_by": [],
  "page": 1,
  "page_size": 1,
  "export_col_list": [
    "file_name", "gravity_material_id", "stat_cost", "ctr", "convert_rate",
    "AppRealRegisterCnt", "AppGamePayUserCntStandardAtv"
  ],
  "task_name": "agent-material-export"
}
```

App、平台和日期不是可移植默认值。全局 `app.list` 的 projection 已登记 `platform`，但上游当前
返回的 App 行省略该字段，因此不能从全局列表自动配对。平台应由调用方业务上下文
确定，或先用 `capabilities search "app list" --platform <platform>` 发现平台专属 App operation，
再用以下报表预检确认本次 App/平台/日期组合。保存 describe 返回的 example 后，先按
`examples[0].preflight` 用 `material.report.query --max-pages 1 --max-items 1` 检查同一组
App/平台/日期；只有命令退出 0 且公开投影的 `data.list` 非空才允许 start。此检查仅在 warning
说明“未登记的 list item 字段已省略”且 `status=contract_changed_additive` 时允许继续，且只用于
确认存在性、只消费公开投影。其他 warning、非零退出、错误或
`health=upstream_changed|blocked` 均须停止。空选择会被上游接受
创建但任务随后进入 FAILED，因此不能把“start 返回 job_id”当作端到端成功。

替换 example 后先离线校验；`validation_scope` 会明确列选择和幂等键仍在 start 校验：

```powershell
gravity insight validate export.material.report.start --input <request.json> --render-wire
```

## 规模、状态与恢复

`page_size` 不限制文件总量，上游会忽略它并导出过滤条件命中的完整结果。控制规模只能依靠最短日期窗口、单 App、单平台、单分群、单用户或单素材 ID；无法证明这些边界的路由不要调用。

轮询间隔不得低于 2 秒，单任务等待不超过 5 分钟。状态 2 是 READY，状态 3 是 FAILED。`cancel` 返回 `code=0` 只表示 CANCEL_REQUESTED；实测任务曾短暂显示状态 4 后继续成为 READY。超时不自动取消。

创建 wire 没有已知上游幂等字段或 header。创建阶段只发一次且不自动重试；结果不确定时先查 `export list`，不要重复创建。

## 文件与隐私

实测文件为 XLSX/OOXML，MIME 是 `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`。READY 返回无签名 query、无可解析有效期的 OSS HTTPS URL，路径位于租户 `/excels/` 前缀。响应有 Content-Length、ETag、Last-Modified 和 Content-MD5，没有 SHA-256 头；SDK 流式计算 SHA-256。

用户级完整验证的表头 allowlist：

- `segment.result.start`：`用户ID`。
- `user_event.start`：`客户(client_id)`、`用户注册时间`、`事件发生时间`、`事件`、`事件属性`。

两条路由都用“比实际少一列”的 allowlist 验证过拒绝，再用精确 allowlist 验证通过。文件只落临时目录，检查 schema、行数和工作表数后立即删除。创建后 FAILED 的路由没有文件，无法执行文件级闸门，不能声称隐私验证完成。

下载前校验 HTTPS host、路径前缀、一次性 effect receipt、Content-Length、MIME、ZIP magic、归档路径和膨胀限制；下载后检查所有 worksheet 的实际表头、重复列、必需列及危险 OOXML 部件。未知表头返回 `CONTRACT_CHANGED`，临时文件会清理，目标文件不会出现。

## 命令

前三条纯离线；start/status/wait/download/cancel/list 会访问 Gravity。联网前先获得授权，
从 describe 的 example 构造请求，并把模板参数替换为 caller 已选择的真实值。

```text
gravity insight export list-capabilities
gravity insight export describe <operation-id>
gravity insight validate <operation-id> --input <request.json> --render-wire
gravity insight export start <operation-id> --input <request.json> --columns <column-codes> --idempotency-key <key>
gravity insight export status <job-id> --operation-id <operation-id>
gravity insight export wait <job-id> --operation-id <operation-id> --interval 2 --timeout 300
gravity insight export download <job-id> --operation-id <operation-id> --output <file.xlsx> --timeout 300
gravity insight export cancel <job-id> --operation-id <operation-id>
gravity insight export list --page 1 --page-size 100
```

只有 `export list-capabilities` 同时显示 `effect=export_job_create`、`contract_status=verified`、
`currently_callable=true` 的 operation 可用于 start。目录中可见不代表已经开放。

`export list` 返回 `gravity-insight.export-list.v2`：每个 job 带 `operation_id`、
`operation_mapping`、`task_type`、state、创建时间和 `request_summary`。摘要只含字段名、任务名
SHA-256 短指纹与长度，`parameter_values_redacted=true`；不会回显 App、日期、过滤值或任务名。
