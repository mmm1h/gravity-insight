# R09B Team Hub Skill Binding

| Field | Value |
| --- | --- |
| Parent directive | `gravity-agent-runtime/v9.1` via `directive.json` |
| Status | `specified` |
| Track | Optional Skill distribution binding |
| Dependencies | R04, R09A |
| Parallel group | `optional-binding` |
| Shared-spine integration | Required and serialized |

## Outcome

R09A can resolve and execute a Skill from an exact project lock and verified local CAS without changing Core Skill Runtime semantics or performing Runtime-time Hub network access.

## Current Baseline

R04 provides Team Hub Stage A, package/CAS/lock and Trusted Pack installation plans. R09A supports Built-in Skills only.

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

Lock/CAS parity, tamper/missing/incompatible cases, trusted-pack verification, offline execution, Built-in non-regression, public surface parity and full gates.

## Rollback And Exit

Pin the previous lock or remove Hub-bound Skills. R09A Built-in operation remains available. No implicit downgrade from a missing locked Skill is allowed.

## Canonical Owners

Skill lock/CAS Runtime reader, readiness mapping, project lock documentation and affected Journey evidence.
