# R04 Team Skill Hub Stage A

| Field | Value |
| --- | --- |
| Parent directive | `gravity-agent-runtime/v9` via `directive.json` |
| Status | `specified` |
| Track | Skill distribution |
| Dependencies | R03 |
| Parallel group | `foundation-b` |
| Shared-spine integration | CLI wiring is serialized |

## Outcome

Team members can synchronize a controlled Git/static HTTPS Hub index, resolve exact Skill dependencies, commit a reproducible lock, fetch and verify packages into an atomic local CAS, and install/verify them offline.

## Current Baseline

Built-in resources ship with the wheel after R03. There is no remote Hub protocol, project lock, content-addressed cache or separation between reproducible resolution state and local installation state.

## Scope

- Freeze Hub Protocol v1 index, package location and dependency semantics.
- Implement `sync`, `search`, `show`, `resolve`, `lock`, `fetch`, `install`, `update`, `verify` and `audit` as bounded control-plane clients.
- Record source identity, source revision/index digest, package digest and exact dependencies.
- Store installation time, path and local health only in uncommitted installation state.
- Support offline verification and materialization after exact fetch.

## Non-goals

- No OCI, Sigstore, TUF, centralized revocation, public marketplace or always-on Hub service.
- No Runtime-time network sync or implicit latest.
- No remote code or package-declared tools.

## Machine Contract

The committed lock contains only reproducible resolution facts. The CAS key is the verified package digest; writes use a temporary target, package-boundary validation, digest verification and atomic commit. `sync` never modifies the lock; `update` is explicit.

## Trust Model

Stage A accepts only explicitly configured, authenticated team-controlled Git repository/ref or static HTTPS source identities. Review fixes the source revision/index digest. A source outside this assumption is blocked until R16 rather than treated as trusted because it supplied its own digest.

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

## Verification

Schema and determinism tests, local Git/static-source fixtures, concurrent CAS tests, archive attack corpus, offline tests, wheel test, lock snapshots, CLI/SDK parity and full repository gates.

## Rollback And Exit

Removing a configured Hub leaves Built-in Skills usable. A failed fetch does not change the lock or prior CAS. Stage B may strengthen authenticity but cannot change v1 lock/digest meaning.

## Canonical Owners

Hub/index/package/lock schemas, local CAS module, control-plane CLI/SDK reference and project lock documentation.
