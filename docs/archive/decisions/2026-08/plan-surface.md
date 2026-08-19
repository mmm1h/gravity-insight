> 归档材料：保留历史决策与取证，不代表当前接口或状态；当前入口见 docs/index.md。

# Plan 面：agent 能不能自己搭一条多步分析并跑完

- 日期：2026-08-19
- 任务：#225
- 结论：能搭、能跑完，但只能手写完整 literal spec；中间结果绑不进 `/spec`。`plan schema` 现在写出这条合同，绑错会列出允许 target。

## 调用方走法（不读 `src/` 直到卡住）

任务：近 7 天 `$UserFirstRegister` 趋势 → 按 `$os` 分维 → 与前 7 天同口径对比。App 固定投放中抖音版 `29034827`。日期按当日 Asia/Shanghai：当前 `2026-08-13..2026-08-19`，对照 `2026-08-06..2026-08-12`。

| 步 | 想干什么 | 怎么知道该怎么写 | 实际发生了什么 |
| --- | --- | --- | --- |
| 1 | 找 Plan 入口 | `docs/index.md` → 上手包 / `agent-workflow.md` §3 / `reference/plan.md` | `gravity plan {schema,run}`；无 `--spec-schema`，机器合同是 `gravity plan schema` |
| 2 | 找事件 spec 形状 | `analysis query --kind event --spec-schema`；`agent-catalog describe analysis.query.spec:event` | spec 要 `start/end/steps`；`group_by` 要 `field+source`；describe `next.argv` = `gravity plan run --input <plan.json>`，另给 `schema_argv` 指向 `--spec-schema` |
| 3 | 确认物理事件 / `$os` | `metadata search Register --app-id 29034827`（`--kind` 不是 search 的 flag） | 本地 catalog 有 `$UserFirstRegister`；`$os` 同时是 event_property 和 user_property。catalog `stale`（synced 2026-08-13），本趟未再 sync |
| 4 | 把 metadata 命中绑进 spec | 文档写 binding 是 RFC 6901 标量；schema 只说 `fields/from/source/target`，**不写各 composite 允许哪些 target** | dry-run `field=nodes[1].request.bindings`，文案「remove the extra binding」，**不列允许 target**。文档后文才写 v1 不写 `/spec/...` |
| 5 | 手写 4 节点 Plan | 文档：`analysis_query` request = `name/kind/app/spec`，可选 `start/end`；describe 另有 `compare_start/compare_end` | dry-run `status=validated`。`compare_*` 在 Plan composite 里被接受（adapter 白名单有这对字段，schema 原先没写） |
| 6 | 真跑 | `plan run --input tmp/plans/02-trend-os-compare.json --concurrency 4` | 顶层 `ok=true` `exit_code=0` `success_count=4` `failure_count=0` `empty_count=0` |

PowerShell 内联 JSON 会吞 `$UserFirstRegister`。必须写文件。

## 发了什么请求、拿到什么响应

全部只打 `29034827`。写 0。生产读 3 次 analysis query（趋势、分维、跨期对比各 1；对比节点内部再打对照窗，计入该节点）。metadata 节点离线。

| 节点 | kind | 窗 | 结果 |
| --- | --- | --- | --- |
| `find_event` | `metadata_search` | 无 | `status=success`，`total=1`，`name=$UserFirstRegister`。catalog `synced_at=2026-08-13T03:59:40Z` |
| `current_trend` | `analysis_query` event，无分维 | 08-13..19 | `analysis.event.query` success。7 个按日点均非空，有阶段总和，`page=null` |
| `current_by_os` | 同上 + `group_by=[{field:$os,source:user}]` | 08-13..19 | success。行上有组标签（展示名，不是 `$os`）。warnings：`unregistered analysis response data keys were omitted (count=2)` |
| `compare_by_os` | 同上 + `compare_start=08-06` `compare_end=08-12` | 双窗 | success。信封有 `windows` 与 `delta.items[]`（含绝对/相对变化）。对照窗 `page=null`。同警告 count=2 |

`depends_on: [find_event]` 只做门闩：查不到事件则下游 `skipped/DEPENDENCY_FAILED`。事件名仍是提交前写死的 literal。`/app` 绑定 dry-run 通过（`04-bind-app.json`，预算要从 200 提到 400，否则 `budget.max_total_items` 拒）。

未再枚举另外 6 个空 App。未打 `promotion.*`。

## agent 靠什么知道该怎么搭

判据：只读信封和文档、没读过源码的 agent，**能搭出可跑的 sibling/依赖门闩 Plan，不能把上一步结果写进下一步 spec**。

