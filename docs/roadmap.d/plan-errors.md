# Plan 适配器安全实际值

- 日期：2026-08-19
- 任务：#232
- 结论：两趟合计把 Plan 范围 B 从 102 降到 14；第二趟逐条裁决 71 条，60 条升 A、11 条因业务 actual 保持 B，全仓为 `1268 = A1106 / B162 / C0`。

## 确凿事实

### 第一趟基线

离线运行 `PYTHONPATH=src python scripts/audit_actionable_errors.py --json` 的最初基线为
`1268 = A1018 / B250 / C0`。第一趟在 28 个调用点增加受控摘要：未知字段只显示字段名列表，
名称错误显示实际名称，预算错误显示 `(实际数, 上限)`，运行期结果错误只显示类型。第一趟结束时
全仓为 `A1046 / B222 / C0`，Plan 范围 B 为 74。

### 第二趟请求与审计

第二趟生产读写请求均为 **0**。未运行 holdout/final，未读取 key 或 sealed JSON，未修改审计器、
识别器、词表、路由、`plan_saved_analysis_adapter.py` 或 `plan_kanban_mutation_adapter.py`。

同一离线审计从 `A1046 / B222 / C0` 变为 `A1106 / B162 / C0`；总调用点仍是 1268，C 仍为 0。
Plan 范围剩 14 条 B：本轮确认不应回显的 11 条，以及让给 #234 的 saved-analysis 3 条。

### 原 58 条逐点裁决

下表行号均为第二趟基线 `584dcaa` 的原行号。A 只摘要结构，不复制 request value 或上游异常；
B 保持原审计等级。

