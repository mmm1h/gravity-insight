# 能力覆盖与缺口

本页回答“现在能调用什么、哪些只是候选、下一步为何不能直接上线”。运行时真相仍以
manifest 与 `gravity agent <query>` 为准；完整路由账本见
[`coverage-report.md`](../src/gravity_sdk/census/data/coverage-report.md)。

## 当前离线快照（2026-08-17）

| 范围 | 当前状态 |
| --- | --- |
| 编译 operation | 233（原 205 + Kanban 18 + 当前自定义指标 3 + 事件/属性模板 4 + 保存分析 1 + 公开 App 信息 1 + D28 变现聚合 1） |
| stable operation | 224（187 read / 37 governed mutation） |
| stable read operation 产品面交叉 | 96 已覆盖 / 82 不应产品化 / 8 原快照待产品化；公开 App 信息、D28、默认值字典、D35、F40、报表目录与订阅已直接闭环 |
| 推广 / 素材 stable 原子读取 | 64 / 24 |
| Census 路由 | 冻结 Web-entry 静态快照内 987，快照内全部有明确归类；不是平台总路由 |
| Census 中 callable covered route | 210 |
| 尚未覆盖的 read route | 335 |
| 明确保留的推广 / 素材 write reservation | 110 / 49 |

这些数字不等于“还有 335 个接口可以直接开发”。推广与素材共有 188 个 catalog-only
draft，但当前没有一个具有成功 probe；它们可用于说明缺口和准备最小探测，不能生成执行
argv，也不能进入 stable manifest。

`987` 的入口、抓取时间、静态闭包与范围外未知项见
[Census 完整性与分母审计](research/census-completeness-audit.md)。本页所有 Census 分解都只在该冻结
集合内成立；未出现的能力不能据此判为平台不存在。

