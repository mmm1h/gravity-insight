# 快速上手

完成本页后，你应能登录 Gravity、用两次顶层调用完成首条事件分析，并继续发现其他只读能力。

## 1. 安装

要求 Python 3.11 或更高版本。

```powershell
python -m pip install -e .
gravity --help
```

如果 `gravity` 不在 `PATH`，使用等价入口：

```powershell
python -m gravity_sdk --help
```

## 2. 首次登录

在交互式终端运行：

```powershell
gravity
```

按提示输入 Gravity 用户名和密码。SDK 会验证登录，并在用户私有目录维护生成的会话 token。`.env.gravity.local` 只需要：

```dotenv
GRAVITY_USERNAME=your-account
GRAVITY_PASSWORD=your-password
```

不要配置 `GRAVITY_AUTH_TOKEN` 或 `GRAVITY_SDK_HOME`，也不要提交本地凭据文件。

检查状态：

```powershell
gravity insight auth status
```

`--help`、operation 搜索、`find`、recipe 检查和本地 metadata 查询不需要凭据，也不会先弹出向导。首次执行需要 Gravity 客户端的命令时才会进入设置流程。

## 3. 离线自检

```powershell
gravity insight --dry-run
gravity sql --dry-run
gravity census --smoke
```

这些命令验证本地合同，不应连接 Gravity。

## 4. 两次调用完成首条事件分析

先由你明确选择 App、日期窗和精确物理事件名；入口不会静默选择默认项目。然后运行：

```powershell
gravity analysis bootstrap `
  --app <selected-app-id> `
  --start 2026-08-01 --end 2026-08-07 `
# 或：--start yesterday --end yesterday；结果含 resolved_date_window
  --target <physical-event> --plan-output first-analysis-plan.json
# 审阅 Plan 中的 App、日期、事件与 metadata 指纹
gravity plan run --input first-analysis-plan.json
```

第一次调用按需登录和同步选定 App 的四类 metadata，只允许每类第一页，然后离线确认事件并写出已
dry-run 验证的 Plan；它不执行分析。第二次使用 Plan 固定的 catalog 快照做合同校验，不重新读取
live metadata，只发业务查询。空会话与空目录的完整上限是 `6 + 1 = 7 HTTP`，CLI 不自动重试。

缺 App、日期或事件时，错误只返回一个确定的 `next_action`，不会代选；metadata 超过第一页时也不会
自动扩量，而是要求你先审阅普通 sync 的更大预算。完整失败分支见[十分钟路径](agent-skills/ten-minute-path.md)。

## 5. 发现并执行其他查询

不要猜 operation ID。第一次盘点完整能力时先走三层离线目录：

```powershell
gravity agent-catalog categories
gravity agent-catalog category app
gravity agent-catalog describe app.list
```

进入具体问题后，Agent 用两条命令完成发现、描述和执行：

```powershell
gravity agent "app"
# 选择 capability card，并执行其中的 next.argv
gravity run app.list --max-items 20
```

`gravity agent` 完全离线，优先返回匹配的 workspace recipe，并用少量 stable operation 补足
候选；每张卡都带必填参数或字段及可复制 argv。需要查看 operation 的完整 schema 时再使用
`operations describe`；输入可用内联 JSON，只改少数字段时可追加 `--set`：

```powershell
gravity insight operations describe analysis.event.list
gravity run analysis.event.list --input '{"app_id":"101"}' --set page_size=100
```

`analysis.event.list` 的 `yesterday_count` 不能当“这个事件有没有数据”的门；`describe` 的
`unreliable_item_keys` 和读取结果的 `warnings` 会指向
`attribution.attribution.query` 或 `analysis.origin_event.evaluate_data`。
`app_id` 按该 operation 合同声明的类型传入；SDK 只把正整数与其数字字符串归一化到声明类型。
跨 route 的声明类型见 [App ID wire types](reference/sdk.md#app-id-wire-types)。

`run` 已在一个进程完成输入校验、父资源处理、读取和诊断；不需要先机械调用 `validate`。

项目提供 `gravity.toml` 时，也可以让 Resolver 在一个进程里完成绑定、校验、父资源检查、执行和诊断：

```powershell
gravity run @<recipe-name> --start 2026-08-01 --end 2026-08-07
gravity run <operation-id> --app <workspace-alias> --input <json>
```

只有 `run` 报告 recipe stale 时再执行 `gravity recipe check <recipe-name>`；纯增量合同用 `gravity recipe accept-contract <recipe-name>` 重钉指纹。

workspace 可由顶层 `--workspace`、显式 API 调用、`GRAVITY_WORKSPACE` 或 cwd 向上查找选中。SDK 只读该文件；执行回执写入用户缓存，不写项目目录。配置格式见 [Workspace 参考](reference/workspace.md)。

## 6. 同步本地元数据目录

先用明确的离线 status 入口检查私有 catalog；它不构造客户端、不读取生产，也不创建空库：

```powershell
gravity metadata status --app-id <selected-app-id>
```

`missing/not_synced/partial/stale/ready/incompatible` 分别说明本地目录缺失、该 App 未同步、存在失败、
超过 freshness 阈值、可用或 schema 不兼容；每个已同步 App 同时报告时间、年龄、过期时间、四类对象数
和失败数。默认 freshness 阈值 24 小时，可用 `--max-age-hours` 覆盖。

冷目录先做零网络估算，再只同步选定 App：

```powershell
gravity metadata sync --app-id <selected-app-id> --max-pages 2 --dry-run
gravity metadata sync --app-id <selected-app-id> --max-pages 2
```

单 App 的“界”是：只读固定四类 Analysis 对象，并把三个分页 operation 各限制为 `max_pages` 页；
另一个非分页 operation 只读一次，因此逻辑请求上限为 `3 * max_pages + 1`，默认 7、硬上限 25。
这个界不包含 runtime 固定策略产生的 HTTP retry 或一次鉴权刷新；执行结果会另外报告实际逻辑请求、
receipt 可见的 HTTP 次数/重试、各 operation 页数、对象数与失败。选这个边界是因为 App、对象集合和
页数都能在首次请求前机械计算，同时不会把账号下其他 App 或 workspace 词汇拖进冷启动预算。

已有 `sync --all-apps [--include-table-lineage]` 保留给明确需要完整账号目录、workspace 词汇或数据表沿革
的调用方；它的请求量依赖可见 App 数和分页，不属于单 App 有界入口。两种同步都使用 staging SQLite
和原子替换。通常不需要指定路径；只有调用方明确管理落盘位置时才使用 `--database`。

同步结果只表示 Gravity 中真实存在的物理元数据，不会推断“业务模块 → 事件”的关系。

## 下一步

- 执行真实分析任务：[Agent 工作流](agent-workflow.md)
- 从完整目录走到第一次真实结果：[十分钟路径](agent-skills/ten-minute-path.md)
- App ID 跨 route 的 string/integer 声明：[App ID wire types](reference/sdk.md#app-id-wire-types)
- 在服务或 notebook 中使用：[Python SDK 参考](reference/sdk.md)
- 理解 Insight、SQL 和合同层：[架构与概念](architecture.md)
- 查完整命令分组：[CLI 参考](reference/cli.md)
