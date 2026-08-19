> 归档材料：保留历史决策与取证，不代表当前接口或状态；当前入口见 docs/index.md。

# 实时事件目录：午间峰值重打仍空

- 日期：2026-08-18
- 任务：#196
- 结论：凌晨 03:21 与午间 12:20 两个开启窗都空；时段假阴性已排除，读产品保持完全缺失。

## 确凿事实

### 第 0 步基线

`python -m unittest discover -s tests`：`Ran 1198 tests`，3 个失败。失败项是 CLI help 被终端 ANSI 着色：

- `test_nested_help_keeps_the_copyable_census_prefix`
- `test_dashboard_snapshot_help_exposes_trailing_output_options`
- `test_nested_help_uses_copyable_gravity_command`

`NO_COLOR=1` 后这 3 项 `OK`。与 realtime-event 实现无关，未改代码。

开窗前读 `app.realtime_event.list`（`app_id=29034827`）得到：

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

上一趟关窗仍在生效，没有发现别人开着窗。

### 生产请求（只动 App `29034827`）

凭据：本 worktree 原先无 `.env.gravity.local`。从兄弟 checkout `D:/git-pjt/gravity-sdk-dev/` 复制 gitignore 会话文件（exp `2026-08-25T00:03:10+08:00`）。未提交凭据。

| # | operation | 形状 | HTTP | 结果 |
|---:|---|---|---:|---|
| 1 | `app.realtime_event.list` | GET `app_id=29034827` | 200 | 上表 `is_enabled=0`，`modify_time=2026-08-18 03:30:35` |
| 2 | `app.user.realtime.event.update` dry-run | `app_id=29034827` `is_enabled=1` `start_time=2026-08-18 12:19:49` `end_time=2026-08-18 14:19:49` `time_slot=2` | 0 网络 | preview；body 只含该 App |
| 3 | 同上 execute | 同上 | 200 | 读回 `is_enabled=1`，窗被收成 `12:19:28..14:19:28`，`modify_time=2026-08-18 12:20:28` |
| 4–15 | `analysis.realtime_event.list` | 见下方 12 行表 | 200 | 每次 drift 仅 additive `/data/list`（array）；无 item、无 `page_info` |
| 16 | `app.user.realtime.event.update` execute | `is_enabled=0`，窗 `12:19:28..14:19:28` | 200 | 读回 `is_enabled=0` |
| 17 | `app.realtime_event.list` | GET `app_id=29034827` | 200 | 见下方关窗 `conf` |

未碰 `27018426` / `27192043` / `24502679` / `20698471` / `27612408` / `26827043`。

### 午间 12 次读取

前端默认形状 + 本趟新增的最近一小时窗；`page=1`、`page_size=50`、`filters={}`。间隔约 60s，共 6 个周期 × 2 种窗 = 12 次。SDK 投影每次 `status=empty`（draft 未登记 `data.list`，空 array 被收成 empty）。协议层以 HTTP receipt 为准：12 次全部 HTTP 200，`response_drift.classification=additive`，字段只有 `/data/list:array`。

| n | 本地时间 | 窗 | `request_time` | HTTP | `code` | `data.list` | `page_info` |
|---:|---|---|---|---:|---|---|---|
| 1 | 12:20:58 | 当天 | `["2026-08-18 00:00:00","2026-08-18 23:59:59"]` | 200 | 成功（投影 empty） | 空 array | 无 |
| 2 | 12:20:58 | 近 1h | `["2026-08-18 11:20:58","2026-08-18 12:20:58"]` | 200 | 同上 | 空 array | 无 |
| 3 | 12:21:58 | 当天 | 同 #1 | 200 | 同上 | 空 array | 无 |
| 4 | 12:21:58 | 近 1h | `["2026-08-18 11:21:58","2026-08-18 12:21:58"]` | 200 | 同上 | 空 array | 无 |
| 5 | 12:22:58 | 当天 | 同 #1 | 200 | 同上 | 空 array | 无 |
| 6 | 12:22:58 | 近 1h | `["2026-08-18 11:22:58","2026-08-18 12:22:58"]` | 200 | 同上 | 空 array | 无 |
| 7 | 12:23:58 | 当天 | 同 #1 | 200 | 同上 | 空 array | 无 |
| 8 | 12:23:58 | 近 1h | `["2026-08-18 11:23:58","2026-08-18 12:23:58"]` | 200 | 同上 | 空 array | 无 |
| 9 | 12:24:58 | 当天 | 同 #1 | 200 | 同上 | 空 array | 无 |
| 10 | 12:24:58 | 近 1h | `["2026-08-18 11:24:58","2026-08-18 12:24:58"]` | 200 | 同上 | 空 array | 无 |
| 11 | 12:25:58 | 当天 | 同 #1 | 200 | 同上 | 空 array | 无 |
| 12 | 12:25:58 | 近 1h | `["2026-08-18 11:25:58","2026-08-18 12:25:58"]` | 200 | 同上 | 空 array | 无 |

