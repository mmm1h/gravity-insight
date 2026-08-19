> 归档材料：保留历史决策与取证，不代表当前接口或状态；当前入口见 docs/index.md。

# Agent 评测基线与留出集

- 日期：2026-08-18
- 任务：存量 `docs/roadmap.md` 按主题归档
- 结论：关键词路由不泛化、自然语言闭环判据、MCP 可行性、47 条动线重验、可重复基线与 key 托管。

正文为原 `docs/roadmap.md` 对应段落的逐字归档，不是新裁决。
文内相对链接按原 `docs/` 根路径理解（本文件在 `docs/roadmap.d/`）。

---

## 留出测试：关键词式自然语言路由不泛化（2026-08-15）

**这是本轮最重要的一次测量，它同时推翻了一个达标声明和我自己写的判据。**

### 测量

`nl-reachability` 线按新判据做完重验与修复，自报 baseline `6 / 7 / 19`
（中英都达标 / 只有一种语言 / 都不达标），修复后 `32 / 0 / 0`，零回归。
反自证纪律确实执行了：问法 19:55:02 冻结提交，源码 20:37:02 才动，中间隔 42 分钟，
且问法明确声明取自台账的分析师任务描述与调用方文档，未读 recognizer。**这些都属实。**

但我用**它没见过的 20 条问法**（同样的动线，我自己写，刻意短、口语化）做留出测试：

| | 修复前 `dev@23422c2` | 修复后 `codex/nl-reachability` |
| --- | --- | --- |
| 命中带候选 | 4 / 20 | **4 / 20** |

**一条都没变。** 逐条输出也完全一致，包括"新用户第二天还回来吗"和"用户都集中在哪些城市"
两条**返回 `success` 但候选是 `analysis.account_user.list` 这类 raw operation**
——路由错，两边一模一样。

### 判定

**冻结纪律挡住了浅层自证（从关键词表反抄问法），没挡住深层自证（调到那 94 句通过为止）。**
`32 / 0 / 0` 对那 94 句是真的，**只对那 94 句是真的**。

**这是我判据写得不够，不是执行线的问题。** 判据只要求"中英各一条自然语言问法"，
一个固定题集必然可以被拟合。同类错误本轮已经犯过两次
（"不换 App"挡住了分群发现、"不重试"挡住了发现链重跑），根源相同：
**我把约束写成了具体动作，而不是要达成的性质。**

### 判据再修正

Agent 面达标必须用**留出集**判定：题面在修复完成后由**未参与修复的一方**新写，
执行线事先不可见。冻结题集只能用于开发期自检，不能作为达标证据。

### 更重要的推论

**关键词式意图路由不泛化——这是我们自己的实测数据，不是行业趋势推论。**
真实用户打的是"登录数最近怎么样"，不是"帮我看看登录事件这周每天的次数，按渠道拆开"。
前者不含分析类型信号，关键词层拿不到；而一个拿到 tool schema 的宿主 LLM
处理这种语义匹配毫无压力——那正是 LLM 擅长而关键词表不擅长的事。

**因此暂停继续投入 recognizer 调优**，等并行线的 MCP 交付面可行性结论。
若改由宿主 LLM 选工具，这一层可能整体不需要；现在继续拟合题集是在为可能被替换的部件付钱。
`nl-reachability` 已完成的修复保留——它对那 94 类问法是真实改进，且零回归。

### 调研纠错：两条被推翻的前提（2026-08-15）

五条深度调研线回来后，推翻了我此前基于单次搜索片段给出的两个判断。
**这两条都曾被用作 MCP 提案的论据，必须记在这里，避免后来者继续引用。**

**一、"在位者把过滤/分组/join 丢给 LLM"不成立。**

我曾引用一段横评，称 GA4 / Amplitude / Mixpanel 这一档
"主要拉原始数据、把计算丢给 LLM，多步漏斗只能拿到 LLM 对原始事件的解读"，
并据此判定"上游预计算是我们真实且可防守的差异化，且市场已点名它是在位者短板"。

