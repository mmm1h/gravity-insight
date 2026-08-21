# R05 Business Semantic Registry

| Field | Value |
| --- | --- |
| Parent directive | `gravity-agent-runtime/v9` via `directive.json` |
| Status | `specified` |
| Track | Method and meaning |
| Dependencies | R01 |
| Parallel group | `foundation-a` |
| Shared-spine integration | Final routing/handoff wiring is serialized |

## Outcome

Reusable Metric, Dimension, Entity, Cohort, Event, SKU, Activity and Release definitions compile into versioned machine contracts. Runtime owns schema and validation; calling projects own concrete bindings and values.

## Current Baseline

Workspace and `workspace_semantic_context.py` already carry App aliases, verified queries, terms, exclusions and derived metric declarations. Business formulas and activity/SKU/tracking facts are intentionally calling-project data, but there is no uniform versioned Semantic URI or conflict model.

## Scope

- Define Semantic schema, stable URI/version, owner and effective range.
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
