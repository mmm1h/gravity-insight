# 路线图

本页是当前开发的唯一权威排期依据，取代历史上不进版本控制的临时目标文件。
盘点快照：`dev@8fd278e`，2026-08-13。

## 目标

**数据分析的任何工作都能完全脱离引力 Web 平台，只用本仓库完成，并且对 Agent 友好。**

衡量单位是**分析动线**，不是 operation 数量。一条动线闭环 = 已知输入 1 次调用、未知 2 次调用完成，
且 CLI+SDK+Plan+Agent card 四面可达，结果是带 `schema_version` 的 envelope
（空/部分失败/能力缺口可区分），未登记字段 fail-closed。

## 现状

41 条分析动线：**已闭环 21 / 部分闭环 14 / 完全缺失 6**。

`draft` 候选数量不等于排期数量：17 项候选全部归并进下面的动线，不单独排期。
9 条 `export.analysis.*` 已判定结案（见[能力覆盖与缺口](capability-coverage.md)），不再列为缺口。

## 优先级

| 序 | 动线 | 为什么排这里 | 阻塞 |
| --- | --- | --- | --- |
| 1 | **D22 看板页面条件忠实重放** | 已对非空 `data.object.config.filter` fail closed；空条件不受影响，待证明与图表条件冲突规则后才能忠实应用 | 合并冲突语义证据不足 |
| 2 | **D35 归因表现聚合** | 当前只能读归因配置，无法回答归因结果；且是 F40 的前置 | 需先恢复完整请求 body |
| 3 | **D34 非 Bytedance 计划/组/创意下钻** | 跨平台产品多数只到顶层 | 依赖 D33 父链 |
| 4 | **D32 平台专属素材/创意深查** | 除 Bytedance 外普遍缺非空合同证据 | 每平台需最小非空 probe |

完整 41 条动线的逐条判定、依赖链与最小证据要求，见每轮盘点产出；本页只维护排期与约束。

## 并行与串行约束

**共享 spine（S）**：`plan_adapters.py`、`agent_capabilities.py`、`agent_composite.py`、
`agent_handoff.py`、`cli.py`、`__main__.py`。九条已交付产品线**全部**修改过前四个。

- **所有触碰 S 的最终接线必须串行**，由一个集成人顺序合并。领域 core、合同研究、证据取证可任意并行。
- 同一领域的 `compiler` / provenance / coverage 生成物必须串行再生成。
- 已知依赖链：`D22 → D23`、`D29 → D30`、`D27 → D28`、`D33 → D34`、`D35 → F40`。

## 两条曾经贴脸的硬约束（已解除，规则保留）

1. **`plan_adapters.py` 已从 491 降到 456 SLOC**，余量 44 行，`_execute_composite` 不再是该文件
   最大函数。解除方式是把固定来源 composite 下沉到窄领域 family router（照 `plan_order_adapter.py`）。
   **这条路径仍是唯一批准的接法**：新增 Plan composite 走 family router，中央文件净增长 ≤ 0，
   不引入全局 adapter registry 或插件机制。余量变宽不等于可以回去直接加分支。
2. **Agent 意图冲突已收口到 `agent_intent_routing.py`**，五个既有 owner 不再持有他产品负向词。
   新增语义相邻产品的成本**不再随相邻产品数增长**。判据是 selector 精确度 + owner 正向证据基数，
   不枚举产品对；新产品只需声明自己的正向证据。不引入插件、注册表或通用意图 DSL。

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
- 13 张固定 composite 卡的 7 对意图重叠已收口：集中层按现有 owner 的正向证据强度与 selector
  精确度收集产品，命中多个产品即返回 `MULTIPLE_INTENTS`，不再搜索 raw operation。
  该判据不枚举产品对；显式 `and/以及/同时` 子句独立识别，wrapper 引用与历史紧邻冲突仍 fail closed。
- 错误分类已对齐：permission 返回 upstream/3，本地 unsupported/policy/privacy 阻断返回 local/4；
  operation、请求行为和错误 code 均未改变，没有读能力损失。这是有意的破坏性行为变更——
  调用方需更新 exit-code 分支：`3` 表示换账号或申请权限，`4` 表示请求未发出、停止改输入重试。

## 使用成本：参数化程度审计结论

判据是**改一个参数要不要改代码**。20 个真实分析场景实撞（11 次 HTTP，无权限失败与合同漂移）：
零成本 11 / 有成本可接受 4 / 需改代码 5。

