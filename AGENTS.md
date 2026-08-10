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
