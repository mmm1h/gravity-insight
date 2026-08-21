# 路线图

产品目标：任何数据分析任务都能在不打开 Gravity Web 的前提下，仅用本仓库完成；Agent 能机器判定发现、执行、空结果、部分失败和能力缺口。

衡量单位是[分析动线](analysis-journeys.md)，不是 operation 数量。动态目录规模只从 `gravity agent-catalog` 与 compiler 获取，不在路线图手写。

## 当前优先级

1. **闭合可回答动线。** 优先修复已有产品的合同、结果可信度和调用成本，不用新增 raw operation 代替产品闭环。
2. **消除调用方猜测。** Schema、错误、owner、effect、日期窗和 allowed claims 必须随机器合同交付。
3. **只推进有新证据的候选。** 精确 blocker 与下一步最小证据见[候选矩阵](candidate-capability-matrix.md)；租户数据和权限未变化时不重复空探测。
4. **控制结构增长。** 共享 spine 串行接线；领域 core 可并行；生成 compiler、provenance、coverage 产物时串行。

## Gravity Agent Runtime program

用户已批准将本仓库从当前 Gravity SDK 内核演进为 Gravity Agent Runtime。目标范围包括同层 Capability Trust/Data Quality、版本化 Skill、Business Semantic、确定性 Operator/Model、有界 Context、受治理 Action/Artifact 和按触发条件建设的 MCP、隔离 SQL Explorer 与 External Control Plane。

目标架构与当前能力必须分开：当前接口仍以 CLI/SDK/Plan、catalog 和机器合同为准；未实现的目标面不得写成已交付。完整批准总纲位于 [architecture source](../specs/agent-runtime/architecture-source.md)，通过 `directive.json` 绑定 digest；串并行依赖和状态以 [Requirement Index](../specs/agent-runtime/index.md) 为准。

当前程序状态：

1. **R00 产品宪法与需求拆分（fixed-dev）**：v9.1 canonical 总纲、directive 和细化后的无环需求图已在 `dev` 完成并通过整仓门禁；不表示已发布到 `main`。
2. **R01 参考纵向切片（fixed-dev）**：`analysis.merge2.ap-cost-anomaly-localization` 已在 `dev@08b42971` 完成；真实路径因底层完整性仍为 `unknown` 而零请求阻断，交付账本和 R02-R08 extraction ledger 位于 R01 Requirement。
3. **R02 Journey / Trust / DQ 泛化（fixed-dev）**：五个显式 Journey 已绑定严格 ledger projection；Operation/Product/Composite 使用同层 Trust、principal-scoped Validation、TTL、Data Quality 和 transitive impact。R01 仍因完整性不足以 exit 4 零请求阻断；旧私有 Trust owner 已删除，未扩建第二执行器或路由器。
4. **R03 Built-in Skill Package（fixed-dev）**：R01 Skill 已升级为单一 JSON Render Model，并确定性生成 wheel package、docs mirror 与 Agent Skills export；本地 resolver 传播 R02 Trust blocker，普通包保持零代码，R04 Hub/CAS/lock/trusted-pack 未被提前实现。
5. **R05 Business Semantic Registry（fixed-dev）**：versioned Definition/Binding/Source、formula/unit/additivity/time/effective-range/conflict 门禁与离线 `SemanticRegistry`/复数 CLI 已集成；Runtime 只含通用 App Entity，Merge2 指标与 App/physical binding 已迁移到 work-dashboard 独立 Source。R01 仍因完整性 unknown 而零请求阻断。
6. **R06 Operator / Model Contracts（in-progress）**：抽取唯一 R01 deterministic Operator，建立闭合 Registry、输入/输出/assumption/claim/golden 门禁；Model 只建 lineage/evaluation/approval/expiry 合同且不内置模型，LTV gap 不提升。
7. **并行规则**：依赖满足且写入边界不重叠的领域 core 可在独立 `codex/<unit>` worktree 并行；共享 spine 最终接线由一个 integrator 串行完成。
8. **Main freeze**：完整计划结束、整体验收通过且用户重新明确批准前，本计划功能只合入 `dev`，不合入 `main`。单项 `fixed_dev` 不等于发布。
9. **持续实施授权**：用户已明确要求依赖满足后持续完成全部 indexed requirements，不再逐项请求批准；计划 owner 仍须在每个单元开工前绑定机器门禁、写入范围与回滚，且不得由该授权推导生产探测、写入、发布或提前解冻 `main`。

## 已定决策

