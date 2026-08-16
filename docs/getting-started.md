# 快速上手

完成本页后，你应能登录 Gravity、发现一个 operation、执行只读查询，并同步本地元数据目录。

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

## 4. 发现并执行查询

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

`run` 已在一个进程完成输入校验、父资源处理、读取和诊断；不需要先机械调用 `validate`。

项目提供 `gravity.toml` 时，也可以让 Resolver 在一个进程里完成绑定、校验、父资源检查、执行和诊断：

```powershell
gravity run @<recipe-name> --start 2026-08-01 --end 2026-08-07
gravity run <operation-id> --app <workspace-alias> --input <json>
```

只有 `run` 报告 recipe stale 时再执行 `gravity recipe check <recipe-name>`。

workspace 可由顶层 `--workspace`、显式 API 调用、`GRAVITY_WORKSPACE` 或 cwd 向上查找选中。SDK 只读该文件；执行回执写入用户缓存，不写项目目录。配置格式见 [Workspace 参考](reference/workspace.md)。

## 5. 同步本地元数据目录

先用 `gravity metadata search "" --app-id <selected-app-id> --limit 20` 检查已有私有 catalog 与
`catalog.synced_at/status`。已有成功且足够新的快照时直接离线使用；冷目录或调用方明确要求刷新时，
再使用正式全 App 同步命令：

```powershell
gravity metadata sync --all-apps
```

它会自动分页同步所有可见 App 的事件、事件属性、用户属性和属性分组，并写入用户私有 SQLite。通常不需要指定路径；只有调用方明确管理落盘位置时才使用 `--database`。

`sync --all-apps` 会产生多次生产读取，不能当成固定一次网络请求；必须审查同步摘要里的失败来源与
快照时间。当前没有单 App sync 入口。

同步结果只表示 Gravity 中真实存在的物理元数据，不会推断“业务模块 → 事件”的关系。

## 下一步

- 执行真实分析任务：[Agent 工作流](agent-workflow.md)
- 从完整目录走到第一次真实结果：[十分钟路径](agent-skills/ten-minute-path.md)
- 在服务或 notebook 中使用：[Python SDK 参考](reference/sdk.md)
- 理解 Insight、SQL 和合同层：[架构与概念](architecture.md)
- 查完整命令分组：[CLI 参考](reference/cli.md)