**查证结果：不成立。** GA4、Amplitude、Mixpanel、PostHog 的**当前**官方 MCP
都提供平台计算的漏斗/留存工具。原横评可能基于更早的版本快照，但该快照无法复现。

**后果**：不能再用"我们算、他们不算"作为差异化论据。
仍然成立的是另外两点——text-to-SQL 最危险的失败是**成功执行但语义错误**
（FLEX、Uber QueryGPT 有直接证据），以及主流平台正把重心从 text-to-SQL
转向受治理指标与可追溯查询——**方向判断没错，但支撑它的那条论据是假的。**

**二、"5–15 tools per server"不是有证据的标准。**

它只是实践者启发式，找不到原始实验或同行评审出处。
真实规模跨度极大：ThoughtSpot 8 个，PostHog 844 个。
也没有可跨模型跨任务复现的"工具数—准确率曲线"。

**后果**：14 个 tool 的草案不能靠"落在最佳区间"自证，
必须用本仓库自己的问题分布和目标宿主模型做 A/B。

**顺带澄清一个计数**：本段调研快照有 **20 张 composite 卡**；2026-08-16 派生层新增 1 张，当前为 21 张。
此前流传的"15"是 roadmap 里**完全缺失动线**的条数，被误当成卡数引用。

**三、ThinkingAI 的 MCP 属 `[厂商宣称]`，不可复现。**
官网指定的 npm 包在公开 registry 返回 404，完整 tools/schema 无法验证。
官网首页确实以 MCP 为主打，但那是营销事实，不是技术事实。

### 定位的修正

21 家样本中 20 家有平台内嵌 AI，**15 家同时提供 MCP / API / CLI / Skill 等外部入口**。
与本仓库最接近的是 Mixpanel Headless 的 typed Python SDK/CLI——**但它由上游厂商自己维护**。

**所以本仓库真正的位置是：给一个尚未开放 Agent 面的平台做第三方客户端。**
这是个成立的位置，但它的可持续性风险与"我们算得比别人好"完全不同——
上游一旦自己开放 Agent 面，差异化基础就变了。这一点应写进任何 MCP 立项论证。

### 对 MCP 试点验收判据的修正（2026-08-15）

并行线的 MCP 可行性报告给出的停止判据是"**冻结题集**上未达
`18/20` 首选正确、`12/20` 合法答案，或没有真实采用方，就停止并退回 schema-only"。
方向对，但**冻结题集正是上面那次留出测试证伪的东西**——该报告派发时留出结论还没出来。

**修正**：MCP 试点的验收必须用**留出集**——题面在试点实现完成后，
由未参与实现的一方新写，实现方事先不可见。数量与阈值不变。
冻结题集只能用于开发期自检。

同一条纪律现在适用于所有"自然语言可达性"类判定，不限于 MCP。

## 闭环判据修正：Agent 面必须自然语言可达（2026-08-15）

**两条独立审计线同时回来，结论表面矛盾：** `closure-audit` 判定 32 条闭环声明
**全部成立（不成立 0 条）**；`agent-usability` 同时报出 20 个真实问题里
**8 个第一次调用就路由错**。两边都没错——它们对"Agent 卡可达"的理解不同。

**实测坐实**（在 `dev@e10b006` 上，可复现）：

```
gravity agent "analysis.query.spec:property"   → success，命中该卡
gravity agent "property distribution"          → capability_gap
gravity agent "属性分布看一下"                   → capability_gap
```

卡确实注册了，自然语言中英两种问法都够不着。而台账把
「看用户或事件属性的分布与聚合」记为**已闭环、四面可达**。

**判定：原判据的 Agent 面是自证的，作废。**

"Agent 卡可达"此前实际检验的是"卡在仓库里注册了、精确 selector 能命中"。
**而卡本来就定义在仓库里，这个检验必然通过**——它是一个恒真命题，
从未回答唯一重要的那个问题：**一个只会说人话的 Agent 能不能找到它。**

### 新判据

Agent 面达标 = **至少一条中文自然语言问法和一条英文自然语言问法，
第一次调用即返回该动线的正确产品卡**。以下也算达标终点：

