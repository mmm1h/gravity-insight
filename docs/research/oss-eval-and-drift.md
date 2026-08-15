# Agent 评测方法学与合同漂移检测开源调研

> 调研日期：2026-08-16。本文是外部实现与论文的取证记录，不是 Gravity SDK 的行为合同。
> `[实证]` 表示已阅读所引论文的方法/实验章节或固定版本源码；`[厂商宣称]` 仅表示项目方公开说明；
> `[推测]` 表示基于证据作出的工程判断。README、排行榜和搜索摘要均不单独升级为 `[实证]`。

## 结论先行

- **[实证]** 公开 Agent 基准普遍把开发集、测试题和判分代码一起公开。τ²-bench、BFCL、
  AgentBench、MCPEval 与 MCP-Universe 的仓库都能直接读到测试任务或生成/判分逻辑；
  AgentBench 论文甚至明确写明 dev/test 均公开。它们主要靠任务划分、环境执行或动态真值提高有效性，
  并没有提供与本仓库“密文题集 + 仓库外密钥”同类的保密边界。
  [AgentBench 方法](https://arxiv.org/html/2308.03688v3)、
  [τ² task split](https://github.com/sierra-research/tau2-bench/blob/c3398666e6559e3a063da3fc04b5acf7f941464e/data/tau2/domains/airline/split_tasks.json)、
  [MCPEval splitter](https://github.com/SalesforceAIResearch/MCPEval/blob/70e1f903175a255c2967615914240f60d4d12a50/src/mcpeval/utils/data_splitter.py)
- **[实证]** 密封并不能解决反复看总分造成的适应性过拟合。Ladder 的出发点正是：即使不公开答案，
  参赛者也可通过反复提交和排行榜反馈逐步拟合 holdout；其防线是限制分数发布，而不是仅加密题目。
  本仓库已经识别出的“重复 aggregate 反馈”风险有成熟理论支持。
  [Ladder 论文](https://proceedings.mlr.press/v37/blum15.html)、
  [Reusable Holdout 论文](https://papers.nips.cc/paper_files/paper/2015/hash/bad5f33780c42f2588878a9d07405083-Abstract.html)
- **[实证]** “程序化 verifier”比单一 LLM 裁判更可审计，但并不自动等于有效真值。
  SWE-bench+ 对 251 个已成功实例的审计发现 32.67% 有解答泄漏，31.08% 因测试薄弱而可疑；
  过滤后报告的解决率从 12.47% 降到 3.97%。这是本调研中最直接的“分数涨了但能力没有相应泛化”公开复盘。
  [SWE-bench+ 方法与审计](https://arxiv.org/abs/2410.06992)
- **[实证]** LLM 裁判不适合作唯一真值的判断站得住。ToolEval 与人工在 pass-rate / win-rate 上的
  一致率分别为 87.1% / 80.3%；LiveMCPBench 结果章节中表现最好的被测裁判与人工约 78.95% 一致，
  且不同裁判波动明显。两者都表明裁判误差足以改变相邻系统排序。
  [ToolBench/ToolEval 论文](https://arxiv.org/abs/2307.16789)、
  [LiveMCPBench 方法与结果](https://arxiv.org/html/2508.01780)
- **[实证]** 本仓库四层可用性指标真正缺的不是再加一个“答对率”，而是独立的安全/约束遵守层。
  AgentDojo 把 benign utility、受攻击时仍完成合法任务的 utility、以及 targeted attack success rate
  分开报告；这证明“任务完成”和“没有执行禁止动作”不能由同一个成功位代替。
  [AgentDojo 论文](https://arxiv.org/abs/2406.13352)
- **[实证]** 合同工具没有形成“所有未知响应字段都 fail-closed”的共识。Pact 的规范测试明确允许
  provider 响应多一个键、却拒绝 consumer 请求多一个键；Schemathesis 只有在 schema 明示
  `additionalProperties: false` 时才因额外响应字段失败；oasdiff 则把新增、删除、类型变化、枚举变化
  拆成不同规则和等级。
  [Pact 响应测试](https://github.com/pact-foundation/pact-reference/blob/9930b06c31b66d835b6b3fe7b4d855f52d394b24/rust/pact_matching/tests/spec_testcases/v1/response/body/unexpected%20key%20with%20not%20null%20value.json)、
  [Pact 请求测试](https://github.com/pact-foundation/pact-reference/blob/9930b06c31b66d835b6b3fe7b4d855f52d394b24/rust/pact_matching/tests/spec_testcases/v1/request/body/unexpected%20key%20with%20not%20null%20value.json)、
  [Schemathesis checks](https://github.com/schemathesis/schemathesis/blob/c60bde9733dad2fc4ef8f6451f58a10e8c7b6663/src/schemathesis/specs/openapi/checks.py)、
  [oasdiff levels](https://github.com/oasdiff/oasdiff/blob/7f888f8ba52cc9b3ae39af456f6a22bcdf9f45ff/checker/level.go)
- **[推测]** 外部证据反对“所有新增响应字段一律当破坏”作为通用兼容性规则，但支持在隐私、投影或
  枚举穷举等明确边界上 fail-closed。Gravity 的未知字段闸门可以作为治理选择保留；文档应明确它比
  一般客户端兼容性检查更强，不要把它表述成行业默认。

## 方法与范围

- **[实证]** 调研固定到以下仓库版本：`sierra-research/tau2-bench@c339866`、
  `ShishirPatil/gorilla@6ea5797`（BFCL）、`OpenBMB/ToolBench@d56fdd8`、
  `THUDM/AgentBench@d1e4a10`、`princeton-nlp/SWE-bench@128cbd1`、
  `SalesforceAIResearch/MCPEval@70e1f90`、`SalesforceAIResearch/MCP-Universe@48b4530`、
  `schemathesis/schemathesis@c60bde9`、`apiaryio/dredd@3d4ae14`、
  `pact-foundation/pact-reference@9930b06`、`OpenAPITools/openapi-diff@63850d8`、
  `oasdiff/oasdiff@7f888f8`、`opticdev/optic@a7bf21e`、
  `alufers/mitmproxy2swagger@f432aca`、`openclarity/apiclarity@37aa375`。
- **[实证]** 取证优先级为论文方法/实验、固定提交源码与可执行规范测试；项目介绍和排行榜仅用于定位，
  不作为事实依据。对于“没有密封”“没有人工一致率”等否定性结论，仅写成“在所读论文与源码中未找到”，
  不把搜索不到提升成不存在。
- **[推测]** 本文比较的是防污染机制、测量对象和漂移发现边界，不比较模型排行榜名次；排行榜会随模型、
  API 和环境变化，且不能直接回答本仓库的装置设计问题。

## A. Agent / 工具调用评测

### τ-bench 与 τ²-bench

- **[实证]** τ-bench 用环境最终数据库状态和任务要求的响应内容做程序化判分，并用 `pass^k` 表示
  同一任务独立运行 k 次全部成功的概率。τ² 当前实现为所有适用 evaluator 奖励的乘积，包含环境状态、
  通信、动作以及实验性的自然语言断言；指标代码还记录平均奖励、成本、读写正确性、数据库匹配、授权、
  终止与响应性。
  [τ-bench 论文](https://arxiv.org/abs/2406.12045)、
  [τ² evaluator](https://github.com/sierra-research/tau2-bench/blob/c3398666e6559e3a063da3fc04b5acf7f941464e/src/tau2/evaluator/evaluator.py)、
  [τ² metrics](https://github.com/sierra-research/tau2-bench/blob/c3398666e6559e3a063da3fc04b5acf7f941464e/src/tau2/metrics/agent_metrics.py)
- **[实证]** `pass^k` 的实现是从 n 次试验的成功数 s 中计算
  `C(s,k)/C(n,k)`；它测的是“随机抽 k 次全部成功”的可靠性，而非平均成功率，也不是连续失败恢复能力。
  [τ² `pass_hat_k`](https://github.com/sierra-research/tau2-bench/blob/c3398666e6559e3a063da3fc04b5acf7f941464e/src/tau2/metrics/agent_metrics.py)
- **[实证]** τ² 把 user 与 agent 都建模为可行动主体，并用原子初始化、解法和断言组合生成任务。
  论文消融中，移除用户的主动工具能力使 GPT-4.1 与 o4-mini 的 `pass^1` 分别下降 18 和 25 个百分点；
  用户模拟器审计还测得 telecom / retail 的总错误率 16% / 40%，其中关键错误率 6% / 12%。
  这使“多主体协作失败”和“模拟用户污染判分”成为可单独观察的层。
  [τ² 方法、消融与审计](https://arxiv.org/html/2506.07982v1)
- **[实证]** 论文按每题 4 次、温度 0 运行，并报告每次试验约 0.086 美元 agent 成本和
  0.059 美元 user 成本；因此重复可靠性同时带来接近线性的推理成本。
  [τ² 实验设置](https://arxiv.org/html/2506.07982v1)
- **[实证]** 所读仓库直接提交了 task split 和任务数据，未找到密文题集、独立密钥保管者、提交预算或
  延迟披露机制。它的主要防线是任务组合、环境状态与多次运行，不是题面保密。
  [公开 split](https://github.com/sierra-research/tau2-bench/blob/c3398666e6559e3a063da3fc04b5acf7f941464e/data/tau2/domains/airline/split_tasks.json)

### BFCL

- **[实证]** BFCL 的 AST 判分器校验函数数量、名称、参数、类型和值，并分别覆盖单函数、多函数、并行调用；
  multi-turn 判分从同一初态分别执行模型调用和 gold 调用，每轮比较状态及必须返回的执行结果，
  irrelevance 类要求不调用工具。
  [AST checker](https://github.com/ShishirPatil/gorilla/blob/6ea57973c7a6097fd7c5915698c54c17c5b1b6c8/berkeley-function-call-leaderboard/bfcl_eval/eval_checker/ast_eval/ast_checker.py)、
  [multi-turn checker](https://github.com/ShishirPatil/gorilla/blob/6ea57973c7a6097fd7c5915698c54c17c5b1b6c8/berkeley-function-call-leaderboard/bfcl_eval/eval_checker/multi_turn_eval/multi_turn_checker.py)
- **[实证]** 分类还显式覆盖缺函数、缺参数、长上下文、记忆、web search、格式敏感与 live 数据。
  这比本仓库四层多出了“工具相关性/拒调”“长上下文退化”和“跨轮状态保持”三个切片。
  [BFCL categories](https://github.com/ShishirPatil/gorilla/blob/6ea57973c7a6097fd7c5915698c54c17c5b1b6c8/berkeley-function-call-leaderboard/TEST_CATEGORIES.md)
- **[实证]** 所读版本的题目与可能答案文件随仓库公开，未找到秘密 holdout 或 `pass^k` 类重复可靠性指标；
  live 类改善的是时效性，合入公开数据后并不继续提供保密性。
  [BFCL data tree](https://github.com/ShishirPatil/gorilla/tree/6ea57973c7a6097fd7c5915698c54c17c5b1b6c8/berkeley-function-call-leaderboard/bfcl_eval/data)

### ToolBench / ToolEval

- **[实证]** ToolEval 的源码调用 LLM 判断任务是否可解、最终答案是否解决任务，以及两个轨迹谁更好；
  prompt 要求考虑事实性、推理、工具调用成本、token、里程碑和探索，并允许 `Unsure` 与平局。
  [ToolEval evaluator](https://github.com/OpenBMB/ToolBench/blob/d56fdd89faf8c91fa135090b212bb9057ee5cfc2/toolbench/tooleval/evaluators/registered_cls/tooleval.py)、
  [judge template](https://github.com/OpenBMB/ToolBench/blob/d56fdd89faf8c91fa135090b212bb9057ee5cfc2/toolbench/tooleval/evaluators/tooleval_gpt-3.5-turbo_default/template.txt)
- **[实证]** 论文以人工标注核验裁判，一致率仅为 pass-rate 87.1%、win-rate 80.3%。
  这支持把 LLM judge 用作开放语义的辅助信号，但反对把它作为唯一发布闸门。
  [ToolBench/ToolEval 论文](https://arxiv.org/abs/2307.16789)
- **[实证]** LiveMCPBench 后续复查发现 ToolBench 中 55.6% 的 API 已不可用；因此实时外部 API 基准的
  “重复失败”混合了 agent 能力、凭证、服务存活和接口漂移，不能直接解释为 agent 不可靠。
  [LiveMCPBench 方法](https://arxiv.org/html/2508.01780)
- **[实证]** 所读论文与代码未找到秘密 holdout、提交反馈预算或对同一题多次独立运行的主指标。

### AgentBench

- **[实证]** AgentBench 在 8 个交互环境中分别使用成功率、F1、环境 reward、游戏进度与 step success，
  并记录超出上下文、无效格式、无效动作、达到步数/重复限制和正常完成等终止原因。
  [AgentBench 方法](https://arxiv.org/html/2308.03688v3)
- **[实证]** 论文明确说明 269 个 development 与 1014 个 test 样本全部公开；实验采用温度 0，
  未对同一题做多次生成。因此划分支持开发/测试分离，却不防预训练污染或针对测试题调优。
  [AgentBench 数据与设置](https://arxiv.org/html/2308.03688v3)
- **[推测]** 对本仓库最可借鉴的是把“无效动作/格式”“上下文耗尽”“步数耗尽”作为失败原因分解，
  而不是照搬其公开 test split。

### SWE-bench 的 held-out 与公开失真复盘

- **[实证]** SWE-bench harness 在隔离容器中应用模型 patch，再执行由 `FAIL_TO_PASS`、
  `PASS_TO_PASS` 与 `eval_script` 构造的测试规范，最终用程序化测试给出二元结果。
  当前 harness 还把二进制测试资产延后到 agent 工作结束后才放入环境，防止运行中的 shell agent 直接读取。
  [evaluation runner](https://github.com/princeton-nlp/SWE-bench/blob/128cbd1a5759694874e6bd56624cb2fd6fb079e2/swebench/harness/run_evaluation.py)、
  [TestSpec construction](https://github.com/princeton-nlp/SWE-bench/blob/128cbd1a5759694874e6bd56624cb2fd6fb079e2/swebench/harness/utils.py)
- **[实证]** 运行时隐藏测试不等于对训练者密封题集：issue、gold patch 与测试数据可公开获取。
  SWE-bench+ 审计 251 个 SWE-Agent + GPT-4 的成功样本，报告 32.67% 解答泄漏、31.08% 弱测试可疑，
  严格过滤使解决率从 12.47% 降到 3.97%。
  [SWE-bench+](https://arxiv.org/abs/2410.06992)
- **[实证]** 另一项污染研究发现两款 Claude 模型在 SWE-bench Verified 上相对新鲜基准
  BeetleBox / SWE-rebench 的表现约高 3 倍，并且仅看 issue 文本定位被修改文件的能力约高 6 倍；
  作者将此作为记忆/污染信号，而非直接证明每个答案都被记住。
  [benchmark contamination study](https://arxiv.org/abs/2512.10218)
- **[推测]** 本仓库的 32/0/0 开发集到 4/20 留出集断崖，与这些案例共同说明：必须同时审计
  题族隔离、oracle 强度和运行时隔离；只看到程序测试通过仍不足以断言泛化。

### MCPEval、MCP-Universe 与 LiveMCPBench

- **[实证]** MCPEval 默认以固定 seed 42 随机打乱后做 70/15/15 划分并把三份数据都写出，
  没有密封。静态指标按工具名、参数和顺序加权 0.4/0.4/0.2，并提供 strict/flexible 模式；
  另以 LLM judge 评价轨迹规划/执行、需求满足和答案完整性。
  [splitter](https://github.com/SalesforceAIResearch/MCPEval/blob/70e1f903175a255c2967615914240f60d4d12a50/src/mcpeval/utils/data_splitter.py)、
  [static metrics](https://github.com/SalesforceAIResearch/MCPEval/blob/70e1f903175a255c2967615914240f60d4d12a50/src/mcpeval/metrics/static_tool_eval.py)、
  [LLM metrics](https://github.com/SalesforceAIResearch/MCPEval/blob/70e1f903175a255c2967615914240f60d4d12a50/src/mcpeval/metrics/llm_multi_aspect_eval.py)
- **[实证]** MCPEval 论文承认工具调用指标衡量的是与 GPT-4.1 参考轨迹的对齐，而非绝对质量，
  因而合法的替代工具路径可能被低估。在所读论文/源码中未找到 LLM judge 与人工的一致性量化。
  [MCPEval 论文](https://arxiv.org/html/2507.12806)
- **[实证]** MCP-Universe 为 231 个任务配置 84 个执行 evaluator：格式、静态真值和在判分时
  读取当前状态的动态真值；源码逐项运行 task evaluator，并报告二元成功、evaluator 通过比例和成功步数。
  [论文方法](https://arxiv.org/html/2508.14704v1)、
  [evaluator source](https://github.com/SalesforceAIResearch/MCP-Universe/blob/48b453021694d9823d308627fb7f6b7edd29541a/mcpuniverse/evaluator/evaluator.py)
- **[实证]** MCP-Universe 论文明确拒绝用 LLM judge 判实时数据任务，理由包括静态知识、风格偏差和幻觉；
  但任务配置与 verifier 随仓库公开，在所读实现中未找到秘密 holdout 或反馈预算。
  [MCP-Universe 论文](https://arxiv.org/html/2508.14704v1)
- **[实证]** LiveMCPBench 把 95 个日常任务放在 70 个 server、527 个工具上，报告成功、步数、
  工具数、执行/路由、token 与成本；其带关键点的轨迹 LLM judge 在结果章节中最高约 78.95% 人工一致率，
  其他 judge 更低。这既补了效率层，也量化了语义裁判的噪声。
  [LiveMCPBench](https://arxiv.org/html/2508.01780)

### 其他活跃方向：安全与重复可靠性

- **[实证]** AgentDojo 的 97 个正常任务与 629 个安全测试分别报告 benign utility、攻击下仍完成正常任务的
  utility，以及 targeted attack success rate。安全不是从任务成功率推导出来的，而是独立测量恶意副作用。
  [AgentDojo](https://arxiv.org/abs/2406.13352)
- **[实证]** 除 `pass^k` 外，本次项目中常见的重复性手段是固定温度单跑（只减小采样噪声）、
  多次独立运行后报平均/方差（测期望性能与波动）、以及动态真值（测环境变化下的当前正确性）。
  它们与 `pass^k` 回答不同问题，不能互相替代。
- **[推测]** 本仓库应继续把 `pass^k` 作为发布可靠性门槛，同时保留单次 pass rate 与失败原因分布；
  只报 `pass^k` 会把“偶发解析失败”和“稳定选错产品”压成同一个零分。

### 防污染手段横向判断

- **[实证]** 本次覆盖的开源 Agent 项目中，未找到一个同时实现“题面加密、完整性校验、密钥由独立保管者持有、
  运行器不返回逐题反馈”的公开实现。多数项目用公开 split；SWE-bench 隐藏的是运行期测试资产，
  τ²/MCP-Universe 用可执行环境或动态真值，BFCL live 用较新的真实函数题。
- **[实证]** Ladder 与 Reusable Holdout 证明/分析的是另一条边界：即使答案不泄露，反复精确反馈也可让
  开发过程适应 holdout。可复用防线包括限制提交/披露、只在显著改进时更新分数，以及带统计保证的噪声机制。
  [Ladder](https://proceedings.mlr.press/v37/blum15.html)、
  [Reusable Holdout](https://papers.nips.cc/paper_files/paper/2015/hash/bad5f33780c42f2588878a9d07405083-Abstract.html)
- **[推测]** HMAC 证明“密文未被篡改/持有 key 的一方生成了标签”，并不自动提供题面机密性；
  本仓库真正的机密性来自密文封装和 key 不入 Git。它仍挡不住同机管理员/密钥持有人读题、运行期内存读取、
  反复 aggregate 反馈，以及 dev/holdout 同模板导致的题族泄漏。
- **[推测]** 对 240 题规模，优先级高于引入差分隐私的是：限定正式评测频率、预登记本次比较、只披露一次
  总体结论、按题族/来源切分并定期补充新题；这些措施直接减少当前已知攻击面，代价也更可控。

## B. API / 合同漂移检测

### Schemathesis 与 Dredd：由正式描述生成主动测试

- **[实证]** Schemathesis 以 OpenAPI schema 为输入，主动生成请求并检查状态码、content type、响应头、
  响应 schema、负向数据拒绝、必需头、授权与 stateful 资源生命周期。没有官方 schema 时，所读核心检查器
  不负责从流量反推基线。
  [checks source](https://github.com/schemathesis/schemathesis/blob/c60bde9733dad2fc4ef8f6451f58a10e8c7b6663/src/schemathesis/specs/openapi/checks.py)
- **[实证]** Schemathesis 把 server/security 失败标为 critical、schema 失败标为 high、content/header
  标为 medium；额外字段是否失败由 schema 的 `additionalProperties` 约束决定，缺省并不一律关闭。
  [failure severities](https://github.com/schemathesis/schemathesis/blob/c60bde9733dad2fc4ef8f6451f58a10e8c7b6663/src/schemathesis/core/failures.py)、
  [OpenAPI checks](https://github.com/schemathesis/schemathesis/blob/c60bde9733dad2fc4ef8f6451f58a10e8c7b6663/src/schemathesis/specs/openapi/checks.py)
- **[实证]** Dredd 把 API Blueprint/OpenAPI 2 描述转换为 transactions，向目标服务发请求，再由 Gavel
  比较实际与期望响应；错误类型可失败，而未规定的 body 可通过。它同样依赖人工已有描述，不负责推断 schema。
  [TransactionRunner](https://github.com/apiaryio/dredd/blob/3d4ae1431397990603285617fa5f7ddb81dc3992/packages/dredd/lib/TransactionRunner.js)、
  [response integration tests](https://github.com/apiaryio/dredd/blob/3d4ae1431397990603285617fa5f7ddb81dc3992/packages/dredd/test/integration/response-test.js)
- **[推测]** 两者适合 CI、测试环境或受控定时探测：覆盖率取决于 schema 与生成策略，成本是实际请求量、
  数据准备和副作用隔离；不适合未经治理地对生产写接口持续 fuzz。

### Pact：消费者驱动契约及其单边边界

- **[实证]** Pact 的可执行规范测试体现 Postel 式方向差异：provider 响应多一个非空键仍匹配，consumer
  请求多一个非空键则不匹配。这是本次调研中对“新增字段是否危险”最直接的代码级外部对照。
  [response case](https://github.com/pact-foundation/pact-reference/blob/9930b06c31b66d835b6b3fe7b4d855f52d394b24/rust/pact_matching/tests/spec_testcases/v1/response/body/unexpected%20key%20with%20not%20null%20value.json)、
  [request case](https://github.com/pact-foundation/pact-reference/blob/9930b06c31b66d835b6b3fe7b4d855f52d394b24/rust/pact_matching/tests/spec_testcases/v1/request/body/unexpected%20key%20with%20not%20null%20value.json)
- **[实证]** verifier 会依据 pact 构造请求并直接发送到配置的 provider base URL；兼容性套件还在验证前后
  调用 provider-state handler。这说明完整工作流依赖 provider 可达，并通常依赖对可重复状态的协作控制。
  [provider client](https://github.com/pact-foundation/pact-reference/blob/9930b06c31b66d835b6b3fe7b4d855f52d394b24/rust/pact_verifier/src/provider_client.rs)、
  [provider-state feature](https://github.com/pact-foundation/pact-reference/blob/9930b06c31b66d835b6b3fe7b4d855f52d394b24/compatibility-suite/pact-compatibility-suite/features/V3/http_provider.feature)
- **[推测]** 上游不配合时可以把 Pact interaction 当作本客户端自有的 live probe，技术上不要求对方知道 Pact；
  但这只是“单边重放契约”，得不到上游发布闸门、provider state、变更通知或修复义务。鉴权、限流、随机数据
  和写副作用也会使验证不稳定，因此不能声称获得了完整的消费者驱动契约保障。

### openapi-diff、oasdiff 与 Optic：差异方向和等级

- **[实证]** openapi-diff 把 schema 的新增属性、缺失属性和属性变化分别记录，并计算方向性的兼容结果；
  类型变化进入独立 changed-schema 分析。它比较两份 OpenAPI，不从运行流量建立基线。
  [SchemaDiff](https://github.com/OpenAPITools/openapi-diff/blob/63850d8074452f5761ce7e7e460307f0f127647a/core/src/main/java/org/openapitools/openapidiff/core/compare/SchemaDiff.java)、
  [ChangedSchema](https://github.com/OpenAPITools/openapi-diff/blob/63850d8074452f5761ce7e7e460307f0f127647a/core/src/main/java/org/openapitools/openapidiff/core/model/ChangedSchema.java)
- **[实证]** oasdiff 为响应 optional property 新增/删除、required 变化、类型 specialized/generalized/changed、
  enum 新值分别设规则；等级为 error/warn/info/none，可逐规则覆盖，默认 backward-compatibility 检查筛出
  warning 以上。它没有把所有变化压成同一个 fingerprint mismatch。
  [optional property rules](https://github.com/oasdiff/oasdiff/blob/7f888f8ba52cc9b3ae39af456f6a22bcdf9f45ff/checker/check_response_optional_property_updated.go)、
  [type rules](https://github.com/oasdiff/oasdiff/blob/7f888f8ba52cc9b3ae39af456f6a22bcdf9f45ff/checker/check_response_property_type_changed.go)、
  [enum rule](https://github.com/oasdiff/oasdiff/blob/7f888f8ba52cc9b3ae39af456f6a22bcdf9f45ff/checker/check_response_property_enum_value_added.go)、
  [levels](https://github.com/oasdiff/oasdiff/blob/7f888f8ba52cc9b3ae39af456f6a22bcdf9f45ff/checker/level.go)
- **[实证]** Optic 能从 proxy、HAR 或 Postman 捕获交互，与既有 OpenAPI 做 verify，或用交互/自动模式
  更新文档；其 diff 命令按 info/warn/error 控制退出码。它连接了“观察到的流量”和“可进 CI 的 spec diff”。
  [capture command](https://github.com/opticdev/optic/blob/a7bf21ebc3ff1fa19d167efb5cac44c5e9a2a456/projects/optic/src/commands/capture/capture.ts)、
  [undocumented actions](https://github.com/opticdev/optic/blob/a7bf21ebc3ff1fa19d167efb5cac44c5e9a2a456/projects/optic/src/commands/capture/actions/undocumented.ts)、
  [diff command](https://github.com/opticdev/optic/blob/a7bf21ebc3ff1fa19d167efb5cac44c5e9a2a456/projects/optic/src/commands/diff/diff.ts)
- **[推测]** 纯 spec diff 成本最低且适合每次 CI，但只能发现进入 base/revision spec 的变化；capture 能补未知接口，
  覆盖率仍受采样流量限制。两者结合优于只比单个全局 fingerprint，因为能回答“哪里、朝哪个方向变化”。

### 无官方 schema：mitmproxy2swagger 与 APIClarity

- **[实证]** mitmproxy2swagger 从 mitmproxy dump 或 HAR 生成 OpenAPI 3，可在已有输出上累积 endpoint；
  新 path 先以 `ignore:` 标记，需人工确认，路径参数用正则推断，JSON/msgpack/form body 用样本推断 schema。
  这是“录制样本 + 人工登记”的单边逆向合同。
  [source](https://github.com/alufers/mitmproxy2swagger/blob/f432acafa5907258f0f529ff582c75fefdca00d7/mitmproxy2swagger/mitmproxy2swagger.py)
- **[实证]** 该实现对若干结构采用“key 不存在才写”的策略，因此早期样本可能主导状态码/形状；CLI 还警告保存
  examples 或 headers 可能泄露敏感信息。样本推断扩大覆盖，也引入代表性与隐私风险。
  [schema inference source](https://github.com/alufers/mitmproxy2swagger/blob/f432acafa5907258f0f529ff582c75fefdca00d7/mitmproxy2swagger/mitmproxy2swagger.py)
- **[实证]** APIClarity 的 spec-reconstructor 模块从 traces 重建 OpenAPI 并可按 API 启停采样；spec-differ
  在 API event 到达时把遥测与 provided 或已批准的 reconstructed spec 比较，分类为 shadow、zombie、
  general 或无差异，并支持唯一差异阈值后停止继续记录。
  [reconstructor](https://github.com/openclarity/apiclarity/blob/37aa375062605a2e5b516cf8356215b608ae4d6c/backend/pkg/modules/internal/specreconstructor/specreconstructor.go)、
  [spec differ](https://github.com/openclarity/apiclarity/blob/37aa375062605a2e5b516cf8356215b608ae4d6c/backend/pkg/modules/internal/spec_differ/spec_diffs.go)
- **[推测]** 对不知道本客户端存在的上游，现实可行的单边基线依次是：人工登记权威字段、用脱敏样本补候选、
  人工批准后固化，再用定时只读 probe 与旁路采样查漂移。直接把一次样本推断结果当权威会把偶然缺字段、
  个体数据和错误响应固化进合同。

### fail-open / fail-closed 与运行位置

- **[实证]** Pact 的响应宽松/请求严格、Schemathesis 对 `additionalProperties` 的遵从，以及 oasdiff 的分级规则
  都反对“任何响应新增字段 = 同等级破坏”作为默认兼容政策；oasdiff 也提示响应 enum 新值可能令穷举客户端意外，
  所以“新增”并不总安全。
- **[实证]** Schemathesis 将 schema 违约列为 high、server/security 列为 critical；oasdiff 把字段消失、
  required/type/enum 方向变化单独分类。外部实现共同支持在已声明安全/类型边界上阻断，而非对所有 diff 同判。
- **[实证]** 在所读项目论文与源码中，未找到一项受控研究量化“生产中对未知响应字段 blanket fail-closed
  与 fail-open”的真实事故率或业务后果。这里能取证的是工具的可执行默认与规则，不是实际后果比较。
- **[推测]** 运行位置形成覆盖/代价梯度：OpenAPI diff 放 CI/PR，几乎无上游请求但只见声明变化；
  Dredd/Schemathesis/Pact 单边模式放测试或定时任务，会产生真实请求；Optic/HAR 用已发生交互补覆盖；
  APIClarity 类旁路生产遥测覆盖最真实，却付出采集、脱敏、存储与采样盲区成本。

## 对本仓库的意义

### 四层指标漏了什么

- **[推测]** **应补：安全/约束遵守层。** 单独统计 forbidden/harmful action、越权读取、未授权写入和敏感输出；
  成功必须是“任务完成且无禁止副作用”。AgentDojo 提供了任务效用与攻击成功分离的外部实证。
  若复用现有程序化 trace、operation allowlist 与投影/隐私闸门，成本主要是定义少量负例和失败码，
  不需要 LLM 裁判；这是唯一建议升格为第五发布层的项目。
- **[推测]** **应补为切片，不升格：多轮/上下文压力。** BFCL 和 AgentBench 证明长上下文、缺参补全、跨轮状态
  会形成独立失败模式；但它更适合按 journey 标注 `turn_count/context_band` 后分层报告，否则每条单轮读取也要
  人为拉长，题量和推理成本都会显著增加。
- **[推测]** **应记录为诊断遥测，不作正确性层：调用数、token、成本、延迟。** τ² 与 LiveMCPBench 都报告这些值，
  它们可发现“正确但不可用”的退化；然而网络和模型供应商噪声大，适合预算/回归警报，不宜与语义正确性相乘。
  成本是保存每次 trial 的 usage/timing，并维护环境可比性。
- **[推测]** **应放入恢复层：幂等性/重试安全。** 本仓库主能力为 read，单独做全局层收益较低；对分页、导出轮询、
  超时重试和未来写操作，应验证同一 request id/游标不会重复副作用。成本集中在可重复 sandbox 与故障注入。
- **[推测]** **应补为 oracle 健康度：模拟器/验证器错误率。** τ² 的 user simulator 关键错误率和 SWE-bench+
  的弱测试审计说明，除了 agent 分数，还要抽样复核题面可解性、参考终点与 verifier。它不是 agent 能力层，
  却决定四层分数能否被解释。

### 留出集密封与外部做法

- **[实证]** 相比本次覆盖的公开 Agent 基准，本仓库的密文题集、仓库外 key、完整性校验、无逐题反馈更强；
  未找到同类开源实现可以直接替换它。SWE-bench 的运行时隐藏测试解决的是 agent 偷看，不解决维护者/训练者污染。
- **[推测]** 本仓库较弱处有四个：同机管理员或 key 持有人仍可读；解密后题面/答案存在进程内存；反复总分会形成
  自适应反馈信道；若 dev/holdout 共享题面模板或来源，密封不能阻止题族过拟合。HMAC 只覆盖认证/完整性，
  不是以上风险的防线。
- **[实证]** Ladder/Reusable Holdout 直接支持第三项风险；SWE-bench+ 与新鲜基准研究支持内容污染和 oracle
  薄弱会制造虚高，但没有证明本仓库已经发生密钥泄露。
- **[推测]** 下一步应先管“使用协议”而非换密码学：独立保管人限制正式运行次数，预登记比较，避免反复披露分层差值，
  以新题/新来源做最终确认，并记录每次访问。240 题上直接移植差分隐私排行榜可能损失过多分辨率，需另行论证。

### fail-closed 是否有外部支持

- **[实证]** **反对 blanket 规则的证据更直接。** Pact 可执行规范允许新增响应键，Schemathesis 默认服从开放 schema，
  oasdiff 进行方向和等级分类；所以“客户端兼容性”语境下，未知可选响应字段通常不与字段消失/类型变化等价。
- **[实证]** **支持窄边界 fail-closed 的证据也存在。** 明示关闭的 schema、必需字段消失、类型不兼容、响应 enum
  扩展、授权/安全失败会被相应工具阻断或提升等级；新增字段在投影与隐私边界上也可能不是无害兼容变化。
- **[推测]** Gravity 当前对未登记字段 fail-closed 的最强理由是“投影/隐私治理”，不是普通反序列化兼容性。
  因此选择可以保留，但证据不支持把新增字段、字段消失和类型变化都解释成同一种风险；至少在诊断与响应优先级上
  应保留方向分类。本文不改闸门实现。

## 最可能出错的判断与未决清单

- **[推测]** **最可能出错：把公开仓库中没找到密封机制写成项目绝对没有。** 本文只声称在固定版本源码与所读论文
  中未找到；托管排行榜可能另有未公开题集、提交限额或内部审计。
- **[推测]** **最可能出错：把 HMAC 当加密。** 若实际封装另有 AEAD/加密层，HMAC 只应被描述为完整性/认证组件；
  本文没有读取、运行或尝试解密留出集，结论来自仓库已有方法说明。
- **[实证]** MCPEval 的论文和源码没有给出本次能定位到的人工裁判一致率；因此不能把它的 LLM 多维分数当成
  已验证的人类替代物。
- **[实证]** 未找到开源 Agent 基准公开复盘“因反复 aggregate 分数而适应性过拟合”的具体工程事故；
  找到的是 Ladder/Reusable Holdout 理论与 SWE-bench 的内容污染/弱 oracle 实例，两类风险相关但不相同。
- **[实证]** 未找到上述合同工具对 blanket fail-open 与 fail-closed 做受控生产后果比较；本文对 Gravity 的判断
  是从规则源码和风险边界外推，不是事故统计。
- **[推测]** Live API 基准的失败会混合上游漂移、凭证/限流和 agent 错误。若未来引用其排行榜，必须先拆分基础设施
  可用性，不应把一次 endpoint 失效算成模型能力退化。
- **[推测]** 未决：第五层安全题的最小集合、正式 holdout 年度/季度补题频率、题族隔离方法，以及新增字段在隐私审查前
  是硬失败还是隔离告警，都需要结合本仓库真实失败样本另行裁决。

## 标注统计

按以标签开头的结论条目计数：实证 55 条，厂商宣称 0 条，推测 24 条；标题、图例和本统计句不计入。
