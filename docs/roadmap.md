# 路线图

本页是当前开发的唯一权威排期依据，取代历史上不进版本控制的临时目标文件。
盘点快照：`dev@8fd278e`，2026-08-13。

## 目标

**数据分析的任何工作都能完全脱离引力 Web 平台，只用本仓库完成，并且对 Agent 友好。**

衡量单位是**分析动线**，不是 operation 数量。一条动线闭环 = 已知输入 1 次调用、未知 2 次调用完成，
且 CLI+SDK+Plan+Agent card 四面可达，结果是带 `schema_version` 的 envelope
（空/部分失败/能力缺口可区分），未登记字段 fail-closed。

## 现状

当前从仓库产品入口反推 42 条产品动线：**已闭环 18 / 部分闭环 9 / 完全缺失 15**；
另有 2 条 legacy/SDK 便利面保留用于兼容与维护，但不计产品动线。
逐条状态、四面入口、调用次数和证据阻塞以[分析动线台账](analysis-journeys.md)为准；旧
`21/14/6` 快照的逐条底稿未进入版本控制，无法复算，已停止作为排期事实。

`draft` 候选数量不等于排期数量：17 项候选归并进台账动线或按明确非目标排除，不按 operation 单独排期。
9 条 `export.analysis.*` 已判定结案（见[能力覆盖与缺口](capability-coverage.md)）：台账仍如实记为
完全缺失，但属于隐私/合同边界，不作为工程排期缺口。

## 优先级

| 序 | 动线 | 为什么排这里 | 阻塞 |
| --- | --- | --- | --- |
| 1 | **D22 看板页面条件忠实重放** | 已对非空 `data.object.config.filter` fail closed；空条件不受影响 | **合并发生在服务端，前端分析已穷尽**（见下） |
| 2 | **D35 归因表现聚合** | 当前只能读归因配置，无法回答归因结果；且是 F40 的前置 | **前端 body 已恢复，缺服务端证据**（见下） |
| 3 | **D34 非 Bytedance 计划/组/创意下钻** | 跨平台产品多数只到顶层 | D32/D33 已证明当前账号的七个平台父链均无可下钻样本 |
| 4 | **D32 平台专属素材/创意深查** | 最小取证已完成，未取得可升级的非空合同 | 当前账号无非空 advertiser 父候选；保持 draft，等待有数据租户 |

完整动线的逐条判定与最小证据要求见[分析动线台账](analysis-journeys.md)；本页只维护排期与约束。

### 分析结果落盘统一裁决（2026-08-14）

**只统一 JSON 落盘，不统一 `--format`，不新增 CSV/表格。** `analysis query`（含 compact batch
与显式多 App 扇出）、`reports pulse`、`sql query` 补 `--output`；写入完整既有 envelope，不改变
结果内容。它们与已有产品共用一个原子结果写入原语和同形 `written` 收据。纯 `error` 或
`capability_gap` 不创建也不替换目标文件；`partial` 写入完整 envelope，同时保留原非零退出码。
理由是 partial 中独立成功组件仍可消费，且 envelope 已明确记录失败组件；拒绝写入反而会丢掉
不可无代价重取的成功结果。终止失败则没有可消费结果，覆盖旧文件会把一次失败伪装成新 artifact。

格式判据不是“有没有 rows 字段”，而是**公开结果合同本身是否是无损二维记录集**。Analysis、Pulse
和 SQL product 的公开合同都包含状态、错误/partial、分页或 Evidence/查询收据；SQL 内部 rows
即使二维，公开结果仍不是裸表。把这些 envelope 输出 CSV 必须丢字段或自创映射，所以不提供。
NDJSON 只保留在已有明确逐记录编码合同的入口；本轮不把它扩到 composite。若以后有公开合同天然
就是同构标量行数组，且所有状态与收据都有无损、版本化的独立承载，才可单独评估 CSV；不得为嵌套
结果定义通用拍平规则。xlsx 仍只走治理导出 effect。

