# 宿主臂 97.9% 对识别器 81.25%：差距变成调用方真能走完的两步

- 日期：2026-08-19
- 任务：#218
- 结论：不切 `DEFAULT_ROUTING_MODE`；识别器信封现在带齐选择 schema / 抄得走的模板 / `then_argv`，拼错选择结构会落到 `field=`；development 上识别器 277/336，宿主合同走完注册身份是 334/336。

本轮生产 HTTP **0**。未读 holdout / final / `.local/agent-usability/*.key` / `*.sealed.json`。未改评测装置、题集、评分、层定义、阈值。未改 `DEFAULT_ROUTING_MODE`，未把 `--host-selection` 改成可选。

## 发了什么请求、拿到什么响应

全部离线，`PYTHONPATH=src`。

| 请求 | 响应要点 |
| --- | --- |
| `discover_capabilities("看一下事件趋势")` | `mode=discover_and_describe`，`routing_mode=recognizer`，`floor=true`；3 张卡 `analysis.query.spec:event` / `analysis.event.info` / `analysis.event.list` |
| 改前 `routing.upgrade` 键 | `when` / `next_action` / `next.argv` / `next.then_argv`。**没有** schema、没有可抄模板 |
| 改后 `routing.upgrade` 键 | 上列加上 `selection_schema_version` / `selection_schema` / `selection_example` |
| `gravity agent-catalog host` | `mode=host_product_catalog`，102 entries = 96 product + 6 gap，约 76 KiB compact / 99 KiB pretty，`network_called=false` |
| 用 host 的 `selection_template` 填 `analysis.query.spec` 再 `--routing host_catalog --host-selection` | `mode=host_catalog_select_and_describe`，`routing_mode=host_catalog`，`floor=false`，无 `upgrade`，选出 `analysis.query.spec`，0 HTTP |
| 同一选择去掉 `candidates[0].reason.boundary_check` | CLI 退出码 4；`error.field=host_selection.candidates[0].reason`，`code=HOST_SELECTION_REJECTED`，`next_action` 含 `field=` |
| development 336 题 × 1 trial `capabilities_many` + `route_score` | 识别器 **277/336** |
| 同一 336 题按 `journey-targets` 写出合法 `gravity.host-product-selection.v1` 再 `resolve_host_product_selection` | **334/336**；失败只剩 J32 / J47 的冻结 scorer `wrong_intent_candidates` |

`then_argv` 实测形状：

```text
["gravity", "agent", "<同一 query>", "--routing", "host_catalog", "--host-selection", "<gravity.host-product-selection.v1>"]
```

选择结构必填字段（host 的 `response_schema.required`，也写进信封 `routing.upgrade.selection_schema`）：

`schema_version` / `catalog_sha256` / `query` / `decision` / `reason` / `candidates`

`decision` 必须与候选数一致：0=`abstained`，1=`selected`，2..5=`multiple_intents`。

## 1. 零知识走宿主臂要几步

| 步 | 命令 | 输出规模 | 进程 / HTTP | 没读过源码会不会卡住 |
| --- | --- | ---: | --- | --- |
| 0 | `gravity agent`（无 query） | 协议信封，含 `routing.upgrade` | 1 / 0 | 改前：知道有宿主臂，但看不到选择长什么样。改后：协议里就有 schema 和模板 |
| 1 | 默认 `gravity agent "<问题>"` | 识别器地板 + 常设 `routing.upgrade` | 1 / 0 | 改前：`then_argv` 有占位符，不知道 JSON 必填键。改后：信封自带 schema / example，仍缺真实 `catalog_sha256` 和 `catalog_ref` |
| 2 | `upgrade.next.argv` = `gravity agent-catalog host` | 102 条，约 76–100 KiB；现另有 `catalog_refs` 和 `selection_template` | 1 / 0 | 改前：要读完 entries 才能猜字段。改后：抄 `selection_template`，从 `catalog_refs` 选一个 |
| 3 | 照抄 `upgrade.next.then_argv`，把占位符换成上一步填好的 JSON | 1 张仓库 describe 的产品卡或规范 gap | 1 / 0 | 改前：拼错只报 `field=host_selection`。改后：报到 `host_selection.candidates[0].reason` 这一级 |
| 4 | 卡上的 `next.argv` / `plan run` | 执行面，本趟不跑 | 视产品而定 | 与原来相同；识别器 / 宿主臂都不执行产品 |

