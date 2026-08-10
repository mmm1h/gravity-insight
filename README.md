# Gravity SDK

Gravity 的受控只读 SDK 与 CLI。它提供三条边界清晰的能力：

- `gravity insight`：结构化 Insight 查询与导出，日常分析首选；
- `gravity sql`：Insight 无法等价表达时使用的受控 SQL 产品；
- `gravity census`：前端路由盘点、合同发现与上游漂移检查。

SDK 还可通过 `gravity metadata sync --all-apps` 将所有可见 App 的事件与属性同步到本地 SQLite。

## 快速开始

```powershell
python -m pip install -e .
gravity
gravity insight capabilities search "event analysis"
gravity metadata sync --all-apps
```

首次交互式运行 `gravity` 会询问 Gravity 用户名和密码，验证登录并在用户私有目录维护会话。使用者不需要配置或维护 token。

查询遵循 **Insight-first**：只要 stable Insight operation 能等价表达目标，就优先使用 Insight；只有复杂跨表、特殊计算或 Evidence 产品无法由 Insight 表达时才使用 SQL。

## 文档入口

从 [文档导航](docs/index.md) 开始。它按任务给出最短阅读路径：

- 第一次安装和查询：[快速上手](docs/getting-started.md)
- Agent 执行查询：[Agent 工作流](docs/agent-workflow.md)
- 理解系统边界：[架构与概念](docs/architecture.md)
- 开发和维护 SDK：[维护者入口](docs/maintainers/index.md)

历史拆仓来源见 [MIGRATION.md](MIGRATION.md)。

## 验证

```powershell
python -m unittest discover -s tests
python -m gravity_sdk.compiler check
python -m gravity_sdk.quality check
python -m gravity_sdk --help
git diff --check
```
