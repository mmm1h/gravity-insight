# Agent 可用性、调用成本与归因合同

- 日期：2026-08-18
- 任务：存量 `docs/roadmap.md` 按主题归档
- 结论：Agent 可用性欠账、1/3 调用成本、缺面裁决、参数化审计、D35/F40 归因合同与并发预算。

正文为原 `docs/roadmap.md` 对应段落的逐字归档，不是新裁决。
文内相对链接按原 `docs/` 根路径理解（本文件在 `docs/roadmap.d/`）。

---

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
- 当时 13 张固定 composite 卡（当前基线为 21 张）的 7 对意图重叠已收口：集中层按现有 owner 的正向证据强度与 selector
  精确度收集产品，命中多个产品即返回 `MULTIPLE_INTENTS`，不再搜索 raw operation。
  该判据不枚举产品对；显式 `and/以及/同时` 子句独立识别，wrapper 引用与历史紧邻冲突仍 fail closed。
- 错误分类已对齐：permission 返回 upstream/3，本地 unsupported/policy/privacy 阻断返回 local/4；
  operation、请求行为和错误 code 均未改变，没有读能力损失。这是有意的破坏性行为变更——
  调用方需更新 exit-code 分支：`3` 表示换账号或申请权限，`4` 表示请求未发出、停止改输入重试。

### Agent 自然语言到答案实测（2026-08-15）

本轮另做了 20 个端到端问题实测（中文 10 / 英文 10），测的是
`gravity agent "<问题>"` 到业务答案、明确空或机器可判定 gap 的整条路径，**不是**下面“改参数要不要
改代码”的 20 场景审计。覆盖事件/漏斗/留存/属性/散点/跨期/分群/用户画像、订单/拆单/变现、
推广/素材/标题包/自定义人群/B 站/广告主、公司用量/业务脉搏、多维/SQL/metadata、多 App 与看板重放。
预期在任何调用前冻结，生产请求没有通过换 App、扩窗、重试或额外翻页追非空。

原始结果按“正确 `MULTIPLE_INTENTS` 或明确 capability gap 也算合法终点”是 **4 / 20**；若只算
业务数据答案则是 **0 / 20**。首调错路由 **8 / 20**：漏斗卡夹带 App raw operation，属性/散点落到
raw operation，素材被误判为素材+推广双意图，带日期和双类型的 title-package 落到 generic Analysis，
广告主/metadata/看板重放报无能力。另有事件趋势、留存仍停在 generic Analysis handoff。

当轮只在领域 `agent_*.py` 内修复了可复现的窄问题：事件趋势与留存现在返回 kind-specific 卡，
素材弱 `ad` 词不再误触发 Promotion，字段式英文广告主问法和 `saved dashboard` 重放可达正确 owner，
“变现表现”返回产品边界 gap 并给出可复制的 detail 重新发现命令。属性/散点已能把正确 Spec 卡排在
第一，但共享 authoritative selection 仍夹带 raw operation，故仍不算唯一卡。原始 8 个错路由中
修掉 3 个，剩 **5 个**；修复后的离线重放不改写原始首调数字。

已完成执行的 Custom Audience 与 Bilibili 两题都严格用了 Agent + Plan 两次顶层调用，未发现
`gravity.agent-call-bound.v1` 失配；前者以 upstream/3 `CONTRACT_CHANGED` 失败，且 next action 仍含
`<operation-id>`，后者以 caller/2 `PAGINATION_LIMIT` partial 停止，且只说提高 bound。两个失败
envelope 都没有保留逐页 HTTP receipt，所以只能证明加上 App catalog 后共 **3–11 次 HTTP**，不能
事后伪造精确次数；这是观测缺口，也是下次生产实测必须先装脱敏 request observer 的前置条件。

本实测自身在当时快照上的净变化为 0：`48 = 32 / 0 / 16` 加 `0 / 0 / 0` 后仍为
`48 = 32 / 0 / 16`；后续 setting route 去重使最终台账成为 `47 = 32 / 0 / 15`。它没有改变任何
产品面，只证明“四面存在”不等于自然语言入口真的可完成；其中 32 条的 Agent 面仍须按后文收紧的
自然语言判据重验，不能把本节当成闭环确认。未修项是共享 authoritative selection、class-level
metadata 产品卡、title-package 日期/双变体边界、Plan 错误 operation-id 投影、Bilibili 可复制分页
动作和 SQL 缺配置的 local/4 统一；具体退出条件记在技术债和动线台账说明中。

## 九条 `1 / 3` 调用成本裁决（2026-08-14）

