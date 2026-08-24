# R14 Adaptive Request Governor And Execution Variants

| Field | Value |
| --- | --- |
| Parent directive | `gravity-agent-runtime/v9.1` via `directive.json` |
| Status | `in_progress`; R14-A internally approved 2026-08-24 |
| Track | Runtime I/O optimization |
| Dependencies | R02 |
| Parallel group | `runtime-infrastructure` |
| Shared-spine integration | Required and serialized |
| Delivery ledger | This Requirement document; no internal GitHub Issue |
| Milestones | R14-A `in_progress`; R14-B/C/D `specified` |
| R14-A baseline | `dev@fac2e6e1648bdf60efe1a1b369c9788058cdebed` |
| R14-A branch / worktree | `codex/r14a-governor-observation` / `D:\git-pjt\gravity-sdk-wt\r14a-governor-observation` |
| Production requests | `0`; fake Runtime HTTP only |
| Main integration | Frozen until whole program completion |

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

## R14-A Plan Owner Verdict And Ready Binding

The user designated this Requirement as the staged delivery ledger and
authorized continuous implementation without repeated approval. With R02
already `fixed_dev`, the plan owner reviewed
`tmp/r14a-governor-observation-proposal.md` and its architecture conflict ledger,
bound the baseline/worktree/gates, and advanced only R14-A through `reviewed`
and `ready` to `in_progress`. R14-B/C/D remain `specified`. This does not
authorize production probing, adaptive scheduling, Variant selection, release
or `main` promotion.

- Observe at the existing `perform_http_request()` count boundary after policy
  authorization. Record one bounded value-free attempt without extra request,
  retry, wait, lease, argument mutation or alternate transport.
- Partition an in-memory recorder by the existing private Runtime scope. Expose
  only hashed host, operation/profile/method, status/outcome, capped latency and
  rate delay, attempts and declared current budgets; never expose path, URL,
  request/response values, credentials, principal or scope digest.
- Preserve the fixed Host Rate Limiter, 24 business/two SQL Runtime semaphores,
  outer SQL two-slot guard, Plan worker/borrow budget, auth refresh and retry
  behavior exactly. R14-A adds no AIMD, circuit, backpressure, single-flight,
  fairness or adaptive decision.
- Keep durable HTTP Receipt v1 unchanged. Add separate observation/snapshot
  schemas, 4,096 observations per scope, at most 64 scopes, bounded ascending
  query with explicit dropped/truncated state, and observe/disabled policy mode.
- Add lazy `GravitySDK.governor.observations()` over the same bound runtime.
  Direct SDKs without that binding fail locally; query performs no network.
- Runtime-owned Artifact/blob HTTP is observed in a private process partition.
  R08 Provider RPC and Provider-internal network remain outside the Runtime HTTP
  Governor and retain their own budgets.
- Acceptance requires byte/count/order-equivalent disabled/observe traces,
  status/retry/budget/privacy/scope/bound tests, current transport/SQL/Plan/
  Receipt/multi-account regressions, full gates, wheel and canonical consumer,
  with zero production HTTP. Active human docs remain exactly 5,500 lines.

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
