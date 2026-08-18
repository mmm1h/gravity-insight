# 选择层残余 20 题成因：无可安全修项

- 日期：2026-08-18
- 任务：#selection-residual（工作目录 `wt-selection-residual`，分支 `grok/selection-residual`，基线 `dev@90a7987`）
- 结论：20 个非 `no_candidate` 失败里，0 条属于「识别器错且改了不伤别的」。本轮不改识别器。离线词法臂对剩余 56 题再加规则已不值得投入；宿主臂做主路径，离线臂只保底。

## 确凿事实

本轮 **0 次生产请求**。只读本地代码、冻结 NL 矩阵、`development` 离线评测。未改评测题集、评分逻辑、层定义、阈值、`docs/roadmap.md`、台账状态列或表头汇总。识别器源码 **零 diff**。

### 怎么量的

`PYTHONPATH=src` 调 `capabilities_many` 对 development 336 题各发现一次，用现成 `route_score` 打分。选择层构成与上一轮 `recognizer-round2` **逐项相同**：

| 层 / 失败类 | 本轮 | 相对 round2 |
| --- | ---: | --- |
| 选择层 | **277/336 (82.44%)** | 未变 |
| `correct` | 231 | 未变 |
| `correct_multiple_intents` | 3 | 未变 |
| `target_gap` | 37 | 未变 |
| `environment_gap` | 6 | 未变 |
| `no_candidate` | 39 | 未变 |
| `wrong_product` | 7 | 未变 |
| `multiple_intents_missing` | 6 | 未变 |
| `wrong_gap` | 4 | 未变 |
| `wrong_intent_candidates` | 3 | 未变 |

277 = 231 + 3 + 37 + 6。39 个 `no_candidate` 本轮按授权不刷。下面只拆另外 20 条。

每条都对过：`affirmative_intent_text`、`multiple_product_intents`、`_positive_query_selectors`、`_strict_query_selectors`、各产品 `*_intent`、`unavailable_journey_gap`、实际 `candidates` / `capability_gaps`。

### 20 条归因

#### 识别器错且可安全修：0

没有一条同时满足「产品在目录里、问句够清楚、选错/收集错」和「改了不伤别的」。

候选修补都做了 development 全量碰撞扫描，全部被否：

| 候选 | 会救 | development 新命中 | 为什么撤 |
| --- | --- | ---: | --- |
| 去掉 `_WRAPPER_SELECTORS` 短路 | J25 | 冻结矩阵 J24 英文首问也会升格多意图 | 见下 J25 |
| schema gap 接受「此刻」当「当前」 | J44 target-gap | 只这一题 | 上一轮已标「对着题集」同类；且会加深 J32 被 schema gap 抢走 |
| user_journey 接受「那位用户」 | J11 first-turn | 只这一题 | 上一轮已把「某位用户 / 那位用户」从词表撤回 |
| 推广意图接受「物理指标」 | J27 multiple | 只这一题 | 协调词「既要 / 也比较」只在这一题配对；扩收集器上一轮已伤 J10/J14/J24/J33 |
| 为 默人/煤体/砖属 建错字表 | J34/J38/J46 | 只对应错字题 | 授权明确禁止 |

#### 一改就伤别的：9

| case | 实际选择 | 伤谁 |
| --- | --- | --- |
| J04.dev.v3.first-turn | `analysis.task.handoff` | 任务交接面要接住未结构化分析任务。问句有「按城市看占比」+「下一条」，没有属性分析封闭类词。收紧 handoff 会伤真任务。 |
| J08.dev.v3.first-turn | `analysis.task.handoff` | 「搭分析 / 候选上下文」触发分析任务，不触发 `analysis_context`（该卡要「事件+属性+指标+模板」三类同现）。收紧同上。 |
| J22.dev.v3.colloquial | `analysis.task.handoff` | 「存下来的那份分析」不是卡面词「保存 / 已存」。handoff 因「分析」接住。给「存下来」开同义是题面词。 |
| J15.dev.v3.indirect-goal | `composite:promotion_performance` | 「投放复盘 + 渠道 + 效果」被推广识别器合法吃下。素材卡要「素材」+动作；问句只有「图片和视频」。上一轮已撤「图片视频」。 |
| J25.dev.v3.multiple | 单卡 `segment_snapshot` | 收集器其实已经给出 snapshot+members。`_WRAPPER_SELECTORS` 在 `direct` 含 wrapper 时丢掉 `positive`。拿掉短路：冻结矩阵 J24 英文「Show this segment's details, version history, and aggregate user count for yesterday.」会变成多意图（`segment_members` 因 `user`+`count` 误入）。这是上一轮「扩收集器伤单产品」的同族。 |
| J27.dev.v3.multiple | 弱 operation 列表 | 协调词拆出「各平台推广层级的物理指标」和「图片视频素材效果」。后半句命中素材；前半句 `promotion_performance_intent` 为假——整句被 `_material_specific_query`（含「素材」）挡掉，子句又没有「表现/效果/报表」。加「物理指标」只救这一题。 |
| J28.dev.v3.multiple | 单卡 `bilibili_account_performance` | 「和其他」拆成两段。后段「平台的通用推广汇总」没有「表现/效果/报表」，推广意图为假。把「汇总」当推广动作会扫到其它「汇总」单产品问句。 |
| J30.dev.v3.multiple | `MULTIPLE_INTENTS` 但是 `material_performance`+`title_package` | 收集器没有 export。后段「通用素材报表文件一起下载」被素材卡吃掉，不是 `export.material.report.start`。把 export 塞进收集器：上一轮已证实伤 J10/J14/J24/J33 单产品首问。 |
| J33.dev.v3.multiple | `material.asset.fetch` | 「既…又…」不在协调词表（只有 既要/既看）。整句被素材下载卡吃掉，导出卡要「素材+导出+文件/数据/报表」。加「既…又…」或把 export/asset 塞进收集器，伤单产品导出/下载问句。 |

