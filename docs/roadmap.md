# 路线图

产品目标：任何数据分析任务都能在不打开 Gravity Web 的前提下，仅用本仓库完成；Agent 能机器判定发现、执行、空结果、部分失败和能力缺口。

衡量单位是[分析动线](analysis-journeys.md)，不是 operation 数量。动态目录规模只从 `gravity agent-catalog` 与 compiler 获取，不在路线图手写。

## 当前优先级

1. **把 Skill Hub 交付为统一方法入口。** 所有已裁定适用于当前产品的外部方法先进入唯一 canonical Skill manifest，再同时生成 Runtime Hub 包和标准 Agent Skill 投影；分发不能伪造 readiness、validation、项目口径或依赖已满足。
2. **闭合可回答动线。** 优先修复已有产品的合同、结果可信度和调用成本，不用新增 raw operation 代替产品闭环。
3. **消除调用方猜测。** Schema、错误、owner、effect、日期窗和 allowed claims 必须随机器合同交付。
4. **只推进有新证据的候选。** 精确 blocker 与下一步最小证据见[候选矩阵](candidate-capability-matrix.md)；租户数据和权限未变化时不重复空探测。
5. **控制结构增长。** 共享 spine 串行接线；领域 core 可并行；生成 compiler、provenance、coverage 产物时串行。

## 当前架构范围

[Canonical Architecture](architecture.md) 只规定跨组件不变量，并由
[`directive.json`](../specs/agent-runtime/directive.json) 绑定 digest。当前接口仍以 CLI/SDK/Plan、
catalog 和机器合同为准；组件 Owner、成熟度与当前限制见
[Runtime Component Index](../specs/agent-runtime/index.md)。`main` 是唯一长期分支，日常变更从短命分支
经必需状态检查和 PR 合入。

## 已定决策