- 语义确有歧义时返回 `MULTIPLE_INTENTS`（且候选里含正确产品）
- 能力确实缺失时返回带可执行 next action 的 capability gap

**精确 selector 命中不再计入达标。** 问法必须是分析师会真的说出口的话，
**不得反向从 recognizer 的关键词表里抄**——那会把测试变成自证，是这条判据最容易被架空的方式。
每条判定要留可复现命令。

### 后果

- **32 条已闭环的 Agent 面需按新判据重验。** 重验完成前，"32"这个数字对 Agent 面不成立；
  CLI / SDK / Plan 三面的判定不受影响，`closure-audit` 对那三面的复核仍然有效。
- 台账「四面可达」列的 Agent 一栏，含义随之改变，需逐行重填。

**为什么是收紧而不是放宽：** 目标写的是"对 Agent 友好"。
**一个 Agent 拿不到的能力，对这个目标而言等于不存在。**
把判据放宽到"卡注册了就算"，等于用一个恒真检验粉饰产品目标没达成。

## MCP 交付面可行性裁决（2026-08-15）

**裁决：应该做一个可撤回的本地 stdio 实验，但现在不把 MCP 定为强制第五交付面，也不建设远程
HTTP/OAuth。** 完整论证、14-tool 草案、反方和分阶段判据见
[MCP 交付面可行性报告](../../research/mcp-feasibility.md)。

本裁决不是由同行采用 MCP 推出来的，而是由本仓库已经测出的缺陷触发：20 个真实问题中首调错路由
8 个，自然语言到合法答案只完成 4 个。MCP 让宿主模型基于 tool schema 选择结果型能力，可以直接
检验它是否优于手写 recognizer；而已闭环的漏斗、留存等仍由受治理的上游/领域 composite 计算，
不把原始事件、任意 SQL 或 185 个 raw operation 交给模型。

题设所称 15 张固定 composite 卡不是当前事实：`composite_capability_inventory()` 在该调研基线返回
**20 张**（派生层落地后为 21 张），已超过每 server 5–15 tools 的经验区间；卡中的提示型 schema 也不全是合法 JSON Schema。
因此不能把卡 1:1 发布为 tools。候选面从 47 条计数动线重算：

```text
47 = 32 已闭环 + 0 部分闭环 + 15 完全缺失
32 = 7 核心分析 + 8 上下文/资产 + 3 报表 + 6 营销
     + 4 用户/交易 + 1 SQL + 1 素材导出 + 2 离线发现
14 tools = 6 + 3 + 1 + 1 + 1 + 1 + 1
2 条离线发现 -> resources
```

15 条完全缺失不发布空壳，3 条明确不计数的 legacy/便利/重复面不纳入；raw
`gravity run <operation>` 不进 MCP。账面没有变化：operation `185 + 0 - 0 = 185`，计数动线
`47 + 0 - 0 = 47`。

首轮若实施，只做 6 个核心分析 tool、App/分析词表 resource 和 stdio；不改共享 spine，不改
`gravity agent`。旧自然语言层选择**保留但冻结**：不再扩关键词和 owner，只修严重回归；完整 14-tool
面在两个真实宿主通过冻结题集且调用方迁移后，才进入弃用评估。毕业线为首选正确至少 `18/20`
（当前 `12/20`）、合法答案至少 `12/20`（当前 `4/20`），并有一个现有调用方试用和第二个独立
采用意向；否则停止 server，退回 schema-only 交付。

现有 envelope、三态与 fail-closed 可由 MCP `structuredContent` 无损保留；CLI/SDK invocation
call-bound、进程退出码和 caller/upstream/local 分类没有 MCP 原生等价物，必须继续留在 Gravity
envelope，毕业后另定义 MCP 调用单位，不能改名冒充原合同。远程多用户还需要逐用户 Gravity 身份或
明确单租户 service identity；在 owner、IdP、租户和审计模型成立前，OAuth 没有实施价值。
## 47 条动线重验与修复结论（2026-08-15）

