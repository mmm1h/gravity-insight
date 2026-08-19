> 归档材料：保留历史决策与取证，不代表当前接口或状态；当前入口见 docs/index.md。

# 实时事件目录：开窗后等 50 分钟仍空

- 日期：2026-08-18
- 任务：#199
- 结论：开窗后持续 50 分钟、8 个时间点 + 2 种非空 filters 仍空，入库延迟假说不成立；读产品保持完全缺失。

## 确凿事实

### 第 0 步

开窗前读 `app.realtime_event.list`（`app_id=29034827`）得到：

```json
{
  "create_time": "2026-05-16 12:06:14",
  "modify_time": "2026-08-18 12:26:13",
  "app_id": 29034827,
  "is_enabled": 0,
  "start_time": "2026-08-18 12:19:28",
  "end_time": "2026-08-18 14:19:28"
}
```

`is_enabled=0`，`modify_time` 仍是午间关窗时刻，没有发现别人开着窗。

### 生产请求（只动 App `29034827`）

| # | operation | 形状 | HTTP | 结果 |
|---:|---|---|---:|---|
| 1 | `app.realtime_event.list` | GET `app_id=29034827` | 200 | 上表 `is_enabled=0`，`modify_time=2026-08-18 12:26:13` |
| 2 | `app.user.realtime.event.update` dry-run | `app_id=29034827` `is_enabled=1` `start_time=2026-08-18 12:40:56` `end_time=2026-08-18 14:40:56` `time_slot=2` | 0 网络 | preview；body 只含该 App |
| 3 | 同上 execute | 同上 | 200 | 读回 `is_enabled=1`，窗被收成 `12:40:37..14:40:37`，`modify_time=2026-08-18 12:41:37` |
| 4–11 | `analysis.realtime_event.list` | 见下方 8 行时间序列 | 200 | 每次 drift 仅 additive `/data/list`（array）；无 item、无 `page_info` |
| 12–13 | `analysis.event.list` | `app_id=29034827` `page=1` 先 `page_size=100` 再 `page_size=2000` | 200 | 全量 117 条，`yesterday_count` 全部为 0 |
| 14–15 | `analysis.realtime_event.list` | 非空 `filters.event_name` / `filters.event_type` | 200 | 同上，空 `data.list` |
| 16 | `app.user.realtime.event.update` execute | `is_enabled=0`，窗 `12:40:37..14:40:37` | 200 | 读回 `is_enabled=0` |
| 17 | `app.realtime_event.list` | GET `app_id=29034827` | 200 | 见下方关窗 `conf` |

未碰 `27018426` / `27192043` / `24502679` / `20698471` / `27612408` / `26827043`。

### 第 2 步：8 个时间点（时间是唯一变量）

开窗后立刻挂 70 分钟看门狗。形状固定为前端默认：当天窗 `request_time=["2026-08-18 00:00:00","2026-08-18 23:59:59"]`、`filters={}`、`page=1`、`page_size=50`。8 次里没有换形状。

SDK 投影每次 `status=empty`（draft 未登记 `data.list`，空 array 被收成 empty）。协议层以 HTTP receipt 为准：8 次全部 HTTP 200，`response_drift.classification=additive`，字段只有 `/data/list:array`，指纹 `b5bd3039…`（与午间当天窗相同）。

| n | 开窗后 | 本地时间 | HTTP | `code` | `data.list` | `page_info` |
|---:|---:|---|---:|---|---|---|
| 1 | 2 min | 12:43:37 | 200 | 成功（投影 empty） | 空 array | 无 |
| 2 | 5 min | 12:46:37 | 200 | 同上 | 空 array | 无 |
| 3 | 10 min | 12:51:37 | 200 | 同上 | 空 array | 无 |
| 4 | 15 min | 12:56:37 | 200 | 同上 | 空 array | 无 |
| 5 | 20 min | 13:01:37 | 200 | 同上 | 空 array | 无 |
| 6 | 30 min | 13:11:37 | 200 | 同上 | 空 array | 无 |
| 7 | 40 min | 13:21:37 | 200 | 同上 | 空 array | 无 |
| 8 | 50 min | 13:31:37 | 200 | 同上 | 空 array | 无 |

没有一次非空，所以没有提前停。

### 第 2.5 步：非空 filters（窗仍开着）

`analysis.event.list` 两次：`page_size=100` 得 100 条，`page_size=2000` 得全量 `total_number=117` / `total_page=1`。117/117 的 `yesterday_count` 都是 `0`，**该 App 上不存在 `yesterday_count > 0` 的事件名**。事件名取自这份已证实存在的列表，不凭空编：自定义事件 `microgame_window_click`（固定入口点击）。`event_type` 取自 hash-matched 前端 `Debug-hpZqESZ9.js` 的 select 选项：`track`（行为事件）/ `profile`（用户事件）；本趟用 `track`。

| n | 本地时间 | `filters` | HTTP | `data.list` | 指纹前 8 |
|---:|---|---|---:|---|---|
| 9 | 13:33:22 | `{event_name: "microgame_window_click"}` | 200 | 空 array | `87c3438c` |
| 10 | 13:33:23 | `{event_type: "track"}` | 200 | 空 array | `6e833dff` |

两次 drift 仍只有 additive `/data/list:array`。没有 item、没有 `page_info`。

### 关窗后重读的 `conf` 原文

