# 授权写面普查与分析能力排期

> 基线：`dev@9db7f81` / `codex/write-census`，2026-08-16。本文只做离线 Census、合同与产品面审计；生产 HTTP **0 次**，未实现 operation，也未改生产代码。

## 结论先行

当前写面不能用“路径里像写动词”直接计数。可复算结论是：

1. 冻结 Web-entry `routes.json` 有 **987** 个唯一 `(method, path)`；它不是平台总路由。当前 operation 为 **226 = 194 read + 32 mutation**。其中 stable **217 = 185 read + 32 mutation**，另有 9 个 experimental read。
2. 只按该 Census 的动作词元分类，在精确扣除 226 个 operation 后得到 **334** 条疑似写，不是约 434。这个口径仍只是启发式。
3. 在该 snapshot 内，更可靠的口径是已复核并生成 blocked-write reservation 的路由：旧 `coverage.json` 有 407 条；再扣除后来已经稳定覆盖的 25 个精确 route，得到 **382 条 snapshot 内当前未覆盖写路由**，恰好对应 382 份 reservation。
4. 这 382 份 reservation 中，明确只读的推广/素材/资产/归因占 226 条，但产品方又明确授权“分群 / 人群包”，所以必须从这 226 条中保留 18 条 audience/directional/custom-audience 例外。最终划掉只读 **208** 条、维度表 **9** 条、仓库明确不做的看板收藏/成员权限 **9** 条，以及不属于给定分析对象 CRUD 的后台配置 **114** 条。
5. 严格落在授权对象内、且已被该 snapshot 观察到的物理写路由是 **42 条**；能明确回答“不做会在哪一步回 Web”的只有 **9 条**。此外还有 **3 个不增加该 snapshot route 数的产品能力洞**：编辑“我的报表”、编辑自己的 v3 报表模板、平台 SQL 工作台对象面。snapshot 外还有多少未知。

最该先做的不是把 42 条逐个提升，而是 `report_config/update` 的保存分析 CRUD。它是一条物理 route，却同时服务事件、漏斗、留存、属性、散点、订单、变现和用户分析；当前仓库能读和重放，但不能保存、修改或删除。

派发基线也已独立复算：32 条 mutation 为分群 6、看板 18、`analysis.from.history.version.create` 1、
自定义指标 2、`report.report.update` 1、订阅 2、报表模板 2；Agent catalog 为
**312 = 226 raw operation + 77 product card + 9 gap**；动线台账为 **53 = 45 闭环 + 1 部分 + 7 缺失**。

## 一、口径与粗算偏差

### 1.1 三个不能混用的数字

| 口径 | 数量 | 含义 | 能否直接排期 |
| --- | ---: | --- | --- |
| 当前 operation 精确对账后，按 `coverage.classify_semantics` 动作词元猜写 | 334 | 路径或 HTTP method 看起来像 mutation；auth/export 先于写分类 | 否，只能找候选 |
| 旧 Census 已复核写面 | 407 | `coverage.json` 当时生成 reservation 的写 route | 否，包含后来已覆盖 route |
| Snapshot 内当前未覆盖、已有 reservation 的写面 | **382** | 407 减当前精确覆盖的 25 个 route；与 382 份 reservation 一一对应 | 可作为该冻结集合的物理写面母集，不是平台母集 |
| Snapshot 内产品授权且属于仓库分析对象的写面 | **42** | 再应用产品授权、仓库边界与人群包例外 | 是，但仍须按回 Web 卡点排序 |
| 有明确回 Web 卡点 | **9** | 42 中能回答“不做卡在哪一步”的 route | 是，进入 P0/P1/P2 |

用户粗算无法在当前树上复现。尤其不能用无边界 substring：例如 `asset` 自带 `set`，会把整个资产族误判为写；也不能把 POST 自动当写，仓库已有大量 POST read。本文使用当前仓库自己的动作边界规则，并以 reservation 的逐 route 决议作为更强证据。

