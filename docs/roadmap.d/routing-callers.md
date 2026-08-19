# 默认路由调用方全量审计

- 日期：2026-08-19
- 任务：#233
- 结论：现在不该切默认，也不该花下一次 holdout；切法甲会同时破坏 CLI、SDK、批量和评测，切法乙是唯一不减能力的语义，但当前评测不会经过它，必须先把真实运行时路径接进 development 装置。

本轮生产 HTTP **0 次**。未运行 holdout / final / all，未读 `.local/agent-usability/*.key`，未读或改任何 `*.sealed.json`，未改题集、评分、层定义或阈值。`D:/git-pjt/work-dashboard` 只读扫描，未改任何文件。

## 审计范围与复算方法

工作树是 `D:/git-pjt/wt-routing-callers`，分支 `codex/routing-callers`，基线与 `HEAD` 均为 `b7105f62aa26c6bb8ce674d18cde9dc40b3455b8`。仓库没有 `.codegraph/`，所以使用 `rg` 和 Python AST 离线扫描。

确凿扫描结果：

- AST 扫描 `src/`、`scripts/`、`tests/`、`evals/` 中名为 `discover_capabilities`、`capabilities_many`、`capabilities_many_for_sdk`、`resolve_capabilities`、`*.capabilities` 的调用，共得 171 个语法命中。人工排除 `agent_export.py:159` 的 `client.export_capabilities()` 这一处同名假阳性后，剩 **170 个路由相关调用点**：运行时/脚本 13 个，测试 157 个。
- 170 个调用点中显式传 `routing=` 的数量是 **0**；宿主臂测试和工具直接调用 `resolve_host_product_selection()`，不通过这些默认参数入口。
- `docs/` 与根 `README.md` 的扩展命令扫描命中 18 个文件；`docs/agent-skills/` 11 个文件全部扫描，其中只有 `capability-gap.md`、`catalog-discovery.md`、`ten-minute-path.md` 教默认/宿主发现命令，其余 8 个没有省略 `--routing` 的能力发现命令。
- `work-dashboard@172af5667cfc410b561dd898eaf03aea6c6b9152` 扫到 6 个现行说明文件和 1 个字符串测试；没有 Python/SDK 调用点。
- 对 `src/gravity_sdk/*plan*.py` 和 `scripts/*plan*.py` 搜索四个发现入口，命中 **0**。Plan 执行不经过 Agent 路由；文档里的“未知能力 -> Agent -> Plan”第一跳才受影响。

离线反事实用 `unittest.mock.patch` 同时把 `agent_host_selection.DEFAULT_ROUTING_MODE` 改为 `host_catalog`，并按源码重载后的形状把 `ROUTING_MODES` 设为 `("host_catalog", "host_catalog")`。socket connect 被 guard；使用只返回本地产品卡的 fake client。结果写到忽略目录 `tmp/codex/routing-callers/routing-counterfactual.json`，未作为长期事实源提交。

## 先定义两种切法

### 切法甲：精确地只翻当前常量

只把 `agent_host_selection.py:26` 从：

```python
DEFAULT_ROUTING_MODE = "recognizer"
```

改为：

```python
DEFAULT_ROUTING_MODE = "host_catalog"
```

不改其他代码。这是本报告中“切法甲”的唯一含义。

这里有一项 `#218` 未发现的确凿事实：这个常量同时承担了三个职责，而不只是 CLI 默认值：

1. `add_host_routing_arguments()` 的 argparse 默认值（`agent_host_selection.py:39-56`）；
2. `ROUTING_MODES=(DEFAULT_ROUTING_MODE, HOST_ROUTING_MODE)` 的识别器 choice 身份（`:26-28`）；
3. `_validate_routing_inputs()` 判断“recognizer 且无 selection 才合法”的比较值（`:96-107`）。

因此只翻它会让 choices 变成 `("host_catalog", "host_catalog")`，并让 SDK 仍传入的字面量 `"recognizer"` 变成非法值。反事实实测中显式 `--routing recognizer` 报：

```text
field=argv; invalid choice: 'recognizer' (choose from 'host_catalog', 'host_catalog')
```

### 切法乙：省略 routing 时由 selection 是否存在分派

本报告把切法乙定义为下面这个闭合合同：

