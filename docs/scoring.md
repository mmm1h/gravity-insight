# Maturity scoring

`gravity maturity score --json` calculates requirement 2.1 from the current
checkout and Runtime artifacts. It does not accept hand-entered scores. Every
dimension contains its fixed maximum, measured state, evidence records, and the
actual numerator and denominator used by the formula `max * passed / total`.

The fixed maxima are 20 for correctness/Trust/Completeness/surface parity, 15
for Journey and Agent value, 15 for Skill/Semantic/Operator/Context maturity,
and 10 each for upstream operations, performance/governance/observability,
CI/release/security/supply chain, architecture/developer efficiency/token
economy, and documentation/information architecture.

A required source that cannot answer its claim keeps the whole dimension at
`measured=false` and `score=null`, but the reason is not collapsed to one
"unmeasured" state. Context-bound sources use
`gravity.context-bound-measurement.v1` with `value`, `coordinate`, `scope`,
`captured_at`, and `binds_to`. Their consumer must pass an expected coordinate,
scope, and binding to the shared resolver. Each object is matched exactly, so a
producer cannot add a context field that an older consumer silently ignores. The resulting
`gravity.measurement-resolution.v1` status is one of `measured`, `not_measured`,
`expired`, `not_applicable`, or `invalid`; a mismatch includes typed field-level
`mismatches` and `MEASUREMENT_CONTEXT_MISMATCH` instead of becoming missing.

Each dimension exposes that unavailable status alongside the existing boolean.
Its evidence record carries the full measurement resolution. The total is also
null until every dimension is measured. `measured_score` is only the subtotal
of measured dimensions; it is never normalized into an estimate for missing
dimensions. `score_upper_bound` adds the full unused weight only to show the
mathematical best case, not to award those points. The maturity result's
`repository.measurement` binds the score to the exact commit, clean/dirty state,
branch, completion-time capture, and worktree root so equal numbers from different
worktrees are not context-free.

The isolated quality collector also exposes a `repository.quality_profile` receipt:
`measurement` is the captured context-bound profile (or null), `resolution`
uses the shared five-state vocabulary, and `collection_failure` explains a
failed launch, timeout, nonzero exit, or missing/malformed stdout. A collection
failure is `not_measured` with `MEASUREMENT_NOT_CAPTURED`, not a measured zero.
The affected dimensions and total keep null scores. Process exit zero alone
does not certify a complete maturity measurement; consumers must inspect the
measurement states and blocking gates.

## Evidence commands

- `gravity journey certifications --json` checks each versioned Journey against
  its ledger binding, surfaces, execution mode, dependencies, Trust,
  Completeness, and Data Quality evidence.
- `gravity census status --json` reads the tracked baseline plus any current
  fetch-step and diff receipts. No evidence is `not_measured`; a complete chain
  beyond its TTL is `expired`; a chain bound to another baseline is
  `not_applicable`; malformed or future-dated context is `invalid`. None is
  assumed unchanged, and all continue to fail the blocking gate.
- `gravity runtime health --json` checks contracts, registries, route accounting,
  and built-in Provider reachability without network access.
- `gravity docs check --json` checks local links, orphan documents, current CLI
  command references, navigation owners, and the existing documentation gate.

Metrics marked `proxy_metric=true` state their limitation in the same evidence
record. Offline Agent cases proxy real Journey usability but retain
production-skipped cases in the applicable denominators. Request budgets and
tool-call observations proxy bounded cost; they do not measure model tokens or
production latency. Static complexity and ownership pointers proxy
maintainability; they do not measure engineering lead time.

`runtime health` and the established documentation gate are invoked by
`python -m gravity_insight.quality check`, so regressions fail the existing
quality path rather than creating a second validation framework.

Integrated Validation writes the same context-bound shape into its receipt.
Maturity scans available receipt candidates and resolves them against the
expected clean, non-trial, complete-gate-set exact HEAD. A receipt for an older
HEAD is therefore observable as `not_applicable`, while an empty receipt store
is `not_measured`; a legacy or malformed receipt without self-carried context is
`invalid` rather than reconstructed from ambient state.

Tests follow the same rule: assertions about a context-dependent measurement
construct the coordinate explicitly or assert an invariant. They do not freeze a
claim about whichever release, branch, clock, or environment happens to be current.