D32 本轮先估 22 次、实际只发 5 次最小 stable 根读取；5 次均为 HTTP 200 空样本。复用 D33
的 Bilibili/Huya 3 次证据后，七个平台中只有 Bilibili account 曾非空，但其 advertiser 为空；
其余六个平台在允许的根读取或最短单日 advertiser 窗口内均为空。没有权限失败、合同漂移、重试、
翻页、扩窗或 App 切换，因而没有 draft 取得非空响应、父依赖和目标权限六项闭环，stable 数不变。

**D32/D34 是数据阻塞，不是工程阻塞。** 七个平台的父链全断在 account 或 advertiser，
且**无一是权限不足**——当前账号下就是没有非 Bytedance 的投放数据。这意味着再投入工程量
也推不动，两条动线不应继续占用排期位。**不要重复探测**：已知为空的路径再探一次只是消耗
上游请求。解锁条件是外部的——拿到有非 Bytedance 投放数据的租户，或由调用方提供该平台样本。
在那之前，188 个推广/素材 draft 保持 draft 是正确状态，不是欠账。

## D22 合并语义：证明不了，且前端这条路已穷尽

`Dashboard-DrzT0Orh.js`（SHA-256 `6fc533…016`）证明：**页面条件以顶层 `dashboard_condition` 发送，
图表条件仍在 `global_conditions` / `global_cond_logic`，共享 HTTP wrapper 原样传递两者**——
**合并发生在服务端**。这意味着继续做前端 bundle 分析不会有答案，那条路已经走到头。

已观察到的请求**同时兼容四种候选规则**（AND 叠加 / 页面覆盖 / 图表覆盖 / 同维替换加异维叠加），
一个都排除不掉。只能确定两件事：页面条件为空时图表条件原样保留；两者都为空时无冲突。
**这两点只证明请求形状，不证明服务端求值。**

artifact 路径也走不通：当前账号 7 个 App 里 6 个的合法 Dashboard tree 无可选看板，
另 1 个响应 `contract_changed`；本地 artifact 与 receipt 均无双条件实例。

**解锁只有两条路**（都不是工程量问题）：拿到服务端合同；或有一个自然存在的、
同时带页面条件与图表条件的看板，用只读请求分别取得异维度组合与同维度冲突的权威结果。
在那之前保持对非空页面条件 fail-closed 是正确的——猜错会让调用方拿到
"看起来对但其实错"的数据，比报错更糟。

**顺带修掉的不一致**：`dashboard_conditions.py` 曾把 `UNSUPPORTED`（local）硬编码为
`exit_code=2`，与错误分类对齐后的 local→4 冲突，测试也固化了 2。该产品落在错误分类合并之前，
是并行开发的遗留。现已改为调用共享的 `exit_code_for_error`，不再硬编码。

## 并行与串行约束

**共享 spine（S）**：`plan_adapters.py`、`agent_capabilities.py`、`agent_composite.py`、
`agent_handoff.py`、`cli.py`、`__main__.py`。九条已交付产品线**全部**修改过前四个。

- **所有触碰 S 的最终接线必须串行**，由一个集成人顺序合并。领域 core、合同研究、证据取证可任意并行。
- 同一领域的 `compiler` / provenance / coverage 生成物必须串行再生成。
- 已知依赖链：`D22 → D23`、`D29 → D30`、`D27 → D28`、`D33 → D34`、`D35 → F40`。

## 两条曾经贴脸的硬约束（已解除，规则保留）

1. **`plan_adapters.py` 已从 491 降到 456 SLOC**，余量 44 行，`_execute_composite` 不再是该文件
   最大函数。解除方式是把固定来源 composite 下沉到窄领域 family router（照 `plan_order_adapter.py`）。
   **这条路径仍是唯一批准的接法**：新增 Plan composite 走 family router，中央文件净增长 ≤ 0，
   不引入全局 adapter registry 或插件机制。余量变宽不等于可以回去直接加分支。
2. **Agent 意图冲突已收口到 `agent_intent_routing.py`**，五个既有 owner 不再持有他产品负向词。
   新增语义相邻产品的成本**不再随相邻产品数增长**。判据是 selector 精确度 + owner 正向证据基数，
   不枚举产品对；新产品只需声明自己的正向证据。不引入插件、注册表或通用意图 DSL。

## 已知能力净损失

`0.2` SQL 收口的净损失**已部分偿还**（收口提交 `d951d52`）。四类逐一判定：

