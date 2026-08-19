# 弃权时给出有界可答问法

- 日期：2026-08-19
- 任务：#229
- 结论：`NO_CANDIDATE` 信封现在带 8 条从已登记产品卡机械导出的可答问法 / `catalog_ref`；`next.argv` 仍指向 `gravity agent-catalog categories`。具名 gap 与 `UNRANKED_OPERATIONS` 不加该字段。development 识别器选择层仍 277/336，因为 scorer 不读 `answerable`。

生产读 **0** 次。未读 holdout / final / `.local/agent-usability/*.key` / `*.sealed.json`。未改评测装置、题集、评分、层定义、阈值。未改 `DEFAULT_ROUTING_MODE`、`client.py`、产品卡 `boundaries`、宿主选择臂、Plan 面。

## 发了什么请求、拿到什么响应

全部离线，`PYTHONPATH=src`。

| 请求 | 响应要点 |
| --- | --- |
| development 336 题 × 1 trial `capabilities_many` + `route_score` | 识别器选择层 **277/336**；失败构成 `no_candidate 41` / `wrong_product 5` / `multiple_intents_missing 4` / `wrong_intent_candidates 5` / `wrong_gap 4` |
| 41 道 `no_candidate` 信封 `capability_gaps[].code` | **36** 条 `NO_CANDIDATE`；**2** 条 `UNRANKED_OPERATIONS`（J11/J12 first-turn，评测仍记 `no_candidate`）；**3** 条无 `code` 的产品边界 gap（J14/J16/J17 negated） |
| 41 道题的 `expected.gap_code` | 41/41 为 `None`：评测期待一张产品卡，不是登记缺口 |
| 41 道问法与已登记 `caller_language` 子串 | **0** 条命中。`prompt_chars ≤ 16` 也是 **0** |
| `canonical_capability_cards()` | 96 张卡全部 `executable=True`；其中非 mutation 54 张，带 caller language 的读产品 44 张，覆盖 8 个 domain |
| `discover_capabilities("utterly unrelated quantum weather")` | `code=NO_CANDIDATE`；顶层与 gap 均有 `answerable` 8 条；`next.argv=["gravity","agent-catalog","categories"]` |
| `discover_capabilities("导出分析结果")` | 仍是 `ANALYSIS_EXPORT_FILE_CONTRACT_MISSING`；信封与 gap 都**没有** `answerable`；`next.argv` 仍是 `export list-capabilities` |
| `discover_capabilities("排那位用户当天的时间线和回传")` | 仍是 `UNRANKED_OPERATIONS`；无 `answerable`；`next.argv` 仍是 `agent-catalog host` |

改后 8 条可答项（按 domain 字母序取该域第一条带 caller language 的可执行非 mutation 卡）：

| domain | catalog_ref | query（caller language 第一条） |
| --- | --- | --- |
| analysis | `analysis.query.spec` | 用同一分析定义比较两个时期 |
| app | `app.app_info.get` | 查看 App 的 OneLink 与公开信息绑定 |
| attribution | `composite:attribution_performance` | 查询归因表现聚合 |
| export | `export.material.report.start` | 创建、轮询并下载素材分析报表 |
| material | `composite:material_performance` | 比较已支持平台的素材表现 |
| metadata | `metadata:search` | 离线查找可用于分析的事件、属性、指标和模板名称 |
| promotion | `composite:advertiser_profile` | 读取巨量广告主消耗、余额、预算模式和状态 |
| report | `composite:business_pulse` | 汇总多个 App 的业务趋势和小时脉搏 |

每条另带 `next.argv=["gravity","agent-catalog","describe", catalog_ref]`。

## 1. 41 道 `no_candidate` 问的是什么

**确凿：** 这 41 道全部是「产品存在、问法没命中识别器」，不是「能力没有」。

| 类 | 题数 | 证据 |
| --- | ---: | --- |
| 口语省略 | 11 | family=`colloquial_ellipsis`；目标 journey 都有已闭环产品 |
| 间接业务目标 | 10 | family=`indirect_business_goal` |
| 首轮缺槽 / 指代 | 9 | family=`first_turn_followup`；其中 2 道实际是 `UNRANKED_OPERATIONS` |
| 否定 / 反向切完 | 7 | family=`negated_or_reverse`；其中 3 道是产品边界 gap（无 `code`） |
| 错字 / 拼音 | 3 | 「标提包/成夲」「归音」「引佣/视屏」 |
| 目标 gap 问法没命中 | 1 | J40 `target_gap`：商店公开资料问法，产品是 `app.app_info.get`，问法没命中词表 |

问法太短不是主因（最短 23 字）。用了词表没有的说法、或否定切完后剩下的词不够，才落到弃权。**没有任何一道是「问的是被登记 gap 挡住的能力」**：那类题走 `target_gap` / `wrong_gap`，不在这 41 里。

