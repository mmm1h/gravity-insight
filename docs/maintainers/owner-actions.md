# Release Governance Owner Actions

Placeholders in governance and package metadata must be replaced before any
external release or enforcement. Decisions already made are recorded here so
they are not re-litigated.

## License — decided: no external-use grant (2026-08-20)

The repository wraps a **private** Gravity API. Granting anyone an OSI license
to use it would be this repository answering an authorization question that
belongs to the upstream platform, not to us. An OSI grant is also irreversible
for the versions it covers, whereas withholding one can be reversed at any time.

Therefore: no `LICENSE` file, and `pyproject.toml` carries no `license` field.
`COPYRIGHT.md` states the position explicitly so that "no license" reads as a
decision rather than an oversight.

Revisit this if the project is ever offered for outside use; Apache-2.0 would be
the natural choice at that point (patent and trademark clauses beyond MIT's).

## Publishing

- The install channel is an immutable `v<version>` tag. Tags are cut from `dev`
  now and from `main` after the future dev-to-main promotion; the channel itself
  is not bound to either branch.
- `pyproject.toml` now uses the confirmed repository and issue URLs under
  `https://github.com/mmm1h/gravity-sdk`.
- `authors` and `maintainers` use `mmm1h`, inferred only from the confirmed
  repository owner. `agent_under_standing_owner_delegation`; `owner_review: pending`.
- The tag workflow uploads to PyPI only when `PYPI_API_TOKEN` is configured.
  Confirm that `gravity-sdk` is controlled by the owner on PyPI, provision the
  secret if publishing is intended, and decide whether artifacts must be signed.
  `agent_under_standing_owner_delegation`; `owner_review: pending`.

## Repository controls

- Configure branch protection: prohibit direct pushes, require pull requests,
  require selected CI checks, and restrict force pushes.
- Select required checks. Today the only candidate is the existing Windows test
  job.
- Replace `@<GITHUB_CODEOWNER>` in `.github/CODEOWNERS` before enforcing code
  ownership.

## Governance contacts

- Replace `<SECURITY_CONTACT>` in `SECURITY.md` with an approved private
  security reporting channel.
- Replace `<CONDUCT_CONTACT>` in `CODE_OF_CONDUCT.md` with an approved private
  conduct reporting channel.

## Findings measured once, not yet wired into CI

CI gained no new jobs this round — Linux runners were declined, and every
candidate job (wheel smoke, Ruff, dependency audit, secret scan) was written
against `ubuntu-latest`. The checks were run locally instead, so the facts are
known even though nothing enforces them yet.

Reported by the executing agent on 2026-08-20. The `pip-audit` finding below
was independently re-measured; the remaining counts are leads rather than
settled counts.

| Check | Result | Follow-up |
|---|---|---|
| wheel + sdist build | 1 wheel, 1 sdist; all 4 sampled package-data files present | none — packaging is not currently dropping contract/manifest/census data |
| Ruff, default rules | 1276 findings | not triaged; out of scope this round |
| Ruff, `F` (pyflakes) only | 69 findings | worth a pass — `F` catches unused imports and undefined names, not style |
| pip-audit | `PYSEC-2026-2275` is real; `requests==2.32.5` was affected and `2.33.0` fixes it | upgraded both exact pins to `2.33.0`; this SDK does not call the sole affected API, `extract_zipped_paths()`; range-based library pinning remains an owner decision |

The dependency advisory applies to all Requests releases before `2.33.0`, but
only applications that directly call `requests.utils.extract_zipped_paths()`
are exposed. This SDK has no such call, so the completed bump is routine
dependency maintenance rather than an emergency runtime mitigation. The
runtime pins remain exact and synchronized; changing the library pin policy to
a compatible range would alter downstream installation behavior and needs a
separate owner decision.
