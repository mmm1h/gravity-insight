# R02 Journey, Capability Trust And Data Quality Platform

| Field | Value |
| --- | --- |
| Parent directive | `gravity-agent-runtime/v9.1` via `directive.json` |
| Status | `specified` |
| Track | Runtime trust platform |
| Dependencies | R01 |
| Parallel group | `platform-core` |
| Shared-spine integration | Required and serialized |

## Outcome

The contracts proved by R01 become reusable machine services for Journey `can-run`, same-layer Operation/Product/Composite trust, current Validation Results, Data Quality and dependency impact propagation.

## Current Baseline

Current contracts express operation stability, pagination completeness/evidence, semantic status, allowed claims and product component failures. The Markdown Journey ledger and usability eval are authoritative current evidence, but no unified machine Trust/DQ plane exists.

## Scope

- Parse or project the current Journey ledger without losing display identity or long notes.
- Add versioned Journey Contracts and stable display binding.
- Define Capability stable contract separately from current Validation Result and TTL.
- Give Operation, Product and Composite their own trust/completeness/quality/claim authority.
- Aggregate Data Quality and dependency impact without automatic production probes.
- Provide offline `can-run` and impact queries.

## Non-goals

- No Skill package distribution, Context Provider, business formula registry or model execution.
- No automatic semantic inference or promotion from HTTP success.
- No blanket live probing to make status green.

## Machine Contract

`lifecycle = active|deprecated|revoked` is separate from `trust_status = stable|unknown|degraded|blocked|quarantined`. Journey `can_run_status = verified|unknown|blocked|invalid`; capability gaps are structured reasons, not statuses. Validation binds provider fingerprint, identity class, evidence references and expiry.

## Migration And Compatibility

The Markdown ledger remains the rich human owner until an explicit later migration. Machine contracts cannot contradict it silently. Existing completeness strings stay `complete|prefix|unknown`; no nested status or `not_applicable` is introduced.

## Safety And Operations

Default evaluation is offline and makes zero target requests. Cache keys include environment, principal, credential generation, workspace, provider fingerprint and contract version. Quarantine and revocation fail closed.

## Acceptance

- Operation/Product/Composite same-layer trust cannot be inherited across layers.
- Stale, drifted, incomplete and DQ-failed dependencies propagate stable reasons.
- `verified=0` is valid when evidence is insufficient.
- Impact output names affected Skill/Journey identities without executing them.
- Current public envelope and request volume do not regress.

## Verification

Parser/format gates, fake-clock TTL tests, drift/quarantine tests, Product/Composite aggregation, identity isolation, zero-network invalid cases, public snapshots, all repository gates and usability eval.

## Rollback And Exit

Trust projection can be disabled only by returning the prior surface plus an explicit unavailable gap; it cannot silently assume stable. Temporary ledger adapters need an owner and removal condition.

## Canonical Owners

Journey contract artifacts, Capability validation artifacts, roadmap decision, Journey ledger state and relevant CLI/SDK reference.
