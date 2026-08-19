> 归档材料：保留历史决策与取证，不代表当前接口或状态；当前入口见 docs/index.md。

# 已登记 gap 不再吞掉同问的其余意图

- 日期：2026-08-18
- 任务：#197
- 结论：多意图识别先于整句 gap 短路；一个能答、一个已登记 gap 的同问现在返回 `multiple_intents`，两个意图都列出来。单意图 gap 题终态变化 0。

## 确凿事实

本轮 **0 次生产请求**。只读本地协议、冻结 development 题集和离线评测。

### 改动前协议顺序

`capability_handoff_cards` 与 `operation_fallback_gap` 都先跑 `unavailable_journey_gap(整句)`。
整句一旦命中已登记 gap，直接返回该 gap，`multiple_intent_gap` 根本不跑。

对两道目标题实测（改前）：

| case | 提问 | 实际终态 |
| --- | --- | --- |
| `J32.dev.v3.multiple` | 我要已同步的表变更历史，也要这个表此刻的完整字段与当前版本。 | `capability_gap` / `CURRENT_TABLE_SCHEMA_PARENT_MISSING`；`candidate_selectors` 空；lineage 半句未出现 |
| `J47.dev.v3.multiple` | 既要把用户事件结果导出成文件，也要按素材引用下载原始视频。 | `capability_gap` / `ANALYSIS_EXPORT_FILE_CONTRACT_MISSING`；素材下载半句未出现 |

`multiple_product_intents` 的分句收集器当时只认 analysis/composite 卡，不认 `metadata:table_lineage`、`material.asset.fetch` 和 `gap:*`。

### 改了什么

1. `operation_fallback_gap`：有中文并列协调词时，先走 `multiple_intent_gap`，再走整句 unavailable gap。
2. 分句收集器：只在「以及 / 同时 / 连同 / 和其他 / 既要|既看 / 也要|也看|也比较」下，对**每一分句**独立判定 lineage / 素材下载 / 已登记 gap。
3. `multiple_intent_gap`：信封仍是既有 `MULTIPLE_INTENTS`；被分句命中的 gap 原样附在后面，保留原来的 `gap_code`、`reason`、`next_action` 和 `next.argv`。
4. 素材卡中文证据补「素材引用」（卡面/台账已有「精确平台素材引用」，不是题面专造词）。
5. 英文列表里的 `and` **不**打开分句 handoff，也**不**覆盖整句已登记 gap。否则 J45 英文首问 `campaign, ad-group, and creative ... Kuaishou and Tencent` 会被拆成 `material_performance` + `promotion_performance`。

未改：评测题集、评分逻辑、层定义、阈值、`_positive_query_selectors` 整句路径、`docs/roadmap.md`、质量 baseline。

### 改动前后 development 对比

官方 `scripts/agent_usability_eval.py run --split development`，生产 HTTP 0。

| | 改动前 | 改动后 |
| --- | ---: | ---: |
| 选择层通过 | 277/336 | 277/336 |
| raw `terminal_kind` 判对 | 238/336 | 240/336 |
| 离线终态层（scorer `end_to_end`） | 49/60 | 51/60 |
| **单意图 gap 题里终态发生变化的** | — | **0** |

选择层分子不变，是因为冻结 scorer 要求 `candidate_selectors` 精确等于 `journey-targets.json` 里的 public product selector。J44 / J47 没有登记 selector；信封里现在是 `gap:CURRENT_TABLE_SCHEMA_PARENT_MISSING` 与 `gap:ANALYSIS_EXPORT_FILE_CONTRACT_MISSING`。这是评分合同缺口，不是协议回退。未改题、未改 scorer。

`terminal_kind` 按 raw case 的 `expected.terminal_kind` 计：`multiple_intents` 题看响应是否出现 `MULTIPLE_INTENTS`。+2 恰好是 J32 / J47。其余 334 题 `status` / `gap_codes` / `first_candidate` 与改前逐题相等。

单意图 gap 题（derived `gap_code` 且不是 `MULTIPLE_INTENTS`）共 41 道，终态变化清单为空。

选择层失败类变化仅发生在这两道：`multiple_intents_missing` 6→4，`wrong_intent_candidates` 3→5。其余失败类计数不变。

### 两道 `.v3.multiple` 改后实际输出

| case | status | journey 对应 | `capability_gaps` |
| --- | --- | --- | --- |
| `J32.dev.v3.multiple` | `capability_gap` | J32 能答 + J44 gap | `MULTIPLE_INTENTS`（`metadata:table_lineage`, `gap:CURRENT_TABLE_SCHEMA_PARENT_MISSING`）+ 原样 `CURRENT_TABLE_SCHEMA_PARENT_MISSING`（含 sync argv） |
| `J47.dev.v3.multiple` | `capability_gap` | J47 gap + J48 能答 | `MULTIPLE_INTENTS`（`gap:ANALYSIS_EXPORT_FILE_CONTRACT_MISSING`, `material.asset.fetch`）+ 原样 `ANALYSIS_EXPORT_FILE_CONTRACT_MISSING`（含 `gravity export list-capabilities`） |

单问对照：`按表名或 App 查询数据表当前 schema、字段和版本。` 与 `导出事件、分群、用户、付费或变现分析结果。` 仍只回各自原 gap，一字未变。

### 验证

- `PYTHONPATH=src python -m unittest discover -s tests`：1199（基线 1198 + 本趟 1）；与本改动相关的 3 个 CLI help 失败是本机 ANSI 色码，基线即有，与协议无关。
- `PYTHONPATH=src python -m pytest -q`：同一 3 个 help 失败；其余 1196 passed。
- `compiler check` / `quality check` 通过。`git diff -- src/gravity_sdk/governance/quality-baseline.json` 为空（无 `hard_limit` / `threshold` / `max_` / `operation_literals` 改动）。
- `C=0`：`test_actionable_error_inventory_is_complete_and_reproducible` 通过。本趟无新增 raise。
- 未读、未写 `docs/roadmap.md`。未 push、未碰 GitHub。

## 推测（不是证据）

若以后要把这两道选择层也变绿，需要在 `journey-targets.json` 给 gap 动线登记稳定 selector（例如 `gap:<CODE>`），或让 scorer 接受 gap selector。那是评分合同变更，本趟不做。

## 台账

`docs/analysis-journeys.md` 只改了 J32 / J47 对应两行的备注，**状态列未改**（J32 仍已闭环，J47 仍部分闭环）。表头 `56 = x / y / z` 不需要变。冻结 case 的 raw `terminal_kind=multiple_intents` 现在对得上协议；选择层期望的 public selector 集合仍对不上，见上。
