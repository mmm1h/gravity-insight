# Gravity Agent Runtime Requirement Index

本目录是 [Gravity Agent Runtime v9.1 canonical architecture](architecture-source.md) 的派生需求层。[directive.json](directive.json) 将批准版本与仓库内完整正文的 SHA-256 绑定。总纲是唯一产品与共享架构源；这里的文档只定义有界交付单元，不得反向改写总纲。

## Program Rules

- 功能需求必须经过 `specified → reviewed → ready` 才能施工；正文不能自行宣布 `ready`。
- 默认一份叶子需求对应一个主 Issue、一个 `codex/<unit>` 分支/Worktree 和一个端到端交付单元。
- R12、R14 是总纲批准的 `staged_epic`；每个强制子阶段仍对应独立 Issue、分支、提交、验收和回滚，父项只能在全部子阶段完成后到达 `fixed_dev`。
- 领域 core 可并行；共享 spine 的最终接线由单一 integrator 串行完成。
- 已验收单元合入 `dev` 后状态为 `fixed_dev`。完整计划结束前不合入 `main`，也不使用 `released`。
- 外部 Hub 或 Provider 缺失只阻塞显式依赖它们的 Skill；不得阻塞 R09A Built-in Core Skill Runtime。
- 实际状态、依赖、里程碑和触发条件以 [index.json](index.json) 为机器权威。

## Dependency Graph

```text
R00 → R01 → R02 ───────────────→ R11
       ├────→ R03 ─┐             ├→ R13A
       ├────→ R05 ─┼─────────────┼→ R14
       ├────→ R06 ─┤             └→ R15 (also R05)
       └────→ R07 → R08

R03 + R06 → R04
R02 + R03 + R05 + R06 + R07 → R09A Core Skill Runtime
R04 + R09A → R09B Team Hub Binding
R08 + R09A → R09C External Context Binding

R09A → R10 (conditional)
R09A → R12-A → R12-B → R12-C
R09A → R13B
R12-A + R13B → R13C

R02 → R14-A → R14-B
R02 → R14-C
R14-B + R14-C → R14-D

R04 → R16 (conditional)
R00 → CT01
CT01 + R09B → CT02 → CT03
```

## Requirements

| ID | Title | Dependencies | State | Delivery |
| --- | --- | --- | --- | --- |
| [R00](R00-product-constitution.md) | Product constitution and directive governance | - | `fixed_dev` | Leaf |
| [R01](R01-reference-vertical-slice.md) | Reference vertical Journey slice | R00 | `fixed_dev` | Leaf |
| [R02](R02-journey-trust-data-quality.md) | Journey, Trust and Data Quality platform | R01 | `fixed_dev` | Leaf |
| [R03](R03-built-in-skill-package.md) | Built-in Skill package and render model | R01 | `fixed_dev` | Leaf |
| [R04](R04-team-skill-hub-stage-a.md) | Team Skill Hub and Trusted Pack Stage A | R03, R06 | `fixed_dev` | Leaf with two artifact channels |
| [R05](R05-business-semantic-registry.md) | Business Semantic Registry | R01 | `fixed_dev` | Leaf |
| [R06](R06-operator-model-contracts.md) | Analysis Operator and Model contracts | R01 | `fixed_dev` | Leaf |
| [R07](R07-context-pack-repo-provider.md) | Entity/time-aligned Context Pack and Repo Provider | R01 | `fixed_dev` | Leaf |
| [R08](R08-external-provider-rpc-guard.md) | External Provider and RPC Guard | R07 | `fixed_dev` | Leaf |
| [R09A](R09A-core-skill-runtime.md) | Core Skill Runtime and Project Overlay | R02, R03, R05-R07 | `fixed_dev` | Leaf |
| [R09B](R09B-team-hub-binding.md) | Team Hub Skill binding | R04, R09A | `fixed_dev` | Leaf |
| [R09C](R09C-external-context-binding.md) | External Context binding | R08, R09A | `fixed_dev` | Leaf |
| [R10](R10-mcp-thin-surface.md) | MCP thin Resources/Tools surface | R09A + trigger | `specified` | Conditional leaf |
| [R11](R11-pap-pilot.md) | Prepared Analysis Plan pilot | R02 | `fixed_dev` | Leaf |
| [R12](R12-action-experiment-receipt.md) | Action, Receipt, Experiment and Outcome | R09A | `fixed_dev` (A/B/C) | Staged epic A→B→C |
| [R13A](R13A-artifact-transfer.md) | Governed binary Artifact Transfer | R02 | `fixed_dev` | Leaf |
| [R13B](R13B-analysis-artifact-renderer.md) | Analysis Artifact and non-Gravity Renderer | R09A | `fixed_dev` | Leaf |
| [R13C](R13C-dashboard-connector.md) | Gravity Dashboard Connector | R12-A, R13B | `fixed_dev` | Leaf |
| [R14](R14-adaptive-governor-variants.md) | Adaptive Governor and Execution Variants | R02 | `fixed_dev` (A/B/C/D) | Staged epic A→B, C, then D |
| [R15](R15-isolated-sql-explorer.md) | Isolated SQL Explorer | R02, R05 | `specified` | Leaf |
| [R16](R16-control-plane-stage-b.md) | Control Plane Stage B | R04 + trigger | `specified` | Conditional leaf |
| [CT01](CT01-thinkingai-inventory.md) | ThinkingAI source inventory | R00 | `specified` | Parallel content |
| [CT02](CT02-thinkingai-representative-skills.md) | Representative ThinkingAI Skills | CT01, R09B | `specified` | Content validation |
| [CT03](CT03-thinkingai-full-specification.md) | Full independent Skill specifications | CT02 | `specified` | Content expansion |

[R09 legacy overview](R09-skill-runtime-project-overlay.md) and [R13 legacy overview](R13-artifact-analysis-delivery.md) are `superseded` navigation records and are not executable graph nodes.

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

`specified` means scope and dependency boundaries exist. Before changing a leaf or epic milestone to `ready`, the plan owner must fill unresolved decisions, bind a current baseline SHA and Issue, confirm write scope/worktree, and approve exact acceptance commands.

The user approved the R01 binding and designated the Requirement document as
the internal program delivery ledger on 2026-08-21. The same authorization lets
the plan owner promote later requirements without repeated user approval after
their dependencies, unresolved decisions, write scopes and exact machine gates
are bound. Production probes, writes, releases and `main` promotion retain their
separate explicit authorization rules.