**裁决：九条均可在 App/平台及其余业务输入已知时降到两次调用。** 本节在这些 scenario 上取代
上面的三次下界；旧裁决只否定
“把目录选择折进执行”：执行命令不能替调用方挑一个看起来合适的引用或物理字段，这一点继续
成立。本轮新增的是显式在线输入解析：

```powershell
gravity agent "<query>" --resolve-inputs <known-inputs.json> --output <catalog.json>
```

SDK 同形入口是 `GravitySDK.resolve_capabilities(...)`。第一次调用完成能力发现，并读取完整、受治理的
在线目录；metadata/table-lineage 冷目录则在 staging SQLite 中完整刷新后原子发布。调用方在返回值中
按稳定 ID（模板按 `scope + id`）或物理名称精确选择，第二次仍走原有 CLI/SDK/Plan 执行入口。
解析响应明确声明 `caller_call_unit=cli_or_sdk_invocation` 和
`internal_http_calls_reduced=false`；它降低的是调用方顶层调用数，不降低、也不隐瞒目录 HTTP 数。

七条在线目录路径分别复用 Dashboard tree、Saved Analysis catalog、Analysis template catalogs、
Segment catalog、Multidim metadata 和逐平台 Promotion metric catalog。引用执行端会重新读取目录：
删除的 ID 找不到即 fail closed，改名仍由同一稳定 ID 指向同一对象，新建对象不会改变已选 ID；
Saved Analysis 还会核对目录与详情身份。Multidim 卡的闭合 schema 给出静态字段，完整 metadata
给出指标、自定义指标及已证明的动态维度；第二次由 FieldPolicy live 复验指标、维度成员关系和排除
关系。日期和 filter value 仍由调用方业务上下文提供，解析器不生成业务值。
Promotion 第二次由 FieldPolicy 逐平台复验指标。在线解析前后都会清除进程内 metadata cache，
同一 SDK 进程不会把解析前的旧目录带入第二次执行。

metadata search 与 table lineage 过去仍是“冷机 3 次”，原因不是离线模式另有计数口径，而是首个
Agent 调用坚持零网络：调用方随后还要单独 `metadata sync`，再执行离线查询。本轮只有在调用方显式
指定 `catalog_policy=refresh` 时，第一次在线 Agent/SDK 调用才把发现和完整 refresh 合并。任一来源
失败时 staging 库丢弃、旧 catalog 保留且本次解析报错；成功后的第二次查询返回带 `synced_at` 的
observed snapshot，不把同步时刻之后的变化声称为当前事实。

这是纯加法能力：默认离线 `gravity agent`、`GravitySDK.capabilities()`、直接 list/metadata sync 和
所有既有执行入口保持不变。解析器只交付受批准投影中的候选，不根据名称相似度、业务口径或自然语言
替调用方选值。若 App 也未知，或 Promotion 的平台也未知，依赖目录仍有先后关系，不能据此宣称两次；
原 `unknown_app_and_*` 下界继续有效。动态卡和 `plan_node.call_bound` 同步使用
`gravity.agent-call-bound.v1`，只有本次确实交付完整目录的 scenario 才降为 2。

**最强反驳：这只是把原来的“Agent 发现 + 目录读取”组合成一条命令，HTTP 量和在线失败面没有减少，
很容易被包装成虚假的成本优化。** 这个反驳对上游成本完全成立；本裁决只在台账既定的
“调用方顶层 CLI/SDK 调用数”口径下成立，所以响应必须保留 live/refresh 收据并直说 HTTP 未减少。
更接近实质失败的是两次调用间没有上游 revision/ETag：当前安全性依赖合同中的稳定 ID，并由第二次
live re-resolution 防止删除或名称漂移选中别的对象；SDK 不能证明上游将来绝不违规复用 ID，也不能
给同一对象的内容编辑提供点时快照。若上游出现 ID 复用证据，或产品要求执行第一次看到的历史版本，
本裁决失效，必须先取得 revision/conditional-read 合同，不能继续按两次闭环计。

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

当前只有治理导出、response-bound 素材文件这两类直接文件 effect，以及下文登记的 Segment mutation
Plan 面适用此例外；素材文件的逐条证明登记在本页第三轮 Issue 19 裁决。
**新增例外必须同时满足以上三条并在此登记**。

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

### Analysis typed primitives 裁决（2026-08-16）

