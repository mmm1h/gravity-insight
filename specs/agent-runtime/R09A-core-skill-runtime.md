# R09A Core Skill Runtime And Project Overlay

| Field | Value |
| --- | --- |
| Parent directive | `gravity-agent-runtime/v9.1` via `directive.json` |
| Status | `in_progress`; plan-owner ready verdict 2026-08-22 |
| Track | Core Runtime composition |
| Dependencies | R02, R03, R05, R06, R07 |
| Parallel group | `core-runtime` |
| Shared-spine integration | Required; one integrator only |
| Delivery ledger | This Requirement document; no internal GitHub Issue |
| Baseline | `dev@2457dcb14f2a94c4398628294253d868f73052d9` |
| Branch / worktree | `codex/r09a-core-skill-runtime` / `D:\\git-pjt\\gravity-sdk-wt\\r09a-core-skill-runtime` |
| Consumer | `work-dashboard@6fdea63c` / `codex/r09a-core-skill-runtime-consumer` |
| Integrator | Root Codex agent; shared-spine wiring remains serial |
| Production requests | `0`; synthetic complete/fresh evidence only |
| Main integration | Frozen until whole program completion |

## Outcome

Built-in Skills resolve Trust, Semantic, Operator and Repo Context dependencies, evaluate readiness, guide the existing execution owner and produce `gravity.analysis-result.v1`. Project Overlay works without a remote Team Hub or external Context Provider.

## Plan Owner Verdict And Ready Binding

The user approved the R01 proposal, designated its Requirement as the internal
delivery ledger and authorized continuous implementation without repeated
Requirement approval. R02, R03 and R05-R07 are `fixed_dev`; the plan owner
reviewed `tmp/r09a-core-skill-runtime-proposal.md` and its conflict ledger,
bound the baseline/worktrees/gates below, and advanced R09A through `reviewed`
and `ready` to `in_progress`. This does not authorize production probes,
credentials, Hub/Provider calls, writes, package installation, release or
`main` promotion.

- Replace the R01-only project contract with a closed
  `gravity.project-skill-overlay.v1`: exact `project.*` identity and `extends`,
  project Semantic sources/scope, Repo Context Requirements and default scope
  only. Trust, completeness, DQ, claims, privacy, selector/effect authority and
  Action authorization cannot be represented as Overlay overrides.
- Add one offline `CoreSkillRuntime` resolver over the existing R02/R03/R05-R07
  owners. It resolves and snapshots dependencies but never routes or executes
  data, syncs Hub content, invokes an external Provider or creates a worker
  pool. R09B and R09C remain independent optional bindings.
- Change the Built-in reference Skill's intrinsic readiness to `executable`,
  while current readiness remains dependency-derived. The live R01 path stays
  blocked on authoritative `completeness=unknown` with zero requests.
- Replace the input-derived digest string with a strict self-digested,
  value-free `gravity.execution-snapshot.v1` object covering exact Runtime,
  Journey, Skill package/manifest, Overlay, Trust, Semantic, Operator/Model,
  Context and execution-contract references. Compare the full snapshot around
  execution.
- Formalize and compile `gravity.analysis-result.v1`. Success/blocked/invalid
  results use one closed reference surface; non-success cannot carry findings,
  allowed claims or Receipt references. Context bodies, row values, credentials
  and private paths never enter component references or the snapshot.
- `ReferenceJourneyRunner` remains the sole Journey execution owner and
  delegates exactly once to the existing metric-anomaly playbook, Plan,
  semantic-compose, Multidim and registered Operator path. The existing
  playbook may consume only the already validated project Semantic binding; no
  router, executor, binder, pagination, permission or Plan adapter is added.
- Migrate the stacked work-dashboard consumer in the same unit and prove both
  the unchanged live block and a synthetic complete/fresh end-to-end success.
  Public SDK/CLI/Plan/Agent Skill parity, real-wheel resources, request/context
  budgets, tamper/conflict cases, full gates and active docs at exactly 5500
  lines are mandatory acceptance evidence.

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

Focused acceptance covers Project Overlay, Core resolution, execution snapshot,
Analysis Result, R01 Journey/playbook, Built-in package/rendering, public SDK and
documentation. Final acceptance additionally runs both complete collectors,
compiler/quality, development usability/security, an isolated installed wheel,
consumer focused/full gates, CLI help and `git diff --check` in both worktrees.

## Rollback And Exit

Disabling Core Skill composition returns existing product discovery and execution; it never selects a guessed fallback. Temporary adapters require explicit owners and removal conditions.

## Canonical Owners

Core Skill resolver/runtime, Overlay schema, Analysis Result schema, agent workflow and Journey state.
