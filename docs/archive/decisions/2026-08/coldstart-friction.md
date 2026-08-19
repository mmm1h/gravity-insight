> 归档材料：保留历史决策与取证，不代表当前接口或状态；当前入口见 docs/index.md。

# 首次使用摩擦：错误入口与 --help

- 日期：2026-08-19
- 任务：#212
- 结论：三个真实分析任务只用 `--help` / `agent-catalog` / `docs/` 就能完成；卡住后读源码的点，多数已在代码侧补成带 `field=` / `next_action` 的错误或 `--help` 文案。分维组标签被投影省略，本趟不改合同。

## 三个真实任务

生产读均只打投放中抖音 App `29034827`。相对短语 `last 7 days` 解析为 `2026-08-13..2026-08-19`（Asia/Shanghai）。导出 create 0 次，写 0 次。

| 任务 | 命令 | 生产结果 |
| --- | --- | --- |
| 目录发现 | `gravity run app.list --max-items 20` | HTTP 200，7 个 App；`id=29034827` 在列 |
| 事件近 7 天趋势 | `analysis query --kind event --app 29034827 --start last 7 days --end last 7 days --spec event-trend.spec.json` | `$AppRegister` 按日：600/559/511/506/534/558/53，阶段总和 3321 |
| 同一事件按 `$os` 分维 | 同上，spec 加 `group_by=[{"field":"$os","source":"user"}]` | 三行阶段总和 16 / 2489 / 816；行上没有 OS 标签 |

分维请求已编成 `group_by_list` 含 `{field:$os, type:user}`。响应 `warnings` 为 `unregistered analysis response data keys were omitted (count=2)`。`result_audit.response_drift.fields` 观察到：

- `/data/list/*/*/list/*/用户.设备类型`（string）
- `/data/union_groups`（array）
- `/data/y`（object）

所以 16+2489+816=3321 对得上总分，但调用方看不到哪一行是哪个 OS。

离线事件发现：`metadata search --app-id 29034827 register` 命中 `$AppRegister`；`yesterday_count` 仍为 0，未当有无数据的门。`metadata properties --app-id 29034827 $os` 同时给出 event_property `$os` 与 user_property `$os`。

## 摩擦表

| 我想干什么 | 先试了什么 | 为什么没成 | 最后读了哪个文件才搞定 | 本该在哪儿写着 |
| --- | --- | --- | --- | --- |
| 看 Analysis Spec 合同 | `analysis query --spec-schema` | 报 `field=kind`，必须先给 `--kind` | 未读源码；文档 `event-trend.md` 已写 `--kind event` | `--help` 应写 `--spec-schema` 需要 `--kind`；顶层 help 应列出 `analysis query --kind --spec --app` |
| 构造事件查询 | `analysis query --kind event` | 落到 raw operation，报缺 `app_id`，下一步是 `operations describe <operation-id>` | `analysis_spec_cli.py` | 缺 `--spec` 应指向 `--spec-schema`，不要假装这是 raw `app_id` |
| 按 OS 分维 | `--dimensions $os` 加 `--spec` | 报 `--spec does not accept unrelated raw-query shortcuts: dimensions`，下一步却说省略 `--spec` 或 `--input` | `analysis_spec_cli.py` | 应说把分组放进 `spec.group_by`，并指向 `--spec-schema` |
| 看分维结果是哪个 OS | 读 `data.list[].list[]` | 只有日期数字，没有组标签；warning 只说 omitted count=2 | `executor.py` + `result_audit` | 合同/`describe` 应声明组标签键；或投影放行已请求的 `group_by.field` 对应标签 |
| 列 App | `run app.list`（子进程无 TTY，且当时只有过期环境 token） | 打印「Gravity 首次使用设置 / 请输入用户名」后失败，不是 JSON | `onboarding.py` | 非交互缺凭据应结构化报 `field=auth`，下一步是交互 `gravity` 或 `auth refresh` |
| 刷新会话 | `insight auth refresh`（无本地 `.env.gravity.local`） | 同样掉进交互向导 | `onboarding.py` / `runtime.py` | `auth status` 的 `next_action` 应同时写交互登录和本地 env + `auth refresh` |
| 看未知 catalog selector | `agent-catalog describe not.a.selector` | 下一步是 `operations search` | `agent_catalog.py` | 下一步应是 `agent-catalog categories` → `category` |
| 看未知 category | `agent-catalog category nope` | 「Use the documented composite or catalog name」 | `agent_catalog.py` | 下一步应是 `agent-catalog categories` |
| 找 App 解析失败时的入口 | 读 `_resolve_app` 错误 | 文案写 `gravity apps list`，该命令不存在 | `analysis_spec.py` | 应写 `gravity run app.list` |
| 在 Windows 重定向 JSON | PowerShell `>` 捕获 `agent-catalog` | JSON 里的中文被弄成非法控制字符 | 未读源码 | `#docs-entry`：Windows 下用 `--output` 或 UTF-8 管道；本趟未给 catalog 加 `--output` |

