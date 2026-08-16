# Gravity SDK

面向数据分析团队的 Gravity Python SDK 与 Agent 优先 CLI。两种入口共享 operation 合同、
认证、运行时、分页、并发、字段投影和结构化错误；CLI 负责开箱即用，SDK 负责长期集成。

它提供三条边界清晰的主要读取入口：

- `gravity insight`：结构化 Insight 查询与导出，日常分析首选；
- `gravity sql`：Insight 无法等价表达时使用的受控 SQL 产品；
- `gravity census`：前端路由盘点、合同发现与上游漂移检查。

SDK 还提供本地元数据检索、跨目录发现与 workspace recipe：`gravity
metadata sync/search`、`gravity find` 和 `gravity run` 让 Agent 无需临时 Python/JSON
脚本即可完成常见查询链路。

当前机器目录覆盖 **223 个 operation** 与 **43 张 Agent 产品卡**；214 个 stable operation
由 184 个 read 和 30 个 governed mutation 组成。写面只开放逐项登记的分群、marker-governed
报表/订阅和 Kanban 工作区；所有写入均先 `--dry-run`，再由调用方显式确认同参数 `--execute`。
create 预览零网络；需要层级影响数的 Kanban 预览只读 tree/detail。自然语言永不自动执行写入；
Kanban 可由显式 `preview|execute` Plan node 调用，其他写产品仍不进入 Plan。

Agent 第一次盘点能力时先用 `gravity agent-catalog categories → category → describe` 三层离线目录；
它完整区分产品卡、raw operation 和精确 gap。进入具体问题后，默认路径最多两步：未知问题用
`gravity agent --input <questions.json> → gravity plan run --input <plan.json>`，一次目录快照批量发现、
一次显式执行；已知 recipe、operation 或 Plan 时直接 `gravity run` / `gravity plan run`，只需一次调用。
发现结果包含可复制 argv 和 `plan_node`，但自然语言不会自动执行。多个独立读取共享一个有界 worker
pool，不逐条起进程。

首次接触仓库时，按[十分钟 Agent 上手路径](docs/agent-skills/ten-minute-path.md)完成能力发现、App/物理
事件选择、零网络编译和一次显式真实分析；它不需要打开 Gravity Web，也不会猜业务输入。

当前 `0.3` 是调用方 surface 的破坏性收口：Multidim 专用入口只有
`gravity multidim query --app <alias|id> ...`，结果行位于 `query.data.list`；Plan request 必须带
`input_schema_version="gravity-insight.multidim-input.v1"`。旧 `multidim query --app-id`、省略 App
的 raw 分流和 `multidim calc-total` 不再提供。专家仍可通过
`gravity run report.multidim.query` / `gravity run report.multidim.calc_total` 精确执行受治理的
operation；这不绕过 operation 版本、字段投影或 fail-closed 合同。

## 快速开始

```powershell
python -m pip install -e .
gravity
gravity agent-catalog categories
gravity agent-catalog describe analysis.query.spec:event
gravity agent "event analysis"
gravity agent --input questions.json
gravity plan schema
gravity multidim query --input-schema
gravity analysis query batch --input queries.json --concurrency 6
gravity analysis user journey --app main --client-id <id> --date 2026-08-12
gravity metadata sync --all-apps
gravity reports --help
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
python -m pytest -q
python -m gravity_sdk.compiler check
python -m gravity_sdk.quality check
python -m gravity_sdk --help
git diff --check
```
