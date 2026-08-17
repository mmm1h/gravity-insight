# 投影边界与隐私

- 日期：2026-08-18
- 任务：存量 `docs/roadmap.md` 按主题归档
- 结论：投影全面放开总裁决、分群成员明细、D27 变现明细隐私边界、Agent 入口表增长与 App 读语义。

正文为原 `docs/roadmap.md` 对应段落的逐字归档，不是新裁决。
文内相对链接按原 `docs/` 根路径理解（本文件在 `docs/roadmap.d/`）。

---

## 投影边界总裁决：全面放开（2026-08-15）

**本节推翻本页此前全部字段级隐藏裁决，是投影边界的唯一权威来源。** 下面三节
（D27 变现明细批准边界、分群成员明细不批准、User Detail 134 字段不批准）**全部作废**，
保留原文只为记录当时的理由和推翻过程。

**判定：上游授权即产品边界。SDK 不再自建第二层访问控制。**

理由是这层门禁在跟产品目标直接冲突。目标写的是"数据分析的任何工作都能完全脱离引力 Web 平台"。
但 Web UI 对同一个已认证账号显示 `analysis.user_detail.list` 的 153 列，SDK 只给 19 列；
分群成员明细在 Web 上点得开，在 SDK 里整条动线被判为不实现。**这不是保护，是能力退化**——
调用方为了拿到这些数据只能退回 Web 平台，目标就没达成。

访问控制在上游：服务端决定这个账号能读什么。SDK 在其之上再叠一层自造的字段门禁，
既不增加任何实际保护（数据本来就对该账号可见），又让本仓库无法替代 Web 平台。

### 具体放开范围

- **`analysis.user_detail.list`**：134 个 `known_omitted` 顶层 key 全部登记并暴露，
  含直接标识符（不可变证据中的实际 key 为 `userdevice_id`，另含 `user$ta_distinct_id`、
  `user$ta_account_id`、`userlogin_id`、
  `useraccount_id`、`userlong_id`）、准标识符（地域/机型/性别/年龄等）、9 个 `bytedanceMid*`
  语义未证实字段，以及既有的 `Name`、`WXOpenID`。
- **`analysis.monetization_detail.list`（D27）**：原永久排除表全部解除——`user_id`、
  `event_user_id`、`device_id`、`ClientID`、`TraceID`、`device_info` 整个嵌套对象、
  `user$ad_count`、`user$ad_avg_ecpm`、`user$ad_ltv`、`Name`、`WXOpenID`。
  **同时移除"不提供按用户维度筛选或分组"的 Guard**——那是纯隐私限制，且按用户分组是真实分析需求。
- **`analysis.segment.user_detail.list`**：从"不批准、保持 reservation"改为**应实现**，
  按闭环判据补齐五面。
- **`export.analysis.*`**：复核后只有 `segment.result.start` 与 `user_event.start` 两条确实消除了
  用户级投影阻塞；旧口径把聚合估算 `origin_event.evaluate` 也计入，属于误分。两条旧文件证据都
  没有证明逻辑列类型，仍不能提升 executable；另 6 条的请求/文件 schema 阻塞不受本裁决影响。
- **实时事件目录**：`client_id`、`request_id`、`request_ip`、`raw_properties` 批准投影。
  该动线的另一半阻塞（item schema 未证实）不受影响。
- **各产品散落的 `known_omitted`**：`advertiser_name`、`advertiser_remark`、`company`、
  `create_user_id/name`、`update_user_id/name`、`operator_id/name`、`tag`、`title_list`、
  `project_list`、`cid`、`delay` 等一律登记并暴露。这些多数是组织内部元数据，本就不该隐藏。

### 仍然保留的（与隐私无关，不挡任何动线）

1. **凭据不进仓库**：`.env.gravity.local` 等继续 gitignore，不进提交、不进文档、不进 issue。
2. **生产响应值不写入 evidence、文档、测试或提交**。合同靠 shape / 字段路径 / 类型 /
   fingerprint 成立，回归测试用合成 fixture，两者都不需要真实值。这条约束的对象是
   **git 历史**，不是 SDK 运行时返回给调用方的内容——后者已全面放开。
3. **未登记字段继续 fail-closed**。这不是隐私机制，是合同漂移检测：上游新增字段时我们要知道。
   **正确的响应是把它登记并暴露，不是把它隐藏。** user_detail 出现第 154 个 key 时仍应
   `contract_changed_additive`。

### 本单元落地结果（2026-08-15）

