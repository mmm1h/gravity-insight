# 路线图

产品目标：任何数据分析任务都能在不打开 Gravity Web 的前提下，仅用本仓库完成；Agent 能机器判定发现、执行、空结果、部分失败和能力缺口。

衡量单位是[分析动线](analysis-journeys.md)，不是 operation 数量。动态目录规模只从 `gravity agent-catalog` 与 compiler 获取，不在路线图手写。

## 当前优先级

1. **闭合可回答动线。** 优先修复已有产品的合同、结果可信度和调用成本，不用新增 raw operation 代替产品闭环。
2. **消除调用方猜测。** Schema、错误、owner、effect、日期窗和 allowed claims 必须随机器合同交付。
3. **只推进有新证据的候选。** 精确 blocker 与下一步最小证据见[候选矩阵](candidate-capability-matrix.md)；租户数据和权限未变化时不重复空探测。
4. **控制结构增长。** 共享 spine 串行接线；领域 core 可并行；生成 compiler、provenance、coverage 产物时串行。

## 已定决策

- Insight-first；SQL 只执行 workspace 已登记产品。
- Workspace SQL 的间接问法必须同时具备审核、跨表聚合、登记名称、日期窗和运行意图；发现只按精确登记名选择 product，无匹配返回既有配置缺口，绝不降级为 Insight、raw operation 或裸 SQL。
- 调用方能选择目录时使用 host catalog；没有 selection 时 recognizer 保持离线地板。
- `app.app_info.get` 的 Agent owner card 按 CLI/SDK 输入对象暴露 `url` 模板；Plan `run` node 仍由 `request.inputs` 承载该对象。
- recognizer 的零候选词法恢复保留原评分；只在原评分弃权且索引内证据足量、唯一并明显领先近邻时选择 owner，索引外填充词不单独构成召回依据。
- recognizer 只对显式协调结构拆分多意图；中文成对 `既…也/又…`、保留右侧名词的 `和其他` 及 `和…一起/一并` 可由各子句独立 owner 组成精确 selector 集，已登记 unavailable gap 仍作为同次交接附件返回。
- 业务语义、活动绑定和派生公式属于调用项目，不进入 SDK。
- 读取共享全局有界并发预算；不叠加 adapter 私有线程池或增加请求总量。
- 未登记字段、破坏性响应漂移、身份/权限不确定和不完整分页 fail closed。
- 写入固定 preview/dry-run、人工确认、显式 execute、写后读回；自然语言不自动写。
- 破坏性调用方 surface 升级不保留兼容别名，但同一发布必须迁移 canonical consumer。
- 宽泛 Analysis 导出只返回不可执行的七族选择交接；每族暴露自己的 selector 和必填输入，不建立统一 dispatcher 或合并异构合同。
- 离线 `doctor` 必须绑定当前源码、editable metadata 与实际 import 来源；任一版本或根目录不一致均在 live probe 前以稳定 `INSTALL_*` 原因失败并给出重装命令。
- 当前表 schema gap 只由明确的当前态 schema，或表语境中的当前态字段加版本触发；已同步沿革仍归 `metadata:table_lineage`，两者显式并列时返回带附属 gap 的 `MULTIPLE_INTENTS`。
- 媒体报表 gap owner 仅在紧邻“报表/投放报表”的领域短语内将“煤体”归一为“媒体”；明确“不要/别混入素材表现”时仍由 `MEDIA_REPORT_ITEM_SCHEMA_MISSING` 优先交接，不扩展全局模糊匹配。

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
