# Changelog

本文件记录 Gravity Insight 面向消费方的显著变更。格式采用
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) 的分类方式，版本采用
[Semantic Versioning](https://semver.org/spec/v2.0.0.html) 的三段格式；即使在
`0.x` 阶段，每个破坏性变更仍必须单独标成 Hard break 或 Soft break。

维护规则由 `scripts/check_changelog.py` 强制执行：`pyproject.toml` 的当前版本必须
有 Unreleased target 或已发布条目；每个版本必须显式声明 breaking changes；有破坏性
变更时必须链接迁移说明；带日期的已发布条目必须匹配
`scripts/changelog_release_lock.json` 中的 SHA-256。
具体维护步骤见[迁移说明维护约定](docs/migration/README.md)。

## [Unreleased]

Target release: `0.3.15`

### Breaking changes

- **Hard break:** Nonempty runtime pins are exact execution constraints: malformed pins fail with `INPUT_INVALID`, mismatched pins fail with `RUNTIME_PIN_MISMATCH` before startup distribution access, authentication or dispatch, even when updates are disabled. Unset/empty pins retain default-on updates. Activation receipts now report `running_version: null` until the staged child observes its imported version; a child exit alone is not execution-version proof.
- **Hard break:** `campaign-outcome-evaluation`, `metric-decomposition`, `scenario-projection`, `sentiment-aggregation` and `funnel-diagnosis` Operators at `@1` now require explicit `mode=rowwise`. Implicit totals, normalized shares and cumulative conversion fail closed with registered reasons and a migration remedy. Exact `@2` contracts restore supported cross-row results with explicit scope, additivity-axis, partition or linear-lineage evidence; no silent version upgrade is provided. Three scenario Model families have explicit `@2` successors and refreshed `@1` parameter digests. Skill Library URI migration remains owned by R2-05/R2-12.

Migration guide: [0.3.15](docs/migration/0.3.15.md)

### Added

- Additive: `doctor` and `skills status --diagnose` distinguish read-only Runtime seed/CAS readiness, project lock resolution, native file consistency, unknown host discovery and unmeasured invocation/routing. Default `skills status` retains its maintenance receipt v1 and masks local paths; status no longer creates state or CAS directories. Neither diagnostic installs host files or infers business success from local readiness.
- Additive: `ratio_identity` derived-metric operator reconciles a native ratio metric against the ratio of two unrounded amount columns via exact cross-multiplication, with caller-declared exact and quantization tolerances; disagreement surfaces `warn`/`fail` data-quality diagnostics (`RATIO_IDENTITY_QUANTIZATION_DRIFT`, `RATIO_IDENTITY_MISMATCH`) instead of unqualified success, zero or missing denominators yield explicitly undefined results, and total rows divide summed amounts rather than averaging row-level ratios.
- Additive: `report-ap-cost-observation` v5 declares the ad-cost grain and provenance boundary: `click_company` as the only native non-time cost dimension, revenue cohorts anchored on activation, an estimation policy that forbids presenting allocated cost as native or exact, and machine-readable capability gaps `AP_COST_DATE_SEMANTICS_UNDECLARED` (upstream never declares which date `ap_cost` represents) and `POST_REGISTRATION_USER_GROUP_EXACT_COST_UNAVAILABLE` (no upstream fact links ad spend to post-registration user groups). Versions v1-v4 remain unchanged; existing bindings do not auto-upgrade.

### Fixed

- Governed metric decomposition now sums and normalizes unrounded component changes, rounding only the output; sub-micro-unit changes no longer disappear before aggregation.

## [0.3.14] - 2026-09-08

### Breaking changes

- None.

### Fixed

- Publish Skill Library `skill-library-v5` so the released library carries the corrected `metric-anomaly-localization@1` completeness declaration. The wheel seed is rebuilt from the checkout while the library is released separately, so a corrected Skill reached the 0.3.13 seed but never `skill-library-v4`: an offline consumer and one fetching the advertised `index_url` read different capability declarations under the same `source_id`. A pinned build-manifest digest now fails at the commit that introduces such drift. Published v1-v4 assets are unchanged.

## [0.3.13] - 2026-09-08

### Breaking changes

- None.

### Added

- Packaged fictional Business Source and Compose request examples with offline CLI regression coverage and a structural Business/Compose schema discrimination guard.
- Additive: `gravity skills host-install-plan --lock <project-lock>` stages only exact locked Skills after offline Runtime/source/index/package preflight; omitting `--lock` preserves full-bundle staging and shared Host entries are never pruned.
- Additive: `gravity skills status` diagnoses project lock/Runtime version drift offline, distinguishes unchecked missing locks from matches and mismatches, and supplies an exact re-lock command without changing Runtime equality enforcement.
- Additive: offline `gravity cache status|prune` reports file counts, logical/allocation bytes, legacy residue and reason-coded retention; pruning defaults to dry-run and requires `--execute`.

### Changed

- Root CLI help now separates caller semantic context, Compose and Business Sources, documents registry scope arguments and exact Compose version choices, and links onboarding to the existing Skill project-binding template without adding runtime behavior.
- Existing Definition schema descriptions explicitly distinguish Business Definition from Compose Definition; schema identities and validation contracts are unchanged.

### Fixed

- Correct join-key evidence denominators and per-probe request counts; existing `source` fragments identify `joinkey-research-{research,targeted}-summary` artifacts with paths, SHA-256 hashes and aggregate excerpts in `tests/fixtures/join_key_evidence_sources.json`. Unresolved evidence, adjudications and expiry rules remain unchanged.
- Cache-root resolution now consistently honors `GRAVITY_CACHE_HOME`, uses `gravity-insight`, and expands/resolves paths. Existing account snapshots remain readable through legacy-location fallback without a forced network refresh; no scope semantics or read capabilities are removed.

## [0.3.12] - 2026-09-07

### Breaking changes

- **Hard break:** `ResponseProjection` gained a `dynamic_key_patterns` field, inserted
  between `numeric_paths` and `empty_object_as_empty_page`. Any caller constructing
  `ResponseProjection` positionally now binds the wrong arguments; construct it with
  keywords, or build it from a contract via `ResponseProjection.from_config`. The
  private `models._response_projection_schema` also moved to the new public module
  `gravity_insight.response_projection_schema` as `response_projection_schema()`.
- **Hard break:** `capability-validation-summary-v2.schema.json` now lists
  `data_evidence_status` in `required`. Summaries produced before 0.3.12 fail
  validation, and consumers that construct summaries must emit one of
  `nonempty` / `confirmed_empty` / `inconclusive` / `not_evaluated`. The field is
  optional in `capability-validation-run-v2.schema.json`, so stored runs stay
  readable. This exists because projected emptiness alone never proved absence of
  rows: a response whose every declared field missed the upstream payload was
  indistinguishable from a genuinely empty result. Only an explicit upstream signal
  (`page.total_items == 0` or HTTP 204) now yields `confirmed_empty`, and a response
  carrying both non-empty projected data and an explicit-empty signal fails closed as
  `inconclusive` rather than silently picking one.
- **Hard break:** `analysis.user_detail.list` moved to `contract_version: 4`,
  declaring eight newly observed top-level fields (`bytedanceMid1_name` through
  `bytedanceMid8_name`, 153 observed fields to 161). Its `contract_fingerprint`
  changes, so Validation Results recorded against version 3 are quarantined with
  `CAPABILITY_FINGERPRINT_MISMATCH` and must be re-recorded.
- **Hard break:** `analysis.funnel.query` declares
  `response_projection.dynamic_key_patterns` and its `contract_fingerprint` changes
  for the same reason. No other operation is affected: the fingerprint payload emits
  `dynamic_key_patterns` only when non-empty, and `analysis.funnel.query` is the only
  operation that declares it.
- **Hard break:** `analysis.order_detail.list` moved to `contract_version: 3` and its
  `pagination.completeness` is now `complete` with `pagination_evidence: production`,
  upgraded from `unknown`/`template`. This is the outcome callers wanted — the
  operation can now satisfy a claim-bearing dependency that requires a full
  collection — but the `contract_fingerprint` changes with it, so Validation Results
  recorded against version 2 are quarantined and must be re-recorded.
- **Hard break:** `analysis.scatter.query` moved to `contract_version: 2`, registering
  thirteen nested numeric paths under `aggregate_by_date`, `date_list` and `y` that
  production responses were already returning. Same fingerprint consequence.
- **Soft break:** the Runtime wheel again carries Skill content, and the root CLI
  provisions it automatically. This **partially reverses the 0.3.5 Hard break** that
  removed wheel-bundled Skills, so it is called out rather than shipped as an
  invisible improvement. What returns is a single sealed archive at
  `gravity_insight/skill_seed/skill-seed-v1.zip` (93 assets, 44 Runtime and 44 Agent
  Skills). What does **not** return is the wheel-owned registry: no
  `gravity_insight/skills/` or `gravity_insight/contracts/skills/` path exists, and
  `scripts/generate_skill_library.py` remains the only build owner. The seed does not
  enter the discovery surface directly — first provisioning still runs the full
  source/index compile, exact managed lock, archive verification, CAS write and final
  verify, with `network_called=false`. Set `GRAVITY_INSIGHT_AUTO_SKILLS=0` to opt out;
  it is deliberately a **separate** switch from `GRAVITY_INSIGHT_AUTO_UPGRADE`, so
  Runtime security updates can be accepted while Skill content is frozen. `doctor`,
  `--help`, `--dry-run`, test and evaluation paths never provision, and importing
  `gravity_insight` still has no file or network side effect.

Migration guide: [0.3.12](docs/migration/0.3.12.md)

### Added

- Operation contracts accept `response_projection.dynamic_key_patterns`, mapping a
  declared data path to a **named** key shape. Only `iso_date` and `decimal_19` are
  accepted — arbitrary regular expressions are deliberately not a contract surface.
  `iso_date` additionally rejects non-calendar dates, and every declared path root
  must be a declared `data_key`. This lets `analysis.funnel.query` return legitimate
  date-bucketed aggregate groups without each new calendar day reading as additive
  drift, while user-property grouping stays fail-closed: a date cannot impersonate a
  requested dimension such as `$os`. Drift declarations gained the reason codes
  `declared_dynamic_key` (shape matched) and `dynamic_key_shape_mismatch` (declared
  but wrong shape); undeclared dynamic keys still report
  `dynamic_key_requires_review`.
- Response drift records carry `expectation_provenance`, pinning the operation
  contract digest and version, the Runtime version, the request shape fingerprint,
  the accepted upstream baseline (observed type, response shape fingerprint,
  observation timestamp, app environment fingerprint) and the corresponding current
  observation. Drift can now be attributed to an upstream change versus a wrong local
  expectation instead of only being reported as a mismatch.
- HTTP receipts carry an optional `credential_scope_opaque_id`, and
  `gravity_insight.runtime_scope.credential_scope_opaque_id()` is public. It is a
  random 64-hex marker persisted `0600` inside the principal scope directory, so
  receipts can be grouped by credential scope without the marker being derived from,
  or revealing, any credential material.
- Cross-operation join keys are now a machine contract rather than a field-name
  guess. `gravity_insight.contracts.join_key.resolve_proven_join_key()` resolves by
  `platform`, `object_type` and optional `object_subtype`, returning the exact left
  and right operation/path pair, normalization rules and the observed evidence.
  `namespace_status` is three-valued — `proven`, `disproven`,
  `insufficient_evidence` — and only a `proven` namespace within its
  `revalidate_after` window resolves; everything else raises `JoinKeyContractError`.
  The registry lives at `contracts/join-keys/registry.v1.json`, validated by
  `join-key-registry-v1.schema.json`.
- Multi-account **authentication failover**, off by default. When
  `GRAVITY_ACCOUNT_FAILOVER=1` and `GRAVITY_ACCOUNT_ENV_FILES` lists ordered
  credential files, a complete read-only operation that fails authentication is
  refreshed once and then retried on the next account. `GRAVITY_ACCOUNT_MAX_ACCOUNTS`
  defaults to 2 and is configurable. `gravity account-pool` and
  `gravity_insight.account_pool.AccountPoolConfig` expose the same behaviour.
  Receipts are partitioned per account generation and record the slot, the reason
  and the cumulative switch count — never the credential.
  **HTTP 429 deliberately does not trigger a switch** and keeps the existing
  backoff: a two-round production experiment (382 + 7 requests, separate processes)
  showed a second principal on the same host is rate-limited while the first is, so
  the quota is not account-scoped. Switching on 429 would spend a second account's
  quota for no throughput. This ships failover only; it does **not** add
  multi-account concurrency.
  Availability is three-valued — `not_configured`, `configured_unavailable`,
  `configured_healthy` — and the switch state is `never_switched` / `switching` /
  `switched_success` / `switched_failed` / `exhausted`, so "no second account" and
  "second account present but unusable" are distinguishable rather than both
  presenting as single-account operation.

### Fixed

- `receipt_query` no longer requires an HTTP receipt's field set to match one of two
  exact shapes; it now requires the mandatory fields and permits a closed set of
  optional ones, so adding a receipt field stops invalidating stored receipts. It
  additionally rejects a receipt whose drift `expectation_provenance` does not bind
  to that receipt's own `request_shape_fingerprint`, which would otherwise let a
  provenance record describe a different request than the one it is filed under.
- A Runtime that refreshes an expired credential mid-flight now writes its
  subsequent HTTP receipts, and partitions its Governor observations, under the
  refreshed credential generation. Both coordinates were previously computed once
  at Runtime construction, so every request after a 401-triggered refresh filed its
  evidence under the *previous* generation — the isolation guarantee failed in the
  one case that happens routinely. Storage and observation coordinates are now
  resolved per request and frozen before any rate wait or I/O, so an in-flight
  response and its transport retries keep the binding they started with while the
  authentication replay picks up the new one. The connection pool is not recycled
  and in-flight pagination is not interrupted. Receipts already written to the wrong
  generation are not migrated.

## [0.3.11] - 2026-09-07

### Breaking changes

- **Hard break:** the three claim-bearing Capability contracts no longer require
  `completeness: "complete"` from dependencies that do not paginate. Those four
  operations declare `pagination.kind: "none"`, so the completeness vocabulary
  (`unknown`/`prefix`/`complete`, whose upgrade criterion is entirely about last-page
  echo and total counts) could never rank them above `unknown`; every claim-bearing
  capability was therefore permanently blocked and published an empty
  `allowed_claims` at runtime. `report.business.query` does paginate and still
  requires `complete`. `journey can-run` on an affected Journey no longer returns
  `COMPLETENESS_INSUFFICIENT`; a dependency lacking a Validation Result now reports
  `DEPENDENCY_VALIDATION_UNKNOWN`, which is resolvable by running validation rather
  than unsatisfiable by contract. Consumers asserting the old reason code must
  update; `meets_completeness`, `assess_capability_requirement` and the
  `COMPLETENESS_INSUFFICIENT` rejection itself are unchanged, and a new CI-time gate
  (`claim-dependency-requirement-unreachable`) fails the build if any claim-bearing
  capability declares a requirement its dependency can never satisfy.

- **Hard break:** `user-detail-aggregate` now reports a privacy-policy-excluded
  field as `USER_DETAIL_AGGREGATE_FIELD_PRIVACY_EXCLUDED` instead of
  `USER_DETAIL_AGGREGATE_FIELD_UNSUPPORTED`. A condition whose non-null value-type
  set disagrees with the non-empty homogeneous observed row type now reports
  `USER_DETAIL_AGGREGATE_CONDITION_TYPE_MISMATCH` with `category=caller` instead
  of `USER_DETAIL_AGGREGATE_MIXED_TYPE` with `category=upstream`, changing the
  process exit from 3 to 2. The mismatch diagnostic now identifies the exact
  filter or measure path, measure name, referenced field, supplied scalar-type
  set and observed row type; it still omits condition values and user rows.
  Both old and new paths are non-retryable. Actual mixed/non-scalar source rows
  retain `USER_DETAIL_AGGREGATE_MIXED_TYPE` and `category=upstream`.
- **Hard break:** the five built-in Model contracts express `claim_policy` in
  canonical stable ids across all three tiers (`validated`, `scenario`,
  `forbidden`) instead of natural-language phrases. `causal claim` becomes the
  existing Skill/Journey id `causality`; the other four become their own ids
  rather than being merged into broader near-synonyms. No prose aliases are
  retained. A consumer matching the old strings gets no match, and a missed
  match against `forbidden` reads as "not forbidden" rather than raising, so a
  caller can silently begin permitting a claim it used to refuse. Model URIs,
  `models describe`/`evaluate` shapes, approval-selection logic and every
  data-read capability are unchanged.
- **Hard break:** Capability Validation run and summary evidence advance from
  `gravity.capability-validation-run.v1` / `summary.v1` to v2. Outcome objects
  may now carry normalized `response_drift` and value-free `error_detail`, and
  the current summary filename changes to `capability-validation-summary.v2.json`.
  Strict v1 parsers and readers of the old summary path must migrate. The
  summarizer still reads immutable v1 runs, and its command response plus all
  collection and trust capabilities are unchanged.

- **Hard break:** stable response projections were reconciled with what upstream
  actually returns across 22 operations. Fields previously omitted with additive
  `result_audit.response_drift` may now be projected, newly known-omitted fields
  no longer produce that drift, and selected JSON containers are now accepted as
  opaque values. `material.local.list.image_set` moves from `item_keys` to
  `known_omitted_item_keys` — the one allowed-to-omitted migration — and
  `material.album.tree` replaces `recursive_data_item_keys` with an explicit
  `data_item_keys` plus self-recursive `nested_item_keys`. `promotion-performance`
  preserves the newly registered Kuaishou account fields. `contract_version` is
  unchanged; Validation Result staleness is enforced by `contract_digest`, which
  covers `response_projection` through `contract_fingerprint`, so evidence
  collected against an old projection is quarantined as
  `CAPABILITY_FINGERPRINT_MISMATCH` rather than silently reused. Strict response
  or `describe` parsers, drift-driven automation, and callers relying on the
  previous omission policy must migrate using the per-operation field matrix in
  the 0.3.11 migration guide.
- **Hard break:** shared structured-JSON input parsing reclassifies two failures
  in opposite directions. Missing, path-like and selector-like `--input` values
  now report `INPUT_INVALID` with `category=caller`, `field=input` and exit code
  2 instead of `LOCAL_IO_ERROR`/exit 4; unreadable UTF-8 files or stdin now
  report `LOCAL_IO_ERROR` with `category=local`, `field=input` and exit code 4
  instead of `INPUT_INVALID`/exit 2. Malformed-JSON diagnostics gain a stable
  `field=input` and a `next_action`, and `export` now preserves an exception's
  own recovery action. This affects every command sharing the parser, including
  `agent`, `plan`, `analysis query`, `derive` and `export`. Consumers branching
  on the old code, category or exit status must migrate.
- **Hard break:** general Insight read results and receipts may now carry
  `gravity.response-drift.v2` for breaking response drift, independently of
  Capability Validation evidence. V2 adds per-field `classification` and, for
  breaking fields, `expected_type`, and admits `missing` and `non_json` observed
  types. Additive-only evidence remains v1 while the exported
  `response_drift.SCHEMA_VERSION` now denotes v2, so callers comparing every
  drift artifact against that constant will mismatch on additive output. Branch
  on each artifact's own `schema_version` and dispatch on `classification`.
- **Hard break:** executable recovery text in Agent gap envelopes changed.
  Multi-intent gaps now direct callers to `gravity agent-catalog describe
  <selector>` instead of passing a selector to the JSON-only `gravity agent
  --input` option, and host-selection, batch-question and derived-metric
  recovery commands now carry explicit JSON-document placeholders. Codes and
  envelope keys are unchanged; consumers matching or executing the previous
  `next_action` strings must update.
- **Hard break:** `material-performance` contract-failure components now expose
  value-free structural diagnostics. Malformed components gain a
  `drift_diagnostics` object naming the failed check and JSON Pointer path,
  valid upstream `CONTRACT_CHANGED` components retain normalized
  `result_audit.response_drift` through product and Plan sanitization, and a
  lower-layer `CONTRACT_CHANGED` without drift adds
  `component_contract_status @ $.status`. The error code, status and outer
  schema name are unchanged; strict component parsers must migrate.
- **Hard break:** Journey `analysis.gravity.game.revenue-forecast-readiness` now
  allows `observed-revenue-driver`, `scenario-revenue-projection` and
  `bounded-target-path`, where its v1 contract previously exposed an empty
  allowed-claim set. The Journey remains unavailable for execution, but
  consumers using its descriptor as a claim authorization policy must update.
- **Hard break:** public
  `reference_journey_quality.evaluate_playbook_data_quality()` no longer accepts
  the required `completeness=` keyword, so a 0.3.10 call raises `TypeError`.
  Completeness is assessed separately from data quality: the returned DQ
  `checks` array no longer contains a `completeness` entry and no longer emits
  `DATA_QUALITY_UNPROVEN`, and successful R01 results propagate the dependency
  completeness instead of hard-coding `complete`.
- **Hard break:** opaque JSON containers declared in `opaque_json_item_keys` now
  apply the same key-level privacy exclusions recursively to their contents, and
  are bounded to 32 KB serialized, depth 8 and 256 elements. A container key
  matching a direct personal identifier, a sensitive analysis field or a
  credential name/suffix is dropped instead of copied verbatim, and an
  over-budget container is reported as breaking drift rather than silently
  truncated. Callers that relied on receiving arbitrary nested upstream JSON
  unfiltered must migrate.

Migration guide: [0.3.11](docs/migration/0.3.11.md)

### Fixed

- Removed the unsupported blanket privacy exclusion for `bytedanceMid1..8`, so
  registered scalar material fields can be filtered and grouped by the bounded
  aggregate product. Direct identifiers, direct personal response fields and
  credential/session fields remain excluded, and no user-detail row is added to
  the result contract.
- The aggregate input schema now states that `WITH_VAL` means JSON non-null and
  therefore includes empty strings, zero and false. It also gives the existing
  `WITH_VAL []` plus `NOT_EQUALS [""]` recipe for a non-null, non-empty string;
  operator behavior and homogeneous condition-type validation are unchanged.
- The `material-performance` product no longer reports `CONTRACT_CHANGED` for
  valid material report rows. Its second-stage sanitizer validated whole rows
  against a stale 13-field set that omitted `material_id`, which every
  production response carries, so the set difference was always non-empty and
  the row projector rejected the batch while the same request through
  `gravity read material.report.query` succeeded. The source-row and opaque
  boundaries are now derived solely from the compiled candidate manifest, and an
  import-time check fails closed if the product's output fields are not a subset
  of registered source fields. Product output stays narrow: the existing fields
  plus `material_id` for the attribution chain.
- Capability Validation run and summary v2 evidence can now persist breaking
  response drift. Both schemas pinned `response_drift` to
  `gravity.response-drift.v1` with `classification: "additive"`, so any operation
  with a missing required field or a changed type made the run report fail
  schema validation before it was written — the evidence format built to record
  drift could only record the harmless kind, and losing one outcome lost the
  whole run. The two schemas now share one definition accepting both v1 additive
  and v2 breaking evidence, and the additive-only filter moved to the drift
  declaration consumer.
- The upstream drift signal no longer reports `clear` when no checked-in file
  contains a recognizable observation. "Not measured" and "measured, no drift"
  shared one value, and the census workflow closed the managed drift Issue on
  either. A third `inconclusive` status now covers the first case; the workflow
  warns and leaves every Issue untouched, while a genuine no-drift census still
  reports `clear` and still closes the Issue. The unexpected-status guard also
  moved ahead of the Issue actions, where previously it sat at the end of an
  `elseif` chain that only one path reached.

## [0.3.10] - 2026-09-05

### Breaking changes

- **Hard break:** CLI startup updates are now enabled when
  `GRAVITY_INSIGHT_AUTO_UPGRADE` is unset, and install newer releases rather than
  only producing an external Installer notification. This includes releases
  containing Hard breaks: startup does not consult the external compatibility
  policy to skip breaking versions. Consumers requiring a controlled lifecycle
  must set `GRAVITY_INSIGHT_AUTO_UPGRADE=0` (also `false`, `no`, `off`) or pin the
  exact running version. Doctor, diagnostic/test/evaluation opt-outs remain.
  A successful installation re-launches the command in a fresh Python process
  from an isolated immutable pip stage; the imported environment and project
  lock are not overwritten. Python SDK imports alone do not activate updates.
- **Soft break:** Startup check, installation and activation-preflight failures
  no longer stop the requested command with update-policy exit code 75. They
  warn with a reason and remedy, then run the current version. Once the updated
  business command starts, its exit code is returned without retrying it.

Migration guide: [0.3.10](docs/migration/0.3.10.md)

### Added

- Private `gravity.runtime-update-receipt.v1` JSON installation and activation
  records bind old/new versions, UTC time, process trigger, interpreter and
  installed stage. The re-launched process receives its activation receipt path
  in `GRAVITY_INSIGHT_UPDATE_RECEIPT`. Release checks reuse the 24-hour cache;
  target-scoped OS locks serialize installation and failed attempts back off
  for 24 hours. Pip output remains in a private diagnostic log.

## [0.3.9] - 2026-09-05

### Breaking changes

- **Hard break:** Five runtime failures that originate upstream or inside the
  Runtime no longer present as caller input errors. A non-object operation
  output, a non-object operation schema, a missing `response_projection`, an
  invalid Multidim product schema, and a schema missing its dynamic binding
  field now raise `CONTRACT_CHANGED` with `category=upstream`, `field=null`,
  and **exit code 3**, where they previously raised `INPUT_INVALID` with
  `category=caller`, a `field` naming a caller input, and **exit code 2**.
  Consumers branching on exit code 2 or on `INPUT_INVALID` for these paths must
  recognise `CONTRACT_CHANGED`. `ContractChangedError` is not a subclass of
  `ValueError`, so handlers catching `ValueError` alone no longer catch them;
  both types remain under `GravityInsightError`. The messages themselves are
  unchanged — only the classification and the `next_action`, which now names a
  repair owner, a next step, and a stop condition.

Migration guide: [0.3.9](docs/migration/0.3.9.md)

### Added

- Context-bound measurements (`gravity.context-bound-measurement.v1`). A
  measurement whose meaning depends on where it was taken now carries that
  context — coordinate, scope, capture time, and the commit or artefact it
  binds to — instead of having it inferred from the environment at the reading
  site. Resolving one against an expected context yields `measured`,
  `not_measured`, `expired`, `not_applicable`, or `invalid` with a reason code,
  so "the evidence aged out", "it was taken somewhere else", and "it was never
  taken" stop collapsing into a single silent `unmeasured`.
- Each `gravity maturity score --json` dimension gains a `status` field naming
  which of those five states it is in. Purely additive: no existing key was
  removed or repurposed, and `measured` keeps its meaning.
- `gravity maturity score --json` gains a `repository.quality_profile` receipt
  reporting whether that measurement was actually captured. Purely additive.

### Fixed

- Subprocess output is no longer decoded with whatever locale the caller
  happened to run under. Every call that reads a child as text now states its
  encoding, and calls that launch a Python child pin the child's encoder as
  well, since pinning only the reader turns a working call into a failing one.
  On a non-UTF-8 console this previously killed the reader thread on the first
  incompatible byte while the command still exited 0, so the output was lost
  rather than reported. Children run with `-I` or `-E` ignore the environment
  and are pinned with `-X utf8` instead.
- A `gravity maturity score --json` dimension whose measurement subprocess
  failed silently degraded to an unmeasured dimension with no signal saying so.
  The capture failure is now reported as `not_measured` with a reason, so
  "measured and scored zero" and "never measured" are distinguishable in the
  output.

## [0.3.8] - 2026-09-05

### Breaking changes

- **Soft break:** Failure-only output from `gravity sql credentials`, SQL product
  discovery, `sql status`, and `sql evidence-preflight` is now the structured
  `gravity-sql.command-error.v1` JSON receipt on stderr instead of an `ERROR:`
  text line. Existing exit codes and all success, `sql query`, and `sql verify`
  schemas are unchanged; consumers that parsed failure text must migrate to the
  receipt fields.
- **Hard break:** The checked-in Repository Map moves from
  `contracts/generated/repository-map.v1.json` to `repository-map.v2.json`.
  Its whole-file JSON transport now tables repeated entry strings, issue paths,
  and module-graph nodes; raw JSON consumers must decode those tables. The
  repository loader and task-context surface still return the complete v1 fact
  shape, and generation proves decoded v2 is field-for-field identical.
- **Hard break:** Segment evaluation no longer maps an upstream rejection of the
  locally valid static custom-event count shape to generic
  `INPUT_INVALID field=input`. It now returns
  `SEGMENT_EVENT_RULE_ACCEPTANCE_UNPROVEN`, `category=upstream`,
  `retryable=false`, and the exact `user_event_rules` path. The public Segment
  spec schema advances from `gravity-insight.segment-rule-spec.v1` to `v2` and
  changes `event_support.default_status` to
  `requires_live_metadata_and_event_specific_acceptance`; metadata validity is
  necessary but no longer presented as endpoint-acceptance evidence.
- **Soft break:** Registered SQL Evidence verification is now fixed at one product
  in flight; direct `verify_all(..., max_workers=N)` callers must remove values
  other than `1`, and direct `build_evidence()` callers must supply the ordered
  verification history. New Evidence is schema v2 and adds that history as a
  required field. Runtime readers continue to accept immutable v1 Evidence, so
  existing read capability is retained while strict raw-output consumers migrate.

Migration guide: [0.3.8](docs/migration/0.3.8.md)

### Changed

- The public-static-graph Census crawl now keeps one bounded worker pool for the
  full recursive traversal, allowing each worker to reuse its HTTP session and
  keep-alive connection across batches. This removes hundreds of avoidable
  TCP/TLS connection establishments on a typical 500-candidate crawl without
  changing the four-worker ceiling, request budget, completeness definition,
  transport-failure classification, or non-capacity fail-closed behavior.
- The version-tag release path now proves tag/current-main/CI commit identity,
  runs a fresh zero-skip Integrated Validation receipt, checks the intended wheel
  across five surfaces and the pinned canonical consumer, validates changelog and
  migration declarations, and aggregates every pre-publish result into one
  artifact-bound release receipt before the unchanged OIDC publisher can run.
- The Agent install contract now defaults to the latest published version
  instead of requiring an exact one. Pinning needed someone to supply a version
  number; with nobody supplying it an Agent reused whatever version the example
  or its own memory carried, and the startup update check is disabled while a
  pin is in effect — so the install silently stayed on a long-superseded
  release. `pin_when_asked` keeps exact pinning available for a stated
  reproducibility requirement, and the contract now also says to read the
  resolved version back as an observation rather than as the input to the next
  install. Project `requirements.txt` / `pyproject.toml` pins are unaffected and
  deliberately left exact.
- Local validation now has one explainable `scripts/run_changed_tests.py`
  entry point. It derives changed files from Git, selects every test reached by
  the bounded reverse dependency closure, and promotes broad impact to Full
  instead of silently truncating. Nine repository-wide scan/build checks are
  marked `full_gate` and excluded only from Focused runs; raw pytest, unittest,
  and CI remain complete, with shard conservation and slow-test marker gates.
- The four-worker pytest scheduler now uses `--dist loadfile`. Three same-host
  full-suite runs measured 224.502s for `load`, 227.025s for `loadscope`, and
  188.213s for `loadfile`; keeping a test module on one worker lets its existing
  repository-scan caches and module fixtures be reused without sharing mutable
  state across workers.
- Pull-request secret scanning now checks the complete tracked tree plus only
  commits added since the base merge point. Pushes to `main` and `dev` retain
  the complete-history scan, and release still requires the exact-SHA full
  history receipt, so the PR critical path is reduced without weakening the
  publication boundary.

### Added

- `GravitySDK.reconcile_standard_retention_denominators()` now produces a bounded,
  offline `match|drift|unknown` record from already-fetched Multidim
  `standard_activate_cnt` and Analysis Retention `init_num` aggregates. It preserves
  both field names and retrieval timestamps, keeps empty or missing evidence out of
  zero, and reports the named native-cohort semantic gap instead of treating
  `values[0]` as a substitute denominator.
- Six stable page-info operations now declare complete collection semantics from
  bounded production observations that reached the echoed final page, returned
  SDK `has_more=false`, and reconciled every returned item with the reported
  total: segment list, shared analysis templates, both attribution postback-map
  lists, material tag categories, and multidimensional metric-tag categories.
- Two previously human-ledger-only closed analysis journeys now have versioned
  machine Journey contracts. Each contract binds its existing ledger title,
  governed operation dependencies, four reachable surfaces, bounded request
  budget, execution owner, and allowed/forbidden claims. Offline certification
  remains `uncertified` until current Capability Validation evidence exists; no
  production execution is implied by registration.
- `operator://gravity/significance-test@1` now evaluates independent binary
  outcome arms entirely offline through `gravity experiment evaluate` and
  `sdk.experiments.evaluate()`. The result carries the selected tail, alpha,
  Bonferroni family handling, observed risk difference and uncertainty; sample,
  variance, window, grouping, causal-claim and same-run self-validation failures
  remain distinct fail-closed outcomes.

### Fixed

- Test-duration classification now normalizes GitHub Actions measurements to
  local-equivalent seconds before applying the immutable 40s local Focused
  threshold. Both that normalization and the 240s absolute CI envelope use one
  measured `716/364` local-to-CI ratio; the absolute ceiling still applies to
  raw CI wall time.

- Grouped two-step user-count Retention no longer returns an arithmetically
  impossible total as `success`. Total offsets with negative counts, a numerator
  above `init_num`, or retained/loss percentages outside `[0, 100]` are nulled
  and returned as `status=partial` with `RETENTION_TOTAL_INVALID`; valid group
  rows remain available. The result also carries a directly executable
  `gravity batch read` payload for one equality-filtered query per observed
  string event-property group, with cross-group aggregation explicitly disabled.
  A zero `init_num` now yields null percentages instead of a fabricated 0% rate.
- Retention no longer compiles or retries two native `SumCount` follow-up
  shapes whose cohort value semantics are unverified. The compact/raw
  preflight stops before metadata or query dispatch with the named
  `RETENTION_ADDITIVE_FOLLOWUP_COHORT_PATH_UNVERIFIED` gap; ordinary Retention
  counts remain executable, while additive placeholders are represented as
  `unmeasured`/`null` rather than a plausible zero. Result notes and the
  [cohort alternatives guide](docs/guides/retention-cohort-alternatives.md)
  distinguish count, sum, per-cohort-user, and per-returning-user denominators.
- Custom-event first-exposure discovery now returns a named capability gap with
  the exact known cross-product boundary and the bounded paired receipt needed
  to close it. The aggregate alternatives guide includes the positive/negative
  static-window definition, explains why Funnel cannot supply the NOT-before
  set without forbidden persistence, and explicitly rejects ordinary
  event-date Retention as an equivalent estimator.
- Registered SQL product results now separate execution status from data
  completeness. Each successful item reports whether its declared `max_rows` was
  reached and returns canonical `complete|unknown` completeness; an exact cap hit
  without an independent total is `possible_truncation` with a bounded warning,
  while the existing N+1 over-fetch still fails closed when an extra row is
  observed. Readiness and immutable Evidence binding remain separate from this
  per-query completeness signal.
- `gravity sql verify` no longer discards an already-verified product prefix when
  a later registered product remains HTTP-rate-limited after the shared runtime's
  bounded retries. Verification is sequential, the final 429 emits a typed
  `RATE_LIMITED` receipt with a maximum 30-second `retry_after_ms`, and the exact
  prefix is atomically checkpointed under workspace state. `--resume` validates
  the date, datasource, configured order, component SQL/contract hashes, and the
  failed product before continuing. Partial checkpoints cannot be published as
  readiness; completed Evidence distinguishes a single run from segmented
  completion and preserves each segment's time and product scope.
- `gravity sql verify` failures now emit the dedicated, redacted
  `gravity.sql-verification-result.v1` receipt instead of collapsing shared SQL
  diagnostics into generic exception text. Engine rejection, non-tabular response,
  and final rate limiting expose the same SQL stage/class/code source as `sql query`,
  bounded logical-request and elapsed evidence, retryability, engine reachability,
  sanitized protocol status, and a fixed safe next action. Internal resume checkpoints
  retain the full strict prefix, while terminal output exposes only progress counts;
  failed verification still cannot publish Evidence or claim readiness.
- Remaining SQL CLI boundary failures no longer discard command stage,
  retryability, upstream/engine reachability, bounded zero-request evidence, or
  the safe next action. An AST-enforced repository gate now rejects new
  exception-to-plain-text CLI handlers; reviewed no-benefit cases require an
  exact path, line, detector, handler hash, reason, and review expiry.

## [0.3.7] - 2026-09-04

### Breaking changes

- None.

### Fixed

- Funnel queries no longer answer a grouped question with an ungrouped total.
  When upstream could not honour a requested user-property `group_by_list`, it
  returned date-priority aggregates instead; those carry finite numbers, so a
  caller checking only the status read the whole-funnel total as if it were the
  grouped answer. The date values under Funnel's `group` container were admitted
  by the global date-key opening — that bypass is closed, scalar projection is
  now path-aware, and a non-empty Funnel result that lost its requested grouping
  is raised as breaking drift (`ok=false`, `status=contract_changed`) naming the
  dropped fields. The error carries a verified workaround; see
  [Funnel grouping alternatives](docs/guides/funnel-grouping-alternatives.md).
  Requests that keep their grouping, and every non-Funnel shape, are unchanged.
- Total-grain event queries no longer return an apparently successful metric
  table containing only dimension labels. The registered `cnt` measure was
  stripped as an unregistered response key while the call still reported
  `ok=true`, so a missing value could be read as zero. `cnt` is now registered
  at its exact path, every leaf dimension row is checked for a finite numeric
  measure, and a missing or invalid one is raised as breaking drift
  (`ok=false`, `status=contract_changed`). Responses that previously looked
  successful but carried no measure now fail closed instead. Wrong-level `cnt`
  and other unregistered keys are still stripped, and daily projection is
  unchanged.
- `gravity maturity score` no longer reports the correctness/surface-parity and
  architecture/token dimensions as unmeasurable. The isolated quality-profile
  subprocess printed a diagnostic report to stdout ahead of its JSON payload, so
  whole-document parsing failed while the subprocess still exited zero — an
  unexplained `None` indistinguishable from missing data. The report now goes to
  stderr, stdout carries exactly one machine-readable document, and parse failures
  surface an explicit reason in each dimension's `missing` instead of being swallowed.
- The Skill maturity dimension now derives Method Complete from the current report
  generated at scoring time rather than an absent manifest field, so
  `skill_semantic_operator_context` is measurable. The report carries a deterministic
  hash of the manifest set it read; a missing, failed or count-mismatched report keeps
  the dimension `measured=false` instead of reporting a stale conclusion.
- Upstream drift is measurable again. The census workflow now publishes a dedicated
  current-state artifact after a complete crawl, and `census status` / `maturity score`
  read it from an ignored local directory. Evidence older than 26 hours, or stamped
  more than five minutes in the future, is rejected as expired rather than silently
  accepted.

### Added

- `gravity analysis dashboard kanban schema` now publishes typed collection
  constraints, and separates a single-request batch bound (`report_ids`,
  1..20, scope `single_action_request`) from total board capacity (decoded
  `ui_config`, 20 items, scope `dashboard_total_layout`) with an explicit
  `request_splitting_increases_capacity=false`. Provenance reports
  `upstream_limit_verified=false`: the limit is a governed SDK wire contract
  and has never been observed enforced upstream.
- `gravity analysis dashboard kanban prepare` plans an entire board — saved
  definitions, notes and an existing or new target — before the first write.
  It returns per-chart artifact compatibility, reuse/create/update decisions,
  desired/existing/final counts, remaining capacity, an actions DAG with
  deferred-ID references, and bounded read/write estimates, while performing
  zero mutations.
- Capability Trust and Data Quality can now be established from real read-only
  execution instead of remaining permanently `unknown`. Each validation binds an
  exact-operation HTTP receipt and six non-empty checks (receipt, semantic status,
  non-empty result, schema/type, freshness, no drift), and expires after 24 hours
  so a stale pass can never stand in for a current one.
- Native saved artifact shapes now cover registration-day payer retention, a
  disjoint first-payment retention cohort, a custom-only average-duration Event
  and a basic multi-metric Event. Each shape was registered from a real
  `saved prepare` diagnostic rather than inferred, and the two retention
  families keep separate denominators — similar field paths are not treated as
  evidence of shared semantics. Event queries may now declare zero ordinary
  metrics when at least one custom formula metric is present and passes full
  formula validation; both empty still fails closed, and funnel and retention
  keep their two-item minimum.

## [0.3.6] - 2026-09-03

### Breaking changes

- None.

### Fixed

- Static HTTPS Skill Hub Sources may now declare a bounded redirect-host allowlist.
  Runtime follows at most one HTTPS redirect to an exact declared host while retaining
  response-size and artifact-digest checks. This makes GitHub Release-backed Sources
  usable without enabling arbitrary redirects; `skill-library-v4` is the corrected
  immutable publication channel.

## [0.3.5] - 2026-09-02

Migration guide: [0.3.5](docs/migration/0.3.5.md)

### Breaking changes

- **Hard break:** Runtime wheel 不再携带或公开解析项目特定的 Built-in Skill；
  `LocalSkillResolver` 与 `gravity skills export-agent` 已移除，execution snapshot 的
  Skill resolution 只接受精确项目 lock。`gravity skills list/show` 现在必须指定
  `--state-root` 并读取已同步 Hub。R01 获客成本异常定位保留原 Journey、Plan owner、
  claims 和失败关闭能力，但项目必须提供 `gravity.skills.lock.json` 与已核验 CAS。

### Added

- `skill-library-v3` 将 AP 成本异常定位作为第 44 个 canonical Skill，通过 Runtime Hub
  与 Agent Skill 两种确定性投影分发，并达到 17/17 Method Complete。

### Changed

- MCP Skill inspection 与 `gravity://catalog/skills` 统一读取 workspace 的已同步 Hub 状态；
  wheel 内置业务 Skill 数归零。
- R01 execution snapshot 新增强制的 project lock、Hub source 和 package digest 绑定；
  缺 lock、CAS、来源或摘要时在目标请求前返回稳定 Hub gap。

### Removed

- 删除 wheel-owned AP Skill manifest/package tree 及其单独生成器，避免 Runtime Core 与
  Skill Library 形成两套业务方法分发权威。

## [0.3.4] - 2026-09-02

Migration guide: [0.3.4](docs/migration/0.3.4.md)

### Breaking changes

- **Hard break:** Agent Skill export 不再生成 Codex 不支持的顶层 `compatibility` frontmatter；
  原运行时版本约束迁移到 `metadata.gravity-runtime-requires`。直接解析导出 frontmatter 的消费方
  必须改读新位置；方法、版本约束值和 Runtime 执行能力均未丢失。

### Added

- Skill Library 为每个 canonical Skill 确定性生成标准 Agent Skill 目录、可复现 ZIP、
  `gravity.agent-skill-index.v1` 及其可离线验证 schema。
- 新增 `skill-library-v2` 发布通道承载 43 项 Method Complete 方法、Runtime-owned
  Operator/Model 依赖和项目 Semantic/Context 填充模板；v1 资产保持不变。

### Changed

- Skill Library build receipt 升级为 v2，分开完整本地 QA tree 与 GitHub Release 的扁平
  `release_assets`；Runtime 与 Agent archive 使用 Release 可直接寻址的全局唯一资产名。

### Fixed

- 修复 `gravity skills export-agent` 生成的 `SKILL.md` 会被当前 Codex validator 因未知
  `compatibility` 键拒绝的问题，并补齐执行前依赖/readiness 与结论前 claim policy 的渐进披露入口。

## [0.3.3] - 2026-09-01

Migration guide: [0.3.3](docs/migration/0.3.3.md)

### Breaking changes

- **Hard break:** Python 导入根从 `gravity_sdk` 改为 `gravity_insight`。PyPI 分发名在
  0.3.2 已经是 `gravity-insight`，`gravity` CLI 名也没有改变；只用 CLI 的消费方不受
  影响，但 Python import 没有兼容 shim。
- **Soft break:** auto-upgrade 的三个主环境变量从 `GRAVITY_SDK_*` 改为
  `GRAVITY_INSIGHT_*`。0.3.3 仍读取旧名作为 fallback，新名与旧名并存时新名优先；
  fallback 的移除版本尚未确定。
- **Hard break:** 安装诊断 JSON 的 `schema_version` 从
  `gravity-sdk.doctor.v1` / `gravity-sdk.install-consistency.v1` 改为
  `gravity-insight.doctor.v2` / `gravity-insight.install-consistency.v2`。解析这些值做
  分支的消费方必须同步更新；`gravity.*` 工具与门禁命名空间没有改变。

### Added

- 增加随 wheel 分发的 `gravity.release-compatibility.v1` 机器契约、稳定读取 API 与
  CHANGELOG 派生门禁，离线消费方可区分硬破坏、软破坏和历史未知状态。
- 增加 user-detail aggregate 的 Direct、Plan 与 Agent 交付面，并补齐请求约束、分页
  完整性和错误分类（#43、#53）。
- 增加受治理的素材文件获取、留存替代路线、批量分析闭环，以及 event analysis 的
  `hour` 时间粒度（#38、#40、#41、#42、#47）。
- 增加 Context authority 分层及外部 context provider 的约束与测试（#56）。
- 登记 Gravity SQL 探索快车道，并增加 schema/plan、分页、proof obligation 与晋级
  校验（#57）。
- 用仓库内 canonical skill library 和 source registry 取代 vendor mirror，并把确定性
  生成检查接入集成验证（#54）。

### Changed

- Python 包、console entry point、文档与安装 wheel 检查统一使用 `gravity_insight`
  import root；分发名和 `gravity` CLI 保持不变（#44）。
- 收敛 Agent Runtime 的当前架构来源，增加 canonical architecture 文档门禁并移除已
  退休的逐需求历史副本（#58）。
- 强化 release provenance、离线 wheel surface、canonical consumer ancestry 与恢复
  路径验证（#52）。
- 补齐 CODEOWNERS、安全报告与行为准则中的治理联系信息（#51）。

### Fixed

- Direct/Plan 的 user-detail aggregate 结果与分页完整性现在由同一 parity 约束校验，
  避免 Plan 丢失 Direct surface 字段（#53）。
- Census 把 HTTP、payload、写盘和 drift failure 分成稳定的失败类别，并保留 last-known-
  good 行为；相应分类进入 adaptive governor（#55）。
- 并发测试改用同步 rendezvous/隔离输出，降低把竞态当成通过或随机失败的风险（#35）。

## [0.3.2] - 2026-08-29

### Breaking changes

- 未记录。现存 tag 注释与 `v0.3.1..v0.3.2` 提交历史没有给出可可靠复原的破坏性变更清单。

### Added

- 增加 control-plane Ed25519 信任根校验；缺少可选校验依赖时 fail closed。
- 增加 plan-only 的显式 opt-in auto-upgrade 生命周期；Runtime 只生成外部 Installer plan，
  不自行安装或重启。
- 增加绑定 exact HEAD 的 integrated validation receipt，以及单测耗时预算门禁。

### Changed

- 并行化 pytest、分片 unittest，并缓存离线 wheel 与仓库级分析输入。

### Fixed

- malformed credential expiry 不再形成无界或静默延长的凭据有效期。
- canonical consumer revision 改为 main 可达的固定提交，并增加 ancestry fail-closed 检查。

> 历史完整性：本条由 annotated tag `v0.3.2`、`git log v0.3.1..v0.3.2` 和 PyPI
> 首次上传时间反推；无法由这些来源确认的变化均视为“未记录”。

## [0.3.1] - 2026-08-27

### Breaking changes

- 未记录。首个 tag 之前没有可用的维护型 changelog，不能可靠复原破坏性变更清单。

### Added

- 首个带 tag 的 `gravity-insight` 分发版本。该版本安装的 Python import root 仍是
  `gravity_sdk`，console entry point 为 `gravity = gravity_sdk.__main__:main`。

> 历史完整性：本条只记录 annotated tag `v0.3.1` 与 PyPI 首次上传能够证明的事实；
> 更早的功能明细未记录。