- Insight-first；SQL 只执行 workspace 已登记产品。
- Workspace SQL 的间接问法必须同时具备审核、跨表聚合、登记名称、日期窗和运行意图；发现只按精确登记名选择 product，无匹配返回既有配置缺口，绝不降级为 Insight、raw operation 或裸 SQL。
- 调用方能选择目录时使用 host catalog；没有 selection 时 recognizer 保持离线地板。
- `app.app_info.get` 的 Agent owner card 按 CLI/SDK 输入对象暴露 `url` 模板；Plan `run` node 仍由 `request.inputs` 承载该对象。
- recognizer 的零候选词法恢复保留原评分；只在原评分弃权且索引内证据足量、唯一并明显领先近邻时选择 owner，索引外填充词不单独构成召回依据。
- recognizer 只对显式协调结构拆分多意图；中文成对 `既…也/又…`、保留右侧名词的 `和其他` 及 `和…一起/一并` 可由各子句独立 owner 组成精确 selector 集，已登记 unavailable gap 仍作为同次交接附件返回。
- `report.get.query` 的 Agent owner card 暴露合同派生的顶层 raw 输入模板与完整 compact input schema，并优先于同 selector 的 generic operation card。
- Runtime 拥有可复用 Semantic 类型/Schema、通用指标/方法定义、版本化 URI，以及单位、可加性、时间粒度、依赖、冲突和公式结构校验；调用项目拥有具体活动名称、SKU 实值、App/埋点绑定、项目专属公式参数与生效窗口和部门口径。
- Skill Hub 的 canonical manifest 是统一方法与口径边界；Runtime Hub package 与 Host Agent `SKILL.md` 是同一 manifest 的两个确定性分发投影。Agent Skill 可安装不提升静态或运行时 readiness，外部来源只有先完成适用性、独立创作和许可裁决后才能进入 manifest。
- Agent Skill 分发完成不等于 Method Complete；`generate_method_gap_report.py` 的逐项机器结果继续作为方法完整度 Owner，未完整 manifest 是后续 Skill Hub 内容深化的首要输入，不由 ZIP 数量或可安装状态掩盖。
- CT05 按获批 staged epic 将适用外部方法清单固定为 43 项；最终退出要求 43/43 均为 Method Complete、每项至少三类结构化运行示例、Runtime 自有依赖无缺口，项目自有 Semantic/Context 缺口有可验证模板。内容完整不自动提升 readiness。
- CT05 已通过 [`skill-library-v2`](https://github.com/mmm1h/gravity-insight/releases/tag/skill-library-v2) 发布：标签固定到 `ad1097443e6fd29bdcdb9bf36ce803271be2ae47`，90 个 receipt-bound 资产加 build manifest 均通过 checkout 外回读，43/43 Runtime 与 43/43 Agent archive 完整验证；canonical source SHA-256 为 `b03992523e2bbb9c31c4c50d8b35af143ddaaa44a30b3fc2becb6a7364e6ad71`，build manifest SHA-256 为 `b23fc0e657e2ed6defb81ecb5f8f050a03ace04aa026c5198cb603e3c93c3243`。已公开的 `skill-library-v1` 85 个资产保持不变，使旧 lock 的 URL、摘要与安装能力继续可用。
- 0.3.5 已将 Runtime wheel 内置业务 Skill 数收敛为零，并把 43 项外部方法与第一方 AP 成本参考方法统一为 44 项 canonical Library。`skill-library-v3` 的 93 个资产与 checkout 外摘要回读通过，但 0.3.5 客户端会拒绝 GitHub Release 必需的一次 CDN 重定向，因此 v3/0.3.5 不作为跨设备可用组合。0.3.6 与不可变 `skill-library-v4` 是修正通道：Source 显式锁定允许主机、最多一跳，R01 仍只接受项目精确 lock 与本地核验 CAS；v1/v2/v3 资产保持不变。
- Skill Library build receipt schema 直接升级到 v2，将完整本地 QA tree 与 GitHub Release 的扁平 `release_assets` 分开；receipt schema v1 从未发布且没有当前消费者，因此该破坏性升级不损失读取或安装能力。
- 读取共享全局有界并发预算；不叠加 adapter 私有线程池或增加请求总量。
- Session、CredentialProvider、metadata/operation catalog、FieldPolicy metadata snapshot 与 receipt state 按 resolved env、账号、principal、credential generation 和 workspace 的不可逆摘要隔离，默认 env 不例外；host limiter 与单一进程 Governor 继续全局共享，scope 摘要不进入公开输出。
- 未登记字段、破坏性响应漂移、身份/权限不确定和不完整分页 fail closed。
- Probe 语义只使用六态机器模型；`unknown` 不等于 read，静态 read candidate 不构成授权，未证实 POST
  必须在任何凭据或网络动作前归入 `unsafe_unknown` 并失败关闭。
- 写入固定 preview/dry-run、人工确认、显式 execute、写后读回；自然语言不自动写。
- 破坏性调用方 surface 升级不保留兼容别名，但同一发布必须迁移 canonical consumer。
- issue #28 将受治理 SQL 的泛化失败 code 直接升级为 stage/类别细分；固定 route、workspace SQL、
  聚合投影、并发上限和结果能力均未改变，因此没有读取能力损失，旧 generic code 不保留别名。
- `analysis.event.query` 不再接受 `$device_id + Count`：生产对照证明该组合始终被拒，而同字段
  `DistinctCount` 与事件次数 `PresetAllCount` 均可读取；因此 schema 收窄没有损失读取能力，并阻止 Agent 把
  caller 输入错误当作 retryable upstream 故障无限重试。
- 宽泛 Analysis 导出只返回不可执行的七族选择交接；每族暴露自己的 selector 和必填输入，不建立统一 dispatcher 或合并异构合同。
- 离线 `doctor` 必须绑定当前源码、editable metadata 与实际 import 来源；任一版本或根目录不一致均在 live probe 前以稳定 `INSTALL_*` 原因失败并给出重装命令。
- 当前表 schema gap 只由明确的当前态 schema，或表语境中的当前态字段加版本触发；已同步沿革仍归 `metadata:table_lineage`，两者显式并列时返回带附属 gap 的 `MULTIPLE_INTENTS`。
- 媒体报表 gap owner 仅在紧邻“报表/投放报表”的领域短语内将“煤体”归一为“媒体”；明确“不要/别混入素材表现”时仍由 `MEDIA_REPORT_ITEM_SCHEMA_MISSING` 优先交接，不扩展全局模糊匹配。
- 分析默认值 owner 仅在紧邻“字典”的领域短语内将“默人值”归一为“默认值”；不扩展全局编辑距离或通用错字表。
- 归因表现 owner 仅在“归音”紧邻“表现/汇总/聚合”时将其归一为“归因”；配置否定仍由原有 affirmative-intent 解析，其他“归音”语境不参与全局模糊匹配。
- **已批准的授权边界**：SDK 可由调用方在请求中承担授权决策；该边界覆盖调用方提供数据库路径与 `allowed_relations`（`sql_explorer_policy.py:158`）、原始行返回及作为标签的 `trust` / `allowed_claims`（`sql_explorer.py:137`）、Hub source 的 `index_url` / `artifact_base_url`（`skill_hub_contract.py:221`），以及按路径过滤敏感内容（`repo_context_index.py:349`）。这是一项设计决策，不作为技术债登记。

## 已裁定设计

- **Artifact transfer 的主机授权来源**：Issue 19 受限子集不再把 fresh response host 当授权。合同按既有生产样本固定三个 exact origin 与 per-role path pattern，首跳和每次同 host redirect 都复核；其他 shard/path 以 `MATERIAL_ASSET_SOURCE_UNSUPPORTED` 失败关闭。新增 origin 只能由值无关生产证据扩合同，不动态学习。
- **Issue 19 关闭路径**：按 fresh-response 可证明子集闭环，不宣称任意历史 ID。`local` 的 5 条自然引用与 `bytedance_project` 的 1 条非空项目素材已经覆盖 JPEG 缩略图和 MP4；普通 source projection 移除 URL，file effect 以私有读取上下文传给共享 Artifact Transfer。缺失、过期、未缓存、删除和二进制权限没有可靠区分信号，统一为 `MATERIAL_ASSET_BINARY_UNAVAILABLE`。破坏性影响是两个 source operation 的直接 URL 消费者必须迁移到 `material.asset.fetch`；已证明的素材内容读取能力由 CLI/SDK/Agent file effect 保留，Plan 仍因文件副作用设计不适用。

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
- 历史与外部调研过程由 Git 保存；当前文档只保留写入唯一 Owner 的有效结论。
