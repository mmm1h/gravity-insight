# AGENTS.md

**先选路，再往下读。**

- **要用这个 SDK 取数分析** → [团队上手包](docs/team-onboarding.md)。最短命令：`$env:PYTHONPATH='src'; python -m gravity_insight agent-catalog categories`。不要通读本文。
- **要修改这个仓库** → 继续读下面的开发约束；已知 Issue、Journey、Skill、selector 或 changed files 时，先运行 `python scripts/task_context.py --help`，只读生成的 L1-L3 最小引用。History/Archive 默认不加载。

## Product goal

This repository is the implementation home of Gravity Agent Runtime. Every
supported data-analysis task must be completable without opening Gravity Web,
using the installed Runtime and its explicitly locked project artifacts. Agents
are first-class consumers: discovery, execution, trust, completeness, method,
context, and error classification stay machine-decidable. Progress is measured
in closed analysis journeys, not in operation, Skill, or registry counts. See
`docs/roadmap.md` and `specs/agent-runtime/index.md` for the current schedule,
dependency graph, parallelism constraints, and explicit non-goals.

## Repository scope

This repository owns the governed Runtime plane and its external control-plane
clients: Insight reads/exports, registered and isolated SQL products, route
census, contracts, probes, trust/data-quality/privacy gates, versioned Skills,
reusable Semantic types/schemas/common definitions, Operator/Model contracts,
bounded Context, governed Action and Artifact handoff, and their agent-facing
CLI/SDK/Plan/MCP surfaces. Runtime owns versioned URIs plus unit, additivity,
time-grain, dependency, conflict and formula-structure validation. Reusable
industry methods may live here; concrete game activity names, SKU values,
tracking/App bindings, project formula parameters/effective windows, department
reporting language, and campaign decisions remain in the calling project.

## Development principles

- **Tests buy risk coverage, not line count.** There is no fixed test-to-source
  ratio; a cap penalises exactly the units whose value *is* the test, such as
  identity isolation or pagination completeness. Cover the risks a change
  touches: stable contract boundaries, fail-closed paths, semantic rejection
  remedies, mutation preview/readback, pagination completeness, the public API
  snapshot, and multi-account isolation. The original prohibition still stands:
  do not enumerate branches, do not write large fixture snapshots, and do not
  add an assertion that restates the one above it.
- **Prefer concurrency wherever reads are independent.** Reuse the existing
  bounded worker pool and budget. Never raise a per-adapter worker count on top
  of the global pool; that multiplies concurrency. Keep total upstream request
  volume at `1x` and raise only peak in-flight count.
- **Do not replicate Gravity Web UI concepts.** Layout, favourites, drag-and-drop,
  and member permission management are permanently out of scope.
- **Use controlled extension types only.** The approved Runtime architecture may
  add typed Skill, Semantic, Operator/Model, Context Provider, and Action
  Connector registries when their requirement is ready. Do not build a generic
  executable plugin mechanism, dependency-injection framework, or abstraction
  for a single call site. Reuse the existing composite / plan adapter / agent
  card triad and keep one execution owner.
- **No unrelated opportunistic refactors.** Cleanup outside the active
  requirement's scope remains prohibited. An approved `ready` Requirement may
  own an explicit structural migration, including a dedicated refactor branch,
  only when its write scope, current-behavior characterization, capability
  preservation, consumer migration, rollback and exit conditions are recorded.
- **A breaking surface change must not cost capability.** Direct breaking
  upgrades are allowed, but first prove no read capability is lost; record the
  finding in `docs/roadmap.md`.
- **Each round starts with a written proposal, and only its current verdict
  lands in long-lived documentation.** Keep the working draft and request
  ledger in `tmp/`; update `docs/roadmap.md` for schedule and decisions,
  `docs/maintainers/technical-debt.md` for structural debt,
  `docs/candidate-capability-matrix.md` for capability evidence, or
  `docs/analysis-journeys.md` for journey state. Approved Agent Runtime
  requirements live only in `specs/agent-runtime/` and must bind the current
  directive; they are delivery contracts, not per-round logs or a second
  architecture. Do not create one-off proposal files, a `docs/proposals/` tree,
  or new per-round archive logs.

## Parallel development

Independent units develop from `main` on separate short-lived `codex/<unit>`
branches and merge through a green PR. Do not split one unit across branches by phase; core, surface,
and agent handoff have ordering dependencies. For a directive-approved
`staged_epic`, each indexed milestone is an independent unit and branch, and
must still deliver its own complete core/surface/handoff slice rather than
splitting that milestone again by implementation phase.

The shared spine is `plan_adapters.py`, `agents/capabilities.py`,
`agents/composite.py`, `agents/handoff.py`, `cli.py`, and `__main__.py`. Preserve
their characterized behavior unless the active requirement explicitly migrates
it; do not create wrappers merely to avoid an approved structural change.
Serialize the final wiring of every unit that touches the spine through a single
integrator. Domain cores, contract research, and evidence gathering may run in
parallel. Regenerate compiler, provenance, and coverage artifacts serially.

## Technical debt

`docs/maintainers/technical-debt.md` records only structural debt provable from
current sources or quality gates. Review it every round: close entries whose
exit condition is met, and compress closed work to a single historical line.
Do not let the list become an archive.

