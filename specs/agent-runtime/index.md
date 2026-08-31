# Runtime Component Index

本页是 [index.json](index.json) 的人类投影，只展示当前组件 Owner、成熟度和限制。产品方向由唯一 [Canonical Architecture](../../docs/architecture.md) 拥有，机器字段由各组件列出的 Schema、Contract 与 Registry 拥有。本目录不再保存 Program 需求图或施工史。

成熟度含义：`stable` 是当前受支持且有明确机器 Owner/回归门禁的面；`bounded` 是受支持但范围限制属于合同的面；`experimental` 是尚未满足毕业证据、可整体移除的试点。成熟度不替代每次调用的 Trust、权限、完整性或 Data Quality 判断。

| Component | Maturity | Canonical machine owner | Current limit / reference |
| --- | --- | --- | --- |
| `execution-kernel` | `stable` | contracts, manifests, product/composite/Plan registries | [CLI](../../docs/reference/cli.md) |
| `journey-trust-quality` | `stable` | Journey, Capability Trust and Data Quality schemas | [Agent workflow](../../docs/agent-workflow.md) |
| `skill-runtime-hub` | `stable` | Skill, Hub source, lock and overlay schemas | [CLI](../../docs/reference/cli.md) |
| `external-method-library` | `stable` | vendor-neutral Skill library and isolated Source Registry | [CT01](CT01-external-method-inventory.md), [CT02](CT02-skill-library-validation.md), [CT03](CT03-skill-library-specification.md) |
| `semantic-registry` | `stable` | Semantic definition/binding/composition schemas | [SDK](../../docs/reference/sdk.md) |
| `operator-model` | `stable` | Operator and Model registries/schemas | [SDK](../../docs/reference/sdk.md) |
| `context-provider` | `stable` | Context, Provider, binding and RPC schemas | [Security](../../SECURITY.md) |
| `action-receipt` | `stable` | Action, authorization, experiment and Receipt schemas | [CLI](../../docs/reference/cli.md) |
| `artifact-delivery` | `stable` | Artifact Transfer and Analysis Artifact schemas | [CLI](../../docs/reference/cli.md) |
| `governor-variants` | `bounded` | Governor snapshot and Execution Variant contracts | process-local; characterized variants only; [limits](../../docs/maintainers/technical-debt.md) |
| `sql-explorer` | `bounded` | SQL Explorer request/result/promotion schemas | SQLite, exploratory/unknown, explicit promotion; [CLI](../../docs/reference/cli.md#sql) |
| `mcp-stdio` | `experimental` | MCP adapter schemas plus parity/removability fixtures | real Host, blind holdout and second adopter remain open; [MCP](../../docs/reference/mcp.md) |
| `external-control-plane` | `bounded` | update contracts and external activation client | Runtime never self-activates; [Architecture](../../docs/architecture.md) |
| `package-facade` | `stable` | public API/owner and module-disposition fixtures | [SDK](../../docs/reference/sdk.md) |

精确 machine path 与限制列表以 [index.json](index.json) 为准。字段变化先改真正 Registry/Schema 与门禁，再刷新本投影；不得把字段表复制回 Markdown。
