# 路由盘点

Census 从公开前端静态资源发现候选路由，并与 SDK 合同对账。它用于发现和漂移分析，不会自动把候选接口升级为 stable。

## 安全范围

- `fetch` 只下载公开 HTML 与 bundle；
- `parse`、`params`、`responses`、`coverage`、`diff`、`impact` 是离线处理；
- 不携带 Gravity 账号凭据调用候选 API；
- 不把字符串命中直接解释为可调用接口。

## 标准流程

```powershell
gravity census --smoke
gravity census fetch --help
gravity census parse --help
gravity census params --help
gravity census responses --help
gravity census coverage --help
gravity census diff --help
gravity census impact --help
```

先查看每个子命令的 `--help`，为 snapshot、raw 和 output 使用显式临时路径。不要覆盖仓库内基线，除非当前任务就是更新基线且证据已审查。

```text
fetch bundles
  → parse route candidates
  → extract request/response consumers
  → reconcile with manifests
  → diff snapshots
  → map impact to operation IDs
```

## 抓取失败诊断与定时告警

需要机器判定失败原因时，为 `fetch --require-complete` 传入
`--failure-output <path>`。该文件与 stderr 使用稳定字段：

- `code`、`category`、`retryable`、`failure_class` 和 `next_action`；
- 熔断时的 `lane.host`、不可逆 `host_key`、`operation_class`、`profile`；
- `failures[]` 中按发生顺序记录的 `failure_index`、HTTP `attempt`、
  `status_class`、可用时的 `http_status`，以及仅 transport failure 才有的
  `exception_type`；
- `cooldown_remaining_ms`。

诊断只保留规范化 host，不保留 URL path、userinfo、query/fragment、header、凭据、
异常 message 或响应值。`failure_class=upstream_capacity` 仅在所有致因都是
`transport_error`、`rate_limited` 或 `server_error` 时成立；混合失败、请求预算耗尽、
入口抓取期间变化和其他 completeness failure 都不是容量降级。

每小时 workflow 在入口变化后最多跑三轮 crawl，每轮对单个资源只尝试一次，并复用同一 raw
目录中已成功下载的 bundle；因此外层退避不会再叠加默认的三次资源内重试。容量失败按报告的
30 秒冷却退避，单次等待最多 60 秒。三轮仍为容量失败时，workflow 上传
`fetch-failure.json`，发出 GitHub warning 并明确“不作 route-drift 结论”，但不制造 hard
failure。任何非容量型不完整仍 fail-closed，并要求维护者检查 snapshot 和失败报告后重跑。

Governor 的阈值 3 和冷却 30 秒按实际 HTTP attempt、同一 scope/host/operation/profile lane
计算。对批量 crawl，这个阈值用于在一个资源耗尽既有三次尝试或多个并发资源连续失败后停止继续
打压同一 host；已经在途的请求不会被取消。阈值本身不按 bundle 数放大，因为数百个资源不是
数百个独立上游容量域。CLI 遇到熔断会终止本轮 crawl，所以冷却由定时 workflow 的有界退避承接。
若未来需要在单进程内续跑，应先实现显式 checkpoint/resume 和全局请求预算，不能单纯抬高阈值。

## 解释 coverage

### 强制覆盖边界

`bundle-snapshot.json.summary.complete=true` 只表示**该次入口可静态递归发现的同源 JS 图**无
pending/failure，且抓取期间入口 HTML 稳定；它不表示平台、租户、角色或全部后端路由完整。
生成的 `routes.json.source` 以
`coverage_scope= "same_origin_static_js_graph_discoverable_from_site_entry"` 和
`platform_complete=false` 固化这个区别，消费方不得从 `bundle_complete=true` 反推平台完整。
任何引用 Census 数字的结论都必须同时写明：

- 分母是冻结 snapshot 内的 route，不是平台总路由；
- 对应 `bundle_id` 或抓取时间；
- 入口、同源静态图和 parser 已知边界；
- “未出现”只能解释为“该范围内未观察到”，范围外未知。

覆盖率可用于同一 snapshot 内的合同对账和漂移比较，不能用于声称“平台只有这些路由”或
“某能力不存在”。完整审计与推荐措辞见归档的
[Census 完整性与分母审计](../archive/research/census-completeness-audit.md)。

