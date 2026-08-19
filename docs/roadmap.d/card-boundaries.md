# 产品卡边界改成 owner 字段

- 日期：2026-08-19
- 任务：#226
- 结论：host 目录的 `boundaries` 现在只投影卡上显式声明的字段；缺字段、空字段、mutation 丢掉授权边界、或 host 投影被改，加载即红。不再从 `description` 按标点切句。

生产读 **0** 次。未读 holdout / final / `.local/agent-usability/*.key` / `*.sealed.json`。未改评测装置、题集、评分、层定义、阈值。未改 `client.py`。

## 发了什么请求、拿到什么响应

全部离线，`PYTHONPATH=src`。

| 请求 | 响应要点 |
| --- | --- |
| `canonical_capability_cards()` | 96 张产品卡；改前 **0** 张有 `boundaries` 字段 |
| `registered_unavailable_gaps()` | 6 条 gap；host 合计 102 |
| 改前 `_boundaries(description)` | 121 条正则切句；23 张卡切出 0 条，落入通用句或 mutation 授权句 |
| `host_product_catalog()` 改后 | 102 entries；每张产品卡 `boundaries` = owner 字段；gap 仍是固定「不可执行、勿邻接替换」 |
| 故意去掉 `composite:analysis_context` 的 `boundaries` | `RuntimeError: canonical product card ... must declare non-empty boundaries` |
| 故意把 host 投影的 `boundaries` 改成通用句 | `RuntimeError: host product catalog owner projection drift` |

## 1. 改前这份投影有多准

口径：一条「边界」= 告诉调用方**这张卡不能做什么 / 不要用于什么**的句子。权限提示、动作摘要里碰巧含「不/只」的词，不算边界。

96 张产品卡、121 条正则切句。

| 汇总 | 数 |
| ---: | ---: |
| 卡 | 96 |
| 正则切出 | 121 |
| 误报 | 10 |
| 漏报卡 | 24（23 张切出 0 条 + 1 张切出了别的、漏了真限制） |
| 通用回退句 | 21 |
| mutation 机械授权句 | 42 |

### 误报（marker 命中，但那句话不是产品边界）

| 卡 | 切出 | 误报 | 漏报 | 例子 |
| --- | ---: | ---: | ---: | --- |
| `composite:monetization_detail` | 2 | 2 | 1 | 「空结果与权限裁剪空集不可区分」「若不确定权限…」不是邻接产品边界；真限制「带字段/筛选/分组交给 raw」被逗号粘在长句里没切出 |
| `composite:segment_snapshot` | 3 | 2 | 0 | 同上两条权限提示；「不读取成员或规则定义」是真边界 |
| `composite:report_directory` | 2 | 2 | 0 | 两条都是权限提示 |
| `composite:report_subscriptions` | 2 | 2 | 0 | 同上 |
| `kanban.mutation:dashboard.copy` | 3 | 1 | 0 | 「复制不含报表关联的看板」是动作摘要，「不含」撞上「不」 |
| `kanban.mutation:dashboard.notes.replace` | 3 | 1 | 0 | 「note-only」的 `only` 命中英文 marker |
| `custom_metric.delete` | 1 | 1 | 0 | 「删除后证明指标 ID 已不存在」是验收步骤，不是「不要用于」 |

漏斗卡 `analysis.query.spec:funnel` 切出「（不返回转化率」——括号被 `；;。` 切开，句子残缺。这不算误报（意思对），但证明标点切分会把真边界切坏。

### 漏报（描述里有限制，或产品本该声明邻接边界，但切出 0 条）

23 张卡正则切出 0 条。其中 mutation `custom_metric.create/update` 靠机械授权句顶着；其余 21 张落入通用句
「Use only for this exact returned object or action…」。

确凿有限制、但没有 marker 词或没有句号的例子：

| 卡 | 描述里实际写了什么 | 切出 |
| --- | --- | ---: |
| `composite:realtime_event_catalog` | 「只返回第一页；默认 event_type=profile」——限制在同一句里，没有「不」 | 0 |
| `composite:segment_members` | 与 snapshot 互斥（不读详情/历史/单日结果），描述没写「不」 | 0 |
| `export.analysis.*.start`（8 张） | 七个子类输入不可互换；描述只写「创建、轮询并原子下载…」 | 0 |
| `composite:analysis_context` / `app_snapshot` | 与对方互斥，描述没写「不用于」 | 0 |
| `composite:user_journey` / `custom_audience` / `company_usage` / `title_package` / `business_pulse` | 邻接产品存在，描述是纯能力句 | 0 |

### 逐卡表（96 行，cut / 误报 / 漏报）

完整机器表在本趟工作区 `tmp/boundary-classify.txt`。按家族：

