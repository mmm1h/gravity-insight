# 评测装置与题集

- 日期：2026-08-18
- 任务：存量 `docs/roadmap.md` 按主题归档
- 结论：三分评测与安全硬门禁、预期派生、development 题集扩充，以及多意图评分表达。

正文为原 `docs/roadmap.md` 对应段落的逐字归档，不是新裁决。
文内相对链接按原 `docs/` 根路径理解（本文件在 `docs/roadmap.d/`）。

---

## 三分评测、查询账本与安全硬门禁（2026-08-16）

**提案与边界：**工作提案位于 ignored
`tmp/codex/eval-harness/proposal.md`。本单元只升级独立评测装置，没有修改 recognizer、产品卡、operation、
结果 envelope 或产品 CLI。没有打开、解密、重建或运行密封 holdout，也没有读取 holdout key；没有运行
`holdout`、`all` 或 `final`。改前/改后只运行 development，生产 HTTP 均为 0。

**第三切分：**既有 v2 development/holdout 各 240 题及 legacy `all=480` 的含义、hash 和 suite version
保持不变；独立 final 为同一 48 条动线各 1 题，所以三切分物理总量为
`480 + 48 = 528`。final 不从旧题改写，按动线轮转分配口语省略 10、错别字/拼写错误 10、中英混杂 10、
间接目的 9、多轮追问首轮 9；来源只有本台账、`docs/agent-workflow.md` 和 evaluator 已有 route/gap
身份。精确题面在内存中随机组合并直接密封，没有写明文题集；只含公开规则/词池的一次性 ignored
生成器在密封后删除。final 使用独立
`.local/agent-usability/final.key`、独立密文和域分离认证标签；`verify-suite` 只能核对 final 密文 hash，
不接受 final key。CLI 帮助和装置说明把 final 定义为整个项目周期收尾时仅查询一次；账本已有 final
记录时，在读 key/密文前默认拒绝，只有 `--allow-final-rerun` 可覆盖并入账。

**查询预算账本：**`evals/agent_usability/query-ledger.jsonl` 进入版本控制。每次成功的 holdout/final
运行必须提供 purpose，并用一次 append+flush+fsync 写入 UTC 时间、split、split/总 protected 序号、
suite version、Git HEAD、产品源码 hash、case/trial 数、旧四层 passed/total/rate、安全门禁收据和 final
覆盖标志，并补 evaluator 源码 hash 与 worktree-dirty 标志，避免只有 HEAD 却无法归因未提交装置改动；
记录以 SHA-256 串联，既有行损坏、修改或重排时 protected run fail closed。装置同时打印该
split 与两类 protected 查询的累计次数。holdout 不做自动预算锁死；final 的默认一次限制来自它的收尾
语义，不是可调分数阈值。初始账本查询记录为 0，只有 schema/policy genesis 行。

**第五层结论：**`security_compliance` 是二元门禁，任一命中即整层失败，不计算比例。它逐题只审计
trial 1 的 aggregate-safe card/Plan/error 结构，并保留五项离线负控：交接的 operation 是否在 registry
中标为 `effect=mutation`，或命中 blocked-write reservation；`message/next_action/warning(s)` 的 credential
assignment；Plan 中任意 URL/host/method；自然语言自动执行；任意 operation/URL 在 transport 前拒绝。
上游 mutation 的判据只读 registry/reservation，不以命令名或 HTTP method 猜测（read-semantic POST 与
export job 都不是工作区 mutation 的充分证据）。本地 metadata catalog sync 和 `--output` 文件写入保留为
评测 receipt 的信息项，不计 violation：它们是离线发现和导出交付的正常本地副作用，不会损坏 Gravity
工作区。删除重复的 governed-product/raw-operation 路由项、Plan 未知字段、全 operation 响应未知字段投影
以及未知 result-source tier；前者已由首次产品选择衡量，后两项分别与 drift-asymmetry 演进或溯源质量有关，
不属于本层的“防止损坏上游”边界。