| 产品 | 判定 | 说明 |
| --- | --- | --- |
| `payment-summary` | **部分恢复** | 聚合 SQL、全部异常计数字段与静态口径已恢复；未恢复 `revenue_yuan` 派生、动态 warning、旧 envelope |
| `first-scene-coverage` | **部分恢复** | 状态、前缀、注册量已恢复；宿主名称映射属调用方语义，覆盖率与动态 warning 未恢复 |
| `event-coverage` | **部分恢复** | 全量与逐事件聚合已恢复；项目事件字典、missing/unknown 对账、新鲜度 warning 未恢复 |
| `profile-coverage` | **不该内置恢复** | 历史 SQL 有成功证据，但 `activity_event` 与画像属性名是业务绑定，属调用方。SDK 不固化这些字段；调用方可按自身契约登记同形 `custom-sql` |

恢复走 workspace recipe 模板（`examples/workspace/sql-capability-recipes.toml`），
**没有重建被删的 builder/summarizer 框架**——那正是收口要去掉的东西。证据是 `0.2` 之前
7 份已发布聚合 Evidence（`2026-07-23`–`2026-08-06`），本轮 0 次上游请求。
同时给 SQL product 增加 `output_semantics`，补上"只有字段名没有字段口径"这一块，
它进入产品目录、Agent 匹配、dry-run 合同与查询摘要，但**不生成动态 warning 或业务判定**。

**仍未偿还的部分**：动态 warning / notes / `partial` 状态、派生比率、声明集合对账。
这些依赖业务字典，按边界属调用方；若将来判定应由 SDK 承担，需要先有不含业务绑定的设计。
历史在线证据截至 `2026-08-06`，此后上游是否漂移未验证，示例 datasource 保持 `pending_review`。

`0.3` Multidim 收口经复核**无取数能力净损失**：raw query/total 仍可经
`gravity run report.multidim.*` 执行，损失的只是旧 CLI/Plan 便利性。

破坏性收口允许直接升级，但**必须先确认没有取数能力净损失**，否则就是在削弱产品目标。

## Agent 可用性欠账

- **"未知 2 次"的承诺不成立，已改为显式声明下界。** 旧记的"8 条"口径有误：把 Dashboard
  control/replay 两张卡并成一行，又把执行后的 stale/parent/diagnostic 重试当成一条正常路径。
  按同一类别口径重算，加上后来新增的分析模板引用路径，实际是 **9 类**。
  **九类全部判定为"显式声明"而非"补齐路径"**——它们都要求调用方精确选择引用、App 或物理字段，
  把目录选择折进执行只会隐式猜值或重复读目录，那比多一次调用更糟。
  下界：未知引用/物理输入 3 次；App 也未知时 4 次；metadata 未同步且 App 未知时最高 5 次。
  声明走 `gravity.agent-call-bound.v1`，四面一致（`gravity agent` candidate、
  `GravitySDK.capabilities()`、`candidate.call_bound`、`plan_node.call_bound`），
  含 `minimum_calls`、`discovery_calls`、`unknown_inputs`、`catalog_status`、`input_sources` 与依赖。
  旧 Plan 不含该字段仍通过，字段不进运行态 `PlanNode`，不改变 request、并发或执行结果。
  Multidim 与 Promotion 的独立目录已用现有 batch 合为一次发现调用，selector 集合与分页数不变。
- 当时 13 张固定 composite 卡（现 15 张）的 7 对意图重叠已收口：集中层按现有 owner 的正向证据强度与 selector
  精确度收集产品，命中多个产品即返回 `MULTIPLE_INTENTS`，不再搜索 raw operation。
  该判据不枚举产品对；显式 `and/以及/同时` 子句独立识别，wrapper 引用与历史紧邻冲突仍 fail closed。
- 错误分类已对齐：permission 返回 upstream/3，本地 unsupported/policy/privacy 阻断返回 local/4；
  operation、请求行为和错误 code 均未改变，没有读能力损失。这是有意的破坏性行为变更——
  调用方需更新 exit-code 分支：`3` 表示换账号或申请权限，`4` 表示请求未发出、停止改输入重试。

## 三处缺面裁决（2026-08-14）