- Insight-first；SQL 只执行 workspace 已登记产品。
- Workspace SQL 的间接问法必须同时具备审核、跨表聚合、登记名称、日期窗和运行意图；发现只按精确登记名选择 product，无匹配返回既有配置缺口，绝不降级为 Insight、raw operation 或裸 SQL。
- 调用方能选择目录时使用 host catalog；没有 selection 时 recognizer 保持离线地板。
- `app.app_info.get` 的 Agent owner card 按 CLI/SDK 输入对象暴露 `url` 模板；Plan `run` node 仍由 `request.inputs` 承载该对象。
- recognizer 的零候选词法恢复保留原评分；只在原评分弃权且索引内证据足量、唯一并明显领先近邻时选择 owner，索引外填充词不单独构成召回依据。
- recognizer 只对显式协调结构拆分多意图；中文成对 `既…也/又…`、保留右侧名词的 `和其他` 及 `和…一起/一并` 可由各子句独立 owner 组成精确 selector 集，已登记 unavailable gap 仍作为同次交接附件返回。
- `report.get.query` 的 Agent owner card 暴露合同派生的顶层 raw 输入模板与完整 compact input schema，并优先于同 selector 的 generic operation card。
- Runtime 拥有可复用 Semantic 类型/Schema、通用指标/方法定义、版本化 URI，以及单位、可加性、时间粒度、依赖、冲突和公式结构校验；调用项目拥有具体活动名称、SKU 实值、App/埋点绑定、项目专属公式参数与生效窗口和部门口径。
- 读取共享全局有界并发预算；不叠加 adapter 私有线程池或增加请求总量。
- Session、CredentialProvider、metadata/operation catalog、FieldPolicy metadata snapshot 与 receipt state 按 resolved env、账号、principal、credential generation 和 workspace 的不可逆摘要隔离，默认 env 不例外；host limiter 与进程级并发槽继续全局共享，scope 摘要不进入公开输出。
- 未登记字段、破坏性响应漂移、身份/权限不确定和不完整分页 fail closed。
- Probe 语义只使用六态机器模型；`unknown` 不等于 read，静态 read candidate 不构成授权，未证实 POST
  必须在任何凭据或网络动作前归入 `unsafe_unknown` 并失败关闭。
- 写入固定 preview/dry-run、人工确认、显式 execute、写后读回；自然语言不自动写。
- 破坏性调用方 surface 升级不保留兼容别名，但同一发布必须迁移 canonical consumer。
- issue #28 将受治理 SQL 的泛化失败 code 直接升级为 stage/类别细分；固定 route、workspace SQL、
  聚合投影、并发上限和结果能力均未改变，因此没有读取能力损失，旧 generic code 不保留别名。
- 宽泛 Analysis 导出只返回不可执行的七族选择交接；每族暴露自己的 selector 和必填输入，不建立统一 dispatcher 或合并异构合同。
- 离线 `doctor` 必须绑定当前源码、editable metadata 与实际 import 来源；任一版本或根目录不一致均在 live probe 前以稳定 `INSTALL_*` 原因失败并给出重装命令。
- 当前表 schema gap 只由明确的当前态 schema，或表语境中的当前态字段加版本触发；已同步沿革仍归 `metadata:table_lineage`，两者显式并列时返回带附属 gap 的 `MULTIPLE_INTENTS`。
- 媒体报表 gap owner 仅在紧邻“报表/投放报表”的领域短语内将“煤体”归一为“媒体”；明确“不要/别混入素材表现”时仍由 `MEDIA_REPORT_ITEM_SCHEMA_MISSING` 优先交接，不扩展全局模糊匹配。
- 分析默认值 owner 仅在紧邻“字典”的领域短语内将“默人值”归一为“默认值”；不扩展全局编辑距离或通用错字表。
- 归因表现 owner 仅在“归音”紧邻“表现/汇总/聚合”时将其归一为“归因”；配置否定仍由原有 affirmative-intent 解析，其他“归音”语境不参与全局模糊匹配。

## 明确不做

- 不复刻 Web 布局、收藏、拖拽和成员权限管理。
- 不开放任意 URL、HTTP 方法、裸 SQL 或自动 text-to-SQL 执行。
- 不把业务模块、活动策略、SKU 或埋点字典放进 SDK。
- 不为单一调用点建立插件、注册表、依赖注入或第二套执行框架。
- 不以扩大隐私投影、自动重试写入或猜测父资源来填补证据缺口。

## 结论写入规则

- 当前排期和跨模块决策更新本页。
- 结构债务更新[技术债清单](maintainers/technical-debt.md)。
- 候选证据更新[候选矩阵](candidate-capability-matrix.md)。
- 动线状态更新[分析动线](analysis-journeys.md)。
- 工作提案和请求账本放 `tmp/`；不要再创建逐趟 Markdown。
- 完整历史与外部调研保留在[归档](archive/index.md)，归档不构成当前合同。
