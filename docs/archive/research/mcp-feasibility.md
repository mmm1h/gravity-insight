> 归档材料：保留历史决策与取证，不代表当前接口或状态；当前入口见 docs/index.md。

# MCP 交付面可行性报告

> 裁决日期：2026-08-15
>
> 基线：`dev@23422c2`，185 个 operation，47 条计数动线
>
> 范围：本报告只做可行性判断与实施设计，不实现 MCP server，不改变现有产品面或闭环判据。

## 结论

**应该做，但只应先做一个可撤回的本地 stdio 实验；现在不应把 MCP 宣布为每条动线都必须同步的
“第五交付面”，也不应同时建设远程 HTTP 与 OAuth。**

最关键的三个理由是：

1. 这是在验证一个已经发生的问题，而不是只追逐行业热点。现有手写自然语言路由在 20 个真实问题中
   首次错路由 8 个，从自然语言到合法答案只走通 4 个；MCP 让宿主模型依据工具名、描述和 JSON Schema
   选择工具，恰好替代这段低质量的意图路由。
2. 仓库有适合暴露为工具的独特内核：已闭环的漏斗、留存等在上游算好，返回版本化、受治理、
   fail-closed 的结果，而不是把 185 个端点或原始事件交给模型临时 join。MCP 应包装这些结果型能力，
   不应包装 raw operation。
3. stdio 试点可以用真实宿主选择准确率决定是否继续，成本和承诺都可控。远程多用户服务则会引入
   身份传递、凭据托管、租户隔离、OAuth、审计和运维，是另一项产品决策，不能借试点顺带做掉。

这不是无条件立项。若试点不能把冻结题集的首选正确率从当前 `12/20` 明显提高，或没有第二个真实
调用方愿意采用，正确动作是停止并只保留 schema 描述，而不是把实验升级为长期交付面。

## MCP 是什么

Model Context Protocol（MCP）是宿主应用与上下文/工具服务器之间的协议。宿主可以是桌面助手、IDE
或自有 Agent；服务器声明自己能提供什么，宿主模型再决定何时调用。它解决的是宿主与能力之间的
标准化发现和调用，不替代 Gravity 的查询合同、权限系统或业务知识库。

MCP 有三种主要原语，控制权不同：

| 原语 | 谁通常决定使用 | 解决的问题 | 本仓库的用法 |
| --- | --- | --- | --- |
| tool | 模型 | 执行动作或计算；通过 `tools/list` 发现、`tools/call` 调用 | 调用受治理的分析结果型能力 |
| resource | 应用/宿主 | 用 URI 列出和读取上下文 | App、事件/属性词表、看板、分群、SQL 产品和 lineage 目录 |
| prompt | 用户 | 显式选择可复用提示模板 | 首期不用；业务问题模板仍属于调用方知识库 |