382 条的顶层分布为：`turbo_engine 341 / account_center 21 / openapi 7 / open_api 5 / report 5 / apprank 2 / event_center 1`。`turbo_engine` 的大族为：

| 第 4 段 | 未覆盖写 route |
| --- | ---: |
| `user` | 70 |
| `bytedance` | 49 |
| `task` | 30 |
| `asset` | 30 |
| `datamanageconfig` | 20 |
| `tencent` | 18 |
| `kuaishou` | 14 |
| `event` | 13 |
| `oppo` | 11 |
| `monetization` | 9 |
| `event_dim` | 9 |
| 其余 | 109 |

`user` 并不等于“用户分析”：70 条主要是 App 管理、归因回溯、测试设备、推广链接和账号配置。`monetization` 9 条是变现平台账号/App 接入配置，也不是“变现细查”的分析定义 CRUD。按前缀映射授权模块会把这两族全部算错。

### 1.2 划掉之后的归属

| 归属 | route 数 | 裁决 |
| --- | ---: | --- |
| 推广/素材/资产/归因只读 | 208 | 不做写；已从四域 226 条中保留 18 条“人群包”显式例外 |
| `event_dim` | 9 | hold；本租户没有可用维度表 |
| 看板收藏、默认收藏、space/dashboard 成员分享 | 9 | 仓库边界明确不做 favourites 与成员权限管理 |
| 账号/App/开发者应用/归因配置/变现接入/管理员预置等 | 114 | 不在给定分析对象 CRUD 授权内 |
| 严格授权写面 | **42** | 进入下一节；不是 42 个都值得实现 |
| Snapshot 内合计 | **382** | 与 reservation 数一致；范围外未知 |

## 二、按授权模块归类的写面缺口

| 授权模块 | 未覆盖写路由数 | 其中值得做的 | 为什么 |
| --- | ---: | ---: | --- |
| 分群 / 人群包 | 18 | 0 | 路由是媒体 audience/directional package 的创建、同步、推送、去重和删除。它们属于分析后的激活，不产出分析结论；当前没有一条仓库内分析动线因此必须回 Web |
| 事件 / 属性元数据治理 | 15 | 4 | `event_info/batch_create`、事件/用户虚拟属性、用户属性导入能直接补出随后查询所需字段；其余分组、模板、显隐和批量清理主要改善治理体验 |
| 分析模块：模板中心 | 5 | 2 | `template/create` 实际承载 create/edit/delete，`template/use` 把模板变成可运行对象；主题、内部发布、分享不是完成个人分析的必要步骤 |
| 分析模块：保存分析 | 1 | 1 | `report_config/update` 承载八类分析的保存、编辑和删除；当前只有 list/get/replay |
| 分析模块：查询生命周期 | 1 | 1 | `kill_query` 让长查询可取消，避免只能回 Web 终止；它改善恢复，不新增结果能力 |
| 分群临时桥接 | 1 | 0 | `to_tmp_segment/create` 未证明是现有 `create-from-analysis` / `create-from-tmp` 闭环所必需的步骤 |
| 多维报表：报表订阅 | 1 | 1 | `subscribe/edit` 修改已有订阅；当前只能创建或删除，修改时须删后重建 |
| **合计** | **42** | **9** | 物理 route 数不是工作项数；保存分析一条 route 的价值高于 18 条人群包 route |

还有三个不能塞进上表 route 数的能力洞：

- `report.report.update` 已是 stable route，合同字段也能表达带 `id` 的更新，但产品面只交付 create/delete；“编辑我的报表”缺 SDK/CLI/Agent 生命周期。
- `report.template.update` 的同一路由 `/conftemplate/template/edit/` 已用于 `is_deleted=1` 删除；删除并不缺，缺的是 owner 校验后的 rename/config update。
- 当前入口把平台 SQL 工作台列为 `/analysis/bi`，但该叶路由没有 component/import，哈希匹配的
  375 个 JS 中也没有 custom-SQL 实现路径；因此缺口不能表示为已知 route 数，范围外实现未知。