本轮先按调用方任务而非四面数量复核台账中的三处缺面，结论是**均不新增产品面**：

- **素材报表导出不进入 Plan v1，但动线已闭环。** 导出是有文件副作用和恢复状态的 effect；
  `export run` 已在一次顶层调用内拥有 create、poll、download、文件 schema 校验与原子提交，超时后还要
  用 `job_id` 恢复。Agent 卡直接交接该命令并声明发现后 1 次调用。把它包装成普通 Plan 数据节点会让
  Plan 错误承诺可重试、超时和部分文件语义，不能增加调用方可完成的任务。
- **legacy promotion snapshot 不进 Agent/Plan 主路径。** 兼容面允许任意非空 promotion resource、
  逐平台原始 input 和按 inventory 选择首个稳定 operation；CLI 的 all 模式还会按各 operation schema
  静默忽略不适用 shortcut。它没有绑定一个 workspace App、统一日期窗和显式物理指标，也不校验结果
  是否仍绑定这些选择。正式分析调用方使用 `promotion performance`：只覆盖已证明平台，固定 App/
  日期/指标合同，指标在平台 metadata 中 fail closed，并具有 CLI/SDK/Plan/Agent 四面。兼容 SDK/CLI
  保留给已知 operation 合同的专家调用方，不再把它计作独立分析动线。
- **任意 stable metadata snapshot 是 SDK 维护便利面，不是调用方产品。** 它按当前 inventory 的
  metadata 分类动态扩缩，默认跳过所有缺必填 input 的 operation，因而既没有稳定业务问题，也不能
  承诺统一完整性。构造分析所需的在线上下文已有固定 13 来源的 `analysis context` 四面产品；名称发现
  已由同步后的 `metadata search` / `metadata vocabulary` 离线产品覆盖。保留原 SDK 方法和精确 raw
  operation 入口，不为 registry 聚合器新增 CLI/Plan/Agent 面。

这三项只校正产品边界和台账口径；所有既有命令、SDK 方法、operation、envelope、Agent selector 与
意图裁决保持不变，`plan_adapters.py` 未修改。

**"设计不适用"是窄例外，不是逃生舱。** 上面对导出 Plan 面的判定给闭环判据开了口子，
必须钉死使用条件，否则以后每条动线都能声明某个面"不适用"来充闭环：

1. 只有 **effect 类型与该面的执行模型不兼容**才成立（导出有文件副作用与恢复状态，
   Plan 节点是无副作用数据节点）。**"实现麻烦""收益不大""调用方用不到"都不成立。**
2. 必须证明**调用方可完成的任务集合不因缺该面而减少**——导出满足：`export run`
   一次顶层调用即可完成，Agent 卡直接交接该命令并声明发现后 1 次。
3. 判定要写进台账该行（记"设计不适用"而非"无"）并在此处留下理由，可被后来者推翻。

当前只有导出的 Plan 面适用此例外。**新增例外必须同时满足以上三条并在此登记**。

## 使用成本：参数化程度审计结论

### Workspace 参数化 Plan 裁决（2026-08-14）

**判定应做，且只做 Plan 构造机制。** 单 operation recipe 无法表达重复的多节点 DAG；要求分析师
或 Agent 每次只换日期却重新生成完整 Plan JSON，是调用成本而不是业务语义。调用方自行写模板脚本
虽能绕过，但会把类型、路径、Plan schema 与 fail-closed 校验拆到仓库外，无法形成机器合同。

本轮新增 workspace `plan_recipes`：参数显式声明 `type/format/required/bindings[]`，只向 literal
Plan 已存在的 `/nodes/<index>/request/...` scalar 叶子写值。展开后的对象进入唯一 Plan v1
校验/adapter preflight/执行路径；不增加 Plan node kind、adapter、worker、线程池、请求或 envelope。
手写 `plan run --input`、DAG/依赖/foreach、全局 `PlanConcurrencyBudget`、partial 与退出码聚合保持。
缺参、类型/格式错或 workspace 绑定路径不存在均在 adapter 构造/执行前以
`PLAN_RECIPE_INVALID`、local/4 失败；dry-run 零执行、零网络。

