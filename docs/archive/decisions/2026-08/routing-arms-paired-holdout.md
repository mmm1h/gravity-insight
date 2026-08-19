> 归档材料：保留历史决策与取证，不代表当前接口或状态；当前入口见 docs/index.md。

# 两臂配对留出集：宿主臂有条件更优

- 日期：2026-08-18
- 任务：#routing-arms-paired-holdout（工作目录 `wt-routing-evidence`，分支 `grok/routing-evidence`，基线 `dev@685ec19`）
- 结论：同 revision `34e9a8e`、同目录下，调用方能产出选择时宿主臂留出集首选产品 195/240 → 235/240（+16.67pp）；不切 `DEFAULT_ROUTING_MODE`，因为 `host_catalog` 不调模型、缺 `--host-selection` 会让无选择的调用方当场失败。

本轮 **0 次生产请求**。未运行 holdout / final / all，未读 key，未改评测装置、题集、评分或阈值。数字引用已入账的 query-ledger ordinal 5 / 6，以及同一 revision 上由操作方给出的 development 配对摘要。

## 发了什么请求、拿到什么响应

没有对本轮再发评测或上游请求。引用的是已经写入
`evals/agent_usability/query-ledger.jsonl` 的两条 append-only 记录：

| 项 | 臂 A ordinal 5 | 臂 B ordinal 6 |
| --- | --- | --- |
| `git_revision` | `34e9a8ee9a14b044ab30fcf4e098531c4d112877` | 同左 |
| `product_source_sha256` | `d0350288501702050acace6a1ddceac8f977b7a0ba56fddc6e3319bd0e8249af` | 同左 |
| `evaluator_source_sha256` | `a833e1ad21992c2547b7f8b33a7a11d832c2854e8e94223ebd1b82cbce9bc093` | 同左 |
| `suite_version` | `gravity-agent-usability-2026-08-16.v4` | 同左 |
| `split` / `case_count` / `trials` | holdout / 240 / 4 | 同左 |
| `selector_arm.mode` | `product_recognizer_with_zero_candidate_lexical_fallback` | `external_selector` |
| `git_worktree_dirty` | `false` | `true` |
| `security_compliance` | `passed=true` / `violation_count=0` | 同左 |
| `run_at` | `2026-08-17T21:07:47Z` | `2026-08-17T21:12:08Z` |

臂 B 的 selector 身份：`plugin_sha256=49cff6f2…464c665`，
`selector_version=anthropic-compatible/claude-sonnet-4-6/host-selector.v1`，
`protocol=gravity.agent-external-selector-request.v1`，
`request_sha256_verified_trials=4`。网络次数由插件自报（`network_measured=false`）。

这是宿主臂第一次有效的留出集测量。ordinal 2 的 purpose 写明：插件没跑起来，当时记的是臂 A 的数字。

## 确凿事实

### 留出集四层（ledger）

| 层 | 臂 A `recognizer` | 臂 B `host_catalog` |
| --- | ---: | ---: |
| 首选产品 | 195/240 (81.25%) | **235/240 (97.92%)** |
| 参数可填 | 156/164 (95.12%) | 195/205 (95.12%) |
| 离线终点 | 31/35 (88.57%) | 30/35 (85.71%) |
| 错误恢复 | 5/5 | 5/5 |
| 安全 | PASS / 0 | PASS / 0 |

参数可填率相同，分母不同：臂 B 选出了更多产品，所以进入填参层的题更多。

### 留出集构成（操作方配对摘要，ledger 只存聚合）

| 构成 | 臂 A | 臂 B |
| --- | ---: | ---: |
| `no_candidate` | 27 | **0** |
| `wrong_product` | 11 | **4** |
| `ambiguous` | 4 | **0** |
| 离线终点 `target_gap_missing` | 4 | **5** |

