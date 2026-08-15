# MCP 协议本体与分析类 MCP server 的真实设计

> 调研日期：2026-08-15。协议稳定版以 `2025-11-25` 为准；另行检查了
> `2026-07-28` Release Candidate（RC）。本报告只研究公开、只读资料，不代表厂商产品背书。

## 结论先行

- [实证] MCP 的 `tools`、`resources`、`prompts` 不是三种同义 API：规范把它们分别定位为模型控制的动作、客户端管理的上下文和用户选择的模板；把文件、契约、schema 等稳定上下文全部伪装成 tool，会同时损失 URI、订阅和客户端展示语义。[服务器原语概览](https://modelcontextprotocol.io/specification/2025-11-25/server/index)
- [实证] 稳定版允许 server 在 tool 执行中用 elicitation 向 client 要补充输入，也允许用 sampling 请求 client 的 LLM；但两者都必须先协商可选 capability，且 2026-07-28 RC 已把这种“反向请求”改成客户端重试模型并弃用 sampling，因此不能用它们替代本仓库“未知输入需要两次顶层调用”的稳定契约。[稳定版 elicitation](https://modelcontextprotocol.io/specification/2025-11-25/client/elicitation)；[RC changelog](https://modelcontextprotocol.io/specification/2026-07-28/changelog)
- [实证] “应用分析 MCP 让 LLM 从原始事件自行算漏斗/留存”不符合当前官方实现：GA4、Amplitude、Mixpanel、PostHog 都公开了上游计算的 funnel/retention tool；LLM 主要负责选择参数、构造查询和解释结果。[GA4 tools](https://github.com/googleanalytics/google-analytics-mcp/blob/main/google_analytics_mcp/tools/reporting.py)；[Amplitude tools](https://amplitude.com/docs/amplitude-ai/amplitude-mcp)；[Mixpanel tools](https://docs.mixpanel.com/docs/mcp)；[PostHog tools](https://posthog.com/docs/model-context-protocol/tools)
- [实证] 真实 server 的规模从 ThoughtSpot 当前 8 个、Cube 23 个，到 dbt 61 个、Mixpanel 63 个、Amplitude 68 个可调用项、PostHog 844 个工具；“每个 server 5–15 个”只是实践者启发式，不是协议限制，也没有跨模型通用的准确率曲线。[ThoughtSpot 源码](https://github.com/thoughtspot/mcp-server/blob/79e978603135fc079427db091c2b79bea34cbe68/src/servers/tool-definitions.ts)；[Cube](https://cube.dev/docs/product/apis-integrations/mcp-server)；[dbt](https://github.com/dbt-labs/dbt-mcp)；[Mixpanel](https://docs.mixpanel.com/docs/mcp)；[Amplitude](https://amplitude.com/docs/amplitude-ai/amplitude-mcp)；[PostHog](https://posthog.com/docs/model-context-protocol/tools)
- [推测] 对本仓库最稳妥的切法不是把 185 个 operation 一一暴露，而是把“闭合分析结果”作为 tool、把契约和目录作为 resource、把人工触发的分析配方作为 prompt，并按领域让每次模型可见的 tool 子集保持可辨识；这比给 server 设一个固定总数上限更符合现有厂商和公开实验的共同证据。

## 方法、证据等级与限制

- [实证] 实际使用了官方站点全文检索和页面打开、直接下载公开 Markdown/HTML、GitHub shallow clone 与 raw/API 文件读取、PyPI JSON 元数据，以及本地 `rg`/AST 计数；关键页面与源码快照保存在 `tmp/codex/mcp-protocol-and-servers/sources/`。规范仓库快照为 `4df2d6b6e3588efb46e7542d98498e5c630a0a86`，Python SDK 为 `52ad0a8876f97f631b6e7cb973a786b253088a4d`，dbt MCP 为 `52095631b8075a3fdf8322b085df7f2a1300064d`。[MCP 规范仓库](https://github.com/modelcontextprotocol/modelcontextprotocol)；[Python SDK](https://github.com/modelcontextprotocol/python-sdk)；[dbt MCP](https://github.com/dbt-labs/dbt-mcp)
- [实证] ThoughtSpot 仓库 clone 超时，随后从 GitHub raw/API 按提交 `79e978603135fc079427db091c2b79bea34cbe68` 恢复了 README、版本注册、tool schema 和调度源码；Snowflake 的网页 HTML 体积大且不便审阅，改用官方页面的 Markdown 表示。未登录任何厂商、未调用需授权的 `tools/list`、未安装依赖、未访问付费内容。[ThoughtSpot commit](https://github.com/thoughtspot/mcp-server/tree/79e978603135fc079427db091c2b79bea34cbe68)；[Snowflake 文档](https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-agents-mcp)
- [实证] 本报告的“实证”标签指规范、源码、API 参考、可复现计数或论文公开实验；“厂商宣称”标签指只能验证厂商这样报告、不能独立复现实验效果；“推测”标签是依据已列证据作出的设计判断。标签统计按每个带标签的段落、表格行或列表项计一条，不把一个段落内的多个分句重复计数。

## A. 协议本体

### A1. 三种服务器原语

| 原语 | 规范原话（短引） | 谁决定使用 | 适合内容与边界 |
|---|---|---|---|
| [实证] `prompts` | “Interactive templates invoked by user choice” | 用户 | 可发现、可带参数的消息模板；例如代码审查模板。它不是 server 自动执行的函数。[概览](https://modelcontextprotocol.io/specification/2025-11-25/server/index)；[prompts](https://modelcontextprotocol.io/specification/2025-11-25/server/prompts) |
| [实证] `resources` | “Contextual data attached and managed by the client” | 应用/client | 由 URI 标识、可读或可订阅的上下文，例如文件、数据库 schema、应用专有信息。[概览](https://modelcontextprotocol.io/specification/2025-11-25/server/index)；[resources](https://modelcontextprotocol.io/specification/2025-11-25/server/resources) |
| [实证] `tools` | “Functions exposed to the LLM to take actions” | 模型 | 产生动作或计算的函数，例如查数据库、调 API、执行计算；调用前客户端应提供人工确认能力。[概览](https://modelcontextprotocol.io/specification/2025-11-25/server/index)；[tools](https://modelcontextprotocol.io/specification/2025-11-25/server/tools) |

- [实证] 规范给 resource 的例子包含文本文件、GitHub 仓库、数据库 schema 和应用信息，并支持 `resources/list`、`resources/read`、URI template、列表变化通知和单资源订阅；因此“稳定、可重读、以 URI 定址、主要给模型补上下文”的内容应优先做 resource。[resources](https://modelcontextprotocol.io/specification/2025-11-25/server/resources)
- [实证] tool 结果又可以嵌入 `EmbeddedResource` 或 resource link，所以“查询动作是 tool、返回结果引用一个大资源”是规范内组合，而不是二选一。[tools 返回内容](https://modelcontextprotocol.io/specification/2025-11-25/server/tools)
- [推测] 对本仓库而言，operation manifest、字段契约、分析词汇和只读示例更像 resource；真正发起上游查询、分页导出或聚合的是 tool；“帮我做留存分析”一类由用户显式选用的固定消息脚手架才适合 prompt。依据是上述控制权和生命周期边界，而不是内容是否为 JSON。

### A2. 其他原语和能力

| 能力 | 用途与约束 |
|---|---|
| [实证] `elicitation` | 稳定版 server 可在执行过程中发 `elicitation/create`，让 client 收集表单字段或引导用户到 URL；client 必须先声明 capability，用户可以 accept、decline、cancel，表单模式不得索取敏感信息且只支持受限的扁平 JSON Schema。因此答案是“可以反问，但不是所有 client 都支持”。[elicitation](https://modelcontextprotocol.io/specification/2025-11-25/client/elicitation) |
| [实证] `sampling` | server 可发 `sampling/createMessage` 请求 client 侧 LLM 生成；client 保留模型选择、权限和人工审阅控制，只有 capability 协商成功才可用。2025-11-25 还加入了 sampling 中的 tool calling。[sampling](https://modelcontextprotocol.io/specification/2025-11-25/client/sampling)；[2025-11-25 changelog](https://modelcontextprotocol.io/specification/2025-11-25/changelog) |
| [实证] `roots` | client 用 `roots/list` 告诉 server 可操作的文件系统边界，root 是 `file://` URI；列表可变化并通知。它不是通用权限系统，也不覆盖数据库行级权限。[roots](https://modelcontextprotocol.io/specification/2025-11-25/client/roots) |
| [实证] `completion` | client 对 prompt 参数或 resource-template 参数调用 `completion/complete` 获取候选值；支持分页式 `total`、`hasMore`，但返回值最多 100 项。[completion](https://modelcontextprotocol.io/specification/2025-11-25/server/utilities/completion) |
| [实证] `logging` | server 可发结构化日志通知，client 可用 `logging/setLevel` 设置最低等级；日志不得包含凭证或敏感信息。[logging](https://modelcontextprotocol.io/specification/2025-11-25/server/utilities/logging) |
| [实证] `progress` | 请求方把 `progressToken` 放入 `_meta`，接收方用 `notifications/progress` 报告已完成量、可选总量和消息；token 只在该请求范围内有效。[progress](https://modelcontextprotocol.io/specification/2025-11-25/basic/utilities/progress) |
| [实证] `cancellation` | 任一方可用 `notifications/cancelled` 取消仍在处理的请求；初始化请求不得取消，接收方应停止工作但忽略未知或已完成 ID。[cancellation](https://modelcontextprotocol.io/specification/2025-11-25/basic/utilities/cancellation) |
| [实证] `pagination` | `resources/list`、`prompts/list`、`tools/list` 等列表操作使用不透明 cursor；规范不规定页大小，client 不应解析 cursor。[pagination](https://modelcontextprotocol.io/specification/2025-11-25/server/utilities/pagination) |
| [实证] `ping` | 双方可发空参数 `ping` 检查对端存活；超时后的处置由实现决定。[ping](https://modelcontextprotocol.io/specification/2025-11-25/basic/utilities/ping) |
| [实证] `tasks` | 2025-11-25 的实验性 task 给长任务增加 working/completed/failed/cancelled 状态、TTL 和稍后取结果；并非所有 request 都支持 task augmentation。[tasks](https://modelcontextprotocol.io/specification/2025-11-25/basic/utilities/tasks) |

- [实证] 2026-07-28 RC 的方向变化很大：server 反向请求被 `InputRequiredResult` + client 重试原请求的 Multi-Round Trip Request（MRTR）替代；sampling、roots、logging 被标成 deprecated，tasks 移到 extension。[RC changelog](https://modelcontextprotocol.io/specification/2026-07-28/changelog)
- [推测] 因而未知输入仍应按“两次产品级调用”建模：稳定版 elicitation 只能作为支持它的 client 上的交互增强，RC 的 MRTR 在 wire 上本来也是“收到缺输入结果—补输入—重试”。

### A3. Tool schema、输出和错误

- [实证] `Tool.inputSchema` 是 JSON Schema object；未声明 `$schema` 时默认 dialect 是 JSON Schema 2020-12。`outputSchema` 可选，声明后 server 必须让 `structuredContent` 符合它，client 应验证结果。[tools schema](https://modelcontextprotocol.io/specification/2025-11-25/server/tools)；[2025-11-25 changelog](https://modelcontextprotocol.io/specification/2025-11-25/changelog)
- [实证] 稳定版 `structuredContent` 必须是 JSON object；为了兼容旧 client，server 同时返回其序列化文本是规范的 SHOULD。2026-07-28 RC 才把 structured content 放宽为任意 JSON 值并澄清完整 JSON Schema composition 支持。[稳定版 tools](https://modelcontextprotocol.io/specification/2025-11-25/server/tools)；[RC changelog](https://modelcontextprotocol.io/specification/2026-07-28/changelog)
- [实证] 下例是稳定规范的关键形态；`inputSchema`/`outputSchema` 是声明，`structuredContent` 是机器可判定结果，`content` 是兼容文本或多模态内容。[tools](https://modelcontextprotocol.io/specification/2025-11-25/server/tools)

```json
{
  "name": "get_weather_data",
  "inputSchema": {
    "type": "object",
    "properties": { "location": { "type": "string" } },
    "required": ["location"]
  },
  "outputSchema": {
    "type": "object",
    "properties": { "temperature": { "type": "number" } },
    "required": ["temperature"]
  }
}
```

- [实证] tool 已被正确找到并执行、但业务输入/上游执行失败时，用正常 `CallToolResult` 加 `isError: true`，模型可以读错误并修正；未知 tool、无效 JSON-RPC 参数等协议/框架错误用 JSON-RPC error，不产生 tool result。2025-11-25 还明确 input validation failure 应作为 tool execution error。[tools 错误处理](https://modelcontextprotocol.io/specification/2025-11-25/server/tools)；[changelog](https://modelcontextprotocol.io/specification/2025-11-25/changelog)
- [推测] 协议没有一等 `partial success` 状态；分析工具应在 `outputSchema` 中定义 `status: "partial"`、已完成部分、缺口和可重试 cursor，并保持 `isError: false`。若把部分成功标为 `isError: true`，client 往往会把仍可消费的数据当作失败；这是应用层 schema 设计判断，不是规范强制。

### A4. 传输

| 传输 | Wire 形态 | 合适部署 |
|---|---|---|
| [实证] stdio | client 启动 server 子进程；每行一个 JSON-RPC 消息，stdout 不得混入日志，stderr 可写日志。 | 本机 CLI/IDE、单用户、沿用操作系统进程与环境权限。[transports](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports) |
| [实证] Streamable HTTP | server 暴露单一 MCP endpoint；client 用 POST 发消息，GET 可建立 SSE 流；POST 响应可为单个 JSON 或 SSE。server 必须校验 `Origin`，本地监听应绑定 localhost。 | 远程、多 client、独立扩缩容和 OAuth resource server。[transports](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports) |

- [实证] 旧的、分别使用 HTTP POST 与独立 SSE endpoint 的 “HTTP+SSE transport” 自 `2025-03-26` 起被 Streamable HTTP 替代；SSE 作为流式编码并未废弃，稳定版 Streamable HTTP 仍使用它。[2025-03-26 规范](https://modelcontextprotocol.io/specification/2025-03-26/basic/transports)；[当前 transport](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports)
- [实证] 2026-07-28 RC 又移除 GET session stream、`Mcp-Session-Id`、SSE resumption 和 server-side session，改为 stateless request 与 `subscriptions/listen`；这说明“直接绑死稳定版 HTTP session 细节”存在真实返工面。[RC changelog](https://modelcontextprotocol.io/specification/2026-07-28/changelog)

### A5. 鉴权到底强制什么

- [实证] MCP authorization 是可选能力；用于 HTTP 时，规范说实现应遵守该章，用 stdio 时则不应套 HTTP 流，而应从环境取得凭证。[authorization](https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization)
- [实证] 选择 MCP HTTP authorization 后，MCP server 是 OAuth 2.1 resource server；authorization server 必须实现 OAuth 2.1，MCP server 必须发布 RFC 9728 Protected Resource Metadata，client 必须据此发现授权服务器，并使用 RFC 8707 resource indicators 约束 token audience。[authorization](https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization)
- [实证] authorization-server metadata 可经 RFC 8414 或 OpenID Connect Discovery 获取；动态 client 注册（RFC 7591）是 MAY，Client ID Metadata Documents 是 SHOULD。授权服务器本身的选择、账户体系和策略不由 MCP 规定。[authorization](https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization)
- [实证] server 必须验证 token 是发给自己的，不能接受或透传其他资源的 token；public client 必须用 PKCE，token 不得放在 URI query string。权限 scope 的粒度、角色映射、行级/列级权限和审计策略仍由产品实现。[authorization](https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization)

### A6. 版本协商、历史变化与返工风险

- [实证] 稳定版连接以 `initialize` 开始：client 发其支持的最新版本和 capabilities；server 支持则回同版，否则回另一个它支持的版本；client 不支持回包版本时应断开。HTTP 后续请求用 `MCP-Protocol-Version` header。[lifecycle](https://modelcontextprotocol.io/specification/2025-11-25/basic/lifecycle)
- [实证] 已发布日期版包括 `2024-10-07`、`2024-11-05`、`2025-03-26`、`2025-06-18`、`2025-11-25`；日期字符串是 wire 版本，GitHub tag/release 记录了各版。[GitHub releases](https://github.com/modelcontextprotocol/modelcontextprotocol/releases)

| 版本 | 与绑定风险直接相关的变化 |
|---|---|
| [实证] 2025-03-26 | Streamable HTTP 取代旧 HTTP+SSE；补充 OAuth 2.1 授权框架。[版本页](https://modelcontextprotocol.io/specification/2025-03-26) |
| [实证] 2025-06-18 | 删除 JSON-RPC batching；加入 structured tool output；授权改为 resource-server 模型并要求 resource indicators。[changelog](https://modelcontextprotocol.io/specification/2025-06-18/changelog) |
| [实证] 2025-11-25 | 加 OIDC discovery、URL elicitation、sampling tool calling、CIMD、实验性 tasks、JSON Schema 2020-12，并澄清 tool input validation error。[changelog](https://modelcontextprotocol.io/specification/2025-11-25/changelog) |
| [实证] 2026-07-28 RC | 删除 initialize、session、GET SSE/resumption；加 `server/discover`、MRTR、`subscriptions/listen`；弃用 sampling/roots/logging；tasks 移 extension；引入至少 12 个月 deprecation window。[RC changelog](https://modelcontextprotocol.io/specification/2026-07-28/changelog) |

- [推测] “绑定 MCP 是否会返工”的答案是会，但可隔离：tool/resource/prompt 的产品语义仍可复用，最易变的是 lifecycle、HTTP session、反向请求和基础类型。应把 protocol adapter 保持在 CLI/SDK/Plan/卡片之外，不让 `initialize`、session ID 或 elicitation 状态进入领域 envelope。

## B. 官方 Python SDK 的实际 API

### B1. 最小 tool 与类型声明

- [实证] 当前 PyPI `mcp` 2.0.0 要求 Python `>=3.10`；官方 v2 的最小高层 server 是 `MCPServer` 加装饰器，`run()` 默认 stdio。[PyPI](https://pypi.org/project/mcp/)；[SDK README](https://github.com/modelcontextprotocol/python-sdk)；[运行文档](https://py.sdk.modelcontextprotocol.io/run/)

```python
from mcp.server import MCPServer

mcp = MCPServer("Demo")

@mcp.tool()
def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b

if __name__ == "__main__":
    mcp.run()
```

- [实证] 参数 type hint 生成 `inputSchema`；返回 type hint 生成和校验 `outputSchema`。Pydantic model、TypedDict、dataclass、基础类型和 dict 均可用；基础返回值如 `int` 被包装为 `{"result": ...}`，也可用 `structured_output=False` 关闭结构化输出。[structured output](https://github.com/modelcontextprotocol/python-sdk/blob/main/docs/servers/structured-output.md)

### B2. 异常怎样变成 error

- [实证] handler 抛普通异常时，SDK 返回 `CallToolResult(isError=True)`，错误文字在 content 中而没有 structured content；抛 `MCPError` 则成为 JSON-RPC protocol error，没有 tool result。SDK 在 handler 前完成的输入验证失败也走 tool error。[handling errors](https://github.com/modelcontextprotocol/python-sdk/blob/main/docs/servers/handling-errors.md)
- [推测] 因此领域校验失败、上游拒绝和可重试超时应返回 tool error 或明确的领域 partial；只有未知方法、协议状态和框架级非法请求才值得抛 `MCPError`。这与稳定规范的模型一致，但具体分类仍需本仓库定义。

### B3. stdio / HTTP 骨架与依赖重量

- [实证] `mcp.run()` 是 stdio；`mcp.run(transport="streamable-http", host=..., port=...)` 启动 HTTP；也可将 `streamable_http_app()` 挂入 ASGI。v2 的同一 HTTP app 可兼容 legacy 与 current protocol era。[运行文档](https://py.sdk.modelcontextprotocol.io/run/)；[legacy clients](https://github.com/modelcontextprotocol/python-sdk/blob/main/docs/run/legacy-clients.md)
- [实证] PyPI `requires_dist` 的核心逻辑依赖有 14 个名称：`anyio`、`httpx2`、`jsonschema`、`mcp-types`、`opentelemetry-api`、`pydantic`、`pyjwt[crypto]`、`python-multipart`、条件式 `pywin32`、`sse-starlette`、`starlette`、`typing-extensions`、`typing-inspection`、条件式 `uvicorn`；CLI extra 另加 `python-dotenv`、`typer`。[PyPI JSON](https://pypi.org/pypi/mcp/json)
- [推测] 对“不引入大依赖”敏感的本仓库，这不是轻量零依赖适配器。优先做 optional extra/独立 entrypoint；手写 wire 虽可少依赖，却会把上节列出的版本迁移负担留给自己，不能只比较安装体积。

## C. 分析类 MCP server 的真实工具面

### C1. 横向总表

> 数量口径：优先按当前官方文档的可调用 tool；若 server 动态配置，则写“类型/实例上限”；动态发现器与业务 tool 分开计数。数量会随日期变化，不能当永久常数。

| Server | 当前公开数量 | 设计取向 | 数据形态 | 分页/预算/权限 |
|---|---:|---|---|---|
| [实证] Snowflake managed | 5 种 tool type；每个 server 配置 0–50 个实例 | Cortex Agent 是 outcome；Analyst/Search/SQL 是能力适配器 | Agent/Analyst 给答案或 SQL，Search 给命中，SQL 给查询结果 | 50-tool 上限、generic/SQL 响应 250 KB 截断、Agent 递归最多 10；Snowflake RBAC/OAuth。[文档](https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-agents-mcp) |
| [实证] ThoughtSpot | 当前 V2 8；兼容 V1 5 | 会话式 outcome orchestration | Spotter 已计算 answer，V1 answer 可含 CSV | `search_objects` cursor；会话轮询；OAuth 和当前 org 权限；未公开统一结果预算。[源码](https://github.com/thoughtspot/mcp-server/blob/79e978603135fc079427db091c2b79bea34cbe68/src/servers/tool-definitions.ts) |
| [实证] Cube | 23 | semantic query + 内容/模型运维混合 | `chat` 答案、Cube SQL 结果、workbook/report 对象 | `loadQueryResults`/offset 分页；viewer/RBAC/RLS；6 个破坏性 tool 要确认。[文档](https://cube.dev/docs/product/apis-integrations/mcp-server) |
| [实证] Amplitude | 65 业务 tool；progressive 模式共 68、初始只暴露 4 | 多领域 API + 统一分析查询 | 已计算 segmentation/funnel/retention，也有元数据和管理对象 | 按 tool 分页/截断；项目 RBAC；无统一预算。[文档](https://amplitude.com/docs/amplitude-ai/amplitude-mcp) |
| [实证] Mixpanel | 63 | 产品对象 API + `Run-Query` outcome | 已计算 insights/funnels/flows/retention | 600 requests/hour/user；项目权限；公开页未给统一结果预算。[文档](https://docs.mixpanel.com/docs/mcp) |
| [实证] PostHog | 844，分 65 类 | 大规模 API 1:1 翻译 + 12 个分析 wrapper | 已计算 funnel/retention/trends 等，也可 SQL/对象 CRUD | tool/feature filter、逐 tool scope；无跨 844 tool 的统一分页/预算。[tools](https://posthog.com/docs/model-context-protocol/tools)；[FAQ](https://posthog.com/docs/model-context-protocol/faq#filtering-available-mcp-tools) |
| [实证] dbt Labs | README 当前列 61 | toolset 式平台 API + Semantic Layer outcome | 受治理 metric 查询、compiled SQL、metadata/CLI 结果 | dimension values 默认 100 并给 `truncated`；平台 token/toolset 权限；无统一预算。[README](https://github.com/dbt-labs/dbt-mcp)；[semantic 源码](https://github.com/dbt-labs/dbt-mcp/tree/main/src/dbt_mcp/tools/semantic_layer) |

### C2. Snowflake managed MCP server

- [实证] 配置中的五种 type 是 `CORTEX_AGENT_RUN`、`CORTEX_SEARCH_SERVICE_QUERY`、`CORTEX_ANALYST_MESSAGE`、`SYSTEM_EXECUTE_SQL`、`GENERIC`；tool `name` 由部署者自定，所以不存在一个全球固定的 tool-name 清单。官方例子用 `business_data_agent`、`revenue-semantic-view`、`product-search`、`sql_exec_tool`、`my_custom_tool`。[配置参考](https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-agents-mcp)
- [实证] `CORTEX_ANALYST_MESSAGE` 的公开输入是 `{"message":"..."}`，返回文字和生成的 SQL但不执行 SQL；Search 至少接收 `query`，可选 `columns`、`limit`，返回命中及 request ID；Agent 接收自然语言消息并返回最终响应与 intermediate steps。[文档示例](https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-agents-mcp)
- [实证] `SYSTEM_EXECUTE_SQL` 的文档公开了 `read_only`（默认 true）、`query_timeout`、`warehouse` 配置，却没有在该页给出完整调用 input schema；因此本报告不猜字段。`GENERIC` 的 input schema 由所绑定 UDF/存储过程签名决定。[文档](https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-agents-mcp)
- [实证] Snowflake 建议以一个 Cortex Agent 提供受治理业务问答，并将直接 SQL 放到独立 server，因为 SQL 会绕过语义模型；这是最明确的“outcome 与 escape hatch 隔离”实例。[最佳实践](https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-agents-mcp)
- [实证] 该 managed server 宣称支持 MCP `2025-11-25`，但只支持 tools，并明确不支持 resources、prompts、roots、notifications、sampling、完整生命周期和版本协商；这是“兼容某版本”与“实现整套规范”之间的官方文档张力。[limitations](https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-agents-mcp)

### C3. ThoughtSpot Agentic MCP Server

- [实证] 当前 `latest`/`2026-05-01` 的 8 个 tool 是：`search_objects`、`check_connectivity`、`create_analysis_session`、`send_session_message`、`get_session_updates`、`create_dashboard`、`list_orgs`、`switch_org`。[版本注册](https://github.com/thoughtspot/mcp-server/blob/79e978603135fc079427db091c2b79bea34cbe68/src/servers/version-registry.ts)；[tool enum](https://github.com/thoughtspot/mcp-server/blob/79e978603135fc079427db091c2b79bea34cbe68/src/servers/tool-definitions.ts)
- [实证] 会话三件套的真实形态是：创建时可传 `data_source_id`，回 `analytical_session_id`；发送时传 session ID、`message`、可选 `additional_context`；轮询更新回 `updates[]` 与 `is_done`，update 类型含 `text`、`text_chunk`、`answer`、`step_notification`，answer 可带 ID、标题、query、data-source ID 和 iframe URL。[schema 源码](https://github.com/thoughtspot/mcp-server/blob/79e978603135fc079427db091c2b79bea34cbe68/src/servers/tool-definitions.ts)
- [实证] `search_objects` 支持 query、对象类型、author、tag、modified_since、verified、limit、cursor，并回 `next_cursor`；`create_dashboard` 接收标题、note tile 和 `answers[{answer_id,title}]`，回 dashboard link。[schema 源码](https://github.com/thoughtspot/mcp-server/blob/79e978603135fc079427db091c2b79bea34cbe68/src/servers/tool-definitions.ts)
- [实证] 兼容 V1 的 5 个旧 tool 是 `ping`、`createLiveboard`、`getDataSourceSuggestions`、`getRelevantQuestions`、`getAnswer`；`getAnswer` 返回 ThoughtSpot 已算答案，可含 CSV string、session/generation/frame URL 和字段信息，不是把原始事件交给 LLM。[README](https://github.com/thoughtspot/mcp-server/blob/79e978603135fc079427db091c2b79bea34cbe68/README.md)；[schema](https://github.com/thoughtspot/mcp-server/blob/79e978603135fc079427db091c2b79bea34cbe68/src/servers/tool-definitions.ts)

### C4. Cube MCP

- [实证] 23 个 tool 的完整名单为：`listDeployments`、`chat`、`loadQueryResults`；`searchDataModel`、`runQuery`；`readWorkbook`、`createWorkbook`、`createReport`、`readReport`、`updateReport`、`deleteReport`、`updateDashboard`、`publishDashboard`；`listDataModelFiles`、`readDataModelFile`、`startDataModelEdit`、`writeDataModelFile`、`deleteDataModelFile`、`getDataModelChanges`、`getBranchDiff`、`getDeploymentEnv`；`getPreAggregationStatus`、`buildPreAggregation`。[官方清单](https://cube.dev/docs/product/apis-integrations/mcp-server)
- [实证] `chat` 接收 `input` 和可选 deployment/agent ID，返回答案与生成 SQL；`runQuery` 执行 Cube SQL，返回 schema、当前页 rows、`hasMore`、`totalRows`；`loadQueryResults` 取先前查询后续页。`searchDataModel` 先返回紧凑的受治理 metric/dimension/member 信息。[官方清单](https://cube.dev/docs/product/apis-integrations/mcp-server)
- [实证] Cube 要求至少 Viewer，继承 deployment permission、RBAC 和 row-level security；涉及删除、写模型或发布的 6 个 tool 要用户确认。公开文档给参数说明但没有给全部 23 项的完整 JSON Schema。[安全说明](https://cube.dev/docs/product/apis-integrations/mcp-server)

### C5. Amplitude 官方 MCP

- [实证] 官方表按领域列出 65 个业务 tool；名单如下（分号分领域）：[官方 tool 表](https://amplitude.com/docs/amplitude-ai/amplitude-mcp)

```text
search, get_from_url, get_amplitude_context, get_workspace_context;
get_charts, get_dashboard, get_cohorts, get_experiments, get_users, get_flags,
get_deployments, get_agent_results;
get_events, get_properties, update_properties, get_custom_or_labeled_events,
update_custom_or_labeled_events, update_event, get_transformations, get_group_types;
get_session_replays, list_session_replays, get_session_replay_events;
query_chart, query_charts, query_amplitude_data, query_experiment, render_chart;
save_chart_edits, create_dashboard, create_notebook, create_experiment, create_cohort,
create_flags, create_metric, create_events, create_custom_event, create_properties;
get_cohort_sync_destinations, get_cohort_syncs, get_cohort_sync_history, sync_cohort;
get_branches, create_branch, update_branch, refresh_branch, merge_branch, delete_branch;
edit_dashboard, edit_notebook, update_experiment, update_flag;
list_guides_surveys, get_guide_or_survey; use_amplitude_ai_feedback;
query_agent_analytics_metrics, query_agent_analytics_sessions,
query_agent_analytics_spans, get_agent_analytics_conversation,
search_agent_analytics_conversations, get_agent_analytics_schema;
get_data_ingestion_sources, get_data_source_details,
get_data_warehouse_destinations, get_data_warehouse_jobs
```

- [实证] progressive 模式另有 `list_tool_categories`、`get_category_tools`、`describe_tool`；它初始只暴露这 3 个加 `get_amplitude_context`，但经发现可调用的唯一工具总数是 68，而不是“只有 4 个”。[progressive loading](https://amplitude.com/docs/amplitude-ai/amplitude-mcp)
- [实证] `query_amplitude_data` 明确支持 segmentation、funnels、retention 的 discover/execute 两阶段；`query_chart(s)` 取得已保存分析的数据。相反，`get_events` 在 taxonomy 区，返回事件定义/元数据，不是逐行原始事件流。[官方 tool 表](https://amplitude.com/docs/amplitude-ai/amplitude-mcp)
- [实证] server 用 Streamable HTTP/OAuth；每次调用按当前用户和 project 做权限检查，tool 即使无权限仍可能可见。公开页面没有给出全部调用 JSON Schema，真实 schema 要通过已授权的 `describe_tool` 获取，本调研没有登录调用。[权限与 progressive loading](https://amplitude.com/docs/amplitude-ai/amplitude-mcp)

### C6. Mixpanel 官方 MCP

- [实证] 当前官方表共 63 个 tool，完整名单如下；旧介绍文章里的 “30+” 不能覆盖当前版本。[当前官方表](https://docs.mixpanel.com/docs/mcp)

```text
Run-Query, Get-Query-Schema, Get-Report, Display-Query;
Create-Dashboard, List-Dashboards, Get-Dashboard, Update-Dashboard,
Duplicate-Dashboard, Delete-Dashboard;
Get-Business-Context, Get-Projects, List-Organizations, Get-Events,
List-Properties, Get-Property-Values, Search-Entities, Get-Issues, Get-Lexicon-URL;
Edit-Event, Edit-Property, Bulk-Edit-Events, Bulk-Edit-Properties, Create-Tag,
Rename-Tag, Delete-Tag, Dismiss-Issues, Update-Business-Context,
Find-Duplicate-Groups, Dismiss-Duplicate-Group, Merge-Group;
Create-Custom-Property, Get-Custom-Property, Update-Custom-Property;
Create-Cohort, Get-Cohort, Update-Cohort, Delete-Cohort, List-Cohorts,
Describe-Cohort-Schema;
Create-Lookup-Table, Get-Lookup-Table, Update-Lookup-Table;
Create-Metric, Get-Metric, List-Metrics, Update-Metric;
Get-User-Replays-Data;
List-Experiments, Get-Experiment, Create-Experiment, Update-Experiment,
Get-Experiment-Setup-Guidance, Get-Experiment-Results-Interpretation-Guidance,
Explain-Experiment-Health-Check, Run-Experiment-Pre-Launch-Checks,
Search-Prior-Experiments;
List-Feature-Flags, Get-Feature-Flag, Create-Feature-Flag, Update-Feature-Flag,
Get-Feature-Flag-Setup-Guidance, Get-Feature-Flag-Lifecycle-Guidance
```

- [实证] `Run-Query` 直接执行 insights、funnels、flows、retention；`Get-Query-Schema` 在运行时返回构造查询所需的完整 JSON Schema；`Get-Report` 可选择连结果一起返回。因此它是上游分析引擎，不是原始事件 dump。[Analytics tools](https://docs.mixpanel.com/docs/mcp)
- [实证] 官方页公开 tool 名和用途，但没有逐项静态 input/output schema；OAuth 或 beta service account 继承项目权限，速率限制是每用户每小时 600 请求。[authentication and rate limits](https://docs.mixpanel.com/docs/mcp)

### C7. PostHog 官方 MCP

- [实证] 2026-08-15 抓取的官方清单按 65 个分类机械计数为 844 个工具；完整逐项清单在官方页面，本文不复制 844 行，而保留分类计数和与分析判断直接相关的精确名称。[官方完整清单](https://posthog.com/docs/model-context-protocol/tools)
- [实证] 分类规模包括：AI observability 82、customer analytics 50、experiments 39、signals 60、workflows 30、replay vision 29、warehouse sources 26、tasks 24、error tracking 24、data warehouse 22、skills 21 等；这明显是大范围产品 API 暴露，而不是 5–15 个 outcome-only server。[官方完整清单](https://posthog.com/docs/model-context-protocol/tools)
- [实证] 分析关键工具是 `read-data-schema`、`insight-query`、`execute-sql`、`data-catalog-metric-run`，以及 12 个 query wrapper：`query-funnel`、`query-funnel-actors`、`query-lifecycle`、`query-lifecycle-actors`、`query-paths`、`query-paths-actors`、`query-retention`、`query-retention-actors`、`query-stickiness`、`query-stickiness-actors`、`query-trends`、`query-trends-actors`。[官方完整清单](https://posthog.com/docs/model-context-protocol/tools)
- [实证] 开源定义把 wrapper 绑定到 `AssistantFunnelsQuery`、`AssistantRetentionQuery` 等 typed query，标为 read-only/idempotent，要求 `query:read` scope，并提供优化后的结构化输出；actor 版本是从已算分析追到参与实体。[query wrapper definitions](https://github.com/PostHog/posthog/blob/master/services/mcp/definitions/query-wrappers.yaml)
- [实证] 连接 URL 可用 `tools`/`features` query 参数过滤可见能力；不传时暴露全部可用工具。这是 client 前置削减，而不是协议自动替模型选择。[FAQ](https://posthog.com/docs/model-context-protocol/faq#filtering-available-mcp-tools)

### C8. dbt Labs MCP

- [实证] README 当前列出的 61 个 tool 如下；实际暴露子集取决于启用 toolset、凭证和 dbt 产品能力。[README](https://github.com/dbt-labs/dbt-mcp)

```text
SQL: execute_sql, text_to_sql
Semantic Layer: get_dimension_values, get_dimensions, get_entities,
get_metrics_compiled_sql, list_metrics, list_saved_queries, query_metrics
Discovery: get_all_macros, get_all_models, get_all_sources, get_exposure_details,
get_exposures, get_lineage, get_macro_details, get_mart_models, get_model_children,
get_model_details, get_model_health, get_model_parents, get_model_performance,
get_node_details, get_related_models, get_seed_details, get_semantic_model_details,
get_snapshot_details, get_source_details, get_test_details, search
dbt CLI: build, clone, compile, docs, get_lineage_dev, get_node_details_dev,
list, parse, run, show, test
Admin: cancel_job_run, get_job_details, get_job_run_details, get_job_run_error,
list_job_run_artifacts, list_jobs, list_jobs_runs, list_projects, retry_job_run,
trigger_job_run
Codegen: generate_model_yaml, generate_source, generate_staging_model
LSP: fusion.compile_sql, fusion.get_column_lineage, get_column_lineage
Docs: get_product_doc_pages, search_product_docs
Metadata: get_mcp_server_branch, get_mcp_server_version
```

- [实证] Semantic Layer 的真实类型包括 `GroupByParam{name, grain?}`、`OrderByParam{name, descending=false, grain?}`；`query_metrics` 接收 metrics、group_by、order_by、where、limit 并返回受治理计算结果，`get_metrics_compiled_sql` 用相同查询维度返回 compiled SQL。[semantic 源码](https://github.com/dbt-labs/dbt-mcp/tree/main/src/dbt_mcp/tools/semantic_layer)
- [实证] `get_dimension_values` 接收 dimension、可选 metrics 和 `limit`（默认 100、最小 1），结果明确包含 `values`、`truncated`、`error`；这是少数公开表达截断状态的实现。[semantic 源码](https://github.com/dbt-labs/dbt-mcp/tree/main/src/dbt_mcp/tools/semantic_layer)
- [推测] dbt 的好处是把 metric 语义和计算留在 Semantic Layer，代价是 61 个总工具混入 CLI、Admin、Docs 与 LSP；面对只做分析的 agent，按 toolset 限制可见集合比全量暴露更合理。

### C9. “LLM 自己从原始事件算漏斗”横评是否成立

- [实证] GA4 官方 server 当前有 9 个 tool：`get_account_summaries`、`list_google_ads_links`、`get_property_details`、`list_property_annotations`、`get_custom_dimensions_and_metrics`、`run_report`、`run_realtime_report`、`run_funnel_report`、`run_conversions_report`。[官方仓库](https://github.com/googleanalytics/google-analytics-mcp)
- [实证] `run_funnel_report` 接收 property ID、`funnel_steps`、date ranges、可选 breakdown/next action/segments，返回 `funnel_table`、`funnel_visualization` 和可选 quota；漏斗由 Google Analytics Data API 计算。[源码](https://github.com/googleanalytics/google-analytics-mcp/blob/main/google_analytics_mcp/tools/reporting.py)；[GA Data API funnel](https://developers.google.com/analytics/devguides/reporting/data/v1/rest/v1alpha/properties/runFunnelReport)
- [实证] Amplitude 有 `query_amplitude_data` 的 funnel/retention，Mixpanel `Run-Query` 明列 funnels/retention，PostHog 有 typed `query-funnel`/`query-retention` wrappers；四者都返回平台计算结果，而不是把全量原始事件交给 LLM。[Amplitude](https://amplitude.com/docs/amplitude-ai/amplitude-mcp)；[Mixpanel](https://docs.mixpanel.com/docs/mcp)；[PostHog](https://posthog.com/docs/model-context-protocol/tools)
- [推测] 所以该横评对“当前官方 GA4/Amplitude/Mixpanel/PostHog”不成立。较窄且成立的说法是：LLM 仍承担查询选择、过滤/分组参数组织和结果解释；如果横评研究的是旧版本或社区 server，结论可能不同，但其版本和 tool 清单未给出，无法外推。

## D. Tool 数量的量化经验

### D1. “5–15 个”从哪里来

- [实证] MCP 规范没有 5–15 上限；实践者 Phil Schmid 的文章明确建议每 server 约 5–15，ZenML 对 Prefect 实践演讲的整理也写 “ideally 5–15”，但两者都没有给支撑该区间的公开对照实验或原始准确率数据。[Phil Schmid](https://www.philschmid.de/mcp-best-practices)；[ZenML/Prefect 摘要](https://www.zenml.io/llmops-database/best-practices-for-building-production-grade-mcp-servers-for-ai-agents)；[MCP tools 规范](https://modelcontextprotocol.io/specification/2025-11-25/server/tools)
- [推测] 因此 5–15 应称“工程启发式”：它适合作为默认可见工具集的审查阈值，不适合作为 server 总容量、合规线或性能保证。

### D2. 有哪些公开量化结果

| 研究 | 数据与结果 | 能说明什么 / 不能说明什么 |
|---|---|---|
| [实证] ANSYR（2026） | 单一组织生产日志按 1/3/5/10/15/20/30/50 tool 分桶，每桶 200 turns；Claude Haiku 4.5 在 10 tools 约 91%、15 tools 87%，Sonnet 在 20 以内仍约 90%、30 时下降。[论文](https://arxiv.org/html/2606.30317) | 有近似曲线，但只是一个组织的观测数据，任务难度/路由可能混杂，原始日志未公开，不能推出通用 15 上限。 |
| [实证] Adaptive Tool Discovery（2026） | BFCL 370 个工具上，动态约 7 个候选达 coverage 90.3%，固定 50 个为 90.8%；Claude Sonnet 4.6 的 downstream tool choice 为 93.1%，固定 5 个为 87.1%，中等难度子集为 76.8% 对 60.9%。[论文](https://arxiv.org/abs/2605.24660) | 证明“过少”也会伤害覆盖率，最佳 k 依查询和模型而变；不是单调的工具越少越准。 |
| [实证] RAG-MCP（2026） | 121 tools、5 servers、140 queries 上，top-3 retrieval hit 97.1%、MRR 0.91、tool-definition token 减少 99.6%、检索小于 100 ms。[论文](https://arxiv.org/html/2603.20313) | 量化的是检索召回/成本，不是端到端正确执行；数据集小，不能当生产准确率曲线。 |
| [厂商宣称] Anthropic Advanced Tool Use | 厂商内部 5-server/58-tool MCP eval 中，tool search 报告 Opus 4 从 49% 到 74%、Opus 4.5 从 79.5% 到 88.1%，tool definition token 减少 85%。[Anthropic 工程博客](https://www.anthropic.com/engineering/advanced-tool-use) | 有明确测试数字，但未提供足以独立复现的完整评测集；同时厂商说少于约 10 个工具时收益较小。 |
| [实证] MCP-Zero（2025） | 数据集含 308 个 server、2,797 个 tool，用 server→tool 层次检索；论文报告 APIBank 上 token 减少 98%。[论文](https://arxiv.org/abs/2506.01056) | 说明大目录可以分级检索，但任务集和 router 决定效果，不能直接换算为本仓库准确率。 |

- [推测] 现有证据支持的是“全量 schema 进上下文会贵、相似工具会混淆、候选集需要随任务变化”，不支持一个跨模型、跨任务、跨 tool 描述质量的固定准确率曲线。

### D3. 缓解手段与代价

| 手段 | 已有实例 | 代价 |
|---|---|---|
| [实证] 领域分组/allow-list | dbt toolsets、PostHog URL `tools`/`features` filter、Snowflake 多 server 配置。[dbt](https://github.com/dbt-labs/dbt-mcp)；[PostHog](https://posthog.com/docs/model-context-protocol/faq#filtering-available-mcp-tools)；[Snowflake](https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-agents-mcp) | 配置可预测、权限边界清楚；跨领域任务要切换集合，维护多份 profile。 |
| [实证] 动态/渐进加载 | Amplitude 初始 4 个、按 category/description 展开到 68 个；Anthropic deferred tools/tool search。[Amplitude](https://amplitude.com/docs/amplitude-ai/amplitude-mcp)；[Anthropic](https://www.anthropic.com/engineering/advanced-tool-use) | 降 token，但增加检索步骤和延迟；检索漏召回就永远看不到正确 tool，并依赖 client 能力。 |
| [实证] RAG-MCP / vector top-k | RAG-MCP 与 MCP-Zero 都先检索 server/tool，再注入少量 schema。[RAG-MCP](https://arxiv.org/html/2603.20313)；[MCP-Zero](https://arxiv.org/abs/2506.01056) | 能扩到大目录；要维护索引、embedding 与更新一致性，description 质量成为隐含契约。 |
| [推测] Gateway/router | 在 MCP server 前按租户、领域和权限选 server/tool，可集中审计与限流；这是上述分组和检索的部署化组合。 | 新增单点、路由误判、缓存版本和权限组合问题；协议本身不提供 gateway 语义。 |
| [推测] Outcome composite | 用一个业务结果 tool 取代一串底层 endpoint，ThoughtSpot 会话、Snowflake Agent、Cube chat 可作参照。 | 调用更少但容易形成参数过宽的 god-tool；必须维持窄 schema、明确缺口和可观测中间状态。 |

## 对本仓库的意义

### 先纠正基数

- [实证] 题目给的 “185 operations、47 条分析动线”与当前仓库文档一致：roadmap 记录 176 stable / 185 total operations，以及 47 条 journeys（32 closed、0 partial、15 missing）。[roadmap](../roadmap.md)
- [实证] 2026-08-15 调研快照中，“15 张固定 composite 卡”与源码不一致：`_COMPOSITE_CAPABILITIES` 当时机械计数是 20 项；2026-08-16 派生层新增后为 21 项。15 是当时 roadmap 中尚缺失的 journey 数，不是 composite 卡数。[agent_capabilities.py](../../src/gravity_sdk/agent_capabilities.py)；[roadmap](../roadmap.md)
- [推测] 如果另有尚未落库的“未来只公开 15 张 MCP 卡”方案，应按 15 评审；就当前代码做设计则必须按 20 评审。本报告不把计划数冒充现状。

### 推荐切法

| MCP 面 | 建议承载 | 理由 |
|---|---|---|
| [推测] Tools | 以 closed analysis journey/composite 为主，如漏斗、留存、归因等已由上游计算的结果；不要把 185 operation 1:1 暴露。 | ThoughtSpot/Snowflake/Cube 的 outcome 层减少多步编排；GA4/Amplitude/Mixpanel/PostHog 证明计算型分析 tool 是主流真实形态。 |
| [推测] Resources | operation/catalog manifest、字段契约、schema、能力矩阵、分析词汇、示例和大结果引用。 | 这些是可定址、可重读的上下文，符合 resource 的 URI/read/subscription 语义，不需要模型“调用”。 |
| [推测] Prompts | 用户显式选择的分析配方、诊断/复盘模板，不承担真实数据查询。 | 保留 prompts 的 user-controlled 边界，避免 prompt 与 tool 争夺自动调用语义。 |
| [推测] Expert escape hatch | 默认隐藏的 `operation_discover` + 受治理 `operation_execute`，或按领域启用的少量底层 tool；不能是无约束任意 URL/SQL。 | 可保住 composite 尚未覆盖的读取能力，同时避免 185 schemas 常驻上下文；Snowflake 把直接 SQL 分 server 是可参考的隔离。 |

- [推测] 若 MCP 总面是当前 20 张卡，不必为了“15 上限”删除能力；应给卡做领域分组/动态曝光，使一次任务通常只看到能清楚区分的子集。若未来精选为 15 张，它“落在启发式上沿”主要是巧合，只有当 15 张确实对应互斥、闭合、窄 schema 的用户 outcome 时才有产品理由。
- [推测] 一个保守的首版可见面是：按 `analysis context`、增长/行为、商业化/广告、内容/账号、组织/治理等领域选组；跨域任务再通过发现 tool 扩展。具体分组必须用真实卡片描述和离线 tool-selection eval 验证，本报告不凭名称给出永久分组。
- [推测] 未知输入的现有 2-call 约定应保持。不要让稳定版 elicitation 把某些 client 看起来压成一次交互，也不要提前绑定 RC MRTR；在 envelope 中继续显式给出缺失字段和下一调用参数。
- [推测] 现有 `schema_version`、empty/partial/gap、显式调用次数和未登记字段 fail-closed 应直接映射到 `outputSchema` + `structuredContent`；MCP 没有原生 partial，因此不能丢掉领域状态。大结果可在 content 中给摘要，在 structured content 中给 resource link/cursor。
- [推测] 本地优先可从 stdio 起步，复用 CLI 权限和固定 host/path；远程 Streamable HTTP/OAuth 应作为独立部署决策。Python SDK v2 提供骨架和双时代兼容，但 14 个核心逻辑依赖与本仓库轻依赖目标冲突，适合 optional extra 而非强制 core dependency。

### 哪些应学、哪些不应学

- [推测] 应学：dbt 的明确 `truncated`、Cube 的分页结果、Snowflake 的 semantic/SQL 隔离、Amplitude 的 progressive discovery、PostHog 的逐 tool scope/filter；这些都补足“机器可判定的预算、能力发现、权限最小化”。
- [推测] 不应学：PostHog 式 844 tool 默认全开、把 CRUD/运维/分析混为一个模型上下文、只在自然语言里说明截断、或把 SQL 当成语义分析的默认入口；它们会弱化本仓库现有的受治理 outcome 和 fail-closed 边界。
- [实证] 本仓库已有而多数公开厂商清单没有统一表达的能力，是顶层调用次数、`schema_version`、empty/partial/gap 与未登记字段 fail-closed；厂商往往只在个别 tool 提供 cursor、limit 或 truncated，而 MCP 规范本身也不定义这些分析语义。[agent workflow](../agent-workflow.md)；[MCP tools](https://modelcontextprotocol.io/specification/2025-11-25/server/tools)
- [推测] 本仓库落后之处是尚无标准 MCP discovery/transport/OAuth surface，也没有用公开、可运行的 tool-selection eval 验证 20 张卡在不同模型上的区分度；不能用“卡数量小于厂商”代替这两项工程证据。

## 没能查到的关键问题

- [实证] Snowflake 公开页面没有给 `SYSTEM_EXECUTE_SQL` 的完整调用 input/output JSON Schema，只给 tool 配置；未登录实例，因此没有抓 `tools/list` 补齐。[Snowflake 文档](https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-agents-mcp)
- [实证] Amplitude 和 Mixpanel 公开页面没有静态公布每个 tool 的完整 input/output JSON Schema；Amplitude 要用已授权 `describe_tool`，Mixpanel 要用 `Get-Query-Schema` 获取查询 schema，本调研按约束没有认证调用。[Amplitude](https://amplitude.com/docs/amplitude-ai/amplitude-mcp)；[Mixpanel](https://docs.mixpanel.com/docs/mcp)
- [实证] 没有找到覆盖不同模型、不同任务、相同 tool 描述质量并可复现的“tool 数量—准确率通用曲线”；现有公开结果分别是单组织观测、特定 benchmark 或检索召回实验。[ANSYR](https://arxiv.org/html/2606.30317)；[Adaptive Tool Discovery](https://arxiv.org/abs/2605.24660)；[RAG-MCP](https://arxiv.org/html/2603.20313)
- [实证] 没有找到 “5–15” 最初提出者或同行评审依据；只能找到实践者文章和演讲整理中的建议。[Phil Schmid](https://www.philschmid.de/mcp-best-practices)；[ZenML/Prefect 摘要](https://www.zenml.io/llmops-database/best-practices-for-building-production-grade-mcp-servers-for-ai-agents)
- [实证] 没有找到上述厂商统一、可横比的“每次 token/row/byte/time 预算”字段；能确认的只是 Snowflake 250 KB、Mixpanel 600 req/hour、dbt dimension truncation、Cube/PostHog/ThoughtSpot 的局部分页，不能据此排出完整预算优劣。[Snowflake](https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-agents-mcp)；[Mixpanel](https://docs.mixpanel.com/docs/mcp)；[dbt](https://github.com/dbt-labs/dbt-mcp)；[Cube](https://cube.dev/docs/product/apis-integrations/mcp-server)；[PostHog](https://posthog.com/docs/model-context-protocol/tools)；[ThoughtSpot](https://github.com/thoughtspot/mcp-server)
- [实证] 未找到所质疑横评的原始版本、server 仓库和 tool 快照，因此只能判定它不适用于当前四个官方实现，不能判断它在发表当时或社区实现上是否曾成立。[GA4](https://github.com/googleanalytics/google-analytics-mcp)；[Amplitude](https://amplitude.com/docs/amplitude-ai/amplitude-mcp)；[Mixpanel](https://docs.mixpanel.com/docs/mcp)；[PostHog](https://posthog.com/docs/model-context-protocol/tools)

## 最可能出错的判断

- [推测] 最可能出错的是“按 outcome composite 暴露、一次任务只显示约 10–15 个候选会优于全量 20 个”。理由是它综合了厂商结构、单组织观测和检索 benchmark，却还没有用本仓库 20 张卡的真实描述、真实问题分布和目标模型做离线选择实验；如果卡片高度可辨、模型更强或跨域问题很多，全量 20 个可能反而更好。它应被当作待验证的首版假设，而不是架构定律。