机制进入 SDK；具体步骤、业务口径与模板实例继续留在调用项目 workspace。仓库只保留虚构形状示例，
不内置“日常经营检查”等模板。不为 Agent 增加发现卡：workspace 实例是调用方私有内容，Agent
发现面仍只描述仓库能力；已知 recipe 名时，CLI/SDK 的显式参数合同已经可机械填写。

判据是**改一个参数要不要改代码**。20 个真实分析场景实撞（11 次 HTTP，无权限失败与合同漂移）：
零成本 11 / 有成本可接受 4 / 需改代码 5。

其中旧场景 4“同一分析跑多个 App”已按真实使用频率从“有成本可接受”改判为产品缺口并收口。
首批选择事件趋势、漏斗、留存、属性分布四类 compact Analysis：它们都是同一 literal spec 只替换
App，结果天然逐 App 独立。`gravity.analysis-query-batch.v2` 每项把标量 `app` 改为显式非空
`apps` 数组，内部机械展开为现有同层 `analysis_query` Plan 节点；展开后最多 32 个组件，拒绝重复
App（包括 alias/ID 解析到同一 App）和 `"*"`。结果只附 `query_id/app` 身份，不做跨 App
排序、TopN、汇总、差异或比率计算。

首批没有纳入 scatter（跨 App 散点比较频率低）、Multidim（物理 metadata/分页预算模型不同）、
Saved/Dashboard/Template replay（每个 App 还要独立解析引用）、period compare（一个节点已含双窗口）、
分群/订单/变现/推广/素材/SQL（各有引用、单日、平台或调用项目产品合同）。这些保持现有单 App 或
显式同层 Plan 形态，不从本轮结果层外推通用多 App 抽象。

并发没有新线程池或默认值：v2 仍只构造同层 Plan 节点，adapter 每节点固定 `max_workers=1`，
共享 `PlanConcurrencyBudget`。fake transport 实测 3 个 App 在预算 1/3 时请求集合都恰为同三个
App，峰值分别为 1/3；一个 App 权限失败时另外两个继续，外层为 `partial` 且失败组件保留 App。
因此总上游请求量是逐 App 单跑请求集合之和，只提高峰值在途数。v1 `app` 输入和 v1 result 分支
保持原样；既有五类单 App batch 回归继续通过。

**底层参数化总体健康**，不需要通用化改造。日期窗、周月粒度、分组（≤20）、多指标（≤50 步）、
AND/OR 条件、漏斗步数与窗口、留存 `offset`（1–365）、Multidim 常见指标维度都是改参数即可。
留存 D7→D8 零开发，推广平台硬编码是 operation 合同必要绑定，推广指标用开放排除法——
这三处均不计缺陷。

**真实缺口只有一类：字段已在 operation 合同与 FieldPolicy 中登记，compact Spec 却没暴露。**
调用方因此被迫从产品入口掉回手写 raw wire JSON，而该结构不自描述，Agent 无法机械填写。

**已补齐 4 项，2 项证据不足保持关闭：**

| kind | 控制项 | 判定 |
| --- | --- | --- |
| Event | `return_hierarchy` | **已暴露**，在线 probe `success` |
| Retention | `query_item_before_after` | **已暴露**，在线 probe 合法 `empty` |
| Funnel | `window.unit=today`（value 锁死 1） | **已暴露**，在线 probe `success` |
| Scatter | `zone.type=dispersed`（不接受 ranges） | **已暴露**，在线 probe 合法 `empty` |
| Event | `custom_query_item_list` | **不暴露**：artifact 0 实例，最小公式 probe `semantic_error` |
| Event | `split_event` | **不暴露**：通过本地 FieldPolicy 但**上游 `semantic_error`** |

`split_event` 的结果值得单独记：它**通过了我们的 FieldPolicy 却被上游拒绝**，
说明本地策略层在这一处比上游宽。这不是 fail-closed 失效（请求确实发出并被拒），
但意味着"FieldPolicy 接受"不能当作"上游可用"的证据——本轮两项未暴露的判定正基于此。

取证路径记录：artifact 语料**六个字段全部 0 非空实例**（扫 32 个模板，最小 App 看板树为空），
所以"先挖 artifact"这条路本轮没起作用，最终靠最小在线 probe 定的。语料扫描成本 74 次 HTTP，
下次做同类取证要先估成本。

