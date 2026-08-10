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
gravity insight capabilities search "applications"
gravity insight capabilities describe app.list
gravity insight read app.list --all-pages --max-items 20
```

需要输入参数时，将 JSON 写入临时文件：

```powershell
gravity insight capabilities describe analysis.event.list
gravity insight validate analysis.event.list --input tmp/event-list.json
gravity insight read analysis.event.list --input tmp/event-list.json --all-pages
```

`describe` 的输入 schema 和 example 是调用前权威。`validate` 只做本地检查；`read` 才会访问 Gravity。

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