| 输入 | 有效臂 |
| --- | --- |
| 省略 `routing`，无 selection | `recognizer` |
| 省略 `routing`，有完整 selection | `host_catalog` |
| 显式 `recognizer`，无 selection | `recognizer` |
| 显式 `recognizer`，有 selection | caller error |
| 显式 `host_catalog`，无 selection | caller error，继续 fail closed |
| 显式 `host_catalog`，有完整 selection | `host_catalog` |

这尚未实现。为核验它的端点语义，本轮只用现有 `discover_capabilities(..., routing=<有效臂>, host_selection=<值>)` 回放：无 selection 返回 `routing_mode=recognizer`，有 selection 返回 `routing_mode=host_catalog`，显式 host 无 selection 返回 `HOST_SELECTION_REJECTED`。这证明两条已有执行臂能承载该合同，不证明 CLI/SDK/batch 的新分派接线已经存在。

## 运行时调用点全量清单

下表中的“甲”是上述精确反事实实测，不是推测。“乙”对无 selection 的现有面是端点回放；需要新增参数/批量 schema 的部分明确标为未实现。

| 调用面与位置 | 今天走哪条臂 | 切法甲会不会坏 / 怎么坏 | 切法乙 |
| --- | --- | --- | --- |
| CLI parser 与 `run_agent_command`：`agent.py:75-138`、`cli.py:503-531` | 省略 routing 时 parser 给 `recognizer`；host router 返回 `None` 后才进协议/识别器 | **坏**。parser 默认变 host，`host_routing_command()` 先于协议和普通发现读取 required selection；单问和无 query 协议都报 `field=input` / `--input is required` | 无 selection 继续 recognizer；有 selection 才 host。需要 parser 用“是否显式传 routing”的 sentinel，尚未实现 |
| `gravity agent --input`：`agent_input_resolution.py:39-50,169-183` | host router 先放行 recognizer，然后 `capabilities_many`；实测 batch item `routing_mode=recognizer` | **坏**。在到达 `_batch_command()` 前就因缺 selection 失败 | 当前 batch schema 没有 selection，故保持 recognizer；若要宿主批量需另行定义每题 selection 合同 |
| `gravity agent --resolve-inputs`：`agent_input_resolution.py:51-81,112-134,186-189` | `_discover()` 省略 routing，走 recognizer，再在线补目录 | **坏**。CLI 先在 host router 缺 selection；SDK 直调则在 `field=routing` 失败 | 无 selection 继续 recognizer；是否允许“host 选卡 + 在线补目录”尚未设计 |
| 公共 `discover_capabilities()`：`agent.py:141-180` | 参数默认字面量 `routing="recognizer"`，实测 recognizer | **坏**。字面量不变，但 validator 的合法值已变 host，实测 `InputValidationError(field="routing")` | 可在 `host_selection` 非空且 routing 未显式给出时选 host；需要 `None` sentinel 或等价机制，尚未实现 |
| `GravitySDK.capabilities()`：`sdk.py:232-256` | facade 不暴露 routing/selection，委托 `discover_capabilities()`，实测 recognizer | **坏**。同上，直接抛 `field=routing` | 现签名无法交 selection，所以只能继续 recognizer；要走 host 必须加法扩展 SDK 参数 |
| core `capabilities_many()` / `discover_one()`：`agent_batch.py:67-106,190-225` | 每题调用 `discover_capabilities()` 且不传 routing，实测 recognizer | **坏但被隔离**。每题异常被包装成 `AGENT_DISCOVERY_FAILED`，batch `status=error/failure_count=N` | schema 无 selection，继续 recognizer；不能把一次全局 selection 猜给 N 个问题 |
| `capabilities_many_for_sdk()`：`agent_batch.py:109-122` | 委托 core batch，recognizer | **坏**，同 core batch | 无 selection，recognizer |
| `GravitySDK.capabilities_many()`：`sdk.py:258-273` | facade 不暴露 routing/selection，recognizer | **坏**，实测 `status=error/failure_count=N` | 无 selection，recognizer；宿主批量仍缺合同 |
| SDK `resolve_capabilities()`：`sdk_metadata.py:88-111` -> `agent_input_resolution.py:84-166` | 内部 `_discover()` 省略 routing，recognizer | **坏**，`field=routing` | 无 selection 继续 recognizer；host + live catalog 未定义 |
| Plan validate/execute/host plan | **不经 Agent 路由**；Plan 源码扫描 0 命中 | 不坏 Plan 本身；但文档中先跑默认 Agent 的第一跳会坏 | Plan 本身不变；未知能力的无 selection 第一跳仍 recognizer |
| 默认评测：`agent_usability_eval.py:436-470,694-739` | `_discover_trials()` -> `capabilities_many()` -> recognizer；`recovery_score()` 另直接调用一次默认 `discover_capabilities()` | **整次评测中止**。batch 先产 N 个 discovery error，随后 recovery 的直接调用抛 `field=routing`，不会生成可用结果 | 不提供 selection，所以仍测 recognizer，不会自动测到宿主臂 |
| 外部 selector 评测：`agent_usability_eval.py:721-733`、`agent_usability_external_selector.py:33-106,323-388` | 独立 plugin -> `_selection_result()`；既不走 CLI 默认，也不调用运行时 `resolve_host_product_selection()` | 不依赖常量；仍是独立 selector harness | 也不依赖乙的运行时分派；不能证明乙已工作 |
| development 差距脚本：`agent_usability_host_arm_gap.py:99-167` | recognizer 半边用 batch；宿主半边直接 `resolve_host_product_selection()` | recognizer 半边全错，比较失真；宿主半边仍可跑 | recognizer 半边不带 selection，保持 recognizer；宿主 oracle 仍显式 resolver |
| 指南生成器：`generate_agent_skills.py:65-97` | 直接默认 `discover_capabilities()` 生成 gap 样本，recognizer | **坏**，`field=routing`；生成器无法重生成指南 | 无 selection，recognizer |

