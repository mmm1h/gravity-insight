> 归档材料：保留历史决策与取证，不代表当前接口或状态；当前入口见 docs/index.md。

# 结果信封该说的没说出来

- 日期：2026-08-19
- 任务：#227
- 结论：analysis 结果信封现带 `interpretation`（漏斗不返率 + 两种分母 + 指标可加性）；Plan 运行时失败保留 `error.message` / `error.next_action`，仍不回显 request。

## 先量：一次典型 analysis 结果里，调用方判断可信度要看什么

对象是 `gravity analysis query` / `sdk.analysis_query` / Plan `analysis_query` 拿到的那份结果。agent 走 `plan run` 时不再读 describe。

| 需要知道的事 | 现在结果上有没有 | 修前写在哪 | 修后 |
| --- | --- | --- | --- |
| 漏斗有没有转化率 | 无（只有人数） | spec notes / describe / 产品卡 | 有：`interpretation.returns_conversion_rate=false` |
| 若自算率，两种合法分母是什么 | 无 | spec notes `rate_denominators` | 有：`previous_step` / `first_step` |
| 这个指标能不能跨维加总 | UV 无声明；4 个登记可加指标只在对不上时事后报警 | `dimension_sum_audit` 白名单；UV 明确不参与也不标记 | 有：`interpretation.metrics[].additivity` = `additive` / `non_additive` / `unknown` |
| 导出是否被截断 | 有（本趟不碰） | `completion_status=truncated` | 不变 |
| 死字段能不能当证据 | 有（本趟不碰） | `unreliable_item_keys` + `warnings` | 不变 |
| 数从哪条产品合同来 | 有 | `result_source.tier` | 不变 |
| 相对日期解析成了哪一天 | CLI 覆盖时有 | `resolved_date_window` | 不变 |
| 分维组标签还在不在 | 有（#215） | 投影留下的组键 | 不变 |
| 运行时失败下一步怎么改 | 无 | 预检有 `message`/`next_action`；`safe_analysis_envelope` 丢掉它们 | 有：运行时 `error` 保留这两项；`result` 仍为 `null` |

修前缺 3 件（无率、分母、UV 不可加）加 1 件运行时自纠。修后这 4 件都在结果上。

不做：SDK 代算转化率；新建 metrics 引擎；对 UV 做假的「各组之和」验收。

## 修 A：声明抬到结果

新字段 `interpretation`，合同 `gravity.analysis-interpretation.v1`。现有字段语义不变，只追加。

- 漏斗：`returns_conversion_rate=false`、`rate_denominators`、`window_funnel_mode=4`、`count_meaning`、`denominator_required`。与 `analysis_query_spec_schema()["kind_schemas"]["funnel"].notes` 同源（`FUNNEL_RESULT_NOTES`）。
- 每种请求指标：`field` / `aggregation` / `additivity`。`PresetUserCount` 与 Distinct/Avg 族为 `non_additive`；`PresetAllCount` / `Count` / `SumCount` 为 `additive`；其余 `unknown`。
- 挂点：`sdk.analysis_query`、CLI compact query、跨期 compare、Plan `analysis_query` 成功信封。`safe_analysis_envelope` 白名单放行 `interpretation`。
- 不代算率，不插入率字段。

## 修 B：运行时失败保留下一步

核实 #225 仍成立（2026-08-19 源码）：

1. `plan_analysis_adapter._SAFE_ERROR_FIELDS` 只有 `category/code/field/retryable/retry_after_ms`。
2. `status=error` 走 `_BREAKING_STATUSES`，被 `_safe_drift_error` 盖成合同漂移套话。
3. 即便信封留下了 `message`/`next_action`，`plan_execution.safe_native_error` 也丢弃它们，改写成 `Plan adapter reported a failure.` + 分类套话。
4. `result=null` 是刻意的，保留。

修法：