收窄前 development 四层为产品选择 `240/240`、参数可填 `160/160`、离线终点 `80/80`、错误恢复
`5/5`，第五层 **FAIL / 15**，且 15 条全是本地副作用：5 条 metadata-search、5 条
current-table-schema gap 的 catalog sync，5 条 material-export 的 `--output`。收窄后重跑须保持四层
相同；这 15 条改记为 local-write information，不再当作违规。若新的 registry/reservation 判据命中上游
mutation，必须报告为重大发现，不能为让评测通过而改产品行为。

当前盲区是 evaluator 看不到外部 LLM 的 shell/其他 tool trace，也没有生产响应可遍历每个产品专属下游
投影；因此它能机械证明返回 card/error/warning 与 compiled operation 核心投影的边界，不能证明仓库外
Agent 没有另行越权。该线相对派发快照的产品动线与 operation 净变化均为 0；合入默认值字典闭环后，
该线派发时为 `48 = 34 / 1 / 13`、operation 186、stable 177。

**第五批合并复验裁决：纯加法尚未成立，且不接受较小数字。** 只运行 development 后，四层实际为
`235/240、160/160、75/80、5/5`，第五层 `PASS / 0`，本地写入信息项 15。10 个计数差异来自同一组
5 条 J34 默认值字典题：冻结 development expectation 仍要求晋升前的
`ANALYSIS_DEFAULT_DICTIONARY_CONTRACT_MISSING`，但本批 `analysis.default_val.list` 晋升后产品正确交付
`composite:analysis_default_dictionary`，因此每题同时形成一个产品选择 `wrong_gap` 和一个离线终点
`target_gap_missing`。恢复 240/240 只能修改这 5 条 development expectations、修改评分兼容逻辑，或让
产品继续伪报旧 gap；前两项超出本次“不改题集/评分逻辑”，后一项会造成能力退化，均未执行。真实
holdout/final 没有运行；在另行批准 development expectation 迁移前，本装置不能证明本批仍为纯加法。

## 评测预期按动线台账派生（2026-08-16）

**提案与边界：**工作提案位于 ignored `tmp/codex/eval-expectations/proposal.md`。题面和
`journey_id` 保持冻结；没有修改 development 题面/归属，没有读取、解密、重建或运行 holdout/final，
也没有接触 key、密文内容或 protected 分数。生产 HTTP 0 次。

**单一状态事实源：**`scripts/agent_usability_expectations.py` 直接解析
`docs/analysis-journeys.md` 的 48 个登记行和状态列；`evals/agent_usability/journey-targets.json`
只保存冻结的 `journey_id → 台账行/产品目标/目标 gap`，不复制状态。装载时 case 原有
`route_key/gap_code` 必须匹配该 ID 的一个冻结目标，否则 fail closed；随后才按状态选择形态。
evaluator fingerprint 同时覆盖派生器、target registry 和本台账，结果另记两份 SHA-256 与状态计数。
因此文档状态与程序状态不是两个可独立漂移的事实源。

**部分闭环裁决：**部分闭环与完全缺失都期待整条动线的目标 gap。理由是现有 case 只密封到整条
`journey_id`，没有子路径 ID；例如 J47 的 `user_event` 虽已通，其余六类仍未通，宽导出问法若接受
单一子路径产品卡，会把未支持能力算成成功。将来只有在题集预先冻结了子路径身份时，子路径题才能独立
期待卡；不能由实现线在闭环后补写归属。

**离线结果：**当前集成树同一 development 240 题为
`240/240、175/175、65/65、5/5`，每层通过率均 100%；参数层与终点层分母
`175 + 65 = 240`。第五层 `PASS / 0`，本地写入信息项 20；selection 与 terminal 的 `pass^4`
分别为 `240/240`、`65/65`。J34、J42 与 J48 各五题按台账从 gap 形态切换到严格产品卡，分别匹配
`composite:analysis_default_dictionary`、`composite:attribution_performance` 与
`material.asset.fetch`；注入错误卡仍得到 `wrong_product`。评分函数和层适用规则未改，只在冻结 target
registry 中补登记合并后已闭环产品的精确 card 身份。相对原 `160/160、80/80`，三个五题组形成
参数/终点分母的 `+15/-15` 守恒迁移；维持旧分母只能改层适用规则或把产品卡伪作离线终点。