## 三、逐族：不做会卡在哪一步

### 3.1 保存分析：P0，补一条闭环

**场景。** 分析师完成事件、漏斗、留存、属性、散点、订单、变现或用户分析，希望把定义保存为可复用对象，之后按新日期重放或交给同事。

**回 Web 卡点。** `完成一次 Analysis → 保存/更新定义`。仓库当前 `analysis.report_config.list/get` 能列出和读取定义，`composite:saved_analysis` 能重放，但没有写入口；分析师只能在 Web 点击“保存”。删除旧定义也一样。

**闭环还是顺手。** 是新闭环。它新增“完成分析 → 持久化 → 再次重放”，不是让已有 replay 少一个参数。

静态证据很完整：`report_config/update` 有 10 个调用点，来自 Event/Funnel/Retention/Property/Scatter/Order/Cash/User 页面；body 观察到 `app_id/config/id/is_deleted/name/remark/subject`，subject 默认值覆盖 `analysis_cash/event/funnel/order/retention/scatter/user/user_property`。读合同也已有 owner 字段与 detail config，适合复用现有 owner gate、marker、preimage 和 readback。

当前能确定 create/edit/delete；**不能从 Census 证明保存分析自身可以 share**。分享 route 出现在下面的模板族，不能把它偷换成 saved-analysis share。

### 3.2 分析模板中心：P1，核心 CRUD 可补闭环，其他只是顺手

**场景。** 把一套事件/属性/留存等分析配置保存为团队模板，或者从模板直接生成分析/看板对象。

**回 Web 卡点。** `已验证分析配置 → 保存为模板` 使用 `/datamanageconfig/template/create/`；`选择模板 → 落成可运行对象` 使用 `/template/use/`。缺任一核心步骤都要回 Web。

**闭环还是顺手。** `create + use` 能闭合“定义模板 → 复用模板”。`subject/create`、`change_internal`、`template_share/create` 是分类、内部发布和分享，主要让既有模板动线更顺手，并受 P1-4 的读写效果隔离约束。

`template/create` 的静态 body 同时有 `id` 与 `is_deleted=1`，所以这里不是再寻找三条 create/update/delete route，而是为同一路由建立三个受治理动作和 owner/readback。

### 3.3 事件 / 属性元数据治理：P1/P2，按能否解锁查询拆开

**场景。** 新事件或用户属性尚不存在，需要创建/导入；现有物理字段不够，需要事件或用户虚拟属性，随后才能用于分析的 group/filter/metric。

**回 Web 卡点。** `发现查询缺字段 → 创建/导入元数据 → 回到 Analysis 查询` 的中间一步。目前 search/list 只能告诉分析师缺什么，不能补上对象。

**闭环还是顺手。** 首批 4 条（事件批量创建、两类虚拟属性、用户属性导入）能补“元数据 onboarding → 查询”的闭环。属性分组、模板 append/delete、显隐和批量清理不会新增可查询信息，放 P2 或不做。

这里明确排除 `report_metrics/create`：已有路线图静态控制流证明它是角色级报表指标权限配置，不是自定义指标 create。自定义指标核心 CRUD 已在当前基线闭环。

### 3.4 报表订阅 update：P1，让现有动线更顺手

**场景。** 修改自己订阅的频率、启停状态、内容或列，而不是删除并重新创建。

**回 Web 卡点。** 当前仓库只有 create/delete；如果不能接受“删后重建”造成的对象 ID 和投递状态变化，就必须打开 Web 编辑。

**闭环还是顺手。** 主要是已有订阅 CRUD 的完整性和顺手性，不新增“订阅报表”任务终点。`subscribe/test` 会真实发送通知，不属于 CRUD，也不是验收所需，继续不做。

### 3.5 我的报表 / 报表模板 edit：P1，不是新 route

**场景。** 修改自己的报表名称、备注、config 或模板内容。

