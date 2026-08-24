# R14 Adaptive Request Governor And Execution Variants

| Field | Value |
| --- | --- |
| Parent directive | `gravity-agent-runtime/v9.1` via `directive.json` |
| Status | `in_progress`; R14-A `fixed_dev`, R14-B internally approved 2026-08-24 |
| Track | Runtime I/O optimization |
| Dependencies | R02 |
| Parallel group | `runtime-infrastructure` |
| Shared-spine integration | Required and serialized |
| Delivery ledger | This Requirement document; no internal GitHub Issue |
| Milestones | R14-A `fixed_dev`; R14-B `in_progress`; R14-C/D `specified` |
| R14-A baseline | `dev@fac2e6e1648bdf60efe1a1b369c9788058cdebed` |
| R14-A branch / worktree | `codex/r14a-governor-observation` / `D:\git-pjt\gravity-sdk-wt\r14a-governor-observation` |
| R14-B baseline | `dev@406c07b259ce89067dcb61f155115d87a8643db8` |
| R14-B branch / worktree | `codex/r14b-adaptive-governor` / `D:\git-pjt\gravity-sdk-wt\r14b-adaptive-governor` |
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

## R14-A Fixed Dev Evidence

- Feature `aaf363259ce9ad8b442ccb2f00bd541d2dad8597` was merged as
  `dev@7c3ae590d8c39995bde821ae0fec7284e4a9f9e1`. Observation wraps the
  existing `perform_http_request()` callable only after the canonical request
  counter increments; it does not change method/URL/headers/query/body/timeout,
  limiter reservation, semaphore acquisition, retry/auth refresh or request
  count. A fake-clock 503→200 workload produced identical serialized request
  bytes/order, two requests, sleeps and result under `disabled` and `observe`.
- `gravity.governor-observation.v1` records only SHA-256 host key, bounded
  operation/profile/method, response/transport outcome, status class/code,
  capped latency/rate delay, actual attempt/attempt budget and declared current
  24-business/two-SQL/timeout budgets. Tests cover 2xx, 4xx, 429, 5xx,
  transport error and retry attempts. URL/path/query/body/response/credential,
  principal and Runtime scope material are absent even for signed Artifact URLs.
- `gravity.governor-observation-snapshot.v1` uses private scope partitions,
  ascending non-skipping cursor pages, at most 4,096 observations and 64 scopes,
  explicit dropped/truncated/has-more state and `network_called=false`.
  `GravitySDK.governor.observations()` reuses the same environment Runtime
  closure and is lazy/cached; unbound direct SDKs fail with
  `GOVERNOR_SCOPE_UNBOUND` without constructing Insight or SQL.
- Durable `gravity.http-receipt.v1`, its retention/query/storage and all public
  result envelopes remain unchanged. Runtime-owned Artifact/blob HTTP enters a
  private process observation partition; R08 Provider RPC produces no Runtime
  HTTP observation and continues to report internal network as not observable.
- The existing Host Rate Limiter moved byte-for-byte into
  `host_rate_limiter.py` and remains re-exported from `http_runtime.py`.
  Existing limiter/cooldown/concurrency tests pass. This reduced
  `http_runtime.py` AST from `3643` to `2907` and requester complexity from
  `22` to `20`; the quality baseline was tightened rather than raised. The
  process 24/two semaphores, outer SQL two-slot guard and Plan reentrant worker
  budget were not removed or adapted. The Plan peak fixture now uses a
  deterministic first-wave barrier instead of timing-based `sleep` overlap.
- R14-A focused coverage is `11 tests, 6 subtests`; merge-head transport/Plan/
  scope/Provider/public/documentation coverage is `76 tests, 21 subtests`.
  Complete gates passed `1707` unittest tests and `1707 passed, 3895 subtests`
  under pytest. Compiler remains `237 operations, 11 manifests`; quality, all
  three deterministic generators, root CLI help, diff checks and touched-file
  Ruff passed. Public root exports are additive at `138` lazy entries / `139`
  `__all__` names. Active human docs remain exactly `5500` lines.
- Actionable errors are `1339 = 1172 A + 167 B + 0 C`. Development usability
  remains selection `296/336`, fillability `248/248`, offline terminal `53/53`,
  recovery `5/5`, security violations `0`, skipped production cases `283` and
  production HTTP requests `0`.
- Final isolated wheel `gravity_sdk-0.3.0-py3-none-any.whl` has SHA-256
  `ac48e6323530dbd9f14801df29eabc50e44c680c8a1f44ef3a81dee827f9e970`.
  External `site-packages` loaded all three root exports, both packaged schemas
  and validated an offline bounded snapshot. Canonical
  `work-dashboard@d1915a18278fca8823782a7d13e691a6d5702ad2` remains clean and
  passed `11 tests, 94 subtests`; no consumer migration was required.
- Production probes, external/provider calls, Runtime HTTP, remote writes,
  releases and `main` promotion performed by R14-A: `0`.

## R14-A Known Limits

- Observation history is process-local and in-memory; restart/disable clears or
  stops the baseline. R14-A reports declared static budgets but does not persist
  metrics or estimate active leases, queue depth, fairness or capacity policy.
- No observation changes scheduling. AIMD, circuit, backpressure, single-flight,
  cancellation-aware leases and Journey fairness belong only to R14-B. Variant
  contracts/characterization/selection remain R14-C/D and cannot consume
  latency as a Trust substitute.

## R14-B Plan Owner Verdict And Ready Binding

R14-A is `fixed_dev`. Under the user's continuous implementation authorization,
the plan owner reviewed `tmp/r14b-adaptive-governor-proposal.md` and its conflict
ledger, bound the baseline/worktree/gates, and advanced only R14-B through
`reviewed` and `ready` to `in_progress`. R14-C/D remain `specified`; this does
not authorize Variant selection, production probes, releases or `main`.

- Replace the process 24-business/two-SQL semaphores and duplicate SQL outer
  guard with one Governor hard capacity: 25 total, 24 business, SQL two and one
  login spare. Static rollback enforces these exact caps without adaptation.
- Adaptive lanes are private scope/host/operation/profile states. Deterministic
  AIMD increases after a full success window, halves on 429/5xx/transport and
  decreases on fixed slow latency; no policy adds a request or retry.
- Three consecutive capacity failures open a 30-second fake-clock circuit;
  half-open permits one probe. A 128-waiter cancellation-aware queue grants
  different waiting Plan Journey keys in rotation when possible.
- Adaptive-only single-flight shares only simultaneous exact private-digest
  effect=`read` successes. Mutations/login/Artifact streams never coalesce;
  failed leaders release followers to their normal request path.
- Only actual leaders increment the canonical HTTP counter and create HTTP
  Receipt/R14-A observation. Rejections and followers fabricate no evidence.
- Add a value-free current-scope adaptive snapshot and
  `sdk.governor.policy()`. Request/Journey keys, scope, URL/path and values stay
  private. Provider RPC remains wholly under R08.
- Bind Plan execution ID through a ContextVar only; Plan workers, adapter demand,
  result order, Host Rate Limiter and existing retry/auth behavior remain.
- Acceptance includes static cap equivalence, fake-clock AIMD/circuit, global
  peak/backpressure/cancellation/fairness, single-flight count/error semantics,
  Receipt/privacy/Provider, full gates, wheel and consumer with zero production
  HTTP. Active docs remain exactly 5,500 lines.

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