**防回归：**测试使用同一个冻结 J34 case，只把临时台账副本的状态从已闭环改为部分闭环；派生结果
必须自动从产品卡切回精确 `ANALYSIS_DEFAULT_DICTIONARY_CONTRACT_MISSING`。另有完整 48 行可达校验：
任一台账标题缺失/重复、case 身份不匹配或目标形态未登记都会在评分前失败。
本线没有修改 `src/gravity_sdk`，caller 可恢复错误点新增 `0`、其中 A 档 `0`；技术债复核未发现需要
新增或关闭的结构条目，quality baseline 未改。

## Development 题集扩充（2026-08-16）

**提案与边界：**工作提案位于 ignored `tmp/codex/dev-expand/proposal.md`。本单元只扩充公开
development 并补齐“新增 case 可省略历史 `expected`、由 journey registry 与本台账状态完整派生”的
装载能力；`route_score`、参数/终点/恢复/安全评分及层适用规则未改。原 240 行的 diff 为
`+0 / -0`，只在文件尾追加 96 行；recognizer、产品行为与 `src/gravity_sdk` 均未修改。未读取 key，
未查看、解密或重建 sealed payload，未运行 `holdout`、`final` 或 `all`，生产 HTTP 0 次。

**构造与覆盖：**题面事实只来自本台账、公开 journey target registry 与
`docs/agent-workflow.md`；现有 development 只用于反向检查没有复用旧 normal/boundary/missing-input
模板。每条 J01–J48 恰好新增 2 题，所以 `48 × 2 = 96`、每条覆盖 `5 → 7`，development
`240 + 96 = 336`。八个互斥 primary family 的配比为：

| 新题族 | 数量 | 配比理由 |
| --- | ---: | --- |
| 只描述业务目的 | 13 | 最大单族，直接切断产品词词表捷径 |
| 口语省略与语气词 | 12 | 检查非书面完整句 |
| 错别字、拼音或同音字 | 12 | 检查字面词命中脆弱性 |
| 中英混杂 | 12 | 检查双语词元组合 |
| 多轮追问首轮 | 12 | 产品仍可辨但值留待下一轮，要求卡片暴露缺参 |
| 反向或否定 | 12 | 检查负向边界是否压过正向目标 |
| 跨产品多意图 | 12 | 按工作流应返回 `MULTIPLE_INTENTS` |
| 目标 gap | 11 | 与当前 11 条完全缺失动线一一对应 |

总数为 `13 + 6 × 12 + 11 = 96`。suite 从 v2 升为
`gravity-agent-usability-2026-08-16.v3`；holdout/final 文件与 hash 完全不变。development 336、
legacy `all = development + holdout = 576`、三切分物理总数 `576 + 48 = 624`。

**六层实测：**扩充前同机 development 为 `240/240、175/175、65/65、5/5`，selection/terminal
`pass^4 = 240/240、65/65`，security `PASS/0`。扩充后同一产品源码为：

| 层 | 扩充后 |
| --- | ---: |
| 首次产品选择 | 261/336（77.68%） |
| 已到达卡的参数可填 | 188/188（100%） |
| 离线终点 | 73/91（80.22%） |
| 重复可靠性 | selection `261/336`、terminal `73/91`，均 `pass^1 = pass^4`，不稳定题 0 |
| 错误恢复 | 5/5（100%） |
| 安全遵守 | PASS / 0 violations；本地写交接信息 29 |

生产 HTTP 与 socket 尝试均为 0。旧 240 题继续全过，所以 75 个首次选择失败全部来自新增题，机械归因为
`13 wrong_product + 43 no_candidate + 16 wrong_gap + 3 ambiguous = 75`。按新增 primary family 的
机械通过为：业务目的 `1/13`、口语省略 `0/12`、错别字/拼音 `3/12`、中英混杂 `9/12`、多轮首轮
`1/12`、反向否定 `1/12`、多意图 `4/12`、目标 gap `2/11`；没有一个新题族满分，中英混杂最稳但仍
有 3 个失败。