| 家族 | 卡数 | 切出 | 误报 | 漏报卡 |
| --- | ---: | ---: | ---: | ---: |
| composite 读 | 31 | 多数 1–3 | 8 | 11 |
| analysis.query.spec 及其 kind | 6 | 1–2 | 0 | 0（漏斗被切残） |
| mutation（segment/kanban/report/template/saved/realtime） | 39 | 2–3 | 2 | 0（授权句兜底） |
| custom_metric | 4 | 0 或 1 | 1 | 3 |
| export | 8 | 0 | 0 | 8 |
| 其余 operation/metadata | 8 | 0–1 | 0 | 2 |

## 2. 选了哪条迁移

**硬迁移：缺 `boundaries` 的卡加载即红。** 不回退到正则。

为什么：这条字段是宿主臂选路吃的边界。正则回退等于「改描述丢边界仍然静默」，本趟要关掉的就是这个口。96 张卡本轮全部填完，没有「剩下没字段的卡」。

另一条（继续正则回退）的代价：有人把限制写成逗号句或不带 marker 的句子，边界继续消失，测试继续绿。那是现状，不是迁移。

### 哪些能机械导出、哪些必须人写

| 来源 | 张数 | 怎么来 |
| --- | ---: | --- |
| mutation 授权句（合同已有 `effect=mutation`） | 42 | 机械：每张 mutation 卡必须含固定授权边界 |
| 描述里已经写清的邻接限制 | ~40 | 人把那句从描述**抄进** `boundaries`，不再靠切分 |
| 描述没写、但产品矩阵已证明互斥 | ~20 | 必须人写（导出七子类、snapshot vs members、analysis_context vs app_snapshot、漏斗不返率） |

本轮 96/96 都有非空 owner 字段。gap 6 条仍用固定「不可执行、勿邻接替换」，不从 reason 切句。

## 3. 删了 / 改描述导致边界消失，什么会红

结构性检查，不逐卡断言句子原文（除 5 条邻接产品抽样，用来证明投影没把字段丢掉）。

| 开口 | 什么红 |
| --- | --- |
| 某张卡定义删掉 `boundaries`，或写成 `()` | `canonical_capability_cards()` / `composite_capability_inventory()` / `host_product_catalog()` 加载 `RuntimeError: must declare non-empty boundaries` |
| mutation 卡丢掉授权边界 | `must keep the mutation authorization boundary` |
| host 投影把 `boundaries` 改成别的 | `host product catalog owner projection drift` |
| 只改 `description`、不动 `boundaries` | **不红**——这是正确行为：边界不再跟散文走 |

测试：`tests/test_agent_card_boundaries.py`。

红→绿：

| 测试 | 红 | 绿 |
| --- | --- | --- |
| `test_every_canonical_product_card_declares_non_empty_boundaries` | `composite:analysis_context` 加载即 `must declare non-empty boundaries` | 96 张卡均有非空 owner 字段 |
| `test_missing_or_empty_owner_boundaries_fail_closed` | 同上（setUpClass 先炸） | 缺字段 / 空元组 / 空白串三条均 raise |
| `test_forged_or_deleted_host_boundaries_are_projection_drift` | setUpClass 炸，投影校验未跑到 | 改投影 `boundaries` 报 `owner projection drift` |
| `test_composite_inventory_rejects_a_card_without_boundaries` | 同上 | 补丁掉 inventory 第一条的字段即红 |
| `test_mutation_cards_keep_the_authorization_boundary` | 同上 | 42 张 mutation 均含授权句；去掉即红 |

## 4. 评测（development only）

基线（#218）：识别器选择层 **277/336**；宿主合同上限 **334/336**。

本趟改的是 host 投影文案，不改识别器词表、不改 scorer、不改 `journey-targets`。宿主合同上限走的是注册身份重放，不读 `boundaries` 做选择；识别器走词法，`boundaries` 不进 lexical 文档。两层都不掉。

| 臂 | 改前（#218） | 改后 |
| --- | ---: | ---: |
| 识别器选择层 | 277/336（82.44%） | **277/336（82.44%）** |
| 宿主合同上限 | 334/336（99.40%） | **334/336（99.40%）** |

识别器失败构成仍是 `no_candidate 41` / `wrong_product 5` / `multiple_intents_missing 4` / `wrong_intent_candidates 5` / `wrong_gap 4`。宿主上限仍只败 J32 / J47 的冻结 scorer `wrong_intent_candidates`。生产 HTTP 0。不跑 holdout / final。

## 推测 / 确凿

确凿：改前 96 张卡 0 个 `boundaries` 字段；121 条切句中 10 条误报、24 张漏报；改后加载路径 fail-closed；正则 `_BOUNDARY_MARKERS` / `_boundaries()` 已删除。

推测：盲选宿主模型（不是合同上限）可能因为邻接限制写得更清楚而少选错产品；本趟不跑模型、不跑 holdout，这个没测。

## 没做

- 不碰凭据 / 运行时 / 缓存 / `client.py` / 响应投影不变量 / 错误 `actual` / `docs/agent-skills/` / Plan 面。
- 不改评测、不跑 holdout/final、不打生产。
- 不动 `docs/roadmap.md`。不 push、不碰 GitHub。
