# 能力覆盖与缺口

本页回答“现在能调用什么、哪些只是候选、下一步为何不能直接上线”。运行时真相仍以
manifest 与 `gravity agent <query>` 为准；完整路由账本见
[`coverage-report.md`](../src/gravity_sdk/census/data/coverage-report.md)。

## 2026-08-16 离线快照

| 范围 | 当前状态 |
| --- | --- |
| 编译 operation | 192 |
| stable operation | 183（176 read / 7 governed Segment mutation） |
| stable read operation 产品面交叉 | 86 已覆盖 / 82 不应产品化 / 8 值得产品化（其中 1 条已闭环） |
| 推广 / 素材 stable 原子读取 | 64 / 24 |
| Census 路由 | 987，全部有明确归类 |
| Census 中 callable covered route | 179 |
| 尚未覆盖的 read route | 343 |
| 明确保留的推广 / 素材 write reservation | 110 / 49 |

这些数字不等于“还有 343 个接口可以直接开发”。推广与素材共有 188 个 catalog-only
draft，但当前没有一个具有成功 probe；它们可用于说明缺口和准备最小探测，不能生成执行
argv，也不能进入 stable manifest。

stable 同样不等于已有分析产品：既有正向交叉只统计 176 条 stable read operation，
`gravity run <operation-id>`、legacy promotion snapshot 和 SDK inventory snapshot 均不算分析动线。
实现前完整交叉为 `86 / 82 / 8`；8 条中只有 `report.company_amount.query` 同时具备成功非空与
分页证据、清晰独立语义和已批准投影，因此已通过 `reports usage` / SDK / Plan / Agent 四面闭环。
其余 7 条的边界与 blocker 以 [路线图](roadmap.md#stable-operation-正向交叉2026-08-14) 为准。

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
- auth/proxy 路由和写操作不属于普通读取缺口。前者保持 unsupported。写操作边界已经显式扩大，
  但只放行 7 条逐项登记的 Segment mutation：从漏斗、规则、历史版本或临时分群创建，规则/名称
  更新、手动刷新和带标记删除。推广投放、素材、多维报表、权限、事件/事件属性删除及其他未登记
  mutation 仍为 reservation/blocked write；范围依据是“补全探索式分析闭环”而不是 HTTP method。

## 四级能力状态

| 状态 | Agent 应如何处理 | 升级条件 |
| --- | --- | --- |
| stable executable | 可以发现、描述、校验和执行 | 持续通过合同、隐私和漂移检查 |
| stable projection gap | 端点可用，但部分响应字段仍 fail-closed | 已有成功、脱敏、非空字段证据即可深化 |
| catalog-only draft | 只报告为 capability gap，不提供执行 argv | 请求绑定、非空响应、分页、隐私、父依赖和权限证据齐全 |
| reservation / unsupported | 不作为待调用能力展示 | 新增 mutation 必须另行改变范围并完成写治理；unsupported 需先取得可执行合同 |

## 写操作边界（2026-08-16 裁决）

Segment 是当前唯一进入 stable manifest 的业务 mutation family。每次 create 都把可见的
`GSDK-<12 hex>` 放进 `segment_remark`，创建后经完整列表和 detail 读回；删除只接受 detail
读回仍带该标记的对象。所有 mutation 默认只生成零网络 dry-run，执行必须显式选择 `--execute`，
单次发送且不自动重放。标记用于识别 SDK 创建物，不过滤任何列表，也不是权限系统。

其余写路由不因本次框架存在而自动获准。尤其 110 条推广写、49 条素材写、多维报表写、权限管理、
`event/event_batch_delete` 与 `event_property_batch_delete` 继续 reservation；只有精确 source contract、
`effect=mutation`、stable/executable 状态及产品层确认流程同时成立时，运行时才会签发一次性写授权。

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
