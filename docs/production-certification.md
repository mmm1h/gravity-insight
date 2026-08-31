# 生产 Journey 认证

认证日期：2026-09-01
代码基线：`5895d927`
目标 App：`29034827`

本文只记录状态、结构证据和 HTTP receipt 引用。生产业务值、用户标识和原始响应均未写入本文或 Git。

## 1. 查询构造结论

结论：**有数据**。

固定结束日为 2026-08-30，以 `PresetAllCount/PresetAllCount` 查询下列 5 个业务事件。15 个事件/窗口组合均返回
`status=success` 和非空业务数据；具体值不记录。每个响应同时观察到 `/data/filter_agg_type` additive drift，故这些结果
证明数据可读，但不消除响应合同债。

| 事件 | 7 天（2026-08-24..30） | 30 天（2026-08-01..30） | 90 天（2026-06-02..08-30） |
|---|---:|---:|---:|
| `pay_click` | 有数据 | 有数据 | 有数据 |
| `prize_wheel` | 有数据 | 有数据 | 有数据 |
| `vip_gift_check` | 有数据 | 有数据 | 有数据 |
| `microgame_window_click` | 有数据 | 有数据 | 有数据 |
| `bingo_reward` | 有数据 | 有数据 | 有数据 |

代表性 receipt：7 天 `c96cf8cdc3ff42a783d8f5b1bc2a8cda`、30 天
`1f2dd5f5f22b4986a23655b6ba34f6c2`、90 天 `391cdaa424e040a096b03ab99eb3eb25`。这三个引用只用于证明请求确实发出并
收到响应，不包含业务值。

## 2. `upstream` 分类判定

判定：`$device_id + Count` 是 caller 侧无效的 metric 组合，不是可重试的 upstream 故障。

- scalar、并发 1 的失败请求仍被旧实现报为 `UPSTREAM_UNAVAILABLE/upstream/retryable=true`，receipt
  `7848a58075894a2b9d38ad13a970f721`。
- 同一事件、同一窗口改为 `PresetAllCount/PresetAllCount` 即成功。
- 保持 `$device_id` 不变、只把聚合改为 `DistinctCount` 即成功且非空，receipt
  `8a80ba31468e4944806a7af61d0828b1`。

已修复：本地字段策略和公开 JSON Schema 均拒绝精确的 `$device_id + Count` 组合，返回
`INPUT_INVALID/caller/field=target.name/retryable=false`，并明确建议 `DistinctCount` 或 `PresetAllCount`。修复后的 dry-run
无 HTTP receipt；测试覆盖失败分类、零派发及两个合法对照。

## 3. 全量 Journey 认证

`journey verify` 为 `valid`，包含 11 个机器合同和 69 条 ledger row。逐项 `can-run` 结果为
`success=0 / empty=0 / unverified=1 / blocked=10`；没有任何 Journey 得到 `can_run_status=verified`，因此没有合法的
Journey `run` 请求。

| Journey | 分类 | 具体原因 |
|---|---|---|
| `analysis.business-pulse` | blocked | `COMPLETENESS_INSUFFICIENT` |
| `analysis.event-trend` | blocked | `COMPLETENESS_INSUFFICIENT`；product-card fingerprint/validation 未满足 |
| `analysis.experiment-outcome-evaluation` | blocked | `OPERATOR_UNAVAILABLE` |
| `analysis.gravity.core.project-metric-contract-check` | blocked | dependency quarantined、semantic missing、Skill unresolved |
| `analysis.gravity.core.returned-filter-comparison` | blocked | dependency quarantined、Skill unresolved |
| `analysis.gravity.game.community-context-correlation` | blocked | dependency quarantined、context missing、Skill unresolved |
| `analysis.gravity.game.device-segment-event-review` | blocked | dependency quarantined、Skill unresolved |
| `analysis.gravity.game.revenue-forecast-readiness` | blocked | dependency blocked、model unvalidated、Skill unresolved |
| `analysis.ltv-curve-fit` | blocked | semantic missing、operator unavailable、model unvalidated |
| `analysis.merge2.ap-cost-anomaly-localization` | blocked | 输入有效；completeness insufficient、context provider unsupported |
| `analysis.readable-app-catalog` | unverified | `DEPENDENCY_VALIDATION_UNKNOWN` |

## 4. J7 的 190 项对账

本次只运行一次 `probe_all(max_workers=1)`。原始 envelope 状态为
`98 success / 75 empty / 13 permission_unavailable / 1 caller error / 3 contract_changed`，另有 17 条 additive drift。
为与 J7 的互斥五类口径一致，先判 breaking、再判 additive、最后判普通 success/empty，得到：

| 分类 | J7 | 本次 | 变化 |
|---|---:|---:|---:|
| success | 82 | 82 | 0 |
| empty | 74 | 75 | +1 |
| unverified | 14 | 14 | 0 |
| additive | 17 | 16 | -1 |
| breaking | 3 | 3 | 0 |
| 合计 | 190 | 190 | 0 |

其中 `material.local.list` 同时带 additive response-drift 记录和 breaking `contract_changed`，按更严重的 breaking 只计一次。
J7 的 14 条逐项身份未保存在当前仓库、Git 历史或本地 J10 产物中，因此无法证明哪一条发生了
`unverified -> success`，也无法证明 `additive -> empty` 的具体身份；unverified 净改善为 0。

本次仍 unverified 的 14 条如下。前 13 条均为 `PERMISSION_UNAVAILABLE` 且目标 operation receipt 为 0；这证明目标请求
未发出，但不足以区分账号权限和不可解析的最小父对象。最后一条为本地 caller 输入缺陷。

