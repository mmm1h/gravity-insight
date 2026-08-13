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

- **Owner area**：Material Performance / Promotion Performance result contracts。
- **证据**：`material_performance_result.py`(406 SLOC) 与 `promotion_performance_result.py`(489 SLOC)
  各自实现同名同构的 `safe_component`、`_safe_success`、`_safe_rows`、`_safe_page`、page receipt 校验、
  `product_envelope`、`_primary_error`。Promotion 上线后又经 `464b1d4`、`099ad46`、`81d0d02` 修补
  结果边界、request binding 与 Plan rows/output paths——相同不变量存在两份，修补时必须人工检查另一份。
  Promotion 文件距 500 只剩 11 SLOC，`_safe_success` 复杂度 14。
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

### 3. Census 把 214 条 POST 仅凭路径词元判为「未覆盖读」

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

## 明确不登记为债务

以下模式经审计判定为**合理领域边界**，不因文件数量多而登记：25 个 `agent_*.py`、
10 个 `_field_policy_*.py`、21 个 `*_cli.py`。不建议合并它们，不建议把 `*_cli.py` 换成动态命令
注册，不建议增加字段 DSL，不建议统一所有 composite result/error/pagination 模型，
不建议放宽或更新 baseline 来容纳增长。

## 已关闭结构债务

Agent 相邻产品冲突已收口到 `agent_intent_routing.py`：按独立 owner 正向证据强度与 selector 精确度
裁决，多个产品返回 `MULTIPLE_INTENTS`，历史紧邻冲突集中兼容；五个既有 owner 不再持有他产品负向词，
raw exact selector、敏感查询和既有 pairwise 行为保持。

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

多 App Analysis 扇出仅在领域 batch/surface 中把显式 `apps` 展开为现有同层 Plan 节点；没有新增
线程池、worker 默认值、adapter registry、跨 App 结果抽象或共享 spine 分支。机器 quality ratchet
保持，`plan_adapters.py` 未修改；本轮复核未产生新的结构债条目。