对标 Mixpanel Headless 后，裁决是**有真实但很窄的组合缺口，应做 Analysis 领域层，不做通用层**。
五类 compact Spec 已共享 condition/metric/event-step 机器 schema 和同一个 compiler，所以查询能力与
合法形状没有缺口；但公开 SDK 只接受 `Mapping`，调用方复用 filter/metric/现有 segment reference
仍靠仓外 dict 复制。`plan_recipes` 已覆盖 App、日期和预先存在 scalar filter value 的 typed 替换，
batch v2 已覆盖同一 literal spec 的显式多 App 扇出；二者都不能追加 condition array item、替换完整
metric object，或把同一受控片段放入另一 kind。这里是程序内结构组合缺口，不是 Plan 参数化缺口。

本轮新增 `analysis_primitives.py`：`AnalysisFilter`、`AnalysisMetric`、`AnalysisCohort`、
`AnalysisStep`、`AnalysisSpec`。`AnalysisCohort` 只表示现有 `user_segment` 引用，不提供 cohort CRUD
或自由规则；`AnalysisSpec` 是不可变 `Mapping` wrapper，可无损包装旧 spec，并只开放已登记位置的
App/日期/metric/filter 增量操作。位置错误在构造期失败；依赖 kind FieldPolicy 或 live metadata 的
语义仍进入唯一 compiler/preflight 后 fail closed。typed/literal 五类回归固定同一 `query_id` 后，
编译出的 operation input 按实际 JSON 序列化逐字节相等。

typed 构造面新增 25 个 caller-recoverable 错误起点，全部有字段路径和替代动作，分档均为 B；
actionable-error inventory 从 `974 + 25 = 999`，分档从 `A/B/C = 218/400/356` 变为
`218/(400+25)/356 = 218/425/356`。这是新增公开输入边界的完整库存更新，不删除扫描范围、不改
分档规则，也不把错误藏到未登记 helper。

结果层不改。现有 envelope 的 schema/status/operation 与 batch `node_id/query_id/app` 身份对可靠比较、
空值和 partial 对齐有帮助；调用方需要自行拆出各引擎 `result.data`，这是保留异构受治理结果的有意
边界，不引入 pandas/DataFrame 依赖，也不做跨 App merge/sort/diff。没有新增 registry、DSL、Plan
binding、adapter 分支、线程池、operation、CLI 参数、envelope 或退出码；`plan_adapters.py` 净增长
`0`。台账可复算为 operation `185 + 0 = 185`，stable `176 + 0 = 176`，Analysis journey
`既有行 + 0 = 既有行`。

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

## D35 / F40 归因结果合同（2026-08-16）

### 提案与静态控制流

本轮先复核 census 同快照前端 bundle 的 hash，并沿 `Measurement` 页面从状态初始化、目录装载、
`Gt` builder 到每个 `/adreport/attribution/` 调用点逐字段恢复完整请求：区分固定字段、页面默认值、
调用点枚举、App/项目目录绑定、配置返回值与调用方筛选，明确 `undefined` 省略和空数组保留规则。
在 builder、值域来源和父依赖形成可复核静态证据前，生产业务请求保持 0 次。

静态证明完成后，只从前端自然调用形状中选择单日、无筛选、无项目、无自定义拆分的最小形状，
按 App catalog 顺序串行验证；同一 `(App, 请求形状)` 仅发一次，不重试、不翻页、不扩窗，取得首个
成功或明确空响应立即停止。若服务端仍拒绝，保留具体错误路径与值无关响应形状，并把下一步收敛到
一条未证明事实。只有 D35 的请求、响应、分页和错误合同成立，才提升 stable operation 并接通
Core / CLI / SDK / Plan / Agent card；随后再以同样证据标准判断 F40 的标识来源、请求绑定、分页和
响应合同，不能用字段投影已放开替代这些事实。

`attribution.attribution.query` 的**前端 builder 已完整恢复**（从与 census 快照哈希匹配的
`Measurement-BV1Ulzee.js` 中的同作用域 builder `Gt`），16 个顶层字段：
该 bundle 的 SHA-256 为
`fb9d486e882c783709794cecce8fb72849151e70eea26537603d7b222a7216ed`；入口
`index-D9HAN43D.js` 为
`aa67659c360861d73309b2f9ca93ac15d95d6b39a092912a32cb72b9f1662d6b`。

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

**2026-08-16 审计纠正：旧“服务端拒绝”判定不能成立。** 当时 2 次最小 POST 虽被记成
`semantic_error`，evidence 只保留 shape/fingerprint，没有保存 `code`、`msg` 或 `extra.error` 原值；
同时旧 prober 把任意非空 `extra.error` 一律当拒绝。已完成归因线的独立 committed evidence 使用精确
builder 记录到 `code=0`、`msg=成功`、`extra.error=无数据` 和空聚合容器，随后同形状取得非空成功，
证明该登记值语义为明确空，不是参数错误。它不能倒推出旧两次响应的具体正文，但足以撤销旧标签对
“缺服务端必填/值域”的证明力。