| 站点 | 裁决 | actual 来源或保持 B 的原因 |
| --- | --- | --- |
| `plan_advertiser_profile_adapter.py:30` | A | 多余请求键名列表，不显示对应值。 |
| `plan_advertiser_profile_adapter.py:40` | B | `start/end` 是调用方日期值；底层异常可能包含原日期。 |
| `plan_analysis_adapter.py:104` | A | 固定 composite 名称。 |
| `plan_analysis_adapter.py:134` | A | `output_fields` 是结构字段名列表。 |
| `plan_analysis_adapter.py:139` | A | 只显示已出现的 `compare_start/compare_end` 字段名，不显示日期。 |
| `plan_analysis_adapter.py:295` | A | 实际结果 Python 类型名。 |
| `plan_bilibili_account_performance_adapter.py:57` | A | 请求键名列表。 |
| `plan_bilibili_account_performance_adapter.py:62` | A | 固定 composite 名称。 |
| `plan_bilibili_account_performance_adapter.py:85` | B | 执行期绑定后的 `start/end` 是业务日期。 |
| `plan_bilibili_account_performance_adapter.py:104` | A | `(实际 item_count, max_items)`。 |
| `plan_bilibili_account_performance_adapter.py:144` | B | 预检 `start/end` 是调用方日期，底层异常可能带原值。 |
| `plan_dashboard_analysis_adapter.py:113` | A | 固定 composite 名称。 |
| `plan_dashboard_analysis_adapter.py:126` | A | `(实际 max_items, 固定最小量 3)`。 |
| `plan_dashboard_snapshot_adapter.py:71` | A | 固定 composite 名称。 |
| `plan_dashboard_snapshot_adapter.py:87` | A | `(实际 max_items, 固定最小量 7)`。 |
| `plan_material_performance_adapter.py:52` | A | 多余请求键名列表。 |
| `plan_material_performance_adapter.py:56` | A | 固定 composite 名称。 |
| `plan_material_performance_adapter.py:77` | A | 受控 platform 枚举值。 |
| `plan_material_performance_adapter.py:79` | A | `(platform_count, max_items)`。 |
| `plan_material_performance_adapter.py:119` | A | `(实际 item_count, max_items)`。 |
| `plan_material_performance_adapter.py:137` | B | 成对日期窗是调用方业务日期。 |
| `plan_material_performance_adapter.py:143` | B | 单个动态边界日期仍是调用方业务日期。 |
| `plan_multidim_adapter.py:69` | A | 固定 composite 名称。 |
| `plan_multidim_adapter.py:76` | A | 缺失 App 的结构值 `null`，没有 App 标识。 |
| `plan_multidim_adapter.py:137` | A | 产品 schema `properties` 的实际类型名。 |
| `plan_multidim_adapter.py:152` | A | 仅显示 `ok/network_called` 两个预检状态。 |
| `plan_multidim_adapter.py:157` | A | 输入 schema 版本枚举。 |
| `plan_multidim_adapter.py:167` | B | 未配置 App 的 alias/id 是调用方业务标识。 |
| `plan_multidim_adapter.py:169` | B | workspace 解析出的异常 App id 仍是业务标识。 |
| `plan_promotion_performance_adapter.py:66` | A | 多余请求键名列表。 |
| `plan_promotion_performance_adapter.py:70` | A | 固定 composite 名称。 |
| `plan_promotion_performance_adapter.py:77` | A | `(platform_count, max_items)`。 |
| `plan_promotion_performance_adapter.py:115` | B | 同一异常同时覆盖绑定后的 App 标识和日期，不能安全拆出原值。 |
| `plan_promotion_performance_adapter.py:129` | A | `(实际 item_count, max_items)`。 |
| `plan_promotion_performance_adapter.py:330` | A | 受控 platform 枚举值。 |
| `plan_promotion_performance_adapter.py:341` | A | 只显示 metric 数量与元素类型，不显示可能含业务语义的 metric 名。 |
| `plan_promotion_performance_adapter.py:369` | B | `start/end` 是调用方业务日期。 |
| `plan_pulse_adapter.py:32` | A | 多余请求键名列表。 |
| `plan_pulse_adapter.py:47` | A | `(required_source_count, max_items)`。 |
| `plan_pulse_adapter.py:103` | A | 受控 platform 枚举值。 |
| `plan_receipt_adapter.py:32` | A | `output_fields` 结构字段名列表。 |
| `plan_receipt_adapter.py:37` | A | 未支持的请求键名列表。 |
| `plan_receipt_adapter.py:44` | A | action 下多余键名列表。 |
| `plan_receipt_adapter.py:54` | A | `(实际 limit, max_items)`。 |
| `plan_receipt_adapter.py:69` | B | receipt id/storage reference 是不透明调用方标识；底层异常可能带原 reference。 |
| `plan_receipt_adapter.py:96` | A | binding target 结构路径。 |
| `plan_segment_adapter.py:55` | A | 固定 composite 名称。 |
| `plan_segment_adapter.py:114` | A | 实际结果 Python 类型名。 |
| `plan_segment_members_adapter.py:43` | A | 固定 composite 名称。 |
| `plan_segment_members_adapter.py:66` | B | 聚合校验覆盖 segment ref/version/fields；异常文本可能带业务 ref 或字段名。 |
| `plan_segment_snapshot_adapter.py:48` | A | 固定 composite 名称。 |
| `plan_segment_snapshot_adapter.py:57` | A | `(实际 max_items, 固定最小量 4)`。 |
| `plan_validation.py:84` | A | `(expanded_execution_count, 上限)`。 |
| `plan_validation.py:90` | A | `(aggregate_item_count, aggregate_limit)`。 |
| `plan_validation.py:109` | A | `(declared_node_count, 上限)`。 |
| `plan_validation.py:137` | A | 只显示禁止出现的 `workspace` 键名。 |
| `plan_validation.py:432` | A | 只显示 cycle size，不显示调用方 node id。 |
| `read_cli.py:37` | A | 只显示同时出现的 `--limit/--max-items` 选项名。 |

汇总：原 58 条中 **47 条升 A，11 条保持 B**。11 条按原因分为：业务日期 6 条、App 标识
或 App+日期混合 3 条、receipt reference 1 条、segment 请求聚合异常 1 条。

### `plan_adapters.py` 原 13 条逐点裁决