补齐纪律（保留）：取不到生产证据的 fail-closed 不暴露；逐字复用 FieldPolicy 已有结构直接编译；
**不建通用公式 DSL、不接受任意表达式**；新字段必须有默认值且默认行为与现状完全一致
（已用五种 kind 的相同 compact Spec 做结构差分验证，归一化 `query_id` 后 inputs 完全相等）。

Funnel、Property、Scatter 顶层无差集；Property 本身没有日期窗，不算丢参。

**已作废的结论**：审计曾把"Event 双窗口"列为头号缺口，该判定基于 `7d5bdb1`，
早于跨期对比合并。`analysis query --compare-start/--compare-end` 已覆盖，
**不要新增 `date_ranges`**——那会造出第二条语义重叠的路径。上游原生 `date_list`
支持双窗口且 1 次请求即可（本轮在线证实），比现有两次查询+本地 delta 省一次请求，
但这是优化不是缺陷，且 operation 硬上限为 2，三期以上只能客户端拼接。

**三处单日限制均为上游已登记合同限制，不是产品阉割**：`analysis.order_detail.list`（订单目录、
拆单追踪父链）与 `analysis.segment.uid_result.list` 都只有单数 `date`。7 天订单目录的正解是
一个 Plan 放 7 个同层节点并发，不是串行启 7 次 CLI；结果按日期节点分开，不混成一个目录。

**detail 元数据成本已核清**：订单产品提交 `d1983c2` 已对精确固定 profile 短路，D27 的
`ba01a3d` 也让变现固定 allowlist 直接本地校验。最小空日两者实测均为 1 POST、0 metadata，
7 个同层订单节点为 7 POST。缓存仅进程内：raw 动态路径两个独立进程各 4 HTTP；同进程连续
两次为 4+2，7 节点为 16（属性目录各 1、分群 7、订单 7）。raw detail 的动态
fields/conditions/order 仍必须加载实时 metadata，未登记字段继续 fail closed。

**旧审计"3 HTTP"是路径错配，不是未解之谜**（此为推断，原始调用未保存）：`d1983c2` 经核
确在审计基线 `7d5bdb1` 的祖先里，fast path 当时已生效；而审计账本那一行标的是
"Order Detail"，即 `analysis detail --kind order` 这条 **raw 路径**——它按设计就要加载 metadata
校验动态字段。产品路径 `analysis order directory` 用固定 profile，实测 0 metadata。
**教训：度量使用成本时必须写清走的是产品入口还是 raw 入口，两者成本不同是设计，不是缺陷。**

**Multidim 使用成本**：`--start/--end/--time-dim/--metrics/--dimensions/--media/--multi-days`
已覆盖常见变化，无需完整 JSON。仍需手写物理 JSON 的是 `filters[]`、`custom_metrics_list`、
`relate_dims`。**多个扁平 filter 的 AND/OR 组合语义上游未经证明**，产品 schema 无 `filter_logic`；
证明不了就只支持可确定语义的形态，不得假定默认值，更不得为此造通用布尔 DSL。

## D35 归因请求合同：部分证明，仍不能开工

`attribution.attribution.query` 的**前端 builder 已完整恢复**（从与 census 快照哈希匹配的
`Measurement-BV1Ulzee.js` 中的同作用域 builder `Gt`），16 个顶层字段：

`child_type`、`date_list`、`metrics_list`、`dims_list`、`report_level`、`statistics_caliber`、
`decimal_point`、`app_id`、`project_id`、`aggregate_app`、`multi_days`、`dims_metrics_list`、
`filtering`、`need_all_metrics`、`need_cname`、`time_zone`。

省略规则：14 个恒发；`project_id` 仅 truthy 时发；`dims_metrics_list` 仅非空时发，
二者为 `undefined` 时由 `JSON.stringify` 从 wire 省略。`filtering` **恒含 8 个数组**
（`ad_platform_list`、`os_platform_list`、`channel_list`、`version_list`、`operator_list`、
`turbo_promoted_object_id_list`、`aid_list`、`advertiser_id_list`），无值时发 `[]` 而非
`null` 或省略。固定值 `child_type="measurement"`、`need_all_metrics=true`、`need_cname=false`；
源码默认 `report_level="day"`、`aggregate_app=false`、`multi_days=30`、`decimal_point=2`、
`time_zone="utc"`。

