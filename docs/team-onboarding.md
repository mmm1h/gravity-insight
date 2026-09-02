# 数据分析团队上手包

本页是安装后完成第一次受治理分析的唯一入口。它不手写动态产品数量，也不保存租户样本。

## 1. 安装与认证

权威发行包是 `gravity-insight`；不要安装同名或近似名的第三方包：

```powershell
python -m pip install gravity-insight
gravity --help
gravity insight auth status
```

首次运行会在交互终端引导登录。凭据只留在用户私有状态目录；认证失败时停止，不把 token、cookie、用户名或密码写进命令、日志或 Plan。

只有修改源码时才在当前 worktree 的独立虚拟环境安装 editable 包：

```powershell
python -m venv .venv
& .venv\Scripts\python.exe -m pip install -e ".[dev]"
& .venv\Scripts\python.exe -m gravity_insight --help
```

源码目录中的非 editable 安装会被 `gravity doctor` 拒绝，避免当前源码与实际导入包不一致。

## 2. 发现能力

```powershell
gravity agent-catalog categories
gravity agent-catalog category analysis --limit 20
gravity agent-catalog describe analysis.query.spec:event
```

按 `categories → category → describe` 浏览当前机器的真实目录，优先选择 `identity_kind=product`。Raw operation 只用于已知 wire 的专家调用；`capability_gap` 只能报告，不能执行。

调用方能可靠选择产品时，先读 `gravity agent-catalog host`，再提交严格的 `gravity.host-product-selection.v1`。没有 selection 时 recognizer 只是离线保底，不会替调用方猜 App、日期、事件或业务口径。

已知 Skill 先从明确 Hub Source 同步，再离线检查版本：

```powershell
gravity skills sync --source source.json --state-root <state-root>
gravity skills list --state-root <state-root>
gravity skills show <skill_uri> --state-root <state-root>
```

Skill 不替代选路、Journey、权限或执行合同；`blocked` 必须停止，`validated` 不代表当前可执行。
Runtime wheel 不内置业务 Skill；所有方法统一通过明确的 Hub Source 完成
`sync → list/search → lock → fetch → verify`。供 Codex、Claude Code 等宿主安装的 `SKILL.md` 包是同一
canonical manifest 的独立 Agent 投影，按 `agent-index.json` 摘要核验，不使用 `gravity models --source`。

## 3. 补参并执行

- 已知 selector：按 `required_inputs` 补齐输入，执行一次。
- 未知任务：第一次发现并选择，第二次执行；不要逐条启动多个进程。
- 多个独立读取：使用一个 Plan 或 batch，共享全局有界并发预算。
- Analysis spec：读取产品卡的 `schema_argv`，不要从 Web wire 或邻近 operation 猜形状。
- Runtime 提供可复用 Semantic；具体活动、SKU、App/埋点绑定和项目公式参数来自显式项目 Source，缺失时不猜。

产品步骤见[任务指南](agent-skills/index.md)，通用协议见[Agent 工作流](agent-workflow.md)。

## 4. 识别终态

| 终态 | 处理 |
| --- | --- |
| `success` 且 `executable=true` | 补齐输入并执行 `next.argv` |
| `multiple_intents` | 拆分任务或让调用方显式选择 |
| `capability_gap` | 报告 code、reason、next action；没有 argv 就停止 |
| `NO_CANDIDATE` | 浏览目录；禁止执行 weak match |
| `UNRANKED_OPERATIONS` | 交给宿主选择，不猜 top-1 |

退出码 0 表示成功或合法空；2 是输入/认证；3 是上游、权限或限流；4 是本地合同、隐私或 I/O。

## 5. 判断结果

先看 envelope，再看数值：

1. 确认 `schema_version`、`status`、`result_source` 和 `resolved_date_window`。
2. 阅读 `warnings`、`diagnostics`、`interpretation`、`unreliable_item_keys` 和 drift audit。
3. 区分 `empty`、`partial`、`semantic_error` 和成功；HTTP 200 不等于业务成功。
4. 只对声明可加的指标求和；UV、设备数和活跃用户通常不可跨维相加。
5. 重要数字用独立 route、分页总数、分日/整窗或 list/export 行数复核一次。
6. 请求的组或身份没有出现在结果中时停止解释，不给无标签行补语义。

把结果交给模型前遵守[结果与 LLM 安全](guides/llm-output-safety.md)。

## 6. 写操作

自然语言永不自动写。固定流程是 preview/`--dry-run`、人工审查 target/impact/preimage/fingerprint、同一输入显式 `--execute`、写后读回。失败不自动重试。

## 交付清单

```text
1. 认证有效且不记录凭据。
2. 从 catalog 选择已登记产品，不猜 selector。
3. 补齐 App、日期和物理字段，只执行 success + executable 的交接。
4. 检查 envelope 状态、窗口、warning、diagnostic 和 interpretation。
5. 重要数字独立对账；gap 和权限边界按结构化错误报告。
6. 写入先预览、人工确认、再显式执行。
```
