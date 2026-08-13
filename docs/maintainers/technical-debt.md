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

### 2. Plan composite 中央入口逼近 file/complexity 阈值

- **Owner area**：Plan composite routing。
- **证据**：`plan_adapters.py` 当前 491 SLOC，距 500 只剩 9 行；`_execute_composite` 50 SLOC/复杂度 14，
  距 15 只剩 1 个决策点。Material、Promotion、Order Split Trace 曾分别使该文件净增 15、16、8 行，
  以当前余量重复前两种接法会立即触发门禁。Order Directory 改用 `plan_order_adapter.py` 家族路由后，
  本轮中央文件 +7/-7、净增长 0。
- **触发条件**：新增或修改 Plan composite 使 `plan_adapters.py` 超过 491 SLOC，或给
  `_execute_composite` 再加产品专用分支。
- **退出条件**：下次开发相邻 Plan 产品时复用或新增窄领域 family router，或顺手把正在修改的相邻既有
  产品收进其领域 router；`plan_adapters.py` 不高于 491 SLOC，中央 validate/execute/project 不再新增
  同一产品的三重知识，公共 Plan schema/request/projection/envelope 保持兼容。
  **不建立全局 adapter registry 或插件机制。**

### 3. Material/Promotion 重复实现多平台结果重建

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

## 明确不登记为债务

以下模式经审计判定为**合理领域边界**，不因文件数量多而登记：25 个 `agent_*.py`、
10 个 `_field_policy_*.py`、21 个 `*_cli.py`。不建议合并它们，不建议把 `*_cli.py` 换成动态命令
注册，不建议增加字段 DSL，不建议统一所有 composite result/error/pagination 模型，
不建议放宽或更新 baseline 来容纳增长。

## 已关闭结构债务

Agent 相邻产品冲突已收口到 `agent_intent_routing.py`：按独立 owner 正向证据强度与 selector 精确度
裁决，多个产品返回 `MULTIPLE_INTENTS`，历史紧邻冲突集中兼容；五个既有 owner 不再持有他产品负向词，
raw exact selector、敏感查询和既有 pairwise 行为保持。

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

Quality profile 已删除与 runtime root 同路径的冗余 CLI 扫描；每个函数 identity 仅产出一次，Markdown
函数/复杂度超额与未修改的 baseline 一致，500/80/15/0 阈值和失败策略保持不变。
