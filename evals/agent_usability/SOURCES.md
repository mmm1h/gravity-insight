# Question authorship sources

The suite was authored from these caller-facing facts at `dev@ac03a0f`:

- `docs/analysis-journeys.md`: the 47 journey goals, 33/14 executable-vs-gap
  status, adjacent-product boundaries, and the 14 target gap codes.
- `docs/agent-workflow.md`: caller-owned input sources, no-guess rules,
  shortest-path call bounds, and distinctions such as snapshot vs members,
  dashboard snapshot vs replay, material vs promotion, and detail vs aggregate.

No question wording was taken from `agent_*.py`, the shared intent router,
selector constants, or existing routing tests. The recognizer was not invoked
while authoring the cases. Exact code-facing route mappings are evaluator
configuration and are intentionally not a source for prompt wording.

Coverage follows the ledger order:

- J01–J06: Analysis event, funnel, retention, property, scatter, and same-spec
  period comparison.
- J07–J14: segment-rule evaluation, analysis context, app governance,
  attribution settings, user journey, business pulse, company usage, and custom
  audiences.
- J15–J25: materials, order directory/trace, monetization detail, governed SQL,
  dashboard snapshot/replay, saved/template replay, and segment snapshot/members.
- J26–J33: Multidim, promotion, Bilibili, advertiser profile, title packages,
  metadata search, table lineage, and material export.
- J34–J47: every explicitly missing journey and its journey-specific capability
  gap, from the analysis-default dictionary through Analysis-result export.
