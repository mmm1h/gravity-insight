> 归档材料：保留历史决策与取证，不代表当前接口或状态；当前入口见 docs/index.md。

# 写操作范围与自然语言路由

- 日期：2026-08-18
- 任务：存量 `docs/roadmap.md` 按主题归档
- 结论：Segment CRUD、三臂对照与臂 C、报表订阅写解锁、Catalog parity、十分钟主路径与 protected selector。

正文为原 `docs/roadmap.md` 对应段落的逐字归档，不是新裁决。
文内相对链接按原 `docs/` 根路径理解（本文件在 `docs/roadmap.d/`）。

---

## 写操作范围裁决与 Segment CRUD（2026-08-16）

**提案与范围：**工作底稿位于 ignored `tmp/codex/write-segments/proposal.md`。项目范围从“业务
operation 全部只读”扩大为“允许逐项治理的分析闭环 mutation”，首批只批准 7 条 Segment route：
`analysis.segment.from.analysis.create`、`analysis.segment.from.rule.create/update`、
`analysis.from.history.version.create`、`analysis.from.tmp.segment.create`、
`analysis.segment.by.manual.update` 与 `analysis.dataanalysis.segment.update`。推广投放、素材、
多维报表、权限、测试设备白名单、`event/event_batch_delete`、
`event_property_batch_delete` 和其余 mutation 不随框架自动获准，继续 reservation/blocked write。
合入当前 dev 后，operation `187 + 7 = 194`，stable `178 + 7 = 185`，callable census route
`174 + 7 = 181`。

**标记与删除闸门：**创建标记放在上游 `segment_remark`，因为列表和 detail 都原样返回该字段，
且它不改变分群规则或成员语义。当前格式为 17 字符 `GSDK-<12 hex>`，由 create kind、规范化语义
请求和可选 idempotency key 的 SHA-256 前 48 bit 确定；可见、稳定、可列表检索，但绝不用于过滤
列表。线上 `from_analysis` 曾接受旧 `gravity_sdk_v1_<16 hex>`，`from_rule` 对旧长格式加说明文字
返回 remark invalid，因此默认收窄到紧凑格式，同时只为清理已经创建的旧对象保留旧格式识别。
调用方说明只放在标记后的 ` | `，超出本地上限时只截说明；标记永不截断、删除或替换。若紧凑标记
仍被某 route 拒绝，操作失败关闭，不做无标记重试。删除执行前必须用 exact ID 读 detail，从上游
preimage 提取标记、名称和 App；没有标记返回 `OWNERSHIP_MARKER_REQUIRED / caller / exit 2`，调用方
传入的名称/备注不能证明归属。该机制防 SDK 自误删，不是权限体系。

**dry-run、幂等与不可重放：**7 条 mutation 的 `--dry-run` 只做合同校验和 wire 编译，返回固定
method/path/query/body 或依赖 preimage 的 request template、目标、影响和前置条件，`offline=true`、
`network_called=false`、`attempts=0`。执行使用与普通 read executor 分离的 mutation executor；每个
exact wire 由 policy 签发一次性 nonce + digest 授权，transport 消费后立即失效，`attempts=1`，401、
限流、超时或连接错误都不自动重放。create 在进程内锁下先完整读列表：同 marker+同名直接复用而不写，
同名异 marker 或同 marker 异名以 caller/2 冲突失败。跨进程竞态仍由上游名称唯一约束收口：线上对
完全相同的第二次 `from_analysis/create` 实际拒绝“名称已存在”，没有生成第二个对象。

引用冲突不能从 Web 文案推断。线上用规则分群 B 引用分群 A 后删除 A，上游仍返回成功并在列表中
消失，说明当前 route 没有可依赖的引用保护（或该类引用不阻止删除）。SDK 不伪造本地引用扫描；若
上游以后明确返回“被引用/使用中”，映射为 `OBJECT_REFERENCED / caller / exit 2`，由调用方先解除
引用。其余写失败沿用三类退出：已存在、被引用、配额超限、缺 ownership marker 为 caller/2；并发
修改和写后读回不确定为 upstream/3，前者可由人重新读后再发但 SDK 不自动重放；本地合同/策略损坏为
local/4。没有失败模式需要第四类退出码。

**读语义与运行时不可绕过性：**`prober/read_semantics.py` 只在 source operation 与仓库
`contracts/operations/<operation_id>.json` 全对象相等，且登记项同时为 `stable + executable +
effect=mutation + POST` 时放行 mutation；它不读取 `confirmed_read` 文件来给写路由改身份。任意 path、
method、effect、字段或稳定性篡改都会失去全对象相等并在 transport 构造前失败；普通 read policy 仍
拒绝 mutation，真正执行还必须再经过 stable registry、mutation input validator、exact route/method
校验和一次性授权。运行时调用方不能只传 operation ID 或伪造 POST 绕过；修改仓库 source contract
本身属于需评审、编译和版本控制的权限变更，不是运行时旁路。

**Plan 与 Agent 裁决：**Segment mutation 不进入 Plan v1，台账 Plan 面记“设计不适用”。它逐条满足
窄例外三条件：(1) create/update/delete 是不可安全重放且需要确认、preimage 和写后读回的 effect，
与 Plan v1 无副作用数据节点的重试/调度模型不兼容；(2) Core、顶层 CLI、SDK 均可完成任务，Agent
卡直接给先 `--dry-run`、确认后 `--execute` 的明确命令交接，缺 Plan 不减少调用方任务集合；(3) 本节
与 `docs/analysis-journeys.md` 已把该面登记为“设计不适用”而非“无”。自然语言只返回
`confirmation_required=true`、`plan_executable=false`、`natural_language_auto_execute=false` 的卡，
没有 Plan node，绝不创建或自动执行。

**安全层同步建议：**第五层应把“编译后 stable operation 的 exact `effect=mutation` 身份 + 本次
一次性 mutation policy receipt”作为合法 mutation 的共同必要条件；仅凭 POST、写词元或 Agent 卡不
足够。未登记 route、draft/reservation、contract 不相等、普通 read authorization、receipt 缺失/复用/
wire 不等仍判违规。本线不改评测装置，避免与 `safety-layer-narrow` 并行线冲突。