- 漂移状态仍用漂移套话（不把上游/业务值拷进 message）。
- `error` / `failed` / `unavailable` 走运行时通道，拷贝已有 `message`/`next_action`。
- Plan 节点失败从 adapter 信封取出这两项，不再盖套话。
- 成功/失败都不回显 `request`。

为不把 `plan_execution.py` 再顶到 500 SLOC，错误细节抽到 `plan_error.py`；`plan_execution` 再导出同名符号。

## 测试红→绿

红是只加测试、未改源码时跑的。绿是加上声明与错误传递后同一两条。

| 测试 | 红 | 绿 |
| --- | --- | --- |
| `test_analysis_result_declares_funnel_rates_and_uv_additivity` | `KeyError: 'interpretation'` | `ok` |
| `test_plan_runtime_error_keeps_message_and_next_action` | `AssertionError: 'Gravity rejected the read operation.' != 'The Analysis response no longer matches its governed contract.'` | `ok` |

摘要行：

- 红：`Ran 2 tests … FAILED (failures=1, errors=1)`
- 绿：`Ran 2 tests … OK`（同文件两条）

## 生产验证（A）

读 **2** 次，全部 App `29034827`，窗 `2026-08-13..2026-08-19`。写 0。未打 `promotion.*`，未枚举另外 6 个空 App。

| # | 形状 | 试过的请求 | 响应（只写结构） | 因此确定 |
| --- | --- | --- | --- | --- |
| 1 | 漏斗 | kind=funnel；两步 `$UserFirstRegister` → `$AdClick`；指标 `PresetUserCount`；`window={unit:day,value:7}`；`time_grain=day` | `status=success`，`window_funnel_mode=4`，`data` 键为 `aggregate_date` / `aggregate_by_date` / `date_list` / `window_funnel_mode`；`data` 下无 conversion/rate 键；两步人数均为正 | 声明 `returns_conversion_rate=false` 与实际响应对得上；SDK 没有插入率。`interpretation.metrics[].additivity=non_additive` |
| 2 | 事件 UV 分维 | kind=event；`$UserFirstRegister` + `PresetUserCount`；`group_by=[{field:$os,source:user}]`；同窗 | `status=success`；`data.list` 非空；行上有 `用户.` 组标签；`interpretation` 无率字段；该指标 `additivity=non_additive` | UV 在结果上被标成不可跨维加总。调用方不必再读 describe |

未再换事件、未换窗。漏斗 `aggregate_date.total` 的键序不是步序，本趟不把「dict values 是否单调」写成事实。

## 推测 / 确凿

确凿：

- 修前结果信封没有漏斗率声明、没有 UV 可加性声明；Plan 运行时失败丢掉 `message`/`next_action`。
- 修后 SDK / CLI compact / Plan 成功信封都有 `interpretation`。
- 投放中抖音 App 上漏斗无率字段、UV 声明为 `non_additive`，与信封一致。
- 运行时失败 `result` 仍为 `null`，request 不回显。
- 错误库存仍是 `1268 = A1018 / B250 / C0`。未新增 raise。
- 质量门禁 `operation_literals=36`。`quality-baseline.json` 无 diff（无 `hard_limit` / `threshold` / `max_` 改动）。
- unittest `1291`（基线 1289 + 本趟 2）。pytest `1291 passed`。development 评测选择层仍 `277/336`。

推测：

- `MaxCount` / `MinCount` / 分位数标 `unknown`，因为本仓没有「跨维能不能加」的生产证据。不要把它们写成可加。
- 报表类 `dimension_sum_mismatch` 仍只覆盖 4 个登记可加指标；analysis UV 走声明，不走那个事后求和。

## 没修什么

- 不碰缓存 / metadata 预取（#228）、gap 导航（#229）、产品卡边界、评测装置与题集。
- 不动 `docs/roadmap.md`。不 push、不碰 GitHub。
- 不代算转化率，不建语义层。
