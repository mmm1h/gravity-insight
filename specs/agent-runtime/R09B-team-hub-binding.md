# R09B Team Hub Skill Binding

| Field | Value |
| --- | --- |
| Parent directive | `gravity-agent-runtime/v9.1` via `directive.json` |
| Status | `fixed_dev`; integrated and validated on `dev` 2026-08-22 |
| Track | Optional Skill distribution binding |
| Dependencies | R04, R09A |
| Parallel group | `optional-binding` |
| Shared-spine integration | Required and serialized |
| Delivery ledger | This Requirement document; no internal GitHub Issue |
| Baseline | `dev@acdb05ce4c622052b80b34e8a572be8183dde670` |
| Branch / worktree | `codex/r09b-team-hub-binding` / `D:\\git-pjt\\gravity-sdk-wt\\r09b-team-hub-binding` |
| Consumer | Retained R09A stack `work-dashboard@e4369ce8`; non-regression only |
| Integrator | Root Codex agent; shared-spine wiring remains serial |
| Production / Hub requests | `0`; local synthetic Git projects and CAS only |
| Main integration | Frozen until whole program completion |

## Outcome

R09A can resolve and execute a Skill from an exact project lock and verified local CAS without changing Core Skill Runtime semantics or performing Runtime-time Hub network access.

## Plan Owner Verdict And Ready Binding

The user designated the R01 Requirement as the internal delivery ledger and
authorized continuous implementation without repeated Requirement approval.
R04 and R09A are `fixed_dev`; the plan owner reviewed
`tmp/r09b-team-hub-binding-proposal.md` and its architecture-conflict ledger,
bound the baseline/worktree/gates below, advanced R09B through `reviewed` and
`ready` to `in_progress`, then accepted the validated implementation as
`fixed_dev`. This does not authorize production probes,
credentials, Hub requests, writes, package installation, release or `main`
promotion.

- Add one offline `RuntimeSkillResolver`. Built-in identity resolves first as
  `unlocked` and never reads project Team state. Non-Built-in identity requires
  one exact entry in tracked, clean `gravity.skills.lock.json`; no missing Team
  Skill can fall back to Built-in content or a guessed package.
- Require the lock's recomputed digest and exact current Runtime version. Read
  the immutable package from the default read-only
  `<workspace.state_root>/skill-hub-cas`; a missing CAS blocks without creating
  any directory. Reuse R04 `validate_skill_directory` for bounded path, link,
  hardlink, file, Render Model and package validation, then compare URI,
  manifest/package digests, Runtime requirements and dependencies to the lock.
- Extract and reuse one public Skill/Journey parity validator for capabilities,
  Semantic, Operator/Model, required Context, claims, request budget and output
  schema. Both Built-in and locked Team artifacts enter the same R09A Core
  dependency composition; `ReferenceJourneyRunner` remains the only execution
  owner.
- For a locked Skill, require separate trusted-pack coverage only for every
  non-Built-in Operator dependency and every Model dependency. Read tracked
  `gravity.trusted-packs.lock.json` plus local
  `<workspace.state_root>/trusted-packs-installation.json` and delegate exact
  startup verification to R04 `verify_trusted_pack_startup`. Runtime never
  installs, imports, loads entry points or scans global distributions; Core
  registries still decide actual Operator/Model availability.
- Extend the execution snapshot Skill reference with nullable exact Team lock,
  Hub source and Trusted Pack lock/state/verification digests. Built-in values
  are explicitly null. Local paths, installation times, credentials and
  business values cannot enter the snapshot or Analysis Result.
- Acceptance uses two clean synthetic Git project worktrees with identical Team
  locks and independent CAS roots. A test-only Team fixture reuses the existing
  R01 runner/playbook and proves identical locked content executes through that
  owner. R09B ships no Team Skill, new Journey, router, executor, Plan adapter,
  CLI command or Hub operation.
- Missing, dirty, tampered or incompatible lock/CAS/trusted state blocks only
  the affected locked Skill with stable reason codes. Built-in R01 remains
  independent, retains its live completeness block and performs zero Hub calls.
- Focused lock/CAS/trusted/Core tests, public API/resource snapshots, isolated
  installed-wheel checks, both complete test collectors, compiler/quality,
  generated artifacts, development usability/security, CLI help, retained
  consumer non-regression and `git diff --check` are mandatory. Active human
  docs remain exactly 5500 lines.

## Fixed Dev Evidence

- Feature commit `909ae1a` and merge `e8fd2a1` add one public
  `RuntimeSkillResolver`; root public API now has `126` lazy exports and
  `gravity_sdk.__all__` has `127` entries including `__version__`. No CLI
  command, Journey, router, executor, Plan adapter, Provider, operation or
  worker pool was added.
- Built-in identity resolves before project access, remains `unlocked`, writes
  null for every Team/Hub/Trusted snapshot field and succeeds even when the
  workspace, lock and CAS do not exist. Team identity never falls back: the
  fixed tracked/clean `gravity.skills.lock.json` must have a valid self-digest,
  the exact current Runtime version and one exact identity.
