# 导出指南

导出是独立 effect，不是普通 read 的大分页别名。默认使用一次 `export run` 完成创建、轮询、
下载、隐私/文件 schema 校验和原子提交；分阶段命令只用于恢复和人工控制。

## 已知导出：一次调用

当前可直接创建的导出有八个：素材报表，以及 Analysis 的单用户事件、
分群结果、分群用户明细、用户明细、付费事件、变现明细和原始事件。准备好 `describe` 合同中的完整
request 后，直接执行：

```powershell
gravity export run export.material.report.start `
  --input material-export.json `
  --columns file_name,gravity_material_id,stat_cost,ctr,convert_rate,AppRealRegisterCnt,AppGamePayUserCntStandardAtv `
  --idempotency-key material-20260812-001 `
  --output D:\exports\material-20260812.xlsx `
  --timeout 300
```

`--output` 是最终 XLSX 的显式目的路径；命令的 JSON envelope 仍写 stdout，绝不会把 JSON
写进该文件。`--columns` 填 `describe.columns.allowed_codes`（请求代码，如
`ClientID,CreateTime` / `AdEventTime,ClientID`），不要填文件表头
（`客户ID,注册时间`）。对素材报表，`--columns` 还必须与 input 的 `export_col_list`
使用相同代码和顺序。不要从自然语言推断业务输入、列或日期。先用离线
`gravity export describe <operation-id>` 取得完整 schema、verified example、
列映射和规模限制。`export run` 用请求代码做创建前校验，用文件表头做下载后校验。

单用户事件导出先用相同 App、ClientID 和单日执行一次第一页 `analysis.user_event.list`；只有
`event_timeline` 含非空列表时，才精确复制其授权 body 并追加 `task_name`：

```powershell
gravity export describe export.analysis.user_event.start
gravity export run export.analysis.user_event.start `
  --input user-event-export.json `
  --columns "客户(client_id),用户注册时间,事件发生时间,事件,事件属性" `
  --idempotency-key user-event-20260816-001 `
  --output D:\exports\user-event-20260816.xlsx `
  --timeout 300
```

这五列顺序固定；`describe.columns.file_schema` 同时给出 worksheet、单元格存储类型和逻辑类型。
App、ClientID、日期、事件名和结构化条件都必须来自调用方或成功父读取，不从自然语言推断。

其余五个 Analysis creator 分别使用：

- `export.analysis.segment.result.start`：`用户ID`；
- `export.analysis.segment_user_detail.start`：`ClientID,CreateTime` 对应 `客户ID,注册时间`；
- `export.analysis.user_detail.start`：`ClientID,CreateTime` 对应 `客户ID,注册时间`；
- `export.analysis.pay_event.start`：`ClientID,TraceID` 对应 `客户ID,订单ID`；
- `export.analysis.monetization_detail.start`：`AdEventTime,ClientID` 对应 `事件发生时间,客户ID`；
- `export.analysis.origin_event.start`：固定五列 `客户ID(client_id),用户注册时间,事件发生时间,事件,事件属性`，文件是 gzip CSV。

同名两列不代表两个族共用文件合同；每个 route 在 `describe.columns.file_schema` 中
保持独立的 worksheet、空文件、表头、存储类型和逻辑类型证据。四个族都要先用同一
App/日期或分群做非空父读取，再精确复制请求条件。

## 未知导出：两次调用

```powershell
gravity agent "material report export"
# 审阅 export capability card，补齐 input/columns/idempotency_key/output 后执行 next.argv
```

第一次调用只做离线发现，第二次是卡片给出的 `gravity export run`。自然语言不会自动创建任务。
导出卡直接交接到 run，不生成 Plan node，也不能放入 Plan v1。批量 Agent 问题复用同一份导出
inventory。

Agent 只暴露 `currently_callable=true` 且 `effect=export_job_create` 的卡。当前会得到上述八个
creator；task status/cancel 等支持路由不是创建候选。`origin_event` 先用 `evaluate_data` 确认 `data.total > 0`，再提交 create；`analysis.event.list.yesterday_count` 不能当门。
`monetization_detail` 的 READY XLSX 已通过保留全部安全规则的 route-scoped 192 MiB 展开上限。
task list/progress/file 仍无任务绑定 total；SDK 在 create 前用同一 App/日列表第一页钉住
`page.total_items`，标注 `create_time_preflight`。钉住总量大于 100 万且文件恰为 1,000,000 行时
结果是 `truncated`，并同时给出已知总量与文件行数；异步重读列表不得当分母。
四个已晋升 Analysis 族已分别完成文件行数与受管总数对账（1/1、1/1、255/255、217/217）。
`stream_event` 的前端按钮只做客户端
表格序列化，未调用声明的 loader，因此它不是待探测的 SDK 服务端缺口。用
`export list-capabilities` 查看边界，不要把 catalog 条目当成可执行能力。

## 超时和分阶段恢复

`run` 创建任务只尝试一次，超时不会自动取消。结果含 `job_id` 时，从该任务继续，不要再次
创建：

```powershell
gravity export status <job-id> --operation-id export.material.report.start --timeout 300
gravity export wait <job-id> --operation-id export.material.report.start --interval 2 --timeout 300
gravity export download <job-id> --operation-id export.material.report.start `
  --output D:\exports\material-20260812.xlsx --timeout 300
```

只有需要显式控制阶段时才用 `export start`。其 `--input/--columns/--idempotency-key` 与 run
相同，随后使用上面的 wait/download。若进程中断且没有可靠的 `job_id`，先运行
`gravity export list --page 1 --page-size 100` 核对任务，再决定是否创建；不得靠重跑产生重复
任务。`task_name` 和 idempotency key 应是可追踪但不含凭据或用户级值的调用方标识。

## 安全与验收

- 只执行 `describe.currently_callable=true` 的 create operation；创建会改变上游任务状态。
- 使用单 App、单平台和已确认非空的最短日期窗；`page_size=1` 不限制导出总行数。
- 目的路径必须明确、可写且位于受控目录；不要写入仓库、共享目录或对话输出。
- 合同漂移、隐私校验、格式/扩展名、host/path、大小或 schema 校验失败时均不提交目标文件。
- 成功后核对 `file.path`、大小、哈希、格式、行数和 schema；`status=partial` 不代表完整导出。
- `completion_status` 只使用 `empty / partial / truncated / expired / complete / gap`；只有原子提交、行数大于 0、且未触达已知上游行上限的完整文件才是 `complete`，头部完整但 0 数据行是 `empty`。`monetization_detail` 在钉住总量大于 1,000,000 且文件恰为 1,000,000 行时为 `truncated`，信封同时给出 `known_total_items` 与 `file.rows`。
- 取消任务前确认 operation 支持 cancel；取消是上游写操作，且请求取消不等于已经终止。