语义审计本身未据并行工作提升 D35；随后归因线用会保存协议判据的新 evidence 完成重新取证并闭环 D35。
F40 的旧 D35 依赖理由同步失效；其独立证据已由下节的测试设备目录与唯一详情请求补齐。

值域与依赖来自同一控制流，而不是猜测：`app_id` 取 App catalog 选择项，若页面未来设置
`connect_app_id` 则优先使用它；当前 bundle 只观察到初始化/重置为 `0`，没有正值赋值。直接 App
把 `project_id` 置为 `0`，所以最小请求省略它；页面没有归因方案 ID 的装载或选择父链。
`date_list` 来自调用方日期区间；`report_level` 的页面枚举是空值/day/week/month，最小为 day；
`statistics_caliber` 的四个实际调用点只用 `user_activated_time` 或
`behavior_occurred_time`；`time_zone` 来自页面时区设置（默认 utc，也可 ortz）；精度开关只产生
2 或 4。筛选值分别来自平台、OS、渠道、版本、运营商、推广对象、aid、广告主目录；最小请求不猜值，
八项均为空数组。`dims_metrics_list` 来自调用方额外拆分，空时省略。

四个前端调用画像已逐一登记为同一受控 operation 的有限输入：

- `attributed_registrations`：`AppRealRegisterCnt`，`date/ad_platform`，激活时间口径；
- `activation_and_pay`：`AppActivateStandard/AppGamePayAmountReportingStandard`，
  `date/ad_platform`，行为发生时间口径；
- `activation_conversion`：三种 `AppActivate*`，`date`，激活时间口径；
- `overview`：`AdShow/AdClick/AppActivateStandard/AppRegisterStandard/`
  `AppGamePayUserCntStandard`，`date`，激活时间口径。

### 生产账本与 D35 裁决

生产共 **3 次业务 HTTP**，全串行、无重试、无翻页、无扩窗，也未触发鉴权刷新：

| 次序 | 目的 | 状态 | 结论 |
| --- | --- | --- | --- |
| 1 | `app.list` 目录事实，第一页 | HTTP 200，7 个候选 | 只在内存按目录顺序取 App；未保存名称 |
| 2 | 首个 App，单日，`attributed_registrations` | HTTP 200；`code=0`、`msg=成功`、`extra.error=无数据` | 明确空；五个数据容器均存在，列表均空 |
| 3 | 第二个 App，同一单日同一形状 | HTTP 200；`code=0`、`msg=成功`、`extra.error=""` | 非空；`columns=3/items=2/static=21/total=1`，立即停止枚举 |

旧不可变 evidence 只保存 `semantic_error` 分类、shape fingerprint 和容器计数，**没有保存**
`msg` 或 `extra.error` 的实际正文，因此不能追认某个服务端字段拒绝原因。新证据反而证明精确 builder
是合法请求，并证明 `extra.error="无数据"` 是成功的明确空。故旧标签不足以证明“服务端拒绝 body”；
本轮合同把 `code in {0,200}` 且 `extra.error in {null,"","无数据"}` 视为非错误，其他值 fail-closed。
这既保留了未知拒绝，也修正了明确空被误分类的风险。

**D35 已闭环。** `attribution.attribution.query` 晋升 stable v1，公开已观察的全部
`columns/items/static/tips/total` 字段，并以动态指标字段绑定有限前端画像；分页为 none。Core
`attribution_performance`、CLI `gravity attribution performance`、SDK、Plan
`attribution_performance` 与 Agent card 共用 `gravity-insight.attribution-performance.v1`。
已知输入 1 次顶层调用、未知 capability 2 次；未知 App 的离线默认场景为 3 次，均由
`gravity.agent-call-bound.v1` 声明。四个内部 HTTP 共享一次 bounded batch 与 Plan worker 租借，
不把内部请求数误算为调用方调用次数。

### F40 生产账本与裁决

hash-matched `Device-TemCRn-D.js` 和 `userSearch-Bhwew5eC.js` 证明：搜索 route 的 body 是
`{app_id,key_word:trimmed-or-undefined}`，响应消费 `data.attribution_list`；测试设备父目录 body 是
`{app_id,page:1,page_size:1000}`，响应消费 `data.list`。调用方选中一行后，详情 body **仅为**
`{app_id,device_id:Number(selected.data.list[].id)}`；这里的 `device_id` 是登记测试设备行的内部 id，
不是可猜的原始设备标识。详情无服务端分页，前端完整消费 `device_white/attribution_list/`
`postback_list/pay_list`。
两 bundle 的 SHA-256 分别为
`5a8a9ad1ee358899bbcbf09fc43711285c51015667431e5fe1892029a4bc3aae` 与
`8a8fda10088a31c241ebd1e96624d8daf9a36e289f09bcf78204398a8c888069`。

