# 技术债清单

本页只记录会提高后续开发成本、且可由当前源码或质量门禁证明的结构性债务。机器阈值与当前
数值以 `src/gravity_sdk/governance/quality-baseline.json` 为准；这里不复制整份 baseline。

内部审计发现不创建 GitHub Issue。Issue 仅接收其他项目真实使用时提交的反馈；本页、当前开发
提交和回归测试负责内部债务的收口。

## 维护规则

- 记录 owner area、证据、触发条件和退出条件；没有证据的“以后可能”不登记。
- 修改热点附近功能时优先下沉到领域模块，不放宽 SLOC/复杂度 baseline。
- 重构必须保持公共 operation/envelope/CLI 兼容；不借一次纵切重写无关模块。
- 每轮完成后删除已关闭条目，或把其结果压成一行历史记录，避免清单本身变成档案库。

## 当前条目

登记于 2026-08-13，依据 `dev@8fd278e` 的源码与质量门禁审计。

### 1. Material/Promotion 重复实现多平台结果重建

**状态（2026-08-15）**：退出码触发项已按退出条件收窄，其他重复仍保留。

- **Owner area**：Material Performance / Promotion Performance result contracts。
- **证据**：`material_performance_result.py`(408 SLOC) 与 `promotion_performance_result.py`(434 SLOC)
  各自实现同名同构的 `safe_component`、`_safe_success`、`_safe_rows`、`_safe_page`、page receipt 校验、
  `product_envelope`、`_primary_error`。Promotion 上线后又经 `464b1d4`、`099ad46`、`81d0d02` 修补
  结果边界、request binding 与 Plan rows/output paths——相同不变量存在两份，修补时必须人工检查另一份。
  本轮新增字段触及 500 SLOC 闸门后，已把纯字段登记下沉到 36 SLOC 的
  `promotion_projection.py`；本轮修改 component aggregate exit code 时又把两边相同的 category→exit
  数字映射下沉到 `errors.exit_code_for_category`。`_safe_success` 复杂度仍为 14，
  其余 row/page/result 重建仍是可证明的重复，故本条不关闭。
- **触发条件**：任一产品再次修改 page receipt、标量行复制、component aggregate status/exit code/
  primary error；或出现第三个采用同一完整分页 batch envelope 的多平台产品。
- **退出条件**：仅在触发发生时，把当次由两边现有测试证明完全相同的**一个**窄原语下沉复用；
  operation identity、字段 allowlist、App/window/metrics binding、failure wording 继续留在各自 owner。
  **不做整文件统一，不造结果 DSL。**

### 2. legacy promotion snapshot 绕过正式产品的全部绑定

- **Owner area**：Promotion 兼容面（CLI/SDK legacy permissive snapshot）。
- **证据**：2026-08-14 缺面裁决查明，该面绕过 `promotion performance` 的五项约束：
  workspace App 绑定、统一日期窗、已证明平台集合、指标 allowlist、平台 metadata 指标校验，
  且不校验返回结果是否仍绑定请求的 App/日期/指标。它接受任意非空 promotion resource 与
  逐平台原始 input，按 inventory 选择**首个** stable operation；CLI `all` 模式会按各 operation
  schema **静默忽略**不适用的 shortcut。本轮已确认它不进 Agent/Plan 主路径
  （`gravity agent "raw promotion snapshot"` 返回 capability_gap），但 CLI/SDK 入口仍在。
- **为什么保留**：没有消费者遥测能证明无人直接使用，删除即可能造成外部破坏。
  这是**有意的保留，不是遗忘**。
- **触发条件**：该面出现新的调用方报告；或 Promotion 产品再次修改平台集合、指标 allowlist
  或结果绑定校验——届时两处语义会进一步分叉；或取得可证明无消费者的证据。
- **退出条件**：优先**收紧到与正式产品同一组绑定**（App/日期/指标/结果校验），
  使两条路径语义一致；确证无消费者时直接删除。**不要为它补 Agent 卡或 Plan 面**——
  那是在把未校验路径推给自动化调用方。静默忽略 shortcut 的行为无论保留与否都应改为显式报错。

### 3. 在线输入解析的两次闭环依赖「上游稳定 ID 不复用」，而这证明不了

