# 数数科技 / ThinkingAI 深挖与国内外分析平台 Agent 形态

> 调研日期：2026-08-15。本文只研究公开、无需登录的信息。标注规则：`[实证]` 表示可以由公开文档、API 参考、源码或可复现实测直接核对；`[厂商宣称]` 表示仅有厂商营销页、新闻稿或疑似投放稿支撑；`[推测]` 表示本文依据已列证据作出的判断。标注统计只数正文中加粗的三类标签，不数本说明。

## 结论先行

- **[实证]** ThinkingAI 公开了 MCP 客户端配置和唯一一个 `query_retention` 调用示例，但没有公开 `tools/list`、参数 JSON Schema、输出 Schema 或完整 tool 清单；其配置所指的 `@thinkingdata/mcp-server` 在本次访问 npm 公共注册表时返回 404，所以“公开可复现的 MCP 产品面”目前尚不能成立。[MCP 页](https://www.thinkingai.cn/product/mcp-service/)｜[首页示例](https://www.thinkingai.cn/)｜[npm 包地址](https://registry.npmjs.org/%40thinkingdata%2Fmcp-server)
- **[实证]** ThinkingAI 的 Skill 公共页不是只有一句 prompt：页面公开了适用前提、数据路径、分步方法和结构化结果回放；但没有可下载 Skill 文件或运行时合同，因此只能证实“步骤化分析配方”，不能证实它在引擎内究竟是 prompt、代码、工作流 DAG 还是几者组合。[付费归因 Skill](https://www.thinkingai.cn/skills/payment-attribution-analysis/)｜[Skill 库](https://www.thinkingai.cn/product/skills-library/)
- **[实证]** 在本文点名的 21 家/组产品中，20 家有平台内嵌分析 Agent 或 AI 分析入口，15 家同时公开了可让外部程序或 Agent 使用的 MCP、对话 API、CLI/Skill 或 agent API；到 2026 年，“内嵌 + 对外暴露”已明显比只做 Web 聊天更常见，逐项来源与计数口径见[形态矩阵](#d1-21-家样本的形态计数)。
- **[实证]** 与本仓库最接近的公开产品不是某个聊天框，而是 Mixpanel Headless：官方提供 typed Python SDK + CLI，覆盖五种查询引擎、对象 CRUD 和治理面，并明确面向可重复、无人值守的 Agent 工作流；差别是它仍由上游厂商维护，并非第三方为一个未开放 Agent 面的平台补客户端。[Headless 文档](https://mixpanel.github.io/mixpanel-headless/)｜[发布说明](https://mixpanel.com/blog/mixpanel-headless/)
- **[推测]** 市场真正的分水岭不是“有没有 LLM”，而是 Agent 能否只在受治理的语义/指标对象上执行，以及答案能否回溯到实际查询；Snowflake、Looker、ThoughtSpot、Databricks 和 Amplitude 都把语义层或受信对象放在模型与查询引擎之间，这比单纯提高 text-to-SQL 模型能力更接近本仓库需要守住的边界。[Snowflake semantic view](https://docs.snowflake.com/en/user-guide/views-semantic/semantic-view-yaml-spec)｜[Looker 原理](https://docs.cloud.google.com/looker/docs/conversational-analytics-overview)｜[ThoughtSpot 语义层](https://www.thoughtspot.com/blog/spotter-semantics)｜[Databricks trusted assets](https://docs.databricks.com/aws/en/genie/talk-to-genie)｜[Amplitude official objects](https://amplitude.com/docs/data/object-management)

## 方法、范围与失败入口

- **[实证]** 实际使用了四类手段：搜索引擎检索；直接打开官方文档/API 页面；`curl` 抓取 HTML 与 Next.js 静态 bundle；对 npm 公共 registry 做匿名 GET。关键原文快照和失败响应保存在 `tmp/codex/vendor-agent-landscape/sources/`，URL 清单位于该目录的 `README.md`；这些本地材料不属于提交产物。
- **[实证]** ThinkingAI 侧实际尝试了官网首页、MCP/Skill/全域感知/私有化/五类 Agent 页面、发布博客、招聘页，旧 `doc.thinkingdata.cn` Open API 文档，站内限定搜索、公开 npm scope 搜索和前端 bundle 检索；除 `query_retention` 外没有找到第二个官方 MCP tool 名，也没有找到 MCP endpoint、`tools/list` 输出或 schema 页面。[MCP 页](https://www.thinkingai.cn/product/mcp-service/)｜[旧 Open API](https://doc.thinkingdata.cn/ta-manual/v3.0/technical_document/open_api/query_api.html)
- **[实证]** 官方 YouTube 演示页能够读到标题 *Introducing Agentic Engine — ThinkingAI Product Demo*，但播放被 YouTube 的“登录以确认不是机器人”门槛阻断；本次没有登录。官网“申请体验”是表单，本次也没有填写。因此后文“真实交互”只描述官网可见的脚本化回放，不把它写成亲手操作过的 live demo。[YouTube 演示页](https://www.youtube.com/watch?v=s4HS1rscrS4)｜[LinkedIn 官方转发](https://www.linkedin.com/posts/thinkingaio_introducing-agentic-engine-thinkingai-product-activity-7450716499079532544-uSDa)
- **[实证]** 火山引擎部分页面的普通 HTML 抓取只返回壳页，正文通过公开文档索引读取；GrowingIO 页面在本机 `curl` 出现 TLS handshake 失败，正文由搜索引擎缓存的官方页面读取。没有尝试绕过登录、付费或授权限制。失败记录位于本地 `tmp/codex/vendor-agent-landscape/sources/README.md` 的 `domestic-comparison` 小节。

## 先统一三个概念

- **[实证]** “帮你写查询”是把自然语言翻译成 SQL/查询配置，并让用户检查中间结构；百度 Sugar BI 会显示维度、度量、过滤器和 SQL，Mixpanel Agent 生成的报告也可进入 query builder 编辑。[Sugar 使用文档](https://cloud.baidu.com/doc/SUGAR/s/Xlpqgy2fl)｜[Mixpanel Agent/Spark](https://mixpanel.com/blog/spark-bringing-generative-ai-to-mixpanel/)
- **[实证]** “帮你得到答案”还包括拆题、调用多个查询或 Python、解释结果、给出来源与追问；火山深度研究、Looker Advanced Analytics、Snowflake Cortex Agents 都公开了这条多步链路。[火山深度研究](https://docs.volcengine.com/docs/86760/1874909?lang=zh)｜[Looker 概览](https://docs.cloud.google.com/looker/docs/conversational-analytics-overview)｜[Snowflake Cortex Agents](https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-agents)
- **[推测]** 两者不是互斥产品类别，而是成熟度阶梯：若中间查询、指标定义和来源不可检查，“答案型”Agent 反而比“查询型”助手更难治理；依据是 Looker 和 Sugar 都把中间计算结构开放给用户，而 Snowflake 把语义对象置于 Agent 之前。[Looker 可解释界面](https://docs.cloud.google.com/looker/docs/conversational-analytics-looker-data)｜[Sugar 使用文档](https://cloud.baidu.com/doc/SUGAR/s/Xlpqgy2fl)｜[Snowflake semantic view](https://docs.snowflake.com/en/user-guide/views-semantic/semantic-view-yaml-spec)

## A. ThinkingAI（原 ThinkingData / 数数科技）深挖

### A1. MCP：公开了接法，未公开合同

- **[实证]** MCP 产品页给出的 Claude Desktop 配置是：

  ```json
  {
    "mcpServers": {
      "thinking-ai": {
        "command": "npx",
        "args": ["-y", "@thinkingdata/mcp-server"],
        "env": { "API_TOKEN": "YOUR_TOKEN" }
      }
    }
  }
  ```

  同一页前端 bundle 还包含 Python `Client("thinking-ai").connect(command="npx", args=["-y", "@thinkingdata/mcp-server"])` 和 Node `new McpServer({name:"thinking-ai", version:"1.0.0"})` 两段展示代码。[官方 MCP 页](https://www.thinkingai.cn/product/mcp-service/)

- **[实证]** 官网目前唯一可定位的工具调用是：

  ```javascript
  await mcp.callTool({
    name: "query_retention",
    args: { timeframe: "last_7_days", cohort: "new_users" }
  })
  ```

  页面同时列出“数据查询、智能分析、触发工作流、报告生成、仪表盘创建”五类能力，但没有把它们映射为 tool 名或 schema。[官网 MCP 区块](https://www.thinkingai.cn/)

- **[实证]** 2026-08-15 匿名请求 npm registry 的精确包名返回 `404 {"error":"Not found"}`，scope 搜索也返回 0 个对象；这只能证明它不是当时公开可下载的 npm 包，不能排除客户私有 registry、登录后包或尚未发布。[registry URL](https://registry.npmjs.org/%40thinkingdata%2Fmcp-server)｜[npm 搜索](https://www.npmjs.com/search?q=%40thinkingdata)
- **[厂商宣称]** 官网说 MCP “双向集成”、兼容主流 AI 平台、具有权限和审计，并在首页称 OAuth 2.0、细粒度权限、交互图表和“毫秒级响应”；没有公开 OAuth scopes、审计事件、权限对象、延迟测试或协议抓包，本报告不把这些当已验证合同。[MCP 页](https://www.thinkingai.cn/product/mcp-service/)｜[首页](https://www.thinkingai.cn/)
- **[推测]** 旧分析 API 很可能是 MCP 的一个底层能力来源，因为它已经有留存、漏斗、事件、分布、路径、用户属性等固定分析端点；但没有证据证明 `query_retention` 与 `/open/retention-analyze` 一一映射，也不能由旧 API 反推出 MCP 参数。[旧 Query API](https://doc.thinkingdata.cn/ta-manual/v3.0/technical_document/open_api/query_api.html)

**[实证]** 旧版公开文档能核对的真实端点包括以下六个分析入口。[Query API](https://doc.thinkingdata.cn/ta-manual/v3.0/technical_document/open_api/query_api.html)

```text
POST /open/event-analyze
POST /open/retention-analyze
POST /open/funnel-analyze
POST /open/distribution-analyze
POST /open/path-analyze
POST /open/user-prop-analyze
```

- **[实证]** 这些端点的请求不是简单的 `timeframe/cohort`，而包含 `projectId`、`eventView`、`events`、`filts`，其中过滤器有 `tableType`、`columnName`、`comparator`、`ftv`，另有 group-by 与时间字段；旧文档还列出对应 user-list 和 user-event-list 读取端点。[请求参数文档](https://doc.thinkingdata.cn/ta-manual/v3.0/technical_document/open_api/query_api.html)

### A2. 100+ Skill：公开形态是“方法 + 步骤 + 结果回放”

- **[实证]** Skill 总页按付费、用户、运营、舆情、数据工程、Agent、知识库、数据采集、数据分析、异常诊断、游戏分析等类别展示条目；主页和 Skill 页的类别/数量并不完全一致，说明“100+”是动态产品目录而不是一个已发布版本的固定 manifest。[Skill 库](https://www.thinkingai.cn/product/skills-library/)｜[首页](https://www.thinkingai.cn/)
- **[实证]** “付费归因分析”详情页的公开数据结构至少包含价值说明、简介、痛点、适用场景、案例、FAQ 和 `replay`；回放按总步骤数、每步标题/说明/结果、最终表格组织。页面不是一组裸 prompt。[Skill 详情](https://www.thinkingai.cn/skills/payment-attribution-analysis/)
- **[实证]** 该回放的实际交互是：用户问“月付费率从 5.2% 掉到 4.8%，钉死原因”；系统依次做近 6 个月 ±2σ 异常判定、付费人数/活跃人数分子分母拆解、付费档位下钻、商品节点定位、版本变更交叉核对，最终把下降关联到 20–40 级商品和 v5.1 免费资源调整，并展示分子分母与档位表格。[Skill 详情](https://www.thinkingai.cn/skills/payment-attribution-analysis/)
- **[实证]** LTV 预测条目在前端公开数据中还给出三项前置门槛、AE CLI 数据路径、SciPy `curve_fit` 和参数/预测表输出，这比“预置问法”更接近可执行分析配方。[Skill 库](https://www.thinkingai.cn/product/skills-library/)
- **[推测]** 最稳妥的运行时判断是：Skill 是把领域说明、可用工具、查询/代码步骤和输出期望封装在一起的可执行 playbook；依据是公开 replay 与 LTV 条目的 CLI/代码/输出字段，究竟以 Markdown、prompt template、工作流 JSON、代码包还是内部 DSL 存储仍无法判断。[Skill 详情](https://www.thinkingai.cn/skills/payment-attribution-analysis/)｜[Skill 库](https://www.thinkingai.cn/product/skills-library/)
- **[厂商宣称]** 公司称这些 Skill 来自十年、1500+ 企业和 8000+ 产品经验，并可由客户把自身经验“编码”为可迁移 Skill；没有公开版本、验收集、准确率定义或客户 Skill 样本。[发布博客](https://thinkingai.cn/blog/7a3f9c2d/)｜[MiniMax 合作稿](https://www.thinkingai.cn/blog/d2c8f5b3/)

### A3. 多 Agent：可见的是中心编排与业务回流，不是 A2A wire contract

- **[厂商宣称]** 官方架构文把平台分为策略层、编排层、执行层，称统一 Orchestrator 负责任务调度、状态和上下文，多个专业 Agent 执行后把结果回传；这是一张产品架构说明，没有消息协议、状态机、重试语义或 trace 样本。[发布博客](https://thinkingai.cn/blog/7a3f9c2d/)
- **[实证]** 自定义 Agent 页公开了一条明确业务链：“分析 Agent 识别流失风险 → 运营 Agent 调度 50 万用户推送 → 实验 Agent 完成初步显著性计算”，并写明“分析 → 运营”“运营 → A/B”两条联动。[自定义 Agent 页](https://www.thinkingai.cn/agent/custom/)
- **[实证]** 运营 Agent 页进一步描述交接：接收分析 Agent 的洞察，创建活动，活动效果回流 A/B Agent；数据分析 Agent 页则称洞察可直接流转给其他 Agent 触发行动。[运营 Agent](https://www.thinkingai.cn/agent/engage/)｜[分析 Agent](https://www.thinkingai.cn/agent/analysis/)
- **[实证]** 数据采集 Agent 的公开职责是生成埋点方案、多平台 SDK 代码并验证数据质量；官方三层架构的执行层举例却主要是分析、A/B、运营和自定义 Agent。因此“采集/分析/实验/运营四个平级 Agent 连续交接”并未被公开材料完整证实，采集更像上游数据准备面。[采集 Agent](https://www.thinkingai.cn/agent/collection/)｜[发布博客](https://thinkingai.cn/blog/7a3f9c2d/)
- **[推测]** 目前可支持的机制图是“中央 Orchestrator 持有任务/上下文，Agent 通过业务产物交接，实验结果再写回知识”；依据是官方架构文与自定义 Agent 时间线。不能支持的说法是“Agent 之间直接用 A2A 发送某个公开 envelope”，因为没有公开 payload、topic、回调或状态 schema。[发布博客](https://thinkingai.cn/blog/7a3f9c2d/)｜[自定义 Agent](https://www.thinkingai.cn/agent/custom/)
- **[实证]** 官方招聘页当前只公开长期招聘入口；被抓取的站点 bundle 曾出现 ClickHouse/Kafka 后端要求及 RAG、多模态知识库、微调方向，但没有可用于验证 Agent handoff 的岗位设计文档。专利关键词检索也没有找到能够确认属于该公司 Agentic Engine 的多智能体专利。[招聘页](https://www.thinkingai.cn/careers/)

### A4. “全域感知”：列出了来源，没公开接入合同

- **[实证]** 官方页列出的行为数据包括登录/活跃/留存、付费/转化/漏斗、关卡/任务/成就、社交互动；用户反馈包括客服对话、应用商店评论、问卷、投诉；外网包括 TapTap、好游快爆、微博、小红书、B站、抖音、Discord 和论坛；知识库包括产品文档、设计规范、复盘、会议总结、行业/竞品报告、FAQ。[全域感知](https://www.thinkingai.cn/product/total-context/)
- **[厂商宣称]** 同页称可通过 SDK、Data Hub、文档、API、邮件接入，并做历史全量和增量同步；没有公开某个舆情 connector 的授权方式、抓取频率、去重/身份关联 schema，也没有知识库 chunk、embedding、权限继承或删除协议。[全域感知](https://www.thinkingai.cn/product/total-context/)
- **[厂商宣称]** 发布博客称语义层 + 知识图谱会结构化“DAU 算法、自然周/运营周、GMV/实收”等隐性知识，并把过往实验和运营效果写入记忆；没有公开知识图谱 ontology 或冲突解决规则。[发布博客](https://thinkingai.cn/blog/7a3f9c2d/)

### A5. 私有化和 MiniMax：边界仍然模糊

- **[厂商宣称]** 私有化页称系统可部署在客户基础设施，数据、模型和推理本地，交付流程是需求评估、方案设计、环境/网络准备、自动化安装与调优、验收、持续运维；公开页没有 CPU/GPU 型号、显存、节点数、Kubernetes/Docker、模型量化、吞吐或容量表。[私有化页](https://www.thinkingai.cn/product/self-hosted/)
- **[厂商宣称]** 双方新闻稿称 MiniMax 是私有化部署的模型底座，ThinkingAI 提供行业场景和 Agentic Engine，MiniMax 提供意图理解、策略生成和长程任务所需的模型能力；没有说明模型权重由谁交付、推理 runtime 谁运维、许可证/升级/微调边界，也没有说明是否必须使用 MiniMax。[合作稿](https://www.thinkingai.cn/blog/d2c8f5b3/)｜[发布博客](https://thinkingai.cn/blog/7a3f9c2d/)
- **[推测]** “数据、模型、推理本地”与“MiniMax 作为底座”最可能意味着客户环境内同时部署 Agent 平台和经授权的 MiniMax 模型服务，但公开证据不足以判断是权重交付、私有 endpoint 还是混合云托管。[私有化页](https://www.thinkingai.cn/product/self-hosted/)｜[MiniMax 合作稿](https://www.thinkingai.cn/blog/d2c8f5b3/)

### A6. 能看到的交互与不能看到的 demo

- **[厂商宣称]** 官网首页脚本演示从“昨日新大区 Day-3 留存下降 14%”开始，显示 20 步漏斗扫描、与历史基准对比、定位新手引导节点、生成策略和人群包，最后出现“关卡难度 -15%”和“一键下发执行”；这是营销动效，不是可复现实测。[首页](https://www.thinkingai.cn/)
- **[实证]** 运营 Agent 页公开的逐步 UI 回放是：用户问“帮我策划一个活动，召回最近流失的高价值用户”→系统给出目标、流失/价值筛选条件、生成的 Push 文案、建议发送窗口和预估指标→用户可点“修改方案”或“立即执行”。[运营 Agent](https://www.thinkingai.cn/agent/engage/)
- **[实证]** 除上述脚本回放和 Skill replay 外，本次没有拿到无需身份即可操作的 sandbox、完整发布会录像或可播放的产品 walkthrough；公开入口最终落到表单或受 YouTube 登录门槛影响。[YouTube 演示页](https://www.youtube.com/watch?v=s4HS1rscrS4)｜[官网 Demo 入口](https://www.thinkingai.cn/)

### A7. ThinkingAI 仍未回答的关键问题

- **[实证]** 未找到：完整 MCP tool 清单、任何 tool 的正式 input/output schema、`tools/list` 实录、OAuth scopes、错误分类、分页/调用次数、版本协商、公开 SDK/API 参考、可下载 Skill artifact、Agent handoff payload、私有化 sizing 表、MiniMax 部署责任矩阵。已尝试入口及 URL 见本地 `tmp/codex/vendor-agent-landscape/sources/README.md` 的 `thinkingai--thinkingdata` 小节。
- **[推测]** 因此 ThinkingAI 当前最可信的对标价值在“产品意图与分析方法呈现”，而不是“公开 Agent 合同”；依据是 Skill replay 的细节与 MCP 合同的空缺形成鲜明反差。[Skill 详情](https://www.thinkingai.cn/skills/payment-attribution-analysis/)｜[MCP 页](https://www.thinkingai.cn/product/mcp-service/)

## B. 国内其他平台

### B1. 火山引擎 DataAgent / 智能分析 Agent

- **[实证]** 智能问数 Agent 连接数据集，并以语义模型和业务知识解释自然语言；深度研究 Agent 会先生成“问题定义 → 假设验证 → 结论推导”提纲，再调用 SQL 数据集工具与 Python，最后输出带数据来源的文档或 Web 报告。[产品概述](https://www.volcengine.com/docs/85637/1563626?lang=zh)｜[深度研究](https://docs.volcengine.com/docs/86760/1874909?lang=zh)
- **[实证]** 语义模型配置的公开粒度是给数据集/字段改业务名和描述；业务知识库可登记术语/歧义表达、字段组合和数据范围，并配置 0–1 匹配阈值与召回条数（文档建议 2–5）。[数据集配置](https://www.volcengine.com/docs/85637/1860219?lang=zh)
- **[实证]** 深度研究的知识不是单一 glossary，而分成业务知识（指标、事件、流程）、分析模板（标准步骤及完整查询逻辑）和历史分析报告三类；另可使用联网搜索和外部 MCP 工具。[深度研究](https://docs.volcengine.com/docs/86760/1874909?lang=zh)
- **[实证]** “步骤干预”是可见、可回算的 UI 操作：执行中可修改模型规划的某一步；报告生成中修改一步会重跑该步和下游；报告完成后可选择同步下游或只改当前步，再点重新生成。系统还展示步骤进度和详情，并允许回看步骤。[深度研究](https://docs.volcengine.com/docs/86760/1874909?lang=zh)
- **[实证]** 对外面不是 MCP server，而是会话 OpenAPI：创建/获取/更新会话、`chatCompletion` 和取结果；流式事件包含 `code`、`tool`、`interpret`、`debug`，多路径用 `round_id`、`is_major` 标识。产品自身另可消费外部 MCP。[OpenAPI](https://docs.volcengine.com/docs/85637/2123149?lang=zh)

### B2. 神策数据

- **[实证]** Sensors AI 在平台内公开五类场景 Agent（人群、单用户洞察、运营策略、报告、深度分析）和六类 Skill，并描述统一编排、OpenAPI/SDK、知识/记忆、权限、审计、引用及人工协同。[Sensors AI](https://www.sensorsdata.cn/engines/SensorsAI.html)
- **[实证]** 更接近本仓库的是官方 Sensors CLI：文档明确面向 Claude Code、Cursor、Codex，配置 Base URL、API Key、Project 后，可由 Agent 查询元数据和数据，管理看板、人群/标签、归因与埋点实现，并返回结构化输出；这证明神策不是只把 AI 绑在 Web UI 里。[Sensors CLI](https://manual.sensorsdata.cn/sa/docs/1hEXIJZs/v0300)
- **[实证]** 神策另有受用户权限约束的 OpenAPI，但本次未找到官方 MCP server 或 CLI 的公开源码、命令全量 schema 和稳定版本合同。[OpenAPI](https://manual.sensorsdata.cn/openapi)

### B3. 其余国内厂商，一句话形态

| 厂商 | 形态与治理层 |
|---|---|
| GrowingIO | **[实证]** IntelliQuery 是平台内嵌自然语言问数；以事件、属性、标签和分群元数据做解释并返回置信信息，公开页当时称单事件/属性/复合指标已支持、漏斗和留存仍在迭代。[官方产品页](https://www.growingio.com/products/IntelliQuery) |
| 易观 | **[实证]** 本次只找到易观自己的行业研究/市场情报服务和关于 Agent 市场的内容，没有找到可核对的易观“问自有行为数据”Agent、MCP 或分析 API 产品页；因此不把它强行归类为已有产品。[易观分析官网](https://www.analysys.cn/) |
| 帆软 FineBI | **[实证]** 智能问数是 BI 内嵌查询/检索，治理来源是指标平台：业务负责人定义指标、口径和血缘，再供问数使用；未找到对外 Agent 协议。[官方帮助](https://help.fanruan.com/finebi/doc-view-1779.html) |
| 观远 | **[实证]** ChatBI 做意图、知识、数据查询和可视化，业务知识可含知识表、逻辑、问答和 SQL/文档；洞察 Agent 用多 Agent 生成周期报告，并公开“洞察结论 API”，但 MCP 只见营销文章提及、没有 schema。[BI Copilot](https://www.guandata.com/bi-copilot)｜[洞察 Agent](https://www.guandata.com/InsightAgent) |
| Kyligence | **[实证]** Copilot 面向根因分析、报告/看板和指标搜索，可嵌入应用；答案依赖其统一语义层与指标定义，未找到公开 MCP/tool schema。[官方页](https://kyligence.io/try-copilot/) |
| 腾讯 | **[实证]** TCDataAgent 是平台内对话 + 完整外部 API；数据知识库可接 DLC、TCHouse 和 MySQL，配置后平台自动创建托管 MCP，API 域名为 `dataagent.tencentcloudapi.com`，另有会话、知识库、权限和自定义场景接口。[使用文档](https://cloud.tencent.com/document/product/1800/122735)｜[API 概览](https://cloud.tencent.com/document/product/1800/124933) |
| 阿里 | **[实证]** Quick BI 智能小Q覆盖问数、报表、解读、报告；知识库字段包括业务定义、数据解释、同义词和“强制改写”。2026 年又公开可下载 Skill 与基于 OpenAPI 的 CLI，让外部 Agent 调小Q；“小Q报表 Skill”甚至用浏览器自动提取仪表板结构生成专属查询 Skill。[上手指南](https://help.aliyun.com/zh/quick-bi/getting-started/smartq-novice-guide)｜[Skill 手册](https://help.aliyun.com/zh/quick-bi/user-guide/quick-bi-open-skill-manual) |
| 百度 | **[实证]** Sugar BI 是内嵌问数，但同时公开 `POST /openapi/v2/group/{groupKey}/ernieAsk`；请求带 `messages` 和 `dataModelHash`，assistant 历史消息是包含 dimensions、measures、filters、aggregator 的 JSON 字符串。治理靠预建数据模型、中文别名、计算字段、问数知识和模型/行权限。[API](https://cloud.baidu.com/doc/SUGAR/s/Elz9nkr36)｜[配置概述](https://cloud.baidu.com/doc/SUGAR/s/Llpqgy2kv) |

### B4. 软文与投放稿审计

- **[厂商宣称]** IT之家《2026 年 Data Agent 榜单权威发布》把衡石列第一，给出“准确性 98%+”等精确数字，却没有样本、测试题、失败项、原始结果或评测主体；同站另一篇仍把衡石第一，作者显示为“-”。这符合“投放稿伪装横评”的特征，只作为厂商能力线索，不作为事实来源。[榜单一](https://www.ithome.com/0/965/575.htm)｜[榜单二](https://www.ithome.com/0/978/753.htm)
- **[厂商宣称]** FineBI 自有域名的“八款横评”和“TOP10”由 FineBI 发布，前者把 FineBI NEXT 放在首位，后者给 FineBI 全五星且排第一；没有同等深度的复现实验或原始数据，利益关系直接可见，判定为厂商 SEO/软文。[八款横评](https://www.finebi.com/uncategorized/2026-%E4%BC%81%E4%B8%9A-data-agent-%E5%B9%B3%E5%8F%B0%E9%80%89%E5%9E%8B%E8%AF%84%E6%B5%8B%EF%BC%9A%E5%AF%B9%E8%AF%9D%E5%BC%8F%E5%88%86%E6%9E%90%E3%80%81%E5%BD%92%E5%9B%A0%E6%B7%B1%E5%BA%A6%E4%B8%8E)｜[TOP10](https://www.finebi.com/blog/article/698e1bcf2c6ebd90bc997264)
- **[厂商宣称]** 同花顺转载的“六款横评”把 SmartBI 第一并称“IDC 七项技术能力全部第一”，但页面未给出对应 IDC 原表、方法或链接；新浪财经转载稿虽按拼音排序，关键效率数字又明确来自观远自己。两者都不用于产品能力判定。[同花顺稿](https://field.10jqka.com.cn/20260324/c675519352.shtml)｜[新浪稿](https://t.cj.sina.com.cn/articles/view/6116078131/16c8bf233001019wok)
- **[推测]** 这些稿件的共同识别信号是：标题含“权威/榜单/TOP/推荐”，恰好把投放方或站点所属产品排第一，竞品篇幅/证据不对称，且精确效果数字没有可复核数据。判断依据就是上列四篇原文，本文完全用官方技术文档替代其能力结论。[IT之家样本](https://www.ithome.com/0/965/575.htm)｜[FineBI 样本](https://www.finebi.com/blog/article/698e1bcf2c6ebd90bc997264)

## C. 国外对照：谁写查询，谁负责答案，谁提供语义

### C1. 产品分析平台

| 产品 | Agent 做到哪一层 | 受治理的中间层 | 对外形态 |
|---|---|---|---|
| Amplitude | **[实证]** 内嵌 Agents/Ask 与外部 MCP 都能运行 segmentation、funnel、retention、实验分析，并可创建图表、看板、队群和指标；属于“查询 + 答案 + 动作”。 | 管理员可把事件、属性、指标、custom event、segment、cohort 标为 official，AI 会优先使用；另有 AI Context 保存业务模型、North Star、术语和排除项。[official objects](https://amplitude.com/docs/data/object-management)｜[AI Context](https://amplitude.com/docs/amplitude-ai/ai-context) | 官方 remote MCP，OAuth，US/EU endpoint；公开完整 tool 分类和 progressive discovery：`list_tool_categories` → `get_category_tools` → `describe_tool`。[MCP](https://www.amplitude.com/docs/amplitude-ai/amplitude-mcp) |
| Mixpanel | **[实证]** Spark（现 Mixpanel Agent）先把自然语言变成可编辑报告；MCP 能问数、建 Board、查 replay、管 Lexicon/实验；Headless 则面向可重复代码执行。 | 事件/属性 Lexicon、报告对象和同一查询计算层；官方强调 MCP 与 UI 使用同一计算管线。[MCP 工程访谈](https://mixpanel.com/blog/mcp-server-interview/) | 官方 MCP 约 30 tools；另有 open-source typed Python SDK + CLI，结果可进 DataFrame。[Headless](https://mixpanel.github.io/mixpanel-headless/) |
| PostHog | **[实证]** PostHog AI 可查行为、replay、SQL 并做动作；官方 MCP/AI plugin 暴露 insight、dashboard、experiment、flag、error、survey 等，属于“答案 + 产品操作”。 | 数据 schema、HogQL、产品 API；官方 Skills 是 Markdown，包含查询模式、系统表 schema、示例和 MCP tool 引用，并由源码模板构建。[架构复盘](https://newsletter.posthog.com/p/what-we-wish-we-knew-before-building) | 官方 MCP 和开源 AI plugin；plugin 公开 27+ tools、30+ task skills，自托管可改 `POSTHOG_MCP_URL`。[plugin](https://github.com/PostHog/ai-plugin) |
| Statsig | **[实证]** 平台内 AI 主要做实验假设建议、结果摘要、自然语言实验搜索；MCP 更偏实验/feature gate 全生命周期，不是一个通用产品分析师。 | 既有 metrics、experiments、gates、segments 及 Console API/RBAC；MCP tool 是 API 的受控 wrapper。[AI 能力](https://www.statsig.com/blog/statsig-ai-features)｜[治理](https://statsig.com/blog/statsig-mcp-governance) | 官方 hosted MCP 约 40 tools，支持读写、OAuth、审计、review 和 org read-only。[MCP 概览](https://docs.statsig.com/integrations/mcp/overview) |
| Heap / Contentsquare | **[实证]** Heap AI CoPilot 已并入 Contentsquare Sense Chat；它在 Web 内根据问题选择分析、生成图表、解释结论并建议追问，结合自动采集、journey 和 replay。 | 自动捕获的行为模型、分群及 Contentsquare 自身体验指标；公开材料未见独立 metrics-as-code 层。[官方指南](https://contentsquare.com/guides/product-analytics/ai/)｜[子处理器命名沿革](https://contentsquare.com/privacy-center/subprocessors/) | 本次未找到面向任意 Agent 的官方分析 MCP/tool schema；能找到的是平台内 chat 与产品集成。 |

- **[实证]** PostHog 公开了难得的反例复盘：第一版 coordinator 路由多 sub-agent 导致上下文丢失和黑箱；第二版单 Agent/模式累计 44 tools 后难扩展；第三版改为 Claude Agent SDK + MCP + Skills + 代码沙箱，并称如果重来会把 MCP 作为 canonical interface。[PostHog 复盘](https://newsletter.posthog.com/p/what-we-wish-we-knew-before-building)
- **[实证]** PostHog 还公开一个可量化但仍属单厂商内部观测的分布：某周 AI 创建的 dashboard 中 34% 来自 MCP，约占所有 dashboard 的 18%；这支持“外部 Agent 不是边缘入口”，但不能外推成全行业份额。[同一复盘](https://newsletter.posthog.com/p/what-we-wish-we-knew-before-building)

### C2. BI / 数据云平台

| 产品 | Agent 是查询助手还是答案代理 | 谁提供受治理语义 | 对外形态 |
|---|---|---|---|
| ThoughtSpot Spotter | **[实证]** Spotter 会拆题、检查结果、追问和给行动；不是让 LLM 直接写 SQL，而是先生成受约束的 search tokens/TML，再由引擎生成 SQL。 | 数据团队/领域专家在 Spotter Semantics/TML 中定义指标、join、安全规则、cohort，并可人工验证映射。[Spotter](https://www.thoughtspot.com/product/agents/spotter)｜[技术说明](https://www.thoughtspot.com/blog/spotter-for-industries) | Web/嵌入式 Agent；官方宣称有 ThoughtSpot MCP 和 Agent as a Service，但本次未定位到公开 tool schema。[Semantics](https://www.thoughtspot.com/product/spotter-semantics) |
| Snowflake Cortex Analyst / Agents / Intelligence | **[实证]** Analyst 把问题变成 SQL；Agents 在其上规划并组合 Analyst、Search、Python sandbox、chart、自定义工具、Skills、MCP 和 web search，属于“答案代理”。 | 数据团队创建 schema-level semantic view：logical tables、dimensions、facts、metrics、relationships、verified queries、synonyms、custom instructions；RBAC/共享/目录在数据库对象层执行。[编辑器](https://docs.snowflake.com/en/user-guide/views-semantic/editor) | Analyst 有 `POST /api/v2/cortex/analyst/message`，请求可指定一个或多个 semantic view；Agents 也有受管 API。[REST API](https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-analyst/rest-api) |
| Databricks Genie | **[实证]** Genie 生成 SQL、结果、图表和追问；trusted query/function 命中时显式展示，API 还能返回 reasoning trace。 | Space editor 配置表/列说明、join、SQL expressions、样例 SQL、Unity Catalog function、文本 instruction 和 knowledge store；Unity Catalog 承担权限。[质量调优](https://docs.databricks.com/aws/en/genie/add-instructions) | Web Genie Space + Conversation/Management API，可嵌入自有 chatbot/agent，支持 CI/CD 管理 space。[API](https://docs.databricks.com/aws/en/genie/conversation-api) |
| Looker Conversational Analytics | **[实证]** 标准模式选择字段/filter/sort/limit，由 Looker 组合 SQL；Advanced Analytics 再生成并执行 Python，用户可展开 reasoning 和“How was this calculated?”。 | Looker developer 写 LookML；Agent 作者补最多五个 Explores 的 context/instructions。join、aggregation、filter 和数据权限由 LookML 强制。[概览](https://docs.cloud.google.com/looker/docs/conversational-analytics-overview)｜[可解释界面](https://docs.cloud.google.com/looker/docs/conversational-analytics-looker-data) | Web/iframe + Conversational Analytics API，可自行构建 chat app。[API codelab](https://codelabs.developers.google.com/codelabs/looker-ca-api) |
| Tableau | **[实证]** Tableau Agent in Pulse 在已定义指标组上找共同驱动、反向趋势、异常和超预期项；GPT-5.2 只综合 Tableau 预计算的统计 insight，不直接分析原始数据。 | Tableau Pulse metric definition 与 bounded metric layer；统计模型先算 insight，生成式模型负责语言和匹配。[Pulse](https://help.tableau.com/current/online/en-us/pulse_ask_discover_qa.htm)｜[Trust](https://help.tableau.com/current/tableau/en-us/tableau_gai_einstein_trust.htm) | 主要是 Tableau Cloud Web/mobile 与 Pulse embedding API；本次未找到把 Pulse Agent 作为通用外部 agent tool 的官方协议。 |

### C3. “写查询”与“得到答案”的归纳

- **[推测]** 第一层是可检查的 query author：百度 Sugar、早期 Mixpanel Spark、Cortex Analyst。它降低写查询门槛，但最终判断仍在用户。[Sugar](https://cloud.baidu.com/doc/SUGAR/s/Xlpqgy2fl)｜[Mixpanel](https://mixpanel.com/blog/spark-bringing-generative-ai-to-mixpanel/)｜[Cortex Analyst](https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-analyst/rest-api)
- **[推测]** 第二层是 governed answerer：Amplitude、ThoughtSpot、Databricks Genie、Looker、Tableau Pulse。它们给结论和追问，但强弱取决于 official object、semantic view、LookML、trusted asset 或 metric definition 是否由数据负责人维护。[Amplitude](https://amplitude.com/docs/data/object-management)｜[ThoughtSpot](https://www.thoughtspot.com/blog/spotter-semantics)｜[Databricks](https://docs.databricks.com/aws/en/genie/talk-to-genie)｜[Looker](https://docs.cloud.google.com/looker/docs/conversational-analytics-overview)｜[Tableau](https://help.tableau.com/current/tableau/en-us/tableau_gai_einstein_trust.htm)
- **[推测]** 第三层是 acting agent：ThinkingAI、火山深度研究、PostHog、Snowflake Agents、Amplitude/Mixpanel MCP。它们把多个查询、代码和写操作串起来；治理焦点从“SQL 对不对”扩大为 tool 权限、审批、审计、预算、重试和副作用。[火山](https://docs.volcengine.com/docs/86760/1874909?lang=zh)｜[PostHog](https://newsletter.posthog.com/p/what-we-wish-we-knew-before-building)｜[Snowflake](https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-agents)｜[Amplitude](https://www.amplitude.com/docs/amplitude-ai/amplitude-mcp)
- **[实证]** 语义层的责任几乎都没有交给最终业务提问者：Amplitude 由 tracking-plan owner/admin 标 official；Snowflake/Looker/Databricks 由数据团队或 space editor；ThoughtSpot 由领域专家和数据团队；Tableau 由 metric creator；国内火山/Quick BI/百度也都要求管理员先配置数据集、指标或知识。[Amplitude](https://amplitude.com/docs/data/official-events-and-properties)｜[Snowflake](https://docs.snowflake.com/en/user-guide/views-semantic/ui)｜[Looker](https://docs.cloud.google.com/looker/docs/conversational-analytics-overview)｜[Databricks](https://docs.databricks.com/aws/en/genie/add-instructions)｜[Quick BI](https://help.aliyun.com/zh/quick-bi/getting-started/smartq-novice-guide)

## D. 商业与交付形态观察

### D1. 21 家样本的形态计数

计数单位是本文点名的 21 家/组：ThinkingAI、火山、神策、GrowingIO、易观、FineBI、观远、Kyligence、腾讯、阿里、百度、Amplitude、Mixpanel、PostHog、Statsig、Heap/Contentsquare、ThoughtSpot、Snowflake、Databricks、Looker、Tableau。一个厂商可以同时计入两种形态；“对外”必须有公开 MCP、自然语言对话 API、Agent CLI/Skill 或 agent API，普通数据导出 API 不算。

- **[实证]** 平台内嵌：20/21；唯一未找到相应产品证据的是易观。逐家链接见[国内表](#b3-其余国内厂商一句话形态)、[产品分析表](#c1-产品分析平台)和[数据云表](#c2-bi--数据云平台)。
- **[实证]** 对外暴露：15/21；它们是 ThinkingAI（仅公开配置、不可复现）、火山、神策、观远、腾讯、阿里、百度、Amplitude、Mixpanel、PostHog、Statsig、ThoughtSpot（仅产品说明、无 schema）、Snowflake、Databricks、Looker。逐家链接见上述三表。
- **[实证]** 两者都有 15/21；只有内嵌、未找到外部 Agent 面的 5/21 是 GrowingIO、FineBI、Kyligence、Heap/Contentsquare、Tableau；两者都未证实的 1/21 是易观。逐家链接见上述三表。
- **[推测]** 这个样本由用户点名，偏向 2026 年积极投入 AI 的头部厂商，不能当市场份额；但 15/21 的样本结果足以否定“外部 Agent 接口只是少数实验”的判断。更准确的说法是：样本内厂商倾向同时保留 Web 聊天和 headless surface，证据边界仅限上述三表。

### D2. 有没有“任意 Agent 可调用的独立客户端/SDK”

- **[实证]** Mixpanel Headless 是最直接的同类：`Workspace`、`Filter`、`Metric`、`CohortDefinition`、`CohortCriteria` 等 typed primitives 可组合到 Insights、Funnels、Retention、Flows、Profiles 五种查询引擎；CLI 同时覆盖查询、dashboard/cohort/experiment CRUD、Lexicon、drop filters、schema governance，查询结果可返回 pandas DataFrame。[SDK 文档](https://mixpanel.github.io/mixpanel-headless/)｜[代码示例](https://mixpanel.com/blog/mixpanel-headless-python-sdk/)
- **[实证]** Sensors CLI、Quick BI CLI + Skill、Databricks/Looker/Snowflake 对话 API 也允许外部 Agent 脱离主要 Web 聊天入口，但它们分别依赖厂商账户、受管 API 或官方数据模型；开放程度和完整产品覆盖各不相同。[Sensors CLI](https://manual.sensorsdata.cn/sa/docs/1hEXIJZs/v0300)｜[Quick BI v6.2](https://help.aliyun.com/zh/quick-bi/product-overview/quick-bi-v6-2-release-notes)｜[Databricks API](https://docs.databricks.com/aws/en/genie/conversation-api)
- **[实证]** 第三方小型 adapter 有先例：Vinkius 提供与 ThinkingData 无隶属关系的托管 MCP，公开八个读写工具；社区也有非官方 Amplitude/Mixpanel MCP。但这些通常只包一小部分 API，缺少上游分析合同、版本治理和完整能力闭环。[Vinkius](https://vinkius.com/apps/thinkingdata-mcp/with/windsurf)｜[社区 Amplitude MCP](https://github.com/moonbirdai/amplitude-mcp-server)｜[社区 Mixpanel MCP](https://www.npmjs.com/package/%40andrew_eragon/mcp-mixpanel)
- **[推测]** 本次没有找到一个成熟公开项目同时满足：第三方维护、针对单一既有分析 SaaS、完整复刻其受治理分析能力、稳定 SDK/CLI/Plan、多类错误可机判、无需该 SaaS Web。依据是找到的社区项目都只覆盖小型 API 子集，而最完整的 Headless 由 Mixpanel 官方维护。[社区 Amplitude MCP](https://github.com/moonbirdai/amplitude-mcp-server)｜[社区 Mixpanel MCP](https://www.npmjs.com/package/%40andrew_eragon/mcp-mixpanel)｜[Mixpanel Headless](https://mixpanel.github.io/mixpanel-headless/)

### D3. 可持续性差别

- **[推测]** 厂商官方 MCP/SDK 的优势是可直接复用内部查询引擎、权限和对象模型，并能同步上游发布；弱点是产品边界由厂商商业策略决定，可能只给 curated tools，或把高级能力绑定套餐和账户。Mixpanel 对 MCP 固定菜单的自评和 Tableau+ 套餐是这两项判断的直接依据。[Mixpanel](https://mixpanel.com/blog/mixpanel-headless/)｜[Tableau+](https://help.tableau.com/current/online/en-us/pulse_capabilities.htm)
- **[推测]** 第三方客户端的优势是可以围绕 Agent 任务而不是 Web UI 组织合同，保留稳定 envelope、错误分类、批量/Plan 和跨版本防漂移；弱点是上游未承诺的 API 随时可能变，第三方必须持续做路由 census、合同编译、探测和 fail-closed，维护成本明显更高。依据是本仓库现有目标与维护机制，而非外部厂商数据。[路线图](../roadmap.md)｜[技术债](../maintainers/technical-debt.md)
- **[实证]** Mixpanel 自己给出了这组权衡：约 30 个 MCP tools 适合有人复核的自然语言会话，但固定菜单和非确定调用链不适合无人值守；Headless 的 typed code surface 用可审计、可重复脚本解决。PostHog则反向选择 MCP + Skills + sandbox 作为统一内外架构。两家都说明“只把 API 包成很多 tools”不是终局。[Mixpanel](https://mixpanel.com/blog/mixpanel-headless/)｜[PostHog](https://newsletter.posthog.com/p/what-we-wish-we-knew-before-building)

## 对本仓库的意义

- **[实证]** 本仓库目标不是复刻 Gravity Web，而是让已知输入一次、未知输入两次的分析动线通过 CLI、SDK、Plan、Agent card 到达，并返回带 `schema_version`、可区分 empty/partial/capability gap 的 envelope；未登记字段 fail-closed，调用次数显式登记。[路线图](../roadmap.md)｜[分析动线台账](../analysis-journeys.md)｜[Agent 工作流](../agent-workflow.md)
- **[推测]** 市场上存在“厂商自己开放 headless surface”的强对应物，尤其是 Mixpanel Headless、Amplitude/PostHog MCP、Databricks/Looker/Snowflake API；所以“分析不必发生在厂商 Web”这个方向已被验证，不再是孤立设想。[Mixpanel](https://mixpanel.github.io/mixpanel-headless/)｜[Amplitude](https://www.amplitude.com/docs/amplitude-ai/amplitude-mcp)｜[Databricks](https://docs.databricks.com/aws/en/genie/conversation-api)｜[Looker](https://docs.cloud.google.com/looker/docs/reference/looker-api/latest)
- **[推测]** 但本仓库的组织身份仍不同：它是上游之外的客户端，必须把“上游事实上能读什么”和“本仓库稳定承诺什么”分开。官方 MCP 可以依靠内部 schema 同步；本仓库只能靠 contract、compiler、route census、probe 和 fail-closed 抵抗漂移。[路线图](../roadmap.md)｜[维护者入口](../maintainers/index.md)
- **[实证]** 已经领先于多数公开 MCP 文档的部分是：显式 `schema_version` envelope、empty/partial/capability-gap 分类、未知字段 fail-closed、顶层调用次数与 Plan 并发预算。ThinkingAI 公开页没有这些合同；Amplitude/Mixpanel/PostHog 虽公开大量 tools，也没有在产品文档中承诺本仓库这种统一结果 envelope。[本仓库路线图](../roadmap.md)｜[ThinkingAI MCP](https://www.thinkingai.cn/product/mcp-service/)｜[Amplitude MCP](https://www.amplitude.com/docs/amplitude-ai/amplitude-mcp)
- **[实证]** 明显落后的部分是外部生态的标准接入：本仓库目前交付 CLI/SDK/Plan/Agent card，而 Amplitude、Mixpanel、PostHog、Statsig 已有远程 OAuth MCP，且公开 discovery/tool 文档；ThinkingAI 即便合同不完整，也已把 MCP 作为产品叙事入口。[Amplitude MCP](https://www.amplitude.com/docs/amplitude-ai/amplitude-mcp)｜[PostHog plugin](https://github.com/PostHog/ai-plugin)｜[Statsig MCP](https://docs.statsig.com/integrations/mcp/overview)
- **[推测]** 应借鉴一：把当前稳定 Agent card/Plan 能力机械生成一个窄 MCP surface，而不是手写第二套工具目录；`describe capability → validate input → execute plan` 比暴露几十个随意 JSON tools 更能复用现有合同。Amplitude 的 progressive discovery 提供了可参照的交互。[Amplitude MCP](https://www.amplitude.com/docs/amplitude-ai/amplitude-mcp)｜[Plan 参考](../reference/plan.md)
- **[推测]** 应借鉴二：引入类似 Mixpanel typed primitives / Snowflake semantic view 的机器可读组合层，但只覆盖已经有多个调用点的领域；不要为“Agent 化”新增通用 registry、插件系统或让模型自由拼上游 wire JSON。[Mixpanel Headless](https://mixpanel.github.io/mixpanel-headless/)｜[Snowflake YAML](https://docs.snowflake.com/en/user-guide/views-semantic/semantic-view-yaml-spec)｜[本仓库技术债](../maintainers/technical-debt.md)
- **[推测]** 应借鉴三：像 Looker、Databricks、Tableau 一样在答案旁保留“如何算出”、实际 query/operation、受信对象和来源；本仓库已有 receipt/envelope 基础，可进一步让每个结果指向稳定 contract/version，而不是输出不可审计的自然语言归因。[Looker](https://docs.cloud.google.com/looker/docs/conversational-analytics-looker-data)｜[Databricks](https://docs.databricks.com/aws/en/genie/conversation-api)｜[Tableau](https://help.tableau.com/current/online/en-us/pulse_ask_discover_qa.htm)
- **[推测]** 明确不该学：ThinkingAI 当前不可复现的包引用和只展示单个 tool 的做法；也不该学首页式自动下发策略。对本仓库而言，未证实 schema 就暴露、让自然语言自动填写业务绑定、或把读分析升级成写操作，都会破坏现有 fail-closed 边界。[ThinkingAI MCP](https://www.thinkingai.cn/product/mcp-service/)｜[Agent 工作流](../agent-workflow.md)
- **[推测]** 第三方定位的可持续前提有三项：上游路由/响应漂移能被自动检测；每条能力有可复核证据和稳定投影；与官方 Web 的能力差距持续缩小。若其中任何一项长期做不到，官方 MCP/SDK 会天然更可持续；若三项做到，本仓库可提供官方 surface 常缺少的跨版本稳定性与 Agent 可判定错误。[路线图](../roadmap.md)｜[分析动线台账](../analysis-journeys.md)
- **[推测]** 优先级建议：先完成已有四面的自然语言可达与合同一致性，再评估由现有 Agent card 自动生成只读 MCP；不要为了追赶“100+ Skill”先建 Skill 商店。依据是本仓库已经把自然语言可达列为欠账，而 ThinkingAI 的 Skill 数量缺少公开运行合同。[路线图](../roadmap.md#agent-可用性欠账)｜[ThinkingAI Skill](https://www.thinkingai.cn/product/skills-library/)

## 最可能出错的判断与未决清单

- **[推测]** 最可能出错的是“ThinkingAI MCP 尚不可公开复现”。证据很强但带时间性：公开 npm 当天 404、官网没有 endpoint/schema；厂商可能使用登录后 registry、客户下载中心，或在本文完成后发布包。它不等于 MCP 在客户环境不存在。[npm endpoint](https://registry.npmjs.org/%40thinkingdata%2Fmcp-server)｜[MCP 页](https://www.thinkingai.cn/product/mcp-service/)
- **[实证]** ThinkingAI 未决：MCP tool/schema、Skill artifact、Agent handoff wire、全域 connector 合同、私有化硬件、MiniMax 责任边界、可操作 demo/完整录像；逐项尝试入口见本地 `tmp/codex/vendor-agent-landscape/sources/README.md` 的 `thinkingai--thinkingdata` 小节。
- **[实证]** 国内未决：神策 CLI 的公开源码/稳定 schema、观远所谓 MCP 的正式文档、GrowingIO 漏斗/留存当前完成度、易观是否有未被公开索引的企业 Agent 产品。[神策 CLI](https://manual.sensorsdata.cn/sa/docs/1hEXIJZs/v0300)｜[观远](https://www.guandata.com/InsightAgent)｜[GrowingIO](https://www.growingio.com/products/IntelliQuery)｜[易观](https://www.analysys.cn/)
- **[实证]** 国外未决：ThoughtSpot MCP 的公开 tool schema、Tableau 是否会开放 Pulse Agent API、Mixpanel Headless early access 的生产 SLA/版本兼容策略、各 MCP 在真实脏 taxonomy 上的独立准确率。[ThoughtSpot](https://www.thoughtspot.com/product/spotter-semantics)｜[Tableau](https://help.tableau.com/current/online/en-us/pulse_ask_discover_qa.htm)｜[Mixpanel](https://mixpanel.com/ai/headless)

## 标注统计

正文断言共 104 条：实证 69 条，厂商宣称 11 条，推测 24 条。计数方法是统计加粗的标签；标题、图例和代码中的普通文本不计。