**生产账本：**所有实际 write 之前均有零网络 dry-run，写预算上限 20，实际 **10** 次，全部
`attempt=1`、无自动重试：(1) `from_analysis/create` 创建测试 A；(2) 同语义直达已登记 mutation，
上游拒绝重名；(3) `from_rule/create` 旧长 remark 被拒；(4) 紧凑标记创建测试 B，上游成功但首次本地
列表读回因 `update_date_range` 嵌套漂移失败，登记精确 nested keys 后读回确认；(5) B 引用 A 时
`save/DEL` 仍成功删除 A；(6) `save/UPDATE_NAME` 成功并读回保留标记；(7) `from_rule/update` 的字符串
ID 被上游拒绝；(8) 按前端数值 wire 修正后更新成功并读回；(9) `by_manual/update` 刷新成功并读回；
(10) `save/DEL` 删除 B。最终再次读取完整列表，SDK 标记与 SDK 测试名称均为 0，生产无残留。
历史版本另存和临时分群持久化已按 hash-matched 前端 wire 登记、dry-run 与测试覆盖，但当前账号在
测试前没有现存分群/临时父对象，未为了覆盖 route 再造业务父链，故没有生产成功样本。

本单元全部生产 HTTP 可由 receipt 复算为 **39**：read/preflight/readback 29 次——`app.list` 2、
`analysis.event.list` 3、`analysis.event_property.list` 1、`analysis.funnel.query` 1、
`analysis.segment.list` 11、`analysis.segment.detail` 11；mutation 10 次——
`from_analysis/create` 2、`from_rule/create` 2、`from_rule/update` 2、`save` 3、manual refresh 1。
transport 状态均为 HTTP 200；四次 mutation 的失败/不确定来自上游语义或本地读回合同，不把 HTTP 200
误记为业务成功。两个实际创建对象都已清理。

**端到端闭环：**调用方给 funnel spec、App、step 和 loss/matched 选择，先运行
`gravity analysis segment create-from-analysis ... --dry-run` 查看精确 funnel 选择与持久化请求，再经
人工确认运行同命令 `--execute`；产品先执行同一已验证漏斗、单次创建、列表/detail 读回并返回稳定
segment ID。该 ID 随后可直接交给 `analysis segment snapshot`、`members` 或留存 spec 使用，最后由
`analysis segment delete --segment-id ... --dry-run` / `--execute` 经标记闸门清理。因此
“漏斗流失 → 保存分群 → 分析留存/成员”已不依赖 Gravity Web。按“一条动线 = 一个调用方能独立完成
的分析任务”复核，保存/管理分群的任务终点是上游可复用分群对象，与读取已有分群详情或成员不是同一
任务，因此从合并前 dev 的 `48 = 36 / 1 / 11` 新增 1 条已闭环动线，成为
`49 = 37 / 1 / 11`。本行闭环只使用生产已验证的 `from_analysis`、`from_rule`、`by_manual` 与 `save`；
`from_history_version/create` 和 `from_tmp_segment/create` 未生产验证，不计入闭环证据。

本线新增 caller-recoverable raise site **27** 个，全部 A 档：全仓从
`1034 = 230 / 434 / 370` 变为 `1061 = 257 / 434 / 370`。技术债清单已复核：mutation policy、wire、
Segment domain core/SDK/CLI 分文件，`registry.py` ratchet 继续收紧，未新增可由当前源码证明的结构债。

## 自然语言路由三臂对照（2026-08-16）

**书面提案：**臂 A 保留现有 recognizer，不改正向、负向或歧义判据。臂 B 采用纯 Python、离线、
确定性的词法检索，只索引既有产品卡的 name/selector/description 与已登记 capability-gap 文案；
仅在完整既有发现链得到零候选、且既有专属 gap/阻断未作判断时运行。单命中只重新物化既有 card/gap，
两个及以上过阈值命中必须经集中层返回 `MULTIPLE_INTENTS`，低于阈值保留 capability gap，绝不按
top-1 强选。臂 C 只扩展评测装置的外部 selector 协议并用固定离线桩证明可测，不接真实 LLM，
不进入产品路径。

阈值只用 development 做 shadow sweep：要求单命中精度 100%、相邻产品不被强选且低置信输入 abstain；
满足约束的阈值中先取召回最高者，并列时取更高者。开工 development 六层为产品选择 `240/240`、
参数可填 `175/175`、离线终点 `65/65`、错误恢复 `5/5`、安全门禁 `PASS/0`，产品选择和终点均
`pass^1 = pass^4`；生产 HTTP 0 次。只有 implementation、development 六层和确定性全部固定后才允许
一次 holdout 选臂查询；预期验证产品选择高于已记录臂 A `193/240`，且离线终点、安全和确定性不退化。
不读取或运行 final，也不根据 holdout 聚合反馈调词、文案或阈值。完整工作提案在 ignored
`tmp/codex/routing-arms/proposal.md`；最终数字、查询账本与拟合风险将在本节原位收口。

**臂 B 实现与阈值：**现有 recognizer、负向词、selector 精确度和 operation fallback 判据均未修改。
只有完整原链得到零候选、且专属 gap/semantic block 也未作判断时，才计算
`idf_weighted_term_coverage.v1`。英文按去通用停用词的 word token，中文按 2/3 字符 gram；分数是 query
token 的 IDF 加权覆盖率，范围 0--1。索引数据仅来自既有 card 的 name/selector/description、workspace
recipe/SQL product 同名字段、已登记 gap 的 journey/code/reason/next_action；刻意不索引 aliases 和评测题。
至少要有 2 项命中证据且分数达到 **0.375**。单命中重新使用既有 card/gap，多命中调用集中
`product_selection_gap` 返回 `MULTIPLE_INTENTS`，不取 top-1；无命中保留原 capability gap。响应的
`match_policy.zero_candidate_lexical_fallback` 暴露算法、阈值、最低证据数、top score、selector 和
matched terms，同一输入不含随机数、时钟、hash iteration 或网络因素。

阈值是在 development shadow mode 一次性固定的。代表性 sweep 为：`0.35 = 26 correct / 1 wrong /
7 multiple / 206 abstain`，`0.365 = 27 / 0 / 5 / 208`，`0.37 = 28 / 0 / 3 / 209`，
`0.375 = 28 / 0 / 3 / 209`，`0.38 = 26 / 0 / 3 / 211`，`0.39 = 26 / 1 / 2 / 211`。
按提案先要求单命中错误为 0、相邻产品不强选，再在正确单命中最多的并列阈值中取更高者，故为 0.375。
定低的实际失败模式是错误单命中，或更多请求只得到 `MULTIPLE_INTENTS`；定高则不会错选，但会把可解释
的正确检索重新变成 gap。当前 development 原链已经 `240/240`，因此臂 B 实际修复的当前
`no_candidate` 是 **0**；shadow 的 28 个正确单命中只是“若原链 abstain 时可恢复”的反事实上界，
不是新增通过题数，更不能冒充留出证据。

六层 development 前后对照为：