### 测试调用点

AST 扫到 **157 个**测试调用，分布在 **27 个**文件；全部省略 `routing=`。下面逐文件列出调用行，便于复算 blast radius：

```text
tests/test_agent_catalog.py:67,315,353,356,371,392
tests/test_agent_lexical_retrieval.py:32,56,76,119,130
tests/test_derived_metrics.py:186,207
tests/test_discovery_next_fields.py:104,116,127,180,191,203
tests/test_gravity_advertiser_profile.py:183,195,200
tests/test_gravity_agent_call_bound.py:108
tests/test_gravity_agent_input_resolution.py:100,115,171,178,184,197,206,220
tests/test_gravity_agent_saved_analysis.py:39
tests/test_gravity_analysis_default_dictionary.py:99
tests/test_gravity_attribution_snapshot.py:264,369
tests/test_gravity_bilibili_account_performance.py:229,254,258
tests/test_gravity_company_usage.py:124
tests/test_gravity_custom_audience.py:140,156
tests/test_gravity_insight_agent_ux.py:311,330,335,342,356,395,428,448,456,465,477,490,518,535,545,572,575,580,613,641,649,657,663,666,677,697,716,760,797,810,811,843,845,897,912,948,977,1002,1022,1037,1062,1070,1082,1147,1235,1244,1251,1639,1642,1653,1690,1692,1716,1722,1757,1760,1791,1795
tests/test_gravity_material_asset.py:115
tests/test_gravity_material_performance_surface.py:274
tests/test_gravity_monetization_guard_agent.py:24,46,53,75,87,91
tests/test_gravity_order_directory_agent.py:51,54,65,86,90,93,100,103,113,117,124,128,165,175
tests/test_gravity_order_trace_agent.py:23,28,45,70,86,103,118
tests/test_gravity_plan.py:568
tests/test_gravity_promotion_performance_agent.py:27,30,74,100,110
tests/test_gravity_realtime_event_catalog.py:153
tests/test_gravity_report_directory.py:185,186,187,200
tests/test_gravity_sdk.py:278,289,300,304
tests/test_gravity_title_package.py:179
tests/test_semantic_compose.py:274
tests/test_semantic_context.py:80,93,109,141,150,167,181,199,202,205,237,291
```

切法甲会让直接发现测试抛错、batch 测试收到 error envelope；现有 `test_agent_host_selection.py:151-166` 还明确锁住 CLI 省略行为为 recognizer。切法乙的无 selection 行为保持这些调用原样。

## 文档与调用项目清单

### 本仓现行调用说明

