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

- The install channel is an immutable `v<version>` tag cut from protected `main`.
- `v0.3.2` was cut from the promoted `main` tree on 2026-08-29. R10 remains a
  bounded pilot; publishing the release did not satisfy its separate graduation
  criteria. The package source has since advanced beyond that tag.
- `pyproject.toml` now uses the confirmed repository and issue URLs under
  `https://github.com/mmm1h/gravity-sdk`.
- `authors`/`maintainers` use `mmm1h`; owner confirmed 2026-08-28 that this is an
  individual account and the intended publishing identity. `owner_review: confirmed`.
- The pending PyPI trusted publisher binds `gravity-insight` to repository
  `mmm1h/gravity-sdk`, workflow `release.yml`, and environment `pypi`. Releases use
  OIDC, so `PYPI_API_TOKEN` remains unset. Artifact signing stays undecided and
  unsigned. `owner_review: confirmed` for publishing; `owner_review: pending` for signing.

## Repository controls

- `main` is protected: no direct pushes or force pushes; changes merge through PRs.
- The required status check is the existing Windows `test` job. Do not weaken it.
- Replace `@<GITHUB_CODEOWNER>` in `.github/CODEOWNERS` before enforcing code
  ownership.

## Governance contacts

- Replace `<SECURITY_CONTACT>` in `SECURITY.md` with an approved private
  security reporting channel.
- Replace `<CONDUCT_CONTACT>` in `CODE_OF_CONDUCT.md` with an approved private
  conduct reporting channel.

## Findings measured once, not yet wired into CI

CI gained no new jobs — Linux runners were declined and every candidate job (wheel
smoke, Ruff, dependency audit, secret scan) targeted `ubuntu-latest`. These ran
locally on 2026-08-20 instead, so the facts are known but nothing enforces them.
The `pip-audit` finding was independently re-measured; the other counts are leads.

| Check | Result | Follow-up |
|---|---|---|
| wheel + sdist build | 1 wheel, 1 sdist; all 4 sampled package-data files present | none — packaging is not currently dropping contract/manifest/census data |
| Ruff, default rules | 1276 findings | not triaged; out of scope this round |
| Ruff, `F` (pyflakes) only | 69 findings | worth a pass — `F` catches unused imports and undefined names, not style |
| pip-audit | `PYSEC-2026-2275` is real; `requests==2.32.5` was affected and `2.33.0` fixes it | upgraded both exact pins to `2.33.0`; this SDK does not call the sole affected API, `extract_zipped_paths()`; range-based library pinning remains an owner decision |

The advisory covers all Requests before `2.33.0` but only exposes callers of
`requests.utils.extract_zipped_paths()`; this SDK has none, so the completed bump
was routine maintenance, not an emergency mitigation. Pins stay exact and
synchronized — moving to compatible ranges changes downstream installs and needs
a separate owner decision.
