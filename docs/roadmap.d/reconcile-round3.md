# 投放 / 素材 / 报表看板生产对账

- 日期：2026-08-18
- 任务：#209
- 结论：Bytedance 投放金额的分页、分维求和和时间窗可加性在 iOS 分身 `24502679` 上成立；抖音分身 `29034827` 同窗投放消耗为 0 不是请求写错。素材报表/素材库的 `gravity_material_id` 恒为 0，已按既有格式标不可信。投放 `data.total` 是单行数组，分维审计原先看不见，已补。

## 选了什么、为什么

前两轮打过归因/事件/变现/导出/留存/漏斗/分群。本轮只打还没对过账的投放读、素材和报表/看板产出面。非 Bytedance 投放按既有前提不打。`report.media_report.list` 本轮已有独立空结论，不重复烧预算。

发请求前的预期见 `tmp/reconcile-round3/EXPECTATIONS.md`。摘要：

| ID | 事先预期 | 依据 | 不成立说明什么 |
|---|---|---|---|
| P1/P2/P3 | 走完全部页或末页余数对得上后，item 数 = `page_info.total_number` | 上游声明了总数 | SDK 丢页或 total 撒谎 |
| D1 | 广告主报表 `sum(stat_cost) == data.total[0].stat_cost` | 金额可加，广告主是划分 | 投影丢行或 total 另有口径 |
| D2 | 项目层金额同样可加；与广告主层 total 应相等 | 同一 App 同窗的完整划分 | 层级漏桶 |
| T1 | 大窗 total = 两个互斥子窗之和 | 金额按日可加 | 日期边界或时区错 |
| X1 | 报表 `advertiser_id` ⊆ 账号目录 | 报表行必须对应已授权账户 | 身份对不上 |
| X2 | 同一素材在库与报表里的标识相等 | 同一对象同一标识 | SDK 换了键或投影丢了键 |
| O1/O3 | 已保存报表/订阅 list 与 detail 观察字段一致 | 同一已保存对象 | 目录撒谎 |
| O2 | 看板树节点 id/name/space_id = detail | 同一看板 | 树投影丢字段或 detail 绑错 |

窗：`2026-08-15..2026-08-17`（闭区间，Asia/Shanghai）。今天可能未结账，不用当天。

## 本趟发了什么请求

业务读约 **57** 次（scout / 形状 / App 扫描 / 核心对账 / 交叉验证 / 末页），写 0。另有 1 次本地 `auth status`。元数据预取：`query_fields=["stat_cost"]` 已在广告主合同 `item_keys` 里，未触发 `promotion.metric.list`。未打 analysis query，没有 `event.list` 预取。

优先试了 `29034827`。该 App 在广告主报表上滤出 249 行、`total.stat_cost=0.00`。随后枚举 catalog 7 个 App（各 1 次 `page_size=1`）才定位到有消耗的是 iOS 分身 `24502679`。

## 确凿事实

### 投放消耗绑在哪个 App

`promotion.bytedance.advertiser.list`，窗 `2026-08-15..2026-08-17`，`query_fields=["stat_cost"]`，`page_size=1`：

| `app_id` 过滤 | `page_info.total_number` | `data.total[0].stat_cost` |
|---|---:|---:|
| 无过滤 | 508 | 31612.50 |
| `29034827`（抖音，投放中） | 249 | 0.00 |
| `24502679`（iOS 分身） | 101 | 31612.50 |
| `26827043`（时光合合） | 94 | 0.00 |
| `27018426` / `27192043` / `20698471` / `27612408` | 0 | 空 |

无过滤首页 10 行的 `app_id` 全是 `24502679`，`app_name` 仍是「甜甜旅行」。`filtering={"app_id":"29034827"}` 被忽略，条数仍是 508；有效过滤是 `filters=[{field:app_id,operator:1,values:[int]}]`。

`promotion.bytedance.app.list` 账号级只有 1 行，`app_id=27192043`（Android 分身），不是抖音也不是有消耗的 iOS。

