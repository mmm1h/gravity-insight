# R02 Journey, Capability Trust And Data Quality Platform

| Field | Value |
| --- | --- |
| Parent directive | `gravity-agent-runtime/v9.1` via `directive.json` |
| Status | `fixed_dev`; accepted on `dev@4f78a0bf` 2026-08-22 |
| Track | Runtime trust platform |
| Dependencies | R01 |
| Parallel group | `platform-core` |
| Shared-spine integration | Required and serialized |
| Delivery ledger | This Requirement document; no internal GitHub Issue |
| Baseline | `dev@186235a77bf7b26d591c437597c314582283ba93` |
| Branch / worktree | `codex/r02-journey-trust-data-quality` / `D:\git-pjt\gravity-sdk-wt\r02-journey-trust-data-quality` |
| Consumer | `work-dashboard@322442c52c1adcb7584cff3065460de23b6d1d2b` -> `codex/r02-journey-trust-consumer` |
| Integrator | Root Codex agent; shared-spine wiring remains serial |
| Production requests | `0`; live evidence not authorized |

## Outcome

The contracts proved by R01 become reusable machine services for Journey `can-run`, same-layer Operation/Product/Composite trust, current Validation Results, Data Quality and dependency impact propagation.

## Plan Owner Verdict And Ready Binding

The user authorized continuous implementation of all indexed Requirements
without repeated per-Requirement approval. After R01 reached `fixed_dev`, the
plan owner reviewed `tmp/r02-journey-trust-data-quality-proposal.md` and its
architecture conflict ledger, bound the current baseline/write scope/machine
gates below, and advanced R02 through `reviewed` and `ready` to `in_progress`.
This does not authorize production probing, writes, release actions or `main`
promotion.

- The Markdown Journey ledger remains the rich human owner. A strict read-only
  parser preserves exact display/status/surface/budget/long-note fields; it
  never slugifies a display string into a permanent ID.
- Machine Journey contracts use explicit stable IDs and exact display bindings.
  The pilot matrix binds readable Apps, event trend, Business Pulse, R01, and
  one expected-blocked LTV Operator/Model gap.
- Stable Operation contracts are projected from compiled manifests. Product
  and Composite Trust contracts require checked-in same-layer artifacts; Agent
  cards or working child Operations cannot synthesize upper-layer Trust.
- Contract and current Validation are separate. Persisted Validation is read
  only from an environment-bound principal-scoped state root and binds identity,
  contract/provider fingerprint, evidence references, TTL, completeness, DQ
  and reason codes. Scope/account/credential digests never enter public output.
- Completeness remains `complete|prefix|unknown`; DQ remains
  `pass|warn|fail|unknown`. No row, HTTP, Markdown or child-layer inference may
  promote either.
- Public targets are `gravity journey list|verify|describe|can-run|impact|run`,
  `gravity capabilities trust|validate|impact`, reusable `JourneyService` and
  `CapabilityTrustService`, with the R01 execution owner unchanged.
- The R01-named public service export may be replaced directly by the generic
  service in the same consumer/public-snapshot migration; no compatibility
  alias or parallel Trust implementation is retained.
- Exact acceptance includes parser/format/digest, same-layer identity, TTL,
  drift/quarantine, DQ aggregation, impact, identity isolation, zero-network,
  R01 parity, public snapshot, real-wheel, canonical consumer, full repository
  gates and development usability evaluation.

## Current Baseline

Current contracts express operation stability, pagination completeness/evidence, semantic status, allowed claims and product component failures. The Markdown Journey ledger and usability eval are authoritative current evidence, but no unified machine Trust/DQ plane exists.

## Scope

- Parse or project the current Journey ledger without losing display identity or long notes.
- Add versioned Journey Contracts and stable display binding.
- Define Capability stable contract separately from current Validation Result and TTL.
- Give Operation, Product and Composite their own trust/completeness/quality/claim authority.
- Aggregate Data Quality and dependency impact without automatic production probes.
- Provide offline `can-run` and impact queries.
- Migrate the R01 Product Trust and Journey gate to the reusable services while
  retaining its project Semantic, Operator, Skill, Context, Analysis Result and
  existing playbook execution owner.
- Project Operation contracts from current manifests and add only the explicit
  Product/Composite contracts exercised by the pilot matrix.

## Non-goals

- No Skill package distribution, Context Provider, business formula registry or model execution.
- No automatic semantic inference or promotion from HTTP success.
- No blanket live probing to make status green.

## Machine Contract

`lifecycle = active|deprecated|revoked` is separate from `trust_status = stable|unknown|degraded|blocked|quarantined`. Journey `can_run_status = verified|unknown|blocked|invalid`; capability gaps are structured reasons, not statuses. Validation binds provider fingerprint, identity class, evidence references and expiry.