1. `analysis.dashboard.condition_favourite.default_to_me.get`
2. `analysis.dashboard.condition_favourite.list`
3. `analysis.dashboard.detail`
4. `analysis.dashboard.members.list`
5. `analysis.dashboard.space_members.list`
6. `analysis.order_split_detail.list`
7. `analysis.segment.detail`
8. `analysis.segment.history_version.list`
9. `analysis.segment.uid_result.list`
10. `analysis.segment.user_detail.list`
11. `analysis.user_detail.list`
12. `analysis.user_event.list`
13. `analysis.user_postback_log.list`
14. `analysis.segment.evaluate_percent`：live probe 名称超过本地 20 字符合同，`INPUT_INVALID/caller`、receipt 0；已缩短并加离线测试，未重复生产探测

`probe_all` 的合同使用 first-readable-app 父项解析，故本节只作为与 J7 同入口的 operation 回归证据，不作为目标 App 的
业务数据证据；目标 App 数据结论只使用第 1 节固定 App、事件和窗口的查询。

## 5. Issue #48 生产侧验证

在精确 POST 路由取得静态 `confirmed_read` 后，user-detail aggregate Plan dry-run 为 `validated`。两个有意设置的一页上限
均返回受治理的 `PAGINATION_LIMIT`，没有 `PLAN_ADAPTER_EXCEPTION`。最终使用最多 100 页、10,000 项、adapter concurrency 1
的有界 Plan，Plan 和 node 均为 `success`，结果 schema 为 `gravity-insight.user-detail-aggregate.v1`，包含
`pagination_audit` 和 43 个 read receipt。

结论：Issue #48 的 Direct/Plan result-envelope 崩溃在生产侧未复现，修复已通过真实只读 Plan 路径验证。分页完整性仍为
`unknown`，所以不能宣称取得完整用户全集。J7 旧逐项台账缺失，无法把该验证归因到某一条 J7 unverified transition。

## 6. 三项 breaking drift

三项均保持 breaking，不降级为 additive；根因分类均为 `cannot_determine`：

| operation | 当前证据 | 结论与缺口 |
|---|---|---|
| `material.local.list` | `contract_changed`；同时仅记录到 `/data/list/*/file_sub_type`、`/data/list/*/video_cover_list` additive 路径 | `cannot_determine`；缺 value-free breaking 字段/类型诊断和 last-known-good 结构，无法区分上游破坏性变化与我方投影错误 |
| `material.material_examine_user.list` | `contract_changed`，1 个 warning，无 response-drift 结构 | `cannot_determine`；缺当前响应的脱敏路径/类型 diff 和 last-known-good 结构 |
| `report.report.detail` | `contract_changed`，12 个 warnings，无 response-drift 结构 | `cannot_determine`；缺当前响应的脱敏路径/类型 diff 和 last-known-good 结构 |

## 7. Principal scope 不一致

根因：持久 metadata/catalog/field-policy 路径使用了包含 session principal 和 credential generation 的 runtime fingerprint。
第一次登录发现 principal、写入 token generation 后，同一配置账号的持久路径随之改变，离线进程因此看到 `missing`。

已修复：新增稳定的 `storage_fingerprint`，只绑定 env 文件位置、配置账号身份和 workspace；runtime/receipt 隔离继续绑定
principal 与 credential generation，账号切换仍改变持久 scope。使用 J10 的隔离 `LOCALAPPDATA` 后，不带 `--database` 的
`metadata status --app-id 29034827` 可找到原 catalog。测试位于 `tests/test_multiuser_isolation.py`，覆盖首次登录前后 runtime
scope 改变而 persistent catalog path 不变。

## 8. Stable contract 与 routes registry

两者职责不同，不应把 read operation 伪造为 `routes/registry.json` 的 `unsupported` 或 `blocked_write` 条目：

- `routes/registry.json` 是负向 disposition registry，当前 schema 只登记 `blocked_write` 和 `unsupported`。
- exact stable executable read contract 是正向授权来源；Census 的 `_route_match` 在负向 classification 前处理
  `exact_stable`。
- `probing.md` 规定安全 GET/HEAD/OPTIONS 可直接成为 `verified_read`；未由精确稳定合同证实的 POST 才必须保持
  `unsafe_unknown`，或以精确 `method + path` 的静态 `confirmed_read` 收口。

因此 4 个 metadata GET（`analysis.event.list`、`analysis.user_property.list`、`analysis.event_property.list`、
`analysis.event_property_group.list`）由安全方法和 stable contract 授权，不写入负向 registry。为消除 POST 入口之间的解释差异，
已为 event/funnel/retention/scatter/property/user-detail 六个精确 POST 路径加入带 reviewer、ISO 日期和静态控制流证据的
`confirmed_read`；相邻路径仍为 `unsafe_unknown`。

## 9. 门禁

最终执行 pytest、unittest、compiler check、quality check、CLI help 和 `git diff --check`。精确的本趟前后计数保留在
`tmp/certification-matrix.json` 和交付回复中，不把易漂移的测试规模固化为长期文档常量。

## 10. 未解决部分

- 11 个 Journey 仍为 `0 success / 0 empty / 1 unverified / 10 blocked`，具体阻塞见第 3 节。
- J7 旧逐项身份缺失，无法给出逐条 transition，只能给出同口径净变化和当前名单。
- 三项 breaking 的 value-free 结构诊断不足，均保持 `cannot_determine`。
- Issue #48 的分页完整性仍为 `unknown`。
- event query 的 `/data/filter_agg_type` additive drift 尚未纳入稳定响应投影。
- `analysis.segment.evaluate_percent` 的 live-probe caller 缺陷已离线修复，但按单次探测纪律未做第二次生产请求。