一条完整升级：**3 次进程启动，0 次 HTTP**（步 1→2→3）。调用方一上来就知道自己能选时，可跳过步 1，**2 次进程、0 HTTP**。

`host` 没有分页、没有可执行 `next.argv`。调用方必须自己写 `gravity.host-product-selection.v1`。这是合同，不是遗漏。

## 2. 那 16.65pp 赢在哪（development 实测，不是 holdout）

留出集 195/240 vs 235/240 引用已入账的配对记录，本轮**没有**打开 holdout。本轮只跑 development。

### 确凿事实

| 臂 | development 选择层 | 失败构成 |
| --- | ---: | --- |
| 识别器（默认） | **277/336 (82.44%)** | `no_candidate 41` / `wrong_product 5` / `multiple_intents_missing 4` / `wrong_intent_candidates 5` / `wrong_gap 4` |
| 宿主合同上限（调用方按注册身份交选择） | **334/336 (99.40%)** | `wrong_intent_candidates 2`（J32、J47） |

277 = 与 `recognizer-handoff.md` / `selection-residual.md` 同一选择层。334 不是再跑一遍宿主模型：题集 identity 写进合法选择结构后，仓库 describe / 规范 gap 能过 `route_score`。这是「调用方真能产出选择时」这条臂的上限。

识别器 59 道错里，**57 道**在宿主合同上限上变对，**2 道**两边都错。宿主没有单独把对题改错。

57 道按识别器失败原因归并后是 **四类系统问题**，不是四五道互不相关的题：

| 类 | 题数 | 识别器在干什么 | 宿主臂为什么赢 |
| --- | ---: | --- | --- |
| A. 词表够不着 | 35 | 口语省略 11 / 间接目标 10 / 首轮缺槽 7 / 否定句切完 7，词法命中为空 | 调用方读 102 条产品/gap 描述，不靠词表 |
| B. 多意图仲裁 | 9 | 3 道收成一张卡、3 道候选集不对、3 道交出 `UNRANKED_OPERATIONS` | 选择结构允许 0..5 个 `catalog_ref`；1 个 describe，多个走 `MULTIPLE_INTENTS` |
| C. 邻接 / 任务交接误吸 | 5 | 4 道进 `analysis.task.handoff`，1 道投放复盘进推广卡 | 调用方按 host 边界勾选，不受 handoff 兜底 |
| D. gap 词面过窄或错字 | 8 | 4 道 gap 词面（含「此刻 schema」）、3 道错字空、1 道 target-gap 空 | 调用方选已登记 gap 或正字产品 |

A 是主因（35/336 ≈ 10.4pp，占 development 57 道差距的六成）。B+C+D 是另外三簇，每簇都能被「调用方读目录再选」消掉，再加词法规则救不回来（见 `selection-residual.md`）。

宿主合同上限仍败的 2 道：

| case | 仓库实际返回 | 冻结 scorer 要什么 |
| --- | --- | --- |
| `J32.dev.v3.multiple` | `MULTIPLE_INTENTS` = `metadata:table_lineage` + `gap:CURRENT_TABLE_SCHEMA_PARENT_MISSING` | `candidate_selectors` 只登记产品 journey，不认 gap 身份 |
| `J47.dev.v3.multiple` | `MULTIPLE_INTENTS` = `gap:ANALYSIS_EXPORT_FILE_CONTRACT_MISSING` + `material.asset.fetch` | 同上 |

语义上选对了。这是评分合同缺口，不是宿主臂选错。本轮按硬约束不改 scorer / 题集。

### 推测

- 留出集 +16.65pp 的构成应与 development 同类：主因是词表够不着，其次多意图和邻接误吸。holdout 题面未打开，不能把 37/9/5/6 这组数字抄到 240 题上。
- 留出集宿主臂 235/240 比本轮合同上限 334/336 低，是因为那次是盲选模型，不是注册身份重放；模型会 abstain 或选邻接产品。本轮没有复跑该模型。
- 留出集宿主臂 `target_gap_missing` 4→5 更像高召回不愿弃权。development 合同上限没有把对题改成错 gap。

## 3. 本轮修了什么（默认值未动）

判据：只读到信封、没读过源码的 agent，能不能靠信封走完升级。