因此「可答问题」不该试图猜这 41 道各自想要哪张卡——对着题集加词已经撤过。该给的是**系统确实答得了的、跨领域的登记问法**，让调用方改口或改走宿主臂，而不是去逛 10 个领域再编一个邻近产品。

## 2. 弃权信封里的「我能答什么」

挂在 `find.capability_gaps` 造出的 `NO_CANDIDATE` 上，再由 `discovery_next_fields` 抄到信封顶层。

硬约束对照：

| 约束 | 做法 |
| --- | --- |
| 不对着题集加词 | 问法只取 `caller_language_fields(selector)[0]`，来源是 `docs/analysis-journeys.md` / `docs/agent-workflow.md` 已登记标题 |
| 不切默认路由 | 未碰 `DEFAULT_ROUTING_MODE` |
| 有界 | 上限 `ANSWERABLE_LIMIT=8`：每个有 caller language 的读领域恰好 1 条。8 个领域全覆盖，不是 96 张卡，也不是逛 10 个 categories |
| 不许假装能答 | 过滤：必须 `executable`、`effect != mutation`、selector 不以 `gap:` 开头、必须已有 caller language。draft / 登记 gap / mutation 进不来 |
| 能力只加不减 | `next.argv` 仍是 `["gravity","agent-catalog","categories"]`；具名 gap 的 argv 仍跟 gap 自己走（#216） |

`UNRANKED_OPERATIONS` 与无 `code` 的产品边界 gap **不加** `answerable`：前者已经指向 host 臂，后者已经确认「不要去找替代」。

## 3. 评测哪一层会读到

| 层 | 读什么 | 本趟字段会不会进分 |
| --- | --- | --- |
| 识别器选择层 `route_score` | `candidates` 是否非空、首卡是否匹配 `route_key`；空候选时看有没有 `MULTIPLE_INTENTS`，否则记 `no_candidate`。目标 gap 题只比 `gap.code` | **不读** `answerable` |
| 参数层 `parameter_score` | 选中卡的 `required_inputs` / template | 空候选到不了这一层 |
| 终端层 `terminal_score` | 目标 gap 的 `code` 是否出现、`next_action` 是否非空、是否离线 | 41 道都不是目标 gap 题；`next_action` 仍非空 |
| 宿主合同上限 | 按 `journey-targets` 写选择结构再 `resolve_host_product_selection` | 不读识别器信封上的 `answerable` |

所以：**分数不会动，因为选择层 / 宿主合同上限都不读 `answerable`。** 这不是「没退化」的同义反复，是评测装置根本看不到这个字段。#226 改 `boundaries` 是同一原因。

实测：识别器选择层 **277/336 (82.44%)**，失败构成与 #218 / #226 相同。宿主合同上限脚本 **334/336**，仍只败 J32 / J47 的冻结 scorer `wrong_intent_candidates`。参数层 225/238、终端层 44/53、安全门禁 PASS、生产 HTTP 0。不跑 holdout / final。

## 4. 测试红→绿

| 测试 | 红 | 绿 |
| --- | --- | --- |
| `test_no_candidate_envelope_lists_answerable_asks` | `ImportError: cannot import name 'ANSWERABLE_LIMIT'` | `Ran 13 tests … OK` |
| `test_answerable_asks_are_executable_registered_products` | 同上 | 同上 |
| `test_answerable_asks_are_bounded_and_one_per_domain` | 同上 | 同上 |
| `test_named_gap_envelope_does_not_list_answerable` | 同上 | 同上 |

#216 具名 gap / UNRANKED / 有候选的既有测试仍绿。

unittest discover：`Ran 1293 tests … OK`（基线 1289 + 本趟 4）。pytest：`1293 passed`。本机未设 `NO_COLOR` 时 3 条 `--help` 会被 argparse ANSI 绊住，与本趟文件无关；`NO_COLOR=1` 后绿。

## 质量门禁

`PASS … operation_literals=36 (ratcheted)`。未改 `quality-baseline.json`，无 `hard_limit` / `threshold` / `max_` 变动。`client.py` 未碰。错误审计数字未变，C 仍为 0。`find.py` SLOC 458 / 500；`capability_gaps` 50 / 80。

## 推测（与事实分开）

- 调用方若按 `answerable` 改口成那 8 条登记问法，识别器会选中对应产品；本趟没有改问法、没有对着 41 道补词，所以 41 道仍是 `no_candidate`。
- 8 条按 domain 字母序取第一条，所以 analysis 给的是时期对比而不是事件趋势。这是机械序，不是「最常被问」。若以后要换代表产品，应改排序键，不要手写名单。
- 8 条按 domain 字母序取第一条，所以 analysis 给的是时期对比而不是事件趋势。这是机械序，不是「最常被问」。若以后要换代表产品，应改排序键，不要手写名单。

## 没做

- 不对着题集加词，不切默认路由，不改评测 / 题集 / 层定义。
- 不把 96 张卡或 draft / gap 列进「我能答」。
- 不动 `docs/roadmap.md`。不 push、不碰 GitHub。
