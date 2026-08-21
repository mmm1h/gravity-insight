# AGENTS.md

**先选路，再往下读。**

- **要用这个 SDK 取数分析** → [团队上手包](docs/team-onboarding.md)。最短命令：`$env:PYTHONPATH='src'; python -m gravity_sdk agent-catalog categories`。不要通读本文。
- **要修改这个仓库** → 继续读下面的开发约束。

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

Independent units develop on separate `codex/<unit>` branches and merge back to
`dev` once green. Do not split one unit across branches by phase; core, surface,
and agent handoff have ordering dependencies. For a directive-approved
`staged_epic`, each indexed milestone is an independent unit and branch, and
must still deliver its own complete core/surface/handoff slice rather than
splitting that milestone again by implementation phase.

The shared spine is `plan_adapters.py`, `agent_capabilities.py`,
`agent_composite.py`, `agent_handoff.py`, `cli.py`, and `__main__.py`. Preserve
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

Run before committing:

```powershell
python -m unittest discover -s tests
python -m pytest -q
python -m gravity_sdk.compiler check
python -m gravity_sdk.quality check
$env:PYTHONPATH='src'; python scripts/agent_usability_eval.py run --split development --output-dir tmp/agent-usability-gate > tmp/agent-usability-gate.log 2>&1; if ($LASTEXITCODE) { exit $LASTEXITCODE }
python -m gravity_sdk --help
git diff --check
```

CI runs `pytest`, not `unittest discover`. The two collect different counts
(946 vs 715 at `8fd278e`) because of how subtests are reported, so a green
`unittest` run alone does not prove CI will pass. Run both.

Tests isolate the developer's private cache in `tests/__init__.py`; without it a
machine holding a real metadata cache fails discovery-ordering tests that pass
in CI. Do not remove that isolation, and do not run tests as
`python tests/<file>.py` — that path bypasses package initialization and is not
isolated.

## Branch workflow

- `main` is the stable integration branch consumed by other projects. Do not
  develop, test, or fix bugs directly on `main`.
- Keep the canonical consumer checkout on `main`. Check out `dev` in a sibling
  worktree (for example `../gravity-sdk-dev`); never switch the consumer
  checkout itself to `dev`.
- Use `dev` for normal development, tests, refactors, and bug fixes. Give each
  development worktree its own ignored `.venv` and editable install, then run
  validation with that environment's Python. A shared editable interpreter may
  still resolve imports from the `main` checkout and produce false test results.
- Promote validated changes from `dev` to `main` only as an explicit release
  action after the required checks pass.
- For the Gravity Agent Runtime program, every executable node and staged-epic
  milestone in `specs/agent-runtime/index.json` remains on `codex/*` branches
  and `dev` until the whole program is complete, integrated validation is green,
  and the user gives a new explicit approval. A single requirement reaching
  `fixed_dev` is never a reason to merge it to `main`.
- Push `dev` to GitHub at the end of every round. Remove a merged worktree and
  run `git worktree prune` as part of closing that unit, not as a later cleanup.

## Issue workflow

- Read `docs/maintainers/issues.md` before taking a GitHub issue.
- Only start implementation from `status:ready`; first change it to
  `status:in-progress` and record the `dev` worktree and intended scope.
- Use exactly one `status:*` and one `priority:*` label. Do not close an issue
  at `status:fixed-dev`; close it only after the fix reaches `main`, then use
  `status:released`.
- If evidence is insufficient, use `status:needs-evidence` and state the exact
  missing safe evidence instead of guessing or broadening a contract.
