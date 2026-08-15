# 自然语言可达性 baseline

## 执行口径

- 代码基线：`codex/nl-reachability@df363c4`；该提交只比 `23422c2` 多冻结题单，没有源码变化。
- 输入：`phrasings.md` 的 47 条动线 × 中英各 1 条，共 94 条。
- 执行：每条题目各启动一次 `PYTHONPATH=<worktree>/src python -m gravity_sdk agent <query> --format json`；并发只用于并行启动相互独立的离线进程，每条题目仍是自己的第一次调用。
- 离线性：94/94 为 `offline=true`、`network_called=false`，退出码均为 0；生产 HTTP 请求 0 次。
- 记号：`✓` 表示第一张产品卡就是目标产品；`✗` 表示没有命中目标产品。`generic gap` 是无目标动线 next action 的通用 `capability_gap`，不计达标。候选按返回顺序完整列出。

## 汇总

- 32 条已闭环：**中英都达标 6 / 只有一种语言达标 7 / 中英都不达标 19**。
- 可复算：`6 + 7 + 19 = 32`；按语言计为 `6 × 2 + 7 = 19 / 64` 条问法达标。
- 15 条完全缺失：正确可执行产品 **0**；正确且带可执行 next action 的目标动线 gap **0**。现有 generic gap、错产品、raw operation 和 Analysis task handoff 均不算漏记的已完成工作。

## 32 条已闭环动线逐条结果