**回 Web 卡点。** `读取自己的对象 → 修改 → 保存`。现在 report product 只提供 create/delete；v3 template 的 `edit` route 也只登记了删除输入。

**闭环还是顺手。** 对“CRUD”是缺边，但分析师可删后重建，所以更接近已有动线的安全更新能力。必须先做完整 preimage、owner 与等价 readback，不能因 route 已 stable 就直接开放任意字段。

特别澄清：**报表模板 delete 已经做到**。`report.template.update` 固定 `is_deleted=1`，`delete_subscription_report()` 会在 owner/marker list readback 后调用它并确认对象消失。缺的是 edit，不是 delete。

### 3.6 查询取消：P2，只改善恢复

**场景。** 一个分析请求长时间运行或用户发现条件错误，希望取消计算。

**回 Web 卡点。** `提交查询 → 等待中决定取消`。仓库没有 cancel surface，只能等本地超时；Web 有 `kill_query`。

**闭环还是顺手。** 只让已有分析更可恢复，不新增分析结果。实现必须绑定仓库自己发起且仍在运行的 query ID，不能成为任意 query kill 工具。

### 3.7 分群临时桥接：不做，答不上必要 Web 步骤

`to_tmp_segment/create` 已有明确 mutation route，但当前“从分析结果或规则创建并管理可复用分群”已经闭环，且已有 `create-from-analysis`、`create-from-history`、`create-from-tmp`。没有证据证明调用方必须先执行这个额外暂存 route；答不上“缺它在哪一步一定回 Web”，因此不排期。

### 3.8 人群包：授权了，但当前不该做

18 条 route 覆盖各媒体 audience/directional package 的 create/edit/delete/sync/push/distinct。

**分析场景。** 当前只能描述为“把已完成的分群推送到媒体用于投放”。

**回 Web 卡点。** 它发生在分析完成后的 activation，不是取得、验证或保存分析结论的一步。

**闭环还是顺手。** 对本仓库的分析动线都不是。产品方授权只说明允许做，不说明值得由 standalone Gravity SDK 做；在出现一个明确的“分析结果必须以人群包为任务终点”的调用方旅程前，保持 reservation。

### 3.9 `user`、`monetization`、`conftemplate` 不能按路径名推断

- `user` 70 条主要是 App/账号、归因回溯、测试设备和推广链接；没有独立“用户分析 CRUD”族。用户/用户属性分析的保存写入已经汇聚到 `report_config/update`。
- `monetization` 9 条是 CSJ/ToBid 账号与平台 App 接入配置，不是 `analysis.monetization_detail`；缺它们不会卡在变现细查查询中。
- v2 `analysis.template.*` 是分析/看板模板中心；v3 `conftemplate` 是多维报表中心。两者都叫模板，但对象、读目录和写生命周期不同，不能合并合同。
- v3 剩余 `admin/preset_template/*` 是管理员预置模板，产品授权又明确“只能改自己的”；`share_template/edit` 与 `template/share_edit` 是共享/权限辅助，不纳入自己的模板 CRUD。

## 四、SQL 工作台：本地 SQL product 不是平台工作台对象面

能确定的结论是：**不是同一个产品 surface**；底层是否最终共用某个执行服务，当前证据不足。

| 证据 | 本地 workspace SQL product | 冻结 Web-entry Census 内观察 |
| --- | --- | --- |
| endpoint | `https://api-insight.gravity-engine.com/custom_sql/api/sql/execute` | 唯一含 SQL 的 route 是 `/report/api/v3/dataanalysis/query_sql/` |
| 输入对象 | `[products.<name>] kind="custom-sql"`，只允许已登记 SQL、App、日期、limit、投影和禁止结论 | `analysis.event.query` 的结构化 event body；合同明确“不是自由 SQL” |
| 持久对象 | 仓库/调用项目里的 `gravity.toml` product | 当前快照没有平台 saved query / history / share route |
| 能力 | 执行受治理、调用方登记的只读聚合产品 | 当前只能证明 Analysis 结构化聚合 |

