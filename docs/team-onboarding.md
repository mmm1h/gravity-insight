# 数据分析团队上手包

目标：让分析师或调用方 Agent 只靠本仓库完成能力发现、执行、判断结果和安全交付。这里不列固定产品数量，也不保存租户样本。

## 分析师先做三件事

1. 确认 `gravity insight auth status` 显示可用身份；认证失败就停止。
2. 运行 `gravity agent-catalog categories`，按 `category → describe` 找到精确产品合同。
3. 审阅 App、日期、事件、指标、字段和写入影响，再执行卡片给出的 CLI 或 Plan。

## 1. 发现能力

```powershell
$env:PYTHONPATH='src'
python -m gravity_sdk agent-catalog categories
python -m gravity_sdk agent-catalog category analysis --limit 20
python -m gravity_sdk agent-catalog describe analysis.query.spec:event
```

优先选择 `identity_kind=product`。Raw operation 是已知 wire 的专家入口；`capability_gap` 只能报告，不能执行。

调用方能可靠选择产品时，读取 `agent-catalog host`，提交严格的 `gravity.host-product-selection.v1`。没有 selection 时使用默认 recognizer；它是离线保底，不会替调用方猜业务输入。

## 2. 补参并执行

- 已知 selector：按 `required_inputs` 填值，直接执行一次。
- 未知任务：第一次发现并选择，第二次执行；不要逐条启动多个进程。
- 多个独立读取：放入一个 Plan 或 batch，复用全局有界并发预算。
- Analysis spec：先读产品卡的 `schema_argv`，不要从 Web wire 或邻近 operation 猜形状。
- Runtime Semantic Registry 提供可复用类型、通用定义、URI 和校验；具体业务定义、公式参数/生效窗口和 App alias 由调用项目的显式 Semantic Source 声明，Runtime 不猜测。先用 `gravity semantics validate --source <file>`，再按精确 URI 解析。

产品级步骤见[任务指南](agent-skills/index.md)，通用编排见[Agent 工作流](agent-workflow.md)。

```powershell
gravity skills list
gravity skills show <skill_uri>
```

已知 Skill 可用上面命令离线读版本和缺口。Skill 不替代选路、Journey、权限或执行合同；
`blocked` 必须停止，`validated` 不代表当前可执行。

## 3. 识别发现终态

| 终态 | 含义 | 处理 |
| --- | --- | --- |
| `success` 且 `executable=true` | 已找到可执行产品 | 补齐输入并执行 `next.argv` |
| `multiple_intents` | 一个问题包含多个独立任务 | 让调用方拆分或显式选择返回的意图 |
| `capability_gap` | 已登记但当前不能完成 | 报告 code、reason、next action；没有 argv 就停止 |
| `NO_CANDIDATE` | recognizer 未命中登记能力 | 浏览目录；禁止执行 weak match |
| `UNRANKED_OPERATIONS` | 只有互不相同的 raw 候选 | 交给宿主选择，不猜 top-1 |

退出码：0 表示成功或合法空；2 是输入/认证；3 是上游、权限或限流；4 是本地合同、隐私或 I/O。

## 4. 判断结果是否可信

执行后先看 envelope，再看数值：

1. 确认 `schema_version`、`status`、`result_source` 和 `resolved_date_window`。
2. 阅读 `warnings`、`diagnostics`、`interpretation`、`unreliable_item_keys` 和 drift audit。
3. 区分 `empty`、`partial`、`semantic_error` 和真正成功；HTTP 200 不等于业务成功。
4. 只对声明可加的指标做分组求和；UV、设备数和活跃用户通常不可跨维相加。
5. 重要数字用第二条独立 route、分页总数、分日/整窗或 list/export 行数对一次。
6. 结果缺少请求的组或身份时停止解释，不给无标签行补语义。

完整规则见[结果与 LLM 安全](guides/llm-output-safety.md)。

## 5. 写操作

自然语言永不自动写。受治理 mutation 固定为：

1. 使用权威输入运行 `--dry-run` 或 preview。
2. 人工审查 target、impact、cascade、preimage 和 fingerprint。
3. 用同一输入只切换为 `--execute`。
4. 检查写后读回与清理结果；失败不自动重试。

## Agent 最小交付清单

```text
1. 认证有效；不记录凭据。
2. 从 catalog 选择已登记产品，不猜 selector。
3. 补齐 App、日期和物理字段；通用 Semantic 来自 Runtime，项目实例绑定来自 workspace。
4. 只执行 success + executable 的交接。
5. 检查 envelope 状态、窗口、warning、diagnostic 和 interpretation。
6. 重要数字做一次独立对账。
7. capability gap 和权限边界按结构化错误原样报告。
8. 写入先预览、人工确认、再显式执行。
```
