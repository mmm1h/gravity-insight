# Gravity SDK 文档

按当前任务选择入口，不要通读文档树。运行时能力、字段和默认值以 CLI 与合同为准，入口页不手抄动态计数。

## 我现在要做什么

| 任务 | 先读 | 需要时再读 |
| --- | --- | --- |
| 安装、认证并确认本机可用 | [快速上手](getting-started.md) | [团队上手包](team-onboarding.md) |
| 让 Agent 发现并执行一个分析任务 | [团队上手包](team-onboarding.md) | [Agent 工作流](agent-workflow.md) |
| 执行事件、漏斗、留存、导出或受治理写入 | [Agent 任务指南](agent-skills/index.md) | [CLI 参考](reference/cli.md)、[分页语义](reference/pagination.md) |
| 在 Python 中长期集成 | [SDK 参考](reference/sdk.md) | [架构与概念](architecture.md) |
| 生成或执行显式 DAG / playbook | [Plan 参考](reference/plan.md) | [Agent 工作流](agent-workflow.md) |
| 配置 App、recipe、SQL 产品或调用方语义 | [Workspace 参考](reference/workspace.md) | [架构与概念](architecture.md) |
| 导出文件或把结果交给 LLM | [导出指南](guides/export.md) | [结果与 LLM 安全](guides/llm-output-safety.md) |
| 修改 SDK、合同、探针或 Evidence | [维护者入口](maintainers/index.md) | [扩展地图](maintainers/extending.md) |
| 参与 Gravity Agent Runtime 大改造 | [完整架构总纲](../specs/agent-runtime/architecture-source.md) | [Requirement Index](../specs/agent-runtime/index.md)、[路线图](roadmap.md)；仅在 Index 存在外部批准的 `ready` 需求时再读取该需求，否则停止实施并等待 owner 指示 |
| 查看当前动线、候选阻塞、排期或技术债 | [分析动线](analysis-journeys.md) | [候选矩阵](candidate-capability-matrix.md)、[路线图](roadmap.md)、[技术债](maintainers/technical-debt.md) |
| 复核外部调研或历史取证 | [当前调研结论](research.md) | [历史与证据归档](archive/index.md) |

## 三条边界

1. **Insight-first。** Stable Insight 能等价表达的问题不走 SQL。
2. **只执行已登记能力。** 不接受任意 URL、HTTP 方法、裸 SQL 或未登记字段；合同漂移 fail closed。
3. **Schema 与实例分属两层。** Runtime 拥有可复用 Semantic Schema、通用定义、URI 和通用校验；具体活动/SKU/App/埋点绑定、公式参数与生效窗口由调用项目提供。

## 文档职责

- 使用路径：本页、快速上手、团队上手包、Agent 工作流。
- 行为合同：reference、manifest、operation contract 和 CLI 输出。
- 当前决策：路线图、动线台账、候选矩阵、技术债。
- 批准的目标架构交付单元：`specs/agent-runtime/`；它不替代当前行为合同。
- 历史证据：archive；归档内容不是当前接口承诺。