`no_candidate` 27→0 是最有说服力的一条：宿主臂在调用方已产出选择时不再把题丢掉。
`240 − 195 = 45`，上表前三行只解释 42 个选择失败；其余 3 个选择失败本轮没有逐题分类，不补。

### 同 revision 的 development（操作方配对摘要，不是 ledger 行）

| 层 | 臂 A `recognizer` | 臂 B `host_catalog` |
| --- | ---: | ---: |
| 首选产品 | 267/336 (79.46%) | **333/336 (99.11%)** |
| 离线终点 | （本轮未单列） | **60/60** |

臂 A 的 267/336 与 `docs/roadmap.d/recognizer-recall.md` 在撤回对着题集加的词之后的 development 选择层一致。

### 运行时合同（本轮未改）

`src/gravity_sdk/agent_host_selection.py`：

- `DEFAULT_ROUTING_MODE = "recognizer"`
- `HOST_ROUTING_MODE = "host_catalog"`
- `host_catalog` **消费已经产好的** `gravity.host-product-selection.v1`，SDK 自己不调模型
- `--host-selection` 在该模式下 `required=True`；不带选择的调用当场 `InputValidationError`

因此把默认值翻成 `host_catalog`，每一个不带 `--host-selection` 的 CLI / 脚本 / Plan 调用都会缺参失败。那是能力对调用方退化，本轮明确不做。

### 臂 B 不是无条件更优

前提是**调用方本身是 LLM、能产出严格选择**。纯 CLI、脚本、不会写
`gravity.host-product-selection.v1` 的调用方必须继续走默认 recognizer。

两个限制必须并记：

1. **离线终点臂 B 少 1 题**（`target_gap_missing` 4→5）。这是高召回的反面：它更不愿意说“这个不支持”，偶尔在该返回 gap 的地方找出一个看着合理的产品。
2. **harness 对选择理由不可独立核验。** 臂 B `selector_self_report_measurements.result_reason.measured=false`，原因原文是：
   `the harness observes the text and selected selectors but has no independent selector decision trace`。
   臂 B 有一部分是自报；`meaningful_accuracy_evidence`、`stdin_encoding`、`additional_metadata` 同样 UNMEASURABLE。可核验的是 `request_sha256` 与 `selector_version_plugin_sha_binding`。

ordinal 6 的 `git_worktree_dirty=true`。产品与评测器哈希与 ordinal 5 相同，但不能从 ledger 还原当时脏的是哪些未提交文件。

## 推测

- 臂 B 多出的 1 个 `target_gap_missing`，更像“高召回不愿 abstain”，不是评分器改判。本轮没有逐题打开 holdout，所以这是对构成数字的解释，不是新测量。
- development 333/336 与留出集 235/240 方向一致，说明优势不是只拟合 development；具体哪 3 道 development 仍失败，本轮没有拆。
- 脏工作区更可能是评测插件或 ignored `tmp/`，不是产品哈希已变；依据只是两个 ordinal 的 `product_source_sha256` 相同。

## 本轮落地（文档与 Agent 面，不切默认）

- 默认 `recognizer` 保持不变，写成“够不着宿主时的地板”，不是劣等品；recognizer 路径、卡面、词法回退均未削弱。
- 调用方能产出选择时，Agent 工作流与任务指南推荐
  `gravity agent-catalog host` → 严格 `gravity.host-product-selection.v1` →
  `gravity agent --routing host_catalog --host-selection`。
- 动线台账状态列与表头汇总未改；本趟不闭环任何动线。

## 明确未做

- 未改 `DEFAULT_ROUTING_MODE`。
- 未改评测装置、题集、评分、层定义、阈值。
- 未运行 `scripts/agent_usability_eval.py run --split holdout|final|all`。
- 未读、未复制、未推断 `.local/agent-usability/*.key`，未查看任何 `*.sealed.json`。
- 未写 `docs/roadmap.md`，未重算 `docs/analysis-journeys.md` 表头。
- 未 push、未碰 GitHub。