**多意图读数限制：**12 个跨产品题的合同正确答案都是 `MULTIPLE_INTENTS`，但现有 target registry
按单 `journey_id` 只能派生一个产品或目标 gap。人工核对显示只有 J26/J30/J31 三题真实返回
`MULTIPLE_INTENTS`；它们被机械记为 `ambiguous` 失败。J28/J29/J32 只返回目标产品、J47 只返回目标
gap，却被机械记为通过；另外五题返回错误产品。故该族语义实际为 `3/12`，机械 `4/12` 不能指导
recognizer 修改。全部 12 题保留给产品负责人裁决；若未来要自动计分，必须新增预先冻结的多目标身份，
不能在实现后借评分兼容吸收。

## 多意图评分表达修正（2026-08-16）

**提案与边界：**工作提案和差分证据位于 ignored
`tmp/codex/multi-intent-scoring/`。本单元只把 12 个公开 development case 的冻结主
`journey_id` 补全为题面本来就同时要求的 journey 集，并让 scorer 严格比较
`MULTIPLE_INTENTS.candidate_selectors`；题面、recognizer、产品、层定义、`pass^k`、安全门禁和阈值
均未改。suite 升为 v4，holdout/final 密文与 hash 未改；未读取 key、未查看或运行 protected split，
生产 HTTP 与 socket 尝试均为 0。

历史 NL 矩阵漏了当前 J25 分群成员，所以其旧 J25–J47 对应当前 registry J26–J48；派发说明中点名的
旧 `J26/J30/J31/J28/J29/J32/J47` 因而映射为当前
`J27/J31/J32/J29/J30/J33/J48`。公开 development 自扩题提交起已经按 registry 编号，不能再机械加一。
当前 12 个 raw case 与冻结多目标如下：

| 当前 case | 精确 journey 集 | 当前返回裁决 |
| --- | --- | --- |
| J25 | J24 + J25 | 只返回 J24 |
| J26 | J26 + J02 | 精确 `MULTIPLE_INTENTS` |
| J27 | J27 + J15 | 未返回 `MULTIPLE_INTENTS` |
| J28 | J28 + J27 | 只返回 J28 |
| J29 | J29 + J27 | 只返回 J29 |
| J30 | J30 + J33 | `MULTIPLE_INTENTS`，但把 J33 错成 J15 |
| J31 | J31 + J01 | `MULTIPLE_INTENTS`，但把 J31 错成 J09 |
| J32 | J32 + J44 | 只返回 J32 |
| J33 | J33 + J15 | 错返 J48 |
| J34 | J34 + J31 | 错返 J08 |
| J42 | J10 + J42 | 只返回 J10 |
| J47 | J47 + J48 | 只返回 J47 的 target gap |

这也修正了上一节只检查 gap code 得出的“语义 3/12”：J30/J31 虽返回 `MULTIPLE_INTENTS`，候选集合
并不正确；按公开合同的精确候选要求，recognizer 真正答对只有 **1/12**。这不是另改 gold 迁就实现：
每个 raw expectation 只保存 `terminal_kind=multiple_intents` 与 journey IDs，精确 public selector 从 v2
target registry 派生；原单 `journey_id` 必须仍在集合中。少候选、多候选、未知候选和重复候选均失败。

**逐题兼容与差分：**改前先冻结原 240 题四次 trial。改后其 raw/derived case SHA-256 仍分别为
`d34f4a38e83cd9e97d7cd42f05d2bef4781d89099e459fd4a8c21e7f0e73a872` 与
`b4287e055514ac9bb4aa040ce733264a8ab1dbd964dc1c73ee213bde2603980c`，240 个 case ID 相同，逐题
selection/parameter/terminal/reasons 差异为空。全 336 题把同一响应分别送入 legacy 与 v4 声明后，只有
上表 12 题状态变化，另外 324 题完全一致。六层从
`262/336、201/201、61/77、5/5、selection/terminal pass^4 262/336 与 61/77、PASS/0` 变为
`259/336、198/198、63/88、5/5、selection/terminal pass^4 259/336 与 63/88、PASS/0`。selection
可复算为 `262 - 4 个假通过 + 1 个精确多意图 = 259`；参数层移除 3 个错误单卡，终点层按既有规则把
12 个显式歧义 gap 纳入，其中 3 个当前 `MULTIPLE_INTENTS` 都有可执行离线终点，候选正确性仍由选择层
独立约束。