- **Owner area**：Agent 输入解析（`agent_input_resolution.py`、`agent_input_catalogs.py`）。
- **证据**：2026-08-15 的裁决把 9 条动线从 `1 / 3` 降到 `1 / 2`，做法是第一次调用同时交付
  能力与完整目录、第二次重新在线解析后执行。该方案的正确性依赖两点：调用方按**稳定 ID** 选择，
  以及第二次执行时重新解析。但**上游没有 revision/ETag**，无法证明它永不复用已删除对象的 ID。
  实现方自己给出了这条反驳，并明确：一旦发现 ID 复用，必须撤销这 9 条的两次闭环判定。
- **触发条件**：观察到任一目录对象的 ID 被复用；或上游开始提供 revision/ETag/版本号。
- **退出条件**：上游提供可校验的版本标识后，把它纳入第二次解析的前置校验，ID 复用即 fail-closed；
  在那之前**不扩大**该模式的适用面——不要把在线输入解析套用到新的动线上来降低调用次数。

### 4. `REPORT_PRODUCTS` 的名字已经和它的内容对不上

- **Owner area**：`agent_report_routing.py`。
- **证据**：该 frozenset 现含 `advertiser_profile`、`custom_audience` 两个 promotion 产品，
  常量名与模块 docstring 里的 "report" 已不成立（docstring 已改为 "bounded no-spec products"，
  常量名没跟着改）。它实际的语义是「无 spec、边界固定的窄产品路由」，与 report 域无关。
- **触发条件**：再加入第三个非 report 域产品，或有人据名字误以为该集合限定 report 域。
- **退出条件**：触发时连同调用点一次改名到位（如 `NO_SPEC_PRODUCTS`）；单独为改名开一次提交不值得。

### 6. Census 把 214 条 POST 仅凭路径词元判为「未覆盖读」

**状态（2026-08-16）**：在线安全缺口已关闭；非推广/素材 155 条已逐条分类，剩余分类证据债务收窄到
188 条既有数据阻塞 draft 与 5 条仍无法判定 route。

- **Owner area**：Census 路由语义分类 / 探测安全。
- **证据**：2026-08-14 取证证明 `analysis.setting.query`（`POST /kanban/report/setting/`）
  **是 mutation 不是查询**——完整前端控制流显示它提交 `config/name/remark`、随后更新看板布局
  并提示修改成功。但 census 此前把它判为 `status=uncovered_read`，唯一语义证据是
  `read_action_path_token`（路径里有 read 味的词），`semantic_confidence=medium`。
  该 draft 已有 **3 次真实 probe 记录**（`2026-08-08`），即探测确实打到了写路由上；
  只因语义报错才没造成写入，**这是运气不是设计**。
  实测同类分布：343 条 `uncovered_read` 中 **261 条（76%）唯一证据就是 `read_action_path_token`**，
  其中 **214 条是 POST**；仅 60 条有 `safe_http_method`（GET，HTTP 语义本身安全），22 条为 registry 声明。
  样本里 `/account_center/api/v1/get_verify_code/v2/` 同样可疑——发送验证码是副作用动作。
- **触发条件**：任何人对 `uncovered_read` 池中的 POST 路由发起 probe；或把这类候选纳入排期。
- **退出条件**：**先加探测闸门**——仅有 `read_action_path_token` 的 POST 路由默认禁止 probe，
  需要逐条人工确认读语义后才放行；再逐步用控制流证据替换弱信号分类。
  **不要反过来把它们批量标成 mutation**——那会误伤真正的读路由；
  正确方向是把"未经证实"与"已证实为读"分开，而不是二选一。
- **注意**：`docs/maintainers/probing.md` 现有纪律针对请求量与隐私，**不覆盖"目标是否真的是读"**。
  这条债务补的是那个缺口。
- **已完成**：`prober/read_semantics.py` 在凭据刷新和 transport 构造前预检显式 probe/batch，且
  `probe_draft` 在任何 discovery 请求前再次执行同一策略；本地策略错误为 exit 4。精确人工确认清单
  强制记录 reviewer、日期与静态证据。12 条静态抽样为 2 写 / 10 真读 / 0 不确定；这不证明多数
  路由误判，但证明风险跨“发送验证码”和“修改报表设置”两个域，不是单一异常。2026-08-15 又逐条
  补入 dashboard tree/detail 与 report-config list/get 四条 GET 的控制流确认；这四条是已审查真读，
  `analysis.setting.query` 仍是 mutation，未据此批量修改剩余弱信号分类或扩张 census 提取器。
