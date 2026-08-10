# Gravity 支付口径

## 复核状态

`gravity sql status --json` 通过 central resolver 固定到一个 immutable snapshot，并在输出中返回 snapshot ID、manifest/result hash；其中的 `payment-summary` 是本口径的最近验证权威。本文定义长期语义，不以正文日期代表当前可用性；`stale`、`pending_review` 或 `blocked` 时查询会被拒绝。

2026-07-17 以前的 SQL 与已发布报告保留当时说明，不做追溯改写。

## 可执行查询

```powershell
gravity sql verify [--date YYYY-MM-DD] [--publish]
gravity sql query payment-summary --start YYYY-MM-DDTHH:MM:SS --end YYYY-MM-DDTHH:MM:SS [--app-id ID ...]
```

只有显式 `verify --publish` 才更新最近验证证据。查询返回 `partial` 时仍可使用聚合结果，但必须原样保留 `warnings` 和 `forbidden_claims`，不得补写被禁止的结论。

## 基础契约

| 项目 | 统一定义 |
| --- | --- |
| 数据源 | Gravity 事件表中的 `$PayEvent` |
| 应用范围 | 查询必须显式声明 `app_id`；Merge2 当前默认 `29034827`，跨应用不得沿用默认值 |
| 时间 | `Asia/Shanghai`，窗口使用左闭右开 `[start, end)` |
| 金额 | `properties['$pay_amount']`，单位分；人民币元为 `amount_cent / 100.0` |
| 订单键 | 优先非空 `$order_id`；缺失时使用 `user_id + create_time + $pay_reason + $pay_amount` |
| 支付状态 | `$PayEvent` 只在订单进入 `PAID` 的成功分支上报；取消或失败使用独立事件 `pay_cancel` |
| 活动归因 | `payment-summary` 不做活动归因；`$pay_reason` 只能作为支付原因聚合，不等于活动 assignment 或 exposure |
| 买家 | 支付窗口内 `COUNT(DISTINCT user_id)` |

## 稳定指标 ID

| 指标 ID | 定义 |
| --- | --- |
| `gravity_revenue_v1` | 对去重后的 `pay_key` 汇总 `amount_cent`，再除以 100 |
| `gravity_order_count_v1` | `COUNT(DISTINCT pay_key)` |
| `gravity_buyer_count_v1` | `COUNT(DISTINCT user_id)` |
| `arppu_gravity_v1` | `gravity_revenue_v1 / gravity_buyer_count_v1`；买家为 0 时返回空值 |
| `participation_rate_active_v1` | 参与用户 / 同窗活跃用户 |
| `participation_rate_eligible_v1` | 参与用户 / 明确可参与用户 |
| `completion_rate_participant_v1` | 完成用户 / 参与用户 |
| `milestone_reach_rate_v1` | 到达指定里程碑用户 / 参与用户 |

## 使用纪律

- 报告必须写明指标 ID、`app_id`、时间窗口，以及 `payment-summary` 未做活动归因。
- 收入、订单和买家不得在同一当前报告中混用 GM 与 Gravity。
- GM 继续用于活动配置、名单下发和运营执行，不再作为当前专题的平行支付口径。
- `$PayEvent` 不等同于会计结算流水。退款、拒付、平台分成或税费未被事件完整表达时，应明确写“行为支付口径”，不得推导净收入或财务对账结论。
- 没有 assignment/holdout 时只能写观察性变化，不能写因果 uplift。
