> 归档材料：保留历史决策与取证，不代表当前接口或状态；当前入口见 docs/index.md。

# Census 完整性与分母审计

> 审计基线：`dev@69ac207`，2026-08-16。本文只复验冻结的公开前端快照、解析器和既有文档；
> Gravity 生产业务 HTTP 请求 0 次，公开静态资源请求 0 次，没有重抓 bundle。

## 结论

`routes.json` **不是平台路由全集**。它是 2026-08-09 02:01:31（UTC+8）从
`https://web.gravity-engine.com/` 公开入口取得的、该入口当时可静态递归发现的同源 JS 图中的
API 候选集合。`987` 只能作为这个冻结集合的分母；集合外的租户/角色/feature flag 模块、其他入口或
origin、运行时拼接 URL、服务端接口和前端未引用接口都未知。

这份具体快照在它声明的窄范围内是完整的：375 个 JS、25,360,834 bytes，0 pending、0 failed；
入口 HTML 抓取前后稳定。原始文件仍在本机忽略目录
`D:/git-pjt/work-dashboard/tmp/codex/gi-census-full/final/`，375/375 个 JS 和入口 HTML 均与
`bundle-snapshot.json` 的 SHA-256 相符。用当前解析器离线重放得到完全相同的
`routes.json`（加入显式 scope 元数据后的 SHA-256
`d3ca80f92a968cdaf76819eac1dee6289e4398e344a061b7796aeaf04fa8f439`）。
原始文件没有进入版本控制，因而“本机还在”不等于仓库拥有可移植的冻结输入。

SQL 工作台的缺失原因也已缩小：它**不是未点击懒加载页，也不是 76 条 UNKNOWN method 之一**。
入口 bundle 明确有 `SQL工作台 → /analysis/bi` 菜单和路由，但该路由是识别出的 210 个 route-like
条目中唯一一个没有 `component` / dynamic import 的叶路由。全部 375 个哈希匹配 JS 中没有
`/custom_sql/`、`sql/execute` 或 SQL 工作台实现 chunk，只有结构化 Analysis 的
`/report/api/v3/dataanalysis/query_sql/`。因此当前构建只证明一个 SQL 菜单/路由占位；功能为何以占位
存在、是否由另一构建或运行时注入、真实 CRUD 路由是什么，仍不确定。

## 1. 抓取源、时间与枚举方式

证据来自 `src/gravity_sdk/census/fetcher.py`、`bundle-snapshot.json` 和哈希匹配的原始入口：

| 问题 | 已确定事实 | 证据 |
| --- | --- | --- |
| 抓取源 | 公开入口 `https://web.gravity-engine.com/` 的 HTML 与同源 JS | snapshot `site_url`；fetcher `DEFAULT_SITE` |
| 抓取时间 | `2026-08-08T18:01:31Z`，即 UTC+8 的 `2026-08-09 02:01:31` | snapshot `fetched_at` |
| 上游构建时间 | `2026-08-07T08:37:46.166Z`，即 UTC+8 的 `2026-08-07 16:37:46.166` | HTML `window.BUILD_INFO.timestamp`，不是抓取时间 |
| 入口 | `assets/index-D9HAN43D.js`，另有 5 个 modulepreload | snapshot `entry_urls` / `modulepreload_urls` |
| 枚举 | HTML module script、modulepreload、manifest 候选、递归 JS 字符串引用/chunk map | fetcher `discovery.strategies` |
| 是否浏览器录流量 | 否；不依赖用户点过哪些页面 | `StaticFetcher.fetch()` 的静态 BFS |
| manifest | 三个 conventional manifest URL 均 404 | snapshot `manifest_probes` |
| 闭包结果 | 497 个发现候选 = 375 个成功 JS + 122 个被 404 证伪的非部署资源 | snapshot `summary` |

入口自身记录 410 个 JS 引用，并含 Vite `__vite__mapDeps` 信号。抓取器按最多 4 并发递归读取同源引用，
而不是等待浏览器触发 dynamic import；结束后还会重新读取入口 HTML，检查入口集合和 HTML hash 是否变化。
所以 `summary.complete=true` 的精确定义是“该入口的可静态发现同源图闭合”，不是“平台完整”。由于没有
可用 manifest，也不能证明 origin 上不存在未被入口引用的 orphan chunk。

## 2. 模块覆盖与可复算下界