| 层 | 臂 A before | 臂 B after | 变化 |
| --- | ---: | ---: | ---: |
| 首次产品选择 | `240/240` | `240/240` | `0` |
| 已到达卡参数可填 | `175/175` | `175/175` | `0/0` |
| 离线终点 | `65/65` | `65/65` | `0/0` |
| 错误恢复 | `5/5` | `5/5` | `0` |
| 重复可靠性 | selection `240/240`、terminal `65/65` | 同左 | `pass^1 = pass^4`，unstable 0 |
| 安全遵守 | `PASS/0` | `PASS/0` | 0 violation |

**臂 C 测量通路：**evaluator 的 `--selector-plugin <python-file>` 每个 trial 向独立进程发送整批
question 和 `agent-catalog` 的 category/capability 投影；响应只允许每题 0--5 个目录内 selector。
未知 selector、重复/缺失 ID、额外字段、malformed JSON、非零退出和 timeout 都在评分前 fail closed；
0 个 selector 记 `EXTERNAL_SELECTOR_ABSTAINED`，多个仍走 `MULTIPLE_INTENTS`，单个 describe 后由原六层
评分。固定离线桩完整跑通 4 trials：产品选择 `27/240`、参数 `27/27`、离线终点 `0/65`、错误恢复
`5/5`、安全 `PASS/0`，selection `pass^1=pass^4=27/240`。该低分只证明通路真的在评分，桩明确登记
`meaningful_accuracy_evidence=false`，不评价 LLM。真实 LLM 还缺 pinned provider/model/prompt/decoding、
凭据与 egress 授权、可信用量/延迟/网络 receipt、protected split custody，以及对当前 catalog 未包含的
Analysis compiler、metadata、export 和专属 gap 身份的覆盖裁决；父进程无法审计子进程 egress。

**protected 查询与结论边界：**implementation、development 和门禁固定后，按预注册 purpose 准备执行
唯一一次 holdout，但当前 worktree 与文档指定 custody worktree 的固定
`.local/agent-usability/holdout.key` 均不存在；账本为 holdout 0 / final 0。既有密文不能用新 key 解密，
没有生成替代 key、搜索其他位置、读取密文或运行 holdout/all/final。因此本轮 holdout **0 次**，不能声称
从 `193/240` 达到 `228/240`；该目标仍需 custodian 恢复原配对 key 后按上面的已冻结 purpose 查询一次。

**泛化与拟合判断：**较可信的是 zero-candidate-only 接点、aliases 排除、IDF 由运行时登记文案推导、
低分 abstain 和集中多意图裁决；它们不依赖具体句子。偏拟合风险最高的是：被索引的 card/gap 文案本身
曾随 development recognizer 轮次演进，0.375 又由同一 development suite 选择；中文字符 gram 还可能
把共享短片段放大。没有加入 case id、完整句、词序特判或删除负向词，但在未查 holdout 前只能称候选臂，
不能称泛化已证明。产品/动线/operation 计数均为 `+0`，生产 HTTP 0 次。
本线新增 caller-recoverable error site `0` 个，因此新增 A/B/C 为 `0/0/0`；全仓审计仍为
`1061 = 257 / 434 / 370`。技术债清单已复核：检索 core 和 selector harness 均在窄模块内，
共享 `agent.py` 恢复到 500 SLOC 质量上限，未新增可由当前源码证明的结构债。

## 自然语言路由第二轮：调用方语言索引与分布阈值（2026-08-16）

**预承诺与边界：**阈值 sweep 前先在 `tmp/codex/routing-semantic/threshold-criterion.md` 写死规则：
排除评分表达不可信的 12 道 `multiple_intents` 后，在 324 题上不新增 wrong product、错误/泛化 gap
或错误歧义，且旧 240 逐题不退化；可行点取 correct 最多，平局取更高阈值。看完 index-only 分布、
但未看任何候选结果时，固定 `0.125..0.375`、步长 0.025 的 11 点网格。只运行 development；
未运行/读取 holdout、final、all、sealed payload 或 key，生产 HTTP 0 次。

**索引增量：**`agent_caller_language.py` 只保存早于扩题存在的 `docs/analysis-journeys.md` 动线标题与
`docs/agent-workflow.md` 产品独立任务描述，并声明这两个来源；没有 `evals/` 内容、题面片段、变体、
case ID 或词序规则。development 内臂 B 的 48 个可安全重物化 card/gap identity 全部取得调用方语言，
共 60 个字段；runtime export inventory 另按 selector 取得素材导出标题。
三条 governed mutation 动线仍由原 recognizer 解析具体 action 并交接 dry-run/人工确认；静态 fallback
不物化 exact-selector 的默认写 action，故没有扩大写能力或 fail-closed 边界。

阈值保持 0.375 时，扩索引单独净救回 **0**，六层前后均为产品选择 `262/336`、参数 `201/201`、
离线终点 `61/77`、错误恢复 `5/5`、selection/terminal pass^4 `262/336、61/77`、安全 `PASS/0`，
不稳定题 0。52 个 fallback 触发仍全部 abstain，但 top score 右移：非零 `47→49`，P25
`.020359→.022781`、P50 `.038222→.053143`、P75 `.065549→.118219`、P90
`.105248→.195502`、P95 `.177314→.235632`、最大 `.285469→.320407`。当前 44 个
no-candidate 中 41 个属于固定触发队列；该子集 P50 `.038036→.051293`、P90 `.104290→.165080`、最大
`.244262→.241796`，证明文档扩充不会让每题单调增分。

**完整权衡曲线与选择：**固定扩索引时原 52 个 fallback 位点，完整门禁进一步发现其中 5 个纯否定
且没有明确正向重述；最终实现对这 5 个 fail closed 并在检索前返回 `not_needed`，下表把它们计入
abstain，实际进入词法评分的是 47 个：

| 阈值 | correct | wrong | multiple | abstain |
| ---: | ---: | ---: | ---: | ---: |
| 0.125 | 7 | 0 | 3 | 42 |
| 0.150 | 7 | 0 | 2 | 43 |
| 0.175 | 5 | 0 | 2 | 45 |
| 0.200 | 3 | 1 | 1 | 47 |
| 0.225 | 2 | 1 | 1 | 48 |
| 0.250 | 0 | 1 | 1 | 50 |
| 0.275 | 0 | 0 | 1 | 51 |
| **0.300** | **1** | **0** | **0** | **51** |
| 0.325 | 0 | 0 | 0 | 52 |
| 0.350 | 0 | 0 | 0 | 52 |
| 0.375 | 0 | 0 | 0 | 52 |

0.175 的两个 multiple 是 J35/J43 中英混杂目标-gap 题，不属于被排除的多意图族；评分器机械上仍
称 `wrong_gap`，语义上却是新错误歧义，故按预承诺淘汰。0.275 仍有一个 multiple；0.300 是最低的
clean 点，且比更高 clean 点多救回 1 题，最终 `MINIMUM_SCORE=0.300`。唯一救回是
`J35.dev.v3.code-switch` 从 wrong gap 到精确 `REALTIME_EVENT_CATALOG_CONTRACT_MISSING`。

