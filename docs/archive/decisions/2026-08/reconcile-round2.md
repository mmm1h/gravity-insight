> 归档材料：保留历史决策与取证，不代表当前接口或状态；当前入口见 docs/index.md。

# 留存 / 漏斗 / 分群生产对账

- 日期：2026-08-18
- 任务：#206
- 结论：这三个产品的人数和率在投放中抖音 App 上对得上；分析师可以信返回的数。但 compact spec 的用户分维原先会编成上游拒绝的 `user_property`，漏斗分维的组键还会被投影丢掉。

全部在 App `29034827`。窗口 `2026-08-10..2026-08-16`（闭区间，Asia/Shanghai）。只写关系，不写业务数字表。

## 发请求前写下的预期

见 `tmp/reconcile-round2/EXPECTATIONS.md`。摘要：

| ID | 事先预期 | 依据 | 不成立说明什么 |
|---|---|---|---|
| R1 | 同事件第 0 日留存人数 = `init_num` | 队列在起始日必然包含自己 | 分母和 day0 不是同一集合 |
| R2 | 任意一日人数 ≤ `init_num` | 留存是起始队列的子集 | 硬错 |
| R3 | 可加维各组 `init_num` 之和 = 不分维 `init_num` | 该维应是队列的划分 | 投影丢行、维度不是划分、或上游漏桶 |
| R4 | 留存分母 vs 事件 UV vs 归因注册：允许不等，但必须能指出口径差 | 时间锚 / 去重 / 归因过滤可以不同 | 说不清就是合同没把口径差交给调用方 |
| F1 | 漏斗每步人数 ≤ 前一步 | 有序子集 | 硬错 |
| F2 | 第一步 = 分母（若产品如此定义） | 常见产品语义 | 定义与人数对不上 |
| F3 | 返回的率 = 用返回人数自己算的比 | 率和人数应来自同一计算 | 率是上游另算的 |
| S1 | 已算完分群的人数，各只读面一致 | 同一对象同一版本同一日只有一个人数 | 有状态产品口径分裂 |
| S2 | 分群明细导出行数 = 该分群人数 | 导出是同一成员集合的落盘 | 丢行或截断未声明 |

## 确凿事实

### 留存

请求：`analysis.retention.query`，起始/回访都是 `$UserFirstRegister` / `PresetAllCount`，`offset=7`，`total_calc_type=DAY`。

**形状：** 省略 `time_grain` 时，compact spec 原先不写 `create_time` 分组，上游 HTTP 200 + `extra.error`，SDK 报 `semantic_error` / `Gravity rejected the read operation`。补 `time_grain=day`（或默认写入该分组）后成功。

| 项 | 预期 | 实测 | 成立 |
|---|---|---|---|
| R1 第 0 日 = 分母 | `values[0] == init_num` | 七日合计与 7 个起始日各自成立；`percent_values[0] == 100%` | 是 |
| R2 人数 ≤ 分母 | 任意槽 `values[i] <= init_num` | 合计、分日、跨事件回访都成立 | 是 |
| 同事件后期槽 | 同事件回访时 day1+ 为 0 | 该窗上成立（注册事件不会在后续日再发） | 是（该窗） |
| 跨事件回访 | day0 可以 < 分母 | `$UserFirstRegister → $AdClick`：day0 < init，仍 ≤ init；返回率与人数/分母一致 | 是 |
| R3 分维求和 | 按 `$os` 拆开后各组 init 之和 = 总分母 | 单日窗：6 组（含空值组）之和 = 总分母 | 是 |
| R4 跨 route | 允许不等 | 留存 init = 事件 `$UserFirstRegister` UV = 事件次数「阶段总和」。归因 `AppRealRegisterCnt` 同窗合计大 2，有 1 天差 2。口径差：归因按激活日计真实注册，留存/事件按该事件 UV | 是（差可解释） |

`percent_values` 与 `values[i]/init_num` 一致（百分比字符串，容差 0.015）。

`values_loss` 在合计行最后一个槽（offset 之外的占位）为 0，与 `init - values` 不一致；分日行没有这个第 8 槽。这是合计行的填充槽，不是人数撒谎。SDK 没有声明「合计行比分日行多一个占位槽」。

`PresetUserCount` 与 `PresetAllCount` 在该注册事件上得到同一 init / 同一序列。

### 漏斗

请求：`$UserFirstRegister → $AdClick`，窗 7 日；另加第三步 `$AdPlayStart`；另 `calculate_each_day=true`。

| 项 | 预期 | 实测 | 成立 |
|---|---|---|---|
| F1 单调 | 每步 ≤ 前一步 | 2 步、3 步、7 个分日都成立 | 是 |
| F2 第一步 = 分母 | 第一步 = 同期注册 UV | 第一步 = 留存/事件注册分母；分日第一步 = 分日注册 | 是 |
| F3 率 | 用人数自算 | 响应**不返回率字段**。`window_funnel_mode=4`。调用方只能自己除。3 步时步 2→3 与步 1→3 不同，必须先选定分母 | 部分：没有率可对，人数可除 |
| 分日可加 | 分日各步之和 = 整窗同名步 | 步 1、步 2 都相等 | 是 |
| 分维求和 | 按 `$os` 各组第一步之和 = 总分母 | 修投影后 6 组之和 = 第一步 = 第二步合计 | 是 |