| 问题 | 答案 |
| --- | --- |
| 输入形状从哪查？ | 有。`gravity plan schema` → `gravity.plan-schema.v1`。Analysis spec 另有 `--spec-schema`。describe 卡给 `input_schema` + `input_template` + `period_compare` |
| 节点之间怎么传中间结果？写在哪？ | `docs/reference/plan.md` + CLI 参考：`bindings`/`foreach`，标量，`from` 必须在 `depends_on`。**修前** schema 不写各 composite 允许 target。**修后** `composites.analysis_query.binding_targets=["/app"]`，`spec_binding=false` |
| 节点失败信封够不够自己修？ | 预检：`INPUT_INVALID` + `field` + `next_action=Correct the gravity.plan.v1 document`。修前绑 `/spec` 不列允许值。修后带 `actual value` 和 `allowed value: "/app"`。运行时失败：`result=null`，不回显 request/binding；依赖失败 `skipped/DEPENDENCY_FAILED`。`safe_analysis_envelope` 的 error 只留 `category/code/field/retryable/retry_after_ms`，**丢掉 message/next_action** |
| `gravity agent` 的 `next.argv` 会不会指向 Plan？接得上吗？ | 会指 `gravity plan run --input <plan.json>`。`plan_node` 只有 `{kind:composite, request:{name,kind}}`，缺 `app/spec/compare_*`。批量发现给 `analysis_query_batch` 模板，占位符仍要调用方填。分维那句英文落到不可执行 `analysis.task.handoff`，`plan_node=null`，但 `next.argv` 仍指向 Plan |

所以：能搭「已知 spec 的多节点 DAG」；不能从发现信封自动长出可执行多步 Plan。缺的是 (1) 各 composite 允许 binding 的机读表（本趟补了 analysis_query）；(2) 发现卡交出的是残缺 `plan_node`；(3) 运行时失败信封不够自纠。

## `fetch_strategy` 死名

**确认不成立（作为仍存活的死名）。** 从家族 A 划掉这一例。

确凿：

- `pagination.py` / `pagination_policy.py` 写出的是 `single_page` / `serial_known_total` / `parallel_known_total` / `serial_unknown_total` / `stopped_missing_total_page`。源码里已无 `single`/`serial`/`parallel` 作为策略名。
- Plan 投影 `plan_multidim_result._safe_page` 在 `ef2c9f0`（#212 / `consumer-affordances`，2026-08-18）已改成上述五词。测试 `test_plan_page_keeps_observed_fetch_strategy` 钉 `single_page`。
- 产品信封 `composite_result._safe_page` **本来就不投影** `fetch_strategy`。这不是死名，是产品面选择。
- 本趟事件查询 `page=null`，没有策略字段可丢。

调用方因此得到的错误结论：在 #212 之前，Plan 里的 multidim `page.fetch_strategy` 会被静默丢掉。HEAD 上这条已经修过。本趟不改投影。

## 修了什么

只动 Plan 面，让 agent 在绑错时能自己改，而不是猜。

1. `plan_schema()` 增加 `composites.analysis_query`：`binding_targets`、`spec_binding=false`、`request_fields`（含跨期字段）。不放宽任何 binding。
2. `validate_exact_targets` 拒绝时带 `actual value` + `allowed value`。具体压过通用：只列出该 adapter 白名单，空白名单写成 `no binding targets`。
3. 文档 `reference/plan.md` / `reference/cli.md` 指向同一 schema 字段。

未拆 `plan_adapters.py`（SLOC 498，阈值 500，本趟未再往里加行）。未改公开 API 形状。

## 测试红→绿

| 测试 | 红 | 绿 |
| --- | --- | --- |
| `test_plan_schema_declares_analysis_query_binding_contract` | `KeyError: 'composites'` | `Ran 3 tests … OK` |
| `test_analysis_query_rejected_binding_lists_allowed_targets` | 文案无 `/spec/steps/0/event`、无 `"/app"` | 同上 |

红是改测试、未改源码时跑的。绿是加上 schema + `validate_exact_targets` 文案后同一 3 条（含原 drift 守卫）。

错误审计：`1268 / A897 / B371 / C0`（原 `A896 / B372`）。`validate_exact_targets` 那一处从 B 升 A。C 仍为 0。

## 生产预算

读 3 次产品查询，全在 `29034827`。写 0。未碰实时事件写开关、未碰导出 create。

## 推测 / 确凿

确凿：4 节点 Plan 生产 4/4 success；`/spec` 绑定预检拒绝；`/app` 绑定预检通过；跨期字段在 Plan composite 上可执行；`fetch_strategy` 五词已在 Plan 投影放行。

推测：`current_by_os` / `compare_by_os` 的 omitted count=2 仍是 `union_groups`/`y`（#215 已记）。未拆响应原文，故不新登记。分维问法落到 `analysis.task.handoff` 是识别器问题，归 #218 路由臂，本趟不改。

## 没修什么 / 下一步

- 不把 `/spec/...` 写成可绑定。那是能力扩张，不是自纠。
- 不改 `safe_analysis_envelope` 丢掉 `message`/`next_action`（运行时失败仍不够自纠）。
- 不改 agent 卡残缺 `plan_node`、不改识别器、不改 `docs/agent-skills/` 生成器。
- 不拆 `plan_adapters.py` / `plan_execution.py`（500 / 498）。下趟若再往接线文件加 composite，先拆再加。
- 不动 `docs/roadmap.md`。不 push、不碰 GitHub。

动线表头 `56 = x / y / z` **不要改**。本趟只在「看某事件…」和「比较两个时期」两行阻塞栏追加证据，状态列仍是已闭环，冻结 case 对得上。
