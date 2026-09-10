# 路线图

产品目标：任何数据分析任务都能在不打开 Gravity Web 的前提下，仅用本仓库完成；Agent 能机器判定发现、执行、空结果、部分失败和能力缺口。衡量单位是[分析动线](analysis-journeys.md)，不是 operation 数量；动态目录规模只从 `gravity agent-catalog` 与 compiler 获取，不在路线图手写。

## 当前优先级

1. **把 Skill Hub 交付为统一方法入口。** 所有已裁定适用于当前产品的外部方法先进入唯一 canonical Skill manifest，再同时生成 Runtime Hub 包和标准 Agent Skill 投影；分发不能伪造 readiness、validation、项目口径或依赖已满足。
2. **闭合可回答动线。** 优先修复已有产品的合同、结果可信度和调用成本，不用新增 raw operation 代替产品闭环。
3. **消除调用方猜测。** Schema、错误、owner、effect、日期窗和 allowed claims 必须随机器合同交付。
4. **只推进有新证据的候选。** 精确 blocker 与下一步最小证据见[候选矩阵](candidate-capability-matrix.md)；租户数据和权限未变化时不重复空探测。
5. **控制结构增长。** 共享 spine 串行接线；领域 core 可并行；生成 compiler、provenance、coverage 产物时串行。
## 当前架构范围
[Canonical Architecture](architecture.md) 只规定跨组件不变量，并由 [`directive.json`](../specs/agent-runtime/directive.json)
绑定 digest。当前接口仍以 CLI/SDK/Plan、catalog 和机器合同为准；组件 Owner、成熟度与当前限制见
[Runtime Component Index](../specs/agent-runtime/index.md)。`main` 是唯一长期分支，日常变更从短命分支
经必需状态检查和 PR 合入。R2-08 本次只拆发现/SQL 第一环，保留执行能力与公共 facade；17 模块 Agent 编排环和 11 模块 Plan 环留待后续版本，结构证据归[技术债第 14 项](maintainers/technical-debt.md#14-根包仍然扁平跨执行核心的大环仍未解)。
## 已定决策
- #223 adds a direct SDK/CLI material-to-registration-cohort composition without new upstream operations. Candidate date discovery is bounded and explicitly not a proven delivery window; daily scans share global budgets and retain unknown user completeness. Project-owned metric bindings and independently classified type gaps replace trial-and-error; retention remains unsupported. User platform discriminator binding is unproven, so this draft delivers diagnostic candidates, not platform-attributed users; #223 acceptance remains blocked on independent scope evidence. Existing material/aggregate/Plan capabilities are unchanged. Static, condition-free contracted user fields avoid implicit metadata reads; dynamic requests retain their existing governance. No Event grouping, privacy rule or join-key evidence changes.
- #203 用户明细 projection v2 仅纳入 7 个在线观察字段，163 个未实测候选保留 gap。保留 SDK code 字典序并纠正输入同序承诺；原两列读取能力不丢失。新增 live metadata、task-bound 总数、类型与空值诊断；分阶段下载须携带同任务收据。没有删除读取入口，旧无收据任务不提升为完整导出；迁移见 [0.3.15](migration/0.3.15.md#user-detail-export-projection)。本地阶段里程碑不是合入或发布声明。
- R2-01 采用 `@1` 失败关闭与显式 `@2` 合同并存：无依据的总体、归一化占比、漏斗累计不再成功；合法逐行比较保留，金额汇总及真实线性漏斗通过新合同的 scope、允许聚合轴、互斥分区和 `root/equal/subset` 谱系恢复。没有删除读取入口或合法分析能力，不静默别名升级；三组场景 Model 提供版本后继并同步参数 digest。八个 Skill 定义的 URI 不在本批迁移，交由 R2-05/R2-12 连同内容 digest、lock、分发工件处理。消费边界和安全回滚见 [0.3.15 迁移说明](migration/0.3.15.md)。
- 本机缓存统一根解析并保留旧账号快照位置回退，读取能力与 principal/账号分片语义不变；缓存盘点/回收见 [CLI](reference/cli.md#本机缓存)。不自动迁移 SQLite、不跨 workspace 共享 CAS；无完整引用证明的热点只报告保留，不宣称已完成 GC。
- #171/#170 的当前取证裁决见[脱敏收据](../evidence/forensics/20260907_operation_recertification.json)：Scatter 补登记已观察的嵌套字段；订单细查仅在末页回显、SDK has_more=false、累计条数等于 total_number 三项齐全后提升 completeness。所有原读取入口与已登记字段保留，没有读取能力损失，也未改变调用参数或结果 envelope；只刷新对应 operation 的版本、指纹与 Validation。默认值字典的可选键 warning、本地素材的空数组元素类型、素材报表空样本仍是未闭合证据，user_detail 的 cohort completeness 继续 unknown；不以声明升级代替现场证明。
- #176 需求 1 只允许显式开启的凭据失效切换，默认单账号能力不变；429 仍走既有退避。2026-09-07 Owner 的独立进程复现否定同 IP 下的账号级限流隔离，需求 2 不推进。完整读取以账号/世代租约重跑，权限与数据范围准入未知即拒绝；高级入口和机器状态见 [SDK 多账号边界](reference/sdk.md#多账号鉴权失效切换高级默认关闭)。#175 的一般刷新根目录重绑定保持独立交付，本变更不修复或依赖该缺陷。单账号读取能力没有删除或降级。
- Owner 裁定 CLI 启动更新默认开启且真实安装，包括 Hard break；精确 pin、doctor 与显式关闭继续有效。安装使用独立不可变 pip stage，校验后由新进程执行，失败回退到未改动的基础环境，不在业务执行中换版。换版留机器可读记录，详见 [0.3.10 迁移指南](migration/0.3.10.md)。变化不删除任何读取 surface，外部 Installer 计划合同仍保留；调用方若需固定语境必须显式 pin 或关闭自动更新。
- Insight-first；SQL 只执行 workspace 已登记产品。
- Workspace SQL 的间接问法必须同时具备审核、跨表聚合、登记名称、日期窗和运行意图；发现只按精确登记名选择 product，无匹配返回既有配置缺口，绝不降级为 Insight、raw operation 或裸 SQL。
- 调用方能选择目录时使用 host catalog；没有 selection 时 recognizer 保持离线地板。
- `app.app_info.get` 的 Agent owner card 按 CLI/SDK 输入对象暴露 `url` 模板；Plan `run` node 仍由 `request.inputs` 承载该对象。
- recognizer 的零候选词法恢复保留原评分；只在原评分弃权且索引内证据足量、唯一并明显领先近邻时选择 owner，索引外填充词不单独构成召回依据。
- recognizer 只对显式协调结构拆分多意图；中文成对 `既…也/又…`、保留右侧名词的 `和其他` 及 `和…一起/一并` 可由各子句独立 owner 组成精确 selector 集，已登记 unavailable gap 仍作为同次交接附件返回。
- `report.get.query` 的 Agent owner card 暴露合同派生的顶层 raw 输入模板与完整 compact input schema，并优先于同 selector 的 generic operation card。
- Runtime 拥有可复用 Semantic 类型/Schema、通用指标/方法定义、版本化 URI，以及单位、可加性、时间粒度、依赖、冲突和公式结构校验；调用项目拥有具体活动名称、SKU 实值、App/埋点绑定、项目专属公式参数与生效窗口和部门口径。
- `analysis.experiment-outcome-evaluation` 独立于建议 Journey；Handoff 只绑定外部 digest 与后置非重叠窗，不评估。`significance-test@1` 仅检验外部聚合二元比例，拒绝因果 claim 与同 run 自证；多指标显式用 Bonferroni，Plan/Agent 接线前仅 `declared`。
- Skill Hub 的 canonical manifest 是统一方法与口径边界；Runtime Hub package 与 Host Agent `SKILL.md` 是同一 manifest 的两个确定性分发投影。Agent Skill 可安装不提升静态或运行时 readiness，外部来源只有先完成适用性、独立创作和许可裁决后才能进入 manifest。
- Agent Skill 分发完成不等于 Method Complete；`generate_method_gap_report.py` 的逐项机器结果继续作为方法完整度 Owner，未完整 manifest 是后续 Skill Hub 内容深化的首要输入，不由 ZIP 数量或可安装状态掩盖。
- CT05 按获批 staged epic 将适用外部方法清单固定为 43 项；最终退出要求 43/43 均为 Method Complete、每项至少三类结构化运行示例、Runtime 自有依赖无缺口，项目自有 Semantic/Context 缺口有可验证模板。内容完整不自动提升 readiness。
- CT05 已通过 [`skill-library-v2`](https://github.com/mmm1h/gravity-insight/releases/tag/skill-library-v2) 发布：标签固定到 `ad1097443e6fd29bdcdb9bf36ce803271be2ae47`，90 个 receipt-bound 资产加 build manifest 均通过 checkout 外回读，43/43 Runtime 与 43/43 Agent archive 完整验证；canonical source SHA-256 为 `b03992523e2bbb9c31c4c50d8b35af143ddaaa44a30b3fc2becb6a7364e6ad71`，build manifest SHA-256 为 `b23fc0e657e2ed6defb81ecb5f8f050a03ace04aa026c5198cb603e3c93c3243`。已公开的 `skill-library-v1` 85 个资产保持不变，使旧 lock 的 URL、摘要与安装能力继续可用。
- 0.3.5 已将 Runtime wheel 内置业务 Skill 数收敛为零，并把 43 项外部方法与第一方 AP 成本参考方法统一为 44 项 canonical Library。`skill-library-v3` 的 93 个资产与 checkout 外摘要回读通过，但 0.3.5 客户端会拒绝 GitHub Release 必需的一次 CDN 重定向，因此 v3/0.3.5 不作为跨设备可用组合。0.3.6 与不可变 `skill-library-v4` 是修正通道：Source 显式锁定允许主机、最多一跳，R01 仍只接受项目精确 lock 与本地核验 CAS；v1/v2/v3 资产保持不变。
- Skill Library build receipt schema 直接升级到 v2，将完整本地 QA tree 与 GitHub Release 的扁平 `release_assets` 分开；receipt schema v1 从未发布且没有当前消费者，因此该破坏性升级不损失读取或安装能力。
- 0.3.5 的“wheel 内无业务 Skill registry/resolver”边界继续成立，但分发形态有意识地部分回退为唯一 manifest-bound 密封镜像：同一 CT03 构建把 build manifest、两个 index、Agent index schema 与清单绑定的 Runtime/Agent ZIP 封入 wheel seed，原始 canonical library 和外部 Source Registry 仍不入包。默认离线 bootstrap 在普通 CLI dispatch 前复用 source/lock/archive/CAS/state 原语，以 generation + receipt pointer 原子激活并只读报告项目 lock 更新；相同 digest 短路，失败保留 last-known-good。Host plan 只向 Codex 和 Claude 原生机制交付已验证 CAS 源，保留本地修改并把 activation 限定为下一次宿主启动。
- 读取共享全局有界并发预算；不叠加 adapter 私有线程池或增加请求总量。
- Session、CredentialProvider、metadata/operation catalog、FieldPolicy metadata snapshot 与 receipt state 按 resolved env、账号、principal、credential generation 和 workspace 的不可逆摘要隔离，默认 env 不例外；host limiter 与单一进程 Governor 全局共享，scope 摘要不进入公开输出。#175：receipt 与 observation 在请求开始时共同绑定当前世代；刷新重放重新解析，在途响应及传输重试保留原绑定，不替换 Runtime 或连接池。
- 未登记字段、破坏性响应漂移、身份/权限不确定和不完整分页 fail closed。发布收据逐字段解释拒绝，并绑定当前 run/attempt 的步骤覆盖，measure 跳过不能形成发布级通过；收据 CLI 必需覆盖输入已同步迁移 workflow/tests，不损失数据读取或只读 measure 能力，不替代发布后 provenance。
- Probe 语义只使用六态机器模型；`unknown` 不等于 read，静态 read candidate 不构成授权，未证实 POST
  必须在任何凭据或网络动作前归入 `unsafe_unknown` 并失败关闭。
- 写入固定 preview/dry-run、人工确认、显式 execute、写后读回；自然语言不自动写。
- Kanban 单动作 schema 同时暴露 JSON-Schema 形状与集合边界；`dashboard.report.link` 的一次请求为 `1..20`，解码后整个 dashboard layout 独立为最多 20 项并跨 link 请求累计。整板 prepare 在首写前只读编译全部 saved artifact、判定 reuse/create/update/link、返回延迟 ID DAG 和快照写次数上界；它不新增整板执行器，不改变任何 mutation 的 preview/execute、owner、幂等、锁或写后读回。仓库只证明 20 是当前 SDK 治理 wire 合同；保留取证明确未在生产强制触发容量拒绝，无法证明 Gravity 上游也实施相同数字限制。
- 破坏性调用方 surface 升级不保留兼容别名，但同一发布必须迁移 canonical consumer。Repository Map v2 只将 entry string、issue path 和 module node 换成确定性表；loader 解码后仍校验完整 v1 fact schema，逐字段往返测试证明 entry、issue location、节点和边不丢失。仓库内 task-context、validation observation 与有序 checkpoint 已同步；外部 raw JSON 消费方按 0.3.8 迁移，读取能力没有损失。五个内置 Model 的 `claim_policy.validated`、`scenario` 与 `forbidden` 已从自然语言直接升级为规范稳定 ID；`models describe/evaluate` 的字段、模型 URI、审批选择逻辑、模型产物和数据读取能力均未删除。`causality` 复用 Skill/Journey 现有 ID；没有精确上层对应物的 Model 约束保留为独立 ID，不用更宽或更窄的近义约束代替。调用方必须把 claim 值作为 ID 消费，不保留自然语言别名。`user-detail-aggregate` 将隐私策略排除与字段未登记拆成不同错误码，并将条件类型不符从真实行混型中拆出为不可重试的 `caller` 错误；诊断现精确定位 filter/measure、字段与两侧类型，真实行混型仍是原 `upstream` code。`bytedanceMid1..8` 的孤立前缀排除已删除：公开字典证明 `Mid1..6` 是投放物料/落地对象 ID，`Mid7/8` 精确业务子类型尚无仓库证据，但没有个人标识依据，故只恢复物理字段的有界聚合能力；三条既有个人/敏感字段策略和无用户行输出不变。`WITH_VAL` 的 JSON 非 null 语义不变并进入 machine schema，非空字符串由既有 `WITH_VAL []` 与 `NOT_EQUALS [""]` 组合表达，不新增操作符、不放宽同型条件校验，也不损失原读取能力。精确匹配旧 code/category/message/field 的调用方按 0.3.11 迁移，不保留会重新合并原因的兼容别名。
- issue #28 将受治理 SQL 的泛化失败 code 直接升级为 stage/类别细分；固定 route、workspace SQL、聚合投影、并发上限和结果能力均未改变，因此没有读取能力损失，旧 generic code 不保留别名。
- issue #110 将 registered SQL verification 固定为登记顺序单并发，并用严格前缀 checkpoint 续跑最终 429；不能选择或跳过产品。新 Evidence v2 记录单次或分段完成，reader 继续接受已发布 v1，因此六个产品的读取与历史 readiness 能力均未删除；变化只移除 verification 的并发调度并增加可审计续跑。issue #115 又将执行状态与数据完整性拆开：结果加性返回 cap 命中、`complete|unknown` 和判定原因；正好命中 cap 且无独立总数时是 `possible_truncation`，N+1 多出一行仍失败关闭；本地传输不裁行，但上游是否另有响应行上限无合同证据，readiness 和正好 N 行均不提升 cohort 完整性。
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
- 动线状态由 `governance/journey-ledger-facts.v1.json` 拥有，旧注释单列 `journey-ledger-annotations.v1.json`，再生成[分析动线](analysis-journeys.md)；snapshot v2 只改变来源身份，旧行字段、顺序与摘要等价，读取能力无损，当前消费者不再解析 Markdown。graph definition/baseline 同样由 `governance/module-graph-*.v1.json` 拥有。
- 工作提案和请求账本放 `tmp/`；不要再创建逐趟 Markdown。
- 2026-09-09 R2 审计是固定输入，已吸收结论退出默认阅读链；其他 R2 任务仍独立验收，不据文档迁移宣称 Host 毕业。CT01–CT05 保留有效合同、来源/权利边界与固定发行证据，施工史由 Git 保存；历史生产认证不代表当前状态。