| 开口 | 改前 | 改后 |
| --- | --- | --- |
| 信封升级字段 | 有命令，无合同 | `routing.upgrade` 带 `selection_schema_version` + `selection_schema` + `selection_example` |
| `agent-catalog host` | 有 `response_schema`，要自己拼 | 另给当前指纹的 `selection_template` 和 `catalog_refs` |
| 选择拼错 | `field=host_selection`，codes 挤在 message 里 | `field=` 落到第一个 violation（例如 `host_selection.candidates[0].reason`），`next_action` 重复该 field |

未改：`DEFAULT_ROUTING_MODE="recognizer"`；`--host-selection` 在 `host_catalog` 上仍 `required=True`；识别器路径、词法回退、`UNRANKED_OPERATIONS` 交接都还在。

## 4. 切默认值决策包

### 确凿事实：今天默认值锁在哪

| 面 | 默认臂 | 依据 |
| --- | --- | --- |
| CLI `gravity agent <query>` | `recognizer` | `add_host_routing_arguments` 的 `default=DEFAULT_ROUTING_MODE` |
| SDK `discover_capabilities()` | `"recognizer"` | `agent.py` 关键字参数写死字符串，**不是**读 `DEFAULT_ROUTING_MODE` |
| SDK `Gravity.capabilities()` | 识别器 | 不传 `routing` / `host_selection` |
| `capabilities_many` / `agent --input` | 识别器 | 内部调 `discover_capabilities` 且不传 routing |
| Plan | 不经 Agent 路由 | 没有 `--routing`；宿主 Plan 走 `execute_host_plan` |
| 评测 development | 识别器 | `_discover_trials` → `capabilities_many` |
| `work-dashboard` | 文档把宿主臂写成主路径，但命令是**显式** `--routing host_catalog --host-selection`；默认 `gravity agent "问题"` 仍当地板 | `10_数据底座/Gravity数据访问与业务口径.md` 第 70–106 行；`tests/test_gravity_sdk_adoption.py` 只锁命令字符串，不锁默认臂 |

因此：只改 `DEFAULT_ROUTING_MODE` 会打断 **CLI 省略 `--routing` 的调用**，**不会**自动打断 SDK facade / 批量发现 / 评测，除非连 `discover_capabilities` 的默认参数一起改。两边一起改才会让「默认」真的变成宿主臂。

显式 `--routing host_catalog` 且不给选择：`load_json_input(..., required=True)` 当场失败。这是正确的 fail-closed，本轮保持。

### 确凿事实：切了默认值会坏谁

假设把 CLI 和 `discover_capabilities` 的默认都改成 `host_catalog`，且 `--host-selection` 仍 required：

| 调用方 | 今天 | 切完 |
| --- | --- | --- |
| `gravity agent "<query>"` | 识别器候选卡 | 缺选择，caller error |
| `gravity agent`（无 query，协议） | `mode=protocol` | 若默认路由先于「无 query」分支，协议面也会断；当前实现是先看 routing 再看空 query |
| `gravity agent --input questions.json` | 批量识别器 | 内部不传 selection，整批失败 |
| `Gravity.capabilities(query)` / `discover_capabilities(query)` | 识别器 | 若函数默认跟着改：同样缺 selection 失败 |
| Plan / `execute_host_plan` | 不受影响 | 不受影响 |
| 评测默认臂 | 277/336 识别器 | 若装置不改：变成「未给 selection 的宿主臂」，与冻结 case 对不上 |
| `work-dashboard` 显式宿主臂命令 | 已带 `--routing` 和 selection | 不坏 |
| `work-dashboard` 默认 `gravity agent "问题"` | 识别器地板 | 当场失败，文档里的地板路径断了 |

这是能力对调用方退化。本轮明确不做。

### 不破坏调用方的切法（确凿行为差，不是已实现）

「默认想走宿主臂，没给选择就退回识别器并在信封里声明」和今天的差：

| | 今天 | 该切法 |
| --- | --- | --- |
| 省略 `--routing` 且无 selection | 识别器 | 仍是识别器（行为不变） |
| 省略 `--routing` 但给了 `--host-selection` | **错误**（recognizer 不得带 selection） | 走宿主臂 |
| 显式 `--routing host_catalog` 无 selection | 错误 | 仍应错误（fail-closed 不削弱） |
| 信封 | `routing.mode=recognizer`，`floor=true` | 无 selection 时同样；有 selection 时 `mode=host_catalog`，`floor=false` |

这不算能力退化：所有今天能成功的调用仍然成功；多出来的是「只交选择、不写 `--routing`」这条今天被拒绝的路。它也**不会**单独把 81.25% 变成 97.9%，因为默认路径仍是识别器，除非调用方真的交选择。