| 教给调用方的路径 | 位置（全量） | 今天 | 切法甲 | 切法乙 |
| --- | --- | --- | --- | --- |
| 无 query 协议 | `docs/team-onboarding.md:96`；`docs/reference/cli.md:59`；`docs/agent-workflow.md:82` | recognizer protocol | 缺 selection，协议拿不到 | recognizer protocol 不变 |
| 单问省略 routing | `README.md:51`；`docs/team-onboarding.md:139-164,338,393`；`docs/getting-started.md:89-94`；`docs/guides/export.md:61`；`docs/agent-workflow.md:30,77-82`；`docs/reference/cli.md:60,414,608,827,921,935,1001,1134`；`docs/reference/plan.md:334,382,446,483,618`；`docs/capability-coverage.md:4` | recognizer | 缺 selection，所有示例成为死命令 | 无 selection 仍 recognizer |
| batch 省略 routing | `README.md:27,52`；`docs/team-onboarding.md:154-164,334-342`；`docs/index.md:59`；`docs/architecture.md:104,129`；`docs/agent-workflow.md:31,94-104`；`docs/reference/cli.md:10,61` | 每题 recognizer | CLI 在 batch 前失败 | 无 selection 仍 recognizer |
| 在线输入解析省略 routing | `docs/analysis-journeys.md:7-10`；`docs/architecture.md:132-136`；`docs/agent-workflow.md:84-92,201`；`docs/reference/cli.md:62,353,1129` | recognizer 发现后补目录 | CLI 缺 selection；SDK `field=routing` | 无 selection 仍 recognizer；host 组合未定义 |
| SDK facade | `docs/reference/sdk.md:8-22,160-164,223-229`；`docs/agent-workflow.md:92` | `capabilities` / `capabilities_many` / `resolve_capabilities` 均 recognizer | direct 抛错或 batch error | 现有签名无 selection，仍 recognizer |
| 显式宿主臂且有 selection | `docs/team-onboarding.md:106-108,147-150,388-393`；`docs/reference/cli.md:63-81`；`docs/agent-workflow.md:82` | host | 仍可用 | 仍可用 |
| Agent skill 默认单问 | `docs/agent-skills/capability-gap.md:5-7`；`docs/agent-skills/ten-minute-path.md:4` | recognizer | 缺 selection | recognizer |
| Agent skill 显式宿主臂 | `docs/agent-skills/catalog-discovery.md:6-11`；上两份 skill 的同段 | host（有 selection） | 不坏 | 不坏 |

`docs/agent-skills/` 其余 `index.md`、`caller-semantics.md`、`event-trend.md`、`funnel.md`、`governed-writes.md`、`period-comparison.md`、`retention.md`、`user-detail-export.md` 没有省略 routing 的能力发现命令；其中 `governed-writes.md` 只有 `agent-catalog`，不进入 Agent router。

`docs/mcp-feasibility.md` 是可行性/迁移讨论，`docs/maintainers/extending.md`、`technical-debt.md` 是维护者说明；扫描有 `gravity agent` 字样，但没有新增运行时调用形状。它们不计作独立调用方，仍已纳入全文扫描。

### `work-dashboard`（只读）

| 位置 | 教的路径 | 今天 | 切法甲 | 切法乙 |
| --- | --- | --- | --- | --- |
| `AGENTS.md:39` | 显式 host 主路径；默认单问地板；batch | host / recognizer / recognizer | 显式 host 可用；默认单问与 batch 坏 | 全部保持，且未来可省略 host 的 routing 标志 |
| `10_数据底座/Gravity数据访问与业务口径.md:45,54,70-120,143-146,242` | 无 query 协议、显式 host、默认单问、batch -> Plan | 分别为 protocol/host/recognizer/recognizer | 协议、默认单问、batch 坏；host 可用 | 不带 selection 的三条 recognizer 不变 |
| `10_数据底座/抖小买量口径.md:73` | 显式 host；默认单问；batch -> Plan | 同上 | 后两条坏 | 不变 |
| `00_操作台协议/外部数据工具迁移.md:17` | 同一四路分流 | 同上 | 默认与 batch 的现行说明失真 | 不变 |
| `30_专题工作区/数据消费入口.md:21-24,41-43` | 显式 host；默认单问；batch -> Plan | 同上 | 默认与 batch 坏 | 不变 |
| `30_专题工作区/专题/无限直购/SQL/分析/index.md:17` | 默认单问与 batch 只作入口引用 | recognizer | 引用失真 | 不变 |
| `tests/test_gravity_sdk_adoption.py:112-139` | 只断言文档含 `agent --input`、host、`routing_mode` 等字符串 | 不执行 SDK/CLI | **可能仍绿**，检测不到上述语义破坏 | 仍绿 |

