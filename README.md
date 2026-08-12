# Gravity SDK

面向数据分析团队的 Gravity Python SDK 与 Agent 优先 CLI。两种入口共享 operation 合同、
认证、运行时、分页、并发、字段投影和结构化错误；CLI 负责开箱即用，SDK 负责长期集成。

它提供三条边界清晰的线上能力：

- `gravity insight`：结构化 Insight 查询与导出，日常分析首选；
- `gravity sql`：Insight 无法等价表达时使用的受控 SQL 产品；
- `gravity census`：前端路由盘点、合同发现与上游漂移检查。

SDK 还提供本地元数据检索、跨目录发现与 workspace recipe：`gravity
metadata sync/search`、`gravity find` 和 `gravity run` 让 Agent 无需临时 Python/JSON
脚本即可完成常见查询链路。

Agent 的默认路径最多两步：未知问题用 `gravity agent --input <questions.json> → gravity
plan run --input <plan.json>`，一次目录快照批量发现、一次显式执行；已知 recipe、operation 或
Plan 时直接 `gravity run` / `gravity plan run`，只需一次调用。发现结果包含可复制 argv 和
`plan_node`，但自然语言不会自动执行。多个独立读取共享一个有界 worker pool，不逐条起进程。

## 快速开始

```powershell
python -m pip install -e .
gravity
gravity agent "event analysis"
gravity agent --input questions.json
gravity plan schema
gravity analysis query batch --input queries.json --concurrency 6
gravity analysis user journey --app main --client-id <id> --date 2026-08-12
gravity metadata sync --all-apps
```

首次在交互式终端运行 `gravity` 会询问 Gravity 用户名和密码，验证登录并在用户私有目录维护会话。`--help`、operation 搜索、`find`、recipe 检查和本地 metadata 查询不会触发登录。使用者不需要配置或维护 token。

查询遵循 **Insight-first**：只要 stable Insight operation 能等价表达目标，就优先使用 Insight；只有复杂跨表、特殊计算或 Evidence 产品无法由 Insight 表达时才使用 SQL。

Python 最小入口：

```python
from gravity_sdk import connect

gravity = connect()  # Insight / SQL client 在第一次使用时才创建并缓存
result = gravity.read("app.list", {"page": 1, "page_size": 20})
```

`GravitySDK/connect` 只统一构造和常用委托，不自动猜 Insight/SQL；专用的
`GravityInsightClient` 与 `GravityClient` 仍是公开 API。

## 文档入口

从 [文档导航](docs/index.md) 开始。它按任务给出最短阅读路径：

- 第一次安装和查询：[快速上手](docs/getting-started.md)
- Agent 执行查询：[Agent 工作流](docs/agent-workflow.md)
- Python 集成：[SDK 参考](docs/reference/sdk.md)
- 理解系统边界：[架构与概念](docs/architecture.md)
- 开发和维护 SDK：[维护者入口](docs/maintainers/index.md)；先用[扩展地图](docs/maintainers/extending.md)选择最小改动面

历史拆仓来源见 [MIGRATION.md](MIGRATION.md)。

## 验证

```powershell
python -m unittest discover -s tests
python -m gravity_sdk.compiler check
python -m gravity_sdk.quality check
python -m gravity_sdk --help
git diff --check
```
