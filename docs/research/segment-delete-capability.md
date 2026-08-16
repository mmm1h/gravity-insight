# 分群删除能力调查

调查日期：2026-08-16
代码基线：`codex/segment-delete-probe@1a7663c`
生产请求预算：30；实际：14

## 结论

平台可以删除分群。它没有独立的 `DELETE` 方法或 `/segment/delete/` 路径，而是复用：

```text
POST /report/api/v3/dataanalysis/segment/save/
```

删除请求由 `action: "DEL"` 表示；同一路由用 `action: "UPDATE_NAME"` 更新名称和备注。本轮创建
分群 `44545 / GSDK分群删除探测-4f97 / GSDK-1a29289eee2c`，删除前按 exact ID 读回并核对
name/marker，随后 `save + DEL` 返回 HTTP 200 / `code=0`。删除后的完整列表不再包含 ID、name 或
marker；再读 detail 返回 HTTP 200 / `code=1004` / `请检查入参：分群ID不存在`。最终残留为 0。

因此，“12 条含 segment 的非 GET 路由里没有 delete/remove path”不能推出平台不能删。这里的直接
原因是删除语义藏在 `/segment/save/` 的 body 中，而不是 path 或 method 中。

当前代码基线其实已经有这项受治理能力：source operation 是
`analysis.dataanalysis.segment.update`，高层 Core/CLI/SDK 分别有 `delete_segment`、
`gravity analysis segment delete` 和 `segment_delete()`。如果只按 operation ID 的 action 或 path
词元盘点，会把这项能力误报为缺失。当前 402 个 reservation 文件中确实也没有独立的分群删除项，
但这不影响已登记 `/segment/save/` 的 `DEL` 语义；本单元没有修改或新增任何 operation。

## 1. `coverage.json` 的来源与完备性

### 生成链

它不是业务接口抓包，也不要求操作者在抓取期间点击页面功能。生成链是：

1. `census/fetcher.py` 从 `https://web.gravity-engine.com/` 的公开入口 HTML 出发，只发 GET；读取
   module script、modulepreload、Vite/Webpack manifest 和 JS 字符串引用，递归下载同源 JS。
2. `census/parser.py` 对下载的 bundle 做“词法字符串扫描 + request-call 上下文 + wrapper 推断”，
   生成 `routes.json`。
3. `census/params.py` 从同一静态调用点提取 request body/query 形状，生成 `route-params.json`。
4. `census/coverage.py` 把静态路由与当时的 stable manifest、reservation 和 route registry 对账，
   生成 `coverage.json` 与报告。`covered` 是合同对账状态，不是“线上调用过”。

仓库 snapshot 抓取于 `2026-08-09T02:01:31+08:00`，入口为
`assets/index-D9HAN43D.js`。它共下载 375 个同源部署 chunk、25,360,834 bytes，解析 2,023 个
route occurrence，归并为 987 个唯一 method/path；76 个 method 无法静态确定。完整 crawl 共 504 次
公开静态资源请求，0 pending、0 failed，另有 122 个词法 `.js` 候选被 HTTP 404 证明不是部署资源。

`coverage.json` 的分类还是生成时点快照，不会随合同文件自动更新。例如当前 source contracts 已把
报表 list/detail/update 晋升为 stable，但 checked-in coverage 仍保留晋升前的 candidate/reservation
分类。这个时间差不改变其中 987 条静态路由本身的来源。

### 完备性边界

`summary.complete=true` 只证明：该次公开入口可递归发现的同源静态 JS 图抓全，且抓取期间入口 HTML
保持稳定。它不证明以下范围完备：

- 只有登录后、特定租户/角色、feature flag 或另一入口文档才下发的模块；
- 跨源 JS（snapshot 明确忽略了 32 个跨源引用）；
- 运行时拼接、解码、加密或服务端下发的 URL；
- 前端没有引用、但后端仍接受的接口；
- path 不变但 body 语义或后端行为发生变化的接口；
- 已从前端移除但后端尚未下线的接口。

所以本题两个候选解释都不完全准确：它不是“引力全部接口”，也不是“抓取期间被用户触发过的接口”；
它是“该时点公开前端静态图中可发现的接口候选”。未点击删除不会导致静态调用点缺失，但静态图中没有
仍然不等于平台没有。

## 2. 分群删除的静态合同

`route-params.json` 在 `UserGroup-CXzHsUf1.js` 的两个 `/segment/save/` 调用点提取到：

