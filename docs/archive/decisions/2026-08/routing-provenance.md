> 归档材料：保留历史决策与取证，不代表当前接口或状态；当前入口见 docs/index.md。

# 应答声明路由臂

- 日期：2026-08-18
- 任务：#204
- 结论：`gravity agent` 两条臂都声明 `routing_mode`；识别器另给常设升级路径；默认值本趟不切。

## 发了什么请求、拿到什么响应

离线、无生产 HTTP。`PYTHONPATH=src`。

| 请求 | 响应要点 |
| --- | --- |
| `discover_capabilities("看一下事件趋势")` | `status=success`，`count=3`，`mode=discover_and_describe`，`routing_mode=recognizer`，`routing.floor=true`，顶层 `next_action` 仍是「怎么执行这个候选」 |
| `resolve_host_product_selection(..., analysis.query.spec)` | `status=success`，`count=1`，`mode=host_catalog_select_and_describe`，`routing_mode=host_catalog`，`routing.floor=false`，无 `routing.upgrade` |
| `validate_questions({"query":"..."})` | `InputValidationError`，`field=input`，消息含 `questions` 合法形状 |
| `validate_questions({"questions":[{"id":"q1","text":"..."}]})` | `InputValidationError`，`field=input.questions[0]`，消息列出合法键 `id/query/domain/platform/limit` |

识别器升级路径不写进顶层 `next_action`，写在 `routing.upgrade.next_action` + `routing.upgrade.next.argv` / `then_argv`。候选卡自己的 `next.argv` 和无候选时的顶层 `next` 都不被覆盖。

## 确凿事实

- 改前识别器信封顶层没有 `routing_mode`；宿主臂 `_selection_envelope` 已经写了 `routing_mode=host_catalog`。
- `DEFAULT_ROUTING_MODE` 仍是 `"recognizer"`；`--host-selection` 在 `host_catalog` 上 `required=True`。本趟未改默认。
- `--input` 合法形状是 `{"questions":[{"id":"...","query":"..."}]}` 或问题数组（字符串或带 `id/query/domain/platform/limit` 的对象）。单对象 `{"query":"..."}` 从来不是合法形状。
- 技能文档由已提交的 `scripts/generate_agent_skills.py` 重生成：`index.md` 任务表新增「调用方自己选产品时走宿主臂」一行；`ten-minute-path.md` 正文点出宿主臂 argv。
- 可执行错误库存由 `1254 / A879 / B375 / C0` 变为 `1265 / A890 / B375 / C0`。新增 11 个 A 级 raise，全部在 `agent_batch_questions.py`。C 仍为 0。
- 本趟不新增产品动线、不改评测装置/题集/层定义。

## 推测

- 调用方看到 `routing.floor=true` 后，会按这次答案的重要性自己决定是否升级到宿主臂。SDK 不替它决定。
- 把默认切成 `host_catalog` 会立刻打断所有未传 `--host-selection` 的现存 CLI / 脚本 / Plan / SDK 调用；见本文件「默认值判断」。

## 默认值判断（只出判断，未改）

**建议：不要切。** 消费方是 agent 并不自动让 `host_catalog` 成为安全默认。

会打断的现存调用方：

1. 位置参数 `gravity agent "<query>"` 以及 SDK `discover_capabilities(query)`：今天默认走识别器并返回候选。切成 `host_catalog` 后，没给 selection 会在 `_validate_routing_inputs` 处 fail-closed（`host-selection` 对宿主臂是 required）。
2. 所有未写 `--routing` 的 CLI 脚本、workspace recipe、Plan 发现节点、评测 development 路径：同样当场变 caller error。
3. `gravity agent --input questions.json` 批量发现：内部仍调 `discover_capabilities`，默认臂跟着变。
4. 协议面 `gravity agent`（无 query）：今天返回 `mode=protocol` 的机器协议。若默认变成宿主臂，无 selection 也会断。

「默认 host_catalog，没给 selection 时返回目录投影 + next.argv」不是零成本切换：

- 今天 `status=success` + 候选卡的调用方会变成「先拿目录、自己选、再二次进入」。未知问题从 1 次发现变成至少 2 次。
- `--host-selection required=True` 必须先改成可选，这是公开 CLI 合同变化。
- 评测 development 选择层数字会从识别器地板切到「未给 selection 的目录投影」，现有冻结 case 的首次选择预期对不上。本趟明确不改评测装置，所以不能在本趟切。

安全切默认的前置：单独一趟改 CLI 合同、迁移 work-dashboard 与文档、给无 selection 的宿主臂定义新信封（目录投影，不是静默识别器）、再跑 development 确认选择层预期。在那之前，识别器地板 + 机读声明是正确组合。
