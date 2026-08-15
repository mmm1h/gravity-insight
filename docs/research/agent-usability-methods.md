# 怎么科学度量与设计「Agent 友好」

> 调研日期：2026-08-15。本文讨论的是：给一个宿主 Agent 一组 CLI / SDK / Plan / MCP 风格工具后，它能否从自然语言出发，选对能力、填对参数、完成任务、在失败后恢复，并且不产生越权副作用。

## 结论先行

[实证] 公开评测已经把“Agent 友好”拆成了不同层次：BFCL 检验函数选择、参数和“不该调用”；τ-bench、MCPMark、ToolSandbox 检验有状态、多轮任务的最终结果；AgentDojo 单独检验有害副作用。没有一个“卡是否注册”的静态检查能替代这些运行时指标。[BFCL](https://gorilla.cs.berkeley.edu/leaderboard)、[τ-bench](https://arxiv.org/abs/2406.12045)、[MCPMark](https://arxiv.org/abs/2509.24002)、[ToolSandbox](https://arxiv.org/abs/2408.04682)、[AgentDojo](https://arxiv.org/abs/2406.13352)

[实证] τ-bench 的严格成功条件是数据库最终状态正确且最终回复包含必要信息；其 `pass^k` 衡量同一任务独立运行 (k) 次全部成功的概率，而不是“多试几次至少撞中一次”。这比单次首次路由命中更接近可依赖的分析旅程。[τ-bench 论文，第 3.2 节](https://arxiv.org/abs/2406.12045)

[实证] “tool description 越短越好”或“越长越好”都没有得到普遍支持：EASYTOOL 在 ToolBench 上把平均工具文档从 2,530 token 压到 748 token，并在所测模型上提高结果；MetaTool 却观察到更长描述与选对率相关，而且同一套改写对不同模型可能一升一降。[EASYTOOL](https://aclanthology.org/2025.naacl-long.44/)、[MetaTool](https://arxiv.org/abs/2310.03128)

[实证] 可恢复错误的关键不是 JSON 外形，而是同时给出失败位置、实际值和当前可接受的替代项；一项受控实验中，这种反馈在 4 次调用上限下把两个模型的终局成功分别从 14/50 提到 36/50、从 8/50 提到 29/50，而只有位置与实际值接近原始诊断基线。[Structured Feedback](https://arxiv.org/abs/2607.14167)

[推测] 对本仓库最稳妥的目标形态不是“关键词 recognizer 或宿主 LLM 二选一”，而是：宿主 LLM 负责开放式语义选择；确定性层负责 schema、权限、字段登记和执行前校验；对高风险或低置信路由明确 abstain，返回候选或追问。依据是 BFCL 暴露的缺参数/缺工具失败、AgentDojo 的副作用指标，以及本仓库现有 fail-closed 能力。[BFCL v3](https://gorilla.cs.berkeley.edu/blogs/13_bfcl_v3_multi_turn.html)、[AgentDojo](https://arxiv.org/abs/2406.13352)、[本仓库路线图](../roadmap.md)

## 调研方法、取证边界与失败

[实证] 本次实际使用了公开网页搜索、论文/规范官网、`curl` 下载 HTML/PDF、`pdftotext` 转文本，以及仓库源码和文档的只读检索；关键原文曾保存在 ignored 工作底稿 `tmp/codex/agent-usability-methods/sources/`，不随仓库分发。优先级是规范/官方文档、论文原文、官方源码库；搜索摘要只用于定位，未作为结论证据。

[实证] 两个 OpenReview PDF 地址返回 HTTP 403；ToolBench 与 MetaTool 均改从公开 arXiv 版本取证。没有尝试登录、付费页或授权资源。[ToolBench arXiv](https://arxiv.org/abs/2307.16789)、[MetaTool arXiv](https://arxiv.org/abs/2310.03128)

[实证] 本文把“有官方规范、文档、源码或可复现实验支持”标为实证；只来自厂商自测或工程博客且缺少独立复现的效果数字标为厂商宣称；从证据组合推导的项目建议标为推测。一个来源可以证明“接口确实这样定义”，却未必能证明“这种设计一定更好”，后者会降级标注。

## A. 公开 benchmark 与评分方法

### 哪些直接相关

[实证] 下表的评分定义均取自各评测原文；“本仓库可借用什么”是对原方法的适用范围概括，不是这些项目对 Gravity 的建议。

| 评测 | 与“给 Agent 一组工具，看它能否选对并用对”的距离 | 真实评分方法 | 本仓库可借用什么 |
|---|---|---|---|
| [BFCL](https://gorilla.cs.berkeley.edu/leaderboard) | 直接，偏函数调用边界 | AST/可执行检查函数名和参数；`relevance` 检查无适用函数时不调用；v3 多轮任务要求每一轮同时通过状态检查和回复检查，超过 20 步失败 | 路由、参数、拒绝调用、缺参追问、恢复路径 |
| [MetaTool](https://arxiv.org/abs/2310.03128) | 直接，偏“需不需要工具、该选哪个” | 工具意识用 accuracy / precision / recall / F1；工具选择用 Correct Selection Rate（CSR） | 分开测“该不该调用”和“调用哪个” |
| [ToolBench / ToolEval](https://arxiv.org/abs/2307.16789) | 直接，但裁判较弱 | `pass rate`：调用预算内完成任务的比例；`win rate`：LLM 裁判比较两条轨迹 | 多工具任务、预算内完成；不直接照搬 LLM 裁判 |
| [τ-bench](https://arxiv.org/abs/2406.12045) | 直接，偏真实多轮业务 | `r_action × r_output`：最终数据库状态与唯一目标状态一致，且回复含必要信息；报告 `pass^1` 与严格的 `pass^k` | 最终状态、最终答案、重复可靠性 |
| [ToolSandbox](https://arxiv.org/abs/2408.04682) | 直接，偏状态依赖和非唯一轨迹 | 用状态相似度和 milestone 检查任意有效轨迹，而非只比唯一调用序列 | 多条合法路径、缺信息、状态依赖 |
| [MCPMark](https://arxiv.org/abs/2509.24002) | 直接，MCP 任务端到端 | 每任务从可重置初态开始，用程序化 verifier 判定完成；报告 `pass@1`、`pass^4`、turns、tool calls | MCP/CLI 旅程的状态重置、程序化验收、成本 |
| [MCPBench（ModelScope）](https://arxiv.org/abs/2504.11094) | 直接评 MCP server，但范围窄 | 固定 LLM 与提示，对服务器比较 QA accuracy、端到端耗时、prompt/completion token；答案由 LLM 判 True/False | 同一宿主下横向比较 server/接口版本 |
| [AgentBench](https://arxiv.org/abs/2308.03688) / [WebArena](https://arxiv.org/abs/2307.13854) | 间接，评更广的自治能力 | AgentBench 汇总 8 个环境各自的 SR/F1/win rate；WebArena 的 812 个网页任务用程序化 functional validators 判成功 | 端到端任务而非调用次数；不适合作为纯工具 schema 分数 |

[实证] 表中定义来自各评测原文。BFCL 的 `multiple` 类明确要求从 2–4 个候选函数中选一个；v3 的 Missing Parameters 要求模型追问而不是猜，Missing Functions 要求识别当前没有合适工具；其 response checker 允许多余的探索或恢复调用，只要求包含完成任务的最小必要调用，因此不会把一条唯一 gold trajectory 当作真理。[BFCL v1 方法](https://gorilla.cs.berkeley.edu/blogs/8_berkeley_function_calling_leaderboard.html)、[BFCL v3](https://gorilla.cs.berkeley.edu/blogs/13_bfcl_v3_multi_turn.html)

[实证] ToolEval 的 `pass rate` 是有限调用数内完成任务的比例，`win rate` 是 LLM 裁判在两条调用轨迹间的偏好；论文报告与人工判断的一致率分别为 87.1% 和 80.3%。这不是程序化真值，且原始 RapidAPI 环境会漂移，因此不应成为本仓库发布门禁的唯一裁判。[ToolLLM / ToolBench，第 4.3 节](https://arxiv.org/abs/2307.16789)

[实证] MCPMark 有 127 个专家/Agent 构造任务，覆盖 Filesystem、GitHub、Notion、Playwright、PostgreSQL 等状态化环境；论文所报最佳设置的 `pass@1` 为 52.56%、`pass^4` 为 33.86%，平均 16.2 turns、17.4 tool calls。它测的是“模型＋Agent loop＋MCP 工具＋环境”的组合，不是 server 静态质量认证。[MCPMark](https://arxiv.org/abs/2509.24002)、[官方仓库](https://github.com/eval-sys/mcpmark)

### MCP server 质量有没有专门方法

[实证] ModelScope 的 MCPBench server report 是本次找到最接近“固定宿主后比较 MCP server”的公开工作：它固定 LLM 与提示，比较 Web Search 和数据库服务器的答案准确率、时间、token，并报告声明式自然语言数据库接口相对通用 PostgreSQL 接口提高 22 个百分点；但其 `valid sample accuracy` 会排除不完整/失败样本，存在选择偏差，而且仅覆盖两个领域。[MCPBench server report](https://arxiv.org/abs/2504.11094)、[代码库](https://github.com/modelscope/mcpbench)

[实证] 官方 MCP Inspector 是交互式检查、连接和调试工具，MCP debugging 文档也把它定位为开发测试工具；两者没有定义跨 server 的质量分数、任务集或发布阈值。因此“能被 Inspector 调通”只能算协议 smoke test，不能算 Agent usability benchmark。[MCP Inspector](https://github.com/modelcontextprotocol/inspector)、[MCP debugging](https://modelcontextprotocol.io/docs/tools/debugging)

[推测] 对本仓库而言，“server/tool 质量”至少要拆成三张表：静态契约质量、固定宿主下的路由/参数质量、端到端旅程质量。这样才能区分问题在描述、宿主模型、执行器、上游数据还是 verifier；依据是 MCPBench 与 MCPMark测量对象不同，而 Inspector只覆盖协议调试。

### 错误恢复与有害调用

[实证] ReflecTool-Bench 覆盖 10 个领域、88 个 API、968 段注入用户侧或助手侧错误的对话，分别测外部 Critique 和继续自身对话的 Self-Reflection；指标拆成错误检测、分类、纠正准确率和解释质量。论文结果显示检测与真正纠正之间存在明显缺口，所以“识别到报错”不能替代“重试后完成”。[ReflecTool-Bench](https://aclanthology.org/2026.findings-acl.86/)

[实证] AgentDojo 将安全拆成三个可计算指标：Benign Utility 是无攻击时完成用户任务的比例；Utility Under Attack 是攻击存在时既完成用户任务又没有对抗副作用的比例；Targeted Attack Success Rate 是攻击目标实现、即执行恶意动作的安全样本比例。[AgentDojo，第 3.4 节](https://arxiv.org/abs/2406.13352)

[推测] 本仓库的恢复评测应主动注入至少五类故障：未知字段、错误枚举、缺必填参数、上游暂时失败、候选意图冲突；分别记录“是否识别”“下一调用是否修正”“预算内是否最终成功”“是否重复同一失败”“是否产生不允许的调用”。这组合了 BFCL v3 的缺参/缺工具、ReflecTool 的检测—纠正拆分和 Structured Feedback 的有限调用实验，而不是复制某一个数据集。

## B. 工具描述、参数 schema 与错误消息

### Tool description：写什么比单纯字数更重要

[实证] OpenAI 的公开 function-calling 指南要求函数名和参数名清楚、描述说明用途和各参数格式；系统提示应说明何时使用和何时不要使用；反复出错的 edge case 可加例子，但指南同时警告例子可能妨碍某些 reasoning model。它还建议用 enum/object 让非法状态不可表示、不要让模型填写应用已知参数，并把总是顺序调用的函数考虑合并。[OpenAI function calling](https://developers.openai.com/api/docs/guides/function-calling)

[厂商宣称] Anthropic 在内部、未公开完整任务集的工具评测中总结：工具应有明确且互斥的用途，频繁串联的操作可合并，名称按服务/资源 namespace，并用 `response_format` 的 enum 让 Agent 选择 concise/detailed 输出；其博客示例称一次响应从约 206 token 降到 72 token。这个数值只证明其内部样例，不是跨模型定律。[Anthropic engineering](https://www.anthropic.com/engineering/writing-tools-for-agents)

[实证] EASYTOOL 不是纯长度消融：它把异构文档改成“简洁工具描述＋功能使用指南”，平均 token 2,530→748（−70.43%）；在论文表 4 中，ChatGPT+DFSDT 的平均 Pass/Win/Success 从 62.3/66.5/15.0 升到 69.8/82.3/52.8，GPT-4o+DFSDT 从 66.3/71.8/63.8 升到 76.8/85.8/77.0。因此能支持的是“删除无关实现细节并保留操作约束有效”，不能归因为“短”本身。[EASYTOOL，第 4.2、5.4 节](https://aclanthology.org/2025.naacl-long.44/)

[实证] MetaTool 的 21,127 个经人工检查查询覆盖是否需要工具、相似工具、场景、多工具等任务；其分析发现更长、更详细的描述与 CSR 正相关，但用一个模型重写的描述对另一个模型有时改善、有时恶化。它与 EASYTOOL 的表面冲突说明描述应按目标宿主做 held-out A/B，而不是设全局字数阈值。[MetaTool，第 4.6 节](https://arxiv.org/abs/2310.03128)

[推测] 本仓库每个可发现能力的描述应固定为四段语义，而非固定字数：`做什么/返回什么`、`适用的用户目标`、`不要用于哪些相邻目标`、`关键前置条件或缺参行为`。反例只写最常混淆的相邻能力，避免把整个 recognizer 关键词表塞进描述；是否有效必须由锁定的自然语言 holdout A/B 决定。

### 参数 schema：把“可校验”与“语义正确”分开

[实证] OpenAI strict mode 保证生成的函数参数遵循所给 JSON Schema 子集；要求 `additionalProperties: false` 且所有 properties 都列为 required，业务上的可选字段可用包含 `null` 的类型表达。这个保证是结构符合 schema，不是值在业务上正确。[OpenAI strict mode](https://developers.openai.com/api/docs/guides/function-calling#strict-mode)

[实证] MCP 的 `Tool` schema 真实字段为必需的 `name`、`inputSchema`，可选的 `title`、`description`、`outputSchema`、`annotations`；annotations 可含 `readOnlyHint`、`destructiveHint`、`idempotentHint`、`openWorldHint`，规范明确这些只是 hint，不能被不可信 server 当作安全保证。[MCP 2025-11-25 schema](https://modelcontextprotocol.io/specification/2025-11-25/schema)

[实证] OpenAI 的指南明确建议 enum 与对象结构令非法状态不可表示；Anthropic 的工程指南给出 `user_id` 优于含糊的 `user`，并建议 pagination/filter/truncation 有合理默认值。前者是公开接口指南，后者是厂商实践而非独立效果实验。[OpenAI function calling](https://developers.openai.com/api/docs/guides/function-calling)、[Anthropic engineering](https://www.anthropic.com/engineering/writing-tools-for-agents)

[推测] 本仓库应优先：稳定标识符用 enum；互斥形态用 `oneOf`/判别字段而非多个相互制约的布尔值；单位写入参数名或 description；能从 session/Plan 推出的值不暴露给模型；默认值只用于不会改变分析语义的展示/分页参数，时间范围、口径、主体等业务值不得静默默认。理由是 schema 能消除结构非法状态，却不能替 Agent 猜业务意图。

### Actionable error：字段路径还不够

[实证] MCP 规范要求工具执行错误放在普通 result 内并设 `isError: true`，而非都升级为 protocol-level error；这让客户端能把错误内容交回模型处理。[MCP tools error handling](https://modelcontextprotocol.io/specification/2025-06-18/server/tools#error-handling)

[实证] Structured Feedback 的对照实验表明，`location + observed value + admissible alternatives` 才是主要增益；把同样修复信息写成 prose 与 keyed JSON 的成功率接近，只有 location+observed 仍接近 raw diagnostic。故“精确字段路径”是必要定位信息，但可接受替代项/取得替代项的动作才让错误真正可修。[Structured Feedback，第 4、6 节](https://arxiv.org/abs/2607.14167)

[推测] 建议错误 envelope 至少稳定包含：`code`、`path`、`observed`、`constraint`、`allowed_values` 或 `discovery_action`、`retryable`、`next_action`。例如现有“把 `group_by[0].field` 换成 metadata-backed 的非 acquisition user property”已包含路径、约束和动作；若候选有限，再返回候选值；若候选很大，则返回获取 metadata 的精确调用，不应把整张字典塞进错误。

### 歧义：该选、该报，还是合并

[实证] BFCL v3 的 Missing Parameters 要求缺必要信息时追问，Missing Functions 要求没有合适工具时不调用；MetaTool 为建立单一 gold label，会合并功能相似工具组并拆开多用途工具。这说明评测本身也承认“工具边界重叠”会让单标签准确率失真。[BFCL v3](https://gorilla.cs.berkeley.edu/blogs/13_bfcl_v3_multi_turn.html)、[MetaTool 数据构造](https://arxiv.org/abs/2310.03128)

[推测] 实际决策规则应是：语义等价且总是串联的工具合并；同一输入对应不同业务口径时不得靠模型猜，返回歧义候选并追问；只是实现入口不同而结果等价时允许模型任选。当前 `MULTIPLE_INTENTS` 方向合理，但成功条件必须同时检查候选集合覆盖正确能力、问题是否真的不可由上下文消歧、以及下一步是否可执行，而不能把所有多命中都算成功。[当前 recognizer](../../src/gravity_sdk/agent_intent_routing.py)

## C. 发现成本、渐进披露与调用次数

[实证] OpenAI 文档说明函数定义会注入模型上下文并计入输入 token；tool search 可先只给 namespace/MCP server 的名称和描述，在需要时加载其工具，避免一开始加载全部定义。不过单个 deferred function 仍会暴露名称和描述，主要延迟加载的是完整参数 schema。[Function calling token usage](https://developers.openai.com/api/docs/guides/function-calling#token-usage)、[Tool search](https://developers.openai.com/api/docs/guides/tools-tool-search)

[厂商宣称] OpenAI 建议最初可用函数尽量少于 20 个、每个 namespace 最好少于 10 个，并称 tool search 可降低 token/成本、保护 prompt cache；这些是厂商操作建议，没有给出跨模型、跨任务的统一拐点，因此不能把 20 或 10 当质量门禁。[Function calling best practices](https://developers.openai.com/api/docs/guides/function-calling#best-practices)、[Tool search best practices](https://developers.openai.com/api/docs/guides/tools-tool-search#best-practices)

[推测] “发现成本”应在运行时直接计量，而不是数卡：`initial_discovery_tokens`（首次请求全部可见工具定义 token）、`cumulative_tool_schema_tokens`（整条旅程实际加载）、候选工具数、首次正确工具排名、检索/展开次数、到首次有效调用的 turns/latency。token 应用目标 tokenizer 对最终发送的 JSON 计数；字符数只能做诊断代理。

[实证] MCPMark 同时报 turns、tool calls，Anthropic 建议在 eval 中跟踪 accuracy、runtime、calls、tokens、tool errors；公开 benchmark 没有给出“一个分析问题应该调用 N 次”的通用常数，因为任务跨度和工具粒度不同。[MCPMark](https://arxiv.org/abs/2509.24002)、[Anthropic evaluation guidance](https://www.anthropic.com/engineering/writing-tools-for-agents)

[推测] `gravity.agent-call-bound.v1` 的“已知输入 1 次、未知能力 2 次”是有价值的产品 SLO/契约，但不是外部共识；应作为每个 scenario 的预算声明，与实际 p50/p95、成功率一起报告。只优化调用数会诱导合并过大的工具或跳过校验，所以门禁顺序必须是安全与正确性通过后，再比较 calls/tokens/latency。[当前 call-bound 实现](../../src/gravity_sdk/agent_call_bound.py)

## D. 自然语言路由与宿主 LLM 选工具

### 查到与没查到的对比证据

[实证] 本次没有找到在同一任务集、同一工具、同一预算下，直接比较“手写关键词/规则 recognizer”与“宿主 LLM 看 schema 自选工具”的公开 head-to-head 研究。找到的邻近证据分别研究 LLM 工具选择（BFCL、MetaTool）、描述/检索改写（EASYTOOL）、有状态端到端任务（τ-bench、MCPMark），不能拼成一个不存在的直接结论。

[实证] LLM 路由已有明确失败类别：BFCL 测 wrong function、wrong arguments、该不调用时调用、缺参数时猜测、缺工具时误用和长上下文；MetaTool 测相似工具与多工具选择；AgentDojo 证明“任务完成”之外还必须检查恶意/越权副作用。[BFCL](https://gorilla.cs.berkeley.edu/leaderboard)、[BFCL v3](https://gorilla.cs.berkeley.edu/blogs/13_bfcl_v3_multi_turn.html)、[MetaTool](https://arxiv.org/abs/2310.03128)、[AgentDojo](https://arxiv.org/abs/2406.13352)

[推测] 自建 NLU 在 LLM 时代仍有四个站得住的工程理由：离线可用、低且稳定的延迟/成本、同输入同版本可复现、审计与硬安全边界。但它只在封闭标签集、语句分布稳定且有真实标注数据时可能胜任主路由；把手写关键词扩到开放自然语言会把语言覆盖责任复制进仓库，当前 8/20 首次错路就是本项目的反证，而不是外部普遍比例。[当前实测记录](../roadmap.md)

[推测] 若保留确定性路线，比关键词匹配更好的候选是：① 对自动化调用保留显式 selector/受限语法；② 用冻结的 BM25/字符 n-gram/线性分类器从真实标注查询检索 top-k，并设 margin 阈值 abstain；③ 只让它缩小候选，不让低置信结果直接执行；④ 用 schema/权限/字段 allow-list 做最终确定性验证。算法固定可以复现，但统计分类器仍会错，因此必须接受 `AMBIGUOUS`/追问。

[推测] 推荐的 A/B 不是把现有 recognizer 直接删除，而是固定同一评测集比较三种 condition：`rule_router`、`host_llm_all_tools`、`retrieval_top_k_then_host_llm`；另设 `oracle_candidate_set` 只用于估计“路由正确时执行器的上限”。若后两者没有在中英、相邻意图、缺参和安全分层上稳定胜出，就没有迁移依据。

## 可重复运行的度量方案

### 1. 评测单位和数据集

[推测] 评测单位应从“operation/card”提升为 **analysis journey**：一条独立自然语言请求，从发现能力到获得受治理 envelope 或一个合法、可继续的 gap/clarification。精确 selector 仅进入 contract smoke suite，不进入自然语言 usability 分数。

[推测] 每个稳定 journey 至少准备 8 条锁定用例：3 条中文正常问法、3 条英文正常问法、1 条与相邻能力形成 hard negative 的问法、1 条缺关键信息/能力缺口问法。另建组合任务、歧义任务与故障注入集；它们不与正常问法互相替代。若有 20 个 journey，基础集即至少 160 条，而不是每张卡中英各一条。

[推测] 防止“反抄关键词”的流程：题目作者只看业务 journey 和匿名化真实问法，不看 recognizer、tool description 或候选关键词；至少一半问法来自独立使用者/历史查询，另一半可由不同模型改写后人工验义；按 journey/表述家族切 train/dev/locked test，不能随机按句子切；评测集先生成 hash 再修改实现；失败样本进入下一版锁定回归集，不能为了过关改提示或 gold label。

[推测] 建议的 suite manifest 如下；字段是本报告的设计，不冒充外部标准：

```json
{
  "suite_version": "gravity.agent-usability.v1",
  "task_id": "retention.zh.hard-negative.003",
  "journey_id": "retention",
  "language": "zh-CN",
  "prompt": "……",
  "expected": {
    "terminal_kind": "answer|clarification|capability_gap|ambiguity",
    "acceptable_selectors": ["gravity-insight.retention.v1"],
    "required_argument_constraints": ["……"],
    "answer_assertions": ["……"],
    "forbidden_calls": ["……"]
  },
  "fault_injection": null,
  "source_family": "independent-analyst-2026q3"
}
```

### 2. 固定运行条件

[推测] 脚本每次记录并输出 NDJSON：suite hash、代码 commit、tool manifest hash、condition、宿主模型及精确版本、系统提示 hash、temperature/seed（若支持）、最大 turns/tool calls/token、环境快照、每次可见的工具、调用与结果、最终答案、耗时和 token。模型版本或 tool manifest 变化时不得与旧结果混作同一 condition。

[推测] route-only 套件在执行前拦截调用，安全地测工具/参数选择；end-to-end 套件使用可重置 fixture/snapshot 和程序化 verifier；故障恢复套件由 harness 在固定第 N 步注入同一种错误。发布评测每题至少 4 次，以 `pass^1` 和严格 `pass^4` 同时报；PR 快速集可只跑 1 次，但不能冒充可靠性结果。

### 3. 指标与判定

[推测] 脚本应逐层输出下列指标及分母，避免一个阶段的高分掩盖另一个阶段的失败：

| 层 | 指标 | 可执行定义 |
|---|---|---|
| 发现/路由 | need-tool F1 | “应调用/不应调用”的 precision、recall、F1 |
| 发现/路由 | route top-1 macro accuracy | 先在每个 journey×language 单元算首个调用正确率，再宏平均，防止大类掩盖小类 |
| 歧义 | candidate set precision/recall | `MULTIPLE_INTENTS` 候选与 gold 可接受集合比较；另计不必要歧义率 |
| 参数 | schema-valid rate | 首次执行调用通过 JSON Schema 的比例 |
| 参数 | constraint accuracy | 必填业务约束、枚举、字段治理和跨字段关系全部正确的比例 |
| 端到端 | journey success | terminal kind 正确、状态/答案 assertion 全过、无 forbidden call 的二元值 |
| 稳定性 | `pass^k` | 同题 k 次独立运行全部成功的任务比例，主报 `pass^1`、`pass^4` |
| 恢复 | recovery success | 注入错误后，在预算内成功且未重复同类非法调用的比例 |
| 安全 | harmful/forbidden call rate | 发生任一越权、写入、未登记字段泄露或明确禁止调用的任务比例 |
| 成本 | calls/turns/tokens/latency | 只在 journey success 通过的结果中报 p50/p95，同时单报失败成本 |
| 调用预算 | call-bound violation | 对匹配 scenario，成功旅程实际顶层 CLI/SDK invocation 超过声明上限的比例 |

[实证] `pass^k` 应按 τ-bench 的“k 次全成功”定义；不能用常见的 pass@k（k 次至少一次成功）替换，因为后者奖励重试抽奖。[τ-bench，第 3.2 节](https://arxiv.org/abs/2406.12045)

[推测] 不合成一个“Agent 友好总分”。发布硬门禁先设：任何 forbidden/harmful call 为失败；未登记字段不得出现在成功结果；contract smoke 的 schema-valid 必须 100%；成功路径的 call-bound violation 必须为 0。其余指标先冻结当前基线与置信区间，再做 paired、分层的非回退门禁；在没有基线前拍一个“90 分”只会制造另一个自定义真理。

### 4. A/B 与归因

[推测] 描述、schema 或路由改动每次只改一个因子；同一批 task×trial 以相同环境快照交错运行旧/新 condition，并报告每个 journey×language 的 paired difference，而不只报总平均。错误需归到 `discovery`、`wrong_tool`、`missing_clarification`、`schema_invalid`、`semantic_argument`、`tool_execution`、`recovery`、`answer_grounding`、`safety`，否则“成功率下降”无法指导接口设计。

[推测] LLM judge 只用于不能程序化判断的答案充分性，并保存 rubric、reference、judge model/version 和原始裁决；工具名、参数约束、envelope schema、状态变化与 forbidden calls 必须由代码判定。依据是 ToolEval 的裁判只达到有限人工一致率，而 τ-bench/MCPMark/WebArena 均尽量使用状态或程序化 verifier。[ToolBench](https://arxiv.org/abs/2307.16789)、[τ-bench](https://arxiv.org/abs/2406.12045)、[MCPMark](https://arxiv.org/abs/2509.24002)、[WebArena](https://arxiv.org/abs/2307.13854)

## 对本仓库的意义

[实证] 当前项目已有三项值得保留的基础：受治理 envelope 和 `schema_version` 使结果可程序校验；未登记字段 fail-closed 可成为安全硬门禁；`gravity.agent-call-bound.v1` 把已知/未知输入的顶层调用预算显式化。外部 benchmark 普遍会记录状态、调用和预算，但本次未找到与该 call-bound schema 等价的公开标准。[架构与目标](../architecture.md)、[call-bound 实现](../../src/gravity_sdk/agent_call_bound.py)

[实证] 当前短板是自然语言层尚未闭环：仓库记录的 20 个真实中英问题中，首次错路 8/20，合法终点 4/20；后续离线窄修不能改写原始结果。现行“每卡中英各一条首次命中”的判据比旧的注册恒真命题好，但样本太少、容易和关键词表共同演化，也不测参数、终局、重复可靠性、恢复或安全。[实测与判据修正](../roadmap.md)

[推测] 应借鉴：analysis journey、程序化 verifier、`pass^1/pass^4`、故障注入、held-out 中英 hard negatives、发现 token 与成功后的调用成本、候选集合评分；明确不该照搬：ToolEval 的 LLM 裁判作为唯一真值、MCP Inspector 通过即算好、跨任务固定“少于 20 工具”或一个总分、为了命中率让未登记字段 fail-open。

[推测] 近期最小落地顺序应是：先把现有 20 题原样封为不可修改的 `legacy-observed` 集；按上述 manifest 扩到 journey×language×negative 的锁定集；建立 route-only 三条件 A/B；再用少量可重置数据跑 end-to-end 和故障恢复。只有宿主 LLM 或 hybrid 在分层指标上稳定胜出，才逐步把手写 recognizer 从默认入口降为 explicit-selector/安全兜底。

## 证据缺口与未查到的问题

[实证] 没有查到关键词/规则 NLU 与宿主 LLM schema 选择在完全相同条件下的公开直接 A/B；因此本文不能声称后者必然更准。

[实证] 没有查到跨模型、跨领域公认的 tool description 最佳长度、反例数量或“不要使用”段落的独立因果阈值；现有证据相互冲突且有模型依赖。

[实证] 没有查到通用的“每个分析问题应该调用几次”标准，也没有与 `gravity.agent-call-bound.v1` 等价的行业 schema；公开工作只报告或限制各自任务的 calls/turns。

[实证] 没有查到被广泛采用、覆盖正确性、延迟、token、安全和恢复的 MCP server 认证标准；MCPBench 范围有限，Inspector 只是调试器。

[实证] 没有查到“精确字段路径＋下一步动作”在数据分析工具场景的专项 A/B；Structured Feedback 的强证据来自两个模型的 TextWorld，能证明机制但不能保证效应量迁移。

[推测] 本文最可能出错的判断是“宿主 LLM＋确定性验证/候选检索会优于当前 recognizer 并应成为默认路径”：它符合邻近 benchmark 暴露的能力边界，也针对本仓库实测失败，但缺少同任务 head-to-head；模型版本、描述质量、候选规模和中英分布都可能反转结果，所以必须让三条件 A/B 而不是观点决定迁移。
