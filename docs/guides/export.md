# 导出指南

导出是独立 effect，不是普通 read 的大分页别名。默认使用一次 `export run` 完成创建、轮询、
下载、隐私/文件 schema 校验和原子提交；分阶段命令只用于恢复和人工控制。

## 已知导出：一次调用

当前唯一可直接创建的导出是 `export.material.report.start`。准备好 `describe` 合同中的完整
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
写进该文件。`--columns` 必须与 input 的 `export_col_list` 使用相同代码和顺序；不要从自然语言
推断业务输入、列或日期。先用离线 `gravity export describe export.material.report.start` 取得
完整 schema、verified example、列映射和规模限制。

## 未知导出：两次调用

```powershell
gravity agent "material report export"
# 审阅 export capability card，补齐 input/columns/idempotency_key/output 后执行 next.argv
```

第一次调用只做离线发现，第二次是卡片给出的 `gravity export run`。自然语言不会自动创建任务。
导出卡直接交接到 run，不生成 Plan node，也不能放入 Plan v1。批量 Agent 问题复用同一份导出
inventory。

Agent 只暴露 `currently_callable=true` 且 `effect=export_job_create` 的卡。当前这会且只会得到
`export.material.report.start`；task status/cancel 等支持路由不是创建候选。所有 Analysis 导出仍
不可调用，其中隐私 blocked 的合同也不会获得 executable 卡。用 `export list-capabilities` 查看
这些边界，不要把 catalog 条目当成可执行能力。

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
- 取消任务前确认 operation 支持 cancel；取消是上游写操作，且请求取消不等于已经终止。