| 字段 | 静态证据 | 语义 |
| --- | --- | --- |
| `action` | 恒出现；字符串；观察值 `DEL`、`UPDATE_NAME` | 删除或更新元数据 |
| `segment_id` | 恒出现 | exact 分群 ID |
| `segment_name` | 恒出现 | 原对象名称或更新后的名称 |
| `segment_remark` | 条件出现；字符串 | 原对象备注；安全删除用它校验 marker |

没有 `status`、`is_delete` 或 `is_deleted` 字段。`analysis.dataanalysis.query.delete` 对应的是
`POST /report/api/v3/dataanalysis/kill_query/`，语义是终止查询，不是删除分群。
`analysis.datamanageconfig.*` 的 kanban/folder/dashboard 删除也属于其他资源；没有证据表明分群挂在
这些对象下删除。

本轮成功删除 wire 为：

```json
{
  "segment_id": "44545",
  "segment_name": "GSDK分群删除探测-4f97",
  "segment_remark": "GSDK-1a29289eee2c",
  "action": "DEL"
}
```

成功响应的观察形状为顶层 `code/data/extra/msg`，HTTP 200、`code=0`、`msg=成功`、
`extra.error=""`、`data` 为 object。本轮账本只保存了 `data` 的类型，没有保存其内部 key，因此内部
精确形状不确定。mutation transport 固定 `attempts=1`，没有自动重放。

对幂等性的精确结论是：第一次 `DEL` 成功；删除后 detail 已无法取得 preimage，所以现有受治理删除
再次调用会在读回阶段失败并且不会再发写。直接绕过 guard 重复发送 raw `DEL` 的上游幂等性没有测试，
也不应为了回答该问题对已删除 ID 再发 mutation。

## 3. 删除是硬删除还是软删除

从 API 可见行为看，它表现为删除，而不是仍可查询的状态更新：

- 成功响应后，完整分群列表中 ID/name/marker 均消失；
- exact detail 返回 `code=1004` 和“分群ID不存在”；
- wire 中没有软删除状态位，只有命令式 `action="DEL"`。

这足以判定“调用方可见的对象已删除”，但不能证明后端数据库物理删行；服务端内部是否保留 tombstone
不确定。如果内部实现属于软删除，它至少不会继续出现在当前 list/detail API 中。本轮测试对象没有被其他
分析引用，因此删除对既有分析结果、缓存结果或依赖引用的影响不确定；没有为了回答这个旁支再制造依赖链。

## 4. 生产实证与清理证据

所有 mutation 都先做了零网络 dry-run，`network_called=false / attempts=0`。所有实际 HTTP 都显式
固定 `attempt_limit=1`，无 transport retry、无翻页、无扩日期窗、无换 App；只选择 `app.list` 返回的
第一个 App。

第一次 create 的 marker 后带中文说明，上游以“分群备注不合法”拒绝。随后单独读取完整列表，确认
旧 name/marker 命中 0，再把 remark 收窄为只含新的 SDK marker，做第二次 dry-run 后发送形态已改变的
create。这是独立的调整后请求，不是 HTTP 自动重试；上游最终只创建了一个对象。