```json
{
  "create_time": "2026-05-16 12:06:14",
  "modify_time": "2026-08-18 13:33:34",
  "app_id": 29034827,
  "is_enabled": 0,
  "start_time": "2026-08-18 12:40:37",
  "end_time": "2026-08-18 14:40:37"
}
```

`modify_time` 从 `2026-08-18 12:26:13` 变成 `2026-08-18 13:33:34`，证明本趟写过并已关回。看门狗已停；停后再读一次 `conf`，仍是上表。

### 预算

任务上限：写 2（失败再 +2）；`app.realtime_event.list` 读 6；`analysis.realtime_event.list` 读 12；`analysis.event.list` 读 2。

本趟实际：

- 写：2 次（开 1 + 关 1），无失败重试。
- `app.realtime_event.list`：3 次（开窗前 1、开窗读回随 mutation 1 次计入写后读回、关窗后再读 1）。上限 6，未超。
- `analysis.realtime_event.list`：10 次（8 次时间序列 + 2 次 filters）。上限 12，未超。
- `analysis.event.list`：2 次。上限 2，用尽。

均未超。未扩到别的 App。

## 三趟对照

| 趟 | 开窗 | 关窗 | 窗实际开了多久 | 读取形状 | 次数 | 结果 |
|---|---|---|---:|---|---:|---|
| 凌晨 | `03:21:23` 开，窗约 2h | `03:30:35` | 约 9 分钟 | 当天窗，`page_size=1`，`filters={}` | 10 | HTTP 200，空 `data.list` |
| 午间 | `12:20:28` 开，窗约 2h | `12:26:13` | 约 7 分钟 | 当天窗 + 近 1h 窗，`page_size=50`，`filters={}` | 12 | HTTP 200，空 `data.list` |
| 本趟 | `12:41:37` 开，窗约 2h | `13:33:34` | **约 52 分钟** | 当天窗，`page_size=50`，`filters={}`，8 个时间点；随后 2 种非空 filters | 10 | HTTP 200，空 `data.list` |

因此「开窗后等得不够久（批量 flush 在 7–9 分钟之后）」不成立。在投放中的抖音 App `29034827` 上，前端默认当天窗持续观察到开窗后 50 分钟仍无 item。

## 已经穷尽的形状空间

- 关着开关：前端当天窗、近 5 分钟、近 1 小时、两次历史开启窗（见 catalog / 凌晨前半）。
- 开着开关、凌晨、约 9 分钟：当天窗 `page_size=1` `filters={}`，10 次。
- 开着开关、午间、约 7 分钟：当天窗 + 近 1h 窗 `page_size=50` `filters={}`，12 次。
- 开着开关、午后、约 50 分钟：当天窗 `page_size=50` `filters={}`，8 个递增时间点。
- 开着开关、同一窗内：`filters.event_name=microgame_window_click`；`filters.event_type=track`。

## 仍未试的部分

- `filters.event_type=profile`（用户事件）。
- `filters` 的 `request_id` / `client_id` / `client_lib` / `client_lib_version` / `properties`。
- 其它 6 个 App 的写入（本趟明确禁止）。
- 超过 2 小时的入库窗、跨日窗、或开窗后超过 50 分钟的更长等待。
- 在 `yesterday_count` 非 0 的日子重取事件名（本趟 117/117 昨天计数都是 0）。

## 推测（不是事实）

- 开着开关、等 50 分钟、空 filters 和非空 filters 都空，更像是这条入库路由在该 App 上当前没有实时流量，而不是「等得不够」。
- `analysis.event.list` 昨天计数全 0，不能单独证明今天没有实时事件：那是昨日聚合，不是这条 realtime list。
- 投放中不等于这条入库路由有实时流量。其它分析面有数据，不能外推到 `analysis.realtime_event.list`。
- draft 合同没有登记 `data.list`，SDK 投影会把空 array 收成 `status=empty` 且看不到 list。协议层事实以 HTTP 200 + additive `/data/list` 为准。

## 因此确定了什么

- **开窗后持续 50 分钟、8 个时间点 + 2 种非空 filters 仍空，入库延迟假说不成立。**
- `analysis.realtime_event.list` 保持 `draft`。blocker 仍是 `empty_sample`、`pagination_unverified`、`response_item_schema_unverified`。
- 动线「查询实时事件目录」保持完全缺失。没有读产品，Core / CLI / SDK / Plan / Agent 读面未建。
- 不许把这 10 次空 list 登记成 item schema。
- 表头 `56 = 50 / 3 / 3` 不要动：状态列未改。

## 评测题

本趟未闭环，题集现在仍然对得上，**不要改**。若以后真有读产品，`evals/agent_usability/cases/development.jsonl` 里 J35 五题都会对不上：

| case | 现在期待 | 闭环后应改成 |
|---|---|---|
| `J35.dev.zh.normal-1` | `gap_code=REALTIME_EVENT_CATALOG_CONTRACT_MISSING`，`route_key=realtime_event_gap`，`terminal_kind=capability_gap` | 命中新产品 selector，不再是目标 gap |
| `J35.dev.zh.normal-2` | 同上 | 同上 |
| `J35.dev.en.normal-1` | 同上 | 同上 |
| `J35.dev.zh.boundary` | 同上 | 同上；仍须与历史事件元数据搜索分开 |
| `J35.dev.en.missing` | 同上 | 不再要「取证 next_action」；应走产品缺参/空结果合同 |