`work-dashboard` 没有直接 Python 调用 `discover_capabilities`、`Gravity.capabilities` 或 `capabilities_many`；它的风险是现行命令文档变成死路，而字符串门禁不会报警。

## 两种切法对照

证据等级：今天是当前代码实测；甲是精确常量反事实实测；乙是用现有两条执行臂做的契约回放，**公共接线尚未实现**。

| 场景 | 今天 | 切法甲：只翻常量 | 切法乙：有 selection 才走宿主 |
| --- | --- | --- | --- |
| 省略 `--routing`、无 selection | CLI query=`recognizer`；无 query=`recognizer` protocol | parser 默认 host，先读 required selection；query/protocol 都 `field=input` 失败 | `recognizer`，行为不变 |
| 省略 `--routing`、给了 selection | recognizer validator 拒绝，`field=routing` | CLI 默认 host，合法 selection 实测成功，`routing_mode=host_catalog`；但 direct SDK 默认仍是字面量 recognizer，反而 `field=routing` | 合法 selection 实测可由现有 host 端点成功解析；需要实现“routing 未给出”的判别 |
| 显式 `host_catalog`、无 selection | fail closed；CLI `field=input`，SDK `HOST_SELECTION_REJECTED/field=host_selection` | 同左 | 同左，不削弱 fail closed |
| SDK `discover_capabilities()` / `Gravity.capabilities()` | recognizer | **不是不变**：`field=routing` | 无 selection 仍 recognizer；`Gravity.capabilities` 尚无 selection 参数 |
| SDK/core batch | 每题 recognizer | 每题 error envelope，`failure_count=N` | schema 无 selection，仍 recognizer |
| 默认评测 | recognizer batch；recovery 再走 recognizer direct | batch 全错后 recovery 抛错，整次 run 中止 | 没 selection，仍 recognizer |
| 外部 selector 评测 | 独立 selector harness | 不受常量影响 | 不经过乙的运行时分派 |
| Plan execute | 不经 Agent routing | 不受影响 | 不受影响 |

## holdout 切默认后究竟测什么

### 确凿代码路径

```text
run_evaluation
  -> _run_evaluation_unrecorded
     -> load_cases(split, key)                         # 先打开受保护 split
     -> 无 --selector-plugin:
        _discover_trials
          -> capabilities_many
             -> discover_one
                -> discover_capabilities(routing="recognizer" 字面量默认)
        recovery_score
          -> discover_capabilities(routing="recognizer" 字面量默认)
     -> 有 --selector-plugin:
        external_selector_trials
          -> plugin subprocess
          -> _selection_result                         # 自建评测 envelope
          -> route_score
```

依据：`agent_usability_eval.py:694-739`、`:436-470`、`:516-555`；`agent_batch.py:190-205`；`agent_usability_external_selector.py:33-106,323-388`。

切法甲的结果不是“holdout 仍为 recognizer 数字”，而是更糟：精确常量翻转后，batch 中每题的字面量 recognizer 被新 validator 拒绝，随后 `recovery_score()` 的直接调用抛错，整个评测在生成结果前中止。`load_cases()` 已经在前面执行，ledger 追加却只在完整 run 成功后发生（`agent_usability_eval.py:790-812`）；若拿受保护 split 试它，会打开题集却得不到有效测量，白花机会。

切法乙若不改评测装置，则所有题都没有 selection，仍经 `capabilities_many` 测 recognizer。它不会从 195 自动变 235，也测不出“有 selection 才走 host”的运行时效果。

带 `--selector-plugin` 的旧宿主臂 holdout 235/240 也不是新默认路径：它使用 `external_selector_trials()` 和 `_selection_result()`，不经过 CLI parser、`host_routing_discovery()` 或 `resolve_host_product_selection()`。它证明“同一 catalog 上外部 selector 有条件更准”，不证明切法乙的公共 SDK/CLI 接线正确。

### 花 holdout 前必须补的同路径证据

