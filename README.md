# Gravity Agent Runtime

Gravity Agent Runtime 的实现仓库，当前稳定内核是面向数据分析团队的 Agent-first Python SDK 与 CLI。仓库把 Gravity 的发现、读取、导出和受治理写入收敛为版本化合同，并按已批准路线扩展版本化 Skill、业务语义、确定性分析方法和有界 Context，让分析任务无需打开 Gravity Web 也能完成。

## 从这里开始

- **使用 SDK 取数或分析**：读 [团队上手包](docs/team-onboarding.md)，然后运行：

  ```powershell
  gravity agent-catalog categories
  ```

- **修改本仓库**：先读 [AGENTS.md](AGENTS.md)，再从 [维护者入口](docs/maintainers/index.md) 选择当前任务。

## 产品入口

- `gravity insight`：受合同治理的 Insight 查询与导出，日常分析首选。
- `gravity sql`：仅执行 workspace 已登记的 SQL 产品，不接受任意 SQL。
- `gravity census`：盘点前端路由、发现候选合同并检查上游漂移。
- `gravity agent-catalog` / `gravity agent` / `gravity plan`：供 Agent 渐进发现、补参和显式执行。

自然语言不会自动执行写入。所有 mutation 先预览，再由调用方用同一输入显式确认执行。

## Agent Runtime 演进计划

Gravity Agent Runtime 计划已整体发布到 `main`；当前可执行能力仍以上述 CLI、SDK、Plan、运行时 catalog 和机器合同为准。版本化[需求索引](specs/agent-runtime/index.md)保存交付状态，目标架构不自动扩大当前公共接口；试点能力仍服从各自的毕业条件。

## 安装

公开支持 Python 3.11 和 3.12。CI 运行 Windows 3.11 完整门禁、Linux 3.11 / 3.12
核心门禁，并在 Linux 3.12 上构建 wheel、以非 editable 方式隔离安装后验证公共 surface。

```powershell
python -m pip install gravity-insight
gravity --help
gravity agent-catalog categories
```

Python 最小入口：

```python
from gravity_insight import connect

gravity = connect()
result = gravity.read("app.list", {"page": 1, "page_size": 20})
```

## 文档

[文档导航](docs/index.md)按任务给出最短阅读路径。调用方式见 [CLI](docs/reference/cli.md)、[SDK](docs/reference/sdk.md) 和 [Plan](docs/reference/plan.md)；精确字段、错误和 fail-closed 行为从[机器契约索引](docs/reference/cli.md#machine-contract-index)进入当前 catalog 与合同。完整目标以 [Canonical Architecture](docs/architecture.md) 为准。
