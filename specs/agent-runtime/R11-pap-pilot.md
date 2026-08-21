# R11 Prepared Analysis Plan Pilot

| Field | Value |
| --- | --- |
| Parent directive | `gravity-agent-runtime/v9` via `directive.json` |
| Status | `specified` |
| Track | Optional Plan-backed optimization |
| Dependencies | R02 |
| Parallel group | `independent-pilot` |
| Shared-spine integration | Required and serialized |

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
