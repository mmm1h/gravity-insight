# Agent 工作流

本页定义调用方如何从任务走到受治理结果。产品参数和响应字段只在任务指南、reference 与机器合同中定义。

## 0. 选择最短入口

| 已知信息 | 入口 |
| --- | --- |
| 已知 recipe、operation 或产品 selector | `gravity run`、专用 CLI 或 SDK 方法 |
| 已知 Analysis kind 和 compact spec | `gravity analysis query` |
| 多个独立任务或存在依赖 | 一个显式 `gravity plan run` |
| 未知当前能力 | `agent-catalog categories → category → describe` |
| 调用方能选择目录项 | `agent-catalog host` + `host-selection` |
| 调用方无法选择 | 默认 `gravity agent` recognizer 保底 |

目录浏览和 schema 查询离线完成。发现不会执行产品，自然语言不会执行写入。

## 1. 解析 Semantic Schema 与项目绑定

Runtime 拥有可复用 Semantic、确定性 Operator 和 Model lifecycle Schema。项目值来自显式 Source；Operator 只按 exact URI 执行静态安装的方法；Model 未命中 trusted digest、未验证/批准、过期或超安全 horizon 时只允许 scenario/hypothesis，不输出生产预测。

Semantic/Binding/Operator/Model 任一未登记必须返回机器 gap；禁止从列名、自然语言或 Skill 文本补公式、方法或模型。需要物理字段时先查本地 metadata，执行前复验 Product 和依赖合同。

## 2. 发现并选择

```powershell
gravity agent-catalog categories
gravity agent-catalog category <domain>
gravity agent-catalog describe <selector>
```

选择规则：

- product 优先于 raw operation；gap 不可执行。
- `required_inputs` 是调用方必须补齐的决策，不用默认值掩盖。
- `schema_argv` 给出紧凑输入合同；`next.argv` 给出执行交接。
- 多意图必须拆分或显式选择；weak match 和未排序 raw 候选不得直接执行。
- 宿主 selection 必须绑定当前 catalog fingerprint，防止跨版本重放。
- 保存分析 live catalog 的 `replay_status=unchecked` 只允许选择稳定 ID；精确 get/prepare 检查后才允许执行。

## 3. 构造执行请求

已知任务一次执行；未知任务在选择后第二次执行。使用 Plan 时：

- 每个 node 有稳定 ID、kind 和 versioned request。
- 依赖只引用上游已声明输出；动态 binding target 必须在 schema 中允许。
- 独立节点共享一个全局 worker pool；不要再给 adapter 叠加线程池。
- `max_pages`、`max_items` 和全局请求预算由调用方显式设置或接受合同默认值。
- 输入、contract fingerprint 或父资源漂移时 fail closed，不静默重编译。

多个同类 Analysis spec 使用 batch；单用户链、Dashboard、Business Pulse 等已有 composite 时使用 composite，不手工串行底层 operation。

## 4. 选择 Insight、SQL 或本地计算

1. Stable Insight 能等价回答：使用 Insight。
2. 需要 workspace 已审查跨表聚合：使用登记 SQL product。
   间接问法只有在同时说明审核、跨表聚合、登记名称、日期窗和运行目标时才归属此路径；Agent 只按调用方给出的精确登记名选择 product。名称缺失或未登记时返回 `WORKSPACE_SQL_PRODUCT_NOT_CONFIGURED`，不猜表、字段或 SQL。
3. 已有结果上的比率、占比、变化和集合对账：使用调用方声明的 derived spec。
4. 三者都不满足：返回 capability gap，不生成裸 SQL 或任意 HTTP。

## 5. 控制效果与写入

读取节点可由 Plan 执行。Mutation 只有在对应产品明确支持 Plan effect 时才能进入 Plan；其余写产品交付同参数两步 CLI：preview/dry-run → 人工确认 → execute。

执行必须验证目标所有权或 marker、容量、cascade 和 preimage。写成功后读回；响应不确定、布局丢失或对象漂移时抛结构化错误，不自动重试。

## 6. 解释结果

调用方按以下顺序读取：

1. `schema_version`、`status`、`ok`、`result_source`。
2. 日期窗、分页/截断、组件状态和 partial failures。
3. warnings、diagnostics、drift audit、interpretation 和 allowed claims。
4. 数据行与汇总。

`empty` 是合法结果但只约束当前输入与权限上下文。重要结论需要第二条独立证据；不可加指标不能用分组和替代总计。详见[结果与 LLM 安全](guides/llm-output-safety.md)。

## 7. 错误恢复

- 输入错误：按 `field`、`actual value` 和 `next_action` 修正调用方请求。
- 认证/权限：停止，不换账号或扩大范围猜测。
- 上游语义拒绝：只使用已审查 remedy；不回显或解释未审查原文。
- 合同漂移：停止相关产品，更新证据与版本后再开放。
- I/O 或导出超时：使用 receipt/checkpoint 恢复，不重复创建任务。

## 8. 交付

交付物至少包含：执行入口、输入范围、解析后的日期窗、结果状态、可信度限制、receipt/checkpoint，以及下一步。不要包含凭据、原始请求、用户级明细或未登记响应字段。