| ID | 动线 | 中文首次结果 | English 首次结果 | 判定 | 未达标的实际行为 |
| --- | --- | --- | --- | --- | --- |
| J01 | 事件趋势 | ✗ `success` → 1 `analysis.task.handoff` | ✗ `success` → 1 `analysis.task.handoff` | 不达标 | 两种语言都路由到通用 Analysis handoff。 |
| J02 | 转化漏斗 | ✓ `success` → 1 `analysis.query.spec:funnel` | ✗ `success` → 1 `analysis.task.handoff` | 部分达标 | English 路由到通用 Analysis handoff。 |
| J03 | 用户留存 | ✗ `capability_gap` → generic gap | ✗ `success` → 1 `analysis.task.handoff` | 不达标 | 中文为通用 gap；English 路由到通用 Analysis handoff。 |
| J04 | 属性分布与聚合 | ✗ `success` → 1 `analysis.task.handoff` | ✗ `success` → 1 `analysis.task.handoff` | 不达标 | 两种语言都路由到通用 Analysis handoff。 |
| J05 | 指标散点关系 | ✓ `success` → 1 `analysis.query.spec:scatter` | ✗ `success` → 1 `analysis.task.handoff` | 部分达标 | English 路由到通用 Analysis handoff。 |
| J06 | 同定义跨期比较 | ✗ `success` → 1 `analysis.task.handoff` | ✗ `success` → 1 `analysis.task.handoff` | 不达标 | 两种语言都路由到通用 Analysis handoff，未返回带 period compare 的 Spec 卡。 |
| J07 | 人群规则人数与占比 | ✗ `capability_gap` → generic gap | ✗ `capability_gap` → generic gap | 不达标 | 两种语言均为无目标 next action 的通用 gap。 |
| J08 | 分析构造上下文 | ✗ `success` → 1 `analysis.task.handoff` | ✗ `success` → 1 `analysis.task.handoff` | 不达标 | 两种语言都路由到通用 Analysis handoff。 |
| J09 | App 治理快照 | ✗ `capability_gap` → generic gap | ✗ `capability_gap` → generic gap | 不达标 | 两种语言均为通用 gap。 |
| J10 | App 归因配置快照 | ✗ `capability_gap` → generic gap | ✗ `capability_gap` → generic gap | 不达标 | 两种语言均为通用 gap。 |
| J11 | 单用户画像/事件/回传 | ✗ `capability_gap` → generic gap | ✗ `capability_gap` → generic gap | 不达标 | 两种语言均为通用 gap。 |
| J12 | 多 App 业务趋势与小时脉搏 | ✗ `success` → 1 `analysis.task.handoff` | ✓ `success` → 1 `composite:business_pulse` | 部分达标 | 中文路由到通用 Analysis handoff。 |
| J13 | 公司资源用量趋势 | ✓ `success` → 1 `composite:company_usage` | ✓ `success` → 1 `composite:company_usage` | 达标 | - |
| J14 | 自定义人群覆盖与状态 | ✓ `success` → 1 `composite:custom_audience` | ✗ `capability_gap` → generic gap | 部分达标 | English 为通用 gap。 |
| J15 | 跨平台素材表现 | ✗ `capability_gap` / `MULTIPLE_INTENTS` → [`composite:material_performance`, `composite:promotion_performance`] | ✗ `capability_gap` → Promotion boundary gap | 不达标 | 问法已明确是素材，中文制造伪歧义；English 错路由为推广表现 gap。 |
| J16 | 单日无标识订单目录 | ✗ `capability_gap` → Order Directory boundary gap | ✗ `capability_gap` → Order Directory boundary gap | 不达标 | 产品存在且问法在边界内，却被产品 Guard 拒绝。 |
| J17 | TraceID 单日拆单追踪 | ✗ `capability_gap` → Order Directory boundary gap | ✓ `success` → 1 `composite:order_split_trace` | 部分达标 | 中文错路由到相邻订单目录 Guard。 |
| J18 | 单日无标识变现明细 | ✗ `capability_gap` → Monetization boundary gap | ✗ `capability_gap` → Monetization boundary gap | 不达标 | 两种语言都被误判为边界外；gap 建议改用 selector，不算自然语言命中。 |
| J19 | workspace 聚合 SQL 产品 | ✗ `success` → 1 `analysis.task.handoff` | ✗ `capability_gap` → generic gap | 不达标 | 中文路由到通用 Analysis handoff；English 为通用 gap。 |
| J20 | 看板详情、成员和筛选收藏 | ✓ `success` → 1 `composite:dashboard_snapshot` | ✓ `success` → 1 `composite:dashboard_snapshot` | 达标 | - |
| J21 | 看板图表与页面条件重放 | ✗ `capability_gap` → generic gap | ✗ `capability_gap` / `MULTIPLE_INTENTS` → [`composite:dashboard_snapshot`, `composite:dashboard_analysis`] | 不达标 | 中文为通用 gap；English 已明确 replay，仍制造控制面快照与执行面的伪歧义。 |
| J22 | 保存分析重放 | ✓ `success` → 1 `composite:saved_analysis` | ✓ `success` → 1 `composite:saved_analysis` | 达标 | - |
| J23 | 分析模板重放 | ✓ `success` → 1 `composite:analysis_template` | ✓ `success` → 1 `composite:analysis_template` | 达标 | - |
| J24 | 分群详情、版本与单日聚合 | ✗ `capability_gap` → generic gap | ✗ `capability_gap` → generic gap | 不达标 | 两种语言均为通用 gap。 |
| J25 | 显式物理字段多维报表 | ✗ `success` → 1 `analysis.task.handoff` | ✓ `success` → 1 `composite:multidim` | 部分达标 | 中文路由到通用 Analysis handoff。 |
| J26 | 平台物理指标推广表现 | ✗ `capability_gap` → generic gap | ✗ `capability_gap` → generic gap | 不达标 | 两种语言均为通用 gap。 |
| J27 | B 站账户/产品投放表现 | ✓ `success` → 1 `composite:bilibili_account_performance` | ✓ `success` → 1 `composite:bilibili_account_performance` | 达标 | - |
| J28 | 巨量广告主 profile | ✓ `success` → 1 `composite:advertiser_profile` | ✓ `success` → 1 `composite:advertiser_profile` | 达标 | - |
| J29 | 巨量普通/标准标题包 | ✓ `success` → 1 `composite:title_package` | ✗ `success` → 1 `analysis.task.handoff` | 部分达标 | English 路由到通用 Analysis handoff。 |
| J30 | 离线元数据名称查找 | ✗ `success` → 1 `analysis.task.handoff` | ✗ `capability_gap` → generic gap | 不达标 | 缺 class-level metadata 产品卡；中文错入 Analysis handoff。 |
| J31 | 已同步表版本与变更观察 | ✗ `capability_gap` → generic gap | ✓ `success` → 1 `metadata:table_lineage` | 部分达标 | 中文为通用 gap。 |
| J32 | 素材分析报表导出 | ✗ `success` → 1 `analysis.task.handoff` | ✗ `success` → 1 `analysis.task.handoff` | 不达标 | 两种语言都路由到通用 Analysis handoff。 |