旧的“未授权枚举用户级测试设备目录”约束已由项目裁决撤销。生产请求严格串行，共 **8 次业务 HTTP**，
全部 HTTP 200，未触发鉴权刷新、重试、翻页、扩窗或详情重发：

| 次序 | Operation | 目的与结果 |
| --- | --- | --- |
| 1 | `app.list` | 取得 7 个 catalog App，只在内存按目录顺序选择。 |
| 2–6 | `app.testing_tool.list` | catalog #1–#5 均 `code=0/msg=成功` 且 `data.list=[]`。 |
| 7 | `app.testing_tool.list` | catalog #6 首次返回 1 条，立即停止；父行 ID 仅在内存中使用。 |
| 8 | `attribution.attribution_detail.query` | 唯一详情请求，body 为 `{app_id,device_id:Number(data.list[].id)}`；`code=0/msg=成功`。 |

目录非空行完整字段为 `app_id:int/create_time:string/device_info:object/id:int/is_template:bool/`
`modify_time:string/name:string/remark:string/reuse_from_device_id:int/testing_company:string/`
`testing_end_time:null/testing_start_time:null/testing_status:int`；`device_info` 子字段为
`android_id:string/imei:string/oaid:string`。分页壳为 `page/page_size/total_number/total_page:int`；前端
固定请求 `page=1/page_size=1000` 并做本地展示分页，本轮按纪律未翻页。

详情 `device_white` 为与目录行相同的完整 object；`attribution_list`、`postback_list`、`pay_list`
均为明确空 array。空数组没有 item 字段证据，故不猜 schema；公开产品严格接受本次已登记空合同，未来
出现非空 item 时返回 `CONTRACT_CHANGED`，待新 shape evidence 登记后再升级。

**F40 已闭环。** `app.testing_tool.list` 与 `attribution.attribution_detail.query` 晋升 stable v1；
Core、CLI `gravity attribution user-detail`、SDK、Plan `attribution_user_detail` 与 Agent card 共用
`gravity-insight.attribution-user-detail.v1`。`gravity.agent-call-bound.v1` 声明已知输入 1、未知
capability 2、未知 App 3、未知设备父行 3、二者均未知 4；父目录依赖不能被凑成无依赖的 2 次。

在此前 D35 新增 4 个 A 档错误点基础上，F40 新增 **2 个** caller 可恢复错误点（详情正整数输入、
Plan request shape），**2 个均为 A 档**；当前集成树从 `1073 = 269 A + 434 B + 370 C` 变为
`1075 = 271 A + 434 B + 370 C`。技术债清单已复核：详情 core 和测试设备 probe 解析均下沉到领域模块，
共享入口的 SLOC/复杂度 ratchet 未上调，也没有新增可由当前源码证明的结构债。

### census 提取器的已知能力边界

那两次未解析 load 卡在 `census/params.py` 的 `_infer_expression`：**无法内联函数调用**
`Gt(...)`，内存形状标为 `unresolved_body_expression`，导致 `body_parameters=[]`。
同 route 另 3 个 occurrence 卡在条件 callee `(e===1?Ie:ze)(...)`，标记
`load_alias_has_no_static_call`。

**杠杆统计已完成，结论是不修。** 同一快照下，条件 alias 影响 97 条 route、123 个 occurrence；
其中 49 条是写、23 条已覆盖、7 条 auth/proxy、1 条 export，只有 17 条未覆盖读。函数调用的
`unresolved_body_expression` 影响 60 条 route、82 个 call site；45 条是写、7 条已覆盖、4 条 export、
3 条 auth/proxy，唯一未覆盖读就是 D35。该 reason 只存在于内存 `_Shape`，序列化后折叠为
`analysis.unresolved_calls` 计数，所以在 `route-params.json` 中 grep 为 0；这仍解释静态提取边界，
但不再为已撤销的 D35 服务端拒绝结论背书。

与台账交叉后，15 条完全缺失、12 条部分闭环中，**当前阻塞根因属于这两类提取失败的均为 0**。
D35 的前端 16 字段已经人工恢复；旧服务端阻塞已在 2026-08-16 语义错误审计中撤销并待重新取证。
默认值字典已有另一 occurrence 提取出
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