入口的菜单/路由表显示产品方列出的主要模块都在该构建中有 component chunk，SQL 工作台例外。
下表把前端 route-like 条目按页面 path 归组；API 数是 `routes.json` 的 first occurrence 落在
“页面 component chunk / component 的一跳依赖 chunk”中的数量。后一列存在跨模块共享，**不可相加**；
它只用于识别“整个模块几乎没有静态 API 证据”，不是新的平台路由分母。

| 模块 | 页面条目 / 唯一 component chunk | API 静态证据（页面 / 一跳） | 判断 |
| --- | ---: | ---: | --- |
| 分析—看板 | 2 / 2 | 48 / 78 | 有充分页面与 API 证据 |
| 分析—行为 | 7 / 6，另 1 个无 component | 13 / 51 | 事件/留存/漏斗/分布/订单/变现充分；无 component 的 1 个是 SQL 工作台 |
| 分析—用户 | 7 / 7 | 21 / 59 | 有充分页面与 API 证据 |
| 多维报表 | 2 / 2 | 34 / 59 | 有充分页面与 API 证据 |
| 推广/创编 | 38 / 37 | 112 / 179 | 有充分页面与 API 证据 |
| 素材 | 18 / 12 | 38 / 101 | 有充分页面与 API 证据；多个 path 复用 component |
| 资产 | 26 / 26 | 88 / 149 | 有充分页面与 API 证据 |
| 归因 | 5 / 5 | 43 / 81 | 有充分页面与 API 证据 |
| 设置/管理 | 33 / 33 | 197 / 254 | 有充分页面与 API 证据 |
| 经营报表 | 2 / 2 | 2 / 34 | 页面 chunk 本身较薄，但依赖图有静态 API 证据 |

这能否证“抓取只包含当时打开过的模块”，也没有发现产品方所列其他一级模块像 SQL 一样整块缺
component。它不能证明每个模块的所有 API 都在 987 中：共享 wrapper、计算 URL、角色专属页面、不同入口
和后端-only route 仍可能缺失。

对“漏了多少”只能给边界，不能给估值：

- 已知固定路径的严格下界是至少 3 条：仓库使用但非 census 来源的
  `/custom_sql/api/sql/execute`，以及官方文档已证明但不在 census 的事件采集、媒体 Token 刷新两条路径。
- SQL saved query / history / share 的路径数未知，不能从一个菜单占位倒推出 CRUD 是 4 条还是复用 1 条。
- 菜单还把“引力排行榜”明确导航到另一 origin `rank.gravity-engine.com`；该应用的静态图不在本次
  `web.gravity-engine.com` 同源 crawl 内。这是 SQL 之外已经证明的入口边界，但不在题面七个主要模块中。
- 角色、租户或 feature flag 之外还缺哪些模块，以及缺失 route 总数，现有冻结证据无法确定。

## 3. SQL 工作台为何没有 API 路由

哈希匹配入口的证据链为：

1. 菜单数组把 SQL 工作台列在行为分析下，指向 `/analysis/bi`。
2. 路由数组也有同名 path，但相邻的事件、漏斗、分布、用户、订单、变现、留存页面都有
   `component: () => import(...)`，SQL 条目没有。
3. 对入口中 210 个 route-like 条目做同一结构检查，只有这个叶路由没有 component。
4. 375 个 JS 的全文只有 `query_sql` 这个 Analysis API 命中；`/custom_sql/` 和 `sql/execute` 为 0。
5. 当前解析器对同一 raw 重放逐字节复现 987/2,023/76，排除 checked-in 输出来自另一份 raw 的可能。

因此能确定的是“该构建没有 SQL 实现 chunk 或 literal API path”，不是“平台没有 SQL 工作台”。
以下解释都没有足够证据择一：未完成/废弃占位、另一个入口或构建、登录后运行时注入、服务端重定向。
现有 bundle 中没有 SQL route component 或外部 URL，故不能把任一解释写成事实。

## 4. 76 条 UNKNOWN method

| 原因 | 数量 | 审计结论 |
| --- | ---: | --- |
| proxy target path 不编码上游 method | 47 | 46 个纯 proxy target，另 1 个同时也是官方目录值；包含推广/素材/资产的重要读写动作，但它们是请求 body 中的目标 API，不是可直接执行的 Gravity method/path 合同 |
| API catalog / documentation / service URL literal | 28 | 22 个官方目录值、4 个文档链接、2 个 service URL；本来就不是页面 request call |
| wrapper method 未解析 | 1 | Sigmob tracking host 常量 `/event_center/api/v1/base/wx/get_scheme/sigmob/`；原始上下文把它作为生成的 tracking URL，不是页面请求 wrapper |