本单元把裁决落实到 92 个 stable operation，并同步登记 1 个仍不可执行的 draft，共新增
**412 个按 operation 去重的字段登记**：
`analysis.user_detail.list` 143 个，`analysis.monetization_detail.list` 25 个，其余 90 个
stable operation 236 个，`developer.application.list` draft 8 个。按实际投影槽位计是 440 条
新增路径；其中 415 条由 `known_omitted` 原位迁入允许投影，另 25 条是嵌套、opaque JSON 或
标量列表的逐子字段合同：D27 的 14 个 `device_info` 子字段占其中 14 条，旧合同只省略了整个
容器、没有分别登记子字段。draft 仍因请求、分页和运行时路由未证实而不可执行，没有新增产品面。

省略台账可复算为：stable `known_omitted` **791 → -407 → 384**；再加未取得读取权限的
`candidate.material.kuaishou.list` 33 条，运行时 operation 合同合计 **824 → -407 → 417**。
非执行 drafts 是 **193 → -8 → 185**；两者合计 **1017 → -415 → 602**。User Detail 现在有
153 个顶层 `item_keys` 和 14 个 `device_info` 子字段；D27 有 26 个顶层 row fields 和 14 个
`device_info` 子字段。未登记字段的 additive drift 判据未改。

D27 的固定单日 composite 返回完整已登记 row；raw operation 的 `fields`、用户/设备字段条件和
排序继续走 live metadata 正确性校验。Agent 对字段、筛选、分组和排序意图不再报隐私 gap，而是交给
raw operation discovery。仍由 Guard 阻断的是跨日、聚合/报表、导出/写入、raw-like 后缀和相邻产品
拼接；这些边界都不是字段隐私裁决。

### 推翻条件

若本项目范围将来扩展到把数据交付给非授权方（公开 agent、第三方消费者、跨租户共享），
本裁决必须重新评估——那时的边界问题不是"SDK 该不该显示"，而是"交付给谁"，
应在交付层解决，仍然不该退回字段级隐藏。

### `export.analysis.*` 重新裁定（2026-08-15）

**提案：**逐条拆开投影、请求、父依赖和完整文件 schema；只有列集合、逻辑类型、格式、表头及
worksheet 语义都已证实的 create route 才复用现有 `export run` 提升，Plan v1 继续沿用上文已登记的
“设计不适用”。工作底稿位于 ignored `tmp/codex/export-unblock/proposal.md`。

**结论：旧“3 条只差投影”应纠正为 2 条，但本轮提升 executable 为 0。**

| Operation | 精确阻塞 | 投影裁决影响 | 解锁证据提供方 |
| --- | --- | --- | --- |
| `origin_event.evaluate` | 自身估算请求/聚合响应已证实；配对 `origin_event.start` 的成功 create 与文件合同未证实，属于父工作流依赖 | 旧隐私措辞作废，但父依赖未解除 | 上游 API/前端 owner 给出成功 submit 合同，或有合法原始事件导出的租户提供一次值无关 shape |
| `origin_event.start` | 既有最小 POST 为 HTTP 200 / semantic 1004、无 task id；成功请求绑定与完整文件 schema 均缺 | 未解除 | 同上 |
| `monetization_detail.start` | create 曾返回 task id，但任务 FAILED；`field_map`/筛选语义及完整文件 schema 未成立 | 未解除 | 上游 API/前端 owner，或有可成功变现明细导出的租户 |
| `segment.result.start` | create→poll→download、XLSX、单 worksheet、表头 `用户ID` 已观察；唯一数据行的存储/逻辑类型未记录 | 用户级投影阻塞已解除；类型合同仍缺 | 有非空分群的授权租户做一次同形最小导出，记录类型不记录值 |
| `segment_user_detail.start` | create 曾返回 task id 后 FAILED；`field_map`、临时/持久分群父绑定和完整文件 schema 未成立 | 未解除 | 上游 API/前端 owner，或有合法分群明细导出的租户 |
| `stream_event.start` | 请求合同和完整文件 schema 均未证实 | 未解除 | 上游 API/前端 owner先给出精确 payload，随后授权租户最小验证 |
| `user_detail.start` | create 曾返回 task id 后 FAILED；`field_map`/条件绑定和完整文件 schema 未成立 | 未解除 | 上游 API/前端 owner，或有合法用户明细导出的租户 |
| `user_event.start` | create→poll→download、XLSX、单 worksheet、5 个表头已观察；文件为 0 行，五列逻辑类型全部不可观察 | 用户级投影阻塞已解除；类型合同仍缺 | 有非空单用户事件日的授权租户做一次单日导出，记录类型不记录值 |
| `pay_event.start` | create 曾返回 task id 后 FAILED；`field_map`/条件绑定和完整文件 schema 未成立 | 未解除 | 上游 API/前端 owner，或有合法付费事件导出的租户 |

