# 超限导出 `truncated` 生产确认

- 日期：2026-08-18
- 任务：#205
- 结论：修后的变现超限导出在生产上报了 `truncated`；同日用户明细对照仍是 `complete`。

## 生产预算

- 导出 create：2 次（1 超限变现 + 1 用户明细小切片）。
- 读：3 次（变现两列 list 预检 1 + create 内 pin 1 + 用户明细 list 预检 1）。poll / download 不计。
- 写：0。未碰实时事件路由。
- 未改分类判据、未改阈值、未改评测装置。

## 确凿事实

### 1. 超限变现导出：信封是 `truncated`

请求：`export.analysis.monetization_detail.start`，投放中抖音 App `29034827`，`create_time` 单日 `2026-08-16`，`field_map={AdEventTime, ClientID}`。走完整 `export run`（create→poll→download→validate）。

| 项 | 值 |
| --- | --- |
| job_id | `36e378a30c44446bb40a65be7e28be60` |
| `state` | `COMMITTED` |
| `completion_status` | `truncated` |
| `file.rows` | 1,000,000 |
| `completeness.known_total_items` | 13,497,923 |
| `known_total_freshness` | `create_time_preflight` |
| `known_total_source` | `analysis.monetization_detail.list.page.total_items` |
| `known_total_binding` | `same_app_and_create_time_day_as_export_create` |
| `truncated` / `complete` | true / false |
| `missing_rows` | 12,497,923 |
| `row_limit` | 1,000,000 |
| 文件大小 | 22,081,051 bytes |

create 前另发一次同形状 list 预检（`fields=["AdEventTime","ClientID"]`，`page_size=1`）：`page.total_items=13,497,921`。与 create 时 pin 的 13,497,923 差 2 行，量级同为约 1,350 万，不是 26 列产品字段那次的 19,196。

`#trust-sweep` 同条件两列 list 是 13,497,911。本轮数字不同，量级相同。

### 2. 小切片对照：用户明细仍是 `complete`

请求：`export.analysis.user_detail.start`，同 App，单日 `2026-08-16`，`field_map={ClientID, CreateTime}`。

| 项 | 值 |
| --- | --- |
| job_id | `cb842d6076ff46eda28a9c132c45e934` |
| `state` | `COMMITTED` |
| `completion_status` | `complete` |
| `file.rows` | 4,556 |
| 同条件 list `page.total_items` | 4,556 |
| `completeness` | 空（该族不走 monetization pin） |

`file_rows == list.total_items`，未触顶。正常路径没有被超限分类带坏。

## 因此确定了什么

- pin 已按导出自己的 `field_map` 两列预检；分母是千万量级，分类器可以报 `truncated`。
- `create_time_preflight` 标注还在；丢钉修复没有回退。
- 判据未改：触顶且已知总量大于文件行数才是 `truncated`；原子提交且 `file_rows == pinned_total > 0` 且未触顶才是 `complete`。

## 推测（不是事实）

- 预检 13,497,921 与 pin 13,497,923 的 2 行差，更像两次读之间上游计数微变，不是列集又钉错。未再发第三次 list 对账。

## 没改什么

- 不改 `completion_status` 分类逻辑。
- 不改评测装置、题集、评分、阈值；不跑 holdout / final。
- 不动 `docs/roadmap.md`。
- 导出动线状态仍是部分闭环：宽问法冻结 gap `ANALYSIS_EXPORT_FILE_CONTRACT_MISSING` 不变。
