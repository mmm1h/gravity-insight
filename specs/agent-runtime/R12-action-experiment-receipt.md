# R12 Action, Experiment And Receipt Governance

| Field | Value |
| --- | --- |
| Parent directive | `gravity-agent-runtime/v9.1` via `directive.json` |
| Status | `in_progress`; R12-A `fixed_dev`, R12-B started 2026-08-22, R12-C `specified` |
| Track | Governed action |
| Dependencies | R09A |
| Parallel group | `governed-action` |
| Shared-spine integration | Required and serialized |
| Delivery ledger | This Requirement document; no internal GitHub Issue |
| Milestones | R12-A `fixed_dev`; R12-B `in_progress`; R12-C `specified` |
| R12-A baseline | `dev@3a47ce9f48902313c7898a0ab632c58d4c29259b` |
| R12-A branch / worktree | `codex/r12a-action-plan-reference-connector` / `D:\\git-pjt\\gravity-sdk-wt\\r12a-action-plan-reference-connector` |
| R12-B baseline | `dev@7e6c190c4e527579ce772261b947c79c5dcb4d45` |
| R12-B branch / worktree | `codex/r12b-receipt-v1-additive-facets` / `D:\\git-pjt\\gravity-sdk-wt\\r12b-receipt-v1-additive-facets` |
| Consumer | Retained R09A stack `work-dashboard@e4369ce8`; non-regression only |
| Integrator | Root Codex agent; shared-spine wiring remains serial |
| Production / external requests / mutations | `0`; injected local fixtures only |
| Main integration | Frozen until whole program completion |

## R12-A Plan Owner Verdict And Ready Binding

The user designated the Requirement as the internal staged-epic ledger and
authorized continuous implementation without repeated approval. R09A is
`fixed_dev`; the plan owner reviewed
`tmp/r12a-action-plan-reference-connector-proposal.md` and its conflict ledger,
bound the baseline/worktree/gates below, advanced only R12-A through `reviewed`
and `ready`, and started it as `in_progress`. R12-B/C remain `specified`. This
does not authorize real credentials, production/external requests, mutation,
package installation, release or `main` promotion.

- Select exact-detail `segment.update_metadata` as the only reference connector.
  Its current owner already provides marker-or-principal ownership, two closed
  managed fields, one-shot mutation and exact name/remark readback. Do not use
  segment create because current catalog completeness cannot prove absence.
- Preview requires a principal-scoped `from_env()` SDK and exact current
  user/authorization source. It resolves current principal, reads exact detail,
  applies the existing owner gate and binds request, target, preimage, owner,
  managed fields, operation contracts and expiry before private state appears;
  no mutation is sent.
- Persist only one-way request/authorization/principal/target/preimage/owner/
  contract digests, managed-field names and timestamps. Never persist raw
  request values, credentials, Scope digest, reversible account identity, user
  rows or sensitive Context. Public plan output is an opaque ID plus safe
  confirmation summary, fingerprint and `require_confirmation` decision.
- Execute requires the exact request plus a second current
  user/authorization confirmation binding plan ID/fingerprint. Revalidate all
  bindings, then atomically claim the immutable plan once before delegating to
  the existing Segment owner. Confirmation replay and automatic retry are
  forbidden.
- Add only an internal expected-preimage digest to
  `update_segment_metadata`; it runs under the existing Segment write lock
  after current detail/ownership resolution and before `_execute_mutation`.
  The connector does not send writes or rebuild owner/readback behavior.
- Pre-write drift returns stable deny/stale reasons and zero mutations. Any
  failure after the owner attempts a write returns a safe `uncertain` execution
  with `automatic_retry=false`; success requires exact managed-field and
  ownership readback.
- Add narrow `GravitySDK.actions`, one root service export and explicit
  `gravity action segment-update preview|execute`. Existing direct mutation
  SDK/CLI/Plan surfaces remain canonical and available; no natural-language
  execution, connector registry/marketplace, R12-B Receipt facet or R12-C
  Experiment/Outcome surface is added.
- Acceptance covers authorization/confirmation authority, exact parity,
  principal/credential, expiry/replay, input/target/preimage/owner/contract/
  managed-field drift, one mutation maximum, uncertain readback, strict private
  state/privacy/bounds, installed wheel, full repository/usability/security and
  retained consumer gates. Active human docs remain exactly 5500 lines.

## R12-A Fixed Dev Evidence

- Feature commit `f6a313c` and merge `ba404f8` add eight strict Action request,
  authorization, confirmation, public/private plan, claim, execution and Policy
  schemas; one `ActionPlanService`; lazy `GravitySDK.actions`; one root export;
  and explicit `gravity action segment-update preview|execute`. Root public API
  now has `129` lazy exports and `gravity_sdk.__all__` has `130` entries including
  `__version__`. No connector discovery/registry, Agent card, Skill permission,
  arbitrary tool/URL/operation, Plan node kind or second mutation executor exists.
