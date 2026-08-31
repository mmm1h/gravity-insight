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

A required source that is absent or cannot answer its claim makes the whole
dimension unmeasured: `measured=false` and `score=null`. The total is also null
until every dimension is measured. `measured_score` is only the subtotal of
measured dimensions; it is never normalized into an estimate for missing
dimensions. `score_upper_bound` adds the full unused weight only to show the
mathematical best case, not to award those points.

## Evidence commands

- `gravity journey certifications --json` checks each versioned Journey against
  its ledger binding, surfaces, execution mode, dependencies, Trust,
  Completeness, and Data Quality evidence.
- `gravity census status --json` reads the tracked baseline plus any current
  fetch-step and diff receipts. Without both current receipts, drift is
  unmeasured rather than assumed unchanged.
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