#### 判据本身模糊：3

| case | 歧义在哪 |
| --- | --- |
| J31.dev.v3.multiple | 期待 `metadata:search` + `analysis.query.spec:event`。实际 `MULTIPLE_INTENTS` 给出 `app_snapshot`+event。前半句「离线找事件和指标名称」不满足 metadata_search（中文要事件/属性/指标/模板里 ≥3 类）。`app_snapshot` 来自非严格 composite 泛匹配「事件」，不是治理快照意图。两个答案都说得通：当「先搜目录再跑事件」，或当「事件分析 + 被误召回的 App 快照」。修 `app_snapshot` 漏匹配是对的，但修完前半句仍进不了 `metadata:search`，候选集还是不对。 |
| J34.dev.v3.multiple | 期待默认字典 + `metadata:search`。实际 `analysis_context`+默认字典。问句「可搜索的事件、属性、指标候选」正是 analysis_context 的三类词，也像 metadata_search，但缺第四类「模板」和「离线/本地」。两个产品都能解释这半句。 |
| J44.dev.zh.boundary | 「要当前 schema，不是已同步的历史沿革。」否定抽取后只剩「要当前 schema」。schema gap 中文要「当前 + schema/字段/版本 + 表」。这是故意写短的边界题：加「表」才够，或承认四字问句不应独吞 gap。 |

#### 期待过时 / 评分合同当前不可达：5

这类**请你改题或改评分，我不动识别器**。

| case | 为什么期待对不上当前目录/协议 |
| --- | --- |
| J32.dev.v3.multiple | 期待 `MULTIPLE_INTENTS` 且候选含 `metadata:table_lineage`（J44 是 gap，没有 selector）。`unavailable_journey_gap` 在收集器之前短路：整句同时命中 lineage 和 `CURRENT_TABLE_SCHEMA_PARENT_MISSING`，发现面只返回 schema gap。这是现协议的 fail-closed：有登记的 unavailable journey 就不出产品卡。评分却要求多意图。**当前识别器+评分合同下这题不可达。** |
| J47.dev.v3.multiple | 期待 `MULTIPLE_INTENTS` 且候选只有 `material.asset.fetch`（J47 是 gap）。实际整句命中 `ANALYSIS_EXPORT_FILE_CONTRACT_MISSING`，导出 gap 同样抢在收集器前。后段「按素材引用下载原始视频」也不满足 asset 卡（要「平台素材/创意引用」+下载+图片/视频）。**当前协议下不可达。** |
| J44.dev.v3.target-gap | 期待 schema gap。实际 `metadata:table_lineage`（「表 + 版本」）。「此刻」不是 gap 词「当前」。产品卡「已同步表版本」对「确认此刻字段和版本」也说得通——F41 当前 schema 在目录里仍是 gap，但问句没有把它和 lineage 切开。 |
| J34.dev.v3.typo | 「默人值」不是「默认值」。handoff 因「分析」接住。不建错字表。若题面改回「默认值」，现识别器会过（`analysis_default_dictionary_query` 已接受「分析+字典+默认」）。 |
| J38.dev.v3.typo / J46.dev.v3.typo | 「煤体」≠「媒体」，「砖属」≠「专属」。否定抽取后 J38 剩下「普通素材表现」，合法进素材卡。不建错字表。改回正字后现 gap 函数会过。 |

