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

当前没有由本轮源码证明、但尚未闭合的结构债务。新证据出现时按上述维护规则登记。

### 已关闭结构债务

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