| # | operation | method/path | HTTP / protocol | 重试、翻页、扩窗 | 作用与证据 |
| ---: | --- | --- | --- | --- | --- |
| 1 | `app.list` | GET `/turbo_engine/api/v1/user/open_app/list/` | 200 / `code=0` | 否 / 否 / 否 | 只取第一页 1 项，选择首个 App |
| 2 | `analysis.segment.list` | GET `/report/api/v3/dataanalysis/segment/list/` | 200 / `code=0` | 否 / 否 / 否 | 首次 create 的完整 preflight |
| 3 | `analysis.segment.from.rule.create` | POST `/report/api/v3/dataanalysis/segment/from_rule/create/` | 200 / `code=1004` | 否 / 不适用 / 否 | “分群备注不合法”，未创建 |
| 4 | `analysis.segment.list` | GET `/report/api/v3/dataanalysis/segment/list/` | 200 / `code=0` | 否 / 否 / 否 | 拒绝后旧 name/marker 命中 0 |
| 5 | `analysis.segment.list` | GET `/report/api/v3/dataanalysis/segment/list/` | 200 / `code=0` | 否 / 否 / 否 | 调整后 create 的完整 preflight |
| 6 | `analysis.segment.from.rule.create` | POST `/report/api/v3/dataanalysis/segment/from_rule/create/` | 200 / `code=0` | 否 / 不适用 / 否 | 创建唯一对象 `44545` |
| 7 | `analysis.segment.list` | GET `/report/api/v3/dataanalysis/segment/list/` | 200 / `code=0` | 否 / 否 / 否 | 创建后 name/marker 列表读回 |
| 8 | `analysis.segment.detail` | GET `/report/api/v3/dataanalysis/segment/detail/` | 200 / `code=0` | 否 / 不适用 / 否 | 创建后 exact detail 读回 |
| 9 | `analysis.segment.detail` | 同上 | 200 / `code=0` | 否 / 不适用 / 否 | 独立 delete-guard；ID/name/marker 匹配 |
| 10 | `analysis.segment.detail` | 同上 | 200 / `code=0` | 否 / 不适用 / 否 | execute 时再次读取 preimage 并校验 marker |
| 11 | `analysis.dataanalysis.segment.update` | POST `/report/api/v3/dataanalysis/segment/save/` | 200 / `code=0` | 否 / 不适用 / 否 | `action=DEL` 成功 |
| 12 | `analysis.segment.list` | GET `/report/api/v3/dataanalysis/segment/list/` | 200 / `code=0` | 否 / 否 / 否 | SDK 写后完整列表确认 ID 已消失 |
| 13 | `analysis.segment.detail` | GET `/report/api/v3/dataanalysis/segment/detail/` | 200 / `code=1004` | 否 / 不适用 / 否 | “分群ID不存在”，`data` 无投影 key |
| 14 | `analysis.segment.list` | GET `/report/api/v3/dataanalysis/segment/list/` | 200 / `code=0` | 否 / 否 / 否 | 最终 ID/name/marker 命中 0 |

合计 14 = 11 read + 3 mutation HTTP；3 个 mutation HTTP 是 1 次被明确拒绝的 create、1 次成功
create、1 次成功 delete。成功创建对象只有 1 个。最终清理状态为 `verified_clean`，残留清单为空。

## 5. 报表对照

保存报表也不是独立 create/delete path。`ReportCommonHeader-Ck1C9MQA.js` 的静态控制流证明同一路由
承载创建、更新和删除：

```text
POST /turbo_engine/api/v2/datamanageconfig/report/update/
```

- create：`name/remark/subject/app_id/project_id/config`；没有 ID 时创建；
- delete：在原对象字段外带 `id/report_group_id/is_delete=1`。

`route-params.json` 对该路由确实提取到 `is_delete`，观察默认值为 `1`；路由附近 UI 文案包含“删除”、
“删除成功”和“确定删除？”。所以报表与分群的根因相同：一个 update/save route 按 body 承载多种语义，
不能仅按 path 或 operation action 盘点 create/delete。差别是分群使用 `action="DEL"`，报表使用
`is_delete=1`。

987 条里另有 `/{from}/report/delete/` 和 `/kanban/report/delete/`，但其控制流分别靠近投放产品/日期
数据删除和 kanban 节点，不是已保存报表目录的删除证据；不能用名字相似替代精确资源控制流。

同分群一样，当前代码基线已经通过 `report.report.update` 的高层 `create_report/delete_report` 暴露
受治理的报表创建和删除。因此“有 update operation、没有 create/delete operation ID”不等于产品面
没有 create/delete。本单元按要求没有做报表生产实证。

## 6. 下一单所需信息与不确定项

如果目标只是安全实现“删除 SDK 自己创建的分群”，wire 级信息已经足够：exact method/path、
`DEL` body、成功 envelope、一次性发送、删除前 detail marker guard、删除后 list/detail 表现都已证明。
但在当前 `1a7663c` 基线上该能力已经存在，不应再新增第二个 operation 或兼容别名；并行治理线合并后应
先确认现有 source operation 和高层 surface 是否仍保留，再决定是否有实现工作。

仍不确定、且不是安全最小实现的 blocker：

- 后端是物理删除还是内部 tombstone；
- raw `DEL` 重复发送的上游幂等性；现有 guard 会阻止第二次写；
- 被分析、分群或其他对象引用时的完整行为，以及删除对历史/缓存分析结果的影响；
- 成功响应 `data` object 的内部 key；本轮只持久化了类型；
- 其他租户、角色或 feature flag 下是否存在另一条分群删除路由。

这些未知项不能从当前静态图或本轮单对象实测外推。它们不改变“本租户可通过 `save + DEL` 删除分群，
且本轮对象已清理”的结论。