因此平台“SQL 工作台”若存在以下对象，仓库都还没有：

- 工作台查询/脚本目录与详情；
- 保存、重命名、删除查询；
- 查询历史；
- 分享/复制查询（是否属于授权范围还需产品确认）。

精确 method/path、owner 字段、请求和响应 schema **不确定**。当前 snapshot 已完整抓取该入口可静态发现的
同源 JS 图，但这个图只是平台子集。入口中的 SQL 菜单/路由是唯一没有 component/import 的叶路由，
所以不是“未点击懒加载页”；375 个 JS 也没有 `/custom_sql/` 或 `sql/execute`。这仍不能证明平台没有
功能，也不能证明它和 `/custom_sql/api/sql/execute` 共用或不共用 backend。没有已知目标 route 时，
生产探测也无法给出安全、可证伪的答案，所以本轮没有使用请求预算。完整复核见
[Census 完整性与分母审计](census-completeness-audit.md)。

## 五、与 `borrow-roadmap` 对齐的排期

### P0：现在做

| 插入位置 | 项目 | 量级 | 为什么排这里 | 可证伪验收 |
| --- | --- | --- | --- | --- |
| **排在现有 P0-1 前** | 保存分析 create/update/delete | L | 一条 route 直接补“做完分析却存不下来”的闭环，覆盖八个 subject；价值比目录顺手性更直接 | 受支持的 event/funnel/retention/property/scatter 各能 preview→execute→list/get→按新日期 replay；update 后只改变审阅字段；owner 不符/缺失在 0 次写请求下拒绝；delete 后完整列表确认消失 |
| **P0 证据线，与上项并行** | 找到平台 SQL 工作台的真实 surface | M | 当前入口只含无 component 的菜单/路由占位，没有可实现 route；先把“不知道接口”变成可排工作 | 从正确租户/角色/入口或运行时证据得到保存查询、目录/detail、历史及可选分享的 method/path、request shape、owner 字段与调用控制流；若该租户/版本没有此功能，也必须以多入口证据明确否证，不能以当前 routes 零命中冒充 |
| 保留现有 P0-1 | 目录优先宿主选路 | M | 仍影响所有自然语言旅程，但它解决“能力存在却选错”，不是新能力 | 沿用原冻结开发集/受保护门槛；本线不读取受保护 split |
| **重写现有 P0-3 的前置条件** | 受治理语义组合层 | XL | 价值未被推翻，但不能再写成“等维度表 CRUD、SQL 工作台、自定义指标三项都完成”：维度表已 hold，自定义指标已完成，SQL 工作台在当前 snapshot 中尚无实现 route | 先冻结不依赖维度表的 3 个组合样例；只有 SQL/metadata 的真实输入面成立后才实现编译器，未知成员与禁止 join 保持 0 请求失败 |

现有 P0-2“上游 owner 替代 marker”已经由三域 owner gate 交付，不再是未来排期；新 mutation 直接复用它并逐族验证。

### P1：下一批

| 项目 | 量级 | 依赖 | 可证伪验收 |
| --- | --- | --- | --- |
| 编辑我的报表、自己的 v3 报表模板、报表订阅 | M | 现有 owner gate；自然语言自动衔接写仍依赖 P1-4 | 三族分别覆盖 owner 自有无 marker 可更新、foreign/shared 拒绝、preimage 与 readback 等价；订阅 test 调用恒为 0 |
| 分析模板中心的 create/update/delete/use | L | saved-analysis config 校验可复用；分享延后到 P1-4 后 | 至少 event/funnel/retention 三类从定义创建模板、按 owner 更新、use 后得到可运行对象并重放、最后安全删除；unsupported config 在写前拒绝 |
| 元数据治理首批 4 条 | L | 现有 metadata catalog；不依赖 `event_dim` | 为一个安全测试对象完成事件创建、事件/用户虚拟属性和用户属性导入中的适用子集，随后真实 Analysis 能引用新字段；清理后目录零残留；拿不到安全样本的子族保持 gap |
| 平台 SQL 工作台最小 CRUD（条件项） | L—XL | P0 SQL surface 取证通过；owner 与只读执行合同成立 | owner 自有 query 可 create/list/get/update/delete；history 只读可分页；共享若 owner 语义不明则明确不交付；不得把自由 SQL 结果升级为受治理业务结论 |