必须先在 development 上增加一条**与准备发布的默认路径完全同构**的评测入口：调用方/selector 产出严格 `gravity.host-product-selection.v1`，然后实际经过切法乙 dispatcher 和仓库 `resolve_host_product_selection()`，再交现有 scorer。development 需要同时证明：

1. 无 selection 的 CLI、协议、batch、SDK、resolve-inputs 全部仍走 recognizer；
2. 有 selection 且省略 routing 的 CLI 和 SDK 实际走 host；
3. 显式 host 无 selection、显式 recognizer 带 selection 仍 fail closed；
4. evaluator 的默认/目标臂标签与真实调用路径一致，不再用 `_selection_result()` 旁路代替运行时；
5. 上述 development 路径绿后，受保护 holdout 只跑一次同一入口。

在这条证据存在前，无论甲还是乙，当前 holdout 都不能回答“切默认提升了多少”。

## J32 / J47：评分合同缺口

本轮重新运行公开 development 的只读 `agent_usability_host_arm_gap.py`：识别器 **277/336**，宿主合同上限 **334/336**，宿主赢 57、单独改错 0、共同失败 2。共同失败仍是：

| case | 宿主实际 `candidate_selectors` | scorer 可识别身份 | 结果 |
| --- | --- | --- | --- |
| `J32.dev.v3.multiple` | `metadata:table_lineage` + `gap:CURRENT_TABLE_SCHEMA_PARENT_MISSING` | `journey-targets.candidate_selectors` 只有 J32=`metadata:table_lineage`；J44 gap 无 selector | `wrong_intent_candidates` |
| `J47.dev.v3.multiple` | `gap:ANALYSIS_EXPORT_FILE_CONTRACT_MISSING` + `material.asset.fetch` | 只有 J48=`material.asset.fetch`；J47 gap 无 selector | `wrong_intent_candidates` |

确凿原因：

- expectation derivation 只把 `journey-targets.json.candidate_selectors` 投影进 multiple-intent expected（`agent_usability_expectations.py:101-151`）；产品 journey 缺 selector 会报错，gap journey 缺 identity 被允许。
- scorer 把 observed 的每个字符串反查到 journey；任一反查为 `None` 即失败，并要求 observed 数量等于 journey 数量（`agent_usability_eval.py:266-293`）。
- host oracle 已经按 gap 的注册 code 生成 `gap:<code>`（`agent_usability_host_arm_gap.py:217-246`），运行时 `product_selection_gap()` 原样保留这些 identities（`agent_host_selection.py:176-202`、`agent_intent_routing.py:280-303`）。

所以在**当前 scorer + 当前 targets + 当前正确宿主输出**不变时，这两题数学上不可满足：expected 有两个 journey，但映射表最多识别其中一个 identity；重复 identity 又被 scorer 拒绝。development 宿主分子将永久最多 **334/336**，直到评分合同改变。这个判断只针对公开 development 两题，不能推断 holdout 也恰好加 2。

改 scorer 的最小语义代价不是改两条 if：需要把 multiple-intent 的身份合同从“产品 selector”升级为“catalog identity（产品 selector 或 `gap:<code>`）”。可复用 host oracle 已有的 product-first、否则 gap identity 规则，但必须同步：

1. `journey-targets.json`/expectation derivation 的身份 schema 和一致性检查；
2. `_multiple_intent_score()` 及 scorer 单测，覆盖 product+gap、gap+product、重复/未知 identity 的 fail-closed；
3. scorer/suite 可比性版本。当前 `_suite_identity()` 只带 development/holdout sealed hashes，不带 scorer 或 journey-targets hash（`agent_usability_eval.py:678-691`）；若静默改 scorer，旧 195/235 与新分数表面可比、实际不是同一量尺；
4. 先用保存的公开 development observations 双评分，说明只有合同缺口改判，再决定是否接受新量尺进入唯一 holdout。

本趟按边界不改 scorer、targets 或 suite。

## 验证

全部命令带 `PYTHONPATH=src`，完整输出位于忽略目录 `tmp/codex/routing-callers/`：

