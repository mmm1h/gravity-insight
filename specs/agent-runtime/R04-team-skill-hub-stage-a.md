# R04 Team Skill Hub And Trusted Pack Stage A

| Field | Value |
| --- | --- |
| Parent directive | `gravity-agent-runtime/v9.1` via `directive.json` |
| Status | `specified` |
| Track | Skill distribution |
| Dependencies | R03, R06 |
| Parallel group | `foundation-b` |
| Shared-spine integration | CLI wiring is serialized |

## Outcome

Team members can synchronize two explicitly separated Artifact channels: static no-code Skill content, and reviewed Team Trusted Operator/Model packs installed externally from exact wheels/digests and allowlisted groups.

## Current Baseline

Built-in resources ship with the wheel after R03, and R06 defines trusted Operator/Model contracts. There is no remote Hub protocol, project lock, content-addressed cache, team code-pack path or separation between reproducible resolution and local installation state.

## Scope

- Freeze Hub Protocol v1 index, package location and dependency semantics.
- Implement `sync`, `search`, `show`, `resolve`, `lock`, `fetch`, `install`, `update`, `verify` and `audit` as bounded control-plane clients.
- Record source identity, source revision/index digest, package digest and exact dependencies.
- Store installation time, path and local health only in uncommitted installation state.
- Support offline verification and materialization after exact fetch.
- Define a separate `trusted_pack` artifact kind and `gravity.trusted-packs.lock.json` with distribution/version/wheel digest/runtime compatibility and allowed Operator/Model groups.
- Generate an external Installer plan; Runtime startup verifies the exact installed distribution but never installs or scans code automatically.

## Non-goals

- No OCI, Sigstore, TUF, centralized revocation, public marketplace or always-on Hub service.
- No Runtime-time network sync, implicit latest, pip execution or environment mutation.
- No code inside ordinary Skill content; a Skill cannot carry, fetch or trigger a Trusted Pack.
- No generic environment-wide entry-point scanning.

## Machine Contract

Skill and Trusted Pack locks contain only reproducible resolution facts and use different artifact kinds/files. The CAS key is the verified artifact digest; writes use a temporary target, package-boundary validation, digest verification and atomic commit. `sync` never modifies either lock; updates are explicit. Trusted Pack loading is restricted to exact locked distributions and allowed groups.

## Trust Model

Stage A accepts only explicitly configured, authenticated team-controlled Git repository/ref or static HTTPS source identities. Review fixes the source revision/index digest. Trusted code additionally requires code review, deterministic wheel build and explicit plan-owner approval. A source outside this assumption is blocked until R16 rather than treated as trusted because it supplied its own digest.

## Package Safety

Reject absolute and parent paths, symlink/hardlink entries, unregistered executable bits, duplicate normalized paths, case-fold collisions and excessive file count, byte size, compression ratio or depth. Concurrent fetches of one digest single-flight and cannot expose a partial CAS entry.

## Migration And Compatibility

Built-in Skills continue to work with no project lock and report `unlocked`. Team/production paths use an exact committed lock. Backend changes cannot alter Manifest, digest, dependency or lock semantics.

## Acceptance

- Two clean worktrees resolve the same source revision to byte-identical locks.
- Offline install works from a populated CAS.
- Tampered index, package, path or digest fails closed.
- Lock never contains installation-local facts.
- Runtime execution performs no Hub network calls.
- A second project installs the same exact Operator wheel through an external Installer plan and Runtime verifies it at startup.
- Ordinary Skill resolution cannot add code, change the trusted-pack lock or load an unlisted entry point.

## Verification

Schema and determinism tests, local Git/static-source fixtures, concurrent CAS tests, archive attack corpus, offline tests, exact trusted-wheel/install-plan fixtures, allowlist and no-environment-scan tests, lock snapshots, CLI/SDK parity and full repository gates.

## Rollback And Exit

Removing a configured Hub leaves Built-in Skills usable. A failed fetch does not change the lock or prior CAS. Stage B may strengthen authenticity but cannot change v1 lock/digest meaning.

## Canonical Owners

Hub/index/package/trusted-pack/lock schemas, local CAS module, external Installer plan contract, control-plane CLI/SDK reference and project lock documentation.
