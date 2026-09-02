# 技术债清单
只登记当前源码或质量门禁能证明、且有明确退出条件的结构债务；产品缺口、上游无数据、历史事故和一次性工作不登记。
每轮仅更新受影响条目：满足退出条件即删除正文并在末尾留一行历史，完整旧内容从 Git 查看。

## 当前条目
登记于 2026-08-13，依据 `dev@8fd278e` 的源码与质量门禁审计。
### 2. legacy promotion snapshot 的兼容分支仍缺正式绑定
**状态（2026-08-28）**：未关闭。stable `(platform, resource, operation)` 唯一三元组实为 **57** 而非 58：正式并集 **25**
（`21 primary ∪ 5`，`ubix/group` 同属两者不可相加），其余 **32** 为兼容；按调用参数路径计则为 26/56。集合冻结在
[`promotion_snapshot_inventory.json`](../../tests/fixtures/promotion_snapshot_inventory.json)，由测试做集合相等校验（非计数）。
- **正式绑定证据**：25 个正式 stable contract 均有必填 `date_list`、App 等值 `filters`、动态 `query_fields`、同构
  `page_info` 和登记行投影；合同漂移 fail-closed。同一 canonical 输入经原 inventory 内核与正式入口产生完全相同的
  operation payload 和原生行，正式结果使用 `gravity-insight.promotion-performance.v1`，不再携带 compatibility marker。
- **primary 卡点**：`bing/advertiser`、`xiaohongshu/advertiser` 无日期/动态指标；`taptap/group`、
  `wechat_video/report` 有 App/日期但无 `query_fields` 与动态指标结果绑定。
- **其余层级卡点**：`bilibili/account` 无动态指标；`bytedance/advertiser_performance` 无 App/动态指标；
  `tencent/tencent_adgroup_v2` 接收 `query_fields` 但结果未登记动态字段；其余 25 个 account/config/parent 层级均
  无必填日期和动态指标（多项亦无 App）。逐条名单见上述冻结 fixture，不在本页重复维护。
- **兼容边界**：上述 32 项仍从 stable inventory 精确匹配后透传 raw input，保持
  `gravity-insight.composite.promotion.v1` 和 `formal_binding_validation=not_performed`；零匹配 unavailable，多匹配或
  不适用 shortcut 执行前失败。`query_fields` 仍过 `FieldPolicy`。57 条均已有请求 schema、响应投影、隐私与分页合同；缺
  日期/动态指标只说明套不进 `promotion-performance` 模型，不妨碍形式化——须等外部证据的只有**删除**分支。Agent/Plan 仍不宣传。
- **触发条件**：兼容平台/层级出现第二个同资源 stable read，取得正式输入/结果绑定，或能证明无消费者。
- **退出条件**：为所有保留兼容平台/层级建立不损失读取能力的正式请求/结果绑定并移入正式路径，或证实无消费者
  后删除；不得以 raw `promotion query` 替代 snapshot 聚合职责。

### 3. 在线输入解析的两次闭环依赖「上游稳定 ID 不复用」，而这证明不了
- **静态复核（2026-08-25）**：风险实际覆盖 5 个引用型 composite 的 6 个目录 operation。按版本词、结构化
  `response_projection` 和 exact operation/evidence 三路复核，没有一个投影具备不复用或单调语义的标识，故不能代替
  revision/ETag token（`analysis.segment.list` 的 `latest_version_calculation_status` 属计算状态，例外但不改结论）。Dashboard/Segment 又无 production/wire
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
- **债务口径**：范围仅为**可采集的 84 条**，非全部 `237-25=212` 条 unknown；84 条 permanent unknown 是机器可验证的能力边界，不计入待关闭债务。
- **证据**：当前 237 条编译 operation 为 `60 complete / 177 unknown`，228 条 stable 为 `60 / 168`，stable
  `page_info` 子集为 `60 / 58`；证据为 `98 production / 9 wire / 130 template`。仅 `template_default` 的 49 条
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
  根本无集合语义；237 条中仅此 1 条通过该谓词）。2026-09-01 对 `analysis.event.query` 的获批 production
  读响应未观察到 `has_more`、`item_count`、`total_items` 或 `page_info`，按计划转入永久 unknown；机器处置现为
  `84 collect / 84 no-new-signal / 9 non-stable`，永久 unknown 为 `47 非集合 + 37 无信号`。完整性总账仍是
  `60 complete / 177 unknown`，不伪装成 complete。
