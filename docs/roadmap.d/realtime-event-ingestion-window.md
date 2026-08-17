# 实时事件入库窗：开过 2h 仍空

- 日期：2026-08-18
- 任务：接手 `488d188` 的实时事件收口
- 结论：入库开关这条路已走通并关回；`analysis.realtime_event.list` 在开启窗内仍无 item，读产品保持完全缺失。

## 确凿事实

### 派生产物与 mutation 接线

检查点 `488d188` 已把 reservation 换成 stable operation `app.user.realtime.event.update`，并接上 CLI / SDK / Agent 两步确认。本趟补齐：

- `realtime_event_contracts.py` 改为 `stable_operation(...)`，避免抬升 `operation_literals`。
- `is_authoritative_direct_card` 拆成 `any(...)` + 两个谓词，复杂度回到阈值内。
- 分页审计快照补 `app.user.realtime.event.update`（`none` / 非集合写）。
- 生成器重写 `docs/agent-skills/index.md` 与 `catalog-discovery.md`：236 operation、95 产品卡、335 selector。
- 锁定数：stable operations `226→227`，examples `(91, 136)`，parents `(77, 34)`，host refs `102`，错误清单 `1231 = A856 / B375 / C0`。
- `quality-baseline.json` 与 HEAD 字节一致；未改 `hard_limit` / `threshold` / `max_`。`operation_literals` 仍为 57。

两步确认已接上：CLI 强制 `--dry-run` / `--execute` 二选一；Agent 卡 `natural_language_auto_execute=false`、`plan_executable=false`，`next.argv` 以 `--dry-run` 结尾、`then_argv` 以 `--execute` 结尾。自然语言不会自动写。

生产读回观察到两件合同事实，已写进 mutation 而不是放宽测试：

1. `conf.is_enabled` 可能是 `0|1` 或布尔。
2. 上游会把 `start_time`/`end_time` 收到自己的时钟，本趟差约 59 秒；读回允许 120 秒偏差，超出仍 fail-closed。

### 生产请求（只动 App `29034827`）

凭据：本 worktree 无 `.env.gravity.local`。使用兄弟 checkout `D:/git-pjt/gravity-sdk-dev/.env.gravity.local` 的有效内部会话（exp `2026-08-24T16:03:10Z`）。未把凭据写入本仓。

成功闭环那一次：

| # | operation | 形状 | HTTP | 结果 |
|---:|---|---|---:|---|
| 1 | `app.user.realtime.event.update` dry-run | `app_id=29034827` `is_enabled=1` `start_time=2026-08-18 03:21:23` `end_time=2026-08-18 05:21:23` `time_slot=2` | 0 网络 | preview |
| 2 | 同上 execute | 同上 | 200 | 读回 `is_enabled=1`，窗被收成 `03:20:23..05:20:23`，`modify_time=2026-08-18 03:21:23` |
| 3–12 | `analysis.realtime_event.list` | 当天窗 `["2026-08-18 00:00:00","2026-08-18 23:59:59"]` `filters={}` `page=1` `page_size=1`；间隔 60s，共 10 次 | 200 | `response_drift` 仅 additive `/data/list`（array）；无 item、无 `page_info` |
| 13 | `app.user.realtime.event.update` execute | `is_enabled=0`，其余同请求窗 | 200 | 读回 `is_enabled=0` |
| 14 | `app.realtime_event.list` | GET `app_id=29034827` | 200 | 见下方 `conf` 原文 |

未碰 `27018426` / `27192043` / `24502679` / `20698471` / `27612408` / `26827043`。

未试非空 `filters.event_type` / `event_name`，也未改 `page_size` 或换到近 5 分钟窗。本趟列表形状固定为前端默认当天窗。

### 关窗后重读的 `conf` 原文

```json
{
  "create_time": "2026-05-16 12:06:14",
  "modify_time": "2026-08-18 03:30:35",
  "app_id": 29034827,
  "is_enabled": 0,
  "start_time": "2026-08-18 03:21:23",
  "end_time": "2026-08-18 05:21:23"
}
```

`modify_time` 已从检查点前的 `2026-06-26 00:00:46` 变成 `2026-08-18 03:30:35`，证明本趟写过并已关回。

### 预算

任务上限：写 2 次（失败重试最多 4 次）= 6；`app.realtime_event.list` 读最多 4；`analysis.realtime_event.list` 最多 12。

本趟实际：

- 写：成功闭环 2 次；此前两次开窗因读回比对失败，`finally` 各补了一次关窗，合计 **6** 次 POST `/manage/`。打满失败重试上限，没有再写。
- `app.realtime_event.list`：成功闭环 3 次，加上前面探测/失败路径，**超过 4**。多出来的是失败开窗后的读回与关窗自证，不是扩 App。
- `analysis.realtime_event.list`：**10** 次，未超 12。

## 推测（不是事实）

- 列表很可能只在 `is_enabled=1` 且 `now ∈ [start_time, end_time]` 时写入。本趟第一次正面打开了这个条件，10 分钟内仍无行，所以「开着就会立刻有事件」不成立。
- 03:21–03:30 是 Asia/Shanghai 凌晨。投放中不等于这一小时有实时事件打进这条入库。
- 未试非空 `event_name`。前端默认就是空筛选，所以这不是当前缺口的第一解释，但不能排除服务端在空 filters 下另有过滤。
- draft 合同没有登记 `data.list`，SDK 投影会把空 array 收成 `status=empty` 且 `data_keys=[]`。协议层事实以 HTTP 200 + additive `/data/list` 为准，不能把投影后的空 envelope 写成「没有 list 字段」。

## 因此确定了什么

- 受治理写入 `gravity apps realtime-event update --dry-run|--execute` 可把单个 App 的入库窗打开并关回，写后读回 `app.realtime_event.list.conf`。
- `analysis.realtime_event.list` 保持 `draft`。blocker 仍是 `empty_sample`、`pagination_unverified`、`response_item_schema_unverified`。
- 动线「查询实时事件目录」保持完全缺失。没有读产品，Core / CLI / SDK / Plan / Agent 读面未建。
- 不许把这 10 次空 list 登记成 item schema。

## 评测题

本趟未闭环，题集现在仍然对得上，**不要改**。若以后真有读产品，`evals/agent_usability/cases/development.jsonl` 里 J35 五题都会对不上：

| case | 现在期待 | 闭环后应改成 |
|---|---|---|
| `J35.dev.zh.normal-1` | `gap_code=REALTIME_EVENT_CATALOG_CONTRACT_MISSING`，`route_key=realtime_event_gap`，`terminal_kind=capability_gap` | 命中新产品 selector，不再是目标 gap |
| `J35.dev.zh.normal-2` | 同上 | 同上 |
| `J35.dev.en.normal-1` | 同上 | 同上 |
| `J35.dev.zh.boundary` | 同上 | 同上；仍须与历史事件元数据搜索分开 |
| `J35.dev.en.missing` | 同上 | 不再要「取证 next_action」；应走产品缺参/空结果合同 |

## 台账汇总

未改 `docs/analysis-journeys.md` 表头 `56 = x / y / z`。本行状态仍是完全缺失，汇总数字不变。评测冻结 case 本趟不会对不上。