现有 P1-1 至 P1-5 均保留原相对顺序；其中 P1-4 是任何“模型读结果后自动建议/衔接写”的安全前置。保存分析与模板 CRUD 本身仍使用 dry-run + 显式 execute，不等待自动写。

### P2：记着但先不做

| 项目 | 量级 | 升档条件 | 可证伪验收 |
| --- | --- | --- | --- |
| `kill_query` 受控取消 | S | 出现真实长查询恢复阻塞 | 只能取消本进程 receipt 绑定、仍在运行的 query ID；其他 ID 在 0 次写请求下拒绝 |
| 元数据分组/模板/显隐/批量清理 | L | 至少一条分析 onboarding 旅程明确卡在该对象，而不是偏好 UI 整理 | 新对象必须被后续 Analysis 实际消费；只完成后台 CRUD 不验收 |
| 模板主题、内部发布与分享 | M | 有团队复用旅程与明确 recipient/owner 合同，且 P1-4 通过 | foreign/shared 边界可机械区分；分享对象可撤回且不会修改他人模板 |

### 不做

- 18 条媒体人群包 mutation：授权存在，但属于 activation，不是当前仓库分析闭环。
- 9 条看板收藏/成员权限辅助：AGENTS 产品边界明确排除 favourites 和 member permission management。
- `subscribe/test`：真实通知副作用，不是 CRUD 验收所需。
- native AI conversation create/message：已有计划只允许影子评测，不把 Web handoff 重新引入默认链。
- 变现账号/App 接入、App/账号管理、归因回溯、推广/素材/资产写、管理员 preset template、角色级 metric permission：都不能回答“完成数据分析在哪一步必须用它”。
- `to_tmp_segment/create`：现有分群创建闭环没有证据依赖它。

## 六、哪些旧排期被新事实改写

1. **P0-2 已完成，不应继续占未来 P0。** 当前基线已有 principal 与三域 marker-or-owner gate。
2. **P0-3 的依赖叙述被推翻。** 自定义指标 CRUD 已闭环；维度表已 hold；平台 SQL 工作台的 exact surface 仍未知。P0-3 的产品价值仍成立，但实现不能等待一个已搁置对象，也不能假装 SQL 工作台已排到可开发状态。
3. **保存分析 CRUD 应插到现有 P0-1 前。** P0-1 解决“能做但选错”，保存分析解决“做完也存不下来”；后者是一条直接缺失的产品旅程。
4. **报表模板 delete 缺口被否证。** 当前已经安全删除；新增工作应命名为 owner-verified edit，避免重复建设。
5. **“SQL 工作台已在既定排期”过于乐观。** 现在只有本地 governed SQL product 执行机制，平台工作台对象 route 还没有发现，必须先有一条 P0 证据线。

## 七、交回判断题