- **计划与触发**：[分页生产证据采集计划](pagination-evidence-plan.md) 精确列出这 84 条（分 58、26 两批，测试按集合相等锁定而非计数）；改 unknown 分页、
  新产品依赖其全集或 exact method+path 取得新 production/wire 字段证据时触发。
- **退出条件**：逐条以同 method+path production sketch/wire 字段把 58 条 stable `page_info` unknown 归入真实形状
  并修正合同；另 26 条 stable collection unknown 须取得可证伪完整性信号或转永久 unknown；不得用合同声明、
  短页、满页启发式提级或全量生产探测。

### 14. 根包仍然扁平，跨执行核心的大环仍未解
- **状态（2026-09-01）**：未关闭，但已建立可失败的边界棘轮。现有引用审计与 `src/gravity_insight/governance/module_graph.py` 共用[模块依赖图 v1](#14-机器图合同)，`quality check` 读取
  `governance/domain-boundary-baseline.json`，锁住 AST-only 最大 SCC 不增、已分类反向边不增，以及根包不得无理由新增模块；四层只按真实子包目录和少量精确 owner 归类，其余明确为 `unclassified`，不从文件名前缀猜。
- **当前证据**：纯词法 `query_match` 已从跨 catalog 的 `find.py` 下沉到 `agents/query_match.py`，旧的
  `gravity_insight.find.query_match` 保持静态再导出；三个 Agent consumer 改依赖 leaf owner 后，AST-only 最大 SCC 从 **41 降到 20**，并非靠移动文件或延迟导入。根包仍为 **501** 个直属模块，其中仅 12 个有当前明确归层，489 个保持未分类；13 条已分类反向边尚未偿还。
- **Agent 包边界**：`gravity_insight.agents` 是 compact Agent interaction 的唯一实现包，`gravity_insight.agent` 是稳定 facade，`agent_runtime_contracts` 保留独立根级合同职责。五条有意保留的 facade 依赖由 bounded module/symbol-set gate 锁定；只有真实职责变化、第二 owner 或 eager cycle 才触发另行批准的拆分。
- **影响**：不改变公开导入或运行行为，但增加定位、归属判断和跨域审查成本。目录治理不得损失调用能力、改变执行 owner 或添加 deep-path shim。
- **退出条件**：按机器图逐个批准有界迁移单元，使根级家族迁入明确 owner 或留下机器可验证的保留理由，偿还 13 条反向边并消除剩余大环；每次必须使 SCC 或违规数真实下降，公开 facade、请求行为和能力保持不变。

### 15. Governor 与 Execution Variant 的当前范围仍是进程内有界实现
- **当前证据**：adaptive state、队列、metrics、single-flight 成功结果和 kill switch 均是进程环境/内存状态，重启会清空；不声明跨进程或分布式协调。固定 Host Rate Limiter 与 bounded requester 继续拥有 pacing、Retry-After、retry 和 auth refresh。
- **选择边界**：只有已登记、已 Characterize 的 event Analysis Direct/Plan variant 可参与；当前 Trust 仍可强制 Direct fallback，延迟或请求成本不能代替 Trust。选择结果不增加第二执行 owner。
- **影响**：调用方不能把观测指标解释为持久 SLO，也不能把未登记 Product 当成自动 variant candidate。
- **退出条件**：为新增候选逐一提供同层语义/完整性/DQ/claims/隐私/请求等价证据和 Journey regression；若需要持久或跨进程调度，先批准新的状态与隔离合同。

## 已关闭

- 2026-08-31：#48 Direct/Plan result-envelope 结构债关闭：稳定产品 surface 由单一机器 registry 生成
  Empty/Partial/Error 六维 parity 矩阵，Plan preflight 离线执行该门禁；递归 completeness 只消费字符串状态，
  producer pagination/source/result audit 与 unknown claims 由 request-bound projector 保留。
- Compact Agent package migration 已关闭；当前 facade/owner 约束保留在公开 API、module disposition 与 wheel 门禁，施工证据由 Git 保存。
- 2026-08-26：#13 公开符号遮蔽债关闭：`gravity_sdk.__init__` 把模块 `__class__` 换装为
  `_ExportAwareModule`，`__getattribute__` 对 8 个碰撞符号每次访问都重查 `_EXPORTS`，
  子模块导入把包属性覆写为 module 时按 `_is_shadowing_module` fail-closed 重新解析而非
  静默返回错误类型；`child-first`/`export-first`/`cross-order` 三种导入顺序均由隔离子进程
  测试锁定，碰撞集合本身有新增探测，未靠改名或「不要导入同名子模块」的约定规避。
- 2026-08-25：#8 Title Package 已从编译合同派生 opaque JSON 字段，复用有界深度、元素和大小投影；未登记和非 opaque 标量规则仍 fail-closed。
- 2026-08-19 以前的关闭项仅保留在 Git 历史中。
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
{"canonical_profile":"canonical","definition_id":"gravity-insight-runtime-possible-module-dependency-graph.v1","dynamic_exports":{"edge":"The package containing the table points to each statically resolved owner module.","modeled_protocol":"_EXPORTS","other_protocols":"__all__, ordinary assignments, __getattr__ bodies, and generic dynamic-import calls do not create string edges.","symbol_multiplicity":"Multiple exported symbols owned by one module produce one edge.","unresolved_values":"Non-literal owners produce no edge and are not guessed."},"edge_direction":"The source module points to the module it may depend on at runtime.","edge_kinds":{"all_or_assignment_reexport":{"included_in_canonical":false,"reason":"__all__ names symbols rather than owner modules, and an assignment does not add a module dependency beyond the expression that produced its value. Inferring owners from names would be guesswork.","rule":"Do not create an edge from __all__ strings or ordinary assignment-based re-exports. Their underlying AST import, when present, remains an edge."},"ast_delayed_import":{"included_in_canonical":true,"reason":"A delayed import does not create an eager import cycle, but calling the function can execute it. The graph measures possible runtime architecture dependencies, so excluding it would hide real coupling.","rule":"Collect the same Import and ImportFrom forms inside function or async-function bodies and mark them as delayed edges."},"ast_eager_import":{"included_in_canonical":true,"reason":"These statements declare direct, statically reproducible runtime dependencies.","resolution":"Import uses the exact imported module when it is a node. ImportFrom uses the resolved module operand; for from . import x, it also uses each named child module that is a node. Star imports point to the resolved module operand. Aliases do not change the target.","rule":"Collect Import and ImportFrom statements outside function and async-function bodies, including class bodies and both potentially executable conditional branches."},"generic_dynamic_import":{"included_in_canonical":false,"reason":"Targets can depend on runtime values. Partially evaluating selected call expressions would create an unstable, incomplete graph; a new governed dynamic table requires a new definition version.","rule":"Do not infer edges from importlib.import_module, __import__, loader APIs, computed strings, or plugin-like registries other than the explicit _EXPORTS rule."},"lazy_export_owner":{"included_in_canonical":true,"reason":"The table is an executable lazy import dispatch contract. Attribute access can import its owner even though no Import AST node names that owner.","rule":"In package __init__.py modules only, collect statically resolvable owner module strings from literal _EXPORTS dictionary values and _EXPORTS[...] assignments. Resolve relative owner strings against that package. Deduplicate symbols that share an owner."},"package_parent":{"included_in_canonical":true,"reason":"Python initializes a package before loading its child module. Keeping this as a separate edge kind makes its large SCC effect visible rather than silently folding it into AST resolution.","rule":"For every non-root module node, add an edge to its immediate dotted parent when that parent is also a node."},"type_checking_import":{"included_in_canonical":false,"reason":"TYPE_CHECKING is false in normal runtime execution, so these are type dependencies rather than possible runtime dependencies.","rule":"Exclude imports in branches proven unreachable at runtime from TYPE_CHECKING or typing.TYPE_CHECKING tests; include the runtime branch of a negated test. Unknown conditions retain both branches."}},"profiles":{"ast+lazy-exports":["ast_eager_import","ast_delayed_import","lazy_export_owner"],"ast-only":["ast_eager_import","ast_delayed_import"],"canonical":["ast_eager_import","ast_delayed_import","lazy_export_owner","package_parent"],"eager-ast-only":["ast_eager_import"]},"purpose":"Measure possible runtime module dependencies for architecture review; this is not an eager-import deadlock detector or a domain ownership classifier.","scc":{"algorithm":"Tarjan strongly connected components with nodes and outgoing targets visited in lexical order.","all_singletons":"A one-node component is an SCC in the algorithmic partition.","cycle":"A component is reported as cyclic when it has more than one node, or when its single node has an explicit self-edge.","ordering":"Reported cyclic components sort by descending size and then lexical member list. Members sort lexically.","self_loop":"A singleton with an explicit self-edge counts as a cyclic SCC.","singleton_without_self_loop":"A singleton without a self-edge does not count as a cycle or a non-trivial SCC."},"scope":{"excluded":"Non-Python files, directories without a .py file of their own, tests, scripts, generated cache files, and dependencies outside gravity_insight are not nodes.","node":"Every .py file recursively below package_root is one module node.","ordinary_module":"Any other .py file maps to its dotted import name relative to package_root.","package_init":"A package __init__.py is the package module node itself; for example gravity_insight/agents/__init__.py is gravity_insight.agents.","package_root":"src/gravity_insight"}}
```
<!-- MODULE_GRAPH_DEFINITION_V1_END -->
<!-- MODULE_GRAPH_BASELINE_V1_START -->
```json
{"definition_id":"gravity-insight-runtime-possible-module-dependency-graph.v1","definition_sha256":"b3e0b2a61cb32c8069acec07315c1c65b94a3506c05133c7878a7a2c967f6326","edge_kind_counts":{"ast_delayed_import":481,"ast_eager_import":2554,"lazy_export_owner":63,"package_parent":682},"node_count":683,"profiles":{"ast+lazy-exports":{"cyclic_scc_count":3,"cyclic_scc_sha256":"ee759a19309b3a830edd4db8e799bc2c8d9eabe421e790ea5c60bdf03e6133ec","cyclic_scc_sizes":[429,3,2],"edge_count":3075,"graph_sha256":"a5872410140ab6de6315d6374626d0ebf0a3ff8927a11a8f3c8d75c7859a57bb","largest_cyclic_scc_size":429,"self_loop_scc_count":0},"ast-only":{"cyclic_scc_count":17,"cyclic_scc_sha256":"5d79303cabf20bea4fa3afd6a9279dd39fc3d80ff53602398ac504168bc95096","cyclic_scc_sizes":[20,17,11,8,6,3,3,3,2,2,2,2,2,2,2,2,1],"edge_count":3012,"graph_sha256":"903e246b36e79e2416ddcd862a9555444ce11ee1c3c02c7cbeb78e4a525f04ce","largest_cyclic_scc_size":20,"self_loop_scc_count":1},"canonical":{"cyclic_scc_count":6,"cyclic_scc_sha256":"d3af3c344c7b6f896ee7528d6c9856e0327c2ff39156785d527890b9e089d8a7","cyclic_scc_sizes":[538,15,8,3,2,2],"edge_count":3676,"graph_sha256":"43a004ebd63c8a292dae2073c500dd562a2c88466f449c568b52d26afd6a529a","largest_cyclic_scc_size":538,"self_loop_scc_count":0},"eager-ast-only":{"cyclic_scc_count":1,"cyclic_scc_sha256":"44030b75772ec96099606525c5adf31176fb58f6d27626721ece46d20ce0f7b0","cyclic_scc_sizes":[5],"edge_count":2554,"graph_sha256":"97535bc2847c9833e00afc2749bed130386adbad75f25a49051c858c7186f11c","largest_cyclic_scc_size":5,"self_loop_scc_count":0}}}
```
<!-- MODULE_GRAPH_BASELINE_V1_END -->
