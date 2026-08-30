# R13C Gravity Dashboard Connector

| Field | Value |
| --- | --- |
| Parent directive | `gravity-agent-runtime/v9.1` via `directive.json` |
| Status | `fixed_dev`; accepted on `dev@c7c5ba2f1615cc186ce7ba87a0deadc4e8e329e7` 2026-08-24 |
| Track | Governed Gravity delivery |
| Dependencies | R12-A, R13B |
| Parallel group | `dashboard-delivery` |
| Shared-spine integration | Required and serialized |
| Main integration | Frozen until whole program completion |
| Delivery ledger | This Requirement document; no internal GitHub Issue |
| Baseline | `dev@130cf8192c604bae461731872fd993ad8c92abb5` |
| Branch / worktree | `codex/r13c-dashboard-connector` / `D:\git-pjt\gravity-sdk-wt\r13c-dashboard-connector` |
| Production requests | `0`; fixture-only target validation |

## Outcome

A validated Analysis Artifact can be translated by a bounded Gravity Dashboard Connector into Preview, explicit confirmation, Execute and Readback without exposing raw Web configuration to a Skill or LLM.

## Plan Owner Verdict And Ready Binding

The user authorized continuous implementation of all indexed Requirements and
designated each Requirement document as the internal delivery ledger. With
R12-A and R13B already `fixed_dev`, the plan owner reviewed
`tmp/r13c-dashboard-connector-proposal.md` and its architecture conflict ledger,
bound this baseline/write scope/machine gates, and advanced R13C through
`reviewed` and `ready` to `in_progress`. This does not authorize production
probing, remote writes, release actions or `main` promotion.

- Add exactly one second closed R12 connector profile:
  `gravity.analysis-dashboard-notes@1`. Reuse the existing Action Plan store,
  authorization, confirmation, one-time plan/field claims and execution owner;
  do not build another executor or a generic connector/plugin registry.
- The request contains one validated `gravity.analysis-artifact.v1`, an exact
  App/space/Dashboard target and the only v1 presentation tuple:
  `markdown_notes + artifact_scope + single_column`. This explicit target choice
  does not infer or rewrite R13B's `unspecified` source visualization.
- Require successful/verified evidence, resolved versioned Metric/Dimension
  bindings, Workspace-resolved source App parity, paired ordered ISO dates,
  exact filters/claims and intact Result/snapshot/Receipt/Artifact digests.
- Reuse the R13B escaped Markdown renderer and split only complete lines into at
  most 20 notes of at most 4,000 characters. Any unsupported tuple, unresolved
  binding or representation overflow returns a stable gap without truncation.
- Delegate the only write and readback to the existing note-only Kanban owner.
  Extend that owner only with an internal expected-preimage assertion under its
  existing write lock. Existing direct Kanban and Segment behavior stays intact.
- Persist no Artifact content, target values or principal identifier: the
  private plan keeps fixed connector identifiers and exact request/principal/
  target/preimage/ownership/contract digests only. Execution evidence binds the
  source Artifact/rendering/Receipt set, target and verified note markers.
- Add explicit `gravity action dashboard-delivery preview|execute`; natural
  language remains unable to authorize or auto-execute. Acceptance includes
  closed-profile schema/tamper/stale/uncertain/concurrency tests, full gates,
  wheel and canonical consumer evidence with zero production HTTP.

## Current Baseline

The repository can replay selected persisted Dashboard charts and perform governed kanban mutations. R13B provides target-independent output, while R12-A provides the Action Plan/Reference Connector governance actually needed here; R12-B/C are not prerequisites.

## Scope

- Define supported visualization/filter/layout subset and deterministic target compilation.
- Validate Metric/Dimension identities, dates, filters, source bindings and claims.
- Produce an R12 Action Preview and exact readback assertions.
- Bind Analysis Artifact, target Dashboard and Receipt evidence.

## Non-goals

- No Dashboard UI, favourites, drag/drop or member permission management.
- No Skill/LLM-authored raw Gravity Web configuration.
- No dependency from R13A or R13B back to Dashboard availability.

## Machine Contract

Connector input is `gravity.analysis-artifact.v1`; output is an R12 governed plan. Unsupported visualization/layout returns a stable gap. Target compilation cannot alter source meaning or claims.

## Migration And Compatibility

Existing Dashboard replay remains a read path. Existing kanban mutations remain governed owners. The connector is a new explicit target adapter and does not repurpose either silently.

## Safety And Operations

User confirmation, ownership, preimage, managed fields, idempotency and readback follow R12. Target schema drift fails closed before mutation.

## Acceptance

