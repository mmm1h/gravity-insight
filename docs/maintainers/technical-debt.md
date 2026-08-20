# 技术债清单

只登记当前源码或质量门禁能证明、且存在明确退出条件的结构债务。产品缺口、上游无数据、历史事故和一次性工作不放在这里。

每轮只更新受影响条目：满足退出条件就删除正文，并在末尾历史行记一次；完整旧内容见归档快照。

## 当前条目

登记于 2026-08-13，依据 `dev@8fd278e` 的源码与质量门禁审计。

### 1. Material/Promotion 重复实现多平台结果重建

**状态（2026-08-20）**：聚合状态与聚合退出码已下沉；其余同名实现经逐项审计后确认已分叉，
本条收窄到尚未满足无行为变化证明的 row copy 与 primary-error selection 共同骨架。

- **Owner area**：Material Performance / Promotion Performance result contracts。
- **已下沉**：`component_aggregate.py` 直接提供纯结构化的 `aggregate_status`、
  `aggregate_exit_code` 与其单组件 category→exit 读取；Material/Promotion 两边保留自己的 operation、
  字段与文案。`test_gravity_component_aggregate.py` 在提取前对两份旧实现锁定 empty/success/error/partial/
  contract-changed、计数、三类 exit 优先级与 primary error，提取后继续通过。
- **已证实的分叉**：Material page receipt 接受 `size=1..1000`，且非空 `total_pages/total_items`
  可大于观察值；Promotion 固定 `size=10`，且非空 totals 必须等于观察值。`safe_component`/
  `_safe_success` 还分别持有单 operation 对多 operation、Promotion App/window/metrics binding、允许的
  data 字段和返回组件字段；`product_envelope` 的领域字段也不同。它们不再作为“完全等价重复”处理。
- **剩余证据债**：`_safe_rows` 的循环骨架相似，但 Material 使用固定字段集并规范化 key，Promotion
  合并平台字段与请求 metrics 且显式拒绝非字符串 key；现有测试不能证明参数化提取对全部 Mapping
  边界逐字段等价。`_primary_error` 的选择/复制骨架相似，但缺失 error 时必须调用各自
  `contract_component`，operation identity 与错误文案不同；现有测试也不足以证明进一步拆分不会改变
  malformed 输入行为。因此两者暂留各自 owner，本条不关闭。
- **触发条件**：任一产品再次修改标量 row copy 或 primary error selection；或出现第三个采用相同
  组件聚合结构的多平台产品。page receipt 已确认是领域差异，修改一边不再单独触发本条。
- **退出条件**：仅当 characterization 能覆盖两边全部 Mapping/key/scalar 或 malformed-error 边界时，
  再把被证明等价的**一个**窄结构操作下沉；字段 allowlist、operation identity 与 fallback 文案必须继续
  留在各自 owner。若不能在不引入 mode/callback 策略的前提下直接调用，则保留分叉实现。
  **不做整文件统一，不造结果 DSL。**

### 2. legacy promotion snapshot 的兼容分支仍缺正式绑定

**状态（2026-08-20）**：正式范围已经收口；非 primary 层级与四个异构平台的兼容读取仍保留本条。

- **Owner area**：Promotion 兼容面（CLI/SDK legacy snapshot）。
- **证据**：`promotion_snapshot_compat.py` 已按输入分流：`primary` 加正式 21 平台复用
  `promotion performance` 的 workspace App、统一日期窗、平台/指标与结果绑定；其他已登记层级及
  `bing/xiaohongshu/taptap/wechat_video` 仍从 stable inventory 精确匹配后透传逐 operation raw input，
  返回 `gravity-insight.composite.promotion.v1`。兼容 envelope 以
  `compatibility.formal_binding_validation=not_performed` 机器标记较低保证；零匹配仍为 unavailable，
  多匹配显式列出候选并在执行前失败，不再选择排序首项。CLI 不适用 shortcut 仍显式失败。
  `query_fields` 到达 operation 后仍经过公共 `FieldPolicy`，剩余差距不是绕过该公共校验，而是没有
  正式产品统一的 App/日期/指标必填约束和返回结果绑定。
- **为什么保留**：基线确实能通过这些 inventory 路径读取；没有消费者遥测能证明无人使用，删除会
  造成能力退化。Agent/Plan 仍只暴露正式产品，不宣传兼容分支为自动化主路径。
- **触发条件**：兼容平台/层级新增第二个同资源 stable read；或对应输入/结果绑定取得正式产品证据；
  或取得可证明无消费者的证据。
- **退出条件**：为所有仍保留的兼容平台/层级建立不损失读取能力的正式请求与结果绑定后移入正式
  路径；或确证无消费者后删除兼容分支。不能用 raw `promotion query` 代替 snapshot 的聚合职责来关债。

### 3. 在线输入解析的两次闭环依赖「上游稳定 ID 不复用」，而这证明不了

