# R12 Action, Experiment And Receipt Governance

| Field | Value |
| --- | --- |
| Parent directive | `gravity-agent-runtime/v9.1` via `directive.json` |
| Status | `in_progress`; R12-A plan-owner ready binding accepted 2026-08-22 |
| Track | Governed action |
| Dependencies | R09A |
| Parallel group | `governed-action` |
| Shared-spine integration | Required and serialized |
| Delivery ledger | This Requirement document; no internal GitHub Issue |
| Active milestone | `R12-A` (`in_progress`); R12-B/C remain `specified` |
| R12-A baseline | `dev@3a47ce9f48902313c7898a0ab632c58d4c29259b` |
| R12-A branch / worktree | `codex/r12a-action-plan-reference-connector` / `D:\\git-pjt\\gravity-sdk-wt\\r12a-action-plan-reference-connector` |
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