**底层参数化总体健康**，不需要通用化改造。日期窗、周月粒度、分组（≤20）、多指标（≤50 步）、
AND/OR 条件、漏斗步数与窗口、留存 `offset`（1–365）、Multidim 常见指标维度都是改参数即可。
留存 D7→D8 零开发，推广平台硬编码是 operation 合同必要绑定，推广指标用开放排除法——
这三处均不计缺陷。

**真实缺口只有一类：字段已在 operation 合同与 FieldPolicy 中登记，compact Spec 却没暴露。**
调用方因此被迫从产品入口掉回手写 raw wire JSON，而该结构不自描述，Agent 无法机械填写。

| kind | 未暴露字段 | 证据强度 |
| --- | --- | --- |
| Event | `custom_query_item_list` | 不足：最小公式样本上游 `semantic_error` |
| Event | `return_hierarchy_list`、`split_event` | 静态：合同 + FieldPolicy + 单测 |
| Retention | `query_item_before_after` | 静态：合同 + FieldPolicy + 单测 |
| Funnel | 嵌套 `window.type=today` | 仅 FieldPolicy 接受 |
| Scatter | 嵌套 `zone_type=dispersed` | 仅 FieldPolicy 接受 |

补齐纪律：**先从生产 artifact 语料取形状**（模板与看板 artifact 是 Web 端产出的必定可用配置），
取不到证据的 fail-closed 不暴露。逐字复用 FieldPolicy 已有结构直接编译，
**不建通用公式 DSL、不接受任意表达式**。新字段必须有默认值且默认行为与现状完全一致。

Funnel、Property、Scatter 顶层无差集；Property 本身没有日期窗，不算丢参。

**已作废的结论**：审计曾把"Event 双窗口"列为头号缺口，该判定基于 `7d5bdb1`，
早于跨期对比合并。`analysis query --compare-start/--compare-end` 已覆盖，
**不要新增 `date_ranges`**——那会造出第二条语义重叠的路径。上游原生 `date_list`
支持双窗口且 1 次请求即可（本轮在线证实），比现有两次查询+本地 delta 省一次请求，
但这是优化不是缺陷，且 operation 硬上限为 2，三期以上只能客户端拼接。

**三处单日限制均为上游已登记合同限制，不是产品阉割**：`analysis.order_detail.list`（订单目录、
拆单追踪父链）与 `analysis.segment.uid_result.list` 都只有单数 `date`。7 天订单目录的正解是
一个 Plan 放 7 个同层节点并发，不是串行启 7 次 CLI；结果按日期节点分开，不混成一个目录。

**detail 元数据成本已核清**：订单产品提交 `d1983c2` 已对精确固定 profile 短路，D27 的
`ba01a3d` 也让变现固定 allowlist 直接本地校验。最小空日两者实测均为 1 POST、0 metadata，
7 个同层订单节点为 7 POST。缓存仅进程内：raw 动态路径两个独立进程各 4 HTTP；同进程连续
两次为 4+2，7 节点为 16（属性目录各 1、分群 7、订单 7）。旧审计的 3 HTTP 与其提交树已有
fast path 矛盾，未保存的精确调用路径无法追溯；raw detail 的动态 fields/conditions/order 仍
必须加载实时 metadata，未登记字段继续 fail closed。

**Multidim 使用成本**：`--start/--end/--time-dim/--metrics/--dimensions/--media/--multi-days`
已覆盖常见变化，无需完整 JSON。仍需手写物理 JSON 的是 `filters[]`、`custom_metrics_list`、
`relate_dims`。**多个扁平 filter 的 AND/OR 组合语义上游未经证明**，产品 schema 无 `filter_logic`；
证明不了就只支持可确定语义的形态，不得假定默认值，更不得为此造通用布尔 DSL。

## 并发

已有 28 条并发路径、7 种模型，底层受业务槽 24、SQL 槽 2、host 令牌桶与 429 cooldown 约束。
17 条可增强候选中收益最大的 Promotion Performance（≤21 平台）、Dashboard Analysis（≤32/64 图表）、
Analysis Context（13 来源）已接入 Plan 全局预算租借。

租借接口把 Plan execution 已占的一槽计入可用 worker，额外容量只做非阻塞 try-acquire；同一 execution
嵌套租借复用已持有容量，退出或异常均归还，因此多个 Plan worker 不会等待额外槽而自锁。adapter
不拥有第二个预算，领域 core 继续复用既有 bounded batch。fake transport 在 Plan 预算 6 下记录到：
Promotion 21 请求峰值 `1→6`、Dashboard 32/64 图表总请求分别 35/67 且图表阶段峰值 `1→6`、
Analysis Context 13 请求峰值 `1→6`；串并行请求 identity 完全相同。21 平台中 3 个失败的结果保持
`partial`，18 个成功/空组件与 3 个逐平台错误/能力缺口均保留，Plan 依赖仍把 partial 视为失败。

