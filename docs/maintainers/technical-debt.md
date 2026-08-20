# 技术债清单

只登记当前源码或质量门禁能证明、且存在明确退出条件的结构债务。产品缺口、上游无数据、历史事故和一次性工作不放在这里。

每轮只更新受影响条目：满足退出条件就删除正文，并在末尾历史行记一次；完整旧内容见归档快照。

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
- **2026-08-20 进展**：Prober 已把隐式允许/拒绝固化为六个互斥机器状态；所有未由精确 stable 合同或
  含 reviewer、ISO 日期、静态证据的逐路由清单确认的 POST 均为 `unsafe_unknown`。该状态在 credential
  status/refresh、session 与 runtime/transport 构造前以稳定机器错误失败；单条、batch、parameter 与
  scoped reprobe 的直接入口复用同一离线前置检查。既有 Census `status` 和逐条语义结论未批量改写。

### 7. 稳定 operation 的分页形状仍有系统性证据债

- **Owner area**：operation pagination contracts / Evidence。
- **证据**：`f798d39` 的 231 条 operation 中，119 条 `page_info` 拥有完全相同的字段集合，证明该字段集
  来自模板而非逐条验证。2026-08-17 逐 route 对齐生产 response sketch、精确 wire consumer 与合同后，
  审计当时的 119 条只有 `59 A / 1 B / 59 unknown`；证据等级为 `62 production / 8 wire / 49 template-only`。
  2026-08-20 对当前 237 条编译 operation 静态重测：`60 complete / 177 unknown`，证据为
  `97 production / 9 wire / 131 template`，kind 为 `119 page_info / 118 none`。其中 228 条 stable 为
  `60 complete / 168 unknown`，证据为 `97 production / 7 wire / 124 template`；119 条 `page_info`
  子集形状为 `60 A / 59 unknown`（B 已移出 `page_info`），完整性为
  `60 complete / 59 unknown`，证据仍为 `62 production / 8 wire / 49 template`。逐条表与判据见
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
- **触发条件**：修改任一 unknown operation 的分页、让新的产品依赖其全集，或取得新的 production/wire
  分页字段证据。
- **退出条件**：逐条用同 method+path 的 production response sketch 或直接 wire 字段把 59 条
  `page_info` unknown 归入真实形状并修正合同；对其余 stable `unknown` 集合取得可证伪的完整性信号。
  不得用现有合同声明、短页或满页启发式给自己提升证据等级，也不得全量生产探测。

## 已关闭

2026-08-19 以前关闭项已压缩到 [清理前快照](../archive/snapshots/technical-debt-2026-08-19.md)，不在当前清单重复展开。
