# Gravity Agent Runtime Requirement Index

本目录是 [Gravity Agent Runtime v9.2 canonical architecture](architecture-source.md) 的派生需求层。[directive.json](directive.json) v9.2 绑定总纲 SHA-256。总纲是唯一产品与共享架构源；这里的文档只定义有界交付单元，不得反向改写总纲。

## Program Rules

- 功能需求必须经过 `specified → reviewed → ready` 才能施工；正文不能自行宣布 `ready`。
- 默认一份叶子需求对应一个主 Issue、一个 `codex/<unit>` 分支/Worktree 和一个端到端交付单元。
- R12、R14 是总纲唯一明确批准的 `staged_epic`；每个强制子阶段仍对应独立 Issue、分支、提交、验收和回滚，父项只能在全部子阶段完成后到达 `fixed_dev`。其他顶层 Requirement 默认为 leaf。
- 领域 core 可并行；共享 spine 的最终接线由单一 integrator 串行完成。
- 已验收单元合入 `dev` 后状态为 `fixed_dev`。完整计划结束前不合入 `main`，也不使用 `released`。
- 外部 Hub 或 Provider 缺失只阻塞显式依赖它们的 Skill；不得阻塞 R09A Built-in Core Skill Runtime。
- 实际状态、依赖、ready 前置、里程碑和触发条件以 [index.json](index.json) 为机器权威。

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
[R17 ready prerequisites: M0 binding and SCC semantics satisfied; dynamic-audit classification satisfied; independent ready review pending] ⇢ R17 leaf (82 moves + 1 consolidation; 1 infrastructure exclusion)
R00 → CT01
CT01 + R09B → CT02 → CT03
```

R17 行中的方括号内容是 `ready_prerequisites`，不是 Requirement 或 milestone 节点；R17 没有 Requirement 依赖。

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
| [R15](R15-isolated-sql-explorer.md) | Isolated SQL Explorer | R02, R05 | `fixed_dev` | Leaf |
| [R16](R16-control-plane-stage-b.md) | Control Plane Stage B | R04 + trigger | `specified` | Conditional leaf |
| [R17](R17-agent-module-package-migration.md) | Compact Agent interaction package migration | -; machine-readable ready prerequisites | `specified` | Leaf with two serial checkpoints on one branch |
| [CT01](CT01-thinkingai-inventory.md) | ThinkingAI source inventory | R00 | `fixed_dev` | Parallel content |
| [CT02](CT02-thinkingai-representative-skills.md) | Representative ThinkingAI Skills | CT01, R09B | `fixed_dev` | Content validation |
| [CT03](CT03-thinkingai-full-specification.md) | Full independent Skill specifications | CT02 | `fixed_dev` | Content expansion |

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

R17's 82-module responsibility-inventoried move set includes the three `agent_*` spine modules; its core implementation checkpoint moves them to
`src/gravity_sdk/agents/{capabilities,composite,handoff}.py` and must update the
machine list atomically with that code move. Until the core phase lands, the paths above
remain authoritative.

Requirement branches implement domain cores and focused tests first. A named integrator performs final shared-spine wiring, generated artifact refresh and cross-requirement validation serially on `dev`.

## Readiness

`specified` means scope and dependency boundaries exist. Before changing a leaf or epic milestone to `ready`, the plan owner must fill unresolved decisions, bind a current baseline SHA and Issue, confirm write scope/worktree, and approve exact acceptance commands.

R17 只有一个 leaf 状态和一个实施分支/Worktree。独立职责清单保留原 81 个 move、零误纳，
并补入唯一由 `agent_handoff` 消费的 `relative_date_agent`，形成 82 个一对一迁移；
`agent_pagination` 合并删除，`agent_runtime_contracts` 与 `find.py` 仍不纳入。前缀图继续
复现 contracts 排除，但四种全作用域图判据没有收敛，所以当前证据支撑调整后的有界范围，
不证明完整 Agent domain，也不声称完全通过总纲的反路径依赖门槛。M0 characterization
与 dynamic-audit classification 均已满足，owner review 仍为 `pending`。实施绑定为
`dev@24f16c667d80107e4149cf76742eab4ada564197`、无 GitHub Issue（内部结构债禁止
自建 Issue）、`codex/r17-migration` / `D:/git-pjt/gravity-sdk-r17-migration`。
机器状态为 `status=specified`、`dynamic_import_audit_classification.satisfied=true`、
`schema=gravity.agent-module-reference-dispositions.v2`、`candidate_sites=238`、
`classified_sites=238`、`unclassified_sites=0`、`blocking_sites=0`；独立复核仍为
`not_ready`。两个内部阶段只是同一分支上的串行提交/回滚 checkpoint，不获得独立
状态，也不能独立使 R17 到达 `fixed_dev`。

`m0_bound_implementation_baseline=113176a381b6d232e95a112d78d1d2f4bc5ac024`；
`m0_bound_artifact_sha256={"tests/agent_migration_characterization.py":"97b3c71842b3904213ec24667ae09f4c821df0384f6667847e3c03f6c9d9d640","tests/fixtures/public_api_exports.json":"d6aa4c9bb939f6e56428192ad432300fe985618fae69492cc9e12820dd43c053","tests/fixtures/public_api_owner_migrations.json":"37517e5f3dc66819f61f5a7bb8ace1921282415f10551d2defa5c3eb0985b570","tests/test_agent_module_migration_characterization.py":"6e5c0530fbc7b869d896d26cb01ec76649f4bf2a48adeeb0b9968395f4af8ffc","tests/test_installed_wheel.py":"bd8d9cf332354147fd4e11f87ac7d09b48ac7dcf1d4eae164900b0baf7bed117"}`；
`ledger_sha256=9d5b4d197cd84a0da4bb644256c9df7670ec89b7258e710434ab1ac8fed8be20`；
`live_checkpoint_sha256=3db0645f85a182332fa5460ea7bea05aa73340d6d6108052292d546cbc74f5d9`；
`live_checkpoint_tracked_sites=909`。

The user approved the R01 binding and designated the Requirement document as
the internal program delivery ledger on 2026-08-21. The same authorization lets
the plan owner promote later requirements without repeated user approval after
their dependencies, unresolved decisions, write scopes and exact machine gates
are bound. Production probes, writes, releases and `main` promotion retain their
separate explicit authorization rules.