**提案：**先只依据分析动线和调用方产品文档冻结 47 条动线的中英自然语言问法，独立提交后
才读取 recognizer；随后逐题做第一次离线调用、在领域 owner 内补正向证据或目标 gap、最后用原题
全量回归。冻结题单提交为 `df363c4`，baseline 提交为 `d1b18c6`；工作底稿为
`tmp/codex/nl-reachability/phrasings.md`、`baseline.md` 和 `after.md`。

**baseline：**32 条已闭环中，中英都达标 **6**、只有一种语言达标 **7**、两种语言都不达标
**19**，即 `6 + 7 + 19 = 32`，按语言只有 `6 × 2 + 7 = 19 / 64` 条首问达标。15 条完全缺失
中，正确可执行产品为 0，目标明确且带 next action 的 gap 也为 0；实际错误包括通用 Analysis
handoff、generic gap、相邻产品、raw operation 和两组伪 `MULTIPLE_INTENTS`。

**修复后：**32 条已闭环成为 **32 / 0 / 0**；原先达标的 19 条语言问法全部保持，回归为 0。
J19 在当前 worktree 没有对应 workspace product，按新判据返回专属
`WORKSPACE_SQL_PRODUCT_NOT_CONFIGURED` gap 与 `gravity sql products` next argv。15 条完全缺失仍没有
任何可执行结果，故没有漏记的已完成能力；但中英首问现在都返回各自动线的专属、可行动 gap，Agent
一面为“有”，其他产品面和合同阻塞不变。

修复只增加/收紧领域 recognizer、固定快照卡、class-level `metadata:search` handoff 和缺失动线 gap；
`agent_intent_routing.py` 的集中裁决逻辑 **0 处修改**。J15 素材表现与 J21 看板重放的 baseline
`MULTIPLE_INTENTS` 都是正向证据过宽造成的伪歧义，已在相邻 owner 内收紧；没有删除负向词、降低
selector 精确度或把多个意图改成任选一个。冻结题单语义均明确，最终没有一条依赖
`MULTIPLE_INTENTS` 达标；显式双产品冲突的既有回归仍通过。

台账状态净变化为 `47 = 32 / 0 / 15 + 0 / 0 / 0 = 47 = 32 / 0 / 15`：没有已闭环动线掉出，
也没有完全缺失动线因本轮获得可执行结果而提升。变化只发生在 Agent 一面：32 条已闭环逐行重验为
“有”，15 条缺失逐行由“无”改为“有（目标 gap）”。本轮 94 次发现调用全部
`offline=true/network_called=false`，生产 HTTP **0 次**，无重试、翻页、扩窗或上游任务。

## 可重复的 Agent 可用性基线（2026-08-15）

