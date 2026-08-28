# 技术债清单
只登记当前源码或质量门禁能证明、且有明确退出条件的结构债务；产品缺口、上游无数据、历史事故和一次性工作不登记。
每轮仅更新受影响条目：满足退出条件即删除正文并在末尾留一行历史，完整旧内容见归档快照。

## 当前条目
登记于 2026-08-13，依据 `dev@8fd278e` 的源码与质量门禁审计。
### 2. legacy promotion snapshot 的兼容分支仍缺正式绑定
**状态（2026-08-25）**：除 `primary` 21 平台外，`bytedance/project`、`honor/ad_group`、`honor/campaign`、
`kuaishou/ad_unit`、`ubix/group` 已复用 Promotion Performance 的 App、日期、平台/指标、分页和结果绑定。逐条重列
发现原记 32 实为 33：漏记的 `ubix/group` 五项条件全满足，已转正；其余 32 个组合的卡点逐条复核后全部仍准确。
- **转正证据**：五项 stable contract（`21 primary + 5 + 32 = 58`）均有必填 `date_list`、App 等值 `filters`、动态 `query_fields`、同构
  `page_info` 和登记行投影；合同漂移 fail-closed。同一 canonical 输入经原 inventory 内核与正式入口产生完全相同的
  operation payload 和原生行，正式结果使用 `gravity-insight.promotion-performance.v1`，不再携带 compatibility marker。
- **primary 卡点**：`bing/advertiser`、`xiaohongshu/advertiser` 无日期/动态指标；`taptap/group`、
  `wechat_video/report` 有 App/日期但无 `query_fields` 与动态指标结果绑定。
- **其余层级卡点**：`bilibili/account` 无动态指标；`bytedance/advertiser_performance` 无 App/动态指标；
  `tencent/tencent_adgroup_v2` 虽接收 `query_fields` 但结果未登记动态字段。其余 25 个 account/config/parent 层级
  无必填日期和动态指标（多项也无 App）：bytedance 除 project/advertiser/performance 外 9 项、honor/account、
  huya/account、kuaishou/account+account_company、oppo/qihu360/sigmob/ubix/vivo/weibo/xiaomi/youdao 八项 account、
  tencent 的 3 个配置层级及 xiaohongshu/developer。
- **兼容边界**：上述 32 项仍从 stable inventory 精确匹配后透传 raw input，保持
  `gravity-insight.composite.promotion.v1` 和 `formal_binding_validation=not_performed`；零匹配 unavailable，多匹配或
  不适用 shortcut 执行前失败。`query_fields` 仍过 `FieldPolicy`；无消费者遥测时不得删除，Agent/Plan 仍不宣传。
- **触发条件**：兼容平台/层级出现第二个同资源 stable read，取得正式输入/结果绑定，或能证明无消费者。
- **退出条件**：为所有保留兼容平台/层级建立不损失读取能力的正式请求/结果绑定并移入正式路径，或证实无消费者
  后删除；不得以 raw `promotion query` 替代 snapshot 聚合职责。

### 3. 在线输入解析的两次闭环依赖「上游稳定 ID 不复用」，而这证明不了
- **静态复核（2026-08-25）**：风险实际覆盖 5 个引用型 composite 的 6 个目录 operation。按版本词、结构化
  `response_projection` 和 exact operation/evidence 三路复核，只有 `create_time`/`modify_time` 等普通时间字段；
  它们没有不复用/单调语义，不能代替 revision/ETag/incarnation token。Dashboard/Segment 又无 production/wire
  item sketch，故只能证明“Runtime 当前没有可用版本标识”，不能证明实际上游响应绝对没有。
- **未扩散**：`_REFERENCE_COMPOSITES` 自首次实现仍精确为原 5 个；唯一 `live_catalog_for_card` 调用链仍由
  `resolve_capabilities` 降次。后来加入 call-bound 的 Segment members/Attribution detail 保持 3 次；测试锁住集合。
