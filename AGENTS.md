# AGENTS.md

## Repository scope

This repository owns the standalone Gravity SDK: Insight reads/exports, custom
SQL reads and pagination, route census, contracts, probes, and their quality
and privacy gates. Business-specific analysis and campaign strategy do not
belong here.

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
python -m gravity_sdk.compiler check
python -m gravity_sdk.quality check
python -m gravity_sdk --help
git diff --check
```

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

## Issue workflow

- Read `docs/maintainers/issues.md` before taking a GitHub issue.
- Only start implementation from `status:ready`; first change it to
  `status:in-progress` and record the `dev` worktree and intended scope.
- Use exactly one `status:*` and one `priority:*` label. Do not close an issue
  at `status:fixed-dev`; close it only after the fix reaches `main`, then use
  `status:released`.
- If evidence is insufficient, use `status:needs-evidence` and state the exact
  missing safe evidence instead of guessing or broadening a contract.
