# R11 Prepared Analysis Plan Pilot

| Field | Value |
| --- | --- |
| Parent directive | `gravity-agent-runtime/v9.1` via `directive.json` |
| Status | `fixed_dev`; integrated and validated on `dev` 2026-08-22 |
| Track | Optional Plan-backed optimization |
| Dependencies | R02 |
| Parallel group | `independent-pilot` |
| Shared-spine integration | Required and serialized |
| Delivery ledger | This Requirement document; no internal GitHub Issue |
| Baseline | `dev@cfd3d51259c44f5f1556423e7b6bf9f2567ed5b1` |
| Branch / worktree | `codex/r11-pap-pilot` / `D:\\git-pjt\\gravity-sdk-wt\\r11-pap-pilot` |
| Consumer | Retained R09A stack `work-dashboard@e4369ce8`; non-regression only |
| Integrator | Root Codex agent; shared-spine wiring remains serial |
| Production / external requests | `0`; local fixtures only |
| Main integration | Frozen until whole program completion |

## Plan Owner Verdict And Ready Binding

The user designated each Requirement as the internal delivery ledger and
authorized continuous implementation without repeated approval. R02 is
`fixed_dev`; the plan owner reviewed `tmp/r11-pap-pilot-proposal.md` and its
conflict ledger, bound the baseline/worktree/gates below, advanced R11 through
`reviewed` and `ready`, and started it as `in_progress`. This does not authorize
credentials, production/external requests, mutation, package installation,
release or `main` promotion.

- Characterize direct Product, Direct Bounded Composite, SDK-internal Plan and
  host-generated Plan separately. Pilot PAP only for principal-scoped,
  read-only host Plans composed exclusively of stable executable `run`
  operation nodes; all unproved topologies fail locally without affecting their
  existing entry points.
- Prepare must enter `execute_host_plan`, complete the ordinary dry-run Plan
  validation/binding/adapter preflight, and only then atomically commit private
  `gravity.prepared-analysis-plan.v1` state. Execute must recheck every binding
  and re-enter `execute_host_plan`; PAP owns no executor, binder, scheduler,
  adapter, permission layer or result envelope.
- Persist only value-free Plan/source bindings, selected operation contract and
  catalog fingerprints, workspace catalog fingerprint, bounded counts/budget
  and expiry. Never persist raw Plan/source/input values, credentials, Scope
  digest, account identifier, user rows or condition-sensitive values. The
  caller resubmits the exact host Plan and sources for execution.
- Return only an opaque nonce/scope-bound `pap_id` plus safe summary. Stable
  local reasons cover unbound scope, unsupported path, identity, reference,
  missing/tampered/expired state, input/source/contract/catalog drift and store
  bounds before target calls.
- Store below the already principal-scoped workspace state with strict
  schema/size/link/count/byte limits, atomic immutable creation, bounded TTL and
  expired-entry cleanup. No mutable alias, latest pointer, remote fetch/sync or
  public backing path is allowed.
- Preserve exact host direct-versus-PAP target request count, request values,
  budget, completeness, errors, projection/privacy and public envelope bytes.
  Prepare and every pre-execution rejection make zero target calls.
- Add one lazy `GravitySDK.prepared_plans` service and one root service export.
  No CLI/MCP/Skill/Journey/Agent-card prerequisite is added; R10 and all
  direct/composite/internal Plan paths remain independent.
- Acceptance includes four-topology characterization; happy/empty/error/
  completeness parity; source attacks; scope isolation; strict private-state
  privacy/tamper/expiry/bounds; input/source/contract/catalog drift; checkpoint
  atomicity; isolated wheel; full repository, usability/security and retained
  consumer gates. Active human docs remain exactly 5500 lines.

## Fixed Dev Evidence

- Feature commit `f76099c` and merge `ae66b22` add strict private/public PAP
  schemas, one `PreparedAnalysisPlanService`, lazy `GravitySDK.prepared_plans`
  and one root export. The root now has `128` lazy exports and
  `gravity_sdk.__all__` has `129` entries including `__version__`; no CLI, MCP,
  Agent card, Skill/Journey dependency or new execution owner was added.
- The pilot accepts only principal/credential-generation-scoped `from_env()`
  SDKs and read-only host Plans composed of stable executable operation `run`
  nodes. Direct Products, Direct Bounded Composites, SDK-internal Plans,
  recipes, composites, SQL, metadata, receipts, arbitrary adapters and all
  mutations retain their existing owners; unsupported PAP preparation returns
  `PAP_UNSUPPORTED_PATH` before target calls.
- Prepare compiles the host source boundary and delegates the exact Plan to
  ordinary `execute_host_plan(..., dry_run=True)`, so structural validation,
  binding and every adapter preflight complete before an atomic artifact
  appears. Execute validates private state, replays that dry preflight and then
  re-enters `execute_host_plan`; it returns the ordinary Plan envelope without
  a PAP wrapper or changed request budget.