规范把 tool 定义为 model-controlled，把 resource 定义为 application-driven，把 prompt 定义为
user-controlled；三者不能互相替代。tool 的输入是 JSON Schema，结果既可以有面向人或旧客户端的
`content`，也可以有匹配 `outputSchema` 的 `structuredContent`。
[Tools 规范](https://modelcontextprotocol.io/specification/2026-07-28/server/tools)、
[Resources 规范](https://modelcontextprotocol.io/specification/2026-07-28/server/resources)、
[Prompts 规范](https://modelcontextprotocol.io/specification/2026-07-28/server/prompts)

这里最容易产生的误解是：`tools/list` 只列静态能力和输入 schema，不会凭空知道当前 workspace 有
哪些 App、事件、看板或物理指标。动态候选仍要从 resource 读取；模型选对工具，也不等于它能猜对
业务 ID 或字段。

## 仓库现状：四种外壳，共享一套能力

### 哪些是能力，哪些是交付外壳

| 层 | 当前职责 | 是否新增取数能力 | MCP 映射 |
| --- | --- | --- | --- |
| operation/contract 与领域 composite | 固定 host/path/method、请求编译、字段投影、分页、聚合、错误与 envelope | **是**，这是能力内核 | MCP handler 必须复用 |
| CLI | 参数解析、文件/stdout、退出码；调用同一 SDK/领域逻辑 | 否，是命令行外壳 | 不在 MCP 中模拟命令行 |
| SDK | Python 调用入口；不猜 Insight/SQL、不加业务口径 | 否，是编程外壳 | MCP server 直接调用它 |
| Plan | DAG、依赖、并发预算、partial 聚合和 adapter preflight | 不新增上游能力；新增编排语义 | 复杂组合仍可由宿主多 tool 调用或后续显式编排 tool 承接 |
| Agent 卡 | 无值的发现、输入提示、Plan node/命令交接 | 否，是发现合同 | 名称、描述和部分 schema 可作为设计输入，不能直接发布 |

因此 MCP 不是第五份数据实现；它仍然会成为第五份**公开调用合同**。差别很重要：复用领域内核可以
避免复制请求和投影逻辑，但 tool 名、描述、输入 schema、结果包装、资源 URI 和错误映射仍要同步维护。

### 固定 composite 卡的实数是 21，不是 15

当前 `composite_capability_inventory()` 在本基线返回 **20** 张固定卡：

1. `analysis_context`
2. `dashboard_analysis`
3. `monetization_detail`
4. `segment_snapshot`
5. `saved_analysis`
6. `analysis_template`
7. `dashboard_snapshot`
8. `app_snapshot`
9. `attribution_snapshot`
10. `multidim`
11. `material_performance`
12. `title_package`
13. `order_directory`
14. `order_split_trace`
15. `promotion_performance`
16. `business_pulse`
17. `company_usage`
18. `custom_audience`
19. `bilibili_account_performance`
20. `advertiser_profile`

其中 17 张走 strict composite，`analysis_context`、`app_snapshot`、`attribution_snapshot` 仍走通用
匹配。题设的 15 张是较早快照，不能作为“天然符合每 server 5–15 tools”的证据；当前 21 张反而超过
建议上限。卡也不是可直接发布的 MCP schema：例如现有提示型 schema 使用
`"type": "string|integer"`，这不是合法 JSON Schema；部分描述还保留已经被
[投影总裁决](../decisions/2026-08/projection-and-privacy.md#投影边界总裁决全面放开2026-08-15)推翻的字段隐藏文字。

结论是：卡可以提供领域 owner、描述和 handoff 线索，MCP tool 必须从结果任务重新分组，并由合法
JSON Schema/Pydantic 模型生成和校验，不能把 21 张卡机械转成 21 个工具。

## 现有机器语义能否映射

### 可保真的部分

- `schema_version`、`status`、数据、component receipt 和 next action 可以原样放进
  `structuredContent`，由 `outputSchema` 约束；同时在 `content` 放一份安全、简洁的 JSON/文本副本，
  兼容还不消费结构化结果的宿主。规范明确要求声明了 output schema 的工具返回与之匹配的
  structured result，并建议为兼容性同时提供序列化文本。
- success、合法 empty、partial、capability gap 等三态/多态继续由 Gravity envelope 区分。
  MCP 自己的 `isError` 只做粗粒度“本次 tool execution 是否失败”，不取代 `status`。
- 未登记字段 fail-closed 完全保留，因为 handler 只调用现有 SDK/领域入口；不得在 MCP 层加 raw
  fallback。这里的 fail-closed 是合同漂移检测，不是隐藏字段。
- 读取类工具可声明 `readOnlyHint=true`、`openWorldHint=false`；导出工具有文件副作用，不声明只读。

### 不能无损变成 MCP 原生概念的部分

| Gravity 语义 | MCP 原生能力 | 设计 |
| --- | --- | --- |
| caller `2` / upstream `3` / local `4` 退出分类 | tool execution 只有粗粒度 `isError`；JSON-RPC error 留给未知方法、参数格式或协议故障 | 保留 envelope 的 `error.category`、`exit_code`、`retryable`；不要映射成自造 JSON-RPC code |
| partial 与 capability gap | `isError` 是布尔值，无法表达这些产品态 | `isError=true` 时仍返回完整结构化 envelope 和 JSON 文本；各宿主是否保留/展示错误结构必须实测 |
| `gravity.agent-call-bound.v1` | MCP 有 `tools/list`、`resources/list/read`、`tools/call`，宿主还可能缓存工具列表 | 原合同的 unit 是 `cli_or_sdk_invocation`，不能换个名字继续声称无损；试点记录真实 RPC，毕业后另定义 `gravity.mcp-call-bound.v1` |
| CLI 进程退出码 | MCP 无进程级产品退出码 | 只作为 envelope 字段保留，宿主按结构化字段决策 |

因此答案不是简单的“全能”或“全不能”：**结果 payload、三态与 fail-closed 可以无损保留；
call-bound 的计量单位、进程退出码和三类错误没有 MCP 原生等价物，只能在 Gravity envelope 中保留。**

官方 Python SDK 的高层装饰器可以从类型提示/Pydantic 生成输入和输出 schema；但是其默认异常处理可能
只给 `is_error`，拿不到本仓库需要的完整结构化错误 receipt。实现时应在错误路径显式构造
`CallToolResult`，并用协议测试证明 `structuredContent` 没被丢弃。
[Python SDK tools](https://py.sdk.modelcontextprotocol.io/servers/tools/)、
[结构化输出](https://py.sdk.modelcontextprotocol.io/servers/structured-output/)、
[错误处理](https://py.sdk.modelcontextprotocol.io/servers/handling-errors/)

### `--resolve-inputs` 的两次闭环在 MCP 下是什么

当前第一次顶层调用同时做能力发现和完整动态输入目录解析，调用方精确选择；第二次调用执行。
MCP 会把它拆成不同协议原语：

1. 冷连接时宿主可能先 `tools/list`，但工具列表通常可缓存，只解决“有什么能力”；
2. 对未知 App/事件/看板/指标，宿主读取相应 resource，解决“本 workspace 有什么合法值”；
3. 宿主或模型用选定值 `tools/call`，执行受治理能力。

所以它不是“原两次自动变一次”。resource read 与 tool call 是两个 MCP RPC，内部 HTTP 量也不会减少；
如果宿主先列工具，冷连接表面上甚至是三条协议消息。MCP 的优势是宿主能原生编排发现与调用，而不是
把目录请求消灭。未来可在宿主普遍支持交互式补参时优化体验，但首期不能依赖单一新协议特性。

## 14 个 tool 的映射草案

### 归并原则和可复算推导

归并单位是“调用方要完成的结果”，不是 operation、页面或现有卡：

```text
47 条计数动线 = 32 已闭环 + 0 部分闭环 + 15 完全缺失
32 已闭环 = 7 核心分析 + 8 上下文/资产 + 3 报表 + 6 营销
            + 4 用户/交易 + 1 SQL + 1 素材导出 + 2 离线发现
14 tools = 6 + 3 + 1 + 1 + 1 + 1 + 1
2 条离线发现 -> resources，不计 tool
```

15 条完全缺失没有可执行能力，不能先发布空壳 tool。台账中另有 3 条明确不计数的 legacy/便利/重复面，
也不纳入。47 条动线和 185 个 operation 的账面均不变：`47 + 0 - 0 = 47`，
`185 + 0 - 0 = 185`。

所有 schema 都应使用合法 JSON Schema 2020-12；多变体工具用显式 discriminator 和 `oneOf`，不能用
无约束 object。日期、App、稳定引用、字段及预算继续复用既有约束。除导出外，返回值都是现有
版本化 envelope 的 `structuredContent` 加兼容文本。

| # | tool | 一句话描述 | 输入 schema 要点 | 返回 | 对应动线/卡 |
| --- | --- | --- | --- | --- | --- |
| 1 | `gravity_query_event_trend` | 查询事件趋势，可选同口径双窗口比较 | `app`、事件 spec、日期/粒度、分组/过滤；可选 `comparison_window` | event/period-comparison envelope | 事件趋势、跨期比较；Analysis spec event |
| 2 | `gravity_query_funnel` | 计算有序步骤漏斗和转化 | `app`、2+ steps、窗口、日期、过滤；可选比较窗口 | funnel envelope | 漏斗、跨期比较；Analysis spec funnel |
| 3 | `gravity_query_retention` | 计算起始/回访事件留存 | `app`、start/return event、offset、日期、过滤；可选比较窗口 | retention envelope | 留存、跨期比较；Analysis spec retention |
| 4 | `gravity_query_property_distribution` | 对事件或用户属性分布聚合 | `app`、subject、property、aggregation、日期/过滤；可选比较窗口 | property envelope | 属性分布、跨期比较；Analysis spec property |
| 5 | `gravity_query_scatter_relationship` | 查询两个指标的散点关系 | `app`、x/y metric、zone、日期/过滤；可选比较窗口 | scatter envelope | 散点、跨期比较；Analysis spec scatter |
| 6 | `gravity_evaluate_segment_rule` | 按受治理规则评估分群命中人数与占比 | `app`、日期、闭合规则 schema；不接受任意表达式 | segment evaluation envelope | 分群规则评估；Analysis spec segment |
| 7 | `gravity_read_context_snapshot` | 读取构造分析所需的受治理上下文快照 | discriminator：`analysis` / `app` / `attribution`；`app`，可选来源集合 | 对应 context envelope | 3 条 context 动线；`analysis_context`、`app_snapshot`、`attribution_snapshot` |
| 8 | `gravity_inspect_analysis_asset` | 查看分析资产定义而不执行 | discriminator：dashboard / segment；稳定引用、`app` | asset snapshot envelope | 看板快照、分群快照；`dashboard_snapshot`、`segment_snapshot` |
| 9 | `gravity_replay_analysis_asset` | 按稳定引用重放已保存分析 | discriminator：dashboard / saved analysis / template；引用、显式运行输入和预算 | replay/component envelope | 3 条重放动线；`dashboard_analysis`、`saved_analysis`、`analysis_template` |
| 10 | `gravity_query_business_report` | 执行已登记的经营或多维聚合报表 | discriminator：multidim / business pulse / company usage；物理 schema、日期、分页预算 | report envelope | 3 条报表动线；`multidim`、`business_pulse`、`company_usage` |
| 11 | `gravity_query_marketing_performance` | 查询已登记营销对象或投放表现 | discriminator：audience / material / promotion / bilibili account / advertiser / title package；平台、对象、日期、指标 | marketing envelope | 6 条营销动线；对应 6 张 composite 卡 |
| 12 | `gravity_read_user_commerce` | 读取用户分析或订单/变现明细 | discriminator：user journey / order directory / order trace / monetization；`app`、单日、稳定用户/TraceID 等 | detail/directory envelope | 4 条用户/交易动线；`order_directory`、`order_split_trace`、`monetization_detail` |
| 13 | `gravity_query_sql_product` | 执行 workspace 已登记的只读 SQL 产品 | `product`、其闭合参数 schema、分页/行预算；不接受任意 SQL | SQL product envelope | custom SQL 动线；SQL product card |
| 14 | `gravity_export_material_report` | 创建、轮询并原子下载已登记素材报表 | 平台、日期、字段、destination discriminator、poll/timeout 预算；本地路径只允许 stdio 且覆盖必须显式 | export receipt、文件摘要与 resource link；不是普通读结果 | 素材导出；`material_performance` handoff |

14 是上限内的高位，不应继续因为“还有一个 operation”而加工具。若宿主对第 10–12 个工具内的
discriminator 选择表现差，优先重新命名/调整分组；只有实测证明两个结果任务不可共同发现时才拆分，
并同时合并或删除低使用工具，保持 5–15。

### 归并丢失了什么

- 不再从工具名直接看出 47 条动线或 20 个内部 owner；调用方要读 discriminator 和输出 identity。
- 同一 family 的描述更宽，模型先选 family、再填 variant，可能把“工具选择错误”变成“variant 填错”。
- 每个上游 operation 的独立调参、wire 字段和诊断便利性不出现在 MCP 主面。
- Plan 的任意 DAG、精细依赖和全局并发预算没有被一一翻译；复杂批处理仍使用 Plan/SDK，或由宿主在
  多次 tool call 之上编排。
- tool schema 不能承载业务词义；活动名、SKU、口径绑定仍由调用项目知识库提供。

这些损失是有意的：MCP 主面优化的是安全地选择分析结果，不是取代专家调试面。

### raw `gravity run <operation>` 不进 MCP

无论把 185 个 operation 变成 185 个 tools，还是做一个接受 `operation + wire JSON` 的万能 tool，都会
破坏结果导向设计：前者降低工具选择准确率，后者让模型猜底层 wire schema，绕过 product-level
约束，并复现“拉原始数据、让 LLM 自己解释”的行业短板。raw 入口继续服务 CLI/SDK 专家调用方和
内部 composite；MCP 最多提供只读 operation/catalog resource 供诊断，绝不提供通用执行 tool。

### resource 清单；首期不发 prompt

建议的 URI 是：

- `gravity://catalog/capabilities`
- `gravity://workspace/apps`
- `gravity://apps/{app}/analysis-vocabulary`
- `gravity://apps/{app}/dashboards`
- `gravity://apps/{app}/saved-analyses`
- `gravity://apps/{app}/segments`
- `gravity://catalog/sql-products`
- `gravity://metadata/table-lineage/{query}`

其中词表和 table lineage 承接 2 条离线发现动线；其他 resource 为 tool 填入稳定 ID 和物理字段。
目录缓存必须按身份/workspace 隔离。业务 playbook、活动口径和推荐问题属于调用方知识库，首期 MCP
prompt 只会制造第二份业务模板，所以不发布。

## 可行性、模块边界与边际成本

### 建议的实现边界

若试点获批，新增独立包和入口，而不是把逻辑塞进共享 spine：

```text
src/gravity_sdk/mcp/
  server.py           # MCPServer/低层 handler 与生命周期
  tool_catalog.py     # 14 个稳定定义、annotations、fingerprint
  analysis_tools.py   # 1–6
  product_tools.py    # 7–14
  resources.py        # URI/list/read 与缓存隔离
  schemas.py          # 合法输入/output JSON Schema 模型
  results.py          # envelope、content、isError 映射
  auth.py             # 仅远程阶段新增
```

另加独立 `gravity-mcp` console entry point、MCP 专项测试和（届时）官方 SDK 依赖。server 只调用公开
`GravitySDK`/已有领域 composite，不改请求编译、投影或并发预算。首期不改 `cli.py`、主
`__main__.py`、`plan_adapters.py`、`agent_capabilities.py`、`agent_composite.py` 或
`agent_handoff.py`；选择 `gravity mcp` 子命令会迫使 CLI spine 膨胀，故不推荐。

按当前官方 Python SDK v2，最小实现入口是 `from mcp.server import MCPServer`，通过 `@mcp.tool`、
`@mcp.resource` 注册能力；`mcp.run()` 默认启动 stdio，远程阶段才使用
`mcp.run(transport="streamable-http", port=...)`。输入/输出用类型提示或 Pydantic 模型生成 schema，
读取工具附 `ToolAnnotations(read_only_hint=True, open_world_hint=False)`。这是建议 pin 住并由互操作
测试包围的协议适配层，不应扩散到领域模块。
[Python SDK server API](https://py.sdk.modelcontextprotocol.io/servers/tools/)、
[Python SDK run API](https://py.sdk.modelcontextprotocol.io/run/)

实现时还应避免从 Agent 卡反向生成所有合同。可以共享稳定的闭合输入模型和 envelope 模型；名称、
描述、MCP annotations 与 resource URI 是 MCP 自己的薄合同。这样新动线落入既有 family 时，边际成本
是一个 schema 分支、dispatch 映射和合同测试；只有新增真正不同的结果任务才新增 tool。

若把 MCP 立即规定为强制第五面，后续每条动线都要同步 tool/resource 决策、schema、映射和互操作测试，
成本会从一次性试点变成永久 ratchet。14 个 tool 若各自手写定义、输入、输出和 handler，粗略就是
`14 × 4 = 56` 个同步点；这只是规划量级，不是源码行数测量。通过模型生成可以降低重复，但不能消除
公开合同的兼容责任。

## 鉴权与传输

### stdio：首期唯一推荐

stdio 由宿主启动子进程，JSON-RPC 消息走 stdin/stdout，日志只能走 stderr。它适合本机 IDE/桌面
助手和当前 `.env.gravity.local` 的单用户凭据模型：不监听端口、不引入远程身份、不需要 OAuth。
MCP 规范也明确指出 stdio server 应从环境取得凭据，而不是走 HTTP 授权流程。
[stdio 规范](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/stdio)

首期要把“stdout 只有协议帧、日志/异常不含 token 或生产响应值”作为门禁。stdio 不是远程共享服务；
不能把它包装成无认证公网进程后仍称为同一个部署模型。

### Streamable HTTP：有明确远程需求后再做

HTTP 适合独立部署和多客户端，但要求 HTTPS、Origin 校验、限流、审计、租户隔离、资源缓存隔离和
明确的日志保留。当前规范使用 POST 为核心的 Streamable HTTP，并要求在本地运行时优先绑定
localhost，以防 DNS rebinding。
[Streamable HTTP 规范](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http)

stdio 可把导出文件原子写入调用用户明确给出的本地路径；HTTP server 不能接受客户端任意服务器路径。
远程阶段必须改用服务器管理的对象 key/resource link，并把路径穿越、配额、过期和下载授权纳入合同。
这也是素材导出不能随“读工具上 HTTP”顺带上线的原因。

OAuth 只解决“宿主客户端是否获准访问 MCP resource server”。它不会自动把本地 Gravity 凭据变成
每用户上游身份。远程上线前必须选定并证明以下一种模式：

- 每用户凭据代理/安全存储，把 MCP subject 映射到其 Gravity 上游身份；或
- 明确的单一 service identity，仅服务一个租户和固定授权范围。

令牌绝不能进入 tool 参数、resource 内容、日志或仓库。MCP HTTP 授权采用 OAuth 2.1 资源服务器
模型、Protected Resource Metadata 和 resource indicator/audience 绑定；Python SDK 提供
`TokenVerifier`、`AccessToken` 和 `AuthSettings`，但授权服务器/IdP 仍是外部基础设施。
[Authorization 规范](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization)、
[Python SDK authorization](https://py.sdk.modelcontextprotocol.io/run/authorization/)

**现在不做 OAuth。** 在没有远程部署 owner、身份模型和真实多用户调用方时实现它，只会锁定错误的
scope 与 tenant 模型。未来可先定义 `gravity.read` / `gravity.export` 之类最小 scope，再由外部 IdP
发 token。远程 MCP 还改变了“谁收到 SDK 输出”：如果接收者不是同一上游已授权用户，必须按投影
总裁决重新审查交付身份边界，而不是重新隐藏字段。

## `gravity agent` 的去留

三个选项的后果是：

| 选项 | 后果 |
| --- | --- |
| (a) 保留并继续投入 | 同时维护关键词 recognizer 和 MCP schema 两套意图层；会持续把研发花在宿主 LLM 已擅长的问题上，但照顾所有纯 CLI 调用方 |
| (b) 保留但冻结 | 既有 selector、Plan handoff 和调用方不退化；只修安全/严重回归，不再加关键词、同义词或新产品路由；用 MCP 试点取得替代证据 |
| (c) 逐步下线 | 最终减少重复合同，但立即开始会让非 MCP 调用方失去自然语言入口，也缺少宿主准确率和迁移清单 |

**推荐 (b)，并把 (c) 设为有条件的后续方向。** 当前不删命令、不删精确 selector、不删
capability search、Plan node 或 call-bound；只冻结手写自然语言 recognizer 的功能扩张。只有完整
14-tool 面在至少两个真实宿主上通过冻结题集，并完成现有调用方迁移盘点后，才发布 recognizer 的
弃用周期。继续 (a) 会重复建设；立刻 (c) 违反既有能力只能加不能减的约束。

## 测试与门禁

MCP 面的测试应少而集中在合同边界，不为 185 个 operation 重写一套测试：

1. **目录/schema 门禁**：`tools/list` 稳定排序和 fingerprint；tool 数始终 5–15；所有 input/output
   schema 通过 JSON Schema 2020-12 校验，无悬空 `$ref`/`$defs`；不存在 raw/missing tool。
2. **映射门禁**：每个 family 一个合成 happy path；handler 只调用既有 SDK/composite；输入缺失或
   discriminator 错误在发请求前失败。测试量继续服从“测试新增行不超过实现新增行三分之一”。
3. **结果/错误门禁**：success、empty、partial、capability gap、caller/upstream/local 和 contract
   drift 的 envelope/退出字段不丢；错误 structured result 在目标宿主仍可读取；绝不 raw fallback。
4. **协议门禁**：官方 Python client 做 in-process/stdio 往返；MCP Inspector 校验；stdout 无日志，
   cancellation、timeout、结果大小和进程退出可控。
5. **隐私与凭据门禁**：合成 fixture；token、`.env.gravity.local`、生产响应值不进工具目录、日志、
   snapshot 或提交。resource 缓存按身份隔离。
6. **宿主可用性门禁**：冻结问题、预期工具和输入先于实现；至少两个真实宿主，不用 host-specific
   system prompt。记录首选正确率、端到端终点、MCP RPC 数和内部 HTTP 数。
7. **仓库门禁**：保留现有 unittest、pytest、compiler、quality、CLI help、diff check 全套；MCP
   不是降低现有门禁的理由。

一次坏 tool schema 可能让宿主整次 `tools/list` 失败，所以目录完整性必须作为 server-level 原子门禁，
不能只测单个 handler。这一点也要求返回目录前先完成全部 schema 编译，而不是运行中部分注册。

## 最强的反对意见：为什么可能不该做

### 1. 规范和 SDK 的返工风险是真实的

MCP 仍在快速演进。仅 2026-07-28 一版就移除了初始化/会话和部分发现机制，调整了交互式输入与缓存
机制，并把 Dynamic Client Registration 的推荐路径改向 Client ID Metadata Documents；官方 Python
SDK v2 也把高层服务器 API 从早期 `FastMCP` 调整为 `MCPServer`。这不是抽象的“未来也许变化”，而是
当前已经发生的破坏性迁移证据。
[2026-07-28 版本说明](https://blog.modelcontextprotocol.io/posts/2026-07-28/)、
[Python SDK](https://py.sdk.modelcontextprotocol.io/)

绑定协议意味着要维护宿主兼容矩阵、pin SDK、跟进版本和传输/授权变化。降低风险的方法是把协议适配
集中在独立包、首期只 stdio，并在发布工具名以前保留实验标签；它不能把风险归零。

### 2. 第五合同的长期成本可能大于短期收益

仓库已经为 CLI/SDK/Plan/Agent 同步付费，且 Agent 卡的提示 schema 和过时描述证明同步漂移确实会
发生。再增加 14 个稳定 tool、8 个 resource URI 和 host 行为测试，意味着每个新结果任务都多一项
发布判断。即使领域实现完全复用，这份合同也必须兼容、迁移和记录。

更尖锐的是：MCP 不保证选对工具。当前卡 21 张已经过多；归并到 14 张虽符合经验上限，宽 family
仍可能让模型选错 variant。若没有实际 A/B，只是把 recognizer 失败换成更难复现的宿主模型失败。

### 3. 真实调用方需求尚未证明

从本仓库能证明的是自然语言路由差，不能证明现有 canonical consumer 正在等待 MCP。若现有调用方
都通过 CLI/SDK/Plan 集成，MCP 可能只解决演示问题，并把远程服务、OAuth 和兼容成本引进来。同行已经
采用 MCP 只能说明互操作机会，不构成本仓库的采用证据。

在这条反对意见下，最低门槛不应是“server 能启动”，而应是：至少一个现有调用方完成试用，且第二个
独立宿主/调用方明确愿意采用；否则不毕业为正式交付面。

### 4. 更便宜的替代确实存在

仓库可以只发布一份由闭合模型生成的 tool-schema manifest，让调用方自己包装 MCP。优点是本仓库不
承担进程生命周期、SDK 版本、传输和 OAuth；若永远只有一个自有调用方，这是经济上更好的方案。

缺点是每个调用方会各自实现错误映射、resource 发现、call-bound、日志和凭据处理，形成不可验证的
分叉；仓库也无法用真实 server 测出宿主是否保留 partial/error structured result。schema-only 可以
是试点失败或没有第二个采用方时的终点，但不足以验证核心假设。

### 为什么仍推荐“做试点”

最强反方足以否决“现在建设正式远程第五面”，但不足以否决一个一轮可撤回的 stdio 实验：它直接测量
已经出现的 `8/20` 路由问题，复用已有受治理结果，不触碰远程身份，并设有明确停止线。推荐的是购买
证据，不是提前承诺长期产品。

## 分阶段落地方案

### 阶段 0：冻结实验合同（实施前）

产出：冻结 20 问题题集、每题预期 tool/variant/合法 gap、现有 recognizer 基线；登记目标宿主版本；
固定 `14 tools + resources` 的候选 manifest，但标为 experimental。

验收：问题和预期先于代码落库；没有从 recognizer 关键词反向生成问法；明确哪些题属于首期 6 工具。

### 阶段 1：一轮内完成的最小 stdio 试点

只实现 6 个核心分析 tools（event、funnel、retention、property、scatter、segment），以及 App 和
analysis vocabulary resources；无 HTTP、OAuth、prompt、raw tool，也不改 `gravity agent`。

验收：

- 官方 client、MCP Inspector 和两个真实宿主都能一次列出 6 个合法 schema，无宿主专用 prompt；
- 冻结题集中属于这 6 个工具的所有问题首次选择正确 tool/variant，未覆盖题不拿来充成功率；
- 合成 success、empty、partial、capability gap 和三类错误端到端保留 envelope；
- stdout、凭据、生产值门禁通过，现有全套质量门禁不回退；
- 任一宿主需要手工修 schema、错误 structured result 丢失或选择准确率没有改善，则停止，不扩面。

### 阶段 2：补齐 14 tools 并决定是否毕业

补 8 个 product tools 和完整 resources，用全部 20 问题在至少两个宿主做 A/B。仍为 stdio，仍不把
MCP 纳入每条动线的强制闭环判据。

毕业线：首选正确至少 `18/20`（当前 `12/20`），自然语言到合法答案至少 `12/20`（当前 `4/20`）；
32 条已闭环动线全部映射到 tool/resource；无 raw fallback；至少一个现有调用方完成真实试用，第二个
独立调用方或宿主确认采用意向。未达任一项就冻结/移除实验 server，保留生成的 schema 供调用方包装。

### 阶段 3：只在远程需求成立时建设 HTTP/OAuth

前置是明确的部署 owner、租户模型、Gravity 身份映射、IdP 和审计/留存策略。实施 Streamable HTTP、
OAuth resource server、TLS、Origin/限流、租户隔离和远程观测；先单租户再多租户。

验收：跨租户和 resource cache 隔离测试、token audience/scope/revocation、无凭据/生产值日志、限流与
故障演练通过；投影交付身份边界复审完成。没有这些证据，不开放远程 endpoint。

### 阶段 4：有迁移证据后处理旧自然语言层

停止向 recognizer 添加新词和新 owner；盘点现有 `gravity agent` 调用方，发布迁移和弃用期。保留
精确 selector/capability search 与 Plan handoff，先下线自然语言 recognizer，最后才考虑命令外壳。
任何未迁移的 canonical consumer 都阻止删除。

## 哪些决定做了就很难回头

下列内容一旦对外发布就形成兼容承诺：稳定 tool 名、resource URI、discriminator、output wrapper、
错误映射；远程 OAuth scope/audience 和租户身份模型；把 MCP 写进强制闭环判据。它们必须在阶段 2/3
毕业时才冻结。

可先试再改的是：experimental tool 描述与 family 分组、stdio 入口名、resource 集合、SDK pin、
是否提供 prompt，以及阶段 1 的六工具范围。试点文档和客户端必须明确“不保证稳定”。

## 已知不确定项

- 当前仓库没有可证明的现有 consumer MCP 需求、宿主清单或远程部署 owner。
- 不同宿主是否展示 `isError=true` 结果里的 `structuredContent`，规范允许服务器返回，但产品行为需实测。
- 14-tool 的宽 family 是否比 20 卡/现有 recognizer 更易选择，只能由冻结题集 A/B 证明。
- Gravity 上游是否存在可委托的逐用户 token/identity 机制，本仓库证据不足；这决定远程多用户是否可做。
- 规范和 Python SDK 后续演进速度、目标宿主支持的协议版本，无法由当前快照保证。

## 外部事实如何影响但不决定本裁决

ThinkingAI 已在官网以 `query_retention` 示例把标准 MCP、OAuth 与细粒度权限作为交付入口，说明用户会
预期分析平台能被通用助手直接发现；Databox 对现有分析 MCP 的批评则强调“返回可用答案而不是原始
数据”。这些是题设给定的市场背景，与本仓库“上游完成漏斗/留存等计算、版本化 envelope、合同漂移
fail-closed”的内核方向一致。
[ThinkingAI](https://www.thinkingai.cn/)、
[Databox 对分析 MCP 的技术比较](https://databox.com/why-databox-mcp-wins-for-ai-analytics-over-individual-connector-mcps)

但竞争者采用、协议流行或官网演示都不能证明本仓库的调用方需求。最终是否从实验毕业，只看本报告的
宿主准确率、端到端完成率和真实采用判据。