拆分前该文件实测 498 SLOC，距 500 闸门 2 SLOC。run 与 SQL-product 校验共享 selector、recipe、
binding、输入 schema 和 workspace product/App 预检 helper，因此整体下沉到窄模块
`plan_run_sql_adapter.py`；中央文件继续只做五类 adapter 装配和 composite 分发，没有新增 registry。

| 原站点 | 裁决 | 安全 actual 摘要 |
| --- | --- | --- |
| `plan_adapters.py:219` | A | operation input schema 的实际类型名。 |
| `plan_adapters.py:237` | A | 离线 validation 的 `ok` 布尔值。 |
| `plan_adapters.py:267` | A | binding target 结构路径。 |
| `plan_adapters.py:319` | A | `{kind: recipe, configured: false}`，不显示 recipe 名。 |
| `plan_adapters.py:325` | A | 解析后的 operation id。 |
| `plan_adapters.py:337` | A | 实际 parameter 键名列表。 |
| `plan_adapters.py:354` | A | 多余 parameter 键名列表。 |
| `plan_adapters.py:362` | A | 缺失 required parameter 键名列表。 |
| `plan_adapters.py:376` | A | `{configured: false}`，不显示 SQL product 名。 |
| `plan_adapters.py:379` | A | `(max_rows, node max_items)`。 |
| `plan_adapters.py:399` | A | 同时出现的 `app_id/app_ids` 字段名。 |
| `plan_adapters.py:408` | A | App 输入容器的实际类型名，不显示 App id/alias。 |
| `plan_adapters.py:443` | A | 固定 composite selector 名称。 |

拆分后 `plan_adapters.py` 为 300 SLOC，`plan_run_sql_adapter.py` 为 282 SLOC，均低于 500。
baseline 在拆分前就没有 `plan_adapters.py` 条目，因为 498 未超过全局 500；生成器禁止为阈值内文件
新增债务条目。运行 `python -m gravity_sdk.quality baseline --write` 后 baseline diff 为空，两个文件仍
都没有条目，这是该格式下最严格状态；`500/80/15/0`、所有 hard limit 与 `operation_literals=36`
均未改变。

### 测试证据

新增 5 个参数化行为测试，每个修改过的 adapter 文件至少由一个 subTest 触发；摘要模式覆盖键名、
实际名称/枚举、实际值与上限、结果类型、结构类型/shape。每个测试的独立红绿摘要如下：

| 测试 | 红态 | 绿态 |
| --- | --- | --- |
| request key lists | `Ran 1 test`; `FAILED (failures=7)` | `Ran 1 test`; `OK` |
| names and enums | `Ran 1 test`; `FAILED (failures=11)` | `Ran 1 test`; `OK` |
| counts and limits | `Ran 1 test`; `FAILED (failures=7)` | `Ran 1 test`; `OK` |
| result types | `Ran 1 test`; `FAILED (failures=2)` | `Ran 1 test`; `OK` |
| run/SQL/CLI shapes | `Ran 1 test`; `FAILED (failures=1)` | `Ran 1 test`; `OK` |

审计钉子也先以旧 `A1046/B222` 运行得到 `Ran 1 test; FAILED (failures=1)`，再只更新实测 A/B，
得到 `Ran 1 test; OK`。受影响领域现有测试为 `Ran 100 tests ... OK`。

完整 unittest 从第一趟的 1313 增为 `Ran 1318 tests ... OK`；pytest 为
`1318 passed, 3426 subtests passed`。compiler check 为 `237 operations, 11 manifests`；quality check
通过且 operation literals 为 36；development usability gate 为 selection `277/336`、terminal
`44/53`、security violations 0；`python -m gravity_sdk --help` 与 `git diff --check` 均通过。

## 推测

本轮 71 条已无“尚待逐点设计”的站点。11 条保持 B 的错误若未来要升 A，需要先把底层校验改成
结构化错误元数据，使 adapter 能读取日期/App/reference/request 的失败类别而不接触原业务值；本轮
没有证据支持扩大该契约，因此不做。saved-analysis 3 条仍待 #234 落地后的新代码形状再裁决。
