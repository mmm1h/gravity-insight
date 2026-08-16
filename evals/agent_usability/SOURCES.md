# Question authorship sources

## Development v3 expansion

The 96 development-only additions were authored at
`dev@6c3b2dd63851b3c869208b500e67e9697d2e76d3` from only:

- the counted journey goals, statuses, blockers, and exact target identities in
  `docs/analysis-journeys.md` and the public journey target registry; and
- the caller tasks, input ownership, adjacent-product boundaries, and explicit
  ambiguity rules in `docs/agent-workflow.md`.

Existing development prompts were read only as a negative style/deduplication
check so the new cases would not reuse their normal/boundary/missing-input
templates. They did not supply product facts or new wording. No protected
payload, key, decrypted memory, prompt-level protected result, recognizer source,
or routing test was used. The recognizer was first invoked only after the 96
questions and their journey IDs were frozen.

Every journey contributes exactly two additions. Primary-family counts are
`13 + 12 + 12 + 12 + 12 + 12 + 12 + 11 = 96`; the final 11 are a one-to-one
cover of the current 11 completely missing journeys. The 12 `multiple_intents`
cases intentionally require `MULTIPLE_INTENTS` under the workflow contract.
The current single-journey scorer cannot represent that response as a pass;
this known measurement limitation is reported with the development result and
must not be repaired by changing recognizer behavior to return one product.

## V2 core

The v2 suite was authored from these caller-facing facts at
`codex/agent-eval@7f73cf9`:

- `docs/analysis-journeys.md`: the 48 counted journey goals, 33/15
  executable-vs-gap status, adjacent-product boundaries, and the 15 target gap
  codes. The three rows explicitly marked as non-independent remain out of the
  suite.
- `docs/agent-workflow.md`: caller-owned input sources, no-guess rules,
  shortest-path call bounds, and distinctions such as snapshot vs members,
  dashboard snapshot vs replay, material vs promotion, and detail vs aggregate.

No question wording was taken from `agent_*.py`, the shared intent router,
selector constants, or existing routing tests. The recognizer was not invoked
while authoring the cases. Exact code-facing route mappings are evaluator
configuration and are intentionally not a source for prompt wording.

Coverage follows the counted ledger order:

- J01–J06: Analysis event, funnel, retention, property, scatter, and same-spec
  period comparison.
- J07–J14: segment-rule evaluation, analysis context, app governance,
  attribution settings, user journey, business pulse, company usage, and custom
  audiences.
- J15–J25: materials, order directory/trace, monetization detail, governed SQL,
  dashboard snapshot/replay, saved/template replay, and segment snapshot/members.
- J26–J33: Multidim, promotion, Bilibili, advertiser profile, title packages,
  metadata search, table lineage, and material export.
- J34–J47: the explicitly missing journeys and their journey-specific capability
  gaps, from the analysis-default dictionary through Analysis-result export.
- J48: exact platform-asset binary preview/download (Issue 19) and
  `PLATFORM_ASSET_BINARY_CONTRACT_MISSING`.

The old v1 manifest said `47 = 33 / 0 / 14`. Its cases already contained D28
as J41 (`monetization_aggregate_gap`); the actual omitted counted ledger row was
Issue 19. V2 keeps D28 and adds the row that was demonstrably absent rather than
duplicating D28 under a second journey ID.

## Independent final authorship

The 48-case final suite was authored at `dev@810dde7` from the same two public
sources above plus the evaluator's already-public route/gap identities. It did
not read `cases/development.jsonl`, `cases/holdout.sealed.json`, the holdout key,
decrypted holdout memory, prompt-level results, or holdout aggregates.

Unlike development/holdout's ordinary Chinese/English, adjacent-boundary, and
missing-input expression families, final rotates five different generation
strategies across journey order so no product family owns one style:

- 10 colloquial, elliptical requests;
- 10 requests containing a realistic Chinese typo or English misspelling;
- 10 Chinese-English code-switched requests;
- 9 indirect requests that state the analysis purpose without naming the
  product;
- 9 first turns that deliberately leave the exact input for a later follow-up.

The exact prompts were randomly composed and sealed in memory; no plaintext
question file was written. The ignored one-time generator contained only the
public ledger parser, strategy rules/word pools, and route/gap identities, and
was deleted immediately after sealing. The repository contains only the
authenticated ciphertext, aggregate construction counts, source revision, and
hashes. No old prompt was opened for rewriting, similarity comparison, or
cross-split deduplication; final uniqueness was checked only within the new 48
in-memory cases.
