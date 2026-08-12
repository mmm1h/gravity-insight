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

当前没有经源码和质量门禁证明、且仍未安排退出条件的 Multidim 结构债务。

本轮已把 CLI 路由、Plan adapter、Multidim service 和 Agent 卡分别下沉到领域模块；通用入口只保留
薄路由，direct/Plan 共用 worker 预算，旧 raw 合同继续兼容。后续若这些模块再次触发机器 ratchet，
再以当时的源码证据登记新条目，不保留已经关闭的历史任务。
