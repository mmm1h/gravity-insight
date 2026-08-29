# <ID> <Title>

| Field | Value |
| --- | --- |
| Parent directive | `gravity-agent-runtime/v9.1` via `directive.json` |
| Status | `draft` |
| Track | `<track>` |
| Dependencies | `<IDs or none>` |
| Parallel group | `<group>` |
| Delivery mode | `leaf` unless total architecture explicitly permits `staged_epic` |
| Main integration | Frozen until whole program completion |

## Outcome

State the user-visible or machine-visible outcome. One requirement must own one end-to-end deliverable, not one implementation phase.

For a `staged_epic`, enumerate mandatory child milestones and require a separate Issue, branch, commit, acceptance and rollback for each. The parent cannot become `fixed_dev` until all milestones do.

## Current Baseline

Name the current owner modules, public surfaces, contracts, tests, request budget and known blockers. Bind the exact HEAD before changing the requirement to `ready`.

## Scope

- Required behavior.
- Public and internal contracts.
- Consumer and documentation changes.

## Non-goals

- Adjacent architecture not owned by this requirement.
- Capabilities deliberately deferred.

## Machine Contract

Define schema versions, identities, lifecycle/readiness, reason codes, authority and dependency propagation.

## Migration And Compatibility

Characterize existing behavior, preserve capability, migrate canonical consumers in the same release unit, and name every temporary compatibility path with owner and exit condition.

## Safety And Operations

Specify identity, privacy, network, request/concurrency, production probe, write authorization, artifact and supply-chain boundaries that apply.

## Acceptance

- Machine-decidable behavior and negative cases.
- Public surface parity.
- No unapproved network or write effects.

## Verification

List focused tests, compiler/quality gates, real wheel checks, consumer checks and the full repository validation required before `fixed_dev`.

## Rollback And Exit

State activation, rollback, blocker and supersession behavior. `fixed_dev` never implies `main` promotion.

## Canonical Owners

Name the long-lived documents and machine artifacts updated when the requirement lands; this file must not become a second runtime contract.