## 15 条完全缺失动线逐条结果

| ID | 动线 | 中文首次结果 | English 首次结果 | 判定 | 实际行为 |
| --- | --- | --- | --- | --- | --- |
| J33 | 分析默认值字典 | ✗ `success` → 1 `analysis.task.handoff` | ✗ `success` → 1 `analysis.task.handoff` | 不达标 | 两种语言都误路由到 Analysis handoff。 |
| J34 | 实时事件目录 | ✗ `success` → 1 `analysis.event.info`, 2 `analysis.event.list`, 3 `analysis.event.query` | ✗ `capability_gap` → generic gap | 不达标 | 中文路由到三个 raw operation；English 为通用 gap。 |
| J35 | 自有/共享/MasterKey 报表目录与定义 | ✗ `capability_gap` → generic gap | ✗ `capability_gap` → generic gap | 不达标 | 两种语言均为通用 gap。 |
| J36 | 报表订阅清单 | ✗ `success` → 1 `analysis.dashboard.detail`, 2 `analysis.report_config.get`, 3 `analysis.report_config.list` | ✗ `capability_gap` → generic gap | 不达标 | 中文路由到三个不相干 raw operation；English 为通用 gap。 |
| J37 | 媒体报表目录 | ✗ `success` → 1 `composite:promotion_performance` | ✗ `capability_gap` → generic gap | 不达标 | 中文错路由到推广表现；English 为通用 gap。 |
| J38 | 当前账号可读 App 项目 | ✗ `capability_gap` → generic gap | ✗ `capability_gap` → generic gap | 不达标 | 两种语言均为通用 gap。 |
| J39 | App OneLink 与公开信息绑定 | ✗ `capability_gap` → generic gap | ✗ `capability_gap` → generic gap | 不达标 | 两种语言均为通用 gap。 |
| J40 | 变现聚合 | ✗ `capability_gap` → generic gap | ✗ `capability_gap` → generic gap | 不达标 | 两种语言均为通用 gap。 |
| J41 | 归因表现聚合 | ✗ `capability_gap` → generic gap | ✗ `capability_gap` → generic gap | 不达标 | 两种语言均为通用 gap。 |
| J42 | 单用户归因明细 | ✗ `success` → 1 `analysis.account_user.list`, 2 `analysis.event_property_value.list`, 3 `analysis.monetization_detail.list` | ✗ `capability_gap` → generic gap | 不达标 | 中文路由到三个 raw operation；English 为通用 gap。 |
| J43 | 数据表当前 schema/字段/版本 | ✗ `capability_gap` → generic gap | ✗ `success` → 1 `metadata:table_lineage` | 不达标 | English 错路由到历史沿革产品；中文为通用 gap。 |
| J44 | 非 Bytedance 平台计划/组/创意表现 | ✗ `capability_gap` → generic gap | ✗ `capability_gap` → Promotion boundary gap | 不达标 | English 被相邻的已闭环跨平台推广产品 Guard 截获。 |
| J45 | 各平台专属素材与创意 | ✗ `capability_gap` → Promotion boundary gap | ✗ `capability_gap` → generic gap | 不达标 | 中文被相邻推广产品 Guard 截获；English 为通用 gap。 |
| J46 | Analysis 结果导出 | ✗ `capability_gap` → generic gap | ✗ `capability_gap` → generic gap | 不达标 | 两种语言均为通用 gap，没有指出 9 条 analysis export 的精确证据动作。 |
| J47 | 精确平台素材预览/下载 | ✗ `capability_gap` → generic gap | ✗ `capability_gap` → generic gap | 不达标 | 两种语言均为通用 gap，没有指出二进制合同/allowlist 的精确证据动作。 |

## baseline 中的 `MULTIPLE_INTENTS` 裁决

本轮 baseline 出现两组 `MULTIPLE_INTENTS`，两组都**不应当**算达标：

1. J15 中文明确要求“素材表现”，`material_performance` 与 `promotion_performance` 的冲突是 recognizer 误报，不是语义歧义。
2. J21 English 明确要求 “Replay the whole dashboard”，`dashboard_analysis` 与 `dashboard_snapshot` 的冲突是控制面词汇侵入执行意图，不是语义歧义。

因此 baseline 没有一条依靠 `MULTIPLE_INTENTS` 达标。