- Private `gravity.prepared-analysis-plan.v1` state contains only canonical
  Plan/referenced-source digests, selected operation catalog/contract and
  workspace catalog fingerprints, preflight fingerprint, bounded counts,
  worker budget and timestamps. It contains no raw Plan, source/input values,
  unused tool data, credentials, Scope digest, account identifier, user rows or
  condition-sensitive values. The public summary contains only opaque
  nonce-specific scoped `pap_id`, topology/count/budget and expiry timestamps.
- Store files have exact schema, canonical digest, regular-single-link/byte
  checks, atomic create, no mutation API, fixed count/total-byte limits and
  bounded TTL with valid expired-entry cleanup. Tests cover malformed/missing,
  content tamper, hardlink, expiry, capacity and failed-commit cleanup without
  leaving a visible partial artifact.
- Stable local reasons cover unbound scope, unsupported path, invalid reference,
  identity/credential-generation drift, missing/tampered/expired state,
  input/source/contract/catalog drift, invalid TTL/worker budget and store
  bounds. Source-control pollution still returns the existing
  `EFFECT_SOURCE_REJECTED`; all failures are value-free and occur before target
  calls.
- Characterization proves success, empty, upstream error, completeness,
  projection/privacy, target request values, one-target-call count and public
  envelope parity against direct `execute_host_plan`. The real installed SDK
  catalog also prepares `app.list` with `run` replaced by a fail-if-called
  sentinel, proving zero target requests rather than a fake-only path.
- Complete gates pass `1623` unittest; `1623 passed, 3833 subtests` pytest;
  compiler `237 operations / 11 manifests`; quality and all three generators
  PASS; integrated R11/Plan/Composite/scope/public/docs gates pass `65` tests
  and `13` subtests; actionable errors remain `1322 = 1157 A + 165 B + 0 C`;
  active human docs remain exactly `5500` lines.
- Development usability remains `296/336` selection, `248/248` fillability,
  `53/53` offline terminal and `5/5` recovery; security PASS and production
  HTTP requests `0`. No real credential, production/external request, mutation
  or release action was used; scope tests used local fake env files only.
- An isolated non-editable wheel loads both PAP schemas and the public service
  from `site-packages`, and its real offline catalog prepare passes; wheel
  SHA-256 is
  `6b6b430177de961bb330a904c62bbe554b10cad45eb064a8754a15ae8a3a914d`.
- Retained work-dashboard consumer `e4369ce8` has no PAP dependency. Its
  current-SDK adoption/R01 suite passes `11` tests and `94` subtests; the branch
  remains clean and no consumer migration or unrelated repair was required.

## Outcome

One characterized Plan-backed path can produce a private immutable Prepared Analysis Plan artifact that preserves source authority, validation, binding, preflight, execution, budgets and public envelopes.

## Current Baseline

The Runtime already supports direct products, Direct Composites, SDK-internal Plan and host-generated Plan with distinct source boundaries. There is no canonical PAP, and not every path needs one.

## Scope

- Characterize direct, composite, internal Plan and host-origin Plan behavior.
- Pilot PAP only for a selected Plan-backed path with proved equivalence.
- Bind source, identity, inputs, contract fingerprints, digest, expiry and stale checks privately.
- Expose only a safe PAP reference/summary.

## Non-goals

- No PAP for Direct Composite or every Runtime call.
- No new executor, binder or scheduler.
- No host source conversion into an SDK-internal source.

## Machine Contract

PAP is `gravity.prepared-analysis-plan.v1`, private and immutable. Host-origin execution re-enters the existing `execute_host_plan` boundary. Tamper, expiry, identity, contract or catalog drift returns stable reasons before execution.

## Migration And Compatibility

PAP is optional and additive. Current Plan calls remain canonical. It cannot become an MCP/Skill prerequisite or change current request counts, completeness, errors, privacy or output shape without a deliberate public migration.

## Safety And Operations

Private state excludes credentials and public Scope digests; storage is bounded and expires. Reuse never bypasses current authorization or preflight. Non-idempotent mutations remain outside the pilot unless separately governed.

## Acceptance

- Selected path has before/after characterization equivalence.
- Host-origin source isolation survives prepare and execute.
- Tamper/stale/expiry/identity drift fail before target calls.
- An unproved path stops at blocked without affecting other features.

## Verification

Topology characterization, digest/tamper/expiry, source authority, request/budget/completeness/error/privacy parity, checkpoint behavior and full gates.

## Rollback And Exit

Disable PAP and execute the existing source-aware path. Failed characterization closes the pilot without leaving a second public route.

## Canonical Owners

PAP schema/store, Plan reference, host source-boundary documentation and affected Journey evidence.
