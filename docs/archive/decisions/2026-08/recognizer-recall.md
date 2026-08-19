> 归档材料：保留历史决策与取证，不代表当前接口或状态；当前入口见 docs/index.md。

# 识别器召回收尾：J36 回归与防过拟合

- 日期：2026-08-18
- 任务：#recognizer-recall2（工作目录 `wt-recognizer-recall`，分支 `grok/recognizer-recall2`，检查点 `8d2bee5`）
- 结论：J36 中文首问重新可达；根因是否定抽取把「别人」截成「别」，不是新卡挤掉报表目录。对着题集加的词已撤；选择层从检查点的 291/336 回到 267/336。

## 确凿事实

本轮 **0 次生产请求**。只读本地代码、冻结 NL 矩阵、quality 门禁和 `development` 离线评测。

### J36 回归

冻结问法：

`帮我找出我自己的、别人共享给我的以及 MasterKey 报表，并读取报表定义。`

检查点 `8d2bee5` 上实测：

| 项 | 结果 |
| --- | --- |
| `affirmative_intent_text` | `帮我找出我自己的` |
| `report_directory_query` | `false` |
| `discover_capabilities` | `capability_gap`，无候选 |
| 词法检索 | `below_threshold`，top 0.132692 |

修复后同一问法：

| 项 | 结果 |
| --- | --- |
| `affirmative_intent_text` | 整句保留（仅 casefold） |
| `report_directory_query` | `true` |
| `discover_capabilities` | `success`，首候选 `composite:report_directory` |
| 英文问法 | 始终 `success` / `composite:report_directory` |

`tests.test_gravity_insight_agent_ux.DiscoveryUxTests.test_frozen_natural_language_journey_matrix_is_first_call_reachable` 全绿。

根因不在新注册的 `app.list` / `app.app_info.get` / `report.get.query` 卡。词法检索对 J36 中英文都低于阈值，从未参与首问排序。真正截断发生在 `agent_intent_text._NEGATED_TAIL`：检查点把 `别(?:给|再|要)?` 加成否定标记，子串「别人」被当成禁止词。

修复：禁止词 `别` 只在后面不是「人/的/样/处/称/名」时生效，并要求左侧不是汉字。因此「别人共享给我的」不再被截断，「别给我素材报表」「别查经营脉搏」仍整句否定。

### 检查点里对着题集加的词

对照 `evals/agent_usability/cases/development.jsonl` 后撤回，因为来源说不清、或只救一道评测原句：

`隔一天`、`占多少`、`这礼拜`/`上礼拜`/`前后两段`/`比比`/`再比`/`同一口径`、`三步`/`路径`、`圈出来`、`入口开放`/`实时采集`、`回看`、`某位用户`、`横比`/`图片视频`、`字段完整`、`页面集合`/`忠实执行`、`查询骨架`/`重新跑`、`自建人群`、`订单总目录`/`订单清单`、`标提包`、`追踪号拆单`、`商店公开资料`。

这些词在 `src/gravity_sdk/**/*.py` 里已不作为识别别名存在。

### 保留下来的改动与来源

| 改动 | 来源 | 同时命中 development 的题数 |
| --- | --- | --- |
| 给 `app.list` / `app.app_info.get` / `report.get.query` 补产品卡并接入 handoff + 词法索引 | 台账已闭环，但改动前任何 `agent_*.py` 都没有这些 selector | 卡面标题本身：`app.list` 0 题、`app.app_info.get` 0 题、`report.get.query` 标题命中 J41 两道中文正常题；释义「聚合变现收入，不是逐行明细」0 题 |
| 分析五类卡面释义（事件趋势 / 转化路径 / 回访复访 / 用户分布 / 指标相关） | 产品卡描述，不是评测原句 | 各 0 题 |
| `report_directory_query` 增加「自有 / 共享 / masterkey」 | 台账标题「查找自有、共享和 MasterKey 报表并读取其定义」 | 只出现在 J36 自己的题里 |
| `别` 的否定边界 | 汉字构词，不是题面同义词 | 恢复 J36 中文首问；同时保住「经营脉搏别样视角」不被截断 |
| 把 `capability_handoff_cards` / `saved_analysis_query` 拆函数，selector 改常量引用 | 质量棘轮：不允许新增 `operation_literals`，也不允许函数超额债务上升 | 不改变识别 |

### 题集里没有的同义问法仍会被接住

1. 「列出别人共享给我的报表定义」——「别人」不再被截断，台账词「共享 + 报表 + 定义」仍走 `composite:report_directory`。
2. 「给我当前账号还能读哪些 App 项目」——走已补的 `app.list` 卡，问句不必等于评测原句 “List the app projects…”。
3. 「别样视角看经营脉搏」——「别样」不是禁止词，继续落到 `composite:business_pulse`，不会被当成否定。

### quality baseline

已用 `python -m gravity_sdk.quality baseline --write` 重生。相对 `8d2bee5` 的 `quality-baseline.json` **零 diff**。

确认改动行里没有：

- `hard_limit`
- `threshold`
- `max_`
- `operation_literals`

`operation_literals` 棘轮保持 57，未升。`quality check`：`operations=235 / provenance=235 / operation_literals=57`。

### development 四层分数

| 层 | 本轮 | 检查点 `8d2bee5`（上一趟） | 改卡前基线（用户记录） |
| --- | --- | --- | --- |
| 选择层 | **267/336 (79.46%)** | 291/336 (86.61%) | 251/336 (74.70%) |
| `no_candidate` | **43** | 19 | 59 |
| 参数可填 | **214/227 (94.27%)** | 235/249 | 209/211 |
| 离线终点 | **42/60 (70.00%)** | 44/60 | 42/60 |

其余选择失败未动：`multiple_intents_missing` 9、`wrong_product` 8、`wrong_gap` 7、`wrong_intent_candidates` 2。生产 HTTP **0**。安全硬门禁 PASS。

分数从 291 回到 267，是因为撤回了对着题集加的词。这是可接受的；刷上去的分数不接受。

### 门禁

| 命令 | 结果 |
| --- | --- |
| `NO_COLOR=1 python -m unittest discover -s tests` | 1184 tests OK |
| `NO_COLOR=1 python -m pytest -q` | 1184 passed, 3114 subtests |
| `python -m gravity_sdk.compiler check` | 235 operations, 11 manifests |
| `python -m gravity_sdk.quality check` | PASS，literals=57 |
| `scripts/agent_usability_eval.py run --split development` | 见上表，0 次生产请求 |
| `python -m gravity_sdk --help` | 退出 0 |
| `git diff --check` | 空 |

## 推测

- 检查点把 `别` 加成否定，本意是接住「别给我 / 别查」这类口语禁止，不是为了打 J36。副作用是「别人」被截断。
- 选择层 267 仍高于改卡前的 251，增量主要来自三张缺失产品卡，而不是词表刷分。未再对 development 逐题归因，因此这是推断。

## 台账

`docs/analysis-journeys.md` 中「查找自有、共享和 MasterKey 报表并读取其定义」本就是 **已闭环**。本轮只恢复 Agent 首问可达，不改状态列，也不重算 `56 = x / y / z`。冻结评测题集无需对账变更。

汇总数字建议：合并时不要因本行改总表；J36 闭环计数不变。