## 本趟代码改动

只改 `src/` 错误文案 / `--help` / 入口分流，以及对应测试。不改文档导航，不改评测，不改质量阈值。

确凿已修：

- 缺 `--spec` 且无 raw `--input`：`field=spec`，下一步 `--spec-schema`。
- `--spec` 遇上 `--dimensions` 等 raw 快捷参数：说明应写入 `spec.group_by` / `spec.steps[].metric`。
- 缺日期：下一步写 ISO 或封闭相对短语。
- 缺 `steps[].metric`：下一步写 `field` + `aggregation` 并指向 `--spec-schema`。
- 未知 catalog category / selector：下一步指向 `agent-catalog` 浏览，不再指向 `operations search`。
- 幽灵命令 `gravity apps list` 改为 `gravity run app.list`。
- 非交互且本地无账号也无 token：结构化 `field=auth`，不再打印向导半截。
- `AUTH_MISSING` / `auth status` 的下一步补上 `.env.gravity.local` + `insight auth refresh`。
- 顶层 `--help` 补上 `analysis query --kind --spec --app` 和完整 `export run` 必填项。
- `analysis query` / `agent-catalog` / `metadata search|events|properties` 的 `--help` 补了 kind、selector、分页说明。

错误审计：`1266 / A891 / B375 / C0` → `1268 / A896 / B372 / C0`。C 仍为 0。新增 raise 都带 path 和 remedy。

## 未修清单

| 项 | 证据 | 不修理由 |
| --- | --- | --- |
| 事件分维结果丢掉组标签 | 生产 `result_audit` 省略 `用户.设备类型`、`union_groups`、`y` | 要改 `analysis.event.query` 投影合同或 `_ANALYSIS_NESTED_RESPONSE_KEYS`；属于合同/隐私裁决，不是 `--help`。交给后续合同趟 |
| `agent-catalog describe` 的 `next.argv` 是 `plan run` 而不是 `analysis query --spec` | `analysis.query.spec:event` 卡 | 改卡面会影响 Agent 交接合同，超出本趟错误消息范围 |
| `export run --help` 的 `--columns` / `--idempotency-key` 仍无说明 | `export_cli.py` 加 help 会顶破 `add_export_commands` 函数 SLOC 80 | 合法形状已在 `export describe`；`--help` 补文案会撞质量棘轮 |
| `analysis --help` 仍不列出 `query` 子命令说明之外的必填项 | `analysis query --help` 已补 | 父解析器是共享 shortcuts，继续堆 help 会顶 `build_parser` |
| Windows PowerShell 重定向破坏中文 JSON | `agent-catalog category app` 经 `>` 后 `json.loads` 失败 | 文档/调用方环境问题，交给 `#docs-entry` |
| 顶层无 `--output` 的 catalog / metadata status | `unrecognized arguments: --output` | 加全局 `--output` 是表面扩容，本趟只修错误消息 |
| 空 `metadata search` 成功返回第一页而不是要求 query | 离线 catalog 合法空查询 | 行为正确；`--help` 已写「省略则列第一页」 |

交给 `#docs-entry`：

- 十分钟路径应写清：本工作树若没有 `.env.gravity.local`，`auth status` 会看到过期/缺失 token；非交互不要跑无 TTY 的 `gravity`。
- Windows 捕获 JSON 用 Python/`--output`，不要用 PowerShell `>`。
- `analysis query` 主路径是 `--kind` + `--spec` + `--app`；`--dimensions/--metrics` 是 raw 专家面。
- 事件分维结果的组标签今天可能被省略，读 `result_audit.response_drift`，不要把三行无标签数字当成可解释分维。

## 验证

- `python -m unittest discover -s tests`：`Ran 1231 tests`。3 个失败（`--help` ANSI 颜色）在未改工作区的 `0ea78b7` 上同样失败，不是本趟引入。
- `python -m pytest -q`：`1228 passed`，同样 3 个基线 `--help` 颜色失败。
- `python -m gravity_sdk.compiler check`：237 operations / 11 manifests。
- `python -m gravity_sdk.quality check`：PASS；`quality-baseline.json` 无 diff，未改 `hard_limit` / `threshold` / `max_`。
- 测试数：基线任务书写 unittest 1220；本工作树现为 1231（含本趟新增 2 个用例）。未减少。

## 推测 / 确凿

确凿：三个任务在 `29034827` 上拿到非空事件趋势；分维行数可加回总分；组标签被投影省略。

推测：被省略的 string 键 `用户.设备类型` 就是 `$os` 的展示名；`union_groups` / `y` 可能是前端分层图辅助结构。未拆响应原文确认，故不登记进合同。
