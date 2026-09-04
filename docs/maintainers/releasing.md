# Release Gate

The tag workflow is the publication boundary. `verify-ci` requires GitHub to
report `main` as protected, proves that the tag, checkout, branch API commit,
and current `origin/main` are the same commit, then re-validates the
identical commit's successful `push`/`main` CI run and unique `ci-required` job.
Supply-chain controls and a fresh exact-tag Integrated Validation run execute in
the Ubuntu `release-supply-chain` job. That job validates the intended wheel on
all five surfaces and against the pinned canonical consumer, checks the
release-version changelog and migration declaration, and emits
`release-gate.json`. Both jobs gate the unchanged OIDC `publish` job. They are hard
failures: a missing scanner/tool, incomplete Git history, unreviewed secret
candidate, failed artifact install, invalid or incomplete SBOM, unreachable
advisory service, incomplete audit response, or reported vulnerability blocks
publish. There are no warning-only supply-chain outcomes.

`verify-ci` only accepts a CI run for the identical commit SHA that ran on
`main` from a `push` event, succeeded, and reported `ci-required`. A missing or
mismatched run fails the release rather than publishing on stale evidence.
`ci-required` is the single aggregated branch-protection check; individual
failures still surface in their own named jobs.

Integrated Validation runs again on the tag commit rather than reusing a local
pre-tag receipt. After exact protected-main equivalence is established, the tag
SHA is checked out as a local `main` branch solely to satisfy IV's clean-main
precondition; the receipt must bind that SHA, contain the complete gate set, and
have zero skips. This deliberately adds release latency and avoids a race in
which `main` advances between a pre-tag IV run and tag creation. The tag path
also uses an independent `.venv`; `workflow_dispatch` measurement/recovery never
executes these publish-only gates.

The aggregate pre-publish receipt re-parses every source receipt, recomputes the
wheel/sdist hashes, and requires the SBOM, dependency audit, installed-wheel
matrix, consumer, changelog, migration, CI, secret-history, protected-main, and
IV facts to agree on the release inputs. Provenance remains explicitly
`deferred_post_publish` in that receipt because OIDC attestations do not exist
until publication; `finalize-release` continues to verify them before creating
or reconciling the GitHub Release.

## Independent controls

Run these with the worktree's independent environment. The build inputs must be
the exact wheel and sdist intended for publication.

```powershell
python scripts/scan_repository_secrets.py --history --receipt tmp/secret-scan.json
python scripts/generate_release_sbom.py --dist-dir dist --output-dir tmp/release-sbom
python scripts/audit_release_dependencies.py --dist-dir dist --receipt tmp/dependency-audit.json
```

SBOM generation non-editably installs the wheel and sdist in separate
pip-less temporary environments, resolves the base runtime dependency closure,
and emits validated CycloneDX JSON 1.6. `--output-reproducible` removes the
timestamp and random serial number; each document is then bound to the exact
distribution filename, kind and SHA-256. Dependency resolution state is an
input: exact direct pins do not lock every transitive package forever, so a
changed package index can legitimately change a later SBOM.

Dependency audit non-editably installs the wheel and audits that isolated
runtime environment against OSV. Output that cannot be parsed or does not cover
the installed dependency set is `unable_to_audit`, never zero vulnerabilities.
The wrapper has no vulnerability ignore option. A future exception must name
the CVE/advisory, prove why the affected path is unreachable, name an owner,
and carry a review expiry before an ignore mechanism is added.

Secret scanning uses detect-secrets provider-token, private-key, Basic Auth,
JWT and secret-keyword detectors. It scans `git ls-files`, not arbitrary
worktree files, and release/CI checkouts fetch and scan complete text history.
The local ignored `.env.gravity.local` is therefore not read; if such a file is
ever committed, it enters both tracked and history scope and blocks the gate.
Generic entropy detectors are excluded because immutable digests and encrypted
evaluation blobs create thousands of non-credential candidates. Reviewed
synthetic-test exceptions bind path, detector and secret hash and require a
specific reason plus review expiry.

## Section 5.9 status

This is the current executable enforcement audit. `implemented` means the tag
workflow either runs the check or consumes and re-validates an exact-SHA receipt
before the unchanged `publish` job becomes eligible.

| Required item | Status | Evidence / missing enforcement |
| --- | --- | --- |
| protected `main` | implemented | `check_release_main.py` requires GitHub branch metadata to report `main` as protected and requires its API commit, the checked-out HEAD, pushed version tag, and freshly fetched `origin/main` to resolve to the identical `GITHUB_SHA`; `check_release_ci.py` separately requires the successful exact-SHA `push`/`main` CI run and unique successful `ci-required` job. |
| Integrated Validation | implemented | The tag job creates an independent `.venv`, runs the complete IV set on the proven tag/main SHA, and the aggregate gate requires an exact-SHA non-trial green receipt with zero skipped gates. |
| wheel + sdist | implemented | `python -m build`, Twine check, and artifact upload require both distributions. |
| non-editable install | implemented | SBOM generation still installs both intended artifacts non-editably; the tag job additionally runs and receipts the five-surface matrix against the exact intended wheel hash. |
| canonical consumer | implemented | The public pinned `work-dashboard` revision is checked on `main`, run with strict prerequisites against the exact intended wheel, and bound into both its own receipt and the aggregate release receipt. |
| journey certifications | implemented | The IV artifact explicitly receipts the component index, journey ledger generator, installed-wheel matrix, and promotion readiness; the aggregate receipt requires all four named gates to pass. |
| provenance | implemented | OIDC Trusted Publishing emits attestations and the post-publish job verifies both PyPI file classes; GitHub Release waits for that verification. |
| SBOM | implemented | Separate artifact-bound CycloneDX 1.6 documents are generated for wheel and sdist and attached to GitHub Release. |
| dependency audit | implemented | The isolated wheel runtime closure is audited against OSV before publish; unavailable data or findings block. |
| changelog | implemented | `check_changelog.py --release-version` requires the tag version to equal the project version, validates the matching section and immutable released-section lock, and emits an artifact-bound receipt before publish. |
| migration | implemented | Every release explicitly declares breaking changes or none; a breaking release must provide the version-matched migration guide, whose SHA-256 is bound into the changelog and aggregate receipts. |
| release receipt | implemented | `build_release_gate_receipt.py` fails closed unless every pre-publish item agrees on the exact SHA and intended distribution hashes; the single `release-gate.json` is uploaded with release evidence. |

## R16 owner review

R16 implemented local Ed25519/TUF-style verification and the plan-only external
activation lifecycle on 2026-08-29, then reached the historical
`fixed_dev; owner_review: pending` state. The old requirement ledger was retired
when the program converged; the current Component Index retains
`external-control-plane` as `bounded`, with activation outside Runtime and real
organization key policy still required.

Owner decisions remain open. The Owner must ratify or reject the historical R16
acceptance; decide whether release artifacts remain unsigned beyond PEP 740 or
name the organizational signer; supply trust-root identity, thresholds,
rotation and revocation/expiry policy when Stage B is activated; and name the
external installer/canary/rollback owner. The trigger conditions also need
Owner confirmation when an outside-team consumer, contractual regulation,
artifact revocation, or air-gapped installation first applies.