- **设计逃逸复核（2026-08-25）**：携带目录解析身份只省去执行前重读，Dashboard detail、Segment detail/history/result、
  Saved detail 仍按同一 ID 寻址，风险后移而非消除。目录全投影指纹能检测投影漂移，却不能证明同一 incarnation：
  Saved 目录行不交付 `config`，Segment 的 `origin_query` 被明确排除在 v1 投影外，故相同投影不蕴含相同执行状态。
  若所有执行相关状态完全相同，删除重建在语义上不可观测；但 Runtime 证不了这个前提。维持原退出条件。
- **退出/取证**：对 6 个 exact method+path 采 body field sketch 及 ETag/Last-Modified；须取得覆盖目录变更的 revision
  或删除重建必变的 item incarnation token（时间戳不算），再由获批测试对象生命周期或上游语义证明。首次目录交付
  token、执行前重读并比较，漂移/复用 fail-closed 后才能关闭；此前不扩大该模式。

### 7. 稳定 operation 的分页形状仍有系统性证据债
- **证据**：当前 237 条编译 operation 为 `60 complete / 177 unknown`，228 条 stable 为 `60 / 168`，stable
  `page_info` 子集为 `60 / 58`；证据为 `97 production / 9 wire / 131 template`。仅 `template_default` 的 49 条
  live `page_info` 被 `reconcile_pagination_audit` 标为 `shape_unproven`。
- **当前缓解**：合同分别声明 `completeness`/`pagination_evidence`，无证据为 `unknown`；原子读取、audit、Plan、
  composite 均传播它，`all_pages` 遇未知/前缀返回 capability gap。已确认 A 的自动读取为 Multidim metadata、
  Material Performance、Business Pulse；两个 report query 均按实测 B 不续页。缺 `total_page` 的 `read_all`
  停第一页并标 `unknown`，满页续读须 `continue_without_total`；单次无 `page_info` 不能证明永不截断。
- **静态复核与处置（2026-08-25 中间态，计数已被下文 85/83 取代，勿按本行取值）**：`reconcile_pagination_audit`
  当时把 177 unknown 分为 86 条 `collect_production_or_wire`、82 条 `not_scheduled_without_new_signal`、9 条 non-stable。82 条均站得住、0 退回，
  但 `analysis.dashboard.tree` 是 list，不是非集合；修正后为 46 条非集合（38 mutation + 8 detail/get）和 36 条
  无可证伪信号（1 静态 tree + 34 条既存 exact production observation + 1 条 shape B）。
- **设计逃逸复核（2026-08-25）**：随真实请求被动记录响应形状不属于被禁的“全量生产探测”，但**技术可行不等于该做**——
  单次观测证不了字段跨租户/权限/灰度恒存，缓存学错后 `read_all` 会按错误 `total_page` 停止并把截断结果标为 complete，
  而 agent 不会质疑，Plan/composite 继续传播；此静默错误比现有 capability gap 更危险，据此否决，未实现。
  同轮把 `analysis.segment.evaluate_percent` 转为永久 unknown（响应严格为 `part/percent/total` 三个必需数值标量，
  根本无集合语义；237 条中仅此 1 条通过该谓词），机器处置变为 `85 collect / 83 no-new-signal / 9 non-stable`，
  永久 unknown 为 `47 非集合 + 36 无信号`。完整性总账仍是 `60 complete / 177 unknown`，不伪装成 complete。
- **计划与触发**：[分页生产证据采集计划](pagination-evidence-plan.md) 的 85 条分 59、26 两批；改 unknown 分页、
  新产品依赖其全集或 exact method+path 取得新 production/wire 字段证据时触发。
- **退出条件**：逐条以同 method+path production sketch/wire 字段把 58 条 stable `page_info` unknown 归入真实形状
  并修正合同；另 27 条 stable collection unknown 须取得可证伪完整性信号或转永久 unknown；不得用合同声明、
  短页、满页启发式提级或全量生产探测。

### 14. 根包仍然扁平，跨执行核心的大环仍未解
- **接续范围**：接续已关闭 #11 中未由 R17 处理的两部分：R17 只迁移了 `agent_*` 家族，没有解决
  `src/gravity_sdk` 根包整体扁平化；跨 plan/analysis/metadata/kanban 执行核心的大环仍未拆。