**最终结果：**六层成为产品选择 `263/336`、参数 `201/201`、离线终点 `62/77`、错误恢复 `5/5`、
selection/terminal pass^4 `263/336、62/77`、安全 `PASS/0`，不稳定题 0。当前 HEAD 全 336 机械
失败归因 `44 no_candidate / 14 wrong_gap / 13 wrong_product / 3 ambiguous` 变为
`44 / 13 / 13 / 3`；排除 12 道多意图后为 `44 / 14 / 8 / 0 → 44 / 13 / 8 / 0`，失败基数
`66→65`。派发背景的 43 个 no-candidate 全部仍未恢复；当前第 44 个是报表闭环后新增的 J36。
旧 240 题 240/240，逐题候选、gap、reason、fallback disposition 与 top score 差异 0；receipt 的
`minimum_score` 按设计 `0.375→0.300`，不伪称字节不变。口语省略仍 `0/12`、只描述业务目的仍
`1/13`，因此安全阈值下词法路线对这两族无效。

**泛化边界：**调用方语料来自题集之前的全量产品文档，且 selector、负向词、多意图和 fail-closed
判据均未修改；这部分不依赖具体题面。偏拟合风险仍高：0.300 由同一公开 development 分布选择，
净收益只落在 J35 一题，中文 2/3 字 gram 与 IDF 又会随文档频率改变。未查询留出前只能称保守候选，
不能称泛化已证明。本线新增 caller-recoverable raise site 0 个；最终全仓错误审计
`1073 = 269 A / 434 B / 370 C`。技术债清单复核后无新增或关闭条目。

## 臂 C：宿主 LLM 盲选能力目录实测（2026-08-16）

**书面提案与盲选纪律：**本线不改 recognizer、题集、评分器、产品行为或运行路径，只回答“宿主
LLM 仅拿公开能力目录时能选到什么”。先从 development 导出 336 个 `case_id + prompt`，再通过公开
`agent-catalog categories → category → describe` 导出 8 个分类、229 个 selector 的完整三层目录；选择
文件写满 336 行后才读取预期和分数，锁定 SHA-256 为
`d5355046f3714ec1541856b6f713ebb75136088cb1fa8f4bf94084b94806c159`。固定映射插件只按 case id
回放选择，4 个 trial 均复用同一映射且声明 `network_called=false`；evaluator 与六层判据一个字未改。
未运行或读取 holdout/final/all、sealed payload 或 key，生产 HTTP 与 socket network 均为 0 次。

六层同条件 development 对照为：

| 层 | 臂 A recognizer | 臂 C 盲选目录 | 变化 / 说明 |
| --- | ---: | ---: | --- |
| 首次产品选择 | `260/336`（77.38%） | `172/336`（51.19%） | `-88`，`-26.19pp` |
| 已到达卡参数可填 | `198/198` | `167/167` | 两边均 100%；分母因到达路由不同不可直接当召回比较 |
| 离线终点 | `64/88`（72.73%） | `8/88`（9.09%） | `-56`；臂 C 不能表达目标 gap 是主因 |
| 错误恢复 | `5/5` | `5/5` | 无变化 |
| 重复可靠性 | selection/terminal `260/336、64/88` | `172/336、8/88` | 两边均 `pass^1=pass^4`，unstable 0；固定映射不代表真实 LLM 随机稳定性 |
| 安全遵守 | `PASS / 0` | `PASS / 0` | 两边生产 HTTP、socket network 均 0 |

臂 A 使用 44 次本地 discovery batch、耗时 9.014 秒；臂 C 使用 4 次外部 selector 子进程调用、耗时
1.059 秒，外部 selector 网络 trial 为 0。该成本只反映一次固定映射回放，不包含真实模型推理成本。

八个 development 扩题族逐类结果为：

| 题类 | 臂 A | 臂 C | 变化 |
| --- | ---: | ---: | ---: |
| 口语省略与语气词 | `0/12` | `9/12` | `+9` |
| 只描述业务目的 | `1/13` | `7/13` | `+6` |
| 多轮追问首轮 | `1/12` | `4/12` | `+3` |
| 反向否定 | `1/12` | `11/12` | `+10` |
| 错别字 / 拼音 | `3/12` | `6/12` | `+3` |
| 中英混杂 | `10/12` | `3/12` | `-7` |
| 跨产品多意图 | `1/12` | `5/12` | `+4` |
| 目标 gap | `3/11` | `2/11` | `-1` |

逐题交叉为臂 C 独赢 38、臂 A 独赢 126、共同通过 134、共同失败 38。臂 C 的 164 个首次选择失败
机械分解为 `42 wrong_product + 69 wrong_gap + 33 no_candidate + 13 ambiguous +
4 multiple_intents_missing + 3 wrong_intent_candidates`。这组失败证明当前实验同时测到了三种不同问题：

- Analysis event/funnel/retention/property/scatter 与 segment evaluate 的目录只有 raw operation，评分目标却是
  kind-specific Spec/产品卡；语义上选到同域 operation 的 42 题仍被正确判为产品层不等价。
- 外部 selector 协议只接受 0--5 个目录 selector；0 个只能变成通用
  `EXTERNAL_SELECTOR_ABSTAINED`，不能表达公开预期中的精确 gap code，也不能表达“一个已知 selector 加一个
  未登记 gap”的部分多意图。69 个 `wrong_gap` 和 4 个 `multiple_intents_missing` 主要暴露的是这一
  surface 缺口，不是描述措辞不足。
- 盲选主动输出 `none` 共 96 题；按 scorer 的精确 route identity 反查三层目录，96/96 都没有对应产品
  selector 或本来就是能力缺失目标。另有 `user_journey`、`table_lineage` 等整条产品只以多个底层
  operation 出现在目录，宿主选多个后被判为歧义。J35 更直接暴露事实冲突：目录把
  `app.realtime_event.list` 描述为已验证可执行读，但动线仍要求
  `REALTIME_EVENT_CATALOG_CONTRACT_MISSING`。

**真正由目录描述救回的证据：**臂 C 在已有完整 composite 描述的口语、业务目的、否定和多意图题上
稳定救回 38 题。起作用的不是 selector 名，而是描述中的目标、返回物和相邻边界，例如
`analysis_context` 明列事件/属性/指标/模板，`order_split_trace` 明列 App/单日/TraceID 与拆单，
`saved_analysis` 明列精确引用且排除模板/看板，`segment_snapshot` 与 `segment_members` 分别声明
“不读取成员”和“逐人属性”。这证明高信息量的产品描述能覆盖词法 recognizer 完全失败的语言形态，
但不能证明当前目录 surface 已足够替代 recognizer。