| 验证 | 结果 |
| --- | --- |
| 当前 CLI protocol | exit 0；`mode=protocol`，`routing_mode=recognizer` |
| 当前 CLI batch | exit 0；`status=success`，item `routing_mode=recognizer` |
| 精确切法甲反事实 | CLI query/protocol 缺 selection；direct SDK `field=routing`；batch `failure_count=N`；显式 recognizer 不再是 choice |
| 切法乙端点回放 | 无 selection=`recognizer`；有 selection=`host_catalog`；显式 host 无 selection fail closed |
| development 两臂差距脚本 | 识别器 277/336；宿主合同上限 334/336；只败 J32/J47；生产 HTTP 0 |
| `unittest discover -s tests` | **Ran 1312 tests / OK**，不低于本任务基线 |
| `pytest -q` | **1312 passed / 3390 subtests passed** |
| compiler | 237 operations / 11 manifests |
| quality | PASS；`operation_literals=36 (ratcheted)` |
| development usability gate | 选择层 277/336；pass^4 277/336；安全 PASS；生产 HTTP 0 |
| `python -m gravity_sdk --help` | exit 0 |
| `git diff --check` | exit 0 |

本趟没有源码、raise 或质量 baseline diff；`tests/test_actionable_error_audit.py` 仍钉住并由全量测试验证 `1268 / A1018 / B250 / C0`。`quality-baseline.json` 没有 `hard_limit` / `threshold` / `max_` 改动，`client.py` 未碰。

## 确凿事实与推测

### 确凿

- `DEFAULT_ROUTING_MODE` 是“CLI 默认 + recognizer 合法身份 + choices 成员”三合一常量；只翻它会破坏 SDK/batch/evaluator，不是 CLI-only 改动。
- 当前所有 13 个运行时/脚本调用点和 157 个测试调用点都没有显式 `routing=`。
- Plan 执行面不调用 Agent 路由；受影响的是 Plan 前的默认发现命令。
- 默认 evaluator 固定走 batch recognizer；外部 selector evaluator 旁路运行时 host resolver。
- 切法乙保持所有今天成功的无 selection 调用继续成功，但当前 SDK facade/batch 没有承载 selection 的输入面。
- J32/J47 在当前 scorer 下不可满足，宿主 development 分子上限是 334。

### 推测 / 尚未决定

- 切法乙的具体 API 形状尚未决定：`routing=None` sentinel、独立 `requested_routing`，或 CLI 层判断都能实现，不能由本次审计替维护者选定。
- `Gravity.capabilities()` 是否增加 `host_selection`，以及 batch 是否接受逐题 selection，属于尚未定义的公共合同；不能假定 CLI 乙自动覆盖 SDK/batch。
- 将真实切法乙路径接进 evaluator 后的 holdout 分数未知。旧 235/240 来自外部 selector harness 和旧 revision，不能抄成新默认结果。
- scorer 若升级 identity 合同，受保护分数会改变多少未知；本轮只证明公开 J32/J47 从当前合同上不可满足。

## 动线台账

未改 `docs/analysis-journeys.md`。本趟没有新增或闭环产品动线，状态列、表头汇总和冻结 case 都不应变化。J32/J47 的冻结 case 本来就与当前 scorer identity 合同不一致；本轮只记录原因，不改 case。

## 我建议切法乙，因为它不减能力；花这次 holdout 之前还缺什么

我建议最终采用**切法乙**，因为它把已有 selection 当成选择 host 的充分信号，同时让所有今天成功的无 selection 调用继续走 recognizer，并保留显式 host 缺 selection 的 fail-closed。切法甲应直接淘汰：它会删除 recognizer 这个合法 choice，破坏 SDK/batch/evaluator，连协议面都会死。

但**现在还不该切，也不该花 holdout**。还缺三项阻塞证据：

1. 定义并实现乙在 CLI、`discover_capabilities`、`Gravity.capabilities`、resolve-inputs 和 batch 上的精确公共合同；batch 若不支持 selection，要明确写成 recognizer-only，而不是含糊地叫“默认已切”。
2. 让 development evaluator 经过同一个乙 dispatcher + `resolve_host_product_selection()`，证明真实运行时而不是外部 `_selection_result()` 旁路；先把全量 caller 回归跑绿。
3. 在花 holdout 前决定 J32/J47：要么先升级并版本化 scorer 的 catalog-identity 合同，要么书面接受当前量尺下宿主 development 分子永久少 2；不能测完后再改尺。

三项完成后，唯一一次 holdout 才能测“准备发布的默认路径”。按当前装置直接跑，只会得到 recognizer、独立 external selector，或切法甲的中止，三者都回答不了问题。
