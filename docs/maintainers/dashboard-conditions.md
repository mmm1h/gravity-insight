# Dashboard Page Conditions Replay (D22)

## Problem

Dashboard chart replay currently emits an unconditional limitation and then
executes the chart without a page-level condition. A successful result can
therefore describe data with weaker filtering than the persisted Dashboard.
That violates the fail-closed replay boundary.

The hash-verified frontend bundle proves that Dashboard query requests contain
a top-level `dashboard_condition` object with `cond_logic` and `list`. The Web
page loads the current account's default filter through
`analysis.dashboard.condition_favourite.default_to_me.get`; its
`data.object.config.filterCondition` selects `AND`/`OR`, and
`data.object.config.filter` is compiled into the request list. This source is
separate from Dashboard detail `ui_config`, chart `even_report[].config`, and
chart-level `global_conditions`.

## Proposal

1. Run all offline tests, compiler checks, privacy/quality checks, CLI help, and
   diff checks before contacting Gravity.
2. Read one minimal real Dashboard parent chain through the stable read-only
   operations `app.list`, `analysis.dashboard.tree`, and
   `analysis.dashboard.detail`. Persist only status classifications plus JSON
   key paths and types under `tmp/codex/dashboard-conditions/`; do not persist
   identifiers, names, condition values, chart config values, credentials, or
   headers.
3. Read the stable default-favourite operation after exact Dashboard
   resolution. Treat `data.object.config.filter` as active only when it is a
   non-empty array. A missing default object, missing config/filter, or an empty
   list is inactive and keeps the existing five chart families executable.
   Malformed containers fail closed as contract drift.
4. Until merge and conflict semantics are proven, isolate every chart from a
   Dashboard with active page conditions as unsupported before validation or
   query execution. Return a machine-decidable capability gap naming the safe
   evidence needed next.
5. Apply page conditions only if the probe or existing immutable frontend
   evidence proves the exact request transformation, precedence, and conflict
   behavior for chart-level conditions. Record an applied-condition receipt
   without returning condition values. Otherwise retain the capability gap.

## Boundaries

- No mixed-subject Dashboard support, UI behavior, favourites, membership, or
  write operations.
- No changes to `plan_adapters.py`, `agent_capabilities.py`,
  `agent_composite.py`, `agent_handoff.py`, `cli.py`, or `__main__.py`.
- Stop live probing on repeated authentication failure, rate limiting,
  contract drift, an unsafe host/path, or any need to widen the sample.
- Keep test additions at or below one third of source additions and cover only
  the active-condition fail-closed boundary plus the empty-condition happy
  path.

## Acceptance

- A Dashboard with a proven non-empty page-condition list cannot produce a
  successful unfiltered chart result.
- A Dashboard whose proven page-condition list is absent or empty compiles and
  executes exactly as before.
- The result distinguishes unsupported condition semantics from query failure
  without exposing raw artifacts or condition values.
- Probe evidence reports the exact artifact source field and whether merge
  precedence was proven; an unproven result states the minimum next evidence.

## Evidence And Decision

The controlled live parent chain issued two requests: `app.list` returned
`success`, then `analysis.dashboard.tree` returned `success` without a selectable
Dashboard. The run stopped without issuing `analysis.dashboard.detail` or
widening to another App. This is classified as an empty artifact sample, not a
permission or contract failure.

The repository's immutable bundle snapshot identifies
`Dashboard-DrzT0Orh.js` as 251654 bytes. A direct public download matched its
recorded SHA-256 exactly. Its Dashboard call sites prove that page conditions
are sent independently from chart fields: event and scatter send the compiled
list as-is, property and retention remove event-scoped conditions, and funnel
removes dimension-table conditions. The evidence does not prove how the server
resolves a page condition that conflicts with a chart-level condition.

Therefore D22 fails closed when `data.object.config.filter` is non-empty. Its
value-free receipt reports source, presence, condition count,
`application_status=blocked_unproven_merge`, and `merge_semantics=unproven`.
The minimum next evidence is one controlled Web request with the same field in
both page- and chart-level conditions plus an authoritative response or server
contract that demonstrates the conflict rule. No merge priority is inferred.