**效度与外推边界：**操作者不是干净的外部模型：已读过仓库和本题背景，自动记忆中有上一轮高层结论；
为定位导出入口还在锁定前看到了少量 evaluator route 常量，且同一 J 编号的七个问法可成组观察。没有在
锁定前读取 `expected`、`journey-targets.json`、动线状态列或任何分数，但不能证明上述先验完全没有影响。
本次 `51.19%` 应视为一个有污染的上界；主观预算为约 `3--10pp` 的可能高估，不能当统计置信区间。
另外这只是一个模型、一次人工批处理式长上下文选择；四次 trial 是固定文件重放，不覆盖模型、提示、温度、
上下文窗口、语言能力、成本和 JSON/tool-use 可靠性差异，因此不能外推到任意调用方 LLM。

**方向裁决：**当前目录加宿主 LLM 不能直接替换 recognizer，机械总分和目标 gap 终点都大幅退化；上线
替换没有证据。但不再为开放自然语言继续堆手写 NLU 词表：困难语言族的对照表证明这条投资回报低，而完整
composite 描述已能让宿主模型跨过词法盲区。下一步优先把现有产品卡、plan-only Analysis compiler、
metadata/export/asset 产品与精确 gap identity 从同一权威来源完整投影进目录，并让 selector 协议显式返回
gap；达到目标身份 parity 后，再用随机化 case id、单题隔离和新模型会话重测。现有 recognizer 在此之前
保留为离线确定性兼容入口，不扩成开放语言理解层，也不把 LLM 接入 SDK 运行路径。

本线产品、动线、operation 计数均为 `+0`；新增 caller-recoverable error site 0 个。技术债清单新增
“agent-catalog 与 Agent 产品/gap 身份不共源”一项，退出条件是不造第二套 registry 的前提下实现目标
身份 parity。

## 报表目录与订阅的写解锁（2026-08-16）

**提案与控制流裁决：**工作底稿位于 ignored `tmp/codex/write-reports/proposal.md`。先对与 census
快照 hash-matched 的公开 bundle 做零业务请求复核，再发送任何生产请求。旧报表创建入口已找到：
`POST /turbo_engine/api/v2/datamanageconfig/report/update/`；create body 为
`name/remark/subject/app_id/project_id/config`，同一路由以 `id/name/subject/report_group_id/config/
remark/is_delete=1` 删除。订阅 create/delete 为已知 v3 `/subscribe/create/` 与 `/subscribe/delete/`。
静态控制流同时证明订阅父值必须来自 v3 conftemplate，所以父报表创建/删除分别登记
`/conftemplate/template/create/` 与 `/conftemplate/template/edit/`。`/subscribe/test/` 会产生真实通知，
不属于任何产品入口，本轮没有调用。

**标记与失败关闭：**旧报表和 v3 父报表把 `GSDK-<12 hex>` 放进 `remark`；订阅没有 remark，故同时
放进 `name` 与 `wildcard_name`。这三个字段都不改变报表计算或订阅收件人语义，并已由 list/detail
原样 round-trip。上游没有拒绝紧凑 marker 格式。第一次把旧 v2 报表 ID 传给订阅 create 时，上游
明确拒绝“找不到报表”；SDK 没有重放、换格式或无 marker 降级，而是改用前端已证明的 v3 父类型。
删除前旧报表走 detail、订阅与 v3 父项走完整 list，均要求读回 marker；缺 marker 为 caller/2。
删除 acknowledgement 后仍可见属于写后读回不确定，返回 upstream/3 且不自动重放；响应合同或本地
policy 损坏仍为 local/4，没有新增退出码类别。

**非空 item 合同：**旧报表 list 与 detail 同次观察并登记 14 个字段：`app_id`、`cid`、`config`、
`create_time`、`create_user_id`、`create_user_name`、`id`、`modify_time`、`name`、`project_id`、
`remark`、`subject`、`update_user_id`、`update_user_name`。订阅 list 观察并登记 23 个字段：
`app_id`、`category`、`cid`、`create_time`、`create_user_id`、`create_user_name`、`end_time`、
`hourly_send_periods`、`id`、`modify_time`、`name`、`project_id`、`project_name`、
`report_conf_template_id`、`report_type`、`send_way`、`start_time`、`subscribe_content`、
`subscribe_selected_columns`、`subscribe_status`、`update_user_id`、`update_user_name`、`wildcard_name`。
所有观察字段均公开投影；未知新增字段仍省略并形成结构化 drift，删除/类型变化 fail-closed。

**五面与 Plan 裁决：**读产品 `gravity-insight.report-directory.v1` 与
`gravity-insight.report-subscriptions.v1` 均有 Core / CLI / SDK / Plan / Agent；目录完整分页后用全局预算
内的有界 worker pool 读取 detail，订阅完整分页读取。Agent 卡共用 `gravity.agent-call-bound.v1`，
已知输入 1 次，未知能力 2 次。两条写产品共用 `gravity-insight.report-mutation.v1`，有 Core / CLI /
SDK / Agent，且 `natural_language_auto_execute=false`、发现后固定 dry-run / execute 两次交接。

报表写与订阅写的 Plan 面逐条记“设计不适用”，引用 Segment 的同一窄例外，并分别满足三条件：
(1) create/delete 是持久化 effect，必须显式确认、不可自动重放、删除前读 preimage/marker、写后读回，
Plan v1 的无副作用数据节点合同没有这些语义；(2) Core、CLI、SDK 和 Agent 两步交接已能独立完成任务，
没有因为缺 Plan 减少调用方任务集合；(3) 本节和 `docs/analysis-journeys.md` 都显式登记例外及边界，
将来 Plan 有 mutation effect/confirmation/replay 合同时可单独撤销。读产品不是例外，正常进入 Plan。

**生产请求账本与零残留：**所有 7 次真写之前都执行了同类 dry-run，均
`offline=true/network_called=false`；真写 `attempts=1`、无 mutation retry，低于 15 次上限。UTC
`2026-08-15T23:35Z` 至 `23:44Z` 的 receipt 复算为 **39 次 HTTP = 32 read + 7 write**，transport
均为 HTTP 200。只有首次 App 解析按默认完整读取走了 `app.list` 5 页；目标报表/订阅列表没有额外翻页，
没有日期窗可扩，也没有换 App 追数据。

- Read 32：`app.list` 5；`report.report.list` 6；`report.report.detail` 3；
  `report.subscribe.list` 8；`report.multidim.template.mine.list` 7；
  `report.my_template.detail` 3。
