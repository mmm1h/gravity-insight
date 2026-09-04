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

Target release: `0.3.9`

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
