# Plan 适配器安全实际值

- 日期：2026-08-19
- 任务：#232
- 结论：Plan 范围的 B 级调用点由 102 降为 74；全仓库存为 `1268 = A1046 / B222 / C0`，未降低质量阈值。

## 确凿事实

离线运行 `PYTHONPATH=src python scripts/audit_actionable_errors.py --json` 的基线为
`1268 = A1018 / B250 / C0`。按 Plan 范围（`plan_adapters.py`、`plan_*_adapter.py`、
`plan_validation.py`、`read_cli.py`）过滤后为 102 条 B。

本轮在 28 个调用点增加了 `actual_value(...)`：未知字段只显示字段名列表，名称错误显示
实际名称，预算错误显示 `(实际数, 上限)`，运行期结果错误只显示类型。没有回显 request 的值、
结果载荷、账号或凭据。复跑审计得到 `1268 = A1046 / B222 / C0`，Plan 范围余 74 条 B。

分类如下：

| 类别 | 条数 | 典型例子 | 本轮处理 |
| --- | ---: | --- | --- |
| 值在作用域且可安全摘要 | 28 | `order_directory` 多余键、Plan item budget | 已升 A |
| 值在作用域但尚待逐点设计摘要 | 58 | 适配器的日期/平台/绑定校验 | 保持 B，不能把原始请求或上游异常写入日志 |
| 质量硬边界 | 13 | `plan_adapters.py` 的 selector/recipe/binding | 保持 B；文件受 500 SLOC 闸，未放宽或绕过 |
| 并发边界让出 | 3 | `plan_saved_analysis_adapter.py` | 未触碰，归 #234 |
| `plan_kanban_mutation_adapter.py` 让出 | 0 | 无 | 审计确认该文件当前没有 B，未触碰 |
| 审计判据误伤 | 0 | 无 | 未修改审计器 |

行为验证：新增测试传入一个含业务值的未知字段；错误消息显示
`["name","unexpected"]`，不包含该业务值。红态为审计钉子仍为旧的
`A1018/B250`，绿态为 `6 passed`；相关既有 Plan 测试为 `9 passed, 18 subtests passed`。

完整离线验证：`unittest` 为 `Ran 1313 tests ... OK`，`pytest` 为
`1313 passed, 3390 subtests passed`，compiler check 为 `237 operations, 11 manifests`，
quality check 为 `operation_literals=36 (ratcheted)`。

## 推测

其余 58 条可通过同一受控摘要模式继续提升；在逐个确认其输入不会是原始业务数据前，不应批量
拼接 `actual_value(request)` 或转发上游异常文本。