- A supported R13B Artifact reaches Preview/Execute/Readback.
- Unsupported layout/visualization stops safely.
- Skill/LLM never sees or submits raw target configuration.
- Dashboard failure does not affect non-Gravity rendering or Artifact Transfer.

## Verification

Compiler fixtures, identity/filter/date validation, preview/execute/readback, ownership/stale/drift cases, Receipt binding, canonical consumer tests and full gates.

## Delivered Evidence

- Implementation `cc01de0acca911711313b3b5d9effeb1e3396e43` was merged as
  `dev@c7c5ba2f1615cc186ce7ba87a0deadc4e8e329e7`. The existing
  `ActionPlanService`, principal-scoped private store, plan/field claims and
  execution envelope now dispatch exactly two closed profiles; no second
  executor, store, dynamic registry, plugin import or compatibility path exists.
- `gravity.analysis-dashboard-request.v1` accepts only a complete Analysis
  Artifact, exact App/space/Dashboard IDs and the explicit
  `markdown_notes/artifact_scope/single_column` tuple. Full Artifact schema and
  self-digest, success/verified status, resolved versioned Metric/Dimension
  digests, Workspace App binding, paired ordered ISO dates, scope/filters,
  unique claims and Result/snapshot/Receipt bindings all fail closed before plan
  allocation. Raw `config`, `ui_config` and `report_list` are not request fields.
- The connector reuses R13B's escaped deterministic Markdown and rejects any
  indivisible line, more than 20 notes or more than 4,000 characters per note;
  it never truncates findings or claims. Public Preview exposes only counts and
  digests, while the private plan stores only fixed identifiers plus request,
  authorization, principal, target, preimage, ownership and contract digests.
- Existing `dashboard.notes.replace` remains the mutation/readback owner. Its
  only extension is an internal expected-preimage check under the existing
  write lock. Execution attempts at most one `dashboard.update`, checks exact
  ordered content-derived markers, and binds Artifact/Result/snapshot/filters/
  claims/rendering plus source and mutation Receipt references. Preimage drift
  is zero-write `stale`; post-write readback failure is `uncertain` with no retry.
- Stable unsupported reasons include visualization, filter mode, layout,
  Artifact status/integrity, Semantic/source/date binding, target kind and
  representation budgets. Report-bearing or foreign-owned Dashboards stop
  before plan creation. Same-preimage and concurrent plans retain atomic one-shot
  claims; crossed connector identity/managed-field and persisted-file tamper are
  rejected as `ACTION_PLAN_TAMPERED`.
- R13C focused coverage is `11 tests, 3 subtests`; merge-head Action/Kanban/
  audit/documentation coverage is `58 tests, 10 subtests`. Complete SDK gates
  passed `1696` unittest tests and `1696 passed, 3889 subtests passed` under
  pytest. Compiler remains `237 operations, 11 manifests`; quality, all three
  deterministic generators, root CLI help, diff checks and touched-file Ruff
  passed. Active human docs remain exactly `5500` lines.
- Actionable errors are `1335 = 1168 A + 167 B + 0 C`. Development usability
  remains selection `296/336`, fillability `248/248`, offline terminal `53/53`,
  recovery `5/5`, security violations `0`, skipped production cases `283` and
  production HTTP requests `0`.
- Isolated real wheel `gravity_insight-0.3.0-py3-none-any.whl` has SHA-256
  `89c5d6f048ac4991262562b112a558a911a14edf07344c72ed7a8895f1b23945`.
  From external `site-packages` it loaded the connector and Action alias, found
  the packaged request schema and parsed the new CLI resource. Canonical
  `work-dashboard@d1915a18278fca8823782a7d13e691a6d5702ad2` remains clean and
  passed `11 tests, 94 subtests`; no consumer migration was required.
- Production probes, target requests, remote writes, releases and `main`
  promotion performed by R13C: `0`.

## Known Limits

- v1 publishes complete Markdown only to an existing owned note-only Dashboard.
  It does not create a Dashboard, create a saved analysis, link reports or
  compose multiple writes; those paths would require a separately proven atomic
  owner rather than a compensating-write workflow.
- Supported scope fields are `app/start/end/timezone/filters`; other filter DSLs,
  chart visualizations, grid layouts, report-bearing targets and content beyond
  the exact note budget return stable gaps. Dashboard availability never affects
  Analysis Artifact, Markdown or Artifact Transfer.

## Rollback And Exit

Disable the connector while preserving Analysis Artifact and other renderers. Failed writes follow R12 uncertainty/readback policy.

## Canonical Owners

Dashboard compiler/connector, supported-subset reference, Action integration and Artifact-to-Dashboard Receipt evidence.
