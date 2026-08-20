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

- Decide whether to publish to PyPI, the package name, whether internal builds
  need a distinct name or version policy, and whether artifacts must be signed.
- Replace `<PYPI_PACKAGE_OWNER>`, `<PYPI_MAINTAINER>`, and
  `<GITHUB_ORG>/<REPOSITORY>` in `pyproject.toml` with approved metadata.

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

Reported by the executing agent on 2026-08-20; **not yet independently
re-measured**, so treat the numbers as leads rather than settled counts.

| Check | Result | Follow-up |
|---|---|---|
| wheel + sdist build | 1 wheel, 1 sdist; all 4 sampled package-data files present | none — packaging is not currently dropping contract/manifest/census data |
| Ruff, default rules | 1276 findings | not triaged; out of scope this round |
| Ruff, `F` (pyflakes) only | 69 findings | worth a pass — `F` catches unused imports and undefined names, not style |
| pip-audit | `requests==2.32.5` → `PYSEC-2026-2275`, fixed in `2.33.0` | **verify, then decide**: bump the pin, or relax to a range and pin in dev constraints |

The dependency finding is the one with a real deadline. `requirements.txt` pins
`requests` exactly, so the fix is a deliberate bump rather than a resolver
decision. Confirm the advisory applies to how this SDK uses `requests` before
changing the pin, and run the suite after.
