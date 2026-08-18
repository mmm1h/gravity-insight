# 分维组标签：投影不再丢掉调用方必需的标识

- 日期：2026-08-19
- 任务：#215
- 结论：事件查询按 `$os` 分维后，每一行都能看到 `用户.设备类型`；scatter 格子能看到 `user$os`。漏斗 `aggregate_date.group` 短标识继续留下。`union_groups` / `y` / `uid` / `group_cols` 仍被挡住。

## 这一类还有多少

投影只放行三类东西：合同登记键、请求派生键（`group_by_list.field` / 事件名）、以及 `allowed_analysis_response_key` 的窄例外。组标签经常不是请求字段名，所以会被当未登记键丢掉。

| route | 分维形状 | 上游组标识 | 修前 | 修后 |
| --- | --- | --- | --- | --- |
| `analysis.event.query` | `group_by_list` 含 `$os` + `create_time/day` | 最内层行键 `用户.设备类型`，值 `null` / `android` / `harmonyos` | 丢掉，只剩日期数字 | 行上留下展示名 |
| `analysis.funnel.query` | 同上 | `aggregate_date.group` 短标识（`android` / `null`） | #206 已修 | 不变 |
| `analysis.retention.query` | 同上 | `total[].group_cols` 已在 nested keys 里 | 不丢组标识；`uid` 丢掉 | 不变 |
| `analysis.property.query` | `group_by_list.field=$os` | 行键就是请求字段 `$os` | 不丢；中文展示名仍省略 | 不变（调用方已有 `$os`） |
| `analysis.scatter.query` | `group_by_list` 含 `$os` | 最内层格子键 `user$os` | 丢掉，格子变空对象 | 格子留下 `user$os` |

`union_groups`（array）和 `y`（object）是事件查询顶层图表辅助结构，不是行标签。本趟不登记、不投影。

## 发了什么请求、拿到什么响应

全部只打投放中抖音 App `29034827`。写 0 次。相对短语 `last 7 days` 解析为 `2026-08-13..2026-08-19`（Asia/Shanghai）。

1. `analysis.event.query`，`$AppRegister` / `PresetAllCount` / `time_grain=day`，无属性分维。
   - HTTP 200。1 行，阶段总和 3333。行上只有日期键，没有组标签。这是预期。
2. 同一请求加 `group_by=[{"field":"$os","source":"user"}]`，编成 `type=user`。
   - HTTP 200。3 行：`用户.设备类型=null` 16、`android` 2497、`harmonyos` 820。16+2497+820=3333。
   - `warnings` 仍有 `unregistered analysis response data keys were omitted (count=2)`，`result_audit` 只剩 `/data/union_groups` 与 `/data/y`。
3. `analysis.scatter.query`，同一事件、同一窗、同一 `$os` 分维，`zone=default`。
   - HTTP 200。`aggregate_date` 是二维格子，不是漏斗那种 `group` 对象。
   - 修前 drift 看到 `/data/aggregate_date/*/*/user$os`（string 与 null）。修后 13 个格子里 12 个有 `user$os`（`android` / `harmonyos`），1 个值为 null；`proc_zone` / `stat_total` / `aggregate_date_group` 仍省略。

本趟生产读约 4 次产品查询（事件不分维 1、事件分维 1、scatter 分维 2）。每次 analysis query 另有 metadata 预取，未计入上表。未枚举另外 6 个空 App。

## 修了什么

只改 `analysis_projection_contract.allowed_analysis_response_key`：

- 事件查询最内层行：`用户.*` / `事件.*` 展示名。
- scatter 最内层格子：`{type}${field}`，例如 `user$os`。
- 漏斗 `aggregate_date.group` 短标识保持原规则。

`uid` / `group_cols` 不是这两种形状，继续丢掉。没有改成「什么都投影」。

测试：

两处开口各配一条会红的测试（合并前补齐：scatter 那条一度被删，只剩生产证据，
但生产不会在回归里跑，开口会静默退化）：

| 测试 | 红 | 绿 |
| --- | --- | --- |
| `test_event_query_keeps_display_group_labels_and_drops_non_labels` | `AssertionError: 'iOS' != None` | 行上留下 `用户.设备类型`；`uid` 仍不在结果里；不分维形状不变 |
| `test_scatter_query_keeps_composed_group_labels_and_drops_non_labels` | `AssertionError: 'android' != None` | 格子留下 `user$os`；`uid` 仍不在结果里 |

红是把 `analysis_projection_contract.py` 单独退回 `dev` 版本、其余不动跑出来的。

## 推测 / 确凿

确凿：事件分维行标签是属性展示名，不是 `$os`；scatter 分维格子标签是 `type+field` 拼接；两组数字可加回事件总分。

推测：`union_groups` / `y` 是前端分层图辅助结构。未拆响应原文，故不登记。scatter 的 `proc_zone` / `stat_total` 是分区统计，不是组标签，本趟不开。

## 没修什么

- 不把 `union_groups` / `y` 放进合同。
- 不改错误文案、`--help`、文档导航、评测、质量阈值。
- 不动 `docs/roadmap.md`。不 push、不碰 GitHub。