**约束**：不要给 adapter 增加独立 worker 默认值或私有预算。所有增强保持上游总请求量 `1x`，只提高
峰值在途数。SQL 硬上限 2 有 4 并发实测失败证据，不提高。分页未知总页、父子依赖链、导出
`create→poll→download`、探测链不并发。fake transport 证明预算与语义，不代表生产 24 并发已完成
soak；真实吞吐、尾延迟和 429 频率仍需在发布流程中做受控长时观察。

## 已批准的隐私投影边界：变现明细（D27）

`analysis.monetization_detail.list` 的 identifier-free 投影已批准，边界如下。
这是产品合同的一部分，不是可调参数。

**永久排除，不得通过任何参数、字段选择或 raw 路径打开：**

| 字段 | 排除理由 |
| --- | --- |
| `user_id`、`event_user_id`、`device_id`、`ClientID` | 直接用户/设备标识 |
| `TraceID` | 可将同一用户的多条变现事件串联，构成间接标识 |
| `device_info` **整个嵌套对象** | 硬标识符已 omit，但 `Phone_Brand`+`Phone_Model`+`OS`+`Rom_version`+`Aspect_Ratio` 组合构成设备指纹，足以重识别 |
| `user$ad_count`、`user$ad_avg_ecpm`、`user$ad_ltv` | 绑定到单个用户的画像指标 |
| `Name`、`WXOpenID` | 已在 `known_omitted_item_keys`，保持排除 |

**批准暴露：** `CreateTime`、`AdEventTime`；`AdPlatform`、`AdvertiserID`、`AdAid`、
`TurboPromotedObjectID`；`event$ad_type`、`event$adn_type`、`event$ad_unit_id`、
`event$ad_through`、`event$ad_source_id`、`event$ad_placement_id`；`event$ecpm`、`samount`；
`re_attribute_info` 中的广告维度字段。

**附加约束：** 不提供按用户维度的筛选或分组——那会绕过投影重新定位个人。
`fields` 动态字段继续 fail-closed，未登记字段默认隐藏。

**D27 已闭环。** 复用原 stable operation，新增固定单日、完整分页、request-bound 的
identifier-free envelope，并通过 CLI/SDK/Plan/Agent card 四面交付；本轮 0 次生产请求，operation
仍为 185。产品请求只有 App、单日与安全边界，固定 fields allowlist；结果逐行和嵌套重建，未知上游
字段默认隐藏，永久排除值不进入 data/total/page/error/receipt。Plan 经窄 Analysis family router 接入，
`plan_adapters.py` 净增长 0。Guard 仅放行无冲突的产品意图，用户/设备筛选或分组、动态字段、跨日、
聚合、导出/写入和 raw-like 请求继续本地报 gap。D28 聚合仍需独立账户绑定与合同证据，本轮未实现。

## Agent 入口表的增长处理

`docs/agent-workflow.md` 的入口表已从 34 行按任务类型压到 17 行，文件由 220 行降到 202 行；
Analysis 编译、报表产品、投放/素材表现、订单、分群、保存分析、看板等同类入口共享一行，
现有直接命令、未知能力路径与 1/2/3 次调用边界全部保留。

**已否决的方案**：拆成独立文档（入口表正是 Agent 最需要的机器可读内容，拆出去要多读一个文件）；
提高上限（门禁本意"入口文档要读得快"是对的，提高等于放弃约束）。

**已落地**：入口表按任务类型分组，同类产品共享一行（例如“跨平台投放/素材表现”同时覆盖
material 与 promotion），后续同族能力扩展现有行，不再按产品逐行增长。

更根本的判断：这张表在**补偿发现机制的不足**。`gravity agent` 本应让调用方知道有哪些产品可用，
路由层现已先裁决多产品再决定是否进入 raw fallback；无法唯一判定时返回明确缺口。

## 明确不做

- 不复刻 Web UI 概念：布局、收藏、拖拽、成员权限管理。`app.project_auth.detail` 与
  `app.user_auth.list` 因此排除，不因取得非空样本而进入分析产品。
- 业务语义属调用方：模块名称、活动 ID、SKU、投放窗口、指标好坏判断都不进本仓库。
- 写操作保持 reservation。
- 证据不足保持 fail-closed：不猜请求合同、不扩大探测找非空样本、不用未批准的用户级标识探测。
