# 能力覆盖与缺口

本页回答“现在能调用什么、哪些只是候选、下一步为何不能直接上线”。运行时真相仍以
manifest 与 `gravity agent <query>` 为准；完整路由账本见
[`coverage-report.md`](../src/gravity_sdk/census/data/coverage-report.md)。

## 当前离线快照（2026-08-16）

| 范围 | 当前状态 |
| --- | --- |
| 编译 operation | 186 |
| stable operation | 177 |
| stable operation 产品面交叉 | 87 已覆盖 / 82 不应产品化 / 8 值得产品化 |
| 推广 / 素材 stable 原子读取 | 64 / 24 |
| Census 路由 | 987，全部有明确归类 |
| Census 中 callable covered route | 173 |
| 尚未覆盖的 read route | 342 |
| 明确保留的推广 / 素材 write reservation | 110 / 49 |

这些数字不等于“还有 343 个接口可以直接开发”。推广与素材共有 188 个 catalog-only
draft，但当前没有一个具有成功 probe；它们可用于说明缺口和准备最小探测，不能生成执行
argv，也不能进入 stable manifest。

stable 同样不等于已有分析产品：本轮首次从 176 条 stable operation 正向检查产品调用链，
`gravity run <operation-id>`、legacy promotion snapshot 和 SDK inventory snapshot 均不算分析动线。
实现前完整交叉为 `86 / 82 / 8`；8 条中只有 `report.company_amount.query` 同时具备成功非空与
分页证据、清晰独立语义和已批准投影，因此已通过 `reports usage` / SDK / Plan / Agent 四面闭环。
其余 7 条的边界与 blocker 以 [路线图](roadmap.md#stable-operation-正向交叉2026-08-14) 为准。
2026-08-16 另将多 App 复验取得非空 shape 的 `analysis.default_val.list` 晋升并闭环默认值字典，
所以当前交叉计数相对该历史快照增加 1 条“已覆盖”。

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

这次语义复核不改 Census 的机器 route status，也不把 UI route 包装成产品：编译 operation 仍为 185、
stable 仍为 176、callable covered route 仍为 172、`uncovered_read` 仍为 343。现在可直接回答真正缺口：
在这 155 条中有分析价值但尚无证据的路由是 39 条；另有 5 条因 method、请求/响应或服务端语义不足
仍无法判定。下一轮只有在租户数据或服务端合同证据改变后才重启这 18 条，不重复当前租户的空探测。

## 平台纵深

- Bytedance 已覆盖账户、广告主、项目、推广、筛选器、汇总表现和主要素材查询，是目前唯一
  同时具备推广与素材纵深的平台。
- Honor 的 Census read route 已基本闭合；Kuaishou、Tencent、Bilibili、Apple、Huawei、
  Oppo、Vivo、Xiaomi 等多数平台仍以账户/广告主等基础读取为主。
- 除 Bytedance 外，平台专属素材能力普遍缺少经过非空样本验证的响应合同；不要把 common
  素材目录误写成各平台已完整覆盖。
- Apple、Huya、Qihu360、Sigmob、UC、Youdao、Bilibili 的 campaign/group/creative/report
  草稿最接近可验证状态。D32 已在当前账号完成最小根读取：只有 Bilibili account 曾非空，但
  advertiser 为空；其余六个平台在允许的根读取或最短单日 advertiser 窗口内均为空，且无权限
  失败或合同漂移。子级未发送，所有草稿继续等待有数据租户的最小非空 probe。
- auth/proxy 路由和写操作不属于普通读取缺口。前者保持 unsupported，后者保持 reservation，
  除非项目范围和安全模型明确扩展。

## 四级能力状态

| 状态 | Agent 应如何处理 | 升级条件 |
| --- | --- | --- |
| stable executable | 可以发现、描述、校验和执行 | 持续通过合同、隐私和漂移检查 |
| stable projection gap | 端点可用，但部分响应字段仍 fail-closed | 已有成功、脱敏、非空字段证据即可深化 |
| catalog-only draft | 只报告为 capability gap，不提供执行 argv | 请求绑定、非空响应、分页、隐私、父依赖和权限证据齐全 |
| reservation / unsupported | 不作为待调用能力展示 | 必须先改变项目范围和治理设计 |

本轮已按第二级补齐 Bilibili 账户汇总、素材分类→标签树、推广变更审计 ID、multidim
合计字段链路、overview 指标列映射，以及事件属性模板的 common/custom/preset 字典；未知
字段继续 fail-closed。

## 导出边界（2026-08-13 判定）

导出是独立 effect，账本在 `src/gravity_sdk/contracts/exports/routes-v1.json`。22 条 route 中只有
5 条 `executable`：`export.material.report.start` 是唯一可创建的导出，其余 4 条
（`export.task.list/progress/cancel`、`export.task_type.list`）是支持路由，不是创建候选。

**9 条 `export.analysis.*` 仍全部不可执行；2026-08-15 投影放开后重新裁定如下**：

| 分类 | 数量 | route | 结论 |
| --- | --- | --- | --- |
| 父工作流依赖 | 1 | `origin_event.evaluate` | 自身估算请求与聚合响应已验证，但配对 `origin_event.start` 的成功 create 和文件合同未成立；旧口径把它误算成用户级投影阻塞 |
| 投影已放开、文件类型未证实 | 2 | `segment.result.start`、`user_event.start` | 前者只有 1 行但未记录单元格存储/逻辑类型，后者为 0 行；两者虽有 XLSX 表头与单 worksheet 证据，仍不满足完整文件 schema |
| 请求/文件合同未验证 | 6 | `origin_event.start`、`monetization_detail.start`、`segment_user_detail.start`、`stream_event.start`、`user_detail.start`、`pay_event.start` | 多数在线可建任务但任务失败，或返回 1004 无 task id；成功 payload/父绑定与完整文件 schema 未证明。**无新证据不重试** |

SDK 已按投影总裁决移除 `user_level` 的本地禁出总闸门，但不会用该裁决替代请求或文件合同。
本轮最小父资源复核在 2 次 HTTP 200 后因第一页分群为空停止，create/poll/download 均为 0；没有
换 App、翻页、扩窗或重试。调用方用 `export list-capabilities` 查看边界，不要把 catalog 条目当成
可执行能力。

## 刷新与核对

日常调用方不需要跑 Census。维护者在 frontend bundle 或 manifest 变化后执行离线对账：

```powershell
gravity census coverage --require-accounted
python -m gravity_sdk.compiler check
```

`coverage` 只消费已保存的 route、manifest、reservation 和 registry 文件；`fetch` 与
`check-upstream` 才会访问网络。任何生产 probe 仍必须遵循
[探测安全](maintainers/probing.md)，不能因为 draft 数量多而批量试探。
