# Gravity SDK

面向数据分析团队的 Agent-first Python SDK 与 CLI。仓库把 Gravity 的发现、读取、导出和受治理写入收敛为版本化合同，让分析任务无需打开 Gravity Web 也能完成。

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

[文档导航](docs/index.md)按任务给出最短阅读路径。接口签名以 [CLI](docs/reference/cli.md)、[SDK](docs/reference/sdk.md) 和 [Plan](docs/reference/plan.md) 参考为准；当前能力以本机 `agent-catalog` 与合同编译结果为准。

历史拆仓来源见 [MIGRATION.md](MIGRATION.md)。