要把默认数字切到宿主臂，调用方必须开始交选择。SDK 自己不调模型。

### 花那一次 holdout 之前还需要的证据

**已经有的（确凿）：**

- 同 revision 留出集配对：195/240 → 235/240，安全 PASS。见 `routing-arms-paired-holdout.md`。
- 本轮 development：识别器 277/336，宿主合同上限 334/336；57 道差距可归为四类系统问题。
- 信封现在够一个没读过源码的 agent 走完 2–3 步；选择拼错有 `field=`。
- 识别器路径测试仍绿；默认值未改。

**还没有、必须在 holdout 前补齐的：**

1. 选定切法的**精确 CLI 合同**（只翻 `DEFAULT_ROUTING_MODE`，还是「有 selection 就走宿主、没有就识别器」）。两种切法的 holdout 对照集不同。
2. 对 `work-dashboard`、本仓测试、脚本做一次「省略 `--routing` 的 `gravity agent` / `discover_capabilities` / `--input`」清单，证明切法 1 会断、切法 2 不断。本轮已抽样，不是全量仓库外扫描。
3. 若切法让默认路径变成「必须先 `agent-catalog host`」，要补一条 development 上的**步数**对照：未知问题从 1 次发现变成 2 次。holdout 分数不能掩盖步数回归。
4. 宿主臂 holdout 235/240 用的是外部模型插件，不是合同重放。若切默认后评测仍走 `capabilities_many`（识别器），holdout **不会**自动变成 235。要测默认臂，必须先定义评测默认路径，且不能在开发轮次偷跑 holdout。
5. J32 / J47 冻结 scorer 与协议不一致。切默认前应决定：改 scorer，或接受宿主臂分子永远少这 2 道。本轮无权改 scorer。

### 推测（与上面分开）

- 对 agent 消费方，切法 2（有 selection 才走宿主）比翻默认字符串更安全，也更接近「97.9% 那条路已经通了」。
- 在信封升级可被独立 agent 走通之前就翻默认，holdout 即使 +16pp 也不能证明调用方拿得到；本轮把这个前置补上了。
- 现在可以安排那一次受保护 holdout。建议对照的是切法 2 的显式宿主臂，而不是先翻默认再测。

## 5. 测试与门禁

每处修一条会红的测试，均在 `tests/test_agent_host_selection.py`：

| 测试 | 红 | 绿 |
| --- | --- | --- |
| `test_recognizer_upgrade_carries_selection_schema_and_copyable_example` | `KeyError: selection_schema_version` | OK |
| `test_host_catalog_exposes_copyable_selection_template` | `KeyError: selection_template` | OK |
| `test_malformed_selection_names_the_broken_field` | `field` 仍是 `host_selection` | `field=host_selection.candidates[0].reason` |
| `test_cli_default_and_unspecified_behavior_remain_recognizer` | （回归，未改期望） | 仍绿 |

未改 `quality-baseline.json` 的 `hard_limit` / `threshold` / `max_`。未改 `operation_literals`。`client.py` 未碰。

门禁摘要（`PYTHONPATH=src`，help 类测试需 `PYTHON_COLORS=0`，否则本机 Python 3.14 给 `--help` 上色，与本趟无关）：

| 门禁 | 结果 |
| --- | --- |
| `unittest discover -s tests` | **Ran 1236 tests / OK**（基线 1233，+3） |
| `pytest -q` | **1236 passed / 3148 subtests** |
| `compiler check` | 237 operations / 11 manifests |
| `quality check` | PASS；`operation_literals=57` 未升 |
| development 评测 | 选择层 **277/336**，安全 PASS，生产 HTTP 0 |
| 错误库存 | 仍 **1268 / A896 / B372 / C0** |
| `git diff --check` | 0 |

## 动线台账

未改 `docs/analysis-journeys.md`。本趟不闭环产品动线，表头 `56 = x / y / z` 不应变，状态列不变。冻结 case 目标身份不变；J32 / J47 选择层仍会对不上 scorer，与 `#gap-multi-intent` 已记录的合同缺口相同。

## 明确未做

- 未改 `DEFAULT_ROUTING_MODE`，未改 `--host-selection` 的 required。
- 未改评测装置、题集、评分、层定义、阈值。
- 未运行 holdout / final / all。
- 未读 key，未碰 sealed。
- 未写 `docs/roadmap.md`。
- 未 push、未碰 GitHub。