- Write 7：`report.report.update` 2（create/delete）；`report.subscribe.create` 2（旧父类型被拒 1、
  v3 父成功 1）；`report.subscribe.delete` 1；`report.template.create` 1；
  `report.template.update` 1。

实际对象序列为：旧报表创建成功；旧父类型订阅 create 被拒且未创建对象；v3 父报表创建成功；disabled、
空收件人订阅创建成功；订阅删除；v3 父报表删除；旧报表删除。v3 父 create/delete 的即时 list 曾因
上游最终一致性返回写后读回不确定，SDK 按 upstream/3 失败关闭且没有重发写；随后独立完整 list 分别
确认创建只出现 1 项、删除后消失。最终 UTC `23:44Z` 的三次独立完整读回为：
`report_directory.item_count=0`、`report_subscriptions.item_count=0`、v3 自有模板 `data.list=[] /
total_number=0`。三类列表中均无 `GSDK-` marker，故生产环境零残留。

**台账与质量：**两条原缺失读动线各因非空 schema 转闭环，`49 = 37 / 1 / 11` 先变为
`49 = 39 / 1 / 9`。沿用 Segment 的独立任务口径，创建/删除可复用报表与创建/删除订阅各新增 1 条
闭环写动线；v3 父报表只是订阅实现脚手架，不另计。因此最终为 `49 + 2 = 51`、
`39 + 2 = 41`，即 **`51 = 41 / 1 / 9`**。新增 4 read + 5 mutation operation，operation
`194 + 9 = 203`、stable `185 + 9 = 194`。本线新增 caller-recoverable raise site **12** 个，
全部 A 档：全仓从 `1061 = A257 / B434 / C370` 变为 `1073 = A269 / B434 / C370`。技术债清单已
复核；实现按 report core/contract/support/CLI 分域，质量 ratchet 没有放宽，未新增可由当前源码证明的
结构债。

**合并评测收口：**两条读取动线在公开 target registry 中由目标 gap 切到产品目标，evaluator 只新增
`selector=composite:report_directory` 与 `selector=composite:report_subscriptions` 两个精确 matcher；
评分算法、层定义和阈值未改。write-reports 已删除这两个 gap recognizer，合并时同步从 Arm B 的既有
gap 查询清单移除相应失效引用；索引来源和 `0.375` 阈值均未改变。历史 NL 回归矩阵漏了 registry 的
J25 分群成员，故原 J25–J47 的 23 条 query 仅把编号改引 J26–J48，J01–J24 不变；47 条中英文 query
列与改前逐字相等。未被任何测试引用的旧连字符版重复 fixture 已删除，现行矩阵逐行校验 ID 存在且
标题等于 registry 的 `ledger_title`，从而不再维护独立动线编号/标题真值。

订阅 recognizer 新增的是产品级正向证据集合：英文仍要求 report + subscription，中文要求“报表”与
“订阅/订了/订的/定时发/定期发/自动发”之一共同出现；没有写死题句或词序。目录 recognizer 没有删除
负向词，并以同一订阅证据排除抢占。三条新增同义问法“我订了哪些报表”“有哪些报表会定时发给我”
“请查看定期发送给我的报表”均首卡到 `composite:report_subscriptions`，目录题仍只到
`composite:report_directory`。development 336 题从 `261/336、188/188、73/91、5/5、selection/
terminal pass^4 261/336 与 73/91、PASS/0` 变为 `262/336、201/201、61/77、5/5、selection/
terminal pass^4 262/336 与 61/77、PASS/0`；不稳定题仍为 0、本地写交接仍为 29、生产 HTTP 为 0。
14 条报表题的选择结果从 `12 target_gap + 2 wrong_gap` 变为 `13 correct + 1 no_candidate`，所以净提升
1 只来自两条闭环目标迁移与订阅可达性修复；参数/终点分母变化是正确产品卡替代 gap 的层间迁移。

## Agent Catalog 产品事实 parity 与改进臂 C（2026-08-16）

**提案与范围：**工作提案位于 ignored `tmp/codex/catalog-parity/proposal.md`。本轮只把既有 Agent
产品卡、compiled manifest 与登记 gap 投影为同一个离线目录；没有改 recognizer、Arm B 阈值、题集、
评分函数或 SDK 执行路径，也没有运行 holdout/final/all。生产 HTTP 和 socket network 均为 0。

**canonical 全集与覆盖推导：**安装时可枚举的产品卡不是另一份手写表，而是从原 owner 逐个物化：
26 张 `composite_capability_inventory` 卡，加 15 张既有非 inventory 卡——Analysis Spec 6（generic/跨期
身份及 event/funnel/property/retention/scatter）、Segment rule 1、Segment mutation 1、Report mutation
1、User Journey 1、Material Asset 1、Metadata Search/Table Lineage 2、受治理 Export 2——合计
`26 + 15 = 41`。旧目录 `229 = 26 product + 203 raw operation`，所以覆盖为 `26/41`；新目录
`255 = 41 product + 203 raw operation + 11 registered gap`，覆盖为 **`41/41`**，缺项 0。新增的
mutation 卡不在 336 题目标里，说明全集不是按题目答案裁剪。workspace recipe/SQL product 是所选
workspace 的动态卡，不属于安装时静态全集；当前未选择 workspace 时仍由既有
`WORKSPACE_SQL_PRODUCT_NOT_CONFIGURED` 条件 gap 表达，未伪造静态产品。

11 个 gap 全部直接来自 `registered_unavailable_gaps()`，category summary 与 describe 都暴露精确
`gap:<CODE>` selector、`gap_code/reason/next_action`，并固定 `identity_kind=capability_gap`、
`catalog_status=registered_unavailable`、`executable=false`。台账当前 9 条完全缺失、1 条部分闭环均在
其中；第 11 条是 workspace 未配置 SQL 产品的环境条件 gap。调用方据 `identity_kind` 区分可执行
`product`、仅专家使用且 `product_equivalent=false` 的 `raw_operation` 与不可执行 gap。

**状态冲突审计与保险：**修复前逐条对照当前 10 条未闭环动线和 203 个 manifest operation，只有 1 处
把不同层身份写成同一能力：J35 的 `app.realtime_event.list` 是已验证的“应用实时事件配置”raw 读，
而“Analysis 实时事件目录”仍完全缺失。其余 9 条没有目录项同时声称同一产品已执行。修复后 J35 raw
项保留 `executable=true`，但明确为 `raw_operation/product_equivalent=false`；并列的精确产品状态是
`gap:REALTIME_EVENT_CATALOG_CONTRACT_MISSING`，故冲突 `1 → 0`，没有牺牲 raw 读取能力。
`validate_catalog_parity` 双向比较 41 张 owner card、203 条 manifest operation、11 个 gap 与目录身份和
executable flag；测试还解析动线台账，要求当前未闭环目标 gap 全在目录中。反事实测试复制目录并把
`app.realtime_event.list.executable` 人为从 true 翻成 false，确定失败为
`catalog operation executable-status drift: ['app.realtime_event.list']`，证明门禁不是只测 happy path。

