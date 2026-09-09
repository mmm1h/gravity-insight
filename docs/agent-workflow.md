# Agent 工作流

本页是宿主从需求到受治理结果的唯一完整使用顺序 Owner。产品参数和响应字段只在任务指南、reference 与机器合同中定义；上手包、README 和 Runtime 入口只给短提示并引用本页。

## 0. 宿主优先的有序合同

```text
业务分析需求
  → 宿主理解目标、拆解任务，核对必要项目口径
  → 当前上下文已有适用能力及有效输入合同？
      是：直接使用现有专用 CLI / SDK / Composite / Plan
          不重复读取目录，不提交关键词重选
      否：读取当前目录，按需 describe/schema
          宿主比较能力与边界，构造现有 host-selection
          Runtime 严格校验，交付补参或执行入口
  → 宿主仍无法可靠选择，或环境不具备宿主选择能力？
      允许 recognizer 提供受限候选
      无匹配、弱匹配或歧义未解：补充必要信息或返回 Gap，不强选
  → 输入、权限及执行合同满足后，由既有执行面执行
  → 宿主检查结果、完整性与限制，再决定追加查询或形成结论
```

“已知能力”必须有当前可用目录/Schema、版本绑定或明确现行产品合同作依据，不能凭模型记忆猜 selector。版本或目录漂移时按协议重新获取；没有漂移不为证明读过目录而重复读取全目录。复杂问题由宿主拆解并复用现有 Composite/Plan，不默认把整段需求原样交给 recognizer。

这是**宿主使用顺序**，不是 Runtime 内置推理阶段：公共 API 的 routing 缺省仍是“有 selection 走 host_catalog，无 selection 走 recognizer”。保留显式 `--routing recognizer` 及合法无 selection 调用作为保底工具；缺 selection 不能证明宿主尝试过选择。有效 selection 由现有宿主臂解析，词法评分不得覆盖它；直接入口也不新增词法重选。

### 三类失败与预算

| 情况 | 正确处置 |
| --- | --- |
| 宿主无法可靠选择，或环境不具备选择协议能力 | 可显式调用 recognizer 获取受限候选；候选仍须符合任务、输入、权限与执行合同。0 候选、弱匹配、未解歧义不执行 |
| 日期、指标口径、App/事件绑定或业务事实缺失 | 先使用已授权项目资料补齐；仍缺则报告精确缺项或 Gap。可查候选，但规则不能替代事实，也不能把歧义改成默认值 |
| selection 过期/格式错/缺字段、能力不存在、权限拒绝、合同漂移或质量/完整性不满足 | 按结构化错误修正协议或报告缺口；不得静默切 recognizer、邻近产品、裸 SQL 或其他账号 |

提交的 selection 校验失败不等于宿主无法理解。`HOST_SELECTION_REJECTED` 的 field/code 指向协议修复；合法 abstained 返回 `HOST_PRODUCT_SELECTION_EMPTY`，多候选返回 `MULTIPLE_INTENTS`，均不自动重选或执行。选中能力仅是发现成功，仍须满足 `missing_inputs`、schema 与执行前门禁。

目录刷新、候选兜底与重试共用当前任务已有的调用/Context/全局请求预算，不新增路由轮询预算。相同未变输入不交替轮询两臂；只在资料、合同、选择或授权等必要条件实际变化后继续。预算耗尽则报告缺口；不得为证明顺序重复全目录或自动重试写入。

### 最短入口

| 已知信息 | 入口 |
| --- | --- |
| 已知 recipe、operation 或产品 selector | `gravity run`、专用 CLI 或 SDK 方法 |
| 已知 Analysis kind 和 compact spec | `gravity analysis query` |
| 多个独立任务或存在依赖 | 一个显式 `gravity plan run` |
| 未知当前能力 | `agent-catalog categories → category → describe` |
| 调用方能选择目录项 | `agent-catalog host` + `host-selection`（省略 routing 即走宿主臂） |
| 调用方无法选择 | `gravity agent --routing recognizer`，或无 selection 的受控调用 |

目录浏览和 schema 查询离线完成。发现不会执行产品，自然语言不会执行写入。

### 观测与验收边界

复用同一次调用的 `routing_mode/routing`、`selection_receipt`、已有执行 receipt、Plan 结果和 eval `observations`，不建立第二套追踪系统。机器字段以当前输出为准：

