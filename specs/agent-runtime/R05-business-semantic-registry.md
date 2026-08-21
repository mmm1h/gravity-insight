# R05 Business Semantic Registry

| Field | Value |
| --- | --- |
| Parent directive | `gravity-agent-runtime/v9.1` via `directive.json` |
| Status | `in_progress`; plan-owner ready verdict 2026-08-22 |
| Track | Method and meaning |
| Dependencies | R01 |
| Parallel group | `foundation-a` |
| Shared-spine integration | Final routing/handoff wiring is serialized |
| Delivery ledger | This Requirement document; no internal GitHub Issue |
| Baseline | `dev@9deb9be68493499beb521f74650ad90525444a09` |
| Branch / worktree | `codex/r05-business-semantic-registry` / `D:\git-pjt\gravity-sdk-wt\r05-business-semantic-registry` |
| Consumer | `work-dashboard@6b94d3d3955646aad4776688e9f99d693e06e20c` -> `codex/r05-semantic-registry-consumer` |
| Integrator | Root Codex agent; plural CLI/root export wiring remains serial |
| Production requests | `0`; live evidence not authorized |

## Outcome

Reusable Metric, Dimension, Entity, Cohort, Event, SKU, Activity and Release definitions compile into versioned machine contracts. Runtime owns schema and validation; calling projects own concrete bindings and values.

## Plan Owner Verdict And Ready Binding

The user authorized continuous implementation without repeated Requirement
approval. R01-R03 are `fixed_dev`; the plan owner reviewed
`tmp/r05-business-semantic-registry-proposal.md` and its conflict ledger, bound
the current baseline/worktrees/safety gates below, and advanced R05 through
`reviewed` and `ready` to `in_progress`. This does not authorize production
probing, writes, releases or `main` promotion.

- Runtime owns closed Semantic Definition/Binding/Source schemas, common
  definitions, formula/unit/additivity/time/dependency validation and stable
  resolution reasons. Project sources own concrete App aliases, physical
  members, formula parameters and effective windows.
- Runtime initially ships only reusable `entity://gravity/app@1`; the R01
  acquisition-spend metric and its binding move to a separate canonical
  work-dashboard semantic source.
- Existing semantic-compose definitions remain physical execution/member
  contracts. Existing workspace semantic context remains routing/local
  arithmetic context; neither is silently promoted into business meaning.
- Formula operators are closed to source/sum/difference/ratio and exact
  versioned dependencies. Cycles, missing dependencies, unit/currency,
  additivity, time-grain, parameter and overlapping-effective-range conflicts
  fail closed.
- Public targets are `SemanticRegistry` and
  `gravity semantics list|describe|resolve|validate`. Singular
  `gravity semantic compose` remains the only current semantic execution path.
- R01 project loading becomes a generic source adapter while preserving exact
  URI, claims, physical binding, App/effective-time gate and zero-request
  behavior. Context generalization remains R07.
- Exact acceptance includes all eight kinds, deterministic compile/digest,
  conflict/status/reason cases, public snapshot/docs, real wheel, canonical
  consumer migration, full repository gates and usability parity.

## Current Baseline

Workspace and `workspace_semantic_context.py` already carry App aliases, verified queries, terms, exclusions and derived metric declarations. Concrete activity/SKU/tracking bindings plus project formula parameters/effective windows remain calling-project data, but Runtime lacks reusable Semantic types/common definitions, versioned URIs and a uniform conflict model.

## Scope

- Define Semantic schema, stable URI/version, owner and effective range.
- Own reusable types, common metric/method definitions and generic formula structure; keep concrete project bindings/values/parameters in project sources.
- Validate formula dependencies, units, currency, additivity, time grain, cohort/entity and attribution windows.
- Compile project JSON/TOML/provider input into immutable definitions.
- Resolve Skill/Journey dependencies offline.
- Return explicit missing, ambiguous, conflicting, expired and invalid reasons.

## Non-goals

- No automatic inference from field names, vendor pages or LLM knowledge.
- No project-specific values embedded in Runtime packages.
- No general-purpose BI semantic cloud or query planner.

## Machine Contract

Definitions use stable URIs such as `metric://project/payment_rate@1`; identity, owner and validity are distinct from source location. Formula graphs are acyclic and unit-checked. Multiple current authoritative definitions for one identity fail closed.

## Migration And Compatibility

Existing workspace semantics are characterized and compiled rather than bypassed. A project may migrate incrementally; undeclared meanings return a Semantic Gap and do not fall back to legacy guessing. Canonical consumer bindings migrate in the same unit as public surface changes.

## Safety And Operations

Semantic resolution is offline. Source documents are data and cannot select internal adapters or authorize actions. Sensitive project values remain under calling-project access control and are not copied into generic packages.

## Acceptance

- Formula cycles, unit conflicts, owner absence and overlapping effective ranges fail closed.
- Same input and sources compile to the same digest.
- R01 definitions compile without changing their meaning.
- Skill/Journey dependency checks return stable reasons.
- Unbound project concepts never become guessed formulas.

## Verification

Schema tests, formula/unit/additivity cases, effective-range property tests, deterministic compilation, workspace migration fixtures, offline zero-network tests, public API snapshots and full gates.

## Rollback And Exit

During migration, legacy workspace declarations may be a source adapter with an explicit removal condition. Disabling the Registry returns gaps rather than substituting inferred semantics.

## Canonical Owners

Semantic schemas/compiler, workspace reference, calling-project binding guide, agent workflow and affected Journey/Skill contracts.
