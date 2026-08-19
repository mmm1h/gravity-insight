> 归档材料：保留历史决策与取证，不代表当前接口或状态；当前入口见 docs/index.md。

# 任务指南补漏斗 / 留存 / 导出

- 日期：2026-08-19
- 任务：#224
- 结论：走已提交生成器补了漏斗、留存、用户明细导出三条短指南；任务表从 8 行加到 11 行。问法以 #217 实测为准，本趟未重打生产。

工作树 `grok/skill-guides`，基线 `dev@ad9497c`。只改生成器、`docs/agent-skills/`、本文件和 README 归档一行。不改 `src/`、不上手包、不 push。

## 生成器怎么工作

新增一条目标要同时改两处：`render_documents()` 的输出表，以及 `_index()` 的目标行。页面正文由 `_guide()` 套合同/产品卡字段，不是手写 markdown。

`--check` 把 `render_documents()` 的全文与磁盘逐字节比较；缺文件或手改生成物都会红。`tests.test_agent_catalog.AgentGuideGenerationTests` 做同一件事。

## 确凿事实（离线）

本机 `PYTHONPATH=src`，`GravityInsightClient.from_env()`，`discover_capabilities`，**零次生产 HTTP**：

| 问法 | 首候选 | executable |
| --- | --- | --- |
| 「转化漏斗」 | `analysis.query.spec:funnel` | true |
| 「看多步行为的转化漏斗」 | `analysis.query.spec:funnel` | true |
| `funnel conversion steps` | `analysis.query.spec:funnel` | true |
| 「注册到后续行为的漏斗，近 7 天每步人数」 | `analysis.task.handoff` | false |
| 「某起始事件后的次日和 7 日留存」 | `analysis.query.spec:retention`（次位 raw `analysis.retention.query`） | true |
| 「把某一天的用户明细导出成文件并下载」 | `export.analysis.user_detail.start` | true |
| 「用户明细导出」 | `export.analysis.user_detail.start` | true |
| 「导出」 | 先素材报表，不是用户明细卡 | — |

产品卡合同（同一离线 client）：

- 漏斗 / 留存：`required_inputs=['app','spec']`；`schema_argv` = `analysis query --kind <kind> --spec-schema`；`next.argv` 仍是 `plan run`。
- 漏斗 compact 必填含 `window`；`unit` 枚举 `today|minute|hour|day`。合同 `notes.returns_conversion_rate=false`；两种分母 `previous_step` / `first_step`。
- 留存 compact 必填：`start/end/steps/offset/period_calc_method/custom_before_method/total_calc_type/week_first_day`。省略 `time_grain` 时编译写入 `create_time/day`。
- 用户明细导出：`schema_argv` = `export describe export.analysis.user_detail.start`；`allowed_codes=ClientID,CreateTime`；文件表头 `客户ID,注册时间`。

生产人数、空信封、跨 route 对账**不重打**，引用 [第二轮冷启动](coldstart-2.md)。

## 推测

无。本趟没有新的生产响应，不把 #217 的租户数字写成新观测。

## 与上手包对照

`docs/team-onboarding.md` 仍写「任务指南表目前只有事件趋势短页，没有漏斗 / 留存 / 导出短页」。这句现在过时。本趟按边界不改上手包。问法、必填、可信度以上手包 §「漏斗 / 留存 / 用户明细」为准；短指南是任务级速查，不复制上手包表格和租户数字。

两边没有口径冲突：漏斗无率、两种分母、留存空信封先换回访、`--columns` 用请求代码、单日用户明细 = 当天漏斗第一步，说法一致。

## 动线台账

漏斗 / 留存仍是已闭环，导出仍是部分闭环。本趟**不改** `docs/analysis-journeys.md` 任何一行，不改表头 `56 = x / y / z`。评测冻结 case 未改。合并对账时表头应保持 **51 / 3 / 2**。