receipt 12 条（本趟，UTC `04:20:59`–`04:26:00`，上海 12:20:59–12:26:00）全部 `http_status=200`，`request_shape_fingerprint=b5bd3039…`，drift 字段只有 `/data/list:array`。没有 item、没有 `page_info`。

未试非空 `filters.event_type` / `event_name`，未换 App，未把空 list 当 schema。

### 关窗后重读的 `conf` 原文

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

`modify_time` 从 `2026-08-18 03:30:35` 变成 `2026-08-18 12:26:13`，证明本趟写过并已关回。

### 预算

任务上限：写 2 次（失败重试最多再 2 次）；`app.realtime_event.list` 读最多 5；`analysis.realtime_event.list` 读最多 14。

本趟实际：

- 写：2 次（开 1 + 关 1），无失败重试。
- `app.realtime_event.list`：4 次（开窗前 1、开窗读回 1、关窗读回 1、杀看门狗后再读 1 确认仍关）。上限 5，未超。
- `analysis.realtime_event.list`：12 次。

均未超。未扩到别的 App。

## 两个时段对照

| 时段 | 开窗 | 关窗 | 读取形状 | 次数 | 结果 |
|---|---|---|---|---:|---|
| 凌晨 | `03:21:23` 开，窗约 2h | `03:30:35`，`is_enabled=0` | 当天窗，`page_size=1`，`filters={}` | 10 | HTTP 200，空 `data.list`，无 `page_info` |
| 午间 | `12:20:28` 开，窗约 2h | `12:26:13`，`is_enabled=0` | 当天窗 + 近 1h 窗，`page_size=50`，`filters={}` | 12 | HTTP 200，空 `data.list`，无 `page_info` |

因此「凌晨低谷所以空」不再成立。在投放中的抖音 App `29034827` 上，前端默认当天窗和近一小时窗、前端默认 `page_size=50`，午间峰值仍无 item。

## 推测（不是事实）

- 列表很可能只在 `is_enabled=1` 且事件实际入库后才有行。开着开关不等于这条 list 立刻有数据。
- 未试非空 `event_name`。前端默认就是空筛选，所以这不是当前缺口的第一解释，但不能排除服务端在空 filters 下另有过滤。
- 投放中不等于这条入库路由有实时流量。其它分析面有数据，不能外推到 `analysis.realtime_event.list`。
- draft 合同没有登记 `data.list`，SDK 投影会把空 array 收成 `status=empty` 且看不到 list。协议层事实以 HTTP 200 + additive `/data/list` 为准。

## 因此确定了什么

- `analysis.realtime_event.list` 保持 `draft`。blocker 仍是 `empty_sample`、`pagination_unverified`、`response_item_schema_unverified`。
- 动线「查询实时事件目录」保持完全缺失。没有读产品，Core / CLI / SDK / Plan / Agent 读面未建。
- 不许把这 12 次空 list 登记成 item schema。
- 表头 `56 = 50 / 3 / 3` 不变：状态列未改。

## 评测题

本趟未闭环，题集现在仍然对得上，**不要改**。若以后真有读产品，`evals/agent_usability/cases/development.jsonl` 里 J35 五题都会对不上：

| case | 现在期待 | 闭环后应改成 |
|---|---|---|
| `J35.dev.zh.normal-1` | `gap_code=REALTIME_EVENT_CATALOG_CONTRACT_MISSING`，`route_key=realtime_event_gap`，`terminal_kind=capability_gap` | 命中新产品 selector，不再是目标 gap |
| `J35.dev.zh.normal-2` | 同上 | 同上 |
| `J35.dev.en.normal-1` | 同上 | 同上 |
| `J35.dev.zh.boundary` | 同上 | 同上；仍须与历史事件元数据搜索分开 |
| `J35.dev.en.missing` | 同上 | 不再要「取证 next_action」；应走产品缺参/空结果合同 |

## 追加：#199 开窗后等 50 分钟（2026-08-18 12:41）

权威记录见 [realtime-event-wait-duration.md](realtime-event-wait-duration.md)。本段只钉一条：同一 App `29034827` 上再开 2h 窗（读回 `12:40:37..14:40:37`，`modify_time=2026-08-18 12:41:37`），固定前端当天窗 `filters={}` `page_size=50`，在开窗后 2 / 5 / 10 / 15 / 20 / 30 / 40 / 50 分钟各读一次，8/8 HTTP 200、空 `data.list`、无 `page_info`。随后窗仍开着补 `filters.event_name=microgame_window_click` 与 `filters.event_type=track`，仍空。已关回 `is_enabled=0`，`modify_time=2026-08-18 13:33:34`。

**开窗后持续 50 分钟、8 个时间点 + 2 种非空 filters 仍空，入库延迟假说不成立。** 状态列保持完全缺失；表头 `56 = 50 / 3 / 3` 不要动。
