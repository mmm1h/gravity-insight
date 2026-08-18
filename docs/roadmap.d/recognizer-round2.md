# 识别器第二轮：否定边界、多意图收集器与封闭类词

- 日期：2026-08-18
- 任务：#recognizer-round2（工作目录 `wt-recognizer-round2`，分支 `grok/recognizer-round2`，基线 `dev@685ec19`）
- 结论：development 选择层从 267/336 到 277/336；`no_candidate` 从 43 降到 39。增量来自「是不是 / 而不是」否定边界、多意图协调词 + 广告主收集器，以及卡面/台账已有的封闭类词。对着题集加的词已撤。

## 确凿事实

本轮 **0 次生产请求**。只读本地代码、冻结 NL 矩阵、quality 门禁和 `development` 离线评测。

### 50 条已闭环动线对账

对照 `docs/analysis-journeys.md` 产品表与 `evals/agent_usability/journey-targets.json`：

| 项 | 结果 |
| --- | --- |
| 台账「已闭环」行 | 50 |
| 其中映射到 J01–J48 | 42 |
| 未进 J01–J48 的已闭环写动线 | 8：看板工作区、保存分析 CRUD、分群创建、语义组合、自定义指标、元数据模板、报表写、订阅写 |
| 评测映射里缺 candidate_selector 的已闭环读动线 | 20（J03–J08、J11–J14、J16–J23、J36–J37）；它们走 `route_key` / composite 名，不是缺卡 |
| 评测映射有 selector 但不在静态 inventory 字面的 | 仅 J33 `export.material.report.start`（导出卡由 export inventory 动态物化，冻结矩阵仍可达） |

8 条 mutation / 语义组合动线**都有** `agent_*.py` 产品卡（`kanban.mutation*`、`saved_analysis.mutation*`、`analysis.segment.mutation*`、`composite:semantic_compose`、`custom_metric.*`、`metadata_template.*`、`report.mutation*`）。它们不在评测 J01–J48，本轮不改台账状态列。

上一趟补的三张卡（`app.list` / `app.app_info.get` / `report.get.query`）仍在。本轮**没有**再发现「已闭环但完全没有 Agent 入口」的读动线。

### 「是不是 / 而不是」截断

与 J36「别人」同类：`_NEGATED_TAIL` 把子串「不是」当禁止词。

实测：

| 问句 | 改前 `affirmative_intent_text` | 改后 |
| --- | --- | --- |
| 「想确认渠道带来的访客是不是一天比一天更常打开登录入口。」 | `想确认渠道带来的访客是` | 整句保留 |
| 「想验证用得越勤的人是不是也花得越多…」 | `想验证用得越勤的人是` | 整句保留 |
| 「创意审查要看各平台独有字段而不是通用目录…」 | `创意审查要看各平台独有字段而` | 整句保留 |
| 「不是看某个 App 的业务量，我要看公司层面的资源消耗随时间怎么变。」 | 仍抽出后半句 | 不变 |
| 「别给我素材报表」 | 空串 | 不变 |
| 「别人共享给我的」 | 整句保留 | 不变 |

修复：禁止词 `不是` 仅在左侧不是「是 / 而」时生效。

### 多意图收集器缺口

`_positive_query_selectors` 漏了 `advertiser_profile`；协调词只有 `and / 以及 / 同时`，吃不到「既要…也要」。

| 改动 | 来源 | development 同时命中 |
| --- | --- | --- |
| 收集器补 `composite:advertiser_profile` | 该卡已有独立 query，其它并列产品早已在收集器里 | J29 多意图 1 题 |
| 协调词补「既要 / 既看 / 也要 / 也看 / 也比较 / 连同 / 和其他」 | 汉语并列连词，不是评测原句 | J25 / J29 多意图；J42 多意图仍未收集归因快照（见下） |

曾把 lineage / asset / export / metadata / attribution_snapshot 一并塞进收集器。冻结矩阵立刻红：J10 中文首问、J14 英文首问、J24 英文首问、J33 中英首问被判成多意图。**已撤回。** 单产品问句里夹带相邻词不能升格成多意图。

### 封闭类词（有来源，非题面）

| 改动 | 来源 | 同时命中 development |
| --- | --- | --- |
| 公司用量接受「配额 / 消耗」而不强制「用量」二字同现 | 卡面「消耗、余额、预算」与公司资源用量产品 | J13 间接目标 + 否定 reframing；「读取公司配额消耗趋势」不在题集 |
| 用户归因明细接受「设备 + 归因 + 回传/明细」 | 卡面 `device_white` / attribution / postback 容器 | J43 两道 |
| 分析默认字典接受「分析 + 字典 + 默认/缺省」 | 卡面标题「分析默认值字典」 | 0 题（「默人值」仍是错字，未救） |
| workspace SQL gap 接受「登记 + 聚合/产品」 | 台账「已审核登记的聚合产品」 | J19 否定 1 题 |
| 实时事件目录 gap 接受「实时 + 上报 + 目录/项/治理」 | 台账「实时事件目录」与治理快照用语 | J35 1 题 |
| 当前 schema gap 在「当前 + 字段/版本 + 表」时也可触发 | 台账「当前 schema、字段和版本」 | J44 typo 1 题；「要当前 schema」原边界题仍无 gap（未退化） |
| 非巨量层级 gap 接受「计划+组+创意」与「查看」 | 台账「计划、组和创意」 | J45 1 题 |
| 平台专属创意 gap 接受「独有」作为「专属」的通用同义 | 行业/产品对照「专属 / 独有字段」 | J46 target-gap 1 题 |