因此：任务前提「投放中、确定有数据」对归因/事件成立，对**投放消耗报表**不成立。抖音分身 249 个广告主全是 0 消耗，不是请求写错——整数/字符串 `app_id`、有无 `filtering` 都试过。

### 分页完整性 — 成立

| 面 | 形状 | 声明总数 | 实测 |
|---|---|---:|---|
| `promotion.bytedance.app.list` | `page_size=7` 全页 | 1 | item=1，`1 % 7 = 1` |
| `promotion.bytedance.advertiser.list` 滤 `24502679` | `page_size=3` 全页 | 101 | item=101，34 页，余 2 |
| `promotion.bytedance.project.list` 滤 `24502679` | `page_size=3` 末页 32 | 94 | 末页 1 行，`94 = 31*3 + 1` |
| `material.report.query` App `29034827` | `page_size=7` 首页 + 末页 182 | 1272 | 末页 5 行，`1272 = 181*7 + 5` |

508 / 1272 行的列表没有整表翻完，用末页余数核 `page_info`。

### 分维求和 — 成立（修审计之前手算）

`promotion.bytedance.advertiser.list` 滤 `24502679`，全 101 行：

- `sum(list[].stat_cost) = 31612.50`
- `data.total` 的运行时形状是 `[{stat_cost: "31612.50"}]`，不是对象
- 两者相等。25/101 行非零，其余零消耗账户仍在划分里

项目层首页 `data.total[0].stat_cost` 已是同一 `31612.50`（首页 3 行之和只有 12853.65，说明 total 是全集不是当页）。末页回显同一 total。

合同把 `data.total` 登记成对象（`data_item_keys.total=["stat_cost"]`），上游给的是单行数组。SDK 仍把 `stat_cost` 投影出来了。`dimension_sum_audit` 原先要求 `total` 是 Mapping，投放报表永远进不了诊断。已修：接受单行数组，并把 `stat_cost` / `query_fields` 纳入可加指标。

### 时间窗可加 — 成立

同一广告主报表、同一 iOS App、同一指标：

- `2026-08-15..2026-08-17` total = 31612.50
- `2026-08-15..2026-08-15` = 13581.53
- `2026-08-16..2026-08-17` = 18030.97
- `13581.53 + 18030.97 = 31612.50`

三个窗的 `total_number` 都是 101，账户集合没因日期收缩。

### 跨 route

- 账号目录 `promotion.bytedance.account.list` 声明 508 行（与未过滤广告主报表条数相同）。未整表对 `advertiser_id` 集合，预算不够。
- 广告主层 total = 项目层 total = 31612.50，同一 iOS App 同窗。
- 素材报表 vs 素材库：对不上标识。见下一节。

### 素材标识 — 不成立，已标注

`material.report.query` `platform=bytedance`：

| App | `total_number` | 首页 `gravity_material_id` | 首页 `material_id`（投影后） | `file_name` |
|---|---:|---|---|---|
| `29034827` | 1272 | 10/10 为 `"0"` | 被省略（drift 里是 string） | 10/10 唯一且非空，消耗合计 31884.95 |
| `24502679` | 423 | 10/10 为 `"0"` | 同上 | 10/10 唯一 |
| `27192043` | 0 | — | — | — |

末页 5 行同样 `gravity_material_id="0"`。`response_drift` 列出被省略的 `material_id`（string）以及 30+ 个未登记字段。

`material.bytedance.list` 绑 iOS 有消耗广告主：11 行，`gravity_material_id` 全是整数 0，`material_id` 11/11 唯一（19 位字符串）。同页 `file_name` 与素材报表首页 10 个名字重叠 0。

交叉验证：报表行有正 `stat_cost`/`ctr`，所以不是「没素材」。恒 0 的是 `gravity_material_id`，不是消耗。按既有先例标注 `unreliable_item_keys`，并在报表合同补登记 `material_id`。

