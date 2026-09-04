# Release Gate

The tag workflow is the publication boundary. Supply-chain controls run in the
Ubuntu `release-supply-chain` job, and the tagged commit's CI evidence is
re-checked by `verify-ci`; both gate the OIDC `publish` job. They are hard
failures: a missing scanner/tool, incomplete Git history, unreviewed secret
candidate, failed artifact install, invalid or incomplete SBOM, unreachable
advisory service, incomplete audit response, or reported vulnerability blocks
publish. There are no warning-only supply-chain outcomes.

`verify-ci` only accepts a CI run for the identical commit SHA that ran on
`main` from a `push` event, succeeded, and reported `ci-required`. A missing or
mismatched run fails the release rather than publishing on stale evidence.
`ci-required` is the single aggregated branch-protection check; individual
failures still surface in their own named jobs.

## J5 timing receipt

The v0.3.7 tag run `33794176327` (2026-09-03) reached PyPI's recorded wheel
upload in 76s and sdist upload in 78s. `verify-ci` and `release-supply-chain`
ran in parallel for 17s and 50s; publish then ran for 26s. The workflow's first
successful post-publish API verification completed about 136s after the tag,
and GitHub Release reconciliation completed the workflow at 152s. Publish must
continue to wait for both exact-SHA CI evidence and checked distributions.
Inside supply-chain, Twine check, SBOM generation, and dependency audit could
be split after the shared build, but the receipt shows only about four seconds
outside the 14s SBOM critical branch, so the extra artifact/job coordination is
not currently justified.

Main CI run `33872829080` spent 429s in the complete-history scan (447s for the
job), making it the critical path. PRs now use the bounded commit-range scan;
`main`/`dev` pushes retain the full scan, which is stronger than a merely
periodic sweep and preserves the exact-SHA release evidence contract.

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
worktree files. Pull requests scan that complete tracked tree plus every added
line in every commit from the base merge point through `HEAD`; this still finds
a credential committed and deleted within the PR. `main`/`dev` pushes scan the
complete text history. Release accepts only an exact-SHA successful `main` push
receipt with `history_included=true`, so incremental PR evidence can never be
promoted as release evidence. The local ignored `.env.gravity.local` is
therefore not read; if such a file is ever committed, it enters tracked and
history scope and blocks the gate.
Generic entropy detectors are excluded because immutable digests and encrypted
evaluation blobs create thousands of non-credential candidates. Reviewed
synthetic-test exceptions bind path, detector and secret hash and require a
specific reason plus review expiry.

## Section 5.9 status

This is a current implementation audit, not a claim that the full release gate
is complete.

| Required item | Status | Evidence / missing enforcement |
| --- | --- | --- |
| protected `main` | partial | Branch policy is recorded, but `release.yml` does not prove the tagged commit equals protected `main`. |
| Integrated Validation | partial | `run_integrated_validation.py` receipts exact-HEAD gates and now includes all three supply controls; `release.yml` does not consume a green receipt. |
| wheel + sdist | implemented | `python -m build`, Twine check, and artifact upload require both distributions. |
| non-editable install | partial | SBOM generation installs both artifacts non-editably; the release job does not run the installed-wheel surface matrix. |
| canonical consumer | partial | Installed canonical-consumer validation exists in Integrated Validation but is not invoked or receipted by `release.yml`. |
| journey certifications | partial | Journey ledger/checks exist in Integrated Validation; the tag workflow has no explicit certification artifact. |
| provenance | implemented | OIDC Trusted Publishing emits attestations and the post-publish job verifies both PyPI file classes; GitHub Release waits for that verification. |
| SBOM | implemented | Separate artifact-bound CycloneDX 1.6 documents are generated for wheel and sdist and attached to GitHub Release. |
| dependency audit | implemented | The isolated wheel runtime closure is audited against OSV before publish; unavailable data or findings block. |
| changelog | partial | GitHub generates release notes, but no maintained changelog or pre-publish changelog check exists. |
| migration | partial | Consumer migration policy and tests exist; the tag workflow does not require a migration declaration/result. |
| release receipt | partial | Integrated Validation and supply checks produce receipts, but no aggregate pre-publish release receipt binds every required item. |

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