The first machine Journey bindings are:

```text
analysis.readable-app-catalog
analysis.event-trend
analysis.business-pulse
analysis.merge2.ap-cost-anomaly-localization
analysis.ltv-curve-fit
```

`analysis.ltv-curve-fit` is intentionally expected to remain blocked until its
Semantic/Operator/Model requirements are supplied by later Requirements.
`verified=0` is a valid current matrix outcome.

## Migration And Compatibility

The Markdown ledger remains the rich human owner until an explicit later migration. Machine contracts cannot contradict it silently. Existing completeness strings stay `complete|prefix|unknown`; no nested status or `not_applicable` is introduced.

The public migration is direct: `GravitySDK.journeys` becomes the reusable
service, R01 CLI/SDK envelopes and exit codes remain behaviorally equivalent,
and canonical consumer/current references migrate in the same unit. No second
router, executor, binder, Plan adapter, pagination or permission owner is added.

## Safety And Operations

Default evaluation is offline and makes zero target requests. Cache keys include environment, principal, credential generation, workspace, provider fingerprint and contract version. Quarantine and revocation fail closed.

An SDK facade without an environment-bound Runtime scope may evaluate static
contracts but cannot consume persisted current Validation. Runtime scope keys,
account material, credential generations and private storage paths are never
rendered publicly.

## Acceptance

- Operation/Product/Composite same-layer trust cannot be inherited across layers.
- Stale, drifted, incomplete and DQ-failed dependencies propagate stable reasons.
- `verified=0` is valid when evidence is insufficient.
- Impact output names affected Skill/Journey identities without executing them.
- Current public envelope and request volume do not regress.
- Ledger rows with inline-code pipes and long notes round-trip without field
  loss; duplicate/malformed rows fail the format gate.
- Impact names transitively affected Capability, Skill and Journey identities
  without probing or executing them.
- The current R01 Journey remains
  `blocked/COMPLETENESS_INSUFFICIENT/network_called=false`.

## Verification

Parser/format gates, fake-clock TTL tests, drift/quarantine tests, Product/Composite aggregation, identity isolation, zero-network invalid cases, public snapshots, all repository gates and usability eval.

## Delivered Evidence

- Implementation `b6f435674fce85d3ec2088e063e464699347d872` was merged as
  `dev@4f78a0bfad146e0fb5bd35a6bbb61fef480a453a`. The five pilot
  Journey contracts verify against all 63 human-ledger rows; the current matrix
  is `verified=0`, with readable Apps `unknown` and the other four Journeys
  honestly blocked.
- R01 migrated to the generic Capability contract, Trust service and DQ result;
  the former R01-only Trust artifact/evaluator were removed. Its real consumer
  result remains exit `4`, `blocked/COMPLETENESS_INSUFFICIENT`, empty findings
  and claims, and `network_called=false`.
- Complete SDK gates: `1449` unittest tests; `1449 passed, 3674 subtests passed`
  under pytest; compiler `237 operations, 11 manifests`; quality PASS with
  `237` provenance records; Journey snapshot, CLI help and diff checks PASS.
- Actionable errors are fully classified at `1290 = 1126 A + 164 B + 0 C`.
  Development usability remains selection `296/336`, fillability `248/248`,
  offline terminal `53/53`, recovery `5/5`, security PASS and production HTTP
  requests `0`.
- Isolated real wheel `gravity_sdk-0.3.0-py3-none-any.whl` has SHA-256
  `8d368ac42df17a9a6a0e5dc4a8e44e1d9b4913a1f71e2e4379b91bcf3458d3a2`.
  It imported from isolated `site-packages`, loaded packaged Journey/Capability
  contracts, verified the registry, evaluated Trust, and preserved R01 exit 4
  from outside the checkout.
- Canonical consumer `codex/r02-journey-trust-consumer@6b94d3d3955646aad4776688e9f99d693e06e20c`
  passes focused adoption/R02 (`10 passed, 94 subtests`), its complete business
  suite (`304 tests`, one policy skip), tracked privacy and GM privacy (`10
  passed`). Its complete governance command still reports only unrelated
  baseline defects: two missing historical assets, one GM SQL provenance drift,
  one expired topic exception and one frozen historical missing link.
- Production probes, target requests, Validation writes, releases and `main`
  promotion performed by R02: `0`.

## Rollback And Exit

Trust projection can be disabled only by returning the prior surface plus an explicit unavailable gap; it cannot silently assume stable. Temporary ledger adapters need an owner and removal condition.

## Canonical Owners

Journey contract artifacts, Capability validation artifacts, roadmap decision, Journey ledger state and relevant CLI/SDK reference.