- The only connector is `gravity.segment-metadata-update@1`. Segment create was
  rejected as the pilot because current paginated catalog evidence cannot prove
  global absence. Metadata update instead binds exact detail identity/App,
  name/remark, owner/update fields, status/timestamps and current contract; the
  existing GSDK-marker-or-principal owner remains authoritative.
- Preview requires an exact current `user/authorization` source whose value
  contains the same `gravity.segment-metadata-update-request.v1`. It resolves
  the current principal, reads exact detail once, applies the existing ownership
  gate and sends zero mutations. Tool result, user instruction, Skill, Context
  and history sources are rejected before detail reads or private state.
- Private `gravity.action-plan-private.v1` contains only request,
  authorization, principal, target, preimage, ownership and operation-contract
  digests; fixed managed-field names, connector identity, timestamps,
  fingerprint and artifact digest. It contains no raw old/new name or remark,
  owner name/ID, credential, Scope digest, user row or Context. Public
  `gravity.action-plan.v1` exposes only opaque plan identity, safe target/change/
  ownership/readback summary, expiry, preview fingerprint and
  `require_confirmation` Policy Decision.
- Execute requires the exact request again plus a second current
  `user/authorization` source binding `plan_id`, `preview_fingerprint` and
  `confirmed=true`. Identity/input/target/contract/expiry checks precede atomic
  O_EXCL plan and `(target,preimage,managed_fields)` claims. Same-plan replay and
  two plans from one preimage are rejected; a new explicitly authorized plan
  from a verified changed preimage remains possible.
- `update_segment_metadata` gained only an internal expected-preimage digest.
  It still owns detail/ownership resolution, request preview, `_execute_mutation`
  and name/remark readback under its original process write lock; the digest is
  compared after current ownership and before the single mutation call. All
  direct Segment and other mutation-family SDK/CLI/Plan paths remain unchanged.
- Stable pre-write reasons cover missing/non-user authorization or confirmation,
  unbound/changed principal scope, malformed/missing/tampered/expired/consumed
  plan, input/target/owner/contract change, field claim, TTL and store bounds.
  Stale outcomes send zero mutations. Any exception after `_execute_mutation`
  was attempted returns `gravity.action-execution.v1 status=uncertain`, preserves
  safe Receipt references when present, fixes `automatic_retry=false`, consumes
  the plan and cannot fabricate success.
- Success requires exactly one write attempt plus existing exact name/remark
  readback and marker/upstream-owner assertion. The public execution result
  contains only safe target identity, verified assertion IDs, Policy Decision
  and opaque Receipt references; it does not copy the direct mutation envelope.
- The upstream Segment save route has no revision/ETag/CAS. The public preview
  therefore declares `upstream_revision_unavailable`: same-scope duplicate
  plans are field-claimed and current detail is checked immediately under the
  owner lock, but an external change after that last read can only be detected
  by readback and yields `uncertain`; no stronger atomicity is claimed.
- Complete gates pass `1641` unittest; `1641 passed, 3840 subtests` pytest;
  compiler `237 operations / 11 manifests`; quality and all three generators
  PASS; integrated Action/Segment/all mutation/public/docs gates pass `66` tests
  and `9` subtests; actionable errors remain
  `1330 = 1163 A + 167 B + 0 C`; active human docs remain exactly `5500` lines.
- Development usability remains `296/336` selection, `248/248` fillability,
  `53/53` offline terminal and `5/5` recovery; security PASS and production HTTP
  requests `0`. All mutation tests used injected local fixtures; no real
  credential, external request or production mutation was used.
- An isolated non-editable wheel loads `ActionPlanService`, all eight schemas
  and the Action CLI from `site-packages`; wheel SHA-256 is
  `e6f40a434a968da09a1c1cffbd2fee986ac04ae5057f606cce028d1af71a8932`.
- Retained work-dashboard consumer `e4369ce8` has no Action Plan dependency. Its
  current-SDK adoption/R01 suite passes `11` tests and `94` subtests; the branch
  remains clean and no consumer migration or unrelated repair was required.

## R12-B Plan Owner Verdict And Ready Binding

The R12-A dependency is `fixed_dev`. Under the user's continuous implementation
authorization, the plan owner reviewed
`tmp/r12b-receipt-v1-additive-facets-proposal.md` and its conflict ledger,
characterized the current Receipt owner and canonical consumer, bound the
baseline/worktree/gates below, advanced only R12-B through `reviewed` and
`ready`, and started it as `in_progress`. R12-C remains `specified`. This does
not authorize credentials, production/external requests, mutation, package
installation, release or `main` promotion.

- Keep `gravity.receipt.v1`, its existing base fields, resolver `_finish`
  construction/persistence owner and separate `gravity.http-receipt.v1` /
  `receipt_references` contracts. With no optional facet, the public resolver
  mapping and stored JSON must retain the exact pre-R12-B shape.