**判定：不能开工。** 2 次最小 POST 均 HTTP 200 但分类 `semantic_error`——响应里出现了预期的
`columns/items/static/tips/total` 聚合容器且结果数组为空，同时带 `extra.error`，
因此既不能算成功也不能算明确 empty。**前端形状不等于服务端合同**；此时实现产品等于把未经
服务端证明的形状包装成正式能力，调用方会以为拿到了归因结果。

仍未知：14 个恒发字段中服务端真正必填的是哪些；metrics/dims/口径/时区的允许值域；
8 个筛选数组的元素类型；`project_id` 与 `connect_app_id` 的覆盖规则；semantic error 的成因
（App 能力 / 数据配置 / 字段值约束 / 其他服务端前置）。

**解锁需要**：该页面一次脱敏的成功或明确空网络记录，或一个确知支持该报表的最小测试 App，
或服务端 schema。三者任一即可，都拿不到就保持 fail-closed。

### census 提取器的已知能力边界

那两次未解析 load 卡在 `census/params.py` 的 `_infer_expression`：**无法内联函数调用**
`Gt(...)`，内存形状标为 `unresolved_body_expression`，导致 `body_parameters=[]`。
同 route 另 3 个 occurrence 卡在条件 callee `(e===1?Ie:ze)(...)`，标记
`load_alias_has_no_static_call`。

**杠杆统计已完成，结论是不修。** 同一快照下，条件 alias 影响 97 条 route、123 个 occurrence；
其中 49 条是写、23 条已覆盖、7 条 auth/proxy、1 条 export，只有 17 条未覆盖读。函数调用的
`unresolved_body_expression` 影响 60 条 route、82 个 call site；45 条是写、7 条已覆盖、4 条 export、
3 条 auth/proxy，唯一未覆盖读就是 D35。该 reason 只存在于内存 `_Shape`，序列化后折叠为
`analysis.unresolved_calls` 计数，所以在 `route-params.json` 中 grep 为 0，并非 D35 结论错误。

与台账交叉后，15 条完全缺失、12 条部分闭环中，**当前阻塞根因属于这两类提取失败的均为 0**。
D35 的前端 16 字段已经人工恢复，卡服务端成功/明确空证据；默认值字典已有另一 occurrence 提取出
`app_id`/`subject`，卡服务端必填语义与响应投影。其余相交项是写、已覆盖 route、helper、export，
或另有父链/非空样本/隐私/产品面 blocker。实现函数内联和条件 callee 不会解锁排期动线，故保持
现有静态分析边界，不为潜在未来收益扩张成通用求值器。明细见
`tmp/codex/census-extractor-leverage/stats.md`。

## 并发

已有 28 条并发路径、7 种模型，底层受业务槽 24、SQL 槽 2、host 令牌桶与 429 cooldown 约束。
17 条可增强候选中收益最大的 Promotion Performance（≤21 平台）、Dashboard Analysis（≤32/64 图表）、
Analysis Context（13 来源）已接入 Plan 全局预算租借。

租借接口把 Plan execution 已占的一槽计入可用 worker，额外容量只做非阻塞 try-acquire；同一 execution
嵌套租借复用已持有容量，退出或异常均归还，因此多个 Plan worker 不会等待额外槽而自锁。adapter
不拥有第二个预算，领域 core 继续复用既有 bounded batch。fake transport 在 Plan 预算 6 下记录到：
Promotion 21 请求峰值 `1→6`、Dashboard 32/64 图表总请求分别 35/67 且图表阶段峰值 `1→6`、
Analysis Context 13 请求峰值 `1→6`；串并行请求 identity 完全相同。21 平台中 3 个失败的结果保持
`partial`，18 个成功/空组件与 3 个逐平台错误/能力缺口均保留，Plan 依赖仍把 partial 视为失败。

