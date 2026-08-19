> 归档材料：保留历史决策与取证，不代表当前接口或状态；当前入口见 docs/index.md。

# 分析查询 metadata 预取成本

- 日期：2026-08-18
- 任务：#210
- 结论：进程内 10 分钟 metadata cache 已经存在且会命中；#206 报的「各 30 HTTP」是默认 `page_size=100` 的分页，不是缺缓存。

本趟是测量任务。全部生产读在 App `29034827`。写 0。未碰实时事件、导出、agent 路由。

## 四问

### 1. 一次典型 analysis query 发多少次 HTTP？

**确凿（离线夹具 + 生产）：**

| 形状 | 冷启动 HTTP | 同进程第 2 次 | 各是什么 |
|---|---|---|---|
| 事件查询，只用固定字段 `PresetAllCount` / `create_time` | 3 | 1 | `analysis.event.list` + `analysis.event_property.list` + `analysis.event.query` |
| 同上，再按 `$os` 用户分维 | 冷启动多 1 | 1 | 再加 `analysis.user_property.list` |
| 留存，只用固定字段 | 冷启动 3；同进程已有 event/property 快照时 1 | 1 | 预取同事件查询；真查询是 `analysis.retention.query` |

漏斗与事件/留存走同一条 `validate_analysis_query` → `validate_analysis_reference_membership`。未单独打漏斗生产请求。

**确凿（代码）：** 预取不是调用方显式发的。`client.read(analysis.*.query)` → executor FieldPolicy → `_load_field_metadata` → `_read_all_untracked`（`page=1, page_size=2000`）。用途是校验物理事件名和属性名是否存在，不是合同投影。

### 2. 预取是每次都发，还是已有缓存没命中？

**确凿：** 进程内 `MetadataCache` 早就在 `client._execute_result` 上，TTL 600s，key=`(operation_id, JSON(规范化 inputs))`。只缓存 `is_metadata_operation()` 允许的 list/get。业务 query 不进 cache。

生产同进程（2026-08-18，App `29034827`）：

| 步 | HTTP | cache hits/misses | 说明 |
|---|---|---|---|
| `event.list` page_size=1 | 1 | 0/1 | 单独探测，key 含 `page_size=1` |
| `event.list` page_size=2000 | 1 | 0/2 | 与上一行不同 key |
| `event_property.list` page_size=2000 | 1 | 0/3 | |
| `user_property.list` page_size=2000 | 1 | 0/4 | |
| 事件查询 1 | 1（只有 query） | 2/4 | FieldPolicy 命中刚写入的 2000 页快照 |
| 事件查询 2 | 1 | 4/4 | 元数据全命中 |
| 事件查询 3（`$os` 分维） | 1 | 7/4 | 再命中已有 user_property 快照 |
| 留存查询 | 1 | 9/4 | 元数据全命中 |

合计 **8 次读 / 预算 25**。第 5–8 步的 `pagination_audit`/`count_http_requests` 均为 1。

**#206 的「各 30」怎么来的（确凿 + 推断分栏）：**

- **确凿：** FieldPolicy 用 `page_size=2000`。该 App 上 `event.list` 共 119 项：`page_size=1` 时 `total_pages=119`；`page_size=2000` 时 `total_pages=1`。`event_property.list` 224 项 / 1 页，`user_property.list` 113 项 / 1 页。
- **推断：** 若某次测量用合同默认 `page_size=100` 再 `read_all`，119 项 ≈ 2 页，到不了 30。30 页更像默认 100、目录约 3000 项，或把多条 query 的分页加总后写成「各 30」。本趟未复现 30。不是 cache key 不稳——同 inputs 第二次必中。

CLI 每次新进程，cache 带不走。Agent 若每问起一个进程，看起来就像「每次都预取」。

### 3. 预取是必需的吗？

**确凿：** 是 FieldPolicy 成员校验，不是投影。

- 有 `event_name` → 拉 `analysis.event.list`，核对 name。
- 有事件字段（含固定字段 `PresetAllCount`/`create_time`）→ 再拉 `analysis.event_property.list`。
- 只有固定字段不在全局 list 里时才再拉 `analysis.event.info`（按事件）。
- 有用户字段/用户分维 → `analysis.user_property.list`。
- 有分群引用 → `analysis.segment.list`（本趟未打）。

`client.validate()` 只声明 `live_metadata_dependencies`，不联网。真正 `read`/`analysis_query` 才会预取。缓存的是元数据快照，每次仍用快照做校验。

### 4. 同进程连发第 2..N 次还会重复预取吗？

**确凿：不会**，只要 App、page/page_size、TTL 未过、没 `clear`、没 bypass。换用户分维只会多打一次尚未缓存的 `user_property.list`。新进程、`clear_metadata_cache`、`bypass_metadata_cache(True)`、成功 mutation 清 cache、TTL 到期，会再预取。

## 本趟改动

没有新建第二套 cache。补的是调用方可观察、可关闭：

- `metadata_cache_stats(client)` / `GravitySDK.metadata_cache_stats()`
- `clear_metadata_cache(client)`
- `bypass_metadata_cache(client, True|False)`

stats 只有 `ttl_seconds/entries/hits/misses/bypassed`，不含 snapshot 值。bypass 跳过复用，不改 FieldPolicy，也不改合同。成功 mutation 仍清 cache。

未改 `client.py`（AST 6764/6765）。未改质量 `hard_limit` / `threshold` / `max_`。未改评测装置。

## 推测（不是本趟事实）

- 长期进程里 10 分钟 TTL 可能让调用方用到刚新增的事件/属性之前的快照。要最新元数据就 `clear` 或 `bypass`。本趟未测 TTL 到期。
- 把 FieldPolicy 的 `page_size` 从默认 100 改成调用方可控，能避免「各 30」那种分页放大；那是分页策略，不是 cache 缺口。本趟不改预取 page_size。