- Add only strict optional top-level `run`, `skill`, `journey`, `capability`,
  `semantics`, `operator_model`, `context`, `pagination`, `data_quality`,
  `policy` and `action` facets. Preserve the R06 `operator_model` keyword and
  reject ambiguous duplicate supply; do not add a generic extension bag or v2.
- A narrow compiler may project facets only from validated execution snapshots,
  Context Packs, Data Quality Results, Policy Decisions and Action results. It
  cannot select/execute a Product, recompute readiness/authorization/readback or
  create a second store.
- Persist only controlled identities, versions, digests, statuses, reason/check
  codes, completeness/evidence and Action readback assertion IDs. Omit request/
  output values, credentials, Scope/principal/account material, raw user rows,
  Context content/title/citation/path and Action target/preimage/owner/
  confirmation.
- Keep Capability/Semantic/Context ordering deterministic and array bounds
  explicit. Unknown facets, malformed/duplicate references, tampered source
  digests and non-canonical inputs fail before Receipt persistence.
- No new CLI/SDK execution surface, telemetry service, signature, external
  audit store, MCP or R12-C Experiment/Outcome contract enters this milestone.
- Acceptance covers exact old-shape/persistence parity, all facets separately
  and together, R06 compatibility, tamper/privacy/defensive-copy/schema/wheel
  gates, complete repository/usability/security checks and the retained clean
  `work-dashboard@e4369ce8` current-SDK suite. Production HTTP remains `0` and
  active human docs remain exactly `5500` lines.

## Outcome

Analysis can hand off a structured recommendation to a narrow governed Action Connector through Preview, explicit user confirmation, Execute, Readback and later Outcome Evaluation, with value-free Receipt evidence.

## Current Baseline

Registered Gravity mutations already support preview/dry-run, explicit execute and domain readback. There is no general Action Plan identity, managed-field ownership, experiment proposal or Skill/Context/Trust Receipt facet composition.

## Delivery Mode

R12 is a `staged_epic`, not one implementation branch. Each stage has a separate Issue, `codex/<unit>` branch, commit, validation record and rollback:

```text
R12-A Action Plan + Reference Connector
→ R12-B Receipt v1 Additive Facets
→ R12-C Experiment Proposal / Outcome Handoff
```

R12-B cannot enter `ready` before R12-A is `fixed_dev`; R12-C cannot enter `ready` before R12-B is `fixed_dev`. The parent reaches `fixed_dev` only after all three stages pass integrated validation.

## Scope

- R12-A selects one narrow readback-capable action, defines Connector/Plan, and binds identity, preimage, owner, fields and expiry.
- R12-B adds optional Receipt v1 Skill/Context/Trust/Policy/Action facets without changing existing meanings.
- R12-C adds Experiment Proposal and separate Outcome Evaluation handoff.

## Non-goals

- No natural-language write, broad connector marketplace or arbitrary external tool execution.
- No automatic non-idempotent retry.
- No recommendation self-approval or same-run outcome self-validation.

## Machine Contract

Public plan output contains only ID and safe confirmation summary. Internal state is exact and immutable. Policy decisions are `allow|deny|require_confirmation` with stable reasons. Stale identity, target, owner or contract blocks execution.

## Migration And Compatibility

The connector delegates current mutation owners; it does not wrap away their policy or readback. Receipt remains `gravity.receipt.v1` with additive optional facets. Canonical consumers migrate with any public shape changes.

## Safety And Operations

Only current explicit user input supplies destination, mutation permission and execute confirmation. Skill, Context, tool output and history are data. Success requires readback; uncertainty remains `uncertain`.

## Acceptance

- **R12-A:** Preview and Execute bind the same authoritative input; confirmation cannot replay after stale conditions; readback/ownership conflicts are machine-decidable.
- **R12-B:** additive facets preserve old consumer behavior and omit credentials, reversible account IDs, raw user rows and sensitive Context.
- **R12-C:** Experiment Proposal is proposal-only until power/metric/guardrail dependencies pass; Outcome Evaluation uses a separate Journey/evidence window.
- Every stage can be rolled back without removing completed earlier-stage behavior.

## Verification

R12-A runs preview/execute parity, stale/preimage/owner/credential, idempotency and uncertain-readback tests. R12-B runs Receipt privacy/compatibility and canonical consumer tests. R12-C runs proposal/evidence-window and no-self-validation tests. Each stage runs affected gates; parent completion runs full gates.

## Rollback And Exit

Disable the connector while retaining historical Receipt references. Expired plans are not migrated or retried. Existing direct governed mutations remain available.

## Canonical Owners

Action/Policy/Receipt schemas, selected mutation owner, action CLI/SDK reference, experiment guide and Journey evidence.
