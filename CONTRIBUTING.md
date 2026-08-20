# Contributing

This repository is a governed SDK, not a wrapper around the Gravity web UI.
Start at `docs/maintainers/index.md`, read only the maintainer guidance for the
task, and put each round's working proposal in `tmp/`.

Develop on `dev` in a dedicated worktree, not `main`. Keep changes narrowly
scoped. Public SDK, CLI, Plan, and operation capabilities are additive: retain
existing public surfaces and prove that a breaking upgrade loses no read
capability. Do not add compatibility aliases solely for old callers.

Stable operations require explicit contracts, deterministic manifest
compilation, projection and privacy review, and fail-closed drift handling. Do
not commit local credentials, cookies, tokens, usernames, passwords, raw
user-level output, or private evidence. Production probing follows
`docs/maintainers/probing.md`; ordinary development checks stay offline.

Before requesting review, run the validation commands in `AGENTS.md` with
`PYTHONPATH=src`. Run both pytest and unittest discovery. Preserve the quality
ratchet, compiler output, actionable-error counts, and public API surface. CI
green status is necessary but does not replace these local checks.
