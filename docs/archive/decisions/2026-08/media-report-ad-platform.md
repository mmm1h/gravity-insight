> 归档材料：保留历史决策与取证，不代表当前接口或状态；当前入口见 docs/index.md。

# 媒体报表：枚举 ad_platform 仍空

- 日期：2026-08-18
- 任务：查找可用的媒体报表 / `report.media_report.list`
- 结论：未拿到非空 item；`report.media_report.list` 保持 `draft`。hash-matched bundle 证明省略 `ad_platform` 就是不筛选（查全集），不是“漏填导致空集”。

## 确凿事实

### 前端请求形状（0 次生产请求）

公开静态 GET 两次，hash 与 `bundle-snapshot.json` 一致：

| 文件 | sha256 | size |
| --- | --- | --- |
| `GeneralImportAd-CKb38unY.js` | `21961901fc606dbae4bfc432e0ab1272006435d1e4571ac3e95724b81a53424d` | 16724 |
| `index-D9HAN43D.js` | `aa67659c360861d73309b2f9ca93ac15d95d6b39a092912a32cb72b9f1662d6b` | 5890290 |

列表装载 body（`Ad` 组件 `Y()`）恒为：

```js
{
  ad_platform: I.value.ad_platform || undefined,
  app_id: I.value.app_id || undefined,
  start_date: I.value.dateRange[0],
  end_date: I.value.dateRange[1],
  page: z.value,
  page_size: U.value,   // 默认 10
  order_by: k.value     // 默认 []
}
```

因此：

- 空字符串选择器变成 `undefined`，JSON 序列化后**键被省略**。省略 `ad_platform` 就是不按平台筛选。
- 空 `app_id` 同样省略。
- 日期字段名是 `start_date` / `end_date`；默认窗是当天到当天。
- 没有合同漏掉的必填字段。

`AppSelect`（`index-D9HAN43D.js`）`modelValue` 类型为 `[Number, Array, String, null]`。单选时 `s.value = e`，`e` 来自 `app.list` 的 `id`；搜索用 `t.id.toString()`。选中后前端更可能发**整数** `app_id`，初始空值是 `""`。

页面文案是「通用媒体数据导入」。平台下拉的可选项是 `U`（`Vc`，约 100 个 `q.*` 枚举）减去本地排除表 `X`。`X` 含 `bytedance` / `tencent` / `kuaishou` 等 24 个原生平台——这只影响下拉，**不改**请求省略语义。`q.bytedance === "bytedance"`，其余取值同名字符串。

既有 `probe-read-confirmations.json` 已写：`app_id` 来自 `AppSelect`，`ad_platform` 来自有限平台选项，空选择转为 `undefined`。本轮与之一致。

### 本轮生产请求（业务 POST 11 次）

目标一律 `POST /turbo_engine/api/v1/common/media_report/list/`。
App 一律优先 `29034827`（甜甜旅行抖音版）。`page=1`，`page_size=1`，`order_by=[]`。
第 1 个 session 另有 1 次认证相关 HTTP；业务 POST 未超 12。

| # | `ad_platform` | `app_id` | 窗 | HTTP / `code` / `list` / `page_info.total_number` / `total.cost` |
| --- | --- | --- | --- | --- |
| 1 | `bytedance` | 字符串 `"29034827"` | `2026-07-17..2026-08-16` | 200 / 0 / `[]` / 0 / `null` |
| 2 | `bytedance` | 整数 `29034827` | 同上 | 200 / 0 / `[]` / 0 / `null` |
| 3 | `bytedance_std` | 整数 | 同上 | 200 / 0 / `[]` / 0 / `null` |
| 4 | `bytedance_star` | 整数 | 同上 | 200 / 0 / `[]` / 0 / `null` |
| 5 | `bytedance_dy_game` | 整数 | 同上 | 200 / 0 / `[]` / 0 / `null` |
| 6 | `bytedance` | 省略 | 同上 | 200 / 0 / `[]` / 0 / `null` |
| 7 | `gravity` | 整数 | 同上 | 200 / 0 / `[]` / 0 / `null` |
| 8 | `tiktok` | 整数 | 同上 | 200 / 0 / `[]` / 0 / `null` |
| 9 | `bytedance` | 整数 | `2026-08-18..2026-08-18`（前端默认当天窗） | 200 / 0 / `[]` / 0 / `null` |
| 10 | `bytedance` | 整数 | `2026-08-17..2026-08-18` | 200 / 0 / `[]` / 0 / `null` |
| 11 | `gravity` | 整数 | `2026-08-18..2026-08-18` | 200 / 0 / `[]` / 0 / `null` |

11/11 均为 `msg=成功`、`extra.error=""`（空字符串，不是“无数据”对象）、`data.list=[]`、`data.page_info` 回显 `{page, page_size, total_number:0, total_page:0}`、`data.total={cost: null}`。无 4xx/5xx，无语义拒绝。

未再发：一年窗、其余 80+ 个选择器可见平台、其余 6 个 App。预算到 11 次业务 POST 停止。

### 因此确定

1. 省略 `ad_platform` **就是查全集**。上一轮无平台筛选的空结果，不能再用“漏填平台”推翻。
2. 在投放中的 `29034827` 上，显式 `bytedance` / `bytedance_std` / `bytedance_star` / `bytedance_dy_game` / `gravity` / `tiktok`，字符串或整数 `app_id`，以及前端默认当天窗，仍然明确空。
3. item schema 仍不成立。`empty_sample` 与 `response_schema_unverified` 保持 open。不晋升、不建产品。

## 推测（不是事实）

这条 route 的页面是「通用媒体数据导入」，表格列是导入消耗行（`advertiser_id` / `campaign_id` / `adgroup_id` / `app_id` / `ad_platform` / `cost`），写入口是独立的 `/common/report_data/import/v2/`。下拉还把 `bytedance` 等原生平台从选项里拿掉。

**可能**它只返回手工导入的通用消耗，不返回巨量原生投放报表。若如此，甜甜旅行抖音版有投放，也解释得通为什么本 route 仍空。这是页面职责推断，服务端没有返回“该 App 无导入行”之外的区分信号。

未证明的还有：更长历史窗、选择器里其余平台、非 `29034827` 的 App 在带平台筛选时是否非空。那些不再用“漏填 `ad_platform`”当理由。