> 本表冻结 2026-08-15 当轮判定。2026-08-16 第二轮已覆盖其中两行：`user_event.start` 完整闭环并
> 可调用；`stream_event.start` 证明前端不产生 server request，改记 `not_applicable`。后续不得按本表
> 的旧 blocker 重复探测，当前状态以本页后文“第二轮纠错与闭环判定”和导出 route catalog 为准。

本轮生产复核总 HTTP **2 次**：`app.list` 最小第一页 GET 1 次、`analysis.segment.list` 最小第一页
GET 1 次，均 HTTP 200；后者明确空，按停止条件未换 App、未翻页、未扩日期窗。create / poll /
download 均为 0，重试为 0，上游新增任务为 0，本地无业务文件残留。投影总闸门已移除
`user_level` 的本地禁出规则，但 route 仍须完整文件 schema 才能 executable；上游授权边界放开不替代
合同漂移检测。

分析动线在本单元当时快照上的状态迁移为 `0 / 0 / 0`：`48 = 32 / 0 / 16` 不变；后续
setting route 去重使最终台账成为 `47 = 32 / 0 / 15`。该合成动线的 9 条均不可执行，故不能标
部分闭环。
## 分群成员明细合同取证（2026-08-15）

**提案：**复用前两趟已经确定的请求、字段来源、历史版本绑定和相邻动线边界；授权重跑因本地脚本
丢失结果而中断的父链：`app.list` 1 次，再逐 App 各 1 次 `analysis.segment.list`，首个非空即停。
目标 route 仍最多 6 次，不重试失败请求、不扩窗、不猜业务值；发现结果每步立即写入 ignored scratch。

**判定：非空 item schema、无分页语义与五面产品均已成立，本动线闭环。**

- 目标是固定只读 `POST /report/api/v3/dataanalysis/segment/user/detail/list/`。必填事实是 App 与
  精确分群，wire 发送 `app_id`、`tmp_segment_id`、`segment_id` 和固定
  `to_update_segment=false`；`segment_version_id` 是可选的精确历史版本绑定。route 没有自然日
  输入，不能把 `analysis.segment.uid_result.list` 的单日聚合日期移植过来。
- 当前 `UserList-DvLxSIf4.js` 与既有 census 一致：目标请求不发送 `fields`、`page` 或
  `page_size`，UI 收到成员行后在本地选列。`fields` 是 SDK 的投影输入，固定 profile 与动态用户
  属性两者都支持；固定项由 operation describe 给出，动态项来自 live
  `analysis.user_property.list` / 本地 metadata，调用方通过 metadata properties/search 发现。
- 父链枚举到 7 个 App，第 1、2 个 `analysis.segment.list` 为空，第 3 个非空后立即停止；
  `tmp/codex/segment-user-detail-3/discovery.json` 在每次请求后追加保存序号、HTTP 状态和父引用。
  该文件被 gitignore，不进入证据、文档或提交。
- 目标 route 共 3 次，均 HTTP 200 非空：页 1 最小请求确认 `data.list` / `data.page_info`；
  页 1 完整行确认 147 个顶层字段、148 条 item shape path；页 2 复验与页 1 envelope/item fingerprint
  完全一致，且响应的 `page/page_size` 不回显请求，确认分页输入被忽略、一次响应即完整结果。
  envelope fingerprint 为 `9758dfcd5988bacade76e88efa536bb6d4fd897a0700f0caf1e36dc50a74849f`，
  item fingerprint 为 `1f2623c0afb67c6d185adeef477dc7894deb4b5349cfc5852fa3a748788f5874`。
- 生产账本总计 7 次（发现 4、目标 3/6）；HTTP 失败、重试、扩窗均为 0，未继续扫描第 4--7 个 App。
  page 2 仅验证合同，不是为追非空翻页。提交的 evidence 只含 shape、类型和 fingerprint，不含值。

语义边界保持互斥：`analysis.segment.list` 是定义目录，`analysis.segment.uid_result.list` 是单日聚合
人数/状态，`analysis segment snapshot` 组合详情、历史和单日聚合；成员明细才回答“有哪些成员、
各自什么属性”。未来 Agent owner 只声明成员/名单/逐人属性正向证据；若同一请求还明确要求规模/占比，
集中 intent router 返回 `MULTIPLE_INTENTS`。Core、CLI `analysis segment members`、SDK
`segment_members()`、Plan `segment_members` 与 Agent `composite:segment_members` 共用
`gravity-insight.segment-members.v1`；Plan 走窄 Analysis Segment family router，`plan_adapters.py`
净增长 0。147 个已证实顶层字段全部登记并按上游授权暴露，未登记字段继续按合同漂移 fail-closed；
凭据键仍递归去除。上游完整响应超过 `max_items` 时只交付有界前缀并发布
`PAGINATION_LIMIT / caller / retryable=false` 的 `ErrorDetail`，退出码由共享分类得到 2。