**改进盲选纪律：**development 的 336 题在 selector 可见前用题面清单 SHA-256
`ef463aec89f8ef2b5f6d0aaf818d852b12da623df6e8c076e77b06fcb596f3f6` 作确定性随机种子；每轮按 journey
去分组，机械断言相邻题不属于同一 journey，再按打散后序号改成 `q-0001...q-0336`。selector 只收到
匿名 ID、prompt 与 10 类/255 selector 的目录。整批选择写满 336 行、12 个多意图均明确后才评分；
锁定文件 SHA-256 为 `a0aeebde2216a0ae411224624baf71eab6a7a15a2174f786c3f08c835acaf242`，固定插件
SHA-256 为 `9e7304427c46bc6b1686d6f8b73864ac16c88b79a86501a1145aefe1161353e6`。4 trials 只回放同一映射，
`network_called=false`，不代表真实模型随机稳定性。

| 层 | 臂 A recognizer | 改进臂 C 目录盲选 | 变化 |
| --- | ---: | ---: | ---: |
| 首次产品选择 | `260/336`（77.38%） | `334/336`（99.40%） | `+74`，`+22.02pp` |
| 已到达卡参数可填 | `198/198` | `248/248` | 均 100%，分母不同 |
| 离线终点 | `64/88`（72.73%） | `88/88`（100%） | `+24`，`+27.27pp` |
| 错误恢复 | `5/5` | `5/5` | 无变化 |
| 重复可靠性 | `260/336、64/88` | `334/336、88/88` | 均 `pass^1=pass^4` |
| 安全遵守 | `PASS / 0` | `PASS / 0` | 生产 HTTP / socket 均 0 |

| development 扩题族 | 臂 A | 改进臂 C |
| --- | ---: | ---: |
| 口语省略与语气词 | `0/12` | `12/12` |
| 只描述业务目的 | `1/13` | `13/13` |
| 多轮追问首轮 | `1/12` | `12/12` |
| 反向否定 | `1/12` | `12/12` |
| 错别字 / 拼音 | `3/12` | `12/12` |
| 中英混杂 | `10/12` | `12/12` |
| 跨产品多意图 | `1/12` | `10/12` |
| 目标 gap | `3/11` | `11/11` |

臂 C 的 failure class 只剩 2 个 `wrong_intent_candidates`。两题分别要求“已同步表沿革 + 当前 schema”
和“用户事件文件 + 素材原视频”，选择已如实锁成 `product + gap`；冻结 scorer 的
`candidate_selectors` 对 gap journey 没有 selector，却又要求 observed candidate 数等于两条 journey，
所以在不改评分逻辑下机械不可通过。没有为了拿满分删除 gap 或把它伪装成 product。

与上一轮 `172/336` 相比净增 162。旧失败中的 `42 wrong_product + 69 wrong_gap + 33 no_candidate +
4 multiple_intents_missing = 148` 属目录/协议不可表达面；扣除本轮仍不可由冻结 candidate-set 表达的两条
混合多意图，**146/162** 可作为结构缺口被移除的机械解释，但没有旧逐题映射，不能冒充逐题因果证明。
其余 16 题来自第二次整批判断与呈现条件共同变化，无法在本实验内把随机化、匿名化和模型判断方差拆开；
随机去分组本意是减少泄漏，不应事后当作正向增益来源。

**效度与贴题自查：**随机化、去分组和匿名 ID 已移除上一轮最明显的 J 编号/相邻七问泄漏；主观高估预算
由 `3–10pp` 收窄为约 **`1–4pp`**，仍不是统计置信区间。操作者在实现前已读过仓库产品事实、公开 target
registry 与 evaluator route 常量，因此不是干净外部模型；这项先验仍可能抬高语义选择。代码侧没有把任何
题句、J 编号或新增同义词写入描述：15 张补入卡全部复用原 card owner，11 个 gap 全部复用原 registry；
最接近“贴题”的地方只在本次一次性选择文件，而它位于 ignored `tmp/`、不进入 SDK。产品、动线、operation
计数均 `+0`；新增 caller-recoverable error site 0 个。技术债中的 catalog 共源项按退出条件关闭。

**验证：**`unittest discover` 为 **1072**（基线 1068，+4），`pytest` 为 **1072 passed / 2939
subtests passed**，文档测试为 **4 passed**；compiler 仍为 203 operations / 11 manifests，quality、CLI
help 与 `git diff --check` 全部通过。caller-recoverable 全仓审计为 `1076 = A269 / B434 / C373`，与本轮
基线快照完全相同，因此本线新增点为 `0/0`、A 档率按约定为 100%。

## 十分钟主路径生产复验与文档收口（2026-08-16）

**提案与纪律：**从 README 和文档索引开始，按现有十分钟指南模拟首次调用方；事件和指标只从
metadata 或产品卡 schema 取得，固定一个文档已有的单日窗口，不换 App、不扩窗、不翻页、不重试。
只修改文档与 `scripts/generate_agent_skills.py`，不改 product、operation、CLI 参数、recognizer 或评测
装置。完整命令记录保存在 ignored `tmp/codex/docs-primary-path/revalidation.md`，不作为长期事实源。

**实走结论：**12 条主路径命令、3 次生产 HTTP 后取得 `analysis.event.query` 的真实 governed result。
请求账本为：认证 POST 200、`app.list` GET 200、事件分析 POST 200；均 attempt 1，列表只读 page 1，
日期保持单日。`app.list` 虽投影出已登记 id/name，却以 `contract_changed`、exit 0、`ok=true` 和
action-required diagnostics 的组合返回；本次仅因同一 App 也存在于 2026-08-13 成功本地 catalog 才继续
复验，不能把它写成普通自动化可安全忽略的状态。最终聚合值不进入文档，也不外推为业务未发生。

**剩余卡点：**旧十分钟生成指南要求从 `category analysis --limit 20` 选择一个实际不在首 20 条中的
产品 selector，属于文档/生成器缺口；已修为直接三层 describe 后再选值。冷 metadata 目录只有
`sync --all-apps`，没有选定 App 的有界同步，因此全新用户不保证在固定十分钟或小 HTTP 预算内取得物理
事件，属于本轮不改的产品 surface 缺口。凭据在本轮已就位，不是阻塞；分析日期仍是调用方必须提供的
天然业务输入。

