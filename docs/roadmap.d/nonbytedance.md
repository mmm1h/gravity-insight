# 非 Bytedance 投放前提：先反查平台，再决定是否打空 route

- 日期：2026-08-18
- 任务：#nonbytedance
- 结论：投放中的抖音 App `29034827` 近 30 天归因平台只有 `bytedance` 与 `natural`；快手分身 `27018426` 同窗归因与变现均为明确空。按分流未再打卡住的快手/腾讯标题 route。D33/D34 与 D32 保持部分闭环。

## 本趟发了什么请求

4 次生产读，全部走已闭环 stable route，0 次卡住 route。

窗：`date_list=["2026-07-19","2026-08-17"]`。

| # | operation | App | 输入形状 | 响应 |
| ---: | --- | ---: | --- | --- |
| 1 | `attribution.attribution.query` | 29034827 | `dims_list=["date","ad_platform"]`，`metrics_list=["AppRealRegisterCnt"]`，`statistics_caliber=user_activated_time` | envelope `ok=true` / `status=success` / `items=60` |
| 2 | `report.get.query` | 29034827 | `data_dims=["monetization_platform"]`，`time_dims=total`，`metrics_list=["reporting_ad_revenue"]`，`filters=[{field:app_id,operator:EQUALS,values:["29034827"]}]` | envelope `ok=true` / `status=success` / `list=2` |
| 3 | `attribution.attribution.query` | 27018426 | 与 #1 同形状 | envelope `ok=true` / `status=empty` / 无 items |
| 4 | `report.get.query` | 27018426 | 与 #2 同形状，`app_id="27018426"` | envelope `ok=true` / `status=empty` / `list=0` |

未发：`promotion.kuaishou.campaign.list`、`material.kuaishou_creative.list`、`material.tencent_asset_text_title.list`。
未发：其余 5 个 catalog App。未换指标、未扩窗。

## 确凿事实

1. `29034827` 在该窗、该 D35 画像下有归因行。`ad_platform` 去重后只有 `bytedance`（30）和 `natural`（30）。没有 `tencent`、`kuaishou` 或其他投放平台字面量。
2. `29034827` 同窗 D28 有变现行。`monetization_platform` 只有 `dy_mini_game` 与空串。这是变现平台，不是投放平台。
3. `27018426` 同窗、同两形状均为明确空（归因 empty、变现 `list=0`）。不是权限拒绝：两条都是 `ok=true`，没有 `code=2000` / `permission_unavailable`。
4. 因此：这两个投放相关 App 在该 30 日窗内，D35 给不出可绑定的非 Bytedance `ad_platform`。按本趟分流，没有合法的 App+平台对去打卡住的三条 route。
5. D33/D34、D32 不晋升、不改闭环状态。腾讯 adgroup / 腾讯托管创意 / `material.tencent.list` 的既有非空合同仍成立。冻结评测 J45/J46 仍期待原 gap。

## 推测（不是本趟证明的）

- **不能写成「整个租户从未在非 Bytedance 投放」。** 2026-08-17 账号级 `promotion.tencent.advertiser.list` 已非空（`total_number=127`），`material.tencent.list` 也非空。那些是账号目录，不是这两个 App 的 D35 `ad_platform`。
- **不能写成「快手 App 永远无数据」。** 只试了 30 日窗 + `AppRealRegisterCnt` + 变现 `reporting_ad_revenue`。未试 `AdClick`/`AdShow`、未试更长窗、未试另外 5 个 App。
- `natural` 是自然量，不是投放平台。`dy_mini_game` 只说明抖音小游戏变现。
- 若另有租户或另有 App 的 D35 出现 `kuaishou`/`tencent`，才值得再打那三条空 route。

## 动线含义

- 状态列保持「部分闭环」。没拿到卡住 route 的 item schema，不能标闭环。
- 剩余快手计划 / 快手创意 / 腾讯标题包子路径：在**这两个 App + 该窗**上，从「证据待补、再枚举空列表」改判为「已知无绑定平台，不必再打」。
- 表头 `56 = 50 / 3 / 3` 不动。汇总由合并时对账。