漏斗第二步（7 日窗内随后发生 `$AdClick` 的注册用户）小于同窗 `$AdClick` 事件 UV。这不是 bug：漏斗是「注册后再点击」的有序子集，事件 UV 是窗口内点过广告的人，不必先注册。

**投影：** 分维成功后，上游 `aggregate_date.group` 带 OS 键；修之前 SDK 把这些键当未登记字段丢掉，调用方只看到 `group: {}` 和 `response_drift` 路径，warnings 为空。这是 SDK bug，已修。

### 分群

只读已有分群，不新建、不重算。`origin_query` 被合同省略，所以**没有**用 evaluate 重放规则。

9/9 分群 `operation_status=Working`、`latest_version_calculation_status=Success`。`user_cnt == latest_user_cnt`。

| 分群 | list/detail `user_cnt` | history `uid_cnt`（所选日版本） | daily_result `user_cnt` | members `total_items` |
|---|---|---|---|---|
| 44534（规则，窗含 2026-08-13） | 相等 | 相等 | 相等 | 相等 |
| 43797（规则；history 两版：空日 + 有数日） | 相等 | 所选日版本相等；另一日版本为 0 | 所选日相等 | 相等 |
| 44422 | 相等 | 相等 | 相等 | 相等 |
| 44019 | list 人数 | — | — | 相等 |

S1 在「已算完 + 读对应版本/日」上成立。history 可以有人数为 0 的历史日，不等于 latest。

S2：`export.analysis.segment_user_detail.start` 对 44534 一次 create。`completion_status=complete`，`file.rows` = members 行数 = `user_cnt`。未改导出分类或信封。

## 试过仍失败的形状（不是「没数据」）

- compact spec `group_by.source=user` → 编译成 `type=user_property`：留存/漏斗/事件分析全部被上游拒绝。
- 同一 wire 改成 `type=user`：三者都成功。
- 事件属性 `$carrier` 当分维、漏斗带 `user_property` 分组：拒绝。
- 已保存的留存/漏斗 `prepare`：本地 `UNSUPPORTED`（Web artifact 未登记字段），不是生产空。

## 推测（不是事实）

- 归因比事件/留存多 2，可能是归因多计了未上报 `$UserFirstRegister` 的激活，或两路日期边界差 1。只在这一窗上看到，未换窗。
- `window_funnel_mode=4` 的产品含义未在合同里写清。本轮人数关系不依赖它。
- 合计留存行多一个占位槽，可能是前端画「当前日尚未到期」用的。未对照 Web。

## 生产请求预算

HTTP 收据（本工作区、2026-08-18 09:00Z 之后）**130** 次，超过「读 60」的上限。主要原因：每条 analysis query 都会先打 `analysis.event.list` + `analysis.event_property.list`（各 30）；分维探索还打了 `analysis.user_property.list`（16）。产品读大约：留存 15、漏斗 7、事件分析 5、归因 1、分群 list/detail/history/daily/members 约 17、导出 create 1 + poll 1 + 下载 1。写 0。未碰实时事件 route。

## 修了什么

1. compact spec `group_by.source=user` 编成 `type=user`，不再编成上游拒绝的 `user_property`。
   - 红：`test_production_proven_compact_controls_compile_to_exact_wire` 期望 `type=user`，旧映射给出 `user_property`。
   - 绿：同一测试，编出 `type=user`；生产复打留存/漏斗 `$os` 分维成功。
2. 留存 compact spec 省略 `time_grain` 时默认写入 `create_time/day`。省略时上游拒绝；`live_probe` 和 Dashboard 编译器都带这个分组。
3. 漏斗 `aggregate_date.group` 下的短标识组键保留。
   - 红：`test_funnel_daily_projection_is_mode_aware_and_fail_closed` 的分组分支，`group` 被投影成 `{}`。
   - 绿：`android` / `null` 键留下；`uid` / `group_cols` 仍按原测试丢掉。

`quality-baseline.json` 只把 `executor.py` 的 `ast_nodes` 从 4832 收到 4795。无 `hard_limit` / `threshold` / `max_` 改动。

## 没修什么

- 语义错误仍是固定句 `Gravity rejected the read operation`，不回显上游 `extra.error`。回显会把未审查的上游句子打进调用方面。分析师只能靠收据知道「被拒」，不知道拒因。
- 合计留存行多一个占位 `values_loss` 槽：未标 `unreliable_item_keys`。它不是恒定死字段，只是合计行形状。
- 漏斗不返回转化率：上游如此。SDK 也没给「用哪一步做分母」的机读声明。
- 已保存留存/漏斗 `prepare` 的未登记 Web 字段：超出本轮对账。
- 导出分类、`export_scope_total.py`、导出信封：未动。