J11 / J12 first-turn 也列在这里作对照，但归入「一改就伤 / 口语省略」更准：

- J11：「那位用户 + 时间线 + 回传」缺卡面要求的「某个/这个/指定/单用户」。实际掉进 `app.list` 弱匹配。放宽「那位用户」只救这一题，上一轮已撤。
- J12：「几个应用的整体起伏」不是「经营/业务 + 脉搏/趋势」。实际掉进 `app.detail`。加「起伏」是题面词。

### 39 个 `no_candidate` 构成（本轮不修，只给问题 3 当证据）

| family | 题数 |
| ---: | ---: |
| colloquial_ellipsis | 11 |
| indirect_business_goal | 10 |
| first_turn_followup | 7 |
| negated_or_reverse | 7 |
| typo_or_pinyin | 3 |
| target_gap | 1 |

分布在 J01–J12、J14–J21、J23–J24、J30、J40、J42、J48。问句里没有对应产品的封闭类词。3 个错字题是标提/成夲、归音、引佣/视屏。

### 宿主臂 56 题差距怎么拆

宿主臂 development 是 **333/336**（`routing-arms-paired-holdout.md`，同目录、不切默认）。离线臂 277，差 56。

56 = 本轮量到的 39 `no_candidate` + 20 非 `no_candidate` − 3 道宿主也失败的题。那 3 道宿主失败本轮未拆（上一轮也没拆）；不把它算进「离线再投入还能拿下」。

对这 56 题按「再加词法规则能否拿下」切开：

| 桶 | 约数 | 依据 |
| --- | ---: | --- |
| 词法规则本质上拿不下 | **52–54** | 39 个口语/省略/指代/错字 `no_candidate`；handoff 抢真任务（J04/J08/J22）；产品边界冲突（J15）；wrapper 保单产品（J25）；收集器一扩就伤冻结矩阵（J27/J28/J30/J33）；评分合同不可达（J32/J47）；题面错字（J34/J38/J46） |
| 看起来像识别器错、但修了只救 1 题或伤别的 | **2–4** | J11「那位用户」、J44「此刻」、J27「物理指标」、J31 `app_snapshot` 泛匹配。全量碰撞扫描都是单题命中或冻结矩阵回归 |
| 再投入还能干净拿下 | **0** | 见上表候选修补 |

### quality / 能力

相对 `90a7987` 的识别器与 `quality-baseline.json` **零 diff**。`operation_literals` 棘轮未动。生产 HTTP **0**。

## 推测

- 宿主臂那 3 道 development 失败，更可能也在多意图/gap 合同，而不是口语省略。本轮没有重跑宿主臂，这是推断。
- J32 的 schema-gap 抢先，作为「当前 schema 在目录里仍是 gap」的 fail-closed 是对的；错的是冻结 case 把它和 lineage 绑成多意图。改题比改识别器干净。
- 若以后要动识别器，唯一不靠题面词的结构性债是：`app_snapshot` 不在 `_STRICT_COMPOSITES`，非严格 composite 会把「事件」泛匹配成治理快照。修它可以减少 J31 的错误配对，但补不齐 `metadata:search`，选择层分数不会动。

## 问题 3 的排期判断

**停掉离线识别器的选路刷分。** 两轮已经从 251 接到 277，剩下的不是「词表还差一点」。

替代方向（按优先级）：

1. **离线臂只保底，宿主臂做主路径。** 调用方能产出选择时走宿主（333/336）；离线臂继续挡封闭类词、否定、相邻产品冲突、unavailable gap。不要为了 277→290 再开一轮加词。
2. **改题，不改识别器。** 上面 5 条期待过时/不可达，加上 3 条歧义，交给题集维护者。尤其 J32/J47：当前协议下离线臂不可能给出题面要的 `MULTIPLE_INTENTS`。
3. **不要换一套离线检索来刷这 56 题。** 词法索引上一轮已经试过：`no_candidate` 里多数 top score 非零，阈值会同时制造假失败和假通过。缺的是省略与指代，不是词重叠。
4. **若以后要缩小两臂差距，做宿主臂的 3 道失败，不要做离线臂的 56 道。**

## 台账

`docs/analysis-journeys.md` 本轮**不改**任何状态列，也不重算 `56 = x / y / z`。冻结评测题集无需对账变更。

汇总数字建议：合并时不要因本文件改总表；已闭环 50 / 部分闭环 3 / 完全缺失 3 不变。表头保持 `56 = 50 / 3 / 3`。
