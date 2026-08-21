# R12 Action, Experiment And Receipt Governance

| Field | Value |
| --- | --- |
| Parent directive | `gravity-agent-runtime/v9` via `directive.json` |
| Status | `specified` |
| Track | Governed action |
| Dependencies | R09 |
| Parallel group | `governed-action` |
| Shared-spine integration | Required and serialized |

## Outcome

Analysis can hand off a structured recommendation to a narrow governed Action Connector through Preview, explicit user confirmation, Execute, Readback and later Outcome Evaluation, with value-free Receipt evidence.

## Current Baseline

Registered Gravity mutations already support preview/dry-run, explicit execute and domain readback. There is no general Action Plan identity, managed-field ownership, experiment proposal or Skill/Context/Trust Receipt facet composition.

## Scope

- Select one narrow, owned, readback-capable action as the reference connector.
- Define Action Connector and immutable Action Plan contracts.
- Bind principal/workspace/credential generation, target preimage, owner, fields, expiry and contract privately.
- Add experiment proposal and outcome evaluation handoff.
- Add optional Receipt v1 facets without changing existing meanings.

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

- Preview and Execute bind the same authoritative input.
- User confirmation is required and cannot be replayed after stale conditions.
- Readback and ownership conflicts are machine-decidable.
- Receipt omits credentials, reversible account IDs, raw user rows and sensitive Context.
- Outcome evaluation uses a separate Journey/evidence window.

## Verification

Preview/execute parity, stale/preimage/owner/credential cases, idempotency boundaries, uncertain readback, privacy snapshots, Receipt compatibility, canonical consumer tests and full gates.

## Rollback And Exit

Disable the connector while retaining historical Receipt references. Expired plans are not migrated or retried. Existing direct governed mutations remain available.

## Canonical Owners

Action/Policy/Receipt schemas, selected mutation owner, action CLI/SDK reference, experiment guide and Journey evidence.
