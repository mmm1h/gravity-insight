> 归档材料：保留历史决策与取证，不代表当前接口或状态；当前入口见 docs/index.md。

# B 级错误补实际值

- 日期：2026-08-19
- 任务：#219
- 结论：离线审计把 121 条 B 升到 A；库存现为 `1268 = A1017 / B251 / C0`。C 仍为 0。

## 确凿事实

- 请求：0 次生产读。全部离线：`scripts/audit_actionable_errors.py` 扫 `src/gravity_sdk` 的显式 caller raise。
- 开工库存：`1268 = A896 / B372 / C0`（`tests/test_actionable_error_audit.py` 钉住值，`dev@53f3d86`）。
- 收工库存：`1268 = A1017 / B251 / C0`。总数未变，没有新增 raise。C 仍为 0。
- 审计器判据未改。`has_actual` 仍只认 `actual value` / `observed value` / `actual_value(`。
- 本轮只改错误消息里的实际值，且只在 agent / find 之外的校验面。未改投影合同、路由、评测、`docs/roadmap.md`。

## 372 条 B 按缺 `actual` 的原因

| 类别 | 条数 | 典型例子 | 本轮处理 |
| --- | ---: | --- | --- |
| 纯粹漏写：值已在作用域 | 226 | `_field_policy_shared.require_exact_mapping` 不报多余键；`operation_manifest_parse.validate_input_field` 不报 `None`/`scatter`；`pagination_inputs` 不报 `page=0` | 主战场。补类型和/或值后升 A |
| 形状错误但正文故意不回显业务值 | 16 | `validate_analysis_conditions` / `group_by_list` / `user_filtering`：「values are not echoed because errors may enter logs」 | 只回显类型或长度（`str` / `21`），不回显条件值。升 A，仍不打印业务数据 |
| 凭据 / 用户标识字段名 | 2 | `reject_sensitive_analysis_field`、`reject_sensitive_metadata_fields` | 只回显被拒字段名，不回显元数据 remark。升 A |
| agent / find，本批并发边界 | 14 | `agent.py` continuation、`find.py` backend | 分类记账，不改 |
| `http_runtime` SQL 体：AST 硬顶 | 4 | `Gravity SQL tabId must be the fixed value 1` | 加 `actual` 会把 `http_runtime.py` 推过 `ast_hard_limit=3815`。保持 B |
| Plan / `read_cli` 面 | 118 | `plan_adapters.py`、`plan_*_adapter.py` | 本批并发边界外，不改 |
| 其余产品面未升 | 约 92 | `resolver_*`、`catalog.py`、`multidim_*`、`template_replay*`、`receipt_query.py` | 多数仍是纯粹漏写，留给下一批。本轮不追求 B=0 |

条数按开工库存归类；升 A 的 121 条全部来自前三类里本轮允许改的模块。

## 本轮升了什么

- 升 A：**121**（`B372 → B251`）。
- 代表消息（离线构造，非生产响应）：
  - `app_id=123` → `actual value: 123; analysis app_id must be a bounded identifier`
  - `query_id="not-an-id"` → `actual value: "not-an-id"`
  - `group_by_list` 长度 21 → `actual value: 21`（不回显组内容）
  - `InputField(kind).validate(None)` → `actual value: null`
  - `InputField(kind).validate("scatter")` → `actual value: "scatter"`
  - `attribution_snapshot(..., app_id="abc")` → `actual value: "abc"`
  - `normalize_material_platforms(["nope"])` → `actual value: "nope"`
- 过滤值、条件值、账号标识仍不进消息。现有 `test_condition_error_sanitizes_value_and_bounds_authoritative_candidates` 仍要求 `do-not-log-this` 不出现。

## 剩下 251 条为什么不该在本轮升

- **14** agent / find：`#216` / `#218` 正在改，本批明确不碰。
- **118** Plan 适配器与 `read_cli`：本批并发边界外。
- **4** `http_runtime.py` SQL 校验：legacy AST 硬顶 `3815`，当前 `3755`。补 `actual_value(` 实测到 `3821`，超过硬顶。放宽 hard_limit 等于本单元失败。
- **约 115** 其余产品面（resolver / catalog / Multidim / template replay / receipt / segment 等）：多数仍是纯粹漏写，但本轮优先 field-policy / analysis / operation 输入这些 agent 最常撞的校验。不追求 B=0。

## 质量棘轮

- `src/gravity_sdk/models.py` AST：`6302 → 6522`。硬顶仍是 `8647`。台账一条：给 `OperationSpec` 输入、`date_list`、filter 校验补 sanitized `actual_value`。
- 未改任何 `hard_limit` / `threshold` / `max_`。`client.py` 未动（`6764 / 6765`）。
- `http_runtime.py` 的 4 条 SQL B 因硬顶回退，AST 回到 `3755`。

## 推测（不是事实）

- 剩余 resolver / catalog / Multidim 的 B，下一轮多半仍可按「类型 + 值 / 类型 + 长度」干净升级。
- Plan 适配器里不少是 `must correct: str(exc)` 包一层，值可能已经在内层异常里；是否算审计器误伤要单独贴 raise 消息再裁决，本轮未改判据。