其中没有 SQL path。也没有发现“重要的一方 Gravity 页面请求只因 method UNKNOWN 而被漏掉”的实例。
47 个 proxy target 中确有重要能力，例如 audience delete、event assets create 和素材查询；census 已发现其
目标 path，但没有足够证据给它们伪造一个上游 HTTP method。后续若要实现，必须还原承载 proxy 的
Gravity 请求及 body 中的 method/host/query_api，而不是把 UNKNOWN 批量改名。

## 5. 分母修正

本轮采用统一规则：

- `987` 表述为“冻结 Web-entry census 中的 987 条”，不得称“平台总路由”。
- `382 = 208 + 9 + 9 + 114 + 42` 仍是 checked-in reservation 集内可复算的**闭合集分类**；
  它不是平台完整写面分解，`42` 也不是平台授权写路由总数。
- `22 / 987 = 2.23%` 仍是“官方目录 path 在该冻结 census 记录中的占比”；它不是“官方 API 覆盖
  平台约 2%”。官方面与 Web-entry census 本来就是不同采样框。
- “census 没有 X”一律改为“该入口、时点、静态可发现同源图内未观察到 X；范围外未知”。

已直接修正：

1. `write-surface-census.md`：把 382/42 的母集改为冻结 snapshot/reservation 子集；补入 SQL 菜单占位、
   唯一 componentless leaf 和“不支持懒加载漏抓”的新证据。
2. `official-api-surface.md`：保留 22/987 算术，但撤销“官方只覆盖平台约 2%”式解释，改成同一冻结
   census 内的记录占比。
3. `roadmap.md`：把写面排期和 SQL route 的范围限定到冻结 census；增加本审计裁决。
4. `capability-coverage.md` 与研究索引：显式标注 987 是快照内账本，并挂入本文。
5. `routes.json` 与生成器：增加机器可读的 `coverage_scope` 和 `platform_complete=false`；
   `maintainers/census.md` 增加强制引用口径，防止后续再次把 `bundle_complete` 解释为平台完整。

## 6. 是否重抓

**不建议盲目重跑当前 public-entry fetch。** 上次代价是 504 次公开静态 GET、约 25.36 MB、59 秒；
同一算法只会刷新“公开入口可静态发现的同源图”，没有理由补出一个在入口中无 component/import 的 SQL
实现。它适合做当前入口的漂移更新，不适合证明平台全集。

若 SQL 工作台成为实现前置，建议另开一次**定向多入口/登录态取证**，先确认正确租户、角色和入口，再：

1. 保存入口 HTML、BUILD_INFO、权限/feature 配置与所有同源/明确批准的跨源应用入口；
2. 用浏览器自动化枚举可见前端页面并记录动态 chunk 与网络请求，SQL `/analysis/bi` 必须单独验收；
3. 对每个入口运行现有 static fetcher，冻结 raw、hash 和失败/pending；
4. 现有 parser 可直接复用到静态 JS，但 HAR/runtime API 与跨入口合并需要单独的 evidence 归并步骤；
5. 不把“点完当前账号菜单”称为全集，因为其他角色/flag 仍不可见。

代价从“约一分钟公开抓取”上升为“有账号/角色矩阵的浏览器遍历、跨入口资产冻结和人工复核”；可以自动化
页面遍历和网络记录，但不能自动证明未获授权角色或未启用 flag 下没有模块。本轮不重抓是因为它不会改变
当前 SQL 原因裁决，且题面明确要求先审计、不实际重抓。

在重抓前，防止过度自信的措施是：维护者文档强制使用上述范围模板；所有 coverage 百分比都同时写明
分子集合、冻结 census 分母和 `bundle_id`；任何“未出现”只生成 evidence gap，不生成“平台不存在”裁决。

## 7. 请求账本与不确定项

Gravity 生产业务 HTTP：**0 次**；operation 0，重试 0，分页 0，扩窗 0。

公开静态资源 HTTP：**0 次**。本轮只离线读取原始快照并运行一次 parser replay；没有执行 fetch 或
check-upstream。历史 snapshot 自身记录的 504 次公开 GET 是 2026-08-09 的抓取账本，不是本轮请求。

仍不确定：

- 平台 SQL 工作台真实实现位于哪里、是否对当前租户/角色可用、精确 method/path 和对象合同；
- `/analysis/bi` 是未完成、废弃、运行时注入还是另一入口的占位；
- 当前 origin 上是否存在入口未引用的 orphan chunk；
- 其他角色、租户、feature flag、其他 origin 和后端-only 接口漏了多少；
- `rank.gravity-engine.com` 的 API 数量与其是否应纳入本仓库分析边界。
