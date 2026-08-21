# R14 Adaptive Request Governor And Execution Variants

| Field | Value |
| --- | --- |
| Parent directive | `gravity-agent-runtime/v9.1` via `directive.json` |
| Status | `specified` |
| Track | Runtime I/O optimization |
| Dependencies | R02 |
| Parallel group | `runtime-infrastructure` |
| Shared-spine integration | Required and serialized |

## Outcome

Runtime-owned network I/O shares one adaptive governance layer, and a Product/Journey may select among explicitly equivalent execution variants using Trust as a hard constraint and cost/latency as secondary objectives.

## Current Baseline

The Runtime already has a process-level Plan worker budget and shared Host Rate Limiter. Adapters borrow from one bounded pool, but there is no unified AIMD/circuit/backpressure policy or execution-variant registry.

## Delivery Mode

R14 is a `staged_epic`; no branch may implement all behavior at once:

```text
R14-A Governor Observation Mode
→ R14-B Adaptive Activation

R14-C Execution Variant Characterization

R14-B + R14-C
→ R14-D Automatic Selection
```

Every stage has a separate Issue, branch, commit, validation and rollback. R14-A changes no scheduling. R14-D cannot enter `ready` until both R14-B and R14-C are `fixed_dev`.

## Scope

- R14-A extends current instrumentation and records value-free host/operation latency, status and budget observations without changing scheduling.
- R14-B governs Runtime-owned Adapter, Composite, Plan, SQL Runtime and Artifact I/O with evidence-backed AIMD, circuit breaker, backpressure, single-flight and Journey fairness.
- R14-C defines variant semantics and proves at least one real Product has two equivalent fixed variants.
- R14-D adds explainable automatic selection with Trust as a hard gate and explicit pin/kill switch.

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

- **R14-A:** observed mode produces metrics but byte-for-byte equivalent scheduling/request count.
- **R14-B:** peak concurrency stays within one global budget, total request count stays `1x`, and 429/5xx/latency adaptation is deterministic under fake time.
- **R14-C:** fixed variants have equivalent output, completeness, DQ, claims, privacy and request semantics.
- **R14-D:** selection is explainable, pinnable, kill-switchable and rollback-safe; cost/latency cannot bypass Trust.
- Provider calls enter RPC budgets only in every stage.

## Verification

R14-A runs observation/no-behavior-change characterization. R14-B runs fake-clock concurrency/circuit/AIMD, request-count, lease/cancellation and fairness tests. R14-C runs the variant equivalence corpus. R14-D runs selection explanation/pin/rollback tests. Parent completion runs current transport regression and full gates.

## Rollback And Exit

Pin prior static policy and canonical variant. Automatic selection must have a kill switch that does not create another public execution path.

## Canonical Owners

Shared runtime/transport/Plan budget, Governor and variant schemas, performance policy reference and Journey evidence.
