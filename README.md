# Gravity SDK

Gravity Agent Runtime 的实现仓库，当前稳定内核是面向数据分析团队的 Agent-first Python SDK 与 CLI。仓库把 Gravity 的发现、读取、导出和受治理写入收敛为版本化合同，并按已批准路线扩展版本化 Skill、业务语义、确定性分析方法和有界 Context，让分析任务无需打开 Gravity Web 也能完成。

## 从这里开始

- **使用 SDK 取数或分析**：读 [团队上手包](docs/team-onboarding.md)，然后运行：

  ```powershell
  $env:PYTHONPATH='src'
  python -m gravity_sdk agent-catalog categories
  ```

- **修改本仓库**：先读 [AGENTS.md](AGENTS.md)，再从 [维护者入口](docs/maintainers/index.md) 选择当前任务。

## 产品入口

- `gravity insight`：受合同治理的 Insight 查询与导出，日常分析首选。
- `gravity sql`：仅执行 workspace 已登记的 SQL 产品，不接受任意 SQL。
- `gravity census`：盘点前端路由、发现候选合同并检查上游漂移。
- `gravity agent-catalog` / `gravity agent` / `gravity plan`：供 Agent 渐进发现、补参和显式执行。

自然语言不会自动执行写入。所有 mutation 先预览，再由调用方用同一输入显式确认执行。

## Agent Runtime 演进计划

当前可执行能力仍以上述 CLI、SDK、Plan、运行时 catalog 和机器合同为准；目标架构不等于已经交付。批准的 Gravity Agent Runtime 改造已拆成版本化[需求索引](specs/agent-runtime/index.md)，每个单元独立验收并集成到 `dev`。

本计划完整完成前不把其中的功能开发合入 `main`。Skill Hub、Context、Operator/Model、MCP、SQL Explorer 等只有在对应需求达到 `ready` 并实际落地后，才会进入当前能力文档和公共接口承诺。

## 安装

```powershell
python -m pip install -e .
gravity --help
gravity agent-catalog categories
```

Python 最小入口：

```python
from gravity_sdk import connect

gravity = connect()
result = gravity.read("app.list", {"page": 1, "page_size": 20})
```

## 文档

[文档导航](docs/index.md)按任务给出最短阅读路径。接口签名以 [CLI](docs/reference/cli.md)、[SDK](docs/reference/sdk.md) 和 [Plan](docs/reference/plan.md) 参考为准；当前能力以本机 `agent-catalog` 与合同编译结果为准，完整目标以 [canonical architecture source](specs/agent-runtime/architecture-source.md) 为准，交付顺序由批准 directive 与[需求索引](specs/agent-runtime/index.md)约束。

历史归档的拆仓来源见 [2026-08-10 拆仓记录](docs/archive/repository-migration-2026-08-10.md)。