另：`advertiser_id="0"` 的 `material.bytedance.list` 返回 `total_number=2471259`，不是拒绝。这是上游语义，不是本趟要修的 bug；调用方若把占位 0 当广告主会扫到百万级目录。

### 产出面往返

- `report.report.list` / `report.subscribe.list`：当前账号明确空（`total_number=0`）。写=0，不能自建。旧闭环靠 marker 自建，本趟无对象可对。状态列保持已闭环。
- `analysis.dashboard.tree` App `29034827`：2 个空间节点，走出 2 个带 `space_id` 的看板。`analysis.dashboard.detail` 两次成功，树与 detail 的 `id`/`name`/`space_id` 一致。
- detail 不返回 `app_id`（合同里是 optional，warning 已说）。`even_report` 是 18 元数组，登记键 `report_id/name/subject/config/remark` 都在；未登记的 `id`/`order_id`/`report_config` 进 drift。看板挂的是分析图表配置，不是 `report.report.list` 那类可复用报表，所以不能拿 `even_report.report_id` 去对空的报表目录。

### 常量性（只作信号）

- 广告主报表 101 行 `advertiser_system_status` 全相同、`advertiser_agent_id` 全相同：无反证，不标注。
- `advertiser_budget_mode` 有 2 个值。
- 素材报表 `ctr`/`convert_rate`/`stat_cost` 有变化，不是死字段。

## 推测（不是事实）

- 投放消耗记在 iOS 分身、归因/事件记在抖音分身，可能是账户绑定而不是 SDK 选错 App。未读账户后台配置。
- `gravity_material_id=0` 可能是上游未回填 Gravity 本地库 id，平台侧 id 在被省略的 `material_id`。标注后调用方应改用 `material_id`。
- 素材报表与素材库 `file_name` 对不上，可能是报表按素材聚合、库按广告主素材文件，不是同一粒度。证据不足，不报跨 route bug。
- 自有报表/订阅当前空，可能是 marker 清理后的真实空集，不是权限拒绝（`ok=true` / `empty`）。

## 修了什么

1. `dimension_sum_audit` 认不出投放 `total=[{stat_cost}]`。
   - 红：`test_resolver_flags_stat_cost_when_upstream_total_is_a_one_row_array`，审计漏掉 mismatch。
   - 绿：同一测试看到 `stat_cost` `list_sum=15.5` / `total=20` / `delta=4.5`。
   - 既有 `reporting_ad_cnt` 对象形 total 测试仍绿。
2. `material.report.query` / `material.bytedance.list` 的 `gravity_material_id` 标 `unreliable_item_keys`；报表补登记 `material_id`。
   - 红：`test_material_report_marks_gravity_material_id_unreliable`、`test_bytedance_material_list_marks_gravity_material_id_unreliable` 在标注前没有该键。
   - 绿：`describe` 给出 `reason` + `use_instead`，读取 `warnings` 复述不要用该字段。

未登记字段只进 drift，不删、不伪造。

## 没修什么

- 投放消耗与归因不在同一 App：上游绑定，不是 SDK 选错。SDK 没告诉调用方「promotion performance 的 `--app` 滤的是投放报表 `app_id`，不是归因画像」。这是语义缺口，改产品文案会动 CLI/Agent 面，本趟只记录。
- `advertiser_id=0` 扫出百万素材：上游语义。
- 自有报表/订阅当前空：无对象可对，不改动线状态。
- 广告主/项目合同的 `data.total` 类型仍写成对象：投影已经能取出 `stat_cost`，改 schema 形状要动编译与大量夹具，收益只是让审计在修之前就能看见。
- `client.py` 未改（AST 6764/6765）。

## 动线含义

状态列不改。冻结评测题集不依赖本趟发现的字段。表头 `56 = 50 / 3 / 3` 不动。

## 门禁

见最终回复。未 push、未碰 GitHub。未读、未写 `docs/roadmap.md`。
