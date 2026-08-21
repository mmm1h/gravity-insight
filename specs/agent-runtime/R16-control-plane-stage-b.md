# R16 External Control Plane Stage B

| Field | Value |
| --- | --- |
| Parent directive | `gravity-agent-runtime/v9.1` via `directive.json` |
| Status | `specified`; conditional |
| Track | Supply chain and updates |
| Dependencies | R04 plus trigger |
| Parallel group | `conditional-control` |
| Main integration | Frozen until whole program completion |

## Trigger

Document an external trust/compliance boundary: untrusted transport, cross-organization or cross-trust-domain distribution, centralized revocation, signer identity or regulated supply-chain requirement. Team-internal cross-repository reuse alone triggers Stage B only when the Stage A controlled-source model is insufficient.

## Outcome

An External Control Plane builds, publishes, verifies, stages, canaries and rolls back Runtime/Skill/Provider/Operator artifacts while preserving Stage A Skill-content and Trusted-Pack artifact kinds, digests and lock semantics. Runtime never replaces its own loaded wheel.

## Current Baseline

R04 provides trusted-source team synchronization, digest locks and local CAS. Repository releases and `main` promotion remain explicit owner actions; there is no organization artifact authenticity, revocation or coordinated activation plan.

## Scope

- OCI artifact publication by immutable digest.
- Signature identity, provenance and license verification.
- TUF-style root/targets/snapshot/timestamp metadata and trust-root rotation.
- Revocation, rollback/freeze/mix-and-match protection and offline bundle.
- Update resolve/download/verify/stage/offline-gate/canary/activation-plan/rollback.
- External Installer/package manager/CI-CD activation.

## Non-goals

- No Runtime self-download, self-install or in-process version switch.
- No implicit latest, partial component activation or public marketplace requirement.
- No change to Stage A Skill or Trusted Pack lock/digest semantics and no merging of code into ordinary Skill packages.

## Machine Contract

Update Plan freezes a compatible execution snapshot and names exact artifacts, digests, signer/provenance policy, gates and rollback target. In-flight Journeys finish on their snapshot. New execution policy distinguishes metadata expiry, package revocation and current activated snapshot explicitly.

## Migration And Compatibility

Stage A projects continue to resolve old locks. Stage B enriches verification metadata outside the stable lock fields. Activation requires current consumer and Journey gates; package publication is not activation and activation is not `main` promotion.

## Safety And Operations

Key/bootstrap/root rotation and threshold policies require organizational owners. Expired metadata blocks update resolution; revoked packages block new execution according to policy while preserving historical Receipt resolution. External activation is restart/deployment aware.

## Acceptance

- Tampered, rollback, freeze, mix-and-match, expired and revoked fixtures behave per policy.
- Offline bundle verifies from an explicit trust root.
- Canary failure leaves the prior complete snapshot active.
- Runtime process cannot mutate its environment or project lock.
- Stage A consumers remain compatible.

## Verification

OCI/signature/provenance/TUF fixtures, root rotation, revocation/expiry matrix, offline bundle, partial download, staging/canary/rollback, external installer contract, execution snapshot and full gates.

## Rollback And Exit

Rollback activates the prior complete external snapshot. A failed Stage B rollout leaves Stage A lock/cache usable under its original trust assumption. No partial artifact set becomes active.

## Canonical Owners

Control Plane schemas/client, release and key-management runbooks, activation/rollback evidence and compatibility matrix.
