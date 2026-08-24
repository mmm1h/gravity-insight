# R13C Gravity Dashboard Connector

| Field | Value |
| --- | --- |
| Parent directive | `gravity-agent-runtime/v9.1` via `directive.json` |
| Status | `in_progress`; internally approved 2026-08-24 |
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

## Rollback And Exit

Disable the connector while preserving Analysis Artifact and other renderers. Failed writes follow R12 uncertainty/readback policy.

## Canonical Owners

Dashboard compiler/connector, supported-subset reference, Action integration and Artifact-to-Dashboard Receipt evidence.
