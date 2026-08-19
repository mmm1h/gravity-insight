> 归档材料：保留历史决策与取证，不代表当前接口或状态；当前入口见 docs/index.md。

# 调研索引

本目录是**外部事实记录与一次性调查底稿**，不构成本仓库的行为承诺。
机器可执行的合同位于 `src/gravity_sdk/contracts`；当前能力口径见 [文档索引](../../index.md)。

## 排期

- [外部做法借鉴规划（P0 / P1 / P2 / P3）](borrow-roadmap.md) — 把下列调研变成可执行排期，
  含「明确不做」一档。
- [授权写面普查与分析能力排期](write-surface-census.md) — 在冻结 Web-entry Census 的 987 条 route 内
  复算未覆盖写面，按产品授权与“少一次回 Web”筛出真正值得建设的对象族。

## 架构评估

- [写治理架构承载力评估](architecture-load-bearing.md) — 能不能扛住自定义指标、维度表、
  事件属性治理、SQL 保存查询这四个新域；含 marker/owner 现状与窄重构方案。

## 上游官方口径

- [引力官方 API / SDK 面评估](official-api-surface.md) — 官方开放面有多大、鉴权模型差异、
  异步导出与回调这类数据回流能力，以及「切换 / 补充 / 维持」的裁决。

## 外部调研

2026-08-15 起对同类分析平台 Agent 形态、协议与方法学的调研。
每条结论标注了 `[实证]` / `[厂商宣称]` / `[推测]`。

- [MCP 协议与分析类 server 实现](mcp-protocol-and-servers.md)
- [MCP 第五交付面可行性裁决](mcp-feasibility.md)
- [厂商 Agent 形态横向调研](vendor-agent-landscape.md)
- [语义层与 text-to-SQL 工程现状](semantic-layer-and-text2sql.md)
- [GitHub 开源语义层与能力路由实现](oss-semantic-and-routing.md)
- [Agent 可用性度量方法](agent-usability-methods.md)
- [Agent 评测方法学与合同漂移检测](oss-eval-and-drift.md)
- [Agent 场景的数据访问安全与治理](agent-security-governance.md)

## 本租户调查

依据本租户前端 bundle、仓库 census 与受控在线验证得出，**是当时的事实快照，不是永久结论**。

- [引力原生 AI 事件分析对话摸底](gravity-native-ai.md)
- [Census 完整性与分母审计](census-completeness-audit.md) — 还原 2026-08-09 抓取源、静态闭包和
  SQL 工作台占位，量化模块/UNKNOWN method，并限定所有 987-route 推导的适用范围。
- [分群删除能力调查](segment-delete-capability.md)
- [维度表 wire 与分析价值探测](dimension-table-wire-probe.md) — 9 条写路由的请求形状；
  **属性绑定是单向门**（无法解除最后一条关联），因此未能证明分析价值。