**约束**：不要给 adapter 增加独立 worker 默认值或私有预算。所有增强保持上游总请求量 `1x`，只提高
峰值在途数。SQL 硬上限 2 有 4 并发实测失败证据，不提高。分页未知总页、父子依赖链、导出
`create→poll→download`、探测链不并发。fake transport 证明预算与语义，不代表生产 24 并发已完成
soak；真实吞吐、尾延迟和 429 频率仍需在发布流程中做受控长时观察。

## 已批准的隐私投影边界：变现明细（D27）

`analysis.monetization_detail.list` 的 identifier-free 投影已批准，边界如下。
这是产品合同的一部分，不是可调参数。

**永久排除，不得通过任何参数、字段选择或 raw 路径打开：**

| 字段 | 排除理由 |
| --- | --- |
| `user_id`、`event_user_id`、`device_id`、`ClientID` | 直接用户/设备标识 |
| `TraceID` | 可将同一用户的多条变现事件串联，构成间接标识 |
| `device_info` **整个嵌套对象** | 硬标识符已 omit，但 `Phone_Brand`+`Phone_Model`+`OS`+`Rom_version`+`Aspect_Ratio` 组合构成设备指纹，足以重识别 |
| `user$ad_count`、`user$ad_avg_ecpm`、`user$ad_ltv` | 绑定到单个用户的画像指标 |
| `Name`、`WXOpenID` | 已在 `known_omitted_item_keys`，保持排除 |

**批准暴露：** `CreateTime`、`AdEventTime`；`AdPlatform`、`AdvertiserID`、`AdAid`、
`TurboPromotedObjectID`；`event$ad_type`、`event$adn_type`、`event$ad_unit_id`、
`event$ad_through`、`event$ad_source_id`、`event$ad_placement_id`；`event$ecpm`、`samount`；
`re_attribute_info` 中的广告维度字段。

**附加约束：** 不提供按用户维度的筛选或分组——那会绕过投影重新定位个人。
`fields` 动态字段继续 fail-closed，未登记字段默认隐藏。

**D27 已闭环。** 复用原 stable operation，新增固定单日、完整分页、request-bound 的
identifier-free envelope，并通过 CLI/SDK/Plan/Agent card 四面交付；本轮 0 次生产请求，operation
仍为 185。产品请求只有 App、单日与安全边界，固定 fields allowlist；结果逐行和嵌套重建，未知上游
字段默认隐藏，永久排除值不进入 data/total/page/error/receipt。Plan 经窄 Analysis family router 接入，
`plan_adapters.py` 净增长 0。Guard 仅放行无冲突的产品意图，用户/设备筛选或分组、动态字段、跨日、
聚合、导出/写入和 raw-like 请求继续本地报 gap。D28 聚合仍需独立账户绑定与合同证据，本轮未实现。

## Agent 入口表的增长处理

`docs/agent-workflow.md` 的入口表已从 34 行按任务类型压到 17 行，文件由 220 行降到 202 行；
Analysis 编译、报表产品、投放/素材表现、订单、分群、保存分析、看板等同类入口共享一行，
现有直接命令、未知能力路径与 1/2/3 次调用边界全部保留。

**已否决的方案**：拆成独立文档（入口表正是 Agent 最需要的机器可读内容，拆出去要多读一个文件）；
提高上限（门禁本意"入口文档要读得快"是对的，提高等于放弃约束）。

**已落地**：入口表按任务类型分组，同类产品共享一行（例如“跨平台投放/素材表现”同时覆盖
material 与 promotion），后续同族能力扩展现有行，不再按产品逐行增长。

更根本的判断：这张表在**补偿发现机制的不足**。`gravity agent` 本应让调用方知道有哪些产品可用，
路由层现已先裁决多产品再决定是否进入 raw fallback；无法唯一判定时返回明确缺口。

## 明确不做

- 不复刻 Web UI 概念：布局、收藏、拖拽、成员权限管理。`app.project_auth.detail` 与
  `app.user_auth.list` 因此排除，不因取得非空样本而进入分析产品。
- 业务语义属调用方：模块名称、活动 ID、SKU、投放窗口、指标好坏判断都不进本仓库。
- 写操作保持 reservation。
- 证据不足保持 fail-closed：不猜请求合同、不扩大探测找非空样本、不用未批准的用户级标识探测。