- **剩余退出条件**：后续只在逐条静态取证时把弱信号替换为已审查证据；不扩张 census 提取器，
  不批量改 mutation。待弱证据 POST 不再需要依靠单独 probe 闸门时删除本条。
- **2026-08-16 进展**：对 343 条 `uncovered_read` 排除 188 条 promotion/material draft 后的 155 条
  完成互斥逐条复核，最终为 `18 等价覆盖 / 89 UI 辅助 / 4 mutation / 0 当前可取证 / 39 数据或证据阻塞 /
  5 无法判定`。本轮把 10 条 AppRank/data-table POST 的 hash-matched 控制流登记为精确 read
  confirmation，并用 10 次有界生产 HTTP 验证最高价值候选；没有用失败或空样本批量改 Census status。
  `promotion.promoted_object.list` 的 draft POST 与 Census UNKNOWN method 差异继续保留为显式证据差异。

### 7. `agent-catalog` 与 Agent 产品 / gap 身份不共源

- **Owner area**：`agent_catalog.py`、Agent 产品卡来源、外部 selector 协议。
- **证据**：2026-08-16 的 336 题 development 盲选中，三层目录含 229 个 operation/composite selector，
  但没有 Analysis kind-specific Spec、period compare、user journey、metadata search/table lineage、
  material export/asset 等 evaluator 正在评分的产品身份，也没有任何目标 gap identity。结果是事件/漏斗/
  留存/属性/散点/分群规则的 42 题只能选到语义相符的 raw operation，却按产品层正确判为
  `wrong_product`；96 个 `none` 逐题反查均没有精确目标目录项；外部协议又只能把空数组变成
  `EXTERNAL_SELECTOR_ABSTAINED`，不能返回目标 gap code。J35 还出现目录把
  `app.realtime_event.list` 声明为已验证可执行，而动线目标仍是合同缺失 gap 的事实冲突。
- **触发条件**：任何宿主 LLM、MCP 或其他调用方把 `agent-catalog` 当 canonical capability interface；
  或新增/迁移一个只存在于 recognizer/evaluator、没有目录身份的产品或 gap。
- **退出条件**：复用现有 composite / plan adapter / Agent card 权威来源，让所有公开 journey target
  identity 在目录中可发现；非执行 gap 也有稳定 code、reason、next action，并允许外部 selector 显式
  选择。增加机械 parity 门禁，证明每个公开目标恰有一个目录身份或被明确登记为 workspace 外部来源。
  **不新建第二套 registry，不把 raw operation 冒充产品卡，也不为达标修改评分目标。**

## 明确不登记为债务

以下模式经审计判定为**合理领域边界**，不因文件数量多而登记：45 个 `agent_*.py`、
10 个 `_field_policy_*.py`、21 个 `*_cli.py`。不建议合并它们，不建议把 `*_cli.py` 换成动态命令
注册，不建议增加字段 DSL，不建议统一所有 composite result/error/pagination 模型，
不建议放宽或更新 baseline 来容纳增长。

## 已关闭结构债务

2026-08-15 修改确认记录读取逻辑时，`_confirmation_keys` 已提升为公开 `confirmation_keys` 并更新跨模块
调用点；精确 method/path、人工证据与已知命名空间三重闸门保持不变，原第 5 条债务关闭。

Agent 相邻产品冲突已收口到 `agent_intent_routing.py`：按独立 owner 正向证据强度与 selector 精确度
裁决，多个产品返回 `MULTIPLE_INTENTS`，历史紧邻冲突集中兼容；五个既有 owner 不再持有他产品负向词，
raw exact selector、敏感查询和既有 pairwise 行为保持。

Agent 自然语言重验已关闭原“产品卡与 raw operation 混排”债务：kind-specific Spec 卡保持唯一权威，
新增 class-level `metadata:search` typed handoff，exact raw selector、recipe/SQL product 优先级和显式
`MULTIPLE_INTENTS` 回归均保持；47 条冻结动线中英首问无 raw fallback 混入。

Plan 固定来源 composite 已下沉到窄 family router；并发增强复用同一全局预算租借，中央
`plan_adapters.py` 低于原 491 SLOC 基线且没有新增 registry、插件或产品三重知识。

