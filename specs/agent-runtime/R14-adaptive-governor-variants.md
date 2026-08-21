# R14 Adaptive Request Governor And Execution Variants

| Field | Value |
| --- | --- |
| Parent directive | `gravity-agent-runtime/v9` via `directive.json` |
| Status | `specified` |
| Track | Runtime I/O optimization |
| Dependencies | R02 |
| Parallel group | `runtime-infrastructure` |
| Shared-spine integration | Required and serialized |

## Outcome

Runtime-owned network I/O shares one adaptive governance layer, and a Product/Journey may select among explicitly equivalent execution variants using Trust as a hard constraint and cost/latency as secondary objectives.

## Current Baseline

The Runtime already has a process-level Plan worker budget and shared Host Rate Limiter. Adapters borrow from one bounded pool, but there is no unified AIMD/circuit/backpressure policy or execution-variant registry.

## Scope

- Extend, not duplicate, current global pool and Host limiter.
- Govern Runtime-owned Adapter, Composite, Plan, SQL Runtime and Artifact I/O.
- Add 429/5xx/latency feedback, AIMD, circuit breaker, backpressure, single-flight and Journey fairness where evidence supports them.
- Define variant semantics, characterization, fixed selection and explanation.
- Prove at least one real Product has two equivalent variants before enabling automatic selection.

## Non-goals

- No control of Provider-internal networking; R08 governs only RPC boundaries.
- No increase in total upstream requests, speculative retry or unproved parallel pagination.
- No automatic selection based only on fewer calls or lower latency.

## Machine Contract

Governor policy keys include host, operation class, identity scope and request budget. Variant contracts include input/output semantics, completeness, DQ, claims, privacy, freshness, request count and current Trust. Selection is explainable and can be pinned.

## Migration And Compatibility

Current fixed concurrency behavior is characterized first. Adaptive behavior starts disabled or in observation mode and uses fake-clock evidence before activation. Adapter-local pools are removed only after equivalent global control is proved.

## Safety And Operations

Circuit state and metrics contain no sensitive values. Retry behavior remains constrained by idempotency and current transport rules. Cancellation and backpressure release leases correctly.

## Acceptance

- Peak concurrency stays within one global budget and total request count stays `1x`.
- 429/5xx/latency cases adapt deterministically under fake time.
- Provider calls enter RPC budgets only.
- Variant output, completeness, claims and privacy are equivalent.
- Selection can be explained, fixed and rolled back.

## Verification

Fake-clock concurrency/circuit/AIMD tests, request-count assertions, lease/cancellation stress, fairness cases, variant characterization corpus, current transport regression and full gates.

## Rollback And Exit

Pin prior static policy and canonical variant. Automatic selection must have a kill switch that does not create another public execution path.

## Canonical Owners

Shared runtime/transport/Plan budget, Governor and variant schemas, performance policy reference and Journey evidence.