- Runtime reads the default `<workspace.state_root>/skill-hub-cas` without
  constructing `SkillHubCAS` or creating a missing root. R04
  `validate_skill_directory` rechecks path/link/hardlink/file budgets, Render
  Model and package digest; URI, manifest/package digests, Runtime requirement
  and the complete dependency snapshot must equal the lock.
- Public Skill/Journey parity now covers Journey identity, capabilities,
  Semantic, Operator/Model, required Context, completeness/DQ, claims, request
  budget and formal Analysis Result output schema. Core consumes the same
  normalized artifact for Built-in and locked Team resolution, while its
  existing Operator/Model registries remain the availability authority.
- A locked Skill's non-Built-in Operators and all Models require exact coverage
  in tracked/clean `gravity.trusted-packs.lock.json` and local
  `trusted-packs-installation.json`. R04 targeted startup verification checks
  lock/state/distribution/group identity without install, entry-point load or
  global scan. Snapshot references include Team lock, exact Hub source plus
  Trusted lock/state/verification digests and exclude local paths/timestamps.
- Two clean synthetic Git projects with identical locks and independent CAS
  roots resolve the same locked Skill reference and both execute successfully
  through the existing R01 runner/playbook/Plan/Operator owner. Guards make any
  Runtime call to Hub sync/fetch/install fail the test. Missing, dirty,
  tampered, wrong-version and dependency-drift lock/CAS cases plus missing,
  tampered, uncovered and group-drift Trusted state fail closed with stable
  scoped reasons; Built-in remains available in every Team failure case.
- Focused R04/R09A/R09B/public gates pass `66` tests and `23` subtests. Complete
  gates pass `1594` unittest; `1594 passed, 3821 subtests` pytest; compiler
  `237 operations / 11 manifests`; quality and both generators PASS; active
  docs remain exactly `5500` lines; CLI, targeted Ruff and diff checks PASS.
- Development usability remains `296/336` selection, `248/248` fillability,
  `53/53` offline terminal and `5/5` recovery; security PASS, production HTTP
  requests `0`, and Runtime Hub requests `0`. The isolated installed-wheel
  import/export/schema/package gate passes from `site-packages`; wheel SHA-256
  is `cf4723231e5714439f29612c03ba0368a1d2ab8cacd9d4ae792fd2112f1c4341`.
  The unchanged Built-in package digest remains
  `544c1448df48f327f1e4785743358490271923448af1025fc82e9ab41eb41c1f`.
- Retained work-dashboard consumer `e4369ce8` has no Team lock and needs no R09B
  migration. Its R09A/current-SDK focused suite passes `11` tests and `94`
  subtests, its branch remains clean, and no unrelated frozen or business path
  was changed.

## Bound Baseline

At the bound baseline, R04 provided Team Hub Stage A package/CAS/lock and
Trusted Pack installation plans while R09A resolved Built-in Skills only. The
retained canonical consumer had no Team lock, so R09B changed no consumer
contract and used its focused R09A suite solely as a non-regression gate.

## Scope

- Resolve exact Skill identity/version/digest from the project Skill lock.
- Read only verified immutable local CAS content during a Journey.
- Verify Runtime compatibility and installed trusted Operator/Model packs against their separate lock.
- Project Hub dependency failures into existing readiness reasons.

## Non-goals

- No Hub sync, fetch, update or code installation inside Runtime execution.
- No changes to routing or Product execution.
- No requirement that projects use a remote Hub for Built-in Skills.

## Machine Contract

Hub binding produces the same normalized Skill model consumed by R09A. Lock/CAS mismatch, missing package, incompatible Runtime or missing trusted pack blocks only the affected locked Skill. Built-in fallback is explicit and cannot impersonate a missing locked Skill.

## Migration And Compatibility

Projects opt in by committing an exact lock. Existing unlocked Built-in projects continue to work. Backend changes remain behind R04 protocol and cannot change Runtime Skill semantics.

## Safety And Operations

Journey execution is offline with respect to Hub sources. Ordinary Skill packages contain no code. Trusted pack installation is an external pre-start operation and never Skill-triggered.

## Acceptance

- Two clean worktrees execute the same locked Skill digest.
- Missing/tampered/incompatible packages block only their Skill.
- Built-in R09A journeys remain independent of R09B availability.
- Runtime performs zero Hub sync/fetch/install calls.

## Verification

Lock/CAS parity, tamper/missing/incompatible cases, trusted-pack verification,
offline execution, Built-in non-regression, public surface parity and full
gates. Test fixtures must fail if Runtime calls Hub sync/fetch/install, creates a
missing CAS root, loads a trusted entry point or scans global packages.

## Rollback And Exit

Pin the previous lock or remove Hub-bound Skills. R09A Built-in operation remains available. No implicit downgrade from a missing locked Skill is allowed.

## Canonical Owners

Skill lock/CAS Runtime reader, readiness mapping, project lock documentation and affected Journey evidence.