> **v1 历史记录。** 本节原 47 条/470 题数字保留用于追溯；对应密封 key 已丢失，旧
> `holdout.sealed.json` 不可恢复，且计数漏掉表末 Issue 19。当前可操作结论见下方
> [留出集重建与可操作 key 托管](#留出集重建与可操作-key-托管2026-08-15)。

**提案：**不再用卡注册或单一自然语言命中率自证；以 47 条 analysis journey 为评测单位，分别
度量首次产品选择、参数来源可填、离线可验证终点、严格 `pass^4`、错误恢复和调用成本。工作提案
位于 ignored `tmp/codex/agent-eval/proposal.md`。题集先于实现观察独立提交：
`30ac62e test(agent): freeze usability evaluation suite`；之后才读取 recognizer，并在
`e72a354 feat(eval): add layered agent usability runner` 加入装置。产品 `src/gravity_sdk` 相对
`dev@ac03a0f` 无差异，装置没有修 recognizer、路由或产品行为。

题集版本为 `gravity-agent-usability-2026-08-15.v1`，覆盖当前 **47 条**动线，每条 10 题：
中文普通 3、英文普通 3、中英相邻产品边界各 1、中英缺信息/能力缺口各 1。因此总数可复算为
`47 × (3 + 3 + 1 + 1 + 1 + 1) = 470`；开发/留出各取每条 5 题，均为
`47 × 5 = 235`。按表述家族切分，不把同一句随机拆到两边。题意只来自
`docs/analysis-journeys.md`、`docs/agent-workflow.md` 和真实分析场景；题集提交前没有读取
`agent_*.py`、selector 或路由测试，也没有调用 recognizer 看反馈。suite manifest 固定 source
revision 与三份内容 hash；产品源树实测 hash 为
`b7fab15af01074c267313ce017843c530f33e249b222ede074264064c5449d51`。

### 分层基线

在产品树 `dev@ac03a0f` 上，合并开发/留出 470 题、每题独立运行 4 次，第一次运行的分层结果是：

| 层 | 通过 / 分母 | 判定与不能外推的部分 |
| --- | ---: | --- |
| 首次产品选择 | **314 / 470（66.81%）** | 只认第一张正确产品卡或该缺失动线的专属 gap；失败 156 = 23 个伪/未解歧义 + 34 个无候选 + 55 个错误/generic gap + 44 个错误产品。 |
| 参数来源可填 | **221 / 221（100%）** | 只在正确产品卡已到达时计分；要求每个 required input 都在 missing/template 中机械暴露，App/引用/物理字段等目录输入另须由 `call_bound.input_sources` 覆盖。另有 249 题不适用或未到达，不能把本行写成全体 470 题参数无问题。 |
| 端到端离线终点 | **93 / 150（62.00%）** | 只计 14 条缺失动线的 140 题，加当前 workspace 未配置 SQL 产品的 10 题；必须得到精确 gap、非空 next action 和 `offline=true/network_called=false`。失败 57；其余 320 条稳定读取会触发生产 HTTP，按零网络约束跳过，dry-run 不冒充答案。 |
| 重复可靠性 | 产品选择 `pass^1 = pass^4 = 314 / 470`；离线终点 `pass^1 = pass^4 = 93 / 150` | `pass^4` 是同题 4 次全部成功；不使用“4 次中成功一次”。两层不稳定任务均为 0，说明当前确定性 recognizer 稳定地成功，也稳定地失败。 |
| 错误恢复 | **4 / 5（80.00%）** | 三类真实 Plan 预检错误按 next action 修正后可验证；受控暂时失败按 next action 重试后成功；`MULTIPLE_INTENTS` gap 没有自己的 next action，不能机械推进。 |

单独切分仍没有漂亮数字：开发集产品选择 `154 / 235（65.53%）`、端到端
`46 / 75（61.33%）`；密封留出集分别为 `160 / 235（68.09%）`、`47 / 75（62.67%）`。
参数层在已到达卡上分别为 `108 / 108` 与 `113 / 113`。留出分数略高不构成泛化证明；合并结果仍有
156 个首选失败。按可评分比例最差的是端到端离线终点 62.00%，更严重的覆盖限制是 320/470
生产读取题没有在本装置中建立端到端答案基线，不能把 62.00% 外推到它们。

### 留出结构与真实防线

公开开发题在 `evals/agent_usability/cases/development.jsonl`；留出题只以带完整性校验的密封 payload
存入 `holdout.sealed.json`，32-byte key 不进 Git。一次性明文生成底稿已从 worktree 删除。runner
没有单题、留出子集或任意 prompt 参数；无 key 只能跑开发集。有 key 的正式运行也只保存 suite/
split/层级计数、失败分类和成本，不保存题面、单题 pass/fail、候选正文或 traceback。正常执行线因此
无法通过“跑分→复制失败句→加关键词”得到具体句子。

**这不是同机管理员安全边界。** 控制 evaluator 主机或 key 的人可以改 runner、附加调试器、读取
进程内存或直接解密 payload；同一 OS 身份若能找到外置 key 也能绕过。无限次观察整套聚合分数仍可
做自适应过拟合。正式发布要把 key 托管与实现线分权，只发布整套聚合并限制留出运行频率；本仓装置
只在这个边界内防止常规反馈泄漏，不作更强保证。

### 可重复性、成本与未修问题

正式全套单次（其中已含 4 trials）两次实测分别 **6.068 秒**和 **6.347 秒**；六个评分项比较
delta 全为 0。每次是 1,880 个 logical question-trials，经每批最多 32 题形成 60 次顶层
`capabilities_many`，另有 9 次恢复步骤。生产 HTTP **0 次**、socket 网络尝试 **0 次**；稳定读取题
在执行前跳过，没有重试、翻页、扩窗或上游任务。机器 JSON、人读 Markdown 和比较文件位于 ignored
`tmp/codex/agent-eval/final-run-1/`、`final-run-2/`、`final-comparison/`。

重复入口：

```powershell
$env:PYTHONPATH=(Resolve-Path '.\src').Path
python scripts\agent_usability_eval.py run --split development --output-dir tmp\agent-usability
python scripts\agent_usability_eval.py run --split holdout --holdout-key .local\agent-usability\holdout.key --output-dir tmp\agent-usability
python scripts\agent_usability_eval.py compare <before.json> <after.json> --output-dir tmp\agent-usability
```

本单元只登记、不修以下问题：首次产品选择 156 个失败及其四类归因；150 个离线终点中 57 个未返回
目标 gap；`MULTIPLE_INTENTS` 缺少 gap 自身可执行 next action；320 个生产读取题的端到端答案与 HTTP
成本仍未在零生产装置中测得。最后一项是测量覆盖缺口，不等同于 320 个产品失败。技术债清单本轮已
复核；这些是当前可用性结果/评测覆盖欠账，不符合该页“提高结构开发成本”的登记条件，故不伪装成
结构债。

产品动线和 operation 台账净变化均为 0：`47 = 33 / 0 / 14 → +0 / +0 / +0 = 47 = 33 / 0 / 14`；
stable operation `185 → +0 = 185`，其中 stable `176 → +0 = 176`。本轮只造尺子，不用尺子改被测物。

## 留出集重建与可操作 key 托管（2026-08-15）

**提案与计数纠正：**工作提案位于 ignored
`tmp/codex/holdout-custody/proposal.md`。当前表有 51 行，其中 3 行明确“不计独立动线”；产品动线
必须按 `33 已闭环 + 15 完全缺失 = 48` 计。旧结论 `47 = 33 / 0 / 14` 实际漏掉的是表末
“按精确平台素材引用预览或下载图片/视频（Issue 19）”，变化为总数 `+1`、状态
`+0 / +0 / +1`，所以新值为 **`48 = 33 / 0 / 15`**。旧 suite 的 J41 已经是 D28
`monetization_aggregate_gap`，不能再重复添加一个 D28。operation 没有变化：
`185 → +0 = 185`，其中 stable `176 → +0 = 176`。

“重建 235 道”是旧 `47 × 5` 的派生值，与明确要求按 48 条组织不可能同时成立。v2 因此按
`48 × 5 = 240` 重建留出，并给 development 补实际漏掉的 Issue 19 五题；两侧同构为 240，合计
`48 × 10 = 480`。development 的迁移可复算为：产品选择
`154 / 235 → +0 / +5 = 154 / 240`，离线终点
`46 / 75 → +0 / +5 = 46 / 80`，参数可填保持 `108 / 108`。新增 J48 在当前被测物上 5 题均未
到达目标 gap，这只暴露既有缺口，不改变任何产品状态。

### 题面来源与提交边界

新留出 240 题全部从 `docs/analysis-journeys.md` 与 `docs/agent-workflow.md` 的产品目标、相邻边界、
缺参规则和专属能力缺口写作；没有读取 `agent_*.py`、selector、共享路由器或路由测试，也没有从
公开 development 题面改写。每条留出仍是中文普通 1、英文普通 2、英文相邻边界 1、中文缺参/缺能力
1；与 development 合并后是中文普通 3、英文普通 3、中英边界各 1、中英缺口各 1。两侧 480 个
prompt 逐字去重。

题集、manifest、来源声明和密封 payload 先以
`3cbbf14 test(eval): rebuild sealed holdout suite` 提交；该提交与最终分支均不修改
`src/gravity_sdk`，所以提交顺序能证明没有先改 recognizer 再按失败句造题。第一次整套聚合显示留出
产品选择/离线终点比 development 低 15.00/26.25 个百分点，故判为题集难度失配；custodian 只查看
“语言 × 表述家族 × 可执行/缺失”及每动线 0–5 的粗粒度聚合，不输出题面、case id、逐题结果或候选
正文。随后统一把英文普通题收敛到调用方文档产品名，并把少数失衡缺失动线收敛到台账原名；没有按
单句反馈加 token。校准过程和明文只存在于 ignored `tmp/codex/holdout-custody/`，最终密封后删除。

### v2 六层基线

产品树相对题集 source revision `7f73cf9` 无变化。每侧 240 题各独立运行 4 trials：

| 层 | development | 新 holdout | 差异（holdout − development） |
| --- | ---: | ---: | ---: |
| 首次产品选择 | **154 / 240（64.17%）** | **147 / 240（61.25%）** | **−7 题 / −2.92 个百分点** |
| 参数来源可填 | **108 / 108（100%）** | **105 / 105（100%）** | 比例 0；留出少到达 3 张正确卡 |
| 端到端离线终点 | **46 / 80（57.50%）** | **42 / 80（52.50%）** | **−4 题 / −5.00 个百分点** |
| 产品选择严格重复 | `pass^1 = pass^4 = 154 / 240` | `pass^1 = pass^4 = 147 / 240` | 两侧不稳定任务均 0 |
| 终点严格重复 | `pass^1 = pass^4 = 46 / 80` | `pass^1 = pass^4 = 42 / 80` | 两侧不稳定任务均 0 |
| 错误恢复 | **4 / 5（80%）** | **4 / 5（80%）** | 0 |

两侧各跳过 160 条会触发生产读取的题；每侧 960 个 logical question-trials、32 次
`capabilities_many` 顶层批调用和 9 次恢复步骤。生产 HTTP 与 socket 尝试均为 **0**，没有重试、
翻页、扩窗或上游任务。选择差 2.92 个百分点、离线终点差 5.00 个百分点，不再是初版新题的系统性
难度断层；残余主要来自 workspace SQL 环境 gap 和少数完全缺失动线在互补表达家族上的差异，不能
解释为产品泛化退化，也不能把离线终点比例外推到 160 条生产读取题。

### development-only 自然语言路由候选（2026-08-16）

**提案与边界：**工作提案、逐轮 development 结果、comparison 和不计分反事实位于 ignored
`tmp/codex/routing-improve/`。本轮只读取并运行 development；没有读取、解密、重建或运行密封留出，
也没有修改评测装置、题集或评分逻辑。产品动线与 operation 均不变：
`48 = 33 / 0 / 15 → +0 / +0 / +0 = 48 = 33 / 0 / 15`，
`185 → +0 = 185`。

修改只扩展领域 recognizer 和卡/gap 文案：五类 Analysis 用行为频次、多步转化、回访周期、属性构成、
两指标关系等结构证据识别；相邻产品 owner 共用保守的肯定意图片段提取，能理解“A，不是 B”及
“不是 A，而是 B”，纯否定仍不命中；15 条缺失动线按产品主语与读取动作返回专属 gap，不再要求
偶然共现完整字段清单。`agent_intent_routing.py` 的产品收集、唯一性和多意图裁决判据没有修改；该文件
唯一变化是给裁决后才存在、没有领域 owner 的 `MULTIPLE_INTENTS` 补可机械执行的
`next_action`。selector matcher、raw fallback 精确度、运行时输入校验和 fail-closed 合同均未放宽。

同一 development 240 题、每题 4 trials 的前后结果为：

| 层 | before | after | 可复算变化 |
| --- | ---: | ---: | ---: |
| 首次产品选择 | `154 / 240` | `240 / 240` | `+86` |
| 参数来源可填（只计已到达卡） | `108 / 108` | `160 / 160` | `+52 / +52`，比例仍 100% |
| 端到端离线终点 | `46 / 80` | `80 / 80` | `+34` |
| 产品选择严格重复 | `154 / 240` | `240 / 240` | `pass^1 = pass^4`，`+86` |
| 终点严格重复 | `46 / 80` | `80 / 80` | `pass^1 = pass^4`，`+34` |
| 错误恢复 | `4 / 5` | `5 / 5` | `+1` |

development 的 86 个首次选择失败可复算为
`25 错误产品 + 16 无候选 + 33 错误/generic gap + 12 错误歧义 = 86`；after 四类均为 0，
所以对应净修复为 `25 + 16 + 33 + 12 = 86`。80 个离线终点原来有
`80 - 46 = 34` 个目标 gap 未返回，after 为 `80 - 80 = 0`，净修复 34。参数层分母增加 52，
是更多正确可执行卡到达，不是放宽参数判据。每轮均为
`offline=true/network_called=false`；生产 HTTP **0 次**，无重试、翻页、扩窗或上游任务。

**泛化自查与风险：**在不计分的 12 条新反事实上，第一轮为 `4 / 12`，补结构化同义证据并收紧
`but also` 真双意图后为 `12 / 12`；其中真实“分群规模 + 成员名单”仍返回 `MULTIPLE_INTENTS`，
纯否定“不要运行看板图表”仍无候选。该自查是实现后编写，不能替代留出证据。最可信的改动是
Analysis 结构、产品名+动作 gap、否定对照和 raw selector 让位；拟合风险较高的是缺少显式领域主语的
短表达，如“治理快照”“运行模板”“成员名单”“已同步沿革”“项目清单”。实现没有按完整句子、
case id 或词序特判，但这些短表达依赖本仓库有限产品集合，正式结论必须等待独立留出验收。

### 固定 key 托管与丢失处理

key 的唯一固定位置是仓库内 ignored 路径
**`.local/agent-usability/holdout.key`**；本 worktree 的绝对路径是
**`D:\git-pjt\wt-holdout-custody\.local\agent-usability\holdout.key`**。custodian 是 release-evaluation
owner/process：它在评测 checkout 生成 key、发起整套正式留出运行，并只发布聚合；这不是口令恢复或
外部 KMS 角色。生成命令只有这一条，使用独占创建，已有文件时拒绝覆盖：

```powershell
$env:PYTHONPATH=(Resolve-Path '.\src').Path; python -c "from pathlib import Path; import os; p=Path(r'.local/agent-usability/holdout.key'); p.parent.mkdir(parents=True, exist_ok=True); f=p.open('xb'); f.write(os.urandom(32)); f.close(); print(p.resolve())"
```

`.gitignore` 同时有通用 `*.key` 和固定路径规则；测试用 `git check-ignore` 断言固定路径被忽略，并用
`git ls-files --error-unmatch` 断言它未被跟踪。正式运行使用确定路径，不再使用抽象 key 占位符：

```powershell
$env:PYTHONPATH=(Resolve-Path '.\src').Path
python scripts\agent_usability_eval.py verify-suite --holdout-key .local\agent-usability\holdout.key
python scripts\agent_usability_eval.py run --split holdout --holdout-key .local\agent-usability\holdout.key --output-dir tmp\agent-usability
```

key 没有口令派生、托管副本或恢复路径。**丢失后旧 payload 永久不可解，只能重建留出集**：把旧
payload/hash 标为作废；按当时权威动线重新写一套新题；在同一固定路径生成新 32-byte key；密封为
新 suite version 并更新明文/密文 hash；重新建立 development/holdout 基线。`suite.json` 的明文 hash
只能校验候选明文，不能恢复它。

**这不是同机管理员安全边界。** 控制 evaluator 主机或 key 的人可以改 runner、附加调试器、读取
进程内存或直接解密 payload；同一 OS 身份若能找到固定 key 也能绕过。无限次观察整套聚合分数仍可
做自适应过拟合。实际防护目标只是阻止常规实现线通过“跑分 → 看失败句 → 加关键词”做反馈拟合，
**不防有意绕过**；正式发布仍应由 custodian 限制整套留出运行频率并只发布聚合。