- **Owner area**：Agent 输入解析（`agent_input_resolution.py`、`agent_input_catalogs.py`）。
- **证据**：2026-08-15 的裁决把 9 条动线从 `1 / 3` 降到 `1 / 2`，做法是第一次调用同时交付
  能力与完整目录、第二次重新在线解析后执行。该方案的正确性依赖两点：调用方按**稳定 ID** 选择，
  以及第二次执行时重新解析。但**上游没有 revision/ETag**，无法证明它永不复用已删除对象的 ID。
  实现方自己给出了这条反驳，并明确：一旦发现 ID 复用，必须撤销这 9 条的两次闭环判定。
- **触发条件**：观察到任一目录对象的 ID 被复用；或上游开始提供 revision/ETag/版本号。
- **退出条件**：上游提供可校验的版本标识后，把它纳入第二次解析的前置校验，ID 复用即 fail-closed；
  在那之前**不扩大**该模式的适用面——不要把在线输入解析套用到新的动线上来降低调用次数。


### 7. 稳定 operation 的分页形状仍有系统性证据债

- **Owner area**：operation pagination contracts / Evidence。
- **证据**：`f798d39` 的 231 条 operation 中，119 条 `page_info` 拥有完全相同的字段集合，证明该字段集
  来自模板而非逐条验证。2026-08-17 逐 route 对齐生产 response sketch、精确 wire consumer 与合同后，
  审计当时的 119 条只有 `59 A / 1 B / 59 unknown`；证据等级为 `62 production / 8 wire / 49 template-only`。
  2026-08-20 对当前 237 条编译 operation 静态重测：`60 complete / 177 unknown`，证据为
  `97 production / 9 wire / 131 template`，kind 为 `119 page_info / 118 none`。其中 228 条 stable 为
  `60 complete / 168 unknown`，证据为 `97 production / 7 wire / 124 template`；119 条 `page_info`
  全量子集为 `60 complete / 59 unknown`；stable 子集实际为 `60 complete / 58 unknown`，其 unknown
  证据为 `2 production / 7 wire / 49 template`。多出的 1 条是 non-executable
  `candidate.material.kuaishou.list`。逐条表与判据见
  `evidence/forensics/20260817_pagination_contract_audit.{json,md}`；当前 kind 由
  `gravity_sdk.pagination_contract_audit.reconcile_pagination_audit` 对账。
- **当前缓解**：operation schema 和 manifest 已把 `completeness` 与 `pagination_evidence` 分开；无证据
  默认 `unknown`，`template` 不能声明 `complete`。原子读取结果、pagination audit、Plan 与 composite
  均传播机器可读完整性；明确要求 `all_pages` 的 Plan 在未知或前缀结果上返回 capability gap，Agent card
  不再允许全集计数声明。已把实测 B 形状的 `report.multidim.query` 改成单响应，不再重复续页；D28
  `report.get.query` 也是实测 B（只有 `page_info.total`）并声明 `none`。缺 `total_page`
  时 `read_all` 默认停在第一页并把完整性标 `unknown`，满页启发式必须 `continue_without_total`。自动完整
  读取风险最高的 Multidim metadata、Material Performance、Business Pulse 三条已实测为 A。三条完整元数据
  `none` 也补到生产观察无 page_info，但单次观察不能证明服务端永不截断。49 条仍声明 `page_info` 但只有
  `template_default` 证据的条目在对账结果里机器可读为 `shape_unproven`。
- **执行计划**：[分页生产证据采集计划](pagination-evidence-plan.md) 把 168 条 stable unknown 逐条分成
  86 条可证伪采集目标和 82 条永久 unknown；可采部分按同一 App 父项复用的最大收益排成 60、26 两批。
  82 条不采项包括 47 条非集合语义和 35 条已有 production 形状但无可用终止/总数信号的 operation。
- **触发条件**：修改任一 unknown operation 的分页、让新的产品依赖其全集，或取得新的 production/wire
  分页字段证据。
- **退出条件**：逐条用同 method+path 的 production response sketch 或直接 wire 字段把 58 条 stable
  `page_info` unknown 归入真实形状并修正合同；对计划中的另外 28 条 stable collection unknown 取得
  可证伪的完整性信号或转入永久 unknown。
  不得用现有合同声明、短页或满页启发式给自己提升证据等级，也不得全量生产探测。

## 已关闭

2026-08-19 以前关闭项已压缩到 [清理前快照](../archive/snapshots/technical-debt-2026-08-19.md)，不在当前清单重复展开。

2026-08-20：Census POST 读词元债已关闭；当前规则只保留安全方法或 exact 静态确认的
`uncovered_read`，其余 POST/未知方法分别为 `unsafe_unknown` / `static_read_candidate`，默认 draft
selector 不再消费它们。

2026-08-20：Agent 有界无 spec 路由集合已改用 `NO_SPEC_PRODUCTS`；`REPORT_PRODUCTS` 作为同对象兼容别名保留。
