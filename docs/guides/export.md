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
- `export.analysis.user_detail.start`：保留必填 `ClientID,CreateTime`，其余已实测字段以 `describe.columns` 为准；自定义字段须匹配当前 App 的 live metadata；
- `export.analysis.pay_event.start`：`ClientID,TraceID` 对应 `客户ID,订单ID`；
- `export.analysis.monetization_detail.start`：`AdEventTime,ClientID` 对应 `事件发生时间,客户ID`；
- `export.analysis.origin_event.start`：固定五列 `客户ID(client_id),用户注册时间,事件发生时间,事件,事件属性`，文件是 gzip CSV。

同名两列不代表两个族共用文件合同；每个 route 在 `describe.columns.file_schema` 中
保持独立的 worksheet、空文件、表头、存储类型和逻辑类型证据。四个族都要先用同一
App/日期或分群做非空父读取，再精确复制请求条件。

## 未知导出：两次调用

用户明细 route 的 `field_map` 与 `--columns` 按集合精确匹配，文件按 code 字典序输出，
不承诺输入插入序。下载逐列校验选定表头和 XLSX 存储类型，字符串标识不转换为数值，
Version 只接受已观察的整数数值，时间保留文本。缺列触发 schema 错误；返回空值计入
`file.empty_values_by_column`；少行和截断由独立的 `completeness` 判定。
create 前同 App、条件、逻辑与字段集的第一页 `page.total_items` 是唯一分母，不做事后重读。
属性标注 `current-at-extraction`，不得推断历史分层、曝光、余额或配置。

```powershell
gravity agent "material report export"
# 审阅 export capability card，补齐 input/columns/idempotency_key/output 后执行 next.argv
```

第一次调用只做离线发现，第二次是卡片给出的 `gravity export run`。自然语言不会自动创建任务。
导出卡直接交接到 run，不生成 Plan node，也不能放入 Plan v1。批量 Agent 问题复用同一份导出
inventory。

Agent 只暴露 `currently_callable=true` 且 `effect=export_job_create` 的卡。当前会得到上述八个
creator；task status/cancel 等支持路由不是创建候选。`origin_event` 先用
`gravity export evaluate export.analysis.origin_event.evaluate` 确认 `estimated_rows > 0`，
再提交 create；不要走 `gravity run`，该 selector 不在 Insight read 注册表。
`analysis.event.list.yesterday_count` 不能当门，该字段在 7/7 App 上均为 0，而投放中 App 的
`attribution.attribution.query` 同日有正 `AppRealRegisterCnt`。`describe` / 读取 `warnings`
会指向 `attribution.attribution.query` 或 `evaluate_data`。
`monetization_detail` 的 READY XLSX 已通过保留全部安全规则的 route-scoped 192 MiB 展开上限。
task list/progress/file 仍无任务绑定 total；SDK 在 create 前用同一 App/日、**同一 `field_map` 列集**的列表第一页钉住
`page.total_items`，标注 `create_time_preflight`。该 route 的 `total_items` 随 `fields` 变化：26 列产品字段与导出两列不是同一个分母。钉住总量大于 100 万且文件恰为 1,000,000 行时
结果是 `truncated`，并同时给出已知总量与文件行数；异步重读列表不得当分母。
四个已晋升 Analysis 族已分别完成文件行数与受管总数对账（1/1、1/1、255/255、217/217）。
`stream_event` 的前端按钮只做客户端
表格序列化，未调用声明的 loader，因此它不是待探测的 SDK 服务端缺口。用
`export list-capabilities` 查看边界，不要把 catalog 条目当成可执行能力。

## 原始事件过滤边界

`origin_event.evaluate` 与 `origin_event.start` 共享版本化输入 schema。
`export describe` 发布 `gravity.export.origin-event-condition.v1` 条目定义：
这是未验证的客户端草案子集，不表示上游接受这些过滤写法。当前执行合同
只允许 `conditions: []`（`max_items: 0`）；非空条件即使符合草案也会在任何
请求前以 `EXPORT_CONDITIONS_UNSUPPORTED` 拒绝，形状错误为 `INPUT_INVALID`。
错误包含字段路径和下一步建议。需要业务过滤时应保留过滤需求、等待维护者
取得真实上游证据并发布新契约；删除过滤器不等于获得等价结果。

仅就 `origin_event.evaluate` / `origin_event.start`（含 run 创建阶段）而言，
上游非成功语义状态为 `EXPORT_SEMANTIC_REJECTED`；成功状态同时带非空
`extra.error` 为 `EXPORT_RESPONSE_CONTRADICTED`，均停止执行。未知拒绝的
责任归属保留 `diagnostics.responsibility=unclassified`；`category=local` 仅表示
本地尚无可用的责任分类，不指称调用方或上游有错。诊断仅含固定原因与安全数字状态，
不回显原始错误文本。真实文件结构漂移仍为 `CONTRACT_CHANGED`。

`export.task.list` 属于独立操作族，仍有历史遗留的响应分类缺口：非成功状态、
矛盾成功和非标量 code 尚未统一处理。已列为独立后续跟进，不在 Issue #218 范围内；
上述两个原始事件操作的分类保证不应外推至任务列表。

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

用户明细分阶段恢复还必须传 `--completeness <receipt.json>`，文件内容为该任务 `start`
返回的 `completeness` 对象；SDK 使用同名参数。`run` 超时或下载失败也保留该对象，
不可使用另一任务的收据或事后列表总数。新投影空文件尚无在线证据；本地头部校验与零总数
匹配测试不代表新的线上实测。空文件但钉取总数非零时是 `partial`。

- 只执行 `describe.currently_callable=true` 的 create operation；创建会改变上游任务状态。
- 使用单 App、单平台和已确认非空的最短日期窗；`page_size=1` 不限制导出总行数。
- 目的路径必须明确、可写且位于受控目录；不要写入仓库、共享目录或对话输出。
- 合同漂移、隐私校验、格式/扩展名、host/path、大小或 schema 校验失败时均不提交目标文件。
- 成功后核对 `file.path`、大小、哈希、格式、行数和 schema；`status=partial` 不代表完整导出。
- `completion_status` 只使用 `empty / partial / truncated / expired / complete / gap`；只有原子提交、行数大于 0、且未触达已知上游行上限的完整文件才是 `complete`，头部完整但 0 数据行是 `empty`。`monetization_detail` 在钉住总量大于 1,000,000 且文件恰为 1,000,000 行时为 `truncated`，信封同时给出 `known_total_items` 与 `file.rows`。
- 取消任务前确认 operation 支持 cancel；取消是上游写操作，且请求取消不等于已经终止。
