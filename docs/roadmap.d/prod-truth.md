# 生产数字对账：七类一致性

- 日期：2026-08-18
- 任务：#194
- 结论：专家手填路径上，可加指标的分页、分维、时间窗和跨 route 数字对得上；Agent 默认不填参、不解析相对日期，分析师现在不能只靠自然语言走完全程。

全部在投放中抖音 App 上做。窗口默认 `2026-08-14..2026-08-16`（闭区间，Asia/Shanghai）。下面只写关系，不写业务数字表。

## 发请求前写下的预期

1. 分页拼接 = 上游声明总数。不成立说明 SDK 丢页或上游 total 撒谎。
2. 分维度求和 = 不分维度总计。指标选次数类 `AppRealRegisterCnt` / `reporting_ad_cnt` / `reporting_ad_revenue`，不是 UV。不成立说明投影丢行或指标其实不可加。
3. 大窗可加指标 = 子窗之和。不成立说明日期边界或时区错。
4. Agent 填参 vs 专家手填，同一事实两个数相等。不等就去看口径/日期/默认筛选。
5. 归因注册 vs 事件注册：允许不等，但必须能指出口径差。
6. 导出 `file_rows == pinned_total` 且 `complete`；超限必须报 `truncated`。
7. 「昨天」「最近 7 天」最终发出的 `start`/`end` 必须是上海日历上的那两天。

## 确凿事实

### 1. 分页拼接 = 上游声明总数 — 成立

- 请求：`analysis.event.list`，`page_size=7`，`--all-pages --max-pages 50 --max-items 2000`。
- 响应：`page_info.total_number=117`，`total_page=17`，`result.page.item_count=117`，`pages_fetched=17`，`pagination_audit.completeness.status=complete`。
- `117 = 16*7 + 5`，边界页露出来了，item 数等于声明总数。

附带观察：`pagination_audit.http_requests_made=1`，但 `result_audit.http_receipts` 有 17 条。审计把 resolver 收据的 `request_count` 当成 HTTP 次数，不是真实分页 HTTP。数字对账仍成立，审计字段不可信。

### 2. 分维度求和 = 不分维度总计 — 成立（挑对可加指标之后）

认定可加的依据：`AppRealRegisterCnt`、`reporting_ad_cnt`、`reporting_ad_revenue` 是次数/金额，不是 UV。

归因 `attribution.attribution.query`，`AppRealRegisterCnt`，`user_activated_time`，窗 `2026-08-14..2026-08-16`：

| 形状 | 行求和 vs `total` |
| --- | --- |
| `dims_list=["date"]` | 三日行之和 = `total` |
| `dims_list=["ad_platform"]` | 平台行之和 = 同一 `total`（上游实际仍按 date+platform 拆，6 行） |
| `dims_list=["date","ad_platform"]` | 6 行之和 = 同一 `total` |

变现 `report.get.query`，`reporting_ad_cnt` + `reporting_ad_revenue`：

| 形状 | 结果 |
| --- | --- |
| `time_dims=day` 且 `data_dims=["monetization_platform"]` | 三行之和 **小于** `total`。事先预期是相等。 |
| 同窗再拆：`time_dims=day` 且无平台维 | 三日行之和 = `total` |
| `time_dims=total` 且带平台维 | 平台行之和 = 同一 `total`（含一个空平台值行） |
| `time_dims=total` 且无任何 `data_dims` | 上游 `INPUT_INVALID` |

所以「分维求和 ≠ 总计」在变现上成立过一次，原因不是指标不可加，而是 `day + monetization_platform` 这一组合漏了空平台值那一行。去掉平台维或改 `time_dims=total` 后对上。SDK 没有告诉调用方「这个维度组合会丢一行」。

`agent-catalog describe report.get.query` 的 input schema 比 `operations describe` 瘦：前者没有 `time_dims`/`data_dims`/`item_enum`。按目录卡手填会踩指标 allowlist。

### 3. 时间窗可加性 — 成立

同一归因请求、同一指标、同一口径：

- `2026-08-14..2026-08-16` 的 `total`
- = `2026-08-14..2026-08-14` 的 `total` + `2026-08-15..2026-08-16` 的 `total`

事件分析 `$UserFirstRegister` / `PresetAllCount` / `time_grain=day`：三日分项之和 = 响应里的「阶段总和」。

事件分析 `time_grain=total` 编译成 `group_by=total`，上游返回空 `{}`，没有阶段总和。这不是日期边界错，是这个 grain 在本租户上不产数。省略 `time_grain` 则编译失败。

### 4. Agent 填参 vs 专家手填 — 三组都没走出 A 路出数

`gravity agent --input` 完全离线，不执行查询。

| 组 | 业务问题 | Agent | 专家手填 |
| --- | --- | --- | --- |
| 4a 归因注册 | 「…归因真实注册数」+ 明确日期 | `NO_CANDIDATE`。改成文档问法「查询归因表现聚合」才命中 `composite:attribution_performance`，但 `missing=['app','start','end']`，日期占位符未填 | `gravity attribution performance --app … --start 2026-08-14 --end 2026-08-16` 与 raw `attribution.attribution.query` 同一画像同一 `total` |
| 4b 事件次数 | 「…$AppRegister 事件次数」 | 命中 `analysis.query.spec:event`，模板里的 start/end/event 都是占位符 | 同一 spec 手填，数稳定 |
| 4c 变现 | 「…变现广告展示次数和收入」 | 命中通用 `analysis.task.handoff`，不是 `report.get.query`。文档问法「按平台、广告位和日期汇总变现结果」才命中 `report.get.query`，仍缺 `date_list`/`metrics_list` | 手填 `reporting_ad_cnt`/`reporting_ad_revenue` 出数 |

