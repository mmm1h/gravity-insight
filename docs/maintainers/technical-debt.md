# 技术债清单
只登记当前源码或质量门禁能证明、且有明确退出条件的结构债务；产品缺口、上游无数据、历史事故和一次性工作不登记。
每轮仅更新受影响条目：满足退出条件即删除正文并在末尾留一行历史，完整旧内容见归档快照。

## 当前条目
登记于 2026-08-13，依据 `dev@8fd278e` 的源码与质量门禁审计。
### 2. legacy promotion snapshot 的兼容分支仍缺正式绑定
**状态（2026-08-25）**：除 `primary` 21 平台外，`bytedance/project`、`honor/ad_group`、`honor/campaign`、
`kuaishou/ad_unit`、`ubix/group` 已复用 Promotion Performance 的 App、日期、平台/指标、分页和结果绑定。逐条重列
发现原记 32 实为 33：漏记的 `ubix/group` 五项条件全满足，已转正；其余 32 个组合的卡点逐条复核后全部仍准确。
- **转正证据**：四项 stable contract 均有必填 `date_list`、App 等值 `filters`、动态 `query_fields`、同构
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
- **静态复核与处置（2026-08-25）**：`reconcile_pagination_audit` 现把 177 unknown 显式分为 86 条
  `collect_production_or_wire`、82 条 `not_scheduled_without_new_signal`、9 条 non-stable。82 条均站得住、0 退回，
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

### 11. `gravity_sdk` 根目录模块扁平化扩大了变更定位范围
- **可测事实**：`src/gravity_sdk/` 平铺 578 个 Python 模块；领域边界主要靠命名而非子包，跨领域定位和审查集中在根目录。
- **影响边界**：不改公开导入或运行时行为；只增加所有权辨识、审查和后续迁移成本。
- **立项（2026-08-25）**：R17 已建，leaf，状态 `specified`。**边界判据不是前缀而是 facade 可达性**：从 `gravity_sdk.agent`
  出发、中间节点仅限 83 个 `agent_*` 候选时最短距离有限者纳入。据此候选 83 → 领域 82 → 一对一迁移 81 + 合并删除 1
  （`agent_pagination`）→ 排除 1。`agent_runtime_contracts` 由判据自动排除（0 条 agent 入边、55 条外部入边、facade
  不可达），留在根目录属 R17 终态；其新归属需另行决策。未采用入边比例阈值，因 `agent_batch`(1:2)、
  `agent_input_resolution`(1:1) 均为合法 Agent 入口——外围消费者数量不能决定 owner。
- **未纳入的更大目标**：跨 plan/analysis/metadata/kanban 执行核心的大环优先级更高，但各方图口径不一致
  （AST-only、含 `_EXPORTS` 字符串边、含 package parent 边分别得出不同 SCC 规模），须先统一图定义再立项。
- **退出条件**：R17 达 `fixed_dev`，根目录 `agent_*.py` 仅剩 `agent_runtime_contracts.py`、根 `.py` 为 496、
  `agents/` 含 81 个实现模块、147 lazy owner 与 148 `__all__` 不变、迁移宇宙 eager SCC 为 0；不得以改名或空目录关闭。

### 13. 8 个公开符号会被同名根模块遮蔽，取值取决于导入顺序
- **可测事实**：147 个 lazy 导出中有 8 个与根模块同名——`analysis_query_batch_schema`、
  `bilibili_account_performance`、`business_pulse`、`company_usage`、`dashboard_snapshot`、`monetization_detail`、
  `order_directory`、`promotion_performance`。`import gravity_sdk.X` 会把子模块对象设为包属性，使 `__getattr__`
  不再触发，于是 `from gravity_sdk import X` 得到模块而非函数。实测 `business_pulse` 直接访问为 function，
  先导入同名子模块后为 module。
- **影响边界**：消费方是 agent，调用会抛 `'module' object is not callable`，且是否触发取决于此前有无其他代码
  导入过该子模块——同一份调用在不同执行路径下行为不同。
- **退出条件**：8 个符号在任意导入顺序下均解析为公开可调用对象，由隔离进程顺序访问测试锁定；不得靠约定
  「不要导入同名子模块」或重命名公开符号规避。

## 已关闭

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
