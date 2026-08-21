# R09 Skill Runtime And Project Overlay

| Field | Value |
| --- | --- |
| Parent directive | `gravity-agent-runtime/v9` via `directive.json` |
| Status | `specified` |
| Track | Runtime integration |
| Dependencies | R02, R04, R05, R06, R07, R08 |
| Parallel group | `integration` |
| Shared-spine integration | Required; one integrator only |

## Outcome

Locked Skills resolve their Capability, Semantic, Operator/Model and Context dependencies, evaluate readiness, guide the existing routing/execution owner, and produce structured Analysis Results. Project overlays customize project bindings without overriding governance.

## Current Baseline

After R02-R08, each domain contract exists independently. Current Agent guides and semantic context can suggest products, but no runtime service composes a locked Skill dependency graph or project overlay into Journey readiness and analysis output.

## Scope

- Resolve Built-in/Hub Skill from exact project lock or explicit unlocked Built-in fallback.
- Evaluate orthogonal lifecycle, readiness and validation at execution time.
- Bind project Semantic/Context/default scope through `project.<name>.*` overlays.
- Preserve exact selector, host catalog and recognizer as the only routing authorities.
- Invoke Operators only after governed data and DQ validation.
- Produce `gravity.analysis-result.v1` and Receipt references.

## Non-goals

- No Skill execution DSL, scheduler, router or arbitrary scripts.
- No overlay override of Trust, completeness, claims, privacy, selector authority or Action authorization.
- No automatic Hub update during a Journey.

## Machine Contract

Skill specification, lifecycle, current readiness and validation are independent. Execution snapshots freeze Skill digest, Semantic, Operator/Model, Provider and contract versions. Every gap names the failed dependency and stable reason without exposing sensitive values.

## Migration And Compatibility

Existing Agent product cards and generated guides remain the public discovery floor until new Skill parity is proved. Public CLI/SDK/Plan owners are reused. Calling projects migrate their overlay, lock and consumer tests in the same unit as new Skill-facing surfaces.

## Safety And Operations

Dependency resolution and `can-run` are offline by default. Context is data; Skills cannot authorize writes. Request and context budgets aggregate once and do not create nested worker pools.

## Acceptance

- Wave A/B/C representative Skills resolve or block honestly.
- Project overlay changes do not require a Runtime wheel release.
- No second routing/execution path appears.
- Locked versions remain frozen for the Journey.
- Analysis Result claims never exceed completeness, DQ, evidence or Context authority.

## Verification

Dependency graph cases, lock mismatch/tamper, overlay merge/conflict, readiness transitions, prompt-injection authority, request/context budgets, CLI/SDK/Plan/Agent parity, canonical consumer tests and full gates.

## Rollback And Exit

Projects can pin the prior Skill/overlay digest. Removing the composed runtime returns existing product discovery rather than executing a guessed fallback. Every temporary adapter has an owner and exit condition.

## Canonical Owners

Skill runtime/resolver, overlay schema, Analysis Result schema, agent workflow, project configuration reference and Journey status.