- **可测事实（2026-08-28）**：`src/gravity_sdk/*.py` 共 496 个；按文件名前缀计数，`plan*` 48、`analysis*` 29、
  `export*` 16、`metadata*` 12、`segment*` 12、`kanban*` 11、`saved*` 8、`report*` 6。
- **影响边界**：当前债务不改变公开导入或运行时行为，只增加模块定位、变更归属判断和跨域审查成本；后续治理也不得
  以整理目录为由损失调用能力或改变执行 owner。
- **已解前置（2026-08-27）**：[模块依赖图 v1](#14-机器图合同) 把节点、四类边、动态导出排除边界与 Tarjan
  cyclic SCC 口径写成机器定义，可重建完整图，并由测试锁住定义摘要、图摘要与 SCC 成员及规模。
- **第一有界单元（2026-08-28）**：`to_jsonable` 从 `runtime` 下沉至叶模块 `json_output` 并保持直接再导出；credential sanitizer 改依赖叶 owner。eager AST-only 仍为 `5`，AST-only `96`→`44`（完整序列 `44,41,3,3,3,2,2,2,2,2,2,1`），加 `_EXPORTS` 仍为 `422`。
  canonical `521`→`522`：`json_output` 原本不在该 SCC 内，`runtime` 的 AST 边使其经 package-parent 并入；canonical 包含 lazy export/package-parent，因此上涨不表示拆环工作量回退，拆环仍按 AST-only `44`。
- **第二有界单元（2026-08-28）**：Plan analysis 三个不可变合同常量下沉至零包内导入的叶模块 `plan_analysis_contract`；adapter 顶层再导出同一对象，`plan_schema()` 保持函数内延迟导入，仅改 owner。eager AST-only 仍为 `5`，AST-only `44`→`41`，原 44 环拆为 `11` 和 `8`（完整序列 `41,11,8,3,3,3,2,2,2,2,2,2,2,1`），加 `_EXPORTS` 仍为 `422`。
  canonical `522`→`523`：新叶模块经 adapter/plan 的 AST 边与 package-parent 边并入既有 canonical SCC；canonical 包含 lazy export/package-parent，因此上涨不表示拆环工作量回退，真实拆环收益仍按 AST-only 的 `44` 拆为 `11` 和 `8` 判断。
  仍无可靠门禁识别不带 `agent_` 前缀却被误放根目录的未来 Agent owner；明确不恢复 v4 职责契约判据：其成员集合由预选 `included_layers` 决定，回答不了未来模块是否属于该域。
- **退出条件**：以该定义批准有界迁移单元，使上述家族迁入明确 owner 或留可机器验证的根级保留理由，消除大环，
  建立非前缀 Agent owner 判据；全程保持公开导入、运行时行为、执行 owner 与调用能力不变，并以门禁锁住结果。
- **委托决策**：`agent_under_standing_owner_delegation`；`owner_review: pending`。

## 已关闭

- 2026-08-27：#11 已关闭：R17 `fixed_dev`，82 项精确移动与 concept/owner/SCC/consumer/wheel 门禁已验收，根 `.py` 为 495、`agents/` 含 82 个实现模块；legacy/v4 脚手架退役，五条 facade 依赖按单一 owner 设计保留；`agent_under_standing_owner_delegation`，`owner_review: pending`。
- 2026-08-26：#13 公开符号遮蔽债关闭：`gravity_sdk.__init__` 把模块 `__class__` 换装为
  `_ExportAwareModule`，`__getattribute__` 对 8 个碰撞符号每次访问都重查 `_EXPORTS`，
  子模块导入把包属性覆写为 module 时按 `_is_shadowing_module` fail-closed 重新解析而非
  静默返回错误类型；`child-first`/`export-first`/`cross-order` 三种导入顺序均由隔离子进程
  测试锁定，碰撞集合本身有新增探测，未靠改名或「不要导入同名子模块」的约定规避。
- 2026-08-25：#8 Title Package 已从编译合同派生 opaque JSON 字段，复用有界深度、元素和大小投影；未登记和非 opaque 标量规则仍 fail-closed。
2026-08-19 以前关闭项见[清理前快照](../archive/snapshots/technical-debt-2026-08-19.md)。
- 2026-08-20：Census POST 读词元债关闭，`uncovered_read` 仅保留安全方法/exact 静态确认，其余为
  `unsafe_unknown`/`static_read_candidate` 且 draft selector 不消费。
- 2026-08-20：Agent 有界无 spec 路由改用 `NO_SPEC_PRODUCTS`，`REPORT_PRODUCTS` 保留同对象兼容别名。
- 2026-08-25：CT03 跨产物绑定、exact revision/index 与跨 Python archive 确定性缺口关闭。
- 2026-08-25：Material/Promotion 行与 malformed-error 边界 characterization 补齐，仅下沉等价的有界 JSON scalar 谓词。
- 2026-08-25：Windows Provider Job 绑定债关闭：挂起启动，绑定/恢复失败以 `PROVIDER_RPC_ISOLATION_FAILED` 在 RPC 前回收。
- 2026-08-25：Repo Context ignore 债关闭：两份规则绑定存在性/SHA-256，无效或漂移均 stable fail-closed。
- 2026-08-25：Provider 与 Adaptive Governor 全量门禁计时 oracle 债关闭；并发测试均改为同步握手与 30 秒死锁保险。

## #14 机器图合同
<!-- MODULE_GRAPH_DEFINITION_V1_START -->
```json
{"canonical_profile":"canonical","definition_id":"gravity-sdk-runtime-possible-module-dependency-graph.v1","dynamic_exports":{"edge":"The package containing the table points to each statically resolved owner module.","modeled_protocol":"_EXPORTS","other_protocols":"__all__, ordinary assignments, __getattr__ bodies, and generic dynamic-import calls do not create string edges.","symbol_multiplicity":"Multiple exported symbols owned by one module produce one edge.","unresolved_values":"Non-literal owners produce no edge and are not guessed."},"edge_direction":"The source module points to the module it may depend on at runtime.","edge_kinds":{"all_or_assignment_reexport":{"included_in_canonical":false,"reason":"__all__ names symbols rather than owner modules, and an assignment does not add a module dependency beyond the expression that produced its value. Inferring owners from names would be guesswork.","rule":"Do not create an edge from __all__ strings or ordinary assignment-based re-exports. Their underlying AST import, when present, remains an edge."},"ast_delayed_import":{"included_in_canonical":true,"reason":"A delayed import does not create an eager import cycle, but calling the function can execute it. The graph measures possible runtime architecture dependencies, so excluding it would hide real coupling.","rule":"Collect the same Import and ImportFrom forms inside function or async-function bodies and mark them as delayed edges."},"ast_eager_import":{"included_in_canonical":true,"reason":"These statements declare direct, statically reproducible runtime dependencies.","resolution":"Import uses the exact imported module when it is a node. ImportFrom uses the resolved module operand; for from . import x, it also uses each named child module that is a node. Star imports point to the resolved module operand. Aliases do not change the target.","rule":"Collect Import and ImportFrom statements outside function and async-function bodies, including class bodies and both potentially executable conditional branches."},"generic_dynamic_import":{"included_in_canonical":false,"reason":"Targets can depend on runtime values. Partially evaluating selected call expressions would create an unstable, incomplete graph; a new governed dynamic table requires a new definition version.","rule":"Do not infer edges from importlib.import_module, __import__, loader APIs, computed strings, or plugin-like registries other than the explicit _EXPORTS rule."},"lazy_export_owner":{"included_in_canonical":true,"reason":"The table is an executable lazy import dispatch contract. Attribute access can import its owner even though no Import AST node names that owner.","rule":"In package __init__.py modules only, collect statically resolvable owner module strings from literal _EXPORTS dictionary values and _EXPORTS[...] assignments. Resolve relative owner strings against that package. Deduplicate symbols that share an owner."},"package_parent":{"included_in_canonical":true,"reason":"Python initializes a package before loading its child module. Keeping this as a separate edge kind makes its large SCC effect visible rather than silently folding it into AST resolution.","rule":"For every non-root module node, add an edge to its immediate dotted parent when that parent is also a node."},"type_checking_import":{"included_in_canonical":false,"reason":"TYPE_CHECKING is false in normal runtime execution, so these are type dependencies rather than possible runtime dependencies.","rule":"Exclude imports in branches proven unreachable at runtime from TYPE_CHECKING or typing.TYPE_CHECKING tests; include the runtime branch of a negated test. Unknown conditions retain both branches."}},"profiles":{"ast+lazy-exports":["ast_eager_import","ast_delayed_import","lazy_export_owner"],"ast-only":["ast_eager_import","ast_delayed_import"],"canonical":["ast_eager_import","ast_delayed_import","lazy_export_owner","package_parent"],"eager-ast-only":["ast_eager_import"]},"purpose":"Measure possible runtime module dependencies for architecture review; this is not an eager-import deadlock detector or a domain ownership classifier.","scc":{"algorithm":"Tarjan strongly connected components with nodes and outgoing targets visited in lexical order.","all_singletons":"A one-node component is an SCC in the algorithmic partition.","cycle":"A component is reported as cyclic when it has more than one node, or when its single node has an explicit self-edge.","ordering":"Reported cyclic components sort by descending size and then lexical member list. Members sort lexically.","self_loop":"A singleton with an explicit self-edge counts as a cyclic SCC.","singleton_without_self_loop":"A singleton without a self-edge does not count as a cycle or a non-trivial SCC."},"scope":{"excluded":"Non-Python files, directories without a .py file of their own, tests, scripts, generated cache files, and dependencies outside gravity_sdk are not nodes.","node":"Every .py file recursively below package_root is one module node.","ordinary_module":"Any other .py file maps to its dotted import name relative to package_root.","package_init":"A package __init__.py is the package module node itself; for example gravity_sdk/agents/__init__.py is gravity_sdk.agents.","package_root":"src/gravity_sdk"}}
```
<!-- MODULE_GRAPH_DEFINITION_V1_END -->
<!-- MODULE_GRAPH_BASELINE_V1_START -->
```json
{"definition_id":"gravity-sdk-runtime-possible-module-dependency-graph.v1","definition_sha256":"8ed98cb1e136461612495d3b0187bae3756f4fbe09cde63a9905e838c8ded95f","edge_kind_counts":{"ast_delayed_import":467,"ast_eager_import":2454,"lazy_export_owner":63,"package_parent":645},"node_count":646,"profiles":{"ast+lazy-exports":{"cyclic_scc_count":3,"cyclic_scc_sha256":"7d07b8d38abd147ddf22e64dcdb7e36e8fe401d0de497a36eeebb2304a7df7dc","cyclic_scc_sizes":[422,3,2],"edge_count":2962,"graph_sha256":"f55bbd1b0741301d6bf784b2d2a823c56821a906bae38a24818630a60a107070","largest_cyclic_scc_size":422,"self_loop_scc_count":0},"ast-only":{"cyclic_scc_count":14,"cyclic_scc_sha256":"bab8dfa24220d255caab25fe06c418dbb8892972ae922fd63c8120b6c0f8b5e2","cyclic_scc_sizes":[41,11,8,3,3,3,2,2,2,2,2,2,2,1],"edge_count":2899,"graph_sha256":"b02f82edfbde187ed6865a42e96c979cd0faa565a0a183c51b9372ce4951e7e5","largest_cyclic_scc_size":41,"self_loop_scc_count":1},"canonical":{"cyclic_scc_count":5,"cyclic_scc_sha256":"b6d6b1abac2764131b0f0bc97ebf71d80cca0cd75d515cc154f29750c8036193","cyclic_scc_sizes":[523,15,3,2,2],"edge_count":3528,"graph_sha256":"18bcf21a0d71b381e765f9d40420bc6cdf5d1e2df16f5e025ac9e92e284af27e","largest_cyclic_scc_size":523,"self_loop_scc_count":0},"eager-ast-only":{"cyclic_scc_count":1,"cyclic_scc_sha256":"afc924028fae98ca426f1d1f6622233562e693d3ee04064bd90569aa4795ec88","cyclic_scc_sizes":[5],"edge_count":2454,"graph_sha256":"be1a53d1b22a318f650f50abf1625fa6bd10a1ffca79e42e7bbbf602b8d729ae","largest_cyclic_scc_size":5,"self_loop_scc_count":0}}}
```
<!-- MODULE_GRAPH_BASELINE_V1_END -->
