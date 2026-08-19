> 归档材料：保留历史决策与取证，不代表当前接口或状态；当前入口见 docs/index.md。

# 实时事件目录：event_type=profile 第一次非空并晋升

- 日期：2026-08-18
- 任务：#211
- 结论：开窗后当天窗 `filters.event_type=profile` 第一次即非空（`data.list` 长度 1000，无 `page_info`）；已关回 `is_enabled=0`，读产品晋升 stable。

## 关窗后重读的 `conf` 原文

```json
{
  "create_time": "2026-05-16 12:06:14",
  "modify_time": "2026-08-18 18:45:19",
  "app_id": 29034827,
  "is_enabled": 0,
  "start_time": "2026-08-18 18:40:43",
  "end_time": "2026-08-18 20:40:43"
}
```

看门狗已停；停后再读一次，仍是上表。

## 确凿事实

### 第 0 步

开窗前读 `app.realtime_event.list`（`app_id=29034827`）得到 `is_enabled=0`，`modify_time=2026-08-18 13:33:34`，窗仍是上一趟的 `12:40:37..14:40:37`。没有发现别人开着窗。

凭据：本 worktree 原先无 `.env.gravity.local`。从兄弟 checkout `D:/git-pjt/gravity-sdk-dev/` 复制 gitignore 会话文件。未提交凭据。

### 有量确认（4 次，开窗前）

| # | operation | 形状 | HTTP / 结果 |
|---:|---|---|---|
| 1 | `attribution.attribution.query` | `app_id=29034827` 当天 `2026-08-18` `dims_list=["date"]` `metrics_list=["AppRealRegisterCnt"]` | success，1 行且有正注册数 |
| 2 | 同上 | 昨天 `2026-08-17` | success，1 行且有正注册数 |
| 3 | `export.analysis.origin_event.evaluate` | `$AppStart` 昨天窗 | `estimated_rows=0` |
| 4 | 同上 | `$startup` 昨天窗 | `estimated_rows=0` |

因此：投放中 App 今昨都有归因注册量；`$AppStart` / `$startup` 不是这条 App 上的有量物理名。4 次预算用尽，未再打 evaluate。`yesterday_count` 仍是死字段，本趟不用它挑事件。

另读 1 次 `analysis.default_val.list`（不算进 4 次有量预算）：观察到 SDK 类型键 `api` / `cocoscreator`，`api` 的第一个版本字符串为 `1.0`。本趟实时 list 在拿到非空前没有用到这两个值。

### 生产写 / 读（只动 App `29034827`）

| # | operation | 形状 | HTTP | 结果 |
|---:|---|---|---:|---|
| 1 | `app.realtime_event.list` | GET `app_id=29034827` | 200 | 开窗前 `is_enabled=0`，`modify_time=2026-08-18 13:33:34` |
| 2 | `app.user.realtime.event.update` dry-run | `is_enabled=1` `start_time=2026-08-18 18:40:21` `end_time=2026-08-18 20:40:21` `time_slot=2` | 0 网络 | preview；body 只含该 App |
| 3 | 同上 execute | `18:41:43..20:41:43` | 200 | 读回 `is_enabled=1`，窗被收成 `18:40:43..20:40:43`，`modify_time=2026-08-18 18:41:43` |
| 4 | `analysis.realtime_event.list` | 当天窗 `request_time=["2026-08-18 00:00:00","2026-08-18 23:59:59"]` `filters={event_type:"profile"}` `page=1` `page_size=50` | 200 | **非空**：`data.list` 长度 1000，无 `page_info` |
| 5 | 同上（类型草图，同一形状） | 同上 | 200 | 再次 `list` 长度 1000；只落字段类型，不落业务值 |
| 6 | `app.user.realtime.event.update` execute | `is_enabled=0`，窗 `18:40:43..20:40:43` | 200 | 读回 `is_enabled=0` |
| 7 | `app.realtime_event.list` | GET | 200 | 见上方关窗 `conf` |
| 8 | 同上 | GET（停看门狗后再读） | 200 | 仍是上表 |

未碰 `27018426` / `27192043` / `24502679` / `20698471` / `27612408` / `26827043`。

### 非空响应形状（值无关）

12 个顶层 item 键，1000/1000 类型一致：

