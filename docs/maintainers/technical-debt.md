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

| Owner area | 当前证据 | 本轮动作 | 退出条件 |
| --- | --- | --- | --- |
| CLI domain routing | `cli.py` 集中注册和分派多个领域，修改 Multidim 会继续扩大热点 | 把 Multidim parser/dispatch 移入 `multidim_cli.py`，`cli.py` 只保留 hook | CLI 行数净减，旧命令/help/输出保持兼容 |
| Plan composite routing | `plan_adapters.py` 已在质量上限附近，Multidim 校验/执行/投影仍内嵌 | 移入 `plan_multidim_adapter.py`，通用文件只显式路由 | 通用 adapter 行数净减，Plan 预检/绑定/预算由领域模块独立覆盖 |
| Composite domain mixing | `CompositeService` 同时承担 snapshot 与 Multidim metadata/query；节点 worker 未传到 metadata loader | 下沉 Multidim service，保留兼容薄委托 | direct/Plan worker 使用同一预算，`CompositeService` 不再增长 |
| Agent opaque composite | Multidim 卡只显示 `inputs: object` 且 plan request 缺槽位 | 独立 `agent_multidim.py` 输出闭合机器 schema和显式模板 | 明确中英文意图唯一命中，NL 不填业务值 |