- 发现输出的 routing `status/arm/selector/terminal_state` 对齐 R2-03；`event=discovery` 的 success 只表示交接成功，不表示执行或业务成功。多候选不伪造一个 selector，候选集合仍来自原 candidates/receipt。
- catalog 指纹沿用已计算的指纹并标明 basis：宿主产品目录与 workspace 目录不是同一个分母，不能互相当 selection 绑定。协议帮助尚未走路由，记为 `not_measured`，不把缺省策略当已执行的臂。
- 收到并校验 selection 只证明协议校验；`host_reason`/`candidate_reasons` 标明 `host_declared`，不是 Runtime 对推理质量的证明。兜底原因若由宿主声明，也须在现有 eval 记录中标注该来源；无证据不虚构原因。
- 宿主是否先读目录、是否加载 Skill 以宿主工具调用记录核验；无记录为 `unknown`。发现阶段的后续执行为 `not_measured`，不能把交接卡的 `next.argv` 当执行事件。
- 直接 CLI/SDK/Plan 保留实际工具入口、原有 operation/node 身份、合同指纹、receipt/status 和错误结果作执行证据，不强制包装成第三条路由。把发现事件与执行事件分开；无执行记录，终态不猜为成功。不要采集私有思维链、凭据或原始用户级数据。

R2-06 离线回归只证明 Runtime 对实际输入的分支、边界与能力保留。真实 Host 的调用顺序、Skill 触发和首次采用验收归 R2-11；固定脚本 catalog → selection、模型自述或离线 mock 均不能代替真实宿主工具事件。R2-05 的生成宿主指导应投影短优先级、可执行目录入口及本页引用，不复制完整合同或假定未加载 Skill 的正文已被读取。

## 1. 解析 Semantic Schema 与项目绑定

Runtime 拥有可复用 Semantic、确定性 Operator、Model lifecycle、Context、Project Overlay 与 Analysis Result Schema。Overlay 只提供项目 Semantic Source/Repo Context/default scope，不能覆盖 Trust、完整性、claims、隐私、selector、effect 或 Action authorization；Operator 只按 exact URI 执行静态方法，Model 未通过 trusted digest/验证/批准/时限/horizon 时只允许 scenario/hypothesis。

Semantic/Binding/Operator/Model/required Context 任一未登记必须返回机器 gap；Repo search 只发现 `role=data` 候选，只有显式 Requirement 可组装 Pack。Core Skill readiness 在执行前冻结值无关 `gravity.execution-snapshot.v1`，执行后必须逐项相等；禁止从列名、自然语言、Context 或 Skill 文本补公式、方法、selector 或授权。

## 2. 发现并选择

```powershell
gravity agent-catalog categories
gravity agent-catalog category <domain>
gravity agent-catalog describe <selector>
```

选择规则：

- product 优先于 raw operation；gap 不可执行。
- `gap:SEGMENT_EVENT_RULE_ACCEPTANCE_UNPROVEN` 对应 `custom event first exposure cohort` /
  `自定义事件首次暴露 cohort`；它不把普通事件日 Retention 当等价结果。
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
   执行后必须单独检查 `completeness` 与 `row_cap_reached`；readiness、Evidence 有效或
   `status=complete` 都不能代替下游 cohort 完整性。`possible_truncation` 时不得接受完整 cohort claim。
3. 已有结果上的比率、占比、变化和集合对账：使用调用方声明的 derived spec。
4. 三者都不满足：返回 capability gap，不生成裸 SQL 或任意 HTTP；隔离 SQL Explorer 只接受调用方另行显式构造的本地请求，绝不作为 Agent/Plan fallback，结果也不能进入 stable Journey。

## 5. 控制效果与写入

读取节点可由 Plan 执行。Mutation 只有在对应产品明确支持 Plan effect 时才能进入 Plan；其余写产品交付同参数两步 CLI：preview/dry-run → 人工确认 → execute。

素材文件是 direct file effect，不进入 Plan。Agent 选择 `material.asset.fetch` 后必须按卡片的
`source_inputs`、`reference_fields` 和 `coverage` 补参；`MATERIAL_ASSET_BINARY_UNAVAILABLE` 只表示
当前 fresh scope 中二进制不可得且原因不可区分，不能改写成删除、过期或无权限。

执行必须验证目标所有权或 marker、容量、cascade 和 preimage。写成功后读回；响应不确定、布局丢失或对象漂移时抛结构化错误，不自动重试。

## 6. 解释结果

调用方按以下顺序读取：

1. `schema_version`、`status`、`ok`、`result_source`；Skill 结果还要校验完整 execution snapshot。
2. 日期窗、分页/截断、组件状态和 partial failures。
3. warnings、diagnostics、drift audit、DQ、evidence level、limitations 和 allowed/forbidden claims。
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
## 9. Experiment / Outcome 交接

只有 verified Analysis Result 与 exact planning snapshot 才能编译 Experiment Proposal；缺 Target/Metric/Guardrail/Power/Context 时保持 `proposal_only`，齐全时也只是 `ready_for_review`，不授权创建。Outcome 必须来自绑定 Proposal 的外部 completed observation，使用不同 Journey 和原分析之后的独立 evidence window；`handoff_ready` 不等于 evaluation 已执行，原建议和同一运行不得自证。
