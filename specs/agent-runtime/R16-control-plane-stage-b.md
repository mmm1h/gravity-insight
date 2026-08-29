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

## Disposition (2026-08-28)

The trigger **has fired**, and the earlier `not triggered` record was wrong. The
repository distributes publicly: GitHub Releases plus `gravity-insight` on PyPI.
Public index distribution is cross-trust-domain distribution, so the
"team-internal cross-repository reuse alone" carve-out does not apply — you
cannot publish to a public index and still call the boundary team-internal.

Implementation is nonetheless **deliberately deferred**, not started. What the
trigger demands in substance is already met by Stage A plus the current release
path: PyPI Trusted Publishing supplies signer identity through OIDC with no
long-lived credential, PEP 740 attestations supply provenance,
`scripts/verify_release_provenance.py` and the pinned provenance fixtures verify
it, and R04 supplies digest locks and a local CAS. The genuine additions Stage B
would bring — centralized revocation, TUF trust-root rotation, offline bundles
and coordinated canary/activation — have no present consumer. Building an
OCI/TUF control plane for one team-internal consumer would be disproportionate.

This requirement does **not** independently gate `main` promotion. Promotion is
already governed by whole-program completion plus explicit owner re-approval,
and this specification decouples the two itself: "package publication is not
activation and activation is not `main` promotion". `R10` is also below
`fixed_dev`, so `R16` is not the unique outstanding item either.

Revisit when any of these becomes true: a consumer outside this team adopts the
published package; a regulated or contractual supply-chain requirement appears;
a published artifact must be revoked; or offline/air-gapped installation is
required. Until then `R16` stays `specified` and unimplemented by decision, not
by oversight.

recorded_by: `agent_under_standing_owner_delegation`; the owner delegated this
call on 2026-08-28 with the instruction to decide from product direction and the
architecture source.

## Validation Core Implementation Record (2026-08-29)

The premise behind the historical deferral changed: `main` promotion now needs
every indexed Requirement at `fixed_dev`, so leaving R16 at `specified` is no
longer neutral. Under `agent_under_standing_owner_delegation` with
`owner_review: pending`, implementation therefore started without rewriting the
Disposition above.

This first segment implements only local verification: immutable digest-bound
OCI descriptors, signer identity/provenance/license policy, TUF-style four-role
threshold metadata, consecutive dual-threshold root rotation, revocation,
rollback/freeze/mix-and-match/expiry protection, and offline bundle validation
from an explicit trust root. Its deterministic `hmac-sha256` profile uses only
the standard library and is a bounded local verification profile, not a claim
of production Sigstore/Cosign equivalence. Tests make zero network requests.

Resolve, download, stage, offline gate, canary, activation planning, rollback
lifecycle, and external Installer integration remain for the second segment.
R04 Skill/Trusted Pack lock fields and digest semantics are unchanged. R16 stays
`specified` until both segments are integrated and the plan owner records the
final lifecycle transition.

### Asymmetric Trust-Root Correction (2026-08-29)

The local verification segment now replaces its historical symmetric
`hmac-sha256` profile with Ed25519 public-key verification through PyNaCl. The
earlier record remains above as implementation history, but HMAC is no longer
accepted by the machine contract: a verifier must not receive the ability to
forge publicly distributed metadata or artifacts.

The selection compared `cryptography`, PyNaCl, a vendored pure-Python Ed25519
verifier, external OpenSSL/OS crypto, and a full TUF/Sigstore client stack.
`cryptography` was security-suitable but broader than this one-primitive
boundary; pure Python would make this repository the owner of hand-written
cryptographic arithmetic; external executables are not a portable Runtime
contract; and the full protocol stacks would rewrite an already bounded local
verification core. PyNaCl was selected as the narrowest established,
native-backed Ed25519 implementation, accepting its CFFI/libsodium binary-wheel
distribution cost because R16 is the public supply-chain trust root rather than
a local leaf feature. Because this control-plane capability is optional for the
SDK's analysis-first consumers, PyNaCl is pinned in the `control-plane` extra
rather than the base install; the `dev` extra includes the same pin for tests.

Production code imports only `VerifyKey` and verifies 32-byte public keys plus
64-byte signatures. It has no private-key loader or signature-generation path.
Deterministic private seeds and `SigningKey` exist only in
`tests/test_control_plane_fixtures.py` and are explicitly test-only,
non-production material. The verifier accepts exactly the `ed25519` algorithm;
unknown or mismatched algorithms fail closed. Dedicated fixtures also prove
that replacing an explicit root public key invalidates the old signature and
that an algorithm claim inconsistent with the trust root is rejected. The six
pre-existing attack fixtures retain their stable reason codes.

Production module import records a missing PyNaCl backend without failing the
package import. Every Ed25519 verification attempt then fails closed with
`CRYPTO_BACKEND_UNAVAILABLE` and directs the caller to install
`gravity-insight[control-plane]`; no successful, skipped, or fallback-algorithm
path exists when that backend is unavailable.

PyNaCl adds a binary distribution surface. Version 1.6.0 publishes a
`cp38-abi3` Windows x86-64 wheel; CPython's stable ABI lets that wheel cover
CPython 3.8 and later, including the local 3.14 environment, without rebuilding
for each Python minor release. Its `cffi>=2.0.0` dependency has a native
`cp314` Windows x86-64 wheel in the local environment.

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