本分支只把该行从完全缺失改为已闭环，即 **已闭环 +1、完全缺失 -1、总数不变**；总数基线另有
并行分支修正，本单元不改合并前总计。Agent 以仓库外给定问法实测：
`gravity agent "这个分群里都有哪些人"` 与
`gravity agent "list the members of this segment"` 均在第一次离线调用返回唯一正确产品卡。

## 已批准的隐私投影边界：变现明细（D27）

> **已作废（2026-08-15）**，被上方「投影边界总裁决：全面放开」取代。本节原文保留仅作历史记录，
> 其中的"永久排除，不得通过任何参数打开"已不再是产品合同的一部分。

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

### 对照裁决：分群成员明细**不批准**（2026-08-14，已于 2026-08-15 推翻）

> **已作废**，被「投影边界总裁决：全面放开」取代。该动线现判定为**应实现**。
> 本节原文保留，因为它当时的第 1 条理由恰好说明了问题所在：
> "做 identifier-free 投影会把区分它与聚合的那部分恰好剥掉——剥完就不再是这条动线"。
> 这句是对的，结论错了：正确的结论是**不做那个投影**，而不是不做这条动线。

`analysis.segment.user_detail.list` 在 stable 交叉中被列为"值得有产品面"，需要
`ClientID`、`device_info`、`re_attribute_info` 与动态 `fields` 的投影批准。**判定：不批准，
保持 reservation。** 这是与 D27 相对的一面，写在这里是为了让批准边界可读，不必每轮重问。

理由不是字段逐个敏感，而是**这条动线的有用内容本身就是用户级的**：

1. 它回答的是"这个分群里有哪些人、各自什么属性"。做 identifier-free 投影会把
   区分它与聚合的那部分恰好剥掉——剥完就不再是这条动线。D27 不同：变现明细去掉标识后，
   广告位/平台/ecpm 维度仍能回答"变现表现如何"。
2. **聚合需求已经有产品**：`analysis segment snapshot` 返回 `part/percent/total`，
   分群规模与占比已闭环。缺的只有逐人下钻，而那正是不该开的部分。
3. 字段层面也不成立：`ClientID` 是直接标识；`device_info` 整个嵌套对象已由 D27 判定为
   设备指纹；`re_attribute_info` 在 D27 只批准了聚合语境下的广告维度字段，
   逐人语境下含义不同；动态 `fields` 无界。

**与 3 条隐私门禁导出属同一类**：不是工程排期缺口，是范围与安全模型问题。
除非项目范围明确扩展，否则不重开。

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

## App / 变现家族读语义取证（2026-08-14）

本轮先读取 snapshot 对应的 `appManageIndex`、`csj` 和 `tobid` bundle，再做受控 probe。实际生产
业务请求共 **3 次**：`app.project.list` 1 次，HTTP 200 明确空；`app.app_info.get` 2 次，均
HTTP 200 但安全投影未达到 success，结论 `inconclusive`；`app.monetization_app.list` 0 次。
认证令牌原本有效，没有额外 credential exchange、重试、翻页或扩窗。

`app.project.list` 与 `app.monetization_app.list` 的 POST 读取控制流已分别登记为精确 route
confirmation，闸门判据未改。probe receipt 现在把通过闸门后确实产生 HTTP observation 的读取记为
`method_verified=true`；旧 receipt 不改写。已有 `pagination_verified=true` 的同 route 证据可复用，
避免为一次第一页复核重复请求 page 2 和 safe-max。

结论分三类：项目列表在当前账号明确为空，但非空 item schema 未成立；app-info 的调用方 URL 来源和
七字段 schema 已恢复，`error/icon_url/image_data` 保持隐藏，但测试 URL 只产生 error-shaped 结果，
仍缺成功数据；所谓 D28 候选其实是平台应用关联目录，不含日期、广告位或变现指标，不能拿它冒充
聚合。D28 下一步转向 `monetization_report/custom_get` 与 `calc_total` 的真实报表合同，并单独做字段
字段合同审查；该段原先对 D27 字段边界的引用已被本页投影总裁决推翻。

