> 归档材料：保留历史决策与取证，不代表当前接口或状态；当前入口见 docs/index.md。

# 为什么还没到 95%

- 日期：2026-08-18
- 任务：#gap-annotation
- 结论：分母仍是 56。已闭环 50/56 = 89.3%。4 条已证实在当前租户下不可达，1 条（实时事件目录）另有专门任务；当前租户数据下的上限是 52/56 = 92.9%。这些条件不在 SDK 侧。

台账指针：[分析动线台账](../../snapshots/analysis-journeys-2026-08-19.md#为什么还没到-95)。本文件只写缺口归因与解锁条件，不改口径、不改状态列、不重算表头汇总。

## 确凿事实

| 项 | 数 |
| --- | ---: |
| 产品动线分母 | 56（不改） |
| 已闭环 | 50 = 89.3% |
| 目标 | 95% = 至少 54/56 |
| 已证实不可达 | 4 |
| 另有专门任务在推 | 1（查询实时事件目录） |
| 其余未闭环 | 1（导出事件、分群、用户、付费或变现分析结果，部分闭环；不是本趟判定的租户不可达） |
| 当前租户数据下的上限 | 50 已闭环 + 1 导出 + 1 实时事件 = **52/56 = 92.9%** |

4 条不可达保持原状态列：D33/D34、D32 仍是部分闭环；F41、查找可用的媒体报表仍是完全缺失。做不到 ≠ 已闭环。

本趟**没有**新发生产请求。下列请求与响应均已落在既有证据文件，此处只做归因，不重测。

### 下钻非 Bytedance 平台的计划、组和创意表现（D33/D34）

阻塞归因：**上游无数据；上游无权限。**

| 已发请求 | 已拿响应 | 因此确定 |
| --- | --- | --- |
| `promotion.kuaishou.advertiser.list`，窗 `2026-03-01..2026-08-16` | HTTP 200 / `code=0` / `total_number=0` | 近半年窗快手广告主报表明确空，不是权限码。见 [permissions-campaigns-and-quality.md](permissions-campaigns-and-quality.md) |
| `promotion.kuaishou.campaign.list` 最小第一页 | HTTP 200 明确空，无 item schema | 快手计划子路径无投放行。见 [nonbytedance.md](nonbytedance.md) |
| `promotion.tencent.ad.list` 对声明父对象 | `code=2000` / `permission_unavailable` | route 可达，被上游拒绝；不再换父重试。见 [permissions-campaigns-and-quality.md](permissions-campaigns-and-quality.md) |
| 对投放中 App `29034827` 与快手分身 `27018426` 各 1 次 `attribution.attribution.query` + 1 次 `report.get.query`（窗 `2026-07-19..2026-08-17`） | `29034827` 归因仅 `bytedance`/`natural`；`27018426` 归因与变现均为明确空 | 这两个投放相关 App、该 30 日窗内没有可绑定的非 Bytedance `ad_platform`。见 [nonbytedance.md](nonbytedance.md) |

解锁条件（不在 SDK 侧）：

1. **上游无数据**：有人在快手真正起一次投放，使 `promotion.kuaishou.advertiser.list` / `campaign.list` 在合法窗内出现非空行。
2. **上游无权限**：有人为声明父对象开通腾讯创意层读权限，使 `promotion.tencent.ad.list` 不再返回 `code=2000`。

两条都满足之前，整条「计划/组/创意」链给不出闭环所需的非空 item schema。账号级腾讯广告主目录已经非空（`total_number=127`），不能拿来顶替 App 绑定的投放行。

### 深查各平台专属素材与创意（D32）

阻塞归因：**上游无数据。** 与 D33/D34 同一投放前提。

| 已发请求 | 已拿响应 | 因此确定 |
| --- | --- | --- |
| `material.tencent_asset_text_title.list`、`material.kuaishou_creative.list` 最小第一页 | HTTP 200 明确空，无 item schema | 专属素材子路径不晋升。见 [permissions-campaigns-and-quality.md](permissions-campaigns-and-quality.md) |
| 同上 4 次 D35/D28 前提反查 | 未给出 `tencent`/`kuaishou` 投放平台值 | 2026-08-18 未再打那两条空 route。见 [nonbytedance.md](nonbytedance.md) |

腾讯托管创意与 `material.tencent.list` 的既有非空合同仍成立，所以本行是部分闭环，不是完全缺失。

解锁条件（不在 SDK 侧）：有人在非 Bytedance 平台起投放并产出专属素材，使快手创意库或腾讯标题库出现至少一行可观察 item。抖音 App 归因只有 `bytedance`/`natural` 时，SDK 无法自造这些对象。

### 按表名或 App 查询数据表当前 schema、字段和版本（F41）

阻塞归因：**上游无数据；需上游人工动作。**

| 已发请求 | 已拿响应 | 因此确定 |
| --- | --- | --- |
| `metadata.data_table.list` 7 种形状（绑投放中 App `29034827` 整数/字符串、7 个 App、省略筛选、`name_like=dim_`、只发分页） | 7/7 HTTP 200 / `code=0` / `total=0` | 不是漏绑投放中 App。见 [f41-data-table.md](f41-data-table.md) |
| `metadata.data_table.detail`，父项取 `operation_log` 本页非 delete 的 32 位 `table_id` | `code=1004` / `table_id not exist` | 日志里的历史 id 不是活表。 |

解锁条件（不在 SDK 侧）：有人在 Web 上建一张当前仍存在的维度表。数据表是手建的；App 有投放不蕴含有表。本仓不自建 marker 表。

### 查找可用的媒体报表

阻塞归因：**需上游人工动作。**

| 已发请求 | 已拿响应 | 因此确定 |
| --- | --- | --- |
| hash-matched `GeneralImportAd-CKb38unY.js` | 空选择器变成 `undefined`，键被省略 | 省略 `ad_platform` 就是查全集，不是漏填。见 [media-report-ad-platform.md](media-report-ad-platform.md) |
| 对投放中 App `29034827` 发 11 次最小第一页（6 个平台值 × 多种 `app_id` 绑定 × 3 个窗） | 11/11 HTTP 200 / `code=0` / `list=[]` / `total_number=0` / `total.cost=null` | item schema 不成立。 |

该页是「通用媒体数据导入」。写入口是独立的 `/common/report_data/import/v2/`，下拉排除了 24 个原生平台。

解锁条件（不在 SDK 侧）：有人在 Web 上导入一份通用媒体消耗。有原生投放不等于本页有导入行。SDK 不能也不该替调用方写入这份数据。

### 查询实时事件目录（不是本趟的「做不到」）

本行仍是完全缺失，但**另有专门任务在推**。它计入 92.9% 上限里「还可以闭环」的那 1 条，不计入上面 4 条不可达。证据见 [realtime-event-catalog.md](realtime-event-catalog.md)。

## 推测（不是事实）

- 若另有租户或另有 App 的 D35 出现 `kuaishou`/`tencent`，D33/D34 与 D32 的「上游无数据」半边可能当场解除；「上游无权限」半边仍要看 `promotion.tencent.ad.list` 是否继续 `code=2000`。
- 媒体报表**可能**只返回手工导入行、不返回巨量原生投放。这是页面职责推断，服务端没有返回「该 App 无导入行」之外的区分信号。
- 导出那条部分闭环若按维护者另判收口，上限仍是 52/56；它不是租户真空，本趟不改它的状态列。

## 本趟明确没做

- 不改分母、不排除任何动线、不重算表头 `56 = 50 / 3 / 3`。
- 不改状态列。不改评测题集。
- 不读、不写 `docs/roadmap.md`。
- 生产 HTTP **0**。