本轮已把 CLI 路由、Plan adapter、Multidim service 和 Agent 卡分别下沉到领域模块；通用入口只保留
薄路由，direct/Plan 共用 worker 预算，旧 raw 合同继续兼容。后续若这些模块再次触发机器 ratchet，
再以当时的源码证据登记新条目，不保留已经关闭的历史任务。

Business Pulse 的 generic Agent 交接缺口已由领域 recognizer、完整 Plan request 和 authoritative
路由收口；执行 core、CLI、SDK 与 Plan adapter 继续复用原实现。`apps/platforms` 的无效数组绑定
入口也已关闭，不保留第二套运行时或未证明的结果层债务。

Promotion Performance 已把 parser/dispatch/shortcut、产品 core、结果重建、SDK、Plan 和 Agent
分别下沉到领域模块；旧 promotion CLI 与 `CompositeService.promotion_snapshot` 只保留兼容薄委托。
通用热点与 quality baseline 未增长，原退出条件已完成，不保留已关闭的活动条目。

Order Split Trace 把“完整父目录精确匹配后再读取 child”的敏感派生留在登记领域 composite，
不把数组 binding、join/reduce 或通用 parent-child DSL 引入 Plan；这一限制是安全产品边界，不登记
为通用引擎债务。Agent 的中英 recognizer、占位 Plan 节点、相邻产品阻断与 raw exact 兼容均在
领域模块内闭合，通用 discovery 入口只保留薄路由。

Order Directory 已以单日四字段 profile、完整分页和 request-bound 结果闭合 Core/CLI/SDK/Plan/Agent；
与 Order Split Trace 共用读取收据和静态字段策略，raw exact selector 继续兼容，通用热点未增长。

Monetization Detail 已以批准字段 allowlist、嵌套重建和保留型 Guard 闭合五面入口；Plan 复用窄
Analysis family router，`plan_adapters.py` 净增长 0，D28 聚合未被误纳入本产品。

Quality profile 已删除与 runtime root 同路径的冗余 CLI 扫描；每个函数 identity 仅产出一次，Markdown
函数/复杂度超额与未修改的 baseline 一致，500/80/15/0 阈值和失败策略保持不变。

Consumer-output 安全审计未新增结构债：上游业务内容继续留在结果容器，receipt/log 保持值无关；
workspace recipe 与 SDK contract 的同名 description 已用 additive origin 元数据区分，公共 JSON writer
统一拒绝非有限数字，不引入内容检测、评分或新的字段 DSL。

多 App Analysis 扇出仅在领域 batch/surface 中把显式 `apps` 展开为现有同层 Plan 节点；没有新增
线程池、worker 默认值、adapter registry、跨 App 结果抽象或共享 spine 分支。机器 quality ratchet
保持，`plan_adapters.py` 未修改；本轮复核未产生新的结构债条目。

Analysis Spec schema 的结构键投影与 funnel 按日模式校验已在领域 schema/执行器和源合同内闭合；
共享 CLI spine 未修改，真正畸形的模式投影继续 fail closed，本轮复核未产生新的结构债条目。

三分评测装置把 protected 查询反馈、final 一次语义与安全遵守门禁收进独立 evaluator/support 模块，
没有增长产品共享 spine 或 quality baseline。外部 LLM shell/tool trace 不在本仓装置可见范围，属于已披露的
测量覆盖边界，不是当前源码中会提高后续开发成本的结构债；本轮复核不新增条目。

派生指标与集合对账经独立 core、CLI/Agent owner 模块及既有 Analysis family router 接入；
`plan_adapters.py` 净增长 0，没有新增通用表达式引擎、adapter registry、数据框依赖或业务字典，
本轮复核未产生新的结构债条目。

Segment mutation 首轮把一次性授权、wire codec、领域 CRUD、CLI/SDK 与 Agent 交接拆入窄模块，
`registry.py` ratchet 继续收紧且 Plan spine 未增长；本轮复核未产生新的活动结构债条目。

F40 单用户归因明细把严格结果重建与测试设备父目录解析下沉到领域模块；共享 client、Agent/Plan
路由均保持既有质量 ratchet，空 item 容器按未来非空 fail-closed 而未引入通用动态 schema，
本轮复核未产生新的活动结构债条目。
