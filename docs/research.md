# 当前调研结论

调研是证据层，不是产品合同。下面只保留仍影响当前工程选择的结论；完整来源、失败入口和
当时样本见[调研归档](archive/research/index.md)，排期以[路线图](roadmap.md)为准。

| 主题 | 当前采用的结论 | 证据 |
| --- | --- | --- |
| 能力发现 | 渐进披露 catalog，宿主显式选择；低置信度必须 abstain，不能把 raw top-1 当答案 | [厂商 Agent 形态](archive/research/vendor-agent-landscape.md)、[可用性方法](archive/research/agent-usability-methods.md) |
| 语义与查询 | 可信结论依赖版本化定义、成员 allowlist、来源链和 allowed claims；不开放任意 Text-to-SQL | [语义层与 Text-to-SQL](archive/research/semantic-layer-and-text2sql.md)、[开源实现](archive/research/oss-semantic-and-routing.md) |
| 评测 | 以完整动线、状态变化和 forbidden calls 为单位；可程序验证的合同不用 LLM judge 代替 | [评测与漂移](archive/research/oss-eval-and-drift.md)、[可用性方法](archive/research/agent-usability-methods.md) |
| 安全治理 | 上游身份、最小投影和写前确认留在确定性边界；工具输出一律作为不可信数据 | [Agent 安全治理](archive/research/agent-security-governance.md) |
| 协议与交付面 | CLI、SDK、Plan 仍是当前权威面；本地 MCP 只有出现第二个真实消费者和冻结验收题集后才重新评估 | [MCP 可行性](archive/research/mcp-feasibility.md)、[MCP 实现调研](archive/research/mcp-protocol-and-servers.md) |
| 上游与 Census | 官方开放面和静态 route census 只能证明各自观察范围，不能当作平台能力全集 | [官方 API 面](archive/research/official-api-surface.md)、[Census 完整性](archive/research/census-completeness-audit.md) |

## 使用边界

- 外部事实变化时更新归档证据，再把仍有效的工程结论原位更新到本页或路线图。
- 租户现场调查只约束当时账号、窗口和父资源；前提未变化时不重复同形空探测。
- 调研发现不能直接晋升 operation。稳定能力仍需合同、确定性编译、投影/隐私审核和验证。