因此没有「两个数」可对。不是口径被悄悄换了，是 Agent 根本不出数。分析师必须自己读合同填参。`--resolve-inputs` 对归因卡报「没有在线 input catalog」。

### 5. 跨 route 同一事实 — 成立，且口径差说得清

事先允许不等。实测：

- 归因 `AppRealRegisterCnt`（`user_activated_time`）三日 `total`
- = 事件分析 `$UserFirstRegister` / `PresetAllCount` 三日「阶段总和」
- ≠ `$AppRegister`（大约小一个数量级）
- ≠ 归因 overview 里的 `AppRegisterStandard`（更小）

`$UserFirstRegister` 才是归因「真实注册」对应的事件。`user_activated_time` 与 `behavior_occurred_time` 在这三日窗上得到同一 `AppRealRegisterCnt` 分日序列，不能推广到别的窗。

用户明细列表 `2026-08-16` 的 `page.total_items` = 当天 `$UserFirstRegister` 次数。这是第三条独立路径。

### 6. 导出文件行数 = 钉住总量 — 小切片成立；超限切片当时不诚实

两次 create，都在修完 `--columns` 代码/表头分裂之后发出。

1. `export.analysis.user_detail.start`，单日、与列表同一条件。
   - 列表第一页钉住 `total_items` 与文件 `rows` 相等。
   - `completion_status=complete`，`COMMITTED`。
   - 用户明细这条不走 monetization 的 pin 函数，靠文件行数自身判 complete。
2. `export.analysis.monetization_detail.start`，同 App 同日。
   - 列表第一页 `total_items` 已过百万上限。
   - 文件恰好 1,000,000 行、`COMMITTED`。
   - 信封是 `completion_status=partial`，`completeness` 为空，**没有**报 `truncated`，也没有给出已知总量。

原因（代码，已修，本轮不再重发 create）：`export run` 轮询 `status` 时用无 completeness 的新 snapshot 覆盖 create 时钉住的总量。`classify_export_rows` 拿到 `None` 就放弃比较。修后的单测：`test_poll_keeps_create_time_preflight_total` 红→绿。

另修一处才能发出这两次 create：`export run` 拿文件表头去校验 `--columns` 的请求代码，`describe` 示例用的 `ClientID,CreateTime` 会被拒。修后的单测：`test_export_run_accepts_describe_request_column_codes` 红→绿。

`export.analysis.origin_event.evaluate` 在 export 合同里 `executable=true`，但 `gravity run` 报 `UNKNOWN_OPERATION`。没有独立 CLI。本轮没走 origin_event create。

### 7. 自然语言窗口解析 — 不成立（根本没解析）

- `gravity analysis query --start yesterday --end yesterday`：本地 `INPUT_INVALID`，只接受 ISO 日期。
- `gravity agent "昨天的归因表现"` / `"最近 7 天的归因表现"`：命中产品卡，start/end 仍是 `<start:YYYY-MM-DD>` 占位符，卡片里没有 `2026-08-17` 或任何具体日期。
- `"昨天的事件趋势"`：误命中三条 metadata 枚举，不是事件分析。
- `"最近 7 天的事件趋势"`：命中事件卡，日期仍是占位符。

没有发出带相对日期的生产查询。SDK 不把「昨天」编译成上海日历日。

## 推测

- 变现 `day + monetization_platform` 漏空平台值，可能是上游按「有平台值」切片，空平台值只进 `total`。未再打别的维度证实。
- `time_grain=total` 空结果可能是该 grain 在事件分析上本就不返回标量。未穷尽其他事件。
- Agent 对「归因真实注册数」`NO_CANDIDATE`，是识别器词表过窄（要「表现/汇总/聚合」），不是产品不存在。

## 生产请求预算

读：远低于 150。导出 create：2（另有 2 次因 `--columns` 校验死在本地，未发上游）。写：0。未碰实时事件 route。

## 修了什么

1. `export run` 把文件表头当成 `--columns` 允许值。
   - 红：`test_export_run_accepts_describe_request_column_codes` 收到 `requested export columns violate the privacy contract`。
   - 绿：同一测试，create 被调用。
2. 变现导出轮询丢掉 create 时钉住的总量。
   - 红：`test_poll_keeps_create_time_preflight_total`，`result.completeness is None`。
   - 绿：同一测试保留 `known_total_items` 与 `create_time_preflight`。
   - 本轮超限文件仍是修前发出的，信封保持 `partial`。

## 没修什么

- Agent 不填日期/指标、相对词不解析：改动大，且评测题集冻结在「不自动执行」。
- `agent-catalog describe` 与 `operations describe` 对 `report.get.query` 合同不一致：要动目录投影，超出本趟对账。
- `pagination_audit.http_requests_made` 低估：可用性，不影响 item 对账。
- 变现空平台值行、事件 `time_grain=total` 空：更像上游语义，证据不够改合同。
- `export.analysis.origin_event.evaluate` 不能 `gravity run`：要给 export_status 单独入口，本趟预算不开第三条 create。
