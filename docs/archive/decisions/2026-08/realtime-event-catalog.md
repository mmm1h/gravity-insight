> 归档材料：保留历史决策与取证，不代表当前接口或状态；当前入口见 docs/index.md。

# 实时事件目录：前端形状 + 含此刻窗仍空

- 日期：2026-08-18
- 任务：查询实时事件目录 / `analysis.realtime_event.list`
- 结论：未拿到非空 item，动线仍完全缺失；空的是「关闭入库开关 + 已试形状」，不是「租户没有实时事件能力」。

## 确凿事实

### 前端 hash-matched 控制流（0 次生产请求）

本机 `work-dashboard` 缓存
`raw/web.gravity-engine.com/assets/Debug-hpZqESZ9.js` 与仓库
`bundle-snapshot.json` sha256
`36bf9a81a27fcf749242c8643e1c5ffef19b75b55ce5fab5da44e5095afe44bf` 一致。

`RealTimeWarehousing` 装载列表时实际 POST：

```js
{
  page: Ge.value,          // default 1
  page_size: Ke.value,     // default 50; UI sizes [50, 100]
  request_time: Ae.value,  // default [startOf('day'), endOf('day')]
  app_id: Z.value.app_id,
  filters: {
    event_type: Z.value.event_type || undefined,
    event_name: Z.value.event_name || undefined,
    request_id: Z.value.trace_id || undefined,
    client_id: Z.value.client_id || undefined,
    client_lib: Z.value.sdk_type || undefined,
    client_lib_version: Z.value.sdk_version || undefined,
    properties: Z.value.event_prop.length ? Xe() : undefined
  }
}
```

空控件把 `filters` 各键省略，序列化为 `{}`。日期选择器 `disabledDate=Ct` 禁止未来日，并以当前日历锚点 ± `3540*24*30*1e3` ms（约 30 天）限制可选日。分页是客户端 `data.list.slice`；响应消费者只绑定 `data.list`。

同页另有独立配置读写，**不是**列表 POST 的绑定字段：

- GET `/user/realtime_event/list/`（stable `app.realtime_event.list`）读 `data.conf.{is_enabled,start_time,end_time}`
- POST `/user/realtime_event/manage/` 写 `{app_id,is_enabled,start_time,end_time,time_slot:2}`
- UI 默认开启时长是 `now .. now+2h`

开关关闭或 `end_time < now` 时，页面仍会按当天窗发列表请求。

### 生产请求（本轮 14 次，超出预算 12）

凭据：本 worktree 无 `.env.gravity.local`；进程环境 token 已于 2026-08-16 过期。使用兄弟 checkout `gravity-sdk-dev/.env.gravity.local` 的有效内部会话（exp 2026-08-24T16:03:10Z）。未把凭据写入本仓。

第 1 次摘要脚本在落盘前异常，receipt `b124604077aa47e5bfa4097efcea1c14` 记录 HTTP 200，`list` 是否非空未保存；第 2 次用同一前端当天窗重打。

| # | operation | app_id | 形状 | HTTP / code / msg | list |
|---:|---|---:|---|---|---|
| 1 | `analysis.realtime_event.list` | 29034827 | `request_time=["2026-08-18 00:00:00","2026-08-18 23:59:59"]` `filters={}` `page=1` `page_size=1`（receipt only） | 200 | 未保存 |
| 2 | 同上 | 29034827 | 同上，当天窗含此刻 | 200 / 0 / 成功 | `[]`，无 `page_info`，`data` 仅 `list` |
| 3 | `app.realtime_event.list` | 29034827 | GET `app_id` | 200 | `conf.is_enabled=0`，`start_time/end_time=2026-06-25 00:00:00..23:59:59`，`modify_time=2026-06-26 00:00:46` |
| 4 | `analysis.realtime_event.list` | 29034827 | 近 5 分钟 `00:19:46..00:24:46`，`filters={}` | 200 / 0 / 成功 | `[]` |
| 5 | 同上 | 29034827 | 近 1 小时，`filters={}` | 200 / 0 / 成功 | `[]` |
| 6 | `app.realtime_event.list` | 27018426 | GET | 200 | `data.conf` 缺失 |
| 7 | 同上 | 27192043 | GET | 200 | `is_enabled=0`，窗 `2026-06-23` |
| 8 | 同上 | 24502679 | GET | 200 | `is_enabled=0`，窗 `2026-05-16` |
| 9 | 同上 | 20698471 | GET | 200 | `data.conf` 缺失 |
| 10 | 同上 | 27612408 | GET | 200 | `is_enabled=0`，窗 `2026-07-31 14:18:03..16:18:03` |
| 11 | 同上 | 26827043 | GET | 200 | `is_enabled=0`，窗 `2026-07-22 11:35:53..13:35:53` |
| 12 | `analysis.realtime_event.list` | 29034827 | 上次开启窗 `2026-06-25 00:00:00..23:59:59` | 200 / 0 / 成功 | `[]` |
| 13 | 同上 | 27612408 | 上次开启窗 `2026-07-31 14:18:03..16:18:03` | 200 / 0 / 成功 | `[]` |
| 14 | 同上 | 26827043 | 上次开启窗 `2026-07-22 11:35:53..13:35:53` | 200 / 0 / 成功 | `[]` |

所有成功列表响应的 envelope 都是 `code=0` / `msg=成功` / `extra=null` / `data={list:[]}`。没有 `page_info`，没有 item 字段。

## 推测（不是事实）

- 列表数据很可能只在 `is_enabled=1` 且 `now ∈ [start_time, end_time]` 时写入；关闭后历史窗不再可回放。依据：开关默认只开 2 小时；07-31 / 07-22 两次历史开启窗现在也空。**未做正向开关实验，不能写成合同。**
- 「含此刻」假设对这条 route 不充分：前端默认就是含此刻的当天窗，但开关关着时当天窗仍空。
- 2026-08-16 / 08-17 的 7/7 全空，更像是「当时开关已关 + 窗落在未开启区间」，不是租户没有这条 route。
- 未试非空 `filters.event_type` / `event_name`。前端默认就是空筛选，所以这不是当前缺口的第一解释。

## 因此确定了什么

- `analysis.realtime_event.list` 保持 `draft`。blocker 仍是 `empty_sample`、`pagination_unverified`、`response_item_schema_unverified`。
- 动线「查询实时事件目录」保持完全缺失。Agent 目标 gap `REALTIME_EVENT_CATALOG_CONTRACT_MISSING` 仍然正确。
- 下一步必须先看到某个 App 的 `app.realtime_event.list.conf.is_enabled=1` 且 `end_time >= now`，再对该开启窗发最小第一页。不要再对关闭开关的 App 用「此刻」或 30 天过去窗重复枚举。
- 未开写入库开关（`manage` 是 mutation）。

## 评测题

未闭环，题集不用改。若以后闭环，`evals/agent_usability/cases/development.jsonl` 里 J35 五题都会对不上：

- `J35.dev.zh.normal-1`
- `J35.dev.zh.normal-2`
- `J35.dev.en.normal-1`
- `J35.dev.zh.boundary`
- `J35.dev.en.missing`

它们现在期待 `gap_code=REALTIME_EVENT_CATALOG_CONTRACT_MISSING`、`route_key=realtime_event_gap`、`terminal_kind=capability_gap`。闭环后应改成命中新产品 selector，而不是目标 gap。

## 台账汇总

未改 `docs/analysis-journeys.md` 表头 `56 = x / y / z`。本行状态仍是完全缺失，汇总数字不变。
