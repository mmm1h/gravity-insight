# R12 Action, Experiment And Receipt Governance

| Field | Value |
| --- | --- |
| Parent directive | `gravity-agent-runtime/v9.1` via `directive.json` |
| Status | `specified` |
| Track | Governed action |
| Dependencies | R09A |
| Parallel group | `governed-action` |
| Shared-spine integration | Required and serialized |

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
