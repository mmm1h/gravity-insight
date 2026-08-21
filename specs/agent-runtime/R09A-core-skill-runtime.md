# R09A Core Skill Runtime And Project Overlay

| Field | Value |
| --- | --- |
| Parent directive | `gravity-agent-runtime/v9.1` via `directive.json` |
| Status | `specified` |
| Track | Core Runtime composition |
| Dependencies | R02, R03, R05, R06, R07 |
| Parallel group | `core-runtime` |
| Shared-spine integration | Required; one integrator only |

## Outcome

Built-in Skills resolve Trust, Semantic, Operator and Repo Context dependencies, evaluate readiness, guide the existing execution owner and produce `gravity.analysis-result.v1`. Project Overlay works without a remote Team Hub or external Context Provider.

## Current Baseline

R02/R03/R05/R06/R07 provide machine contracts independently. Current Agent guides can suggest Products, but no Core Skill Runtime composes those local dependencies into one execution snapshot and Analysis Result.

## Scope

- Resolve Built-in Skills shipped in the Runtime wheel.
- Evaluate orthogonal lifecycle, readiness and validation.
- Bind project Semantic/Repo Context/default scope through `project.<name>.*` Overlay.
- Preserve exact selector, host catalog and recognizer as the only routing authorities.
- Invoke Operators only after governed data, completeness and DQ validation.
- Freeze Skill/Semantic/Operator/Context/contract versions in an execution snapshot.

## Non-goals

- No remote Hub sync/cache binding; R09B owns it.
- No external MCP/subprocess/host Context binding; R09C owns it.
- No Skill execution DSL, router, scheduler or arbitrary scripts.

## Machine Contract

An unlocked Built-in Skill reports `skill_resolution=unlocked` but remains executable when all local dependencies pass. Analysis Result contains value-free Skill, Journey, Capability, Semantic, Operator, Context Pack and Receipt references. Project Overlay cannot override Trust, completeness, claims, privacy, selector authority or Action authorization.

## Migration And Compatibility

Existing Agent cards/guides remain the discovery floor until parity is proved. Product/Composite/Plan owners remain the only executors. Public surface changes migrate canonical consumers in the same development unit.

## Safety And Operations

Dependency resolution and `can-run` are offline by default. Context is data and Skills cannot authorize writes. Missing remote Hub or external Provider is irrelevant because neither is a dependency of R09A.

## Acceptance

- A Built-in reference Skill runs end to end with local Repo Context.
- Project Overlay changes do not require a Runtime wheel release.
- No second route, executor, binder, pagination or permission path appears.
- Claims never exceed Trust, completeness, DQ or Context authority.
- R09A remains green when R04/R08/R09B/R09C are absent.

## Verification

Dependency/readiness transitions, project overlay merge/conflict, request/context budgets, Analysis Result/Receipt snapshots, CLI/SDK/Plan/Agent parity, absence-of-Hub/Provider tests, consumer tests and full gates.

## Rollback And Exit

Disabling Core Skill composition returns existing product discovery and execution; it never selects a guessed fallback. Temporary adapters require explicit owners and removal conditions.

## Canonical Owners

Core Skill resolver/runtime, Overlay schema, Analysis Result schema, agent workflow and Journey state.
