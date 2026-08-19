> 归档材料：保留历史决策与取证，不代表当前接口或状态；当前入口见 docs/index.md。

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

**Verdict: the merge rule cannot be proven from the available evidence.** This
is not a partial proof of merge semantics. The evidence proves the request
boundary, but none of the four candidate rules can be distinguished.

The immutable bundle snapshot identifies `Dashboard-DrzT0Orh.js` as 251654
bytes with SHA-256
`6fc5339f29035a8aa08755e1ebfc482dd227c1c4511ff35c340dcc621ac48016`.
The snapshot record is at
`src/gravity_sdk/census/data/bundle-snapshot.json:1622`; three local census
copies match both values. Complete call-site inspection shows that the
frontend does not merge page conditions into chart conditions:

- event sends chart `global_conditions` / `global_cond_logic` and a separate
  `dashboard_condition` in the same request (byte offset 60353);
- scatter also sends the compiled Dashboard list unchanged (offset 120299);
- property and retention remove event-scoped Dashboard conditions (offsets
  77227 and 92742);
- funnel removes Dashboard conditions backed by a dimension table (offset
  109123); and
- the shared HTTP wrapper passes the constructed body directly as Axios
  `data` (`api-B9xDXL35.js`, offset 136461); no request interceptor rewrites
  either condition field.

The only other frontend `dashboard_condition` matches are generated OpenAPI
response examples, not consumers. The published source-map URL returns HTTP
404. Consequently any cross-field merge or precedence occurs after the request
leaves the frontend, and the bundle cannot prove the server rule.

The bounded artifact census covered all seven Apps visible to the current
account. It issued two `app.list` GETs and seven Dashboard-tree GETs. All nine
returned HTTP 200: six tree responses were valid but contained zero selectable
Dashboards, while one tree response was classified `contract_changed`. No
Dashboard detail, default favourite, chart query, pagination, retry, widened
sample, or write was attempted. Local receipts and ignored working artifacts
also contain no Dashboard with both condition sources populated.

The counterexample matrix therefore remains unresolved:

| Page condition | Chart condition | Proven request behavior | Effective server behavior |
| --- | --- | --- | --- |
| empty | empty | separate empty/default fields are sent | no conflict to classify |
| empty | non-empty | chart field is preserved; Dashboard list is empty | no conflict to classify |
| non-empty | empty | Dashboard field is preserved | unknown |
| non-empty, different dimension | non-empty | both fields are sent separately | AND/OR/override unknown |
| non-empty, same dimension | non-empty | both fields are sent separately | winner/replacement rule unknown |

A production query probe was not sent. `analysis.event.query` is a proven read,
but its stable request contract does not include `dashboard_condition`; offline
validation rejects that field with `INPUT_INVALID` and `network_called=false`.
Using a raw transport would bypass the governed SDK, while creating a
conflicting artifact would violate the read-only boundary. The weak-POST
read-semantics gate was not hit; the stable input-contract gate stopped this
path first.

Therefore D22 continues to fail closed when
`data.object.config.filter` is non-empty. Its value-free receipt reports source,
presence, condition count, `application_status=blocked_unproven_merge`, and
`merge_semantics=unproven`. The minimum safe evidence is either a server
contract for the two request fields, or a naturally existing Dashboard whose
captured read-only request and authoritative result distinguish both a
different-dimension case and a same-dimension conflict. One case alone cannot
prove the full rule; no merge priority is inferred.