- `covered`：已登记 stable，仍需关注响应字段和上游 hash 漂移；
- `uncovered_read`：安全 HTTP 方法，或 exact POST 已有带 reviewer/日期/控制流的 read confirmation；
- `static_read_candidate`：未知方法但静态信号指向读，只能继续静态取证；
- `unsafe_unknown`：POST 只有未验证读信号，既不是 read 也不是 mutation 结论；
- blocked-write / blocked-privacy：明确保留，不应追求 callable；
- 其他 unknown：进入人工分类，不直接生成通用 operation。

`semantic_evidence` 还表示证据强度，而不是可探测性授权：

- `safe_http_method`：GET/HEAD/OPTIONS 的 HTTP 读语义证据；
- `route_registry:read_contract_not_verified`：维护者登记的读合同声明；
- `read_action_path_token`：仅由 `/list`、`/get`、`/query` 等路径词元推断的弱证据。

最后一类若同时为 POST，Census 直接给出 `unsafe_unknown`；只有
`probe-read-confirmations.json` 中 exact `method + path` 的完整静态确认才进入 `uncovered_read`。
Draft selector 只消费 `uncovered_read`，因此不会再把弱 POST 变成 read draft。Prober 仍独立校验同一
确认文件和 exact stable 合同，Census status 不是在线授权，也不能反向批量标成 mutation。

2026-08-20 在 `dev@b7c15ed` 对冻结 987-route snapshot 与当前 237-operation manifests 重算：改规则前
`uncovered_read=329`，其中 POST 211；严格的“唯一证据为 `read_action_path_token`”POST 是 **203**，
历史 214 已不再是 HEAD 数字。规则化重算后，21 条 exact confirmed POST 与 57 条安全方法保留为
`uncovered_read=78`；190 条未确认 POST 为 `unsafe_unknown`，61 条未知方法读信号为
`static_read_candidate`。总路由和 accounted 均保持 987，没有逐条手改或静态升级证据。

2026-08-14 的历史 12 条静态抽样仍为 2 写 / 10 真读 / 0 不确定；它只证明路径词元不能裁决 POST，
不证明多数条目是写。逐项采样记录是可丢弃的临时工件，不作为当前分类台账。

## 更新仓库数据

应用新路由或响应字段前：

1. 保存来源 snapshot 与 hash；
2. 检查 diff 是否只包含目标上游变化；
3. 对受影响 operation 运行合同和投影测试；
4. 新字段先完成隐私分类；
5. 运行 compiler、quality、完整单元测试和 `git diff --check`。

生产页面确认仍受 [探测安全](probing.md) 约束。

## 请求提取器的已知诊断边界

`route-params.json` 的 `analysis.unresolved_reasons` 只保留 occurrence 级原因。表达式级
`unresolved_body_expression` 位于提取期间的内存 shape，输出时只折叠进
`analysis.unresolved_calls` 计数；因此不能用 JSON 文本 grep 统计该原因。需要诊断时必须用与
`bundle-snapshot.json` 逐文件 hash 一致的 raw bundle 重放当前提取器，同时分别报告 route、
occurrence/call-site 和 coverage 分类，不能把三个口径混用。

2026-08-14 的同快照杠杆评估得到：`load_alias_has_no_static_call` 为 97 route / 123 occurrence，
`unresolved_body_expression` 为 60 route / 82 call site；与 15 条完全缺失和 12 条部分闭环动线的
当前 blocker 交叉均为 0。函数内联与条件 callee 因而暂不实现；未来只有在它们能移除多条排期
动线的当前 blocker 时再重评，不能因静态命中规模大就扩张为通用 JS 求值器。

**杠杆低的原因是分布，不是数量**——两类失败绝大多数落在本就不追的区域：

| 失败类型 | 写操作 | 已覆盖 | 未覆盖读 | auth/proxy | export |
| --- | ---: | ---: | ---: | ---: | ---: |
| `load_alias_has_no_static_call`（97 route） | 49 | 23 | 17 | 7 | 1 |
| `unresolved_body_expression`（60 route） | 45 | 7 | **1（D35）** | 3 | 4 |

本表是当轮静态提取优先级快照；其中写操作不是取数缺口。后续范围裁决只把 7 条已取得完整 wire
证据的 Segment mutation 提升为 stable，表内其余写（尤其推广/素材）继续 reservation；auth/proxy
保持 unsupported，已覆盖的 route 不需要再提取。
当时真正相交的只有默认值字典与 D35，而这两条卡的是**服务端语义与非空证据**，不是静态提取
能力。2026-08-16 两条都靠后续生产证据晋升；新证据不来自提取器，因此不改变上述杠杆裁决。
复算方法见上一段，逐 route 明细不入库（随 bundle 变化即过期）。