**文档与生成器结论：**README、索引和 Agent 工作流现在把三层 `agent-catalog` 作为首要全量发现入口，
并显式写出当前 `257 = 205 operation + 42 product card + 10 gap`。分群、报表和订阅写共用
`dry-run → 人工确认 → 同参数 execute`，在工作流、CLI 参考和生成任务指南均可达；调用方语义上下文与
派生指标各有可复制的虚构最小示例。生成器从手摘 Analysis 卡改为消费 canonical 产品卡、compiled
manifest、export contract 和 workspace/derived schema version，产物由 4 篇增为 7 篇。canonical
mutation 卡仍只物化每个 family 的默认 create 动作，不枚举全部 CLI action；文档列出完整动作并把该
机器输入缺口保留为已知限制，不修改产品卡。

本轮不新增产品动线、operation、stable 能力或 caller-recoverable error site：`51 + 0 = 51`，
`42 / 1 / 8 + 0 / 0 / 0 = 42 / 1 / 8`，operation/stable 仍为 `205 / 196`，新增错误点 `0/0`。
验证为 unittest **1076**、pytest **1076 passed / 2955 subtests passed**、文档测试 **4 passed**、
compiler **205 operations / 11 manifests**，quality、生成器 check、CLI help 与 `git diff --check` 均通过。
caller-recoverable 审计为 `1075 = A271 / B434 / C370`；本轮新增点为 0，故新增 A 档仍为 `0/0`。

## Protected selector 桥接与 read envelope 语义收口（2026-08-16）

**提案与安全边界：**工作提案位于 ignored `tmp/codex/bridge-and-envelope/proposal.md`。selector 只用
测试内即时生成的 authenticated synthetic protected fixture；没有运行 holdout/final/all、读取真实 key、
查看或解密 sealed suite。`app.list` 合同核对使用 4 次生产 HTTP 后停止，未逐 operation 在线试错。

**selector 根因与修复：**父 evaluator 用 UTF-8 编码 subprocess stdin，但 Windows 子 Python 默认把
`sys.stdin` 当 GBK。普通 development locked-replay 插件读取后不需要重新发布题面，乱码仍可能形成合法
JSON；protected one-shot bridge 则在 `json.load(sys.stdin)` 后立刻 canonicalize 为 UTF-8 并写 request，
GBK 解码产生的 surrogate 会在 `encode("utf-8")` 处退出，所以 request 尚未落盘。两种 loader 最终都产出
普通 JSON dict；根因不是解密后 case 结构、临时路径或不可序列化对象。桥接器现显式给子 Python 设置
`PYTHONIOENCODING=utf-8`。合成 protected fixture 经真实 loader→blind questions→subprocess→catalog
selection→原评分链跑通；固定 stub 还会重新 canonicalize request，故能覆盖原失败点。非零退出现在报告
`stage=subprocess_execute`、exit code 与限长单行 stderr；例如合成 exit 7 明确暴露
`synthetic bridge crash`；超时与非法 JSON 也分别标明 subprocess/response-decode stage 并保留限长
stderr，不再只有通用错误。

**`app.list` 合同判定：**一次 `page_size=1` shape 只观察到 `sub_package_list=null`，状态为 success；
同页 `page_size=20` 的 7 行则证明该字段当前为 `null | list[string]`，list 长度为 0 或 1，未观察到 object
item。v3 只把字段名加入 `item_keys`，没有登记 `scalar_list_item_types`，执行器因此把 4 个 list 值归为
`uncontracted nested item containers`，形成 breaking `contract_changed`，且 `response_drift=None`。这是本地
合同登记漏项，不是上游本轮 breaking change；源合同升为 v4，精确登记 string-list，未知或混合 item 类型
仍 fail closed，没有改投影判据。

**统一的机械规则：**公共 read 的 `ok` 表示语义成功，不表示“函数/HTTP 已完成”。`success`、`empty`
及既有 `contract_changed_additive` 状态为成功集合；新增字段在当前 raw executor 继续保留原 `success/empty`
并写 `result_audit.response_drift`。其余状态均非成功。exit 0 只对应语义成功；caller 错误为 2，upstream
错误为 3，local/unclassified 为 4，breaking `contract_changed` 固定为 upstream/exit 3。raw read 现显式
带派生 `ok`；breaking drift 同时生成 `CONTRACT_CHANGED/upstream/retryable=false/next_action`。resolver 只有
在 execute 已返回非成功结果时添加 `execution_failed`，并携带该结构化 error；empty/additive success 不再
产生该 diagnostic。batch、raw CLI 与 resolver 共用同一成功判定/退出映射。

**离线同类盘点与计数：**当前私有 OperationCatalog 快照离线筛 `probe.status=contract_changed` 为
**1 条：`app.list`**；提交内 probe evidence 另有 `report.multidim.query` 的 additive 记录，不属于 breaking
矛盾。旧代码结构上会让任意 raw operation 的 breaking status 被 resolver 当成功，修复覆盖全部 205 条
operation；已有 evidence 能证明实际命中的清单只有上述 1 条，不能把“潜在影响面”冒充“已发生数量”。
修复后当前已知矛盾清单为 0。产品/动线/operation/stable 均不新增：`51 + 0 = 51`、
`42 / 1 / 8 + 0 / 0 / 0 = 42 / 1 / 8`、`205 + 0 = 205`、`196 + 0 = 196`。技术债清单已复核；共享
状态原语有 raw/model、batch、CLI 和 resolver 多个调用点，client SLOC ratchet 从 1092 收紧到 1087，
未新增活动结构债。

**生产 HTTP 账本：**共 **4 次**。① authentication POST，HTTP 200，attempt 1；② `app.list` GET，
HTTP 200，`page=1/page_size=1`，响应后本地 shape 摘要器处理 null 失败；③ 相同 `app.list` GET，HTTP 200，
显式作为本地诊断恢复重试，证明首行字段为 null/success；④ `app.list` GET，HTTP 200，
`page=1/page_size=20`，一次取得当前 7 行 shape 并证明 null|string-list/contract_changed。所有 SDK 请求均
`attempts=1`；没有自动 HTTP 重试、翻页、换 App、扩日期窗或其他 operation 请求。

caller-recoverable 审计仍为 `1075 = A271 / B434 / C370`；本轮只增强一个既有 selector ValueError 的
上下文，并由 breaking status 生成返回值 ErrorDetail，没有新增 raise site，因此新增错误点/A 档为
`0/0`。验证为 unittest **1077**、pytest **1077 passed / 2955 subtests passed**、文档测试 **4 passed**、
compiler **205 operations / 11 manifests**；quality、CLI help 与 `git diff --check` 均通过。