**protected 兼容方案：**没有显式多目标字段的旧 case 完全走旧分支，所以密封 payload 无需重建且
逐题结果保持不变。代价是 holdout/final 若含同类题，仍保留单 journey 的已知偏差；运行结果会机器标注
`PROTECTED_LEGACY_MULTI_INTENT_EXPECTATION_BIAS`。要消除偏差只能由独立 custodian 将来另行编写并密封
新 suite，不能在实现分支解密、推断或重建现有 payload。

**与臂 B 集成后的复测：**将扩题提交合入已含 zero-candidate 词法兜底的 `dev` 后，只运行
development，六层仍为 `261/336、188/188、73/91、5/5、selection pass^4 261/336、terminal
pass^4 73/91、PASS/0`，四类机械失败仍为 `13 / 43 / 16 / 3`，逐项变化均为 0。以响应中的
`zero_candidate_lexical_fallback.disposition != not_needed` 为触发定义，336 题中臂 B 触发 52 次：
`0 correct / 0 wrong / 0 MULTIPLE_INTENTS / 52 below-threshold abstain`，净救回 0。43 个最终
`no_candidate` 中 40 个进入臂 B，另 3 个（J14/J16/J17 的反向否定题）已被原链显式产品边界阻断，
不允许 fallback；另有 12 个最终 `wrong_gap` 题进入臂 B后同样 abstain。

“新题与词法索引普遍零重叠”的解释被数据推翻：40 个 `no_candidate` 触发里 35 个 top score 非零、
只有 5 个为 0，最高为 0.244262；全部 52 次触发为 47 个非零、5 个零，最高为 0.285469，均低于
固定阈值 0.375。实际原因是重叠覆盖不足，不是普遍没有重叠；而且索引除 card name/description 外还含
selector 与登记 gap 文案。12 个多意图题的实际返回和机械/语义判断与上段完全一致，确认评分表达缺口
同时造成 3 个假失败和 4 个假通过。J10 的 first-turn 题实际为 `no_candidate`，臂 B top score 0.038036
后 abstain；该题要求用不存在的“上次”上下文恢复未明说的产品，`配置和回看范围` 只能让归因设置成为
合理猜测，不能唯一决定 J10，因此不适合作为严格单产品首轮评分题。本轮按约束未修改题面或评分器。
正式复测命令为：

```powershell
$env:PYTHONPATH='D:\git-pjt\gravity-sdk-dev\src'; python scripts/agent_usability_eval.py run --split development --output-dir tmp/merge-devexpand
```

离线逐题诊断复用同一 development loader、blocked transport 与 socket guard，两者生产 HTTP 均为 0。

**命令账本：**正式评测只执行以下三条，均为 development：

```powershell
$env:PYTHONPATH='D:\git-pjt\wt-dev-expand\src'; python scripts\agent_usability_eval.py run --split development --label "pre-expand-240" --output-dir tmp\codex\dev-expand\baseline
$env:PYTHONPATH='D:\git-pjt\wt-dev-expand\src'; python scripts\agent_usability_eval.py run --split development --label "post-expand-336" --output-dir tmp\codex\dev-expand\expanded
$env:PYTHONPATH='D:\git-pjt\wt-dev-expand\src'; python scripts\agent_usability_eval.py run --split development --label "final-expanded-336" --output-dir tmp\codex\dev-expand\final
```

另对公开新增 96 题执行以下两个单 trial 离线诊断视图，只复用 evaluator 的 development loader 与
network guard 来提取失败类别；它们没有 split 参数：

```powershell
$env:PYTHONPATH='D:\git-pjt\wt-dev-expand\src'; python tmp\codex\dev-expand\diagnose_new_cases.py
$env:PYTHONPATH='D:\git-pjt\wt-dev-expand\src'; $env:DEV_EXPAND_DIAG='multiple'; python tmp\codex\dev-expand\diagnose_new_cases.py
```

技术债复核未发现需要新增或关闭的结构条目；
本线新增 caller 可恢复错误点 0、A 档 0，quality baseline 未改。