### 对着题集加过、已撤回的词

`隔一天`、`圈出来`、`入口开放`/`实时采集`、`回看`、`某位用户`/`那位用户`、`横比`/`图片视频`、`字段完整`、`页面集合`/`忠实执行`、`查询骨架`、`自建人群`、`订单总目录`、`标提包`、`商店公开资料`、`下下来`、`原图`（只为「引佣/视屏」错字）、`分析文件`、`版本史`/`指定日期总量`、`同一口径`/`前后两段`/`这礼拜`。

这些词在最终 diff 里不存在。

### 题集里没有的同义问法仍会被接住

1. 「这个行为每天发生量是不是在上升？」——「是不是」不再截断，事件分析卡面词「行为 / 每天 / 发生量」仍走 `analysis.query.spec:event`。
2. 「读取公司配额消耗趋势」——不必出现「用量」二字，走 `composite:company_usage`。
3. 「既要巨量广告主账户余额状态也要跨平台推广表现」——「既要 / 也要」拆成两段，收集器给出 `advertiser_profile` + `promotion_performance`。

### 未动（成因未定或一改就回归）

| 类 | 题 | 判定 |
| --- | --- | --- |
| 口语/省略/首轮指代 | J01–J12、J16–J18、J20–J21、J23–J24 多数 no_candidate | 匹配器要的是产品封闭类词；问句里没有。加词只能对着题面，撤 |
| 题面错字 | J30 标提/成夲、J38 煤体、J42 归音、J46 砖属、J48 引佣/视屏、J34 默人值 | 不建错字表 |
| 首轮 follow-up 被 `analysis.task.handoff` 抢走 | J04/J08/J22/J34 wrong_product | 任务交接面本就要接住未结构化分析任务；收紧会伤真任务 |
| 图片视频 vs 推广 | J15 wrong_product | 「投放复盘 + 渠道」被推广识别器合法吃下；加「图片视频」是上一趟已撤的题面词 |
| J25/J27/J28/J33/J47 多意图 | 半句命中或 gap 抢先 | 扩收集器会伤冻结矩阵，未定 |
| J30/J31/J34 多意图候选集不对 | 命中了 MULTIPLE_INTENTS 但 selector 集不是题面那对 | 未定 |
| J44 边界 / target-gap | 「要当前 schema」太短；「此刻字段和版本」被 table_lineage 抢走 | 未定 |
| J40 商店公开资料 | 卡面词是「公开信息 / OneLink」，不是「公开资料」 | 上一趟已撤，保持 |

### quality baseline

相对 `685ec19` 的 `quality-baseline.json` **零 diff**。确认没有：

- `hard_limit`
- `threshold`
- `max_`
- `operation_literals`

`operation_literals` 棘轮保持 57。`quality check`：`operations=236 / provenance=236 / operation_literals=57`。

### development 四层分数

| 层 | 本轮 | 上一趟收尾 `recognizer-recall` |
| --- | --- | --- |
| 选择层 | **277/336 (82.44%)** | 267/336 (79.46%) |
| `no_candidate` | **39** | 43 |
| `target_gap` | **37** | 34 |
| `environment_gap` | **6** | 5 |
| `correct` | **231** | 227 |
| `correct_multiple_intents` | **3** | 1 |
| `multiple_intents_missing` | **6** | 9 |
| `wrong_product` | **7** | 8 |
| `wrong_gap` | **4** | 7 |
| `wrong_intent_candidates` | **3** | 2 |
| 参数可填 | **218/231 (94.37%)** | 214/227 (94.27%) |
| 离线终点 | **49/60 (81.67%)** | 42/60 (70.00%) |

选择层 277 = 231 correct + 3 correct_multiple_intents + 37 target_gap + 6 environment_gap。生产 HTTP **0**。安全硬门禁 PASS。`test_frozen_natural_language_journey_matrix_is_first_call_reachable` 全绿。

### 门禁

| 命令 | 结果 |
| --- | --- |
| `NO_COLOR=1 python -m unittest discover -s tests` | 1192 tests OK |
| `NO_COLOR=1 python -m pytest -q` | 1192 passed, 3121 subtests |
| `python -m gravity_sdk.compiler check` | 236 operations, 11 manifests |
| `python -m gravity_sdk.quality check` | PASS，literals=57 |
| `scripts/agent_usability_eval.py run --split development` | 见上表，0 次生产请求 |
| `python -m gravity_sdk --help` | 退出 0 |
| `git diff --check` | 空 |

## 推测

- 选择层 +10 主要来自否定边界恢复整句（J05/J13/J43 等）和 gap/用量/多意图收集器，而不是词表刷分。未对每道新通过题做词法回退逐项打分，这是推断。
- 宿主臂 333/336 仍远高于 277。剩下 39 个 `no_candidate` 多数是口语省略或首轮指代，离线规则识别器按现有「封闭类词必须出现」政策接不住；扩词会过拟合。
- J32 多意图现在先落到 `CURRENT_TABLE_SCHEMA_PARENT_MISSING`，因为「此刻字段与当前版本」被 schema gap 吃掉。这可能是正确的 fail-closed，也可能是收集器仍缺 lineage。未定。

## 台账

`docs/analysis-journeys.md` 本轮**不改**任何状态列，也不重算 `56 = x / y / z`。冻结评测题集无需对账变更。

汇总数字建议：合并时不要因本文件改总表；已闭环 50 / 部分闭环 3 / 完全缺失 3 不变。
