# Gravity Agent Runtime Requirement Index

本目录是 [Gravity Agent Runtime v9.3 canonical architecture](architecture-source.md) 的派生需求层。[directive.json](directive.json) v9.3 绑定总纲 SHA-256。总纲是唯一产品与共享架构源；这里的文档只定义有界交付单元，不得反向改写总纲。

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
[R17 delivery accepted on dev; historical M0 and dynamic ledger bindings retained] ⇢ R17 fixed_dev leaf (82 moves + 1 consolidation; 1 infrastructure exclusion)
R00 → CT01
CT01 + R09B → CT02 → CT03
```

R17 方括号是交付验收记录，不是新增 Requirement 或 milestone；R17 没有 Requirement 依赖。

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
| [R10](R10-mcp-thin-surface.md) | MCP thin Resources/Tools surface | R09A + explicit bounded-pilot trigger | `fixed_dev` | Conditional leaf; local stdio only |
| [R11](R11-pap-pilot.md) | Prepared Analysis Plan pilot | R02 | `fixed_dev` | Leaf |
| [R12](R12-action-experiment-receipt.md) | Action, Receipt, Experiment and Outcome | R09A | `fixed_dev` (A/B/C) | Staged epic A→B→C |
| [R13A](R13A-artifact-transfer.md) | Governed binary Artifact Transfer | R02 | `fixed_dev` | Leaf |
| [R13B](R13B-analysis-artifact-renderer.md) | Analysis Artifact and non-Gravity Renderer | R09A | `fixed_dev` | Leaf |
| [R13C](R13C-dashboard-connector.md) | Gravity Dashboard Connector | R12-A, R13B | `fixed_dev` | Leaf |
| [R14](R14-adaptive-governor-variants.md) | Adaptive Governor and Execution Variants | R02 | `fixed_dev` (A/B/C/D) | Staged epic A→B, C, then D |
| [R15](R15-isolated-sql-explorer.md) | Isolated SQL Explorer | R02, R05 | `fixed_dev` | Leaf |
| [R16](R16-control-plane-stage-b.md) | Control Plane Stage B | R04 + trigger | `specified` | Conditional leaf; trigger fired 2026-08-28, implementation deferred by decision — see its Disposition |
| [R17](R17-agent-module-package-migration.md) | Compact Agent interaction package migration | -; bound delivery evidence | `fixed_dev` | Leaf; original two serial checkpoints preserved |
| [CT01](CT01-thinkingai-inventory.md) | ThinkingAI source inventory | R00 | `fixed_dev` | Parallel content |
| [CT02](CT02-thinkingai-representative-skills.md) | Representative ThinkingAI Skills | CT01, R09B | `fixed_dev` | Content validation |
| [CT03](CT03-thinkingai-full-specification.md) | Full independent Skill specifications | CT02 | `fixed_dev` | Content expansion |

[R09 legacy overview](R09-skill-runtime-project-overlay.md) and [R13 legacy overview](R13-artifact-analysis-delivery.md) are `superseded` navigation records and are not executable graph nodes.

## Milestones

| ID | Parent | Dependencies | State |
| --- | --- | --- | --- |
| R12-A | R12 | - | `fixed_dev` |
| R12-B | R12 | R12-A | `fixed_dev` |
| R12-C | R12 | R12-B | `fixed_dev` |
| R14-A | R14 | - | `fixed_dev` |
| R14-B | R14 | R14-A | `fixed_dev` |
| R14-C | R14 | - | `fixed_dev` |
| R14-D | R14 | R14-B, R14-C | `fixed_dev` |

## Integrated Validation

`integrated_validation_green` 仅在同一个 clean `dev` SHA 和该 worktree 的独立
`.venv` 上成立：运行
`.venv/Scripts/python.exe scripts/run_integrated_validation.py`，25 个 included
gate 全部退出 0，运行前后 HEAD 不变且工作树保持 clean，并生成绑定 exact HEAD 的
`tmp/integrated-validation/{commit_sha}/receipt.json`。receipt 是 ignored run
artifact，不是新的 canonical source；脏树在生成前直接拒绝。

机器定义、完整 gate 清单和排除项以 [index.json](index.json) 的
`integrated_validation` 为准。真实 PyPI provenance 只在发布后存在，因此明确属于
post-release gate；合 `main` 前只运行已纳入清单的离线 provenance fixture。所有
included gate 均禁用真实网络。

## Integration Ownership

The following files are shared-spine integration points and cannot be wired concurrently across worktrees:

```text
src/gravity_sdk/plan_adapters.py
src/gravity_sdk/agents/capabilities.py
src/gravity_sdk/agents/composite.py
src/gravity_sdk/agents/handoff.py
src/gravity_sdk/cli.py
src/gravity_sdk/__main__.py
```

R17's human-reviewed 82-module manifest included the three Agent spine modules.
Their delivered owners are now `src/gravity_sdk/agents/{capabilities,composite,handoff}.py`;
the machine list above matches the accepted core checkpoint.

Requirement branches implement domain cores and focused tests first. A named integrator performs final shared-spine wiring, generated artifact refresh and cross-requirement validation serially on `dev`.

## Readiness

`specified` means scope and dependency boundaries exist. Before changing a leaf or epic milestone to `ready`, the plan owner must fill unresolved decisions, bind a current baseline SHA and Issue, confirm write scope/worktree, and approve exact acceptance commands.

R10 的第二条 trigger 分支由 2026-08-28 owner task directive 满足：只批准
可移除的本地 stdio pilot，并绑定未达 Host 准确率或缺少第二采用方即退回
schema-only 的退出条件。当前状态是 `fixed_dev`；基线为
`824f92524f5703d7cb7ba0b2d6a671befb51a45f`，分支/Worktree 为
`codex/r10-mcp-stdio-pilot` / `D:/git-pjt/gravity-sdk-r10mcp`。GitHub 搜索未找到
对应 R10/MCP Issue，机器索引如实记录 `github_issue=null`，不伪造 Issue。
`specified → reviewed → ready` 的记录者为
`agent_under_standing_owner_delegation`，`owner_review: pending`；合入 `dev` 与
开发 20 题验收前不得提升到 `fixed_dev`。2026-08-29 状态裁决把开发集绑定
`fixed_dev`，把盲测 holdout 与第二独立采用方保留并绑定 `released`/永久产品面；
二者均未取消。通用显式 enum/格式绑定规则修复后，阶段 A（只改 evaluator）
与阶段 B（再澄清 Skill/Journey、Product/Operation/Composite 描述）均为首选
`18/20`、合法答案 `18/20`、MCP RPC `120`、内部/生产 HTTP `0`；两项冻结争议
答案仍判错。没有声明或接入真实 Host 版本，不得冒充 Claude Desktop/Cursor
证据。开发门槛已过，因此状态为 `fixed_dev`；盲测、真实 Host 和第二采用方仍
绑定 `released`。裁决记录者为 `agent_under_standing_owner_delegation`，
`owner_review: pending`。

R17 已按外部计划 owner 裁决达到 `fixed_dev`：Phase 1
`4926362f42f9ea68a11e42559a802cb7ba67f6ee`、Phase 2
`ea33c42eeb82fc7fb8a62ef60e11ba5a8527dc69` 和 dev 集成
`125bb84cbb98a575a2ef3c4a577f174027bc908d` 已验收。双 collector 全绿、
两级 rollback tree 精确一致，独立 thermo review 无高置信阻断；原迁移分支和历史不改。
裁决为 `agent_under_standing_owner_delegation`，`owner_review: pending`。
原实验式 independent-ready 前置已退役为准确的 `delivery_acceptance`；
两个已满足的 `ready_prerequisites` 只保留 M0/动态 ledger 的历史证据绑定，
不伪造更早的 ready 或用户逐项批准。

边界是人工审阅的 compact Agent interaction manifest：82 项一对一移动，
`agent_pagination` 合并删除，共享 `agent_runtime_contracts` 留在根目录。
Runtime 执行核、共享 schema validator、独立 Find protocol 不因此进入 Agent 包。
relative-date 已按同一个边界词去除规则迁入 `agents.relative_date`。
这不证明完整 Agent domain，也不声称通用自动独立证明。legacy 图/docstring/
consumer-count 分类器、v4 职责绑定实验及其签名摘要已退役；真实不变量复用
manifest、公开 owner、现有 eager SCC、concept/errata/wheel 和 consumer gate。

五条基线 facade 依赖有意保留：`agents.batch` 和 `agents.input_resolution`
依赖 `agent.discover_capabilities`，`agents.batch_questions` 依赖
`agent.DEFAULT_LIMIT`，`agents.host_selection` 和 `agents.output` 依赖
`agent.SCHEMA_VERSION`。这是单一 discovery/protocol owner 设计，不构成 eager cycle，
也不是 #11 的未完成零反向边目标；模块/符号集合由有界测试锁定。

机器状态：`status=fixed_dev`、`dynamic_import_audit_classification.satisfied=true`、
`schema=gravity.agent-module-reference-dispositions.v2`、`candidate_sites=238`、
`classified_sites=238`、`unclassified_sites=0`、`blocking_sites=0`。
`accepted_by=agent_under_standing_owner_delegation`；`owner_review=pending`；
`phase_1_commit=4926362f42f9ea68a11e42559a802cb7ba67f6ee`；
`phase_2_commit=ea33c42eeb82fc7fb8a62ef60e11ba5a8527dc69`；
`dev_integration_commit=125bb84cbb98a575a2ef3c4a577f174027bc908d`。

`m0_bound_implementation_baseline=113176a381b6d232e95a112d78d1d2f4bc5ac024`；
`m0_bound_artifact_sha256={"tests/agent_migration_characterization.py":"97b3c71842b3904213ec24667ae09f4c821df0384f6667847e3c03f6c9d9d640","tests/fixtures/public_api_exports.json":"d6aa4c9bb939f6e56428192ad432300fe985618fae69492cc9e12820dd43c053","tests/fixtures/public_api_owner_migrations.json":"37517e5f3dc66819f61f5a7bb8ace1921282415f10551d2defa5c3eb0985b570","tests/test_agent_module_migration_characterization.py":"6e5c0530fbc7b869d896d26cb01ec76649f4bf2a48adeeb0b9968395f4af8ffc","tests/test_installed_wheel.py":"bd8d9cf332354147fd4e11f87ac7d09b48ac7dcf1d4eae164900b0baf7bed117"}`；
`ledger_sha256=9d5b4d197cd84a0da4bb644256c9df7670ec89b7258e710434ab1ac8fed8be20`；
`live_checkpoint_sha256=d0a1523ce65bb24b795cb0d031f3cd4e884d59a0312c0b8d44bbcfbcb57a62f2`；
`live_checkpoint_tracked_sites=314`。

The user approved the R01 binding and designated the Requirement document as
the internal program delivery ledger on 2026-08-21. The same authorization lets
the plan owner promote later requirements without repeated user approval after
their dependencies, unresolved decisions, write scopes and exact machine gates
are bound. Production probes, writes, releases and `main` promotion retain their
separate explicit authorization rules.
