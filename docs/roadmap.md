# 路线图

本页是当前开发的唯一权威排期依据，取代历史上不进版本控制的临时目标文件。
盘点快照：`dev@8fd278e`，2026-08-13。

## 目标

**数据分析的任何工作都能完全脱离引力 Web 平台，只用本仓库完成，并且对 Agent 友好。**

衡量单位是**分析动线**，不是 operation 数量。一条动线闭环 = 已知输入 1 次调用、未知 2 次调用完成，
且 CLI+SDK+Plan+Agent card 四面可达，结果是带 `schema_version` 的 envelope
（空/部分失败/能力缺口可区分），未登记字段 fail-closed。

## 现状

41 条分析动线：**已闭环 20 / 部分闭环 15 / 完全缺失 6**。

`draft` 候选数量不等于排期数量：17 项候选全部归并进下面的动线，不单独排期。
9 条 `export.analysis.*` 已判定结案（见[能力覆盖与缺口](capability-coverage.md)），不再列为缺口。

## 优先级

| 序 | 动线 | 为什么排这里 | 阻塞 |
| --- | --- | --- | --- |
| 1 | **D22 看板页面条件忠实重放** | 已对非空 `data.object.config.filter` fail closed；空条件不受影响，待证明与图表条件冲突规则后才能忠实应用 | 合并冲突语义证据不足 |
| 2 | **D27 无标识变现明细** | 底层 operation 已 stable，wire 无需重探，是最接近工程闭环的一条 | **需要隐私投影批准**（决策项，非工程项） |
| 3 | **D35 归因表现聚合** | 当前只能读归因配置，无法回答归因结果；且是 F40 的前置 | 需先恢复完整请求 body |
| 4 | **D34 非 Bytedance 计划/组/创意下钻** | 跨平台产品多数只到顶层 | 依赖 D33 父链 |
| 5 | **D32 平台专属素材/创意深查** | 除 Bytedance 外普遍缺非空合同证据 | 每平台需最小非空 probe |

完整 41 条动线的逐条判定、依赖链与最小证据要求，见每轮盘点产出；本页只维护排期与约束。

## 并行与串行约束

**共享 spine（S）**：`plan_adapters.py`、`agent_capabilities.py`、`agent_composite.py`、
`agent_handoff.py`、`cli.py`、`__main__.py`。九条已交付产品线**全部**修改过前四个。

- **所有触碰 S 的最终接线必须串行**，由一个集成人顺序合并。领域 core、合同研究、证据取证可任意并行。
- 同一领域的 `compiler` / provenance / coverage 生成物必须串行再生成。
- 已知依赖链：`D22 → D23`、`D29 → D30`、`D27 → D28`、`D33 → D34`、`D35 → F40`。

## 两个已经贴脸的硬约束

1. **`plan_adapters.py` 余量 9 SLOC**（491/500），`_execute_composite` 复杂度 14/15。
   再按 Material/Promotion 的方式直接加分支会当场触发门禁。
   **解法已存在**：照 `plan_order_adapter.py` 做窄领域 family router，中央文件净增长为 0。
   不要为此引入全局 adapter registry 或插件机制。
2. **Agent 意图冲突正在跨 owner 扩散**。Order Directory 接入时回改了 5 个既有产品 recognizer，
   且这些 owner 至今残留其专用排除词。新增语义相邻产品的成本随**相邻产品数**增长。

## 已知能力净损失

`0.2` SQL 收口删除了 `payment-summary`、`first-scene-coverage`、`profile-coverage`、
`event-coverage` 的专用 builder、summarizer、warnings 和映射语义；当前 `custom-sql` 只能投影
声明字段，**不能等价恢复**。本仓库没有等价迁移证据。

`0.3` Multidim 收口经复核**无取数能力净损失**：raw query/total 仍可经
`gravity run report.multidim.*` 执行，损失的只是旧 CLI/Plan 便利性。

破坏性收口允许直接升级，但**必须先确认没有取数能力净损失**，否则就是在削弱产品目标。

## Agent 可用性欠账

- "未知 2 次"的承诺在 8 条路径上不成立（引用未知、物理指标未知、metadata 未同步、App 未知等
  实际需要 3 次）。要么补齐路径，要么在卡上显式声明调用次数下界与输入来源。
- 13 张固定 composite 卡中有 7 对存在意图重叠，已复现真实误路由：
  `gravity agent "多维报表和经营脉搏"` 返回无关 operation 而非两个产品或明确的多意图缺口。
- 错误分类文档与实现不一致：文档称 permission 为 exit 3，实现返回 caller/2。

## 并发

已有 28 条并发路径、7 种模型，底层受业务槽 24、SQL 槽 2、host 令牌桶与 429 cooldown 约束。
17 条可增强候选中收益最大的是 Promotion Performance（≤21 平台）、Dashboard Analysis（≤32/64 图表）、
Analysis Context（13 来源）。

**约束**：向 Plan 现有全局预算租借，**不要把 adapter 的 worker 从 1 改成 6**——那会与全局池
形成嵌套并发乘法。所有增强保持上游总请求量 `1x`，只提高峰值在途数。SQL 硬上限 2 有 4 并发
实测失败证据，不提高。分页未知总页、父子依赖链、导出 `create→poll→download`、探测链不并发。

## 明确不做

- 不复刻 Web UI 概念：布局、收藏、拖拽、成员权限管理。`app.project_auth.detail` 与
  `app.user_auth.list` 因此排除，不因取得非空样本而进入分析产品。
- 业务语义属调用方：模块名称、活动 ID、SKU、投放窗口、指标好坏判断都不进本仓库。
- 写操作保持 reservation。
- 证据不足保持 fail-closed：不猜请求合同、不扩大探测找非空样本、不用未批准的用户级标识探测。
