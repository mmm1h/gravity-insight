# Release Gate

## One-click release cut

- Merge consumer-facing changelog and migration edits through normal PRs first.
  `pyproject.toml` and Unreleased target must match; a placeholder-only release is refused.
- Complete [owner setup](owner-actions.md#release-cut-setup-and-key-lifecycle).
- In Actions, choose **Release cut**, **Run workflow**, branch **main**; optionally
  supply `version` (must equal main's package version). Or run:

  ```sh
  gh workflow run release-cut.yml --ref main
  gh workflow run release-cut.yml --ref main -f version=0.3.28 -f dry_run=true
  ```

- Prepare moves Unreleased into a dated release using Asia/Shanghai, appends only
  its digest, and runs compatibility/harness generators. A bot commit A is pushed
  to `release-cut/vV/prepare`; exact-SHA dispatch CI must report `ci-required` success.
- Promote fast-forwards main to A without force, then requires successful exact-SHA
  **push/main** CI. Tag rechecks main=A and pushes annotated `vV`; the unchanged
  tag-push `release.yml` is the only publication path.
- Open train waits for the whole release run to succeed, generates B on A (only
  the next-patch package bump), validates B locally and through branch dispatch CI,
  then fast-forwards main to B. Do not merge other changes between tagging and B.
- Resume by re-running the cut. It fetches main/tags/retained candidate branches,
  reconstructs candidate trees, and uses exact workflow/event/branch/SHA runs.
  A on main resumes push-CI/tag; an existing tag resumes release/train; B on main
  reports done. A supplied version still must match current main, including after B;
  if an old explicit input no longer matches, dispatch again without it.
- Failed CI/release runs are not silently replaced. Re-run their failed jobs, then
  retry the cut. Missing runs time out; rejected promotion or unexpected main/tag
  state stops without force, retagging or rebasing. Retain real candidate branches
  until completion for recovery; if abandoning an unpromoted candidate, inspect
  and remove its branch before starting from changed main.
- Follow the existing [release recovery](owner-actions.md#publishing) for partial
  publication; GitHub-only recovery does not replace the required successful tag
  push run. Never delete/recreate a published tag to trigger a new run.
- Dry run prepares A on a unique `release-cut/dry-run/<run>-<attempt>` branch and
  waits for green dispatch CI, then builds/checks B locally. It never promotes main
  or creates tags. Both `finally` and an `always()` step delete the remote dry ref;
  after runner loss, inspect and delete that exact ref manually. It reports the
  actions a real run would take; it does not prove tag publication.
- All pushes use the environment deploy key; the token only dispatches/reads Actions.
  Candidate branches do not match CI push filters, so CI is explicitly dispatched.
  Main pushes trigger CI; the tag push triggers release. Polling and job timeouts
  are bounded; the non-cancelling cut group serializes cuts, not other main writers.

## Publication boundary

- Keep `release.yml` as the only publish path. Require protected main, identical tag/checkout/API/main SHA, and successful exact-SHA push/main CI with unique `ci-required`.
- Run supply-chain controls and fresh exact-tag Integrated Validation in `release-supply-chain`; validate the intended wheel on all five surfaces and the pinned canonical consumer, plus changelog/migration declarations. Both verify-ci and supply-chain gate OIDC publish.
- Use an independent `.venv` and local main checkout of the proven tag SHA for IV. Require an exact-SHA, non-trial receipt with every gate and zero skips; dispatch measurement/recovery cannot substitute for these publish gates.
- Fail closed on missing tooling, incomplete history, secret findings, artifact-install failure, invalid SBOM, unavailable/incomplete advisory results, vulnerabilities, or mismatched evidence. No warning-only supply-chain outcomes.
- The aggregate re-parses receipts, recomputes distribution hashes, and binds wheel/sdist, SBOM, audit, surface, consumer, changelog/migration, CI, secret-history, protected-main and IV facts. Provenance remains `deferred_post_publish` until OIDC attestations exist; finalize-release verifies it before GitHub Release reconciliation.

## Declared step coverage

- Job success alone is insufficient. Give each supply-chain step a stable ID; the builder checks the fixed prerequisite inventory against workflow drift tests and requires coverage-prepublish plus the current run ID/attempt.
- Aggregate with `always()`: measure runs with skipped gates fail aggregation and cannot emit a passing release-gate receipt. The read-only measurement tail may inspect published assets after verify-ci, but cannot authorize publish.
- Record raw `steps.*.outcome`, never the continue-on-error-adjusted conclusion. Bind `gravity.context-bound-measurement.v1` observations to workflow/job/step, scope, SHA, event, run and attempt; re-resolve observations rather than trusting summaries.
- Missing/skipped is `not_measured`; failed/cancelled/malformed/future is `invalid`; wrong context is `not_applicable`; older than 24 hours is `expired`. Only every prerequisite `measured` with outcome `success` in a push run passes.
- List expected, ran, skipped, missing and excluded IDs. Prepublish excludes its observer and later operations; final includes aggregation/distribution upload but excludes its own observer and subsequent evidence upload. No observation attests future completion.
- Upload diagnostic evidence with `always()`. Checkout/Python/upload failure may leave no artifact; absence never passes. These are trusted-workflow observations, not cryptographic proof of execution or a replacement for receipt/provenance validation.

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
