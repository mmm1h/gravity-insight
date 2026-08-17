# AGENTS.md

## Product goal

Every data-analysis task must be completable without opening Gravity Web, using
this repository alone. Agents are first-class consumers: discovery, execution,
and error classification stay machine-decidable. Progress is measured in closed
analysis journeys, not in operation counts. See `docs/roadmap.md` for the
current schedule, parallelism constraints, and the explicit non-goals.

## Repository scope

This repository owns the standalone Gravity SDK: Insight reads/exports, custom
SQL reads and pagination, route census, contracts, probes, and their quality
and privacy gates. Business-specific analysis and campaign strategy do not
belong here.

## Development principles

- **Implementation volume stays well above test volume.** Each change adds at
  most one third as many test lines as source lines. Cover contract boundaries,
  fail-closed paths, and one happy path; do not enumerate branches or write
  large fixture snapshots.
- **Prefer concurrency wherever reads are independent.** Reuse the existing
  bounded worker pool and budget. Never raise a per-adapter worker count on top
  of the global pool; that multiplies concurrency. Keep total upstream request
  volume at `1x` and raise only peak in-flight count.
- **Do not replicate Gravity Web UI concepts.** Layout, favourites, drag-and-drop,
  and member permission management are permanently out of scope.
- **Do not over-engineer.** No plugin mechanisms, registries, dependency
  injection, or abstraction layers for a single call site. Reuse the existing
  composite / plan adapter / agent card triad. When a central entry point nears
  its ratchet, add a narrow domain family router instead.
- **Opportunistic cleanup only in files the current change already touches.**
  Do not open standalone refactor branches.
- **A breaking surface change must not cost capability.** Direct breaking
  upgrades are allowed, but first prove no read capability is lost; record the
  finding in `docs/roadmap.md`.
- **Each round starts with a written proposal, and its conclusions land in
  version control.** Record them in the existing authoritative documents:
  `docs/roadmap.md` for schedule and decisions, `technical-debt.md` for
  structural debt, `candidate-capability-matrix.md` for capability evidence.
  Do not create one-off proposal files or a `docs/proposals/` tree. A survey
  that is useful today is stale two rounds later, and the documentation tree
  would pay for it forever. Keep the working draft in `tmp/`; land the verdict.

## Parallel development

Independent units develop on separate `codex/<unit>` branches and merge back to
`dev` once green. Do not split one unit across branches by phase; core, surface,
and agent handoff have ordering dependencies.

The shared spine is `plan_adapters.py`, `agent_capabilities.py`,
`agent_composite.py`, `agent_handoff.py`, `cli.py`, and `__main__.py`. All nine
delivered product lines modified the first four. Treat these files as
append-only, and serialize the final wiring of every unit that touches them
through a single integrator. Domain cores, contract research, and evidence
gathering may run fully in parallel. Regenerate compiler, provenance, and
coverage artifacts serially.

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

- Start at `docs/index.md`; do not read the documentation tree front to back.
- Querying agents follow `docs/agent-workflow.md`.
- SDK changes start at `docs/maintainers/index.md` and then read only the
  task-specific maintainer page.
- Business modules, campaign semantics, and tracking bindings belong in the
  calling product knowledge base, not in this repository.

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
