# 误导字段：yesterday_count 死字段与 app_id 类型

- 日期：2026-08-18
- 任务：#201
- 结论：`yesterday_count` 在本租户 7/7 App 上恒为 0，是死字段不是数据条件问题；`app_id` 55 条 string / 28 条 integer / 0 条双类型，SDK 只按合同声明类型做标识归一化。

## 确凿事实

### 陷阱一：`analysis.event.list.yesterday_count`

请求形状（7 个 App 各 1 次，共 7 次读，0 次写）：

- operation：`analysis.event.list`
- 输入：`app_id` 为字符串、`page=1`、`page_size=2000`、`need_favourite` 走合同默认
- 未改时间窗（该 route 没有日期输入）
- 未碰实时事件相关路由

| `id` | os | 事件总数 | `yesterday_count` 非 0 | 字段类型 |
| --- | ---: | ---: | ---: | --- |
| 29034827 | 6 | 117 | 0 | 117 int |
| 27018426 | 15 | 13 | 0 | 13 int |
| 27192043 | 1 | 118 | 0 | 118 int |
| 24502679 | 0 | 117 | 0 | 117 int |
| 20698471 | 3 | 25 | 0 | 25 int |
| 27612408 | 3 | 129 | 0 | 129 int |
| 26827043 | 3 | 129 | 0 | 129 int |

交叉验证（同日 `2026-08-17`，`attribution.attribution.query`，`dims_list=["date"]`，`metrics_list=["AppRealRegisterCnt"]`，`statistics_caliber=user_activated_time`，`app_id` 为整数）：

| `id` | envelope | 有正 `AppRealRegisterCnt` 行 |
| --- | --- | --- |
| 29034827 | `success`，1 行 | 是 |
| 27192043 | `success`，1 行 | 是 |
| 27018426 | `empty`，0 行 | 否 |

因此：投放中抖音 App 与 Android 分身昨天都有量，但事件目录仍报 0。这不是“某个 App 没数据”。

本轮生产读 **10** 次（7 事件列表 + 3 归因），写 0 次。

### 陷阱二：`app_id` 声明类型（236 个 operation 合同）

| 字段 | 声明类型 | 条数 |
| --- | --- | ---: |
| `app_id` | string | 55 |
| `app_id` | integer | 28 |
| `app_id` | 两种都接受 | 0 |
| `app_ids` | array（无 item_type） | 1 |
| 无 `app_id` / `app_ids` | — | 152 |

同类标识也有 string/integer 分裂，例如 `advertiser_id` 6 string / 4 integer，`dashboard_id` 2/2，`project_id` 2/1，`space_id` 2 string / 12 integer。这些字段没有做成通用归一化。

## 判定

- **`yesterday_count` 是本租户死字段。** 7/7 App 全 0，且至少 2 个 App 用有量 route 证明昨天有事件量。未试其它日期，因为该字段没有日期输入；“昨天”由上游决定。
- **`app_id` 做合同内归一化。** 证据是：同一标识在不同 route 声明相反类型，没有任何合同同时接受两种类型，也没有证据表明某条 route 的 string/integer 语义不同。归一化是纯增量。

## 推测（不是事实）

- 上游可能根本没算 `yesterday_count`，或只对未观察到的内部条件赋值。本轮没有前端源码证明。
- 其它租户是否同样全 0，未知。标注按本租户实测写，没有写成“全球恒 0”。

## 处置

- 不删除、不改写 `yesterday_count` 的上游值。
- 合同 `response_projection.unreliable_item_keys.yesterday_count` 给出 `reason` + `use_instead`；`describe`/`schema` 透出；读取 `warnings` 复述“不要用这个字段判断有没有数据，走 attribution 或 evaluate_data”。
- `app_id` 只在合同已声明 `string`/`integer` 时，把正整数与其十进制数字字符串归一到声明类型。`"abc"`、负数、非数字仍 fail-closed，错误带 `field=app_id`。
- 未对 `advertiser_id` 等其它分裂标识做归一化。

## 未改

- 不改评测装置、题集、评分、阈值；不跑 holdout / final。
- 不动 `docs/roadmap.md` 汇总数字。
- 导出动线状态仍是部分闭环；冻结宽问法 gap 不变。
