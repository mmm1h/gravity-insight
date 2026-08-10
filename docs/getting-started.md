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

不要猜 operation ID。按固定顺序执行：

```powershell
gravity insight operations search "applications"
gravity insight operations describe app.list
gravity insight read app.list --all-pages --max-items 20
```

需要输入参数时可直接使用内联 JSON；只改少数字段时可追加 `--set`：

```powershell
gravity insight operations describe analysis.event.list
gravity insight validate analysis.event.list --input '{"app_id":"101"}'
gravity insight read analysis.event.list --input '{"app_id":"101"}' --set page_size=100
```

`describe` 的输入 schema 和 example 是调用前权威。`validate` 只做本地检查；`read` 才会访问 Gravity。

项目提供 `gravity.toml` 时，也可以让 Resolver 在一个进程里完成绑定、校验、父资源检查、执行和诊断：

```powershell
gravity recipe validate <recipe-name>
gravity recipe check <recipe-name>
gravity run @<recipe-name> --start 2026-08-01 --end 2026-08-07
gravity run <operation-id> --app <workspace-alias> --input <json>
```

workspace 可由显式调用、`GRAVITY_WORKSPACE` 或 cwd 向上查找选中。SDK 只读该文件；执行回执写入用户缓存，不写项目目录。配置格式见 [Workspace 参考](reference/workspace.md)。

## 5. 同步本地元数据目录

跨 App 盘点事件和属性时，使用正式同步命令：

```powershell
gravity metadata sync --all-apps
```

它会自动分页同步所有可见 App 的事件、事件属性、用户属性和属性分组，并写入用户私有 SQLite。通常不需要指定路径；只有调用方明确管理落盘位置时才使用 `--database`。

同步结果只表示 Gravity 中真实存在的物理元数据，不会推断“业务模块 → 事件”的关系。

## 下一步

- 执行真实分析任务：[Agent 工作流](agent-workflow.md)
- 理解 Insight、SQL 和合同层：[架构与概念](architecture.md)
- 查完整命令分组：[CLI 参考](reference/cli.md)
