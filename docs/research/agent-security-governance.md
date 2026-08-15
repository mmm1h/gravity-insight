# Agent 场景下的数据访问安全与治理

调研日期：2026-08-15

## 结论摘要

**E01 [实证]** 工具结果中的间接 prompt injection 已有可复现案例：攻击者把指令放进公开 GitHub issue 或 WhatsApp 消息，agent 读取后会调用另一个高权限工具并外传私有数据；因此分析结果中的昵称、备注、事件属性等用户可控字符串属于同一类“不可信工具输出”，不能因为它来自已授权的数据接口就当成可信指令。[Invariant GitHub MCP PoC](https://invariantlabs.ai/blog/mcp-github-vulnerability)、[Invariant WhatsApp MCP PoC](https://invariantlabs.ai/blog/whatsapp-mcp-exploited)、[GHSA-7r34-79r5-rcc9](https://github.com/advisories/GHSA-7r34-79r5-rcc9)

**E02 [实证]** MCP 官方并不允许“拿客户端给的上游 token 原样转发”：远程 MCP 的入站 token 必须绑定 MCP server 这个 audience，server 调上游时必须使用另一枚由上游签发的 token；官方把 token passthrough 明确定义为禁用模式，并指出它会破坏审计归因和形成 confused deputy。[MCP 2026-07-28 Authorization](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization)、[MCP Security Best Practices](https://modelcontextprotocol.io/docs/2026-07-28/tutorials/security/security_best_practices)

**E03 [实证]** 可核验的 Snowflake、Cube、Looker 都不是“只在 MCP 层重新做一套字段权限”，而是让 agent 查询继承既有用户、角色、行级/列级策略，同时在 MCP/agent 交付层另加 server/tool allowlist、OAuth 或审计；这是一种“上游数据权限 + 交付层能力治理”的混合模式。[Snowflake managed MCP](https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-agents-mcp)、[Cube Core Data APIs](https://docs.cube.dev/reference/core-data-apis)、[Looker managed MCP](https://docs.cloud.google.com/looker/docs/mcp)

**E04 [实证]** 厂商没有形成“用户级数据一律不得进入 LLM”的统一做法：公开产品同时存在云 API 的不训练/有限留存和区域选项、BYOC/单租户、仓内推理、行列策略与掩码等多种控制形态；“数据是否可见”和“数据是否离开原处理边界”被当作两个不同问题处理。[OpenAI API data controls](https://developers.openai.com/api/docs/guides/your-data#default-usage-policies-by-endpoint)、[Cube infrastructure options](https://docs.cube.dev/admin/deployment/infrastructure)、[Snowflake cross-region inference](https://docs.snowflake.com/en/user-guide/snowflake-cortex/cross-region-inference)、[Looker-connected data residency](https://docs.cloud.google.com/gemini/data-agents/conversational-analytics-api/data-residency)

**I01 [推测]** 对本仓库而言，“本地单用户 stdio”与“远程、多用户、任意 agent”应分开看：前者可以继续从环境取凭据，后者若仍共用 `.env.gravity.local` 就无法可靠回答“谁代表谁调用”，最小增量不是先造字段门禁，而是先建立调用方身份、代表用户、每用户上游授权、工具范围和审计链；是否实现完整 OAuth 取决于是否真的开放远程 HTTP 面。依据是 MCP 明确把 OAuth 流程设计给远程 HTTP、把 stdio 凭据留给环境，以及三家可核验平台的身份继承模式。[MCP authorization tutorial](https://modelcontextprotocol.io/docs/tutorials/security/authorization)、[Snowflake managed MCP](https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-agents-mcp)、[Looker managed MCP](https://docs.cloud.google.com/looker/docs/mcp)

## 调研方法、范围与证据口径

**E05 [实证]** 本次实际使用了：内置网页搜索与正文打开、PowerShell `Invoke-WebRequest`、`curl.exe` 失败回退、对下载 HTML 的本地 `rg` 检索，以及对仓库文档和源码的只读检查。关键 HTML/PDF 已保存到 `tmp/codex/r5-security/sources/`；MCP 官方、Snowflake、Cube、Looker、Invariant、OWASP、GitHub、USENIX 等 30 份页面或论文成功落盘。NSA 的公开 PDF 可由网页阅读器读取，但 `Invoke-WebRequest` 和 `curl.exe` 均返回 HTTP 403，未伪装为已归档；ThinkingAI 页面在网页阅读器超时，但直接下载成功。未登录任何网站，未访问付费内容，未安装依赖。

**E06 [实证]** 报告中的计数单位是“带唯一 ID 的证据条目”，不是句子数；一条可以包含同一来源链支撑的一组紧密事实。`[实证]` 用于官方规范、官方技术文档、源码/API schema、CVE/GHSA、论文或可复现 PoC；`[厂商宣称]` 用于营销页、信任中心或无独立验证的比例；`[推测]` 只用于跨来源类比、样本归纳和对本仓库的条件性判断。

**E07 [实证]** 仓库当前基线是：上游授权作为产品访问边界，SDK 不再另做字段级访问控制；同时继续要求凭据不入库、生产响应值不进入 evidence/文档/测试/提交、未登记字段按 contract drift fail closed。[投影边界总裁决](../roadmap.md#投影边界总裁决全面放开2026-08-15) 当前 `run` 把脱敏 receipt 写入私有 `state_root/receipts/`，不保存输入值或结果行；代码审计字段包括 `gravity_operation_id`、状态、耗时、页数和行数。[agent workflow](../agent-workflow.md#L185)、[client.py](../../src/gravity_sdk/client.py#L1117)

## A. MCP 的已知安全问题

### 1. 工具结果中的 prompt injection

**E08 [实证]** Invariant 的 GitHub MCP 演示把恶意指令写进公开 issue；agent 为处理 issue 调取该内容后，又读取私有仓库，并把私有信息写到公开 pull request。研究者明确把问题归因于 agent 系统把不可信公开内容与高权限工具放在同一信任域，而不是 GitHub MCP server 的普通代码漏洞。[研究说明与演示](https://invariantlabs.ai/blog/mcp-github-vulnerability)、[可复现实验仓库](https://github.com/invariantlabs-ai/mcp-injection-experiments)

**E09 [实证]** 另一个同类链条已进入安全公告：`mcp-atlassian` 的 CVE-2026-27826 允许攻击者控制 Jira base URL，引导 server 请求攻击者端点，再把伪造响应作为 Jira 数据送入 tool result；公告明确指出这形成 data-layer prompt injection，且不需要篡改工具参数。[GHSA-7r34-79r5-rcc9](https://github.com/advisories/GHSA-7r34-79r5-rcc9)

**I02 [推测]** 暂未找到“昵称/备注/事件属性”这三个字段名的公开 MCP 攻击报告；但 GitHub issue、聊天消息和伪造 Jira 返回值与它们具有同样的控制关系：字段值由业务用户或外部系统写入，随后作为 tool result 进入模型上下文。因此“这些字段会成为注入面”是有直接同类案例支撑的类比，不是已经对本仓库完成的 exploit 证明。依据链是 E08、E09 以及 OWASP 将每个 tool response 视为不可信输入的要求。[OWASP MCP Security Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/MCP_Security_Cheat_Sheet.html#12-prompt-injection-via-tool-return-values)

### 2. Tool poisoning、rug pull 与 tool shadowing

**E10 [实证]** Invariant 展示了三种可复现行为：在 `add(a,b,sidenote)` 的描述中隐藏读取 `~/.cursor/mcp.json` 或 SSH key 并偷偷塞入参数的指令；用户首次批准后 server 改写描述的 rug pull；恶意 server 通过描述影响可信 server 的 `send_email` 收件人的 tool shadowing。WhatsApp 演示进一步显示，server 可以先以无害描述通过审批，稍后改变语义并外传聊天记录。[tool poisoning 研究](https://invariantlabs.ai/blog/mcp-security-notification-tool-poisoning-attacks)、[WhatsApp rug pull 研究](https://invariantlabs.ai/blog/whatsapp-mcp-exploited)

**E11 [实证]** MCP 的 `ToolAnnotations` 当前真实结构只有五个可选提示字段；这些 annotation 对不可信 server 只是 hints，不是授权或强制策略，默认值也故意保守：

```ts
interface ToolAnnotations {
  title?: string;
  readOnlyHint?: boolean;    // default false
  destructiveHint?: boolean; // default true
  idempotentHint?: boolean;  // default false
  openWorldHint?: boolean;   // default true
}
```

官方同时说明 annotation 不能抵抗 prompt injection；`unsafeOutputHint`、`secretHint`、`trustedHint` 等仍只是提案。因此不能把 `readOnlyHint` 当作 server-side enforcement，也不能把缺少 `openWorldHint` 当作“输出可信”。[MCP Tool Annotations](https://blog.modelcontextprotocol.io/posts/2026-03-16-tool-annotations/)

### 3. Confused deputy、token passthrough 与过度权限

**E12 [实证]** MCP 官方 confused-deputy 示例是：MCP proxy 使用固定的上游 OAuth client ID，攻击者动态注册恶意 MCP client，并借浏览器中已有的授权 cookie 诱导用户批准；如果 proxy 没有维护“每用户批准过哪些 client_id”的记录和逐客户端 consent，就可能替错误的 client 取得授权。官方缓解包括：每用户 consent 记录、展示 client 名称/请求 scopes/redirect URI、CSRF 保护和精确 redirect URI 校验。[MCP Security Best Practices — Confused Deputy](https://modelcontextprotocol.io/docs/2026-07-28/tutorials/security/security_best_practices#confused-deputy-problem)

**E13 [实证]** 对 token passthrough，2026-07-28 授权规范要求客户端在授权请求和 token 请求中都带 RFC 8707 `resource`；server 必须验证 token 的目标 audience，只接受专门签给自己的 token。server 调上游 API 时必须使用上游授权服务器签发的独立 token，不能转发从 MCP client 收到的 token。官方列出的风险包括绕过限流/校验、无法区分 MCP client、下游日志身份错误、被盗 token 借 server 外传数据和跨服务信任破坏。[MCP Authorization](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization)、[Token Passthrough](https://modelcontextprotocol.io/docs/2026-07-28/tutorials/security/security_best_practices#token-passthrough)

**E14 [实证]** “一个 tool 能做得比调用方以为的多”在真实产品配置中不是抽象问题。Snowflake 的 `SYSTEM_EXECUTE_SQL` 可以绕过 Cortex Agent 的 semantic views、verified queries 和 orchestration，所以官方要求若确需直连 SQL，应放在独立 MCP server 并绑定专用最小权限角色；其 SQL tool 默认 `read_only: true`，还能设 `query_timeout` 和 warehouse。[Snowflake managed MCP](https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-agents-mcp#configure-tool-types)

### 4. 官方安全要点与扫描工具

**E15 [实证]** MCP 官方 security best practices 的可操作要点包括：禁止 token passthrough；做 token audience 校验；OAuth metadata 获取要防 SSRF（HTTPS、私网/保留地址阻断、DNS 与 redirect 重验）；服务端状态 handle 必须绑定由已验证 token 得到的用户；本地 server 要显式 consent、沙箱和最小文件/网络权限，直接本地连接优先 stdio；OAuth URL 不得交给 shell 打开；scope 应最小化；远程 HTTP 要认证。该文档处理的是协议与实现边界，并没有宣称模型层可以完全消除间接 prompt injection。[MCP Security Best Practices](https://modelcontextprotocol.io/docs/2026-07-28/tutorials/security/security_best_practices)

**E16 [实证]** NSA 2026 年《MCP Security》把 sleeper/rug-pull、tool-output prompt injection、跨工具/多 agent 级联外传列为现实威胁，并建议使用受支持项目、审阅代码、划分 trust zone、让 tool/model 与数据分类对齐、校验 schema/范围/大小、限制歧义参数转发和沙箱化。公开 PDF 可在线阅读，但本次命令行归档连续收到 403；这里引用原始 URL，不引用二手摘要。[NSA Cybersecurity Information Sheet: MCP Security](https://media.defense.gov/2026/Jun/02/2003943289/-1/-1/0/CSI_MCP_SECURITY.PDF)

**E17 [实证]** 已公开的 MCP 实现漏洞至少包括：MCP Inspector `<0.14.1` 的未认证 proxy RCE（CVE-2025-49596）；`mcp-remote` `<0.1.16` 通过恶意 `authorization_endpoint` 触发命令注入（CVE-2025-6514）；git MCP server `<=2.1.4` 可由恶意 commit log 间接诱导命令注入（CVE-2025-53107）；以及 E09 的 Atlassian SSRF/工具结果注入（CVE-2026-27826）。这些 CVE 覆盖本地进程启动、OAuth URL、业务内容和上游 URL 四个不同边界。[NVD CVE-2025-49596](https://nvd.nist.gov/vuln/detail/CVE-2025-49596)、[GHSA-6xpm-ggf7-wc3p](https://github.com/advisories/GHSA-6xpm-ggf7-wc3p)、[GHSA-3q26-f695-pp76](https://github.com/advisories/GHSA-3q26-f695-pp76)、[GHSA-7r34-79r5-rcc9](https://github.com/advisories/GHSA-7r34-79r5-rcc9)

**E18 [实证]** 可用的扫描/清单包括：`mcp-scan` 能发现本机 MCP 配置、读取 tool descriptions、做静态扫描，并提供 runtime proxy；默认远程扫描会发送 tool 名和描述，`--local-only` 才不发送，而文档称 tool call 内容和结果不被保存。OWASP MCP Cheat Sheet 则给出逐项审计清单：最小权限、描述/schema pinning、沙箱、敏感动作人工确认、输入输出校验、远程认证、跨 server 隔离、供应链检查、集中日志与 PII/secret 脱敏。[mcp-scan 文档](https://invariantlabs-ai.github.io/docs/mcp-scan/scanning/)、[OWASP MCP Security Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/MCP_Security_Cheat_Sheet.html)

## B. 数据平台在 agent 场景下的访问控制

### 1. Snowflake managed MCP server

**E19 [实证]** Snowflake managed MCP server 默认使用 Snowflake OAuth，也可绑定 External OAuth/企业 IdP；`USAGE` on MCP SERVER 只允许连接与发现工具，调用 Cortex Search、Semantic View、Agent、UDF/Stored Procedure 还要各自底层权限。Snowflake 建议 OAuth 而不是硬编码 token，PAT 必须绑定最小权限角色，并建议 MCP session 禁用 secondary roles、限制 allowed roles。[Snowflake managed MCP access control](https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-agents-mcp#access-control)

**E20 [实证]** Snowflake 的权限路径是“登录用户 → 默认角色 → MCP server/tool privilege → 底层对象 privilege”；Cortex Agent 根据查询用户的 default role 决定 session 权限。对于多租户调用，`agent:run` 可以传不可变 session attribute，再由 row access policy 使用 `SYS_CONTEXT('SNOWFLAKE$SESSION_ATTRIBUTES', 'region')` 过滤；文档明确说 Snowflake 提供机制，客户负责正确配置租户边界。[Cortex Agent access control](https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-agents-setup)、[Multi-tenancy for Cortex Agents](https://docs.snowflake.com/de/user-guide/snowflake-cortex/cortex-agents-multi-tenancy)

**E21 [实证]** Snowflake 的 SQL tool 配置把能力边界写在真实 schema 中：

```yaml
tools:
  - title: "SQL Execution Tool"
    name: "sql_exec_tool"
    type: "SYSTEM_EXECUTE_SQL"
    config:
      read_only: true
      query_timeout: 600
      warehouse: "<warehouse_name>"
```

`read_only` 默认即为 `true`；这与“用户有 SELECT 权限”是两道不同控制：前者限制 tool 语义，后者决定具体对象/行/列能否读取。[Snowflake tool configuration](https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-agents-mcp#configure-tool-types)

### 2. Cube

**E22 [实证]** Cube 把 MCP 列为 Core Data API 的 AI assistant 接口，并声明所有 Core Data APIs 共用 authentication、security context 和 semantic-layer access policies；个人 token 以该用户身份认证，用户的 groups、user attributes 和 data policies 都应用到查询。因此 MCP 不获得绕过语义层策略的单独通道。[Cube Core Data APIs](https://docs.cube.dev/reference/core-data-apis)

**E23 [实证]** Cube 的 row-level policy 是显式数据模型配置，默认所有行公开；可按 group 和 `userAttributes` 过滤：

```yaml
cubes:
  - name: orders
    access_policy:
      - group: manager
        row_level:
          filters:
            - member: country
              operator: equals
              values: ["{ userAttributes.country }"]
```

该策略作用于 APIs & integrations，而非只作用于网页 UI。[Cube row-level security](https://docs.cube.dev/docs/data-modeling/access-control/row-level-security)

**E24 [实证]** Cube 也提供与列级安全相似的 member-level policy，用 `member_level.includes` / `excludes` 控制 cubes、views、dimensions、measures；一旦给特定 group 配策略，其他 group 默认拒绝，还可对受限 member 返回 masked value。与此同时，未配置策略时所有 cube/view/member 默认公开。[Cube member-level security](https://docs.cube.dev/docs/data-modeling/access-control/member-level-security)

**V01 [厂商宣称]** Cube 的产品博客称 MCP Connector 由组织管理员统一管理 connector、tool 和 availability，默认没有工具开启；工具需要授权时在 chat 内请求 OAuth/credential，并继续使用现有访问控制。该页面给出了具体产品行为，但不是独立测试或协议 schema，因此只计厂商宣称。[Cube MCP Connectors](https://cube.dev/blog/introducing-mcp-connectors)

### 3. Looker 与 ThoughtSpot

**E25 [实证]** Looker managed MCP 当前为 preview：管理员先把 AI agent 注册成 OAuth client，用户用标准 Looker 登录，client 继承该用户的 roles 和 content access；所有 MCP tools 默认关闭，管理员必须逐个启用。其限制也写得很清楚：preview 尚无 fine-grained OAuth scopes，访问控制依赖全局 tool allowlist 加用户基础权限，tool allowlist 改动不会自动推送给已连接客户端，需重连刷新 manifest。[Looker managed MCP](https://docs.cloud.google.com/looker/docs/mcp)

**E26 [实证]** Looker 既有模型可以把 user attributes 用于 access filters，也能用 `required_access_grants` 控制 model/explore/join/view/field 访问；API credential 绑定 Looker user，调用以该用户权限执行。Conversational Analytics 的 user access token 会继续遵守 LookML 的 `access_filters`、`access_grants` 和 `sql_always_where`，而 service-account API key 会让所有终端用户共享同一访问级别，是官方文档自己揭示的 confused-deputy 风险形态。[Looker access control](https://docs.cloud.google.com/looker/docs/access-control-and-permission-management)、[Conversational Analytics authentication](https://docs.cloud.google.com/gemini/data-agents/conversational-analytics-api/authentication)

**V02 [厂商宣称]** ThoughtSpot 的公开 MCP 页面称其 server 使用 OAuth 2.1，并自动继承 ThoughtSpot 中已有的 permissions、access controls 和 security protocols；公开 executive guide 又称继承云数据权限、RBAC 与 semantic definitions。没有找到无需登录即可核验的 MCP tool schema、tool allowlist 配置或 MCP 审计字段，因此只能把“权限继承”记为厂商宣称。[ThoughtSpot Agentic MCP Server](https://www.thoughtspot.com/blog/introducing-agentic-mcp-server)、[ThoughtSpot MCP executive guide](https://media.thoughtspot.com/pdf/ThoughtSpot-Executive-Guide-to-MCP-ebook.pdf)

### 4. 权限究竟放在哪一层

**I03 [推测]** 按公开材料逐家计数：Snowflake、Cube、Looker 三家有技术文档可核验为“混合模式”，即数据行列/对象权限沿用上游身份和策略，同时 MCP/agent 层再控制 server/tool、OAuth client 或审计；ThoughtSpot 的材料也声称相同模式，但只能算厂商宣称。样本中 **0/3 家可核验产品**采用“任何拿到一个共享上游 token 的 MCP client 都完全透传、MCP 层不识别用户也不限制 tool”的纯透传模式；若把 ThoughtSpot 宣称计入，则是 4/4 混合模式。这个小样本不能外推为全行业比例。[Snowflake](https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-agents-mcp)、[Cube](https://docs.cube.dev/reference/core-data-apis)、[Looker](https://docs.cloud.google.com/looker/docs/mcp)、[ThoughtSpot](https://www.thoughtspot.com/blog/introducing-agentic-mcp-server)

**I04 [推测]** 这三家与本仓库“SDK 不自建字段门禁”的决定有一个相似点和一个关键差别：相似点是 agent 交付面不再复制一套字段 ACL，而复用已有数据平台的行列/对象策略；差别是它们没有把“上游授权”理解成“交付层什么都不做”，而是额外绑定用户、限制 tool、保留审计，并对直连 SQL 等绕过语义层的能力单独隔离。依据是 E19–E26；这是架构对照，不是对本仓库的裁决。

## C. PII、驻留与合规

### 1. 厂商对“明细交给 LLM”的实际做法

**E27 [实证]** OpenAI API 文档称 API 数据默认不用于训练，默认 abuse-monitoring logs 最长保留 30 天；合格客户可申请 Modified Abuse Monitoring 或 Zero Data Retention。数据驻留按 project 配置，文档明确区分 storage 与 processing，并明确第三方服务导致的跨区传输/存储不属于其 residency 承诺。也就是说“云模型不训练”不等于“不处理、不短期留存、也不等于数据不流向第三方 tool”。[OpenAI API data controls](https://developers.openai.com/api/docs/guides/your-data#default-usage-policies-by-endpoint)

**E28 [实证]** Snowflake 默认把 cross-region inference 设为 `DISABLED`，可只允许指定 region；启用跨区时，输入、服务生成 prompt 和输出会到处理 region，但文档称不在跨区推理期间存储或缓存，并说明同云网络/跨云 mTLS 的传输路径。这个控制解决的是推理位置，不是字段可见性。[Snowflake cross-region inference](https://docs.snowflake.com/en/user-guide/snowflake-cortex/cross-region-inference)

**E29 [实证]** Cube 提供多租户、单租户、客户对象存储和 BYOC 四种基础设施；BYOC 把所有与 private data 交互的组件部署在客户 AWS/Azure/GCP 账号中。Google Conversational Analytics 对 Looker 数据源的 regional endpoint 只承诺 data at rest 驻留，而同页对 BigQuery 数据源还提供 jurisdictional processing 承诺，说明“选了区域”仍要逐产品核对 in-use/in-transit 范围。[Cube infrastructure](https://docs.cube.dev/admin/deployment/infrastructure)、[Google Conversational Analytics data residency](https://docs.cloud.google.com/gemini/data-agents/conversational-analytics-api/data-residency)

**V03 [厂商宣称]** ThoughtSpot 的 Trust 页面称客户数据不用于训练模型，第三方 LLM 合同采用 zero retention，且沿用 RBAC/access controls；没有找到独立验证其每个 MCP tool 的数据路径，因此这里只记录厂商口径。[ThoughtSpot AI principles](https://www.thoughtspot.com/trust/ai-principles)、[ThoughtSpot enterprise-grade AI](https://www.thoughtspot.com/trust/enterprise-grade-ai)

**V04 [厂商宣称]** ThinkingAI 当前私有化页面直接展示“80% 客户选择私有化”“100% 数据主权”“0 数据外泄”，并称数据、模型、推理全链路在客户基础设施；页面没有给样本数、统计期间、客户定义、问卷或第三方审计，所以比例和结果不能升级为实证。[ThinkingAI 私有化部署](https://www.thinkingai.cn/product/self-hosted/index.html)

**V05 [厂商宣称]** 2021 年的 36Kr 项目页已经写过“300 多家客户、80% 以上私有化部署”，早于本轮 MCP/生成式 agent 产品语境；这至少证明 80% 口径并非因 2025–2026 年 agent 数据进入云端 LLM 才首次出现，但该历史数字同样是企业自述。[36Kr 项目页](https://pitchhub.36kr.com/project/1678464992408580)

**I05 [推测]** 目前没有来源证明“数数科技 80% 客户选私有化”的主要驱动就是 LLM 数据出境。更谨慎的解释是：历史比例早在生成式 agent 之前就存在，当前页面把数据主权、模型和推理放在一起重新包装；数据安全、部署控制、合规或采购偏好都可能是驱动，无法从公开材料分解权重。依据是 V04、V05。

### 2. 法规和监管材料能说到哪里

**E30 [实证]** 中国《生成式人工智能服务管理暂行办法》适用于向境内公众提供生成内容的服务，并明确企业/机构内部研发应用、未向公众提供服务的不适用；对适用的提供者，它要求个人信息具有同意或其他合法依据，并要求保护使用者输入与使用记录、不得收集非必要个人信息、不得非法留存可识别输入/记录或非法提供给他人。该文本没有出现 MCP，也没有规定“分析结果中的用户级明细一律不得进入模型”。[国家网信办《暂行办法》](https://www.cac.gov.cn/2023-07/13/c_1690898327029107.htm)

**E31 [实证]** 国家网信办 2025 年政务大模型部署指引要求加强数据安全、保密和个人信息保护，落实“涉密不上网、上网不涉密”，防止秘密和敏感信息输入非涉密大模型，并防范敏感数据汇聚关联风险。这是明确的场景化禁入做法，但对象是政务和涉密/敏感信息，不能直接等同于一般商业分析字段。[政务领域人工智能大模型部署应用指引](https://www.cac.gov.cn/2025-10/10/c_1761819469929310.htm)

**E32 [实证]** EDPB Opinion 28/2024 讨论 AI model 开发和部署中的个人数据：是否匿名要逐案判断；以 legitimate interest 为依据要做目的、必要性和权利平衡三步评估；非法处理的数据可能影响后续部署，除非模型已适当匿名化。它不是 MCP 专项意见，也没有给“允许/禁止把明细行送入 agent”的字段清单。[EDPB Opinion 28/2024](https://www.edpb.europa.eu/news/edpb-opinion-on-ai-models-gdpr-principles-support-responsible-ai_en)

**E33 [实证]** California Privacy Protection Agency 已把 risk assessment、cybersecurity audit 和 automated decisionmaking technology 纳入 CCPA 规则体系；California Attorney General 的 CCPA 页面列出访问、删除、更正、opt-out 和限制 sensitive personal information 使用/披露等权利。两份公开材料都没有 MCP 专用条款，也没有把一次 agent 分析查询规定成固定的技术实现。[CPPA CCPA updates](https://cppa.ca.gov/regulations/ccpa_updates.html)、[California AG CCPA](https://oag.ca.gov/privacy/ccpa)

**I06 [推测]** 截至本次检索，没有找到 GDPR/CCPA/个保法监管机构针对“分析 MCP 将已授权用户级结果交给云端 LLM”的专门裁决或统一技术清单；能找到的是现有个人信息处理原则、AI model 意见、公众 GenAI 规则和具体行业/政务禁入指引。因此合规部分只能陈述这些相邻规则，不能从中推导一个跨法域统一答案。检索依据见 E30–E33；这不是法律建议。

### 3. 字段级开关的产品形态

**E34 [实证]** 有厂商提供由客户决定 agent 能看哪些字段的开关，但通常复用语义层/数据平台而不是在 MCP protocol 里新增字段。Cube 用 `member_level.includes/excludes` 和 masking；Looker 用 field 上的 `required_access_grants`；Snowflake 用 column masking policy、row access policy，并在 `ACCESS_HISTORY.policies_referenced` 中记录命中的 policy 和 column。三种形态分别是模型成员 allow/deny、字段 access grant、数据库动态掩码/行策略。[Cube member-level security](https://docs.cube.dev/docs/data-modeling/access-control/member-level-security)、[Looker access control](https://docs.cloud.google.com/looker/docs/access-control-and-permission-management)、[Snowflake ACCESS_HISTORY](https://docs.snowflake.com/en/sql-reference/account-usage/access_history)

**I07 [推测]** 四家样本反映的是做法分歧而非价值判断：Snowflake/Cube/Looker 允许 agent 在既有权限内取得明细，并提供行列/工具控制；ThoughtSpot 宣称沿用权限；同时又提供仓内推理、BYOC、区域/留存控制，允许客户改变模型处理边界。没有证据显示样本厂商会仅因为字段是昵称、设备 ID 或用户 ID 就在 MCP 层统一拒绝；是否拒绝通常交给客户的数据策略。依据是 E19–E34 和 V02–V03，样本仅四家。

## D. 审计与可追溯

**E35 [实证]** OWASP MCP checklist 要求记录所有 tool invocation、完整参数、user context 和 timestamp，送入 SIEM 并对新工具、admin 查询、异常频率告警；同一清单同时要求从日志中 redact secrets 和 PII。因此“全参数”不是“原样永久落盘”，实现时要同时满足可归因与内容最小化。[OWASP Monitoring, Logging & Auditing](https://cheatsheetseries.owasp.org/cheatsheets/MCP_Security_Cheat_Sheet.html#10-monitoring-logging--auditing)

**E36 [实证]** Snowflake 提供了接近“哪个用户、查了什么、拿走多少”的组合证据：`QUERY_HISTORY` 含 `query_id`、`query_text`、`authn_event_id`、`user_name`、`role_name`、`query_tag`、状态、耗时、`bytes_written_to_result`、`rows_written_to_result`；`ACCESS_HISTORY` 用同一 `query_id` 记录直接/底层 table、view、column 和命中的 masking/row policies。Cortex Agent observability 还记录 conversation、planning、tool execution、SQL、span inputs/outputs，且以 `READ UNREDACTED AI OBSERVABILITY EVENTS TABLE` 单独控制谁能看未脱敏内容。[QUERY_HISTORY schema](https://docs.snowflake.com/en/sql-reference/account-usage/query_history)、[ACCESS_HISTORY schema](https://docs.snowflake.com/en/sql-reference/account-usage/access_history)、[Cortex Agent monitoring](https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-agents-monitor)

**E37 [实证]** Snowflake 的 `query_tag` 是可由 session parameter 设置、随后进入 `QUERY_HISTORY` 的通用字段；但没有找到 managed MCP 自动把 MCP client、agent ID 或 represented user 写入 `query_tag` 的官方说明。能核验的是查询本身已有 `user_name`/role/authn event，Agent usage/observability 另有 request、agent 和 trace 维度；要把两者强关联仍需产品文档或实测证据。[QUERY_HISTORY](https://docs.snowflake.com/en/sql-reference/account-usage/query_history)、[Cortex Agent monitoring](https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-agents-monitor)

**E38 [实证]** Looker 明确说 agent 的每个动作都写入 System Activity 和 Cloud Audit Logs；History 与 Event Attribute Explores 可回答 MCP 发起了哪些 API、一个 MCP request 关联哪些 events、管理员改了哪些 tool settings、MCP 用户跑了哪些 query。其文档也提醒 System Activity 只是审计补充，不应替代组织的合规日志策略。[Looker managed MCP audit](https://docs.cloud.google.com/looker/docs/mcp#audit-logging)、[System Activity](https://docs.cloud.google.com/looker/docs/system-activity-pages)

**I08 [推测]** 结合 OWASP、Snowflake、Looker，面向本仓库的最小审计 envelope 可分成四组，而不必保存结果值：身份（MCP client/agent、认证 subject、represented user、上游账号/role）、意图与能力（tool 名、schema/version hash、只读/开放网络属性、参数名与敏感值摘要或 hash）、执行（request/operation/query ID、时间、状态、耗时、页数、行数/返回字节、调用次数）、数据边界（访问的对象/字段、命中的策略、输出目的地/是否经外部 tool）。这是从公开字段归纳出的建议 schema，不是 MCP 标准规定的统一 schema。依据是 E35–E38。

**E39 [实证]** 本仓库当前“每个生产 HTTP 请求完成即落盘脱敏 receipt”的外部对应物不是一模一样的标准名称，而是 query/request ID、query history、access history、AI trace 和 Cloud Audit Logs：它们共同提供“完成后立即产生可关联事件”的能力。仓库已经记录 operation/status/duration/pages/rows 且不存输入值/结果行，但目前没有 agent identity、represented user、上游 role、tool manifest hash、输出目的地或字段访问清单。[本仓库 receipt](../agent-workflow.md#L185)、[本仓库审计字段](../../src/gravity_sdk/client.py#L1117)、[Snowflake QUERY_HISTORY](https://docs.snowflake.com/en/sql-reference/account-usage/query_history)、[Looker audit](https://docs.cloud.google.com/looker/docs/mcp#audit-logging)

**I09 [推测]** 因此仓库的 receipt 在“不把生产值写进证据”和逐请求计数方面比只保存聊天 transcript 更窄、更利于隐私；但在主体归因和跨层 lineage 上落后于 Snowflake/Looker 的组合日志。这个比较只涉及公开字段覆盖面，不代表三者的实际完整性、时效或防篡改能力相同。依据是 E36–E39。

## 版本控制中的业务数据：公开事故与成熟对应实践

**E40 [实证]** 2020 年研究报告《No Need to Hack When It’s Leaking》记录了公开 GitHub 仓库中直接出现患者 PDF、SQL dump 和其他 PHI，以及仓库凭据进一步暴露医疗系统的案例；报告估计九家机构合计涉及约 16–20 万条 PHI。它是安全研究者的协作调查，不是监管机构最终裁决，且本报告不复制任何患者内容。[原始研究报告 PDF](https://databreaches.net/wp-content/uploads/No-need-to-hack-when-its-leaking.pdf)

**E41 [实证]** USENIX Security 2023 对 109 名有版本控制经验的开发者调查，30.3% 表示经历过 code-secret 泄漏；14 次深入访谈全部涉及源码/配置硬编码，部分人泄露了包含敏感内部或客户数据的数据库密码。常见预防是把 secret 外置、用 `.gitignore`/阻断机制和监控；常见补救是吊销/轮换 secret、清理 VCS history 和做取证。[USENIX 论文与数据](https://www.usenix.org/conference/usenixsecurity23/presentation/krause)

**E42 [实证]** GitHub 官方的成熟处置顺序是：若泄露的是 secret，先 revoke/rotate；再视需要用 `git-filter-repo` 重写历史、清理中央引用，并协调 forks、PR 引用和所有 clones。官方强调只删当前文件或 force-push 不足以消除副本，旧 clone 还可能重新污染历史。[GitHub removing sensitive data](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository)

**E43 [实证]** GitHub push protection 会在 push 前阻断可识别 secret，支持 CLI、网页提交、上传、REST API 和 GitHub MCP server；但它只覆盖支持的 secret pattern，不是通用业务数据/PII DLP。GitHub MCP 对公开仓库默认扫描 AI 生成响应和写操作中的 secret，这说明“agent 写入版本库”已被产品化为单独的数据泄漏边界。[GitHub push protection](https://docs.github.com/en/code-security/concepts/secret-security/push-protection)、[GitHub MCP push protection](https://docs.github.com/en/code-security/concepts/secret-security/push-protection-and-the-github-mcp-server)

**I10 [推测]** 本仓库“生产响应值不写入 evidence、文档、测试或提交”对应的是比 secret scanning 更宽的 data minimization / synthetic-fixture 纪律：它同时防止普通 PII、业务明细和不可撤销的 Git 历史扩散。外部成熟实践可补充的是 pre-commit/CI 的 secret scanning、对自有标识符或数据形状做定制 DLP、泄露后先吊销凭据再历史清理；但不能把 GitHub push protection 当作现有纪律的替代品。依据是 E40–E43。

## 对本仓库的意义

### 1. “上游授权即边界、SDK 不自建字段门禁”在 agent 场景的外部对照

**I11 [推测]** 有人做了相近选择，但不是无条件的同一选择：Snowflake、Cube、Looker 都让 agent 复用上游 user/role/RLS/column policy，而不是在 MCP 层按“用户级、设备级、标识符”重新维护静态 denylist；它们的理由或产品目标是保证所有 API/agent 入口使用同一语义和权限模型、避免 agent 绕过既有治理。与此同时，它们在交付层保留 caller authentication、per-user identity、tool allowlist/RBAC、read-only 配置和 audit。故可供决策的外部事实是：**不复制字段 ACL 很常见；不识别调用主体、不约束工具和不留审计并不常见。** 依据是 E19–E26、I03–I04。

### 2. 如果增加 MCP 面，哪些是明显缺陷，哪些是条件性增强

**I12 [推测]** 下表是把 MCP 官方 MUST/SHOULD、OWASP checklist、真实攻击链和三家平台控制映射到本仓库后的风险分级；“必须”表示在对应部署条件下缺失会留下已知攻击路径，不是法规判定。

| 级别 | 措施 | 外部事实依据 |
|---|---|---|
| 远程 MCP 必须 | 每请求认证；把 MCP client、认证 subject、represented user 与上游账号/role 绑定；禁止共享高权限 `.env` 代表所有用户 | [MCP Authorization](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization)、E19、E25 |
| 远程 MCP 必须 | 入站 token audience 校验；MCP token 与上游 token 分离；禁止 token passthrough；HTTPS、PKCE、issuer/redirect/SSRF 校验 | [MCP Security Best Practices](https://modelcontextprotocol.io/docs/2026-07-28/tutorials/security/security_best_practices)、E12–E13、E17 |
| 任意 agent 必须 | 工具最小权限和默认关闭；分析面默认只读；直连 SQL/导出/开放网络 tool 分域；服务端校验参数、limit、timeout 和分页预算 | E14、E18、E21、E25 |
| 任意 agent 必须 | 把工具输出中的自由文本视为不可信；不能让读取业务字段自动触发外传/写入；跨 server 数据流、敏感写操作和外部发送需要硬隔离或模型外确认 | E08–E10、E15–E18 |
| 任意 agent 必须 | tool manifest/描述变更可见并重批或 pin/hash；记录 tool version/schema hash，避免 rug pull | E10–E11、E18 |
| 生产环境必须 | 逐调用审计并能关联用户、agent、tool、上游 request/query、对象/字段、状态、行数/字节和输出目的地；日志本身脱敏且受权限控制 | E35–E39 |
| 条件性 | SDK 自建字段 allow/deny 或 masking：上游已有可靠行列策略且用户身份不丢失时可不复制；跨租户、共享账号、第三方 agent 或无法证明上游策略时价值上升 | E20、E24、E26、E34、I04 |
| 条件性 | 本地 stdio 沙箱、文件/网络白名单：只在受控进程运行风险较低；安装第三方 local server 或 proxy 架构时应升级为基线 | E15、E17–E18 |
| 条件性 | 私有化、本地模型、BYOC、区域处理、ZDR/MAM：取决于数据分类、合同与驻留需求，不能替代身份和权限控制 | E27–E33 |
| 条件性 | `query_tag`、应用层消息签名、内容注入扫描：是有用的防御纵深；目前不是 MCP 对所有实现统一规定的最小互操作字段 | E18、E37 |

### 3. `.env.gravity.local` 到 agent 凭据模型的最小改动；OAuth 2.1 是否值得现在做

**E44 [实证]** MCP 授权规范把 authorization 定义为可选能力：HTTP transport 实现授权时应遵循该规范；stdio transport 不应套用这套远程 OAuth 流程，而应从环境取得凭据。官方 tutorial 也明确说 OAuth 面向远程 HTTP，本地 stdio 可使用环境或嵌入库提供的凭据。[MCP Authorization](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization)、[Authorization tutorial](https://modelcontextprotocol.io/docs/tutorials/security/authorization)

**I13 [推测]** 最小分阶段改动可以这样理解，而不是一次性承诺完整身份平台：

1. 仅交付本地、单用户 stdio 时，`.env.gravity.local` 仍可作为本机上游凭据来源；新增 MCP tool 默认只读、参数/输出 schema、tool manifest 版本、调用 receipt 中的 client/agent 标识和输出目的地即可。这里的 agent 标识是审计标签，不等于强认证。
2. 一旦开放远程 HTTP 或多用户，就不能继续让所有请求共享该文件中的账号；至少需要认证 MCP caller、建立 represented-user 绑定、为每个用户取得或选择最小权限上游凭据、加密存储/轮换、audience 校验、MCP/upstream token 分离和逐主体审计。
3. 若远程客户端需要代表交互式用户，按当前 MCP OAuth profile 实现 OAuth 2.1/PKCE/Protected Resource Metadata 是有互操作价值的；若只是本机 stdio，现在做完整 OAuth 收益有限。后台无用户的 service agent 可考虑 MCP OAuth Client Credentials extension，但它识别的是应用身份，不能凭空补出 represented human。

该分期判断依据 E02、E12–E15、E19、E25、E35–E44；它回答“什么时候值得做”，不替项目决定是否发布远程 MCP。

## 没能查到或不能证实的关键问题

**I14 [推测]** 下列内容在公开、无需登录的来源中没有拿到足够证据，不能用“业界通常”补齐：

- 没有找到以昵称、备注、事件属性为具体载体的已公开 MCP exploit；只有控制关系等价的 issue、聊天消息、Jira response 案例。
- 没有找到 Snowflake managed MCP 自动设置 `QUERY_TAG` 为 agent/client/user 的官方说明，也没有找到一个跨 MCP 与 SQL history 的公开强关联 schema。
- 没有找到 ThoughtSpot MCP 的公开 tool schema、tool allowlist、字段级开关或审计字段；现有材料主要是营销页和 executive guide。
- Cube 文档证明 MCP 共用 semantic-layer policies，但没有找到公开的“远程 MCP OAuth subject 如何精确映射到 `securityContext`”握手字段说明。
- ThinkingAI/数数科技的“80%”没有样本、期间、客户口径或第三方验证，也没有证据能把因果归到 LLM 数据出境。
- 没有找到 GDPR、CCPA 或中国个人信息监管机构针对“分析 MCP 把已授权明细送入云 LLM”的专门裁决、统一字段清单或统一审计 schema。
- 没有一家样本产品公开证明审计日志能精确记录“最终送入模型上下文并被模型读到的行数”；Snowflake 的 rows/bytes 是 SQL result 指标，不等同于最终上下文消费量。
- NSA PDF 命令行下载被站点 403 拒绝；网页阅读器能读取，但 `tmp` 中没有该份原文副本。

## 证据标签统计

**E45 [实证]** 按唯一编号条目计数（不把正文中对旧编号的引用重复计数）：`[实证]` 45 条，`[厂商宣称]` 5 条，`[推测]` 14 条。最可能出错的是 I03/I11 的跨厂商归纳：样本只有四家，ThoughtSpot 缺技术文档，而且“上游”在 Snowflake、语义层产品与本仓库中的层级并不完全相同；因此报告只把它作为外部做法对照，不当成行业统计结论。