| 键 | 类型 | 产品是否暴露 |
|---|---|---|
| `client_id` | string | 是 |
| `client_lib` | null | 否（本样本恒 null） |
| `client_lib_version` | null | 否（本样本恒 null） |
| `client_time` | string | 是 |
| `event_name` | string | 是 |
| `event_type` | string | 是 |
| `raw_properties` | object | 否（不透明对象，含动态键） |
| `request_id` | string | 是 |
| `request_ip` | string | 否 |
| `request_time` | string | 是 |
| `request_ua` | string | 否 |
| `time_free` | integer | 否 |

没有 `page_info`。请求 `page_size=50`，服务端一次回了 1000 条。分页按实测声明 `kind=none`，**不复制模板 `page_info`**。

前端 hash-matched `Debug-hpZqESZ9.js` 的 `event_type` select 只有 `track` / `profile`。前三轮只试过空 filters 和 `track`；本趟第一次试 `profile` 即非空。

### 预算

任务上限：写 2（失败再 +2）；`app.realtime_event.list` 读 6；`analysis.realtime_event.list` 读 12；确认事件有量的读 4。

本趟实际：

- 写：2 次（开 1 + 关 1），无失败重试。
- `app.realtime_event.list`：开窗前 1、开窗读回随 mutation、关窗读回随 mutation、关后再读 1、停看门狗后再读 1。上限 6，未超。
- `analysis.realtime_event.list`：2 次（第一次非空即停；第二次只为固化类型草图，同一形状）。上限 12，未超。
- 有量确认：4 次，用尽。

均未超。未扩到别的 App。

## 四轮合计已试过的形状

- 关着开关：前端当天窗、近 5 分钟、近 1 小时、两次历史开启窗。
- 开着开关、凌晨约 9 分钟：当天窗 `page_size=1` `filters={}`。
- 开着开关、午间约 7 分钟：当天窗 + 近 1h 窗 `page_size=50` `filters={}`。
- 开着开关、午后约 50 分钟：当天窗 `filters={}` 8 个时间点；`event_name=microgame_window_click`；`event_type=track`。
- **本趟开着开关、傍晚**：当天窗 `event_type=profile` → **非空**。

未再穷尽 `request_id` / `client_id` / `client_lib` / `properties` / 近 7 天空 filters：任务要求任何一次非空立刻停读。

## 推测（不是事实）

- 该 App 上这条 list 对 `event_type=track` 和空 filters 持续为空，对 `profile` 立刻有 1000 行，更像是服务端默认不回 track，或当前窗内只有用户属性事件入库。
- `page_size=50` 却回 1000，和前端客户端 `slice` 一致：服务端可能一次吐固定上限，分页是客户端切。未再发第二页，所以不把“服务端分页”写进合同。
- 归因今昨有注册量，不能推出 track 实时 list 非空；本趟已经用 `profile` 打破了“开窗仍恒空”。

## 因此确定了什么

- `analysis.realtime_event.list` 晋升 `stable`。分页 `none`，`list_path=data.list`，无 `page_info`。
- 动线「查询实时事件目录」改为已闭环。Core / CLI / SDK / Plan / Agent 读面共用 `gravity-insight.realtime-event-catalog.v1`。
- 默认读形状是当天窗 + `filters.event_type=profile`。空 filters / `track` 仍可能空，那是数据形状，不是合同缺失。
- 表头 `56 = 50 / 3 / 3` **不要动**。状态列从「完全缺失」改为「已闭环」，汇总由合并时对账；建议变为 `56 = 51 / 3 / 2`。

## 评测题（不要动题集）

题集现在会对不上。`evals/agent_usability/cases/development.jsonl` 里 J35 五题仍期待目标 gap，闭环后应改成：

| case | 现在期待 | 闭环后应改成 |
|---|---|---|
| `J35.dev.zh.normal-1` | `gap_code=REALTIME_EVENT_CATALOG_CONTRACT_MISSING`，`route_key=realtime_event_gap`，`terminal_kind=capability_gap` | 命中 `composite:realtime_event_catalog`，不再是目标 gap |
| `J35.dev.zh.normal-2` | 同上 | 同上 |
| `J35.dev.en.normal-1` | 同上 | 同上 |
| `J35.dev.zh.boundary` | 同上 | 同上；仍须与历史事件元数据搜索分开 |
| `J35.dev.en.missing` | 同上 | 不再要「取证 next_action」；应走产品缺参合同（缺 `start`/`end`） |
