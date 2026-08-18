# 相对日期解析

- 日期：2026-08-18
- 任务：#200
- 结论：封闭中英相对短语确定性地解析成显式时区日历窗并回显；模糊短语 fail-closed。

## 确凿事实

- CLI `--start/--end/--date` 在 argparse 之后、下游 ISO 校验之前解析封闭相对短语。
- 成功结果带 `resolved_date_window`（`gravity.relative-date-window.v1`），含 expression、start、end、timezone、timezone_source、display。
- 时区顺序：`GRAVITY_TIMEZONE` → 已配置 workspace `defaults.timezone` → `Asia/Shanghai`。未配置 workspace 的占位 `UTC` 不参与。
- 默认 `Asia/Shanghai` 的依据：SQL products / Evidence / credentials / 生产对账窗口，不是本机时区。
- 周一起始：`week_first_day=1`（`analysis.retention.query` 合同默认）。
- 「本周 / this week」**截到今天**，与「本月 / this month」同口径。交回时它原本返回整周
  周一..周日，2026-08-18（周二）会给出 `08-17..08-23`，尾部五天尚未发生；
  「本月」却已经截到今天。两者口径不一致，且半截是未来的窗会给出看起来正常的数。
  维护者改成 `start..today` 并同步收紧了该用例断言。「上周 / 上月」仍是完整的过去周期。
- 「最近一段时间 / recently / last few days」等无唯一答案的短语返回 `INPUT_INVALID`，`field=start/end` 或 `date`，带 `next_action`。
- ISO `YYYY-MM-DD` 行为不变；非法 ISO 仍交给原产品校验。
- 生产对账（2026-08-18，App `29034827`，只读）：`yesterday` 解析为 `2026-08-17..2026-08-17 (Asia/Shanghai)`。同一窗再手填 ISO 发第二次。两次 `attribution_performance` 均为 `success`，四个画像数字相等：`AppRealRegisterCnt=2755`，`AppActivateStandard=2728`，`AppRegisterStandard=16`，`AdClick=6548`，`AdShow=268591`。写 0 次。

## 推测

- Agent 问句里点名「甜甜旅行」仍不足以填 `app`：账号下同名产品有五个平台分身，默认 workspace App 与「问句点名」都不是无歧义选择。本单元不填 app。