stable 同样不等于已有分析产品：既有正向交叉是晋升前快照；本轮新增的 `app.app_info.get` 已由
公开 URL 成功合同直接闭环，
`gravity run <operation-id>`、legacy promotion snapshot 和 SDK inventory snapshot 均不算分析动线。
实现前完整交叉为 `86 / 82 / 8`；8 条中只有 `report.company_amount.query` 同时具备成功非空与
分页证据、清晰独立语义和已批准投影，因此已通过 `reports usage` / SDK / Plan / Agent 四面闭环。
其余 7 条的边界与 blocker 以 [路线图](roadmap.md#stable-operation-正向交叉2026-08-14) 为准。
2026-08-16 另将多 App 复验取得非空 shape 的 `analysis.default_val.list` 晋升并闭环默认值字典，
所以当时交叉计数相对该历史快照增加 1 条“已覆盖”；本轮 `app.app_info.get` 再增加 1 条。

## 其余 155 条未覆盖读路由逐条复核（2026-08-16）

本轮对 `343 - 188 = 155` 条非推广/素材 draft 路由逐条读取 Census、hash-matched frontend bundle、
manifest 和既有合同证据。阶段一不发生产请求，互斥分类为：

| 类别 | 离线初判 | 取证后最终 |
| --- | ---: | ---: |
| 已有等价产品覆盖 | 18 | 18 |
| UI 辅助路由 | 89 | 89 |
| mutation / 写操作 | 4 | 4 |
| 有分析价值、证据可自取 | 18 | 0 |
| 有分析价值、但数据/证据阻塞 | 21 | 39 |
| 无法判定 | 5 | 5 |
| **合计** | **155** | **155** |

这张六类表冻结的是派发时的 343 条 `uncovered_read` 快照。随后晋升的
`analysis.default_val.list` 在该表中原列为“UI 辅助路由”；晋升后它从 `uncovered_read` 移入
callable covered；D35 随后也从“有分析价值、但数据/证据阻塞”闭环。因此当前分母可复算为
该段在默认值字典与 D35 晋升后为 `341 - 188 = 153`；报表/订阅再晋升 4 条 read，F40 再晋升
2 条 read，当前 `uncovered_read=341-4-2=335`。上表仍保留 155 条逐路由复核的历史取证总账，
不把事后的晋升倒写成当时遗漏。

分母没有快照漂移：343 条 `uncovered_read` 中，draft 目录有 148 条 promotion 与 40 条 material
唯一 path，排除后恰为 155。唯一 method 证据差异是 `promotion.promoted_object.list`：draft 为 POST，
Census 对同一 path 仍为 UNKNOWN；按唯一 path 排除，未重复计数。逐条工作账本保存在本 worktree 的
`tmp/codex/route-coverage/route-classification.md`，生成器断言 155 条无遗漏、无重复。

阶段二按“实时事件 → 数据表 schema/版本 → 巨量项目素材表现 → AppRank 榜单/趋势/竞品 → 点击监测
链接 → 兜底 eCPM → 自有多维模板详情”的分析师价值顺序复核 18 条候选。实际生产 HTTP **10 次**，
低于 40 次预算；4 次 AppRank 根目录为 HTTP 200 semantic error，data-table list、两条点击监测目录与
自有模板父目录为 HTTP 200 明确空，另 2 次为 App 目录父读取。其余目标在发送前因缺合法父值、值域
或已有同租户空样本而 fail closed；没有重试、翻页、扩窗或猜业务值。18 条均未取得可晋升的成功非空
响应合同，故最终全部转入“数据/证据阻塞”，本轮新增产品和分析动线均为 0。

这次语义复核自身不改 Census 的机器 route status，也不把 UI route 包装成产品；其派发快照为
operation 185、stable 176、callable covered route 172、`uncovered_read=343`。随后默认值字典与 D35
各晋升 1 条 read，Segment mutation 再把 7 条 reservation 提升为 stable；报表/订阅写解锁再新增
4 read + 5 mutation，F40 再晋升 2 read。因此当前值统一为 operation
`185 + 2 + 7 + 9 + 2 = 205`、stable `176 + 2 + 7 + 9 + 2 = 196`、callable covered route
`172 + 2 + 7 + 9 + 2 = 192`、`uncovered_read=335`。
现在可直接回答真正缺口：
在这 155 条中有分析价值但尚无证据的路由是 39 条；另有 5 条因 method、请求/响应或服务端语义不足
仍无法判定。下一轮只有在租户数据或服务端合同证据改变后才重启这 18 条，不重复当前租户的空探测。

## 平台纵深

- Bytedance 已覆盖账户、广告主、项目、推广、筛选器、汇总表现和主要素材查询，是目前唯一
  同时具备推广与素材纵深的平台。
- Honor 的 Census read route 已基本闭合；Kuaishou、Tencent、Bilibili、Apple、Huawei、
  Oppo、Vivo、Xiaomi 等多数平台仍以账户/广告主等基础读取为主。
- 除 Bytedance 外，平台专属素材能力仍不要写成已完整覆盖。2026-08-17 当前租户已取得腾讯
  `material.tencent.list` 非空样本并登记 URL/人员字段；`material.tencent_medium_creative.list`
  已取得非空 item schema 并晋升。其他平台创意 draft 仍缺 confirmed-read 或非空 item schema。不要把 common 素材目录误写成各平台已覆盖。
- Apple、Huya、Qihu360、Sigmob、UC、Youdao、Bilibili 的 campaign/group/creative/report
  草稿仍接近可验证，但当前租户账户目录只绑了 `bytedance/tencent/kuaishou`。腾讯广告主与
  广告组根已非空；快手账户/广告主报表在 `2026-03-01..2026-08-16` 明确空。腾讯广告组报表
  已晋升；腾讯创意报表对声明父对象返回 `code=2000`，不再换父重试。
- auth/proxy 路由和写操作不属于普通读取缺口。前者保持 unsupported。写操作边界已经显式扩大，
  但只放行 12 条逐项登记的 mutation：7 条 Segment，以及 5 条 marker-governed 报表/订阅
  create/delete 脚手架。推广投放、素材、多维报表、权限、事件/事件属性删除及其他未登记
  mutation 仍为 reservation/blocked write；范围依据是“补全探索式分析闭环”而不是 HTTP method。

## 四级能力状态

| 状态 | Agent 应如何处理 | 升级条件 |
| --- | --- | --- |
| stable executable | 可以发现、描述、校验和执行 | 持续通过合同、隐私和漂移检查 |
| stable projection gap | 端点可用，但部分响应字段仍 fail-closed | 已有成功、脱敏、非空字段证据即可深化 |
| catalog-only draft | 只报告为 capability gap，不提供执行 argv | 请求绑定、非空响应、分页、隐私、父依赖和权限证据齐全 |
| reservation / unsupported | 不作为待调用能力展示 | 新增 mutation family 必须另行改变范围并完成写治理；unsupported 需先取得可执行合同 |

## 写操作边界（2026-08-16 裁决）

当前只开放 12 条逐项登记的 stable mutation：7 条 Segment，以及 5 条 marker-governed 报表/订阅
operation。Segment create 把可见 `GSDK-<12 hex>` 放进 `segment_remark`；报表放进 `remark`；订阅
同时放进 `name/wildcard_name`。创建后经完整列表或 detail 读回，删除只接受执行时读回仍带标记的
对象。所有 mutation 默认只生成零网络 dry-run，执行必须显式选择 `--execute`，单次发送且不自动
重放。标记用于识别 SDK 创建物，不过滤任何列表，也不是权限系统。

其余写路由不因本次框架存在而自动获准。尤其 110 条推广写、49 条素材写、多维查询模板写、权限管理、
`event/event_batch_delete` 与 `event_property_batch_delete` 继续 reservation；只有精确 source contract、
`effect=mutation`、stable/executable 状态及产品层确认流程同时成立时，运行时才会签发一次性写授权。

本轮已按第二级补齐 Bilibili 账户汇总、素材分类→标签树、推广变更审计 ID、multidim
合计字段链路、overview 指标列映射，以及事件属性模板的 common/custom/preset 字典；未知
字段继续 fail-closed。

## 导出边界（更新至 2026-08-16 第二轮）

导出是独立 effect，账本在 `src/gravity_sdk/contracts/exports/routes-v1.json`。22 条 route 中有
7 条可创建导出加 4 条支持路由可执行：`export.material.report.start` 与六个 Analysis creator
（含现已可调用的 `export.analysis.monetization_detail.start`）；其余 4 条
（`export.task.list/progress/cancel`、`export.task_type.list`）是支持路由，不是创建候选。

9 条 `export.analysis.*` 当前逐条裁定如下：

| 分类 | 数量 | route | 结论 |
| --- | --- | --- | --- |
| 完整合同、可调用 | 7 | `user_event.start`、`segment.result.start`、`segment_user_detail.start`、`user_detail.start`、`pay_event.start`、`monetization_detail.start`、`origin_event.start` | 前五族已有非空 XLSX 文件合同。`monetization_detail` 现可调用并标注截断。`origin_event` 现可调用：evaluate 正数后 create→poll→download 得到 gzip CSV，五列表头与 1 行已实测 |
| 父工作流依赖 | 0 | — | `origin_event.evaluate` 现可调用，且已与成功 create/文件合同配对 |
| 投影已放开、文件类型未证实 | 1 | `segment.result.start` | 只有 1 行但未记录单元格存储/逻辑类型；XLSX 表头与单 worksheet 证据仍不满足完整文件 schema |
| 请求/文件合同未验证 | 0 | — | `origin_event.start` 已取得成功 create 与 gzip CSV schema |
| 前端无服务端路径 | 1 | `stream_event.start` | hash-matched loader 没有调用点，按钮走客户端表格序列化；记为 `not_applicable`，不是 SDK 缺口，不得 probe 未使用 route |

SDK 已按投影总裁决移除 `user_level` 的本地禁出总闸门，但不会用该裁决替代请求或文件合同。
第二轮按 catalog 枚举 App，9 次生产 HTTP 在第三个 App 首次非空后完成 user-event 文件合同；没有
翻数据页、扩窗或重试。调用方用 `export list-capabilities` 查看边界，不要把不可执行或
`not_applicable` catalog 条目当成可执行能力。

## 刷新与核对

日常调用方不需要跑 Census。维护者在 frontend bundle 或 manifest 变化后执行离线对账：

```powershell
gravity census coverage --require-accounted
python -m gravity_sdk.compiler check
```

`coverage` 只消费已保存的 route、manifest、reservation 和 registry 文件；`fetch` 与
`check-upstream` 才会访问网络。任何生产 probe 仍必须遵循
[探测安全](maintainers/probing.md)，不能因为 draft 数量多而批量试探。
