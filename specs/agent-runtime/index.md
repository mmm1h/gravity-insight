# Gravity Agent Runtime Requirement Index

本目录是 [Gravity Agent Runtime v9 总纲](directive.json) 的派生需求层。总纲是唯一产品与共享架构源；这里的文档只定义一个交付单元的合同、迁移、验收和回滚，不得反向改写总纲。

## Program Rules

- 每份需求通过 `directive.json` 绑定已批准总纲版本和 SHA-256。
- 功能需求必须经过 `specified → reviewed → ready` 才能施工；正文不能自行宣布 `ready`。
- 一份需求对应一个主 Issue、一个 `codex/<unit>` 分支/Worktree 和一个端到端交付单元。
- 领域 core 可并行；共享 spine 的最终接线由单一 integrator 串行完成。
- 已验收单元合入 `dev` 后状态为 `fixed_dev`。完整计划结束前不合入 `main`，也不使用 `released`。
- 实际状态、依赖和并行组以 [index.json](index.json) 为机器权威。

## Dependency Graph

```text
R00 → R01 → R02
       ├────→ R03 → R04 ─┐
       ├────→ R05 ───────┤
       ├────→ R06 ───────┤
       └────→ R07 → R08 ─┤→ R09 → R10
                          │       └→ R12 → R13
R02 ──────────────────────┼→ R11
                          ├→ R14
R02 + R05 ────────────────┼→ R15
R04 ──────────────────────┘→ R16 (conditional)

R00 → CT01
CT01 + R09 → CT02 → CT03
```

## Requirements

| ID | Title | Dependencies | Initial state | Parallelism |
| --- | --- | --- | --- | --- |
| [R00](R00-product-constitution.md) | Product constitution and directive governance | - | `fixed_dev` after this documentation round | Serial bootstrap |
| [R01](R01-reference-vertical-slice.md) | Reference vertical Journey slice | R00 | `specified` | Serial reference |
| [R02](R02-journey-trust-data-quality.md) | Journey, Trust and Data Quality platform | R01 | `specified` | Shared-spine integration |
| [R03](R03-built-in-skill-package.md) | Built-in Skill package and render model | R01 | `specified` | Foundation A |
| [R04](R04-team-skill-hub-stage-a.md) | Team Skill Hub Stage A | R03 | `specified` | Foundation B |
| [R05](R05-business-semantic-registry.md) | Business Semantic Registry | R01 | `specified` | Foundation A |
| [R06](R06-operator-model-contracts.md) | Analysis Operator and Model contracts | R01 | `specified` | Foundation A |
| [R07](R07-context-pack-repo-provider.md) | Context Pack and Repo Provider | R01 | `specified` | Foundation A |
| [R08](R08-external-provider-rpc-guard.md) | External Provider and RPC Guard | R07 | `specified` | Foundation B |
| [R09](R09-skill-runtime-project-overlay.md) | Skill Runtime and Project Overlay | R02, R04-R08 | `specified` | Serial integration |
| [R10](R10-mcp-thin-surface.md) | MCP thin Resources/Tools surface | R09 + trigger | `specified` | Optional surface |
| [R11](R11-pap-pilot.md) | Prepared Analysis Plan pilot | R02 | `specified` | Independent pilot |
| [R12](R12-action-experiment-receipt.md) | Action, Experiment and Receipt governance | R09 | `specified` | Governed action |
| [R13](R13-artifact-analysis-delivery.md) | Artifact and analysis delivery | R02, R12 | `specified` | Delivery plane |
| [R14](R14-adaptive-governor-variants.md) | Adaptive Governor and Execution Variants | R02 | `specified` | Runtime infrastructure |
| [R15](R15-isolated-sql-explorer.md) | Isolated SQL Explorer | R02, R05 | `specified` | Isolated product |
| [R16](R16-control-plane-stage-b.md) | Control Plane Stage B | R04 + trigger | `specified` | Conditional control plane |
| [CT01](CT01-thinkingai-inventory.md) | ThinkingAI source inventory | R00 | `specified` | Parallel content |
| [CT02](CT02-thinkingai-representative-skills.md) | Representative ThinkingAI Skills | CT01, R09 | `specified` | Content validation |
| [CT03](CT03-thinkingai-full-specification.md) | Full independent Skill specifications | CT02 | `specified` | Content expansion |

## Integration Ownership

The following files are shared-spine integration points and cannot be wired concurrently across worktrees:

```text
src/gravity_sdk/plan_adapters.py
src/gravity_sdk/agent_capabilities.py
src/gravity_sdk/agent_composite.py
src/gravity_sdk/agent_handoff.py
src/gravity_sdk/cli.py
src/gravity_sdk/__main__.py
```

Requirement branches implement domain cores and focused tests first. A named integrator performs final shared-spine wiring, generated artifact refresh and cross-requirement validation serially on `dev`.

## Readiness

`specified` means scope and dependency boundaries exist. Before changing a requirement to `ready`, the plan owner must fill its unresolved decisions, bind a current baseline SHA and Issue, confirm write scope and worktree, and approve its exact acceptance commands.