## Entry points

- `gravity insight ...` for governed Insight operations.
- `gravity sql ...` for governed custom-SQL products and exports.
- `gravity census ...` for frontend route census and drift checks.
- Existing Insight commands may be invoked directly as `gravity <command>`.

## Documentation

- Querying / analysis agents start at `docs/team-onboarding.md`; do not read this
  file as a usage guide.
- Start at `docs/index.md` for the task table; do not read the documentation
  tree front to back.
- Querying agents follow `docs/agent-workflow.md` only when executing a specific
  product.
- SDK changes start at `docs/maintainers/index.md` and then read only the
  task-specific maintainer page.
- Gravity Agent Runtime program work also reads
  `specs/agent-runtime/directive.json`, the complete repository-canonical
  `architecture-source.md`, the Requirement Index, and exactly one externally
  approved `ready` requirement. A specification cannot approve itself or
  silently change the parent architecture.
- `docs/archive/` preserves non-normative history and evidence. Never use it as
  the source of current interfaces, schedule, capability state, or debt.
- Runtime owns reusable Semantic types/schemas, common metric/method definitions,
  versioned URIs and generic validation for units, additivity, time, dependencies
  and conflicts. Project-specific activity names, SKU values, tracking/App
  bindings, formula parameters/effective windows, campaign strategy, and final
  reporting language belong in the calling product knowledge base.

## Consumer migration

- Calling-facing SDK/CLI/Plan surfaces may make direct breaking upgrades; do
  not add compatibility aliases, implicit modes, or legacy envelopes solely
  for old consumers.
- In the same release, migrate `work-dashboard` canonical consumers, current
  routing docs, and consumer tests to the new surface. Frozen historical
  reports may retain old commands as historical facts.
- This rule does not weaken upstream operation governance. Operation input and
  response changes still require explicit contract versions, projection and
  privacy review, and fail-closed drift handling.

## Safety

- Read operations use fixed hosts, paths, methods, and manifest contracts.
- Never commit `.env.gravity.local`, tokens, cookies, usernames, passwords, or
  raw user-level output.
- New stable operations require a contract, deterministic manifest compilation,
  projection/privacy review, and tests.
- Production probing must follow `docs/maintainers/probing.md`.

## Validation

`python scripts/task_context.py ...` 返回的 `risk_assessment` 是唯一分级入口；命中多条规则时取
最高风险，未知路径按高风险处理。验证节奏如下：

- 低风险：Self-review + `focused_gate`。
- 中风险：Independent Review + `risk_assessment.selected_commands` 中的 Surface/Consumer 门禁。
- 高风险：Adversarial Review + 下列 Full Gate；干净提交再跑 selected commands 中的 Integrated
  Validation 与离线 canary contract。Release 无论 changed files 都按高风险处理。

Full Gate 只用于高风险或 Release，不作为低/中风险提交的默认前置条件：

```powershell
& ".venv/Scripts/python.exe" -m unittest discover -s tests
& ".venv/Scripts/python.exe" -m pytest -q
& ".venv/Scripts/python.exe" -m gravity_insight.compiler check
& ".venv/Scripts/python.exe" -m gravity_insight.quality check
& ".venv/Scripts/python.exe" -m gravity_insight --help
git diff --check
```

Repository Map 与 package-reference checkpoint 有显式生成顺序；只运行编排入口，禁止倒序手工重建：

```powershell
& ".venv/Scripts/python.exe" scripts/refresh_validation_harnesses.py
& ".venv/Scripts/python.exe" scripts/refresh_validation_harnesses.py --check
```

CI runs `pytest`, not `unittest discover`. Re-derive test and subtest counts on
high-risk/Release rounds from the latest fully green dual-collector gate. The
separate unittest collector is an ablation candidate because pytest already
collects unittest cases; retain it until repeated receipts resolve its net value.

Tests isolate the developer's private cache in `tests/__init__.py`; without it a
machine holding a real metadata cache fails discovery-ordering tests that pass
in CI. Do not remove that isolation, and do not run tests as
`python tests/<file>.py` — that path bypasses package initialization and is not
isolated.

## Branch workflow

- `main` is the only long-lived development and integration branch. It is
  protected: never commit or push directly to it, force-push it, or weaken its
  required `test` status check.
- Create each development worktree on a short-lived branch based on current
  `main`. Give it an ignored `.venv` and editable install, then validate with
  that environment's Python; shared editable interpreters can resolve imports
  from another checkout and produce false results.
- Merge only through a green PR to `main`. `merged_main` means code is on the
  protected trunk but not necessarily released; the retired `fixed_dev` token
  remains only in frozen Agent Runtime delivery evidence.
- Remove a merged worktree and run `git worktree prune` while closing its unit.

## Issue workflow

- Read `docs/maintainers/issues.md` before taking a GitHub issue.
- Only start implementation from `status:ready`; first change it to
  `status:in-progress` and record the short-lived branch/worktree and intended scope.
- Use exactly one `status:*` and one `priority:*` label. Do not close an issue
  before the fix reaches `main`; then close it with `status:released`.
- If evidence is insufficient, use `status:needs-evidence` and state the exact
  missing safe evidence instead of guessing or broadening a contract.