1. **当前 snapshot 能确认的授权写面缺口多少？** 物理 route **42**，其中 9 条值得做；另有 3 个不表现为新 route 的能力洞。382 条冻结 reservation 母集中：208 只读、9 hold、9 仓库边界排除、114 非授权分析对象、42 授权；平台范围外未知。
2. **答不上“在哪一步回 Web”的族？** 媒体人群包、额外临时分群、看板收藏/成员分享、模板主题/内部发布、元数据分组/显隐/批量清理、native AI、变现接入、App/账号和管理员/角色权限族。后两类甚至不属于给定分析对象授权。
3. **SQL 工作台是否同一个东西？** 不是同一产品 surface。本地是 workspace 登记的 `/custom_sql/api/sql/execute` 只读产品；Census 唯一 `query_sql` 是结构化事件分析。平台 saved/history/share 的 route 与 backend 关系不确定。
4. **保存分析现在能不能做，模板中心是哪族？** 现在能 list/get/replay，不能 create/update/delete。分析/看板模板中心是 v2 `analysis.template.*` / `datamanageconfig/template*`；v3 `conftemplate` 是多维报表中心。保存分析 create/edit/delete 可由 `report_config/update` 静态证明；saved-analysis share 不能证明。
5. **P0 是什么，和旧 P0 谁先？** 保存分析 CRUD 排在 P0-1 前；SQL 工作台 static surface discovery 与之并行。P0-1 保留；P0-2 已完成；P0-3 先改依赖再做。
6. **旧路线是否被推翻？** P0-2 的“未完成”状态、P0-3 的三项依赖、报表模板 delete 缺口、以及“SQL 工作台已经处于可实现排期”均被当前事实改写；P0-1 的价值未被推翻。
7. **授权了但不该做的族？** 有，18 条媒体人群包 mutation。它们是分析后的投放激活，没有当前分析旅程因此回 Web；授权不是价值证明。看板收藏/成员权限也不做，但原因更强：仓库产品边界已明确排除。

## 不确定项与停止条件

- 平台 SQL 工作台的精确 route、对象 schema、owner、history/share 语义及其与 custom-SQL backend 的关系不确定。
- `report_config/update` 能证明保存分析 create/edit/delete，不能证明 saved-analysis share。

## 后续 wire 与产品裁决（2026-08-16）

后续静态调用点和生产最小请求把本普查的 P0 假设收敛为精确合同：同一
`report_config/update` 对 create 省略 `id/is_deleted`，对 update 只增加 `id`，对 delete 增加 `id` 并
固定 `is_deleted=true`；三者均提交 `app_id/subject/name/config/remark`，`config` 为 JSON string。
因此没有 `action` 字段，也不是仅靠 ID 有无区分删除。

生产 93 条目录样本只观察到 event/funnel/retention/scatter/user-property 五类。五类 detail 外层 shape
一致，但 config 的路径数和 fingerprint 分别为 143/`50c36295…`、68/`0def5f2f…`、96/`80fd7c2a…`、
65/`c566f423…`、71/`6d3dc62c…`，明确不同构。实现因此选择“一条物理 operation + 显式 subject”，
调用方动作卡仍按 create/update/delete 分开；产品只开放五个已有严格 compiler 的 subject。
cash/order/user 不是被判定为不该保存，而是租户无样本、config 未证明，保持 fail-closed。

事件类已完成真实 create/list/get/update/readback/query/delete/final-list，最终 marker 为 0；但 query 的
真实聚合数字没有在验收脚本异常前写入 value-free evidence，所以资产动线只记部分闭环。owner 字段
实测为 `create_user_id`，精确等式是 `create_user_id == gravity_id`；单对象 creator 只允许
`creator.id` fallback。list/get 不走 metadata cache，mutation 成功后仍统一清 cache，删除读回使用完整
新列表。请求实际 41/40，超限原因、逐类计数和 receipt 见
[`20260816_saved_analysis_crud.json`](../../evidence/forensics/20260816_saved_analysis_crud.json)；发现后未再请求，
对象已清理。share 仍无证据，未实现；v3 conftemplate 边界不变。
- 模板 `change_internal` 与 share 的 recipient/owner 细节、订阅 edit 的完整 request body 仍不足以直接实现。
- 42 是当前 987-route 快照内的物理 route 数；一个 route 可承载多个动作，Census 也会排除其他入口/
  origin、运行时 URL 和后端-only route。因此 42 不是平台授权写面总数、最终 operation 数或完成度 KPI。
- 本轮没有已知、安全且一次请求即可改变上述裁决的目标 route，故生产 HTTP 使用 **0 / 8**。
