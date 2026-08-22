# R09A Core Skill Runtime And Project Overlay

| Field | Value |
| --- | --- |
| Parent directive | `gravity-agent-runtime/v9.1` via `directive.json` |
| Status | `fixed_dev`; integrated and validated on `dev` 2026-08-22 |
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
and `ready` to `in_progress`, then accepted the validated implementation as
`fixed_dev`. This does not authorize production probes,
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

## Fixed Dev Evidence

- Feature commit `011bd42` and merge `c7cf3ce` add strict packaged
  `gravity.project-skill-overlay.v1`, `gravity.execution-snapshot.v1` and
  `gravity.analysis-result.v1` contracts plus public compilers and one lazy
  `CoreSkillRuntime`. Root public API now has `125` lazy exports.
- The Core resolver composes exact R02/R03/R05-R07 owners offline. Snapshot
  references freeze Runtime version, Journey, Built-in manifest/package,
  Overlay Git revision/digest, Capability Trust digest, Semantic
  definition/binding/source/registry digests, Operator/Model, Context Pack and
  execution contract. Question, App/date/hypothesis, Context bodies, rows,
  credentials and private paths are rejected from the snapshot.
- The R01-only v3 project/Semantic adapters and provisional result descriptor
  are removed. The Built-in manifest now declares intrinsic
  `readiness=executable`; current `LocalSkillResolver` and Core readiness still
  return blocked because authoritative Multidim completeness remains `unknown`.
  The existing playbook consumes only the compiled project Semantic binding,
  retains its Plan/semantic-compose/Multidim/Operator owner, and freezes that
  binding into checkpoint identity.
- `ReferenceJourneyRunner` compares the complete snapshot before/after its
  single existing execution. Snapshot drift, request-budget excess, failed DQ
  or any dependency gap emits a compiled non-success Analysis Result with no
  findings, allowed claims or Receipt references. Synthetic complete/fresh
  evidence produces a schema-valid success through the existing Operator only;
  live work-dashboard remains exit 4 `COMPLETENESS_INSUFFICIENT`, empty
  findings/claims/receipts and `network_called=false`.
- R01 CLI/SDK/Plan remain available and the generated Built-in Agent Skill now
  constitutes the explicit Agent surface; no Agent card, MCP Tool, router,
  executor, binder, pagination, permission path or worker pool was added. R09B
  Team lock and R09C external Context binding remain absent and unnecessary.
- Focused R09A/public/docs gates pass `57` tests and `20` subtests. Complete
  gates pass `1586` unittest; `1586 passed, 3821 subtests` pytest; compiler
  `237 operations / 11 manifests`; quality and generators PASS; actionable
  errors are `1321` total (`1157 A`, `164 B`, `0 C`); active docs remain exactly
  `5500` lines; CLI and staged diff checks PASS.
- Development usability remains `296/336` selection, `248/248` fillability,
  `53/53` offline terminal and `5/5` recovery; security PASS and production HTTP
  requests `0`. Isolated wheel import/schema/package/live-block gates pass from
  `site-packages`; wheel SHA-256 is
  `421a98925a9834383ea9a239ce60456ab5c4cbee1959207c59dcb31cc9235a9a`,
  Built-in package digest is
  `544c1448df48f327f1e4785743358490271923448af1025fc82e9ab41eb41c1f`.
- Canonical consumer commits `e30c2036` and `e4369ce8` migrate the tracked
  work-dashboard Overlay, focused contract and current reference; focused gates
  pass `11` tests and `94` subtests. Its full governance remains blocked by
  unrelated inherited facts: two missing historical migration assets, one GM
  SQL provenance drift, one expired topic exception, one frozen HTML tmp link,
  and existing GM approval/registry suite contradictions. No R09A path fails and
  the consumer branch is not pushed while those repository gates are red.
- The mandatory full gate also exposed an R08 Windows taskkill descendant
  escape on unchanged `dev`; separate corrective `a4b7af3` / merge `8128185`
  introduced pre-stdin Job Object containment and passed R08/full gates before
  R09A final validation. R09A itself did not absorb Provider binding or RPC
  ownership.

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
