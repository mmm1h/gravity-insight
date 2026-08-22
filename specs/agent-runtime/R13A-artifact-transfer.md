# R13A Governed Binary Artifact Transfer

| Field | Value |
| --- | --- |
| Parent directive | `gravity-agent-runtime/v9.1` via `directive.json` |
| Status | `in_progress`; reviewed/ready binding accepted 2026-08-22 |
| Track | Binary/file delivery |
| Dependencies | R02 |
| Parallel group | `artifact-transfer` |
| Shared-spine integration | Public CLI wiring is serialized |
| Delivery ledger | This Requirement document; no internal GitHub Issue |
| Baseline | `dev@f5a5d2359290b5a73f5cd8ced985cc5d89c5b47f` |
| Branch / worktree | `codex/r13a-artifact-transfer` / `D:\git-pjt\gravity-sdk-wt\r13a-artifact-transfer` |
| Integrator | Root Codex agent; shared-spine wiring remains serial |
| Production requests | `0`; existing value-free evidence is sufficient |

## Outcome

The existing `material.asset.fetch`/`gravity materials fetch` capability is carried through one governed Artifact Transfer contract with exact reference resolution, bounded streaming, validation, atomic output and value-free evidence.

## Plan Owner Verdict And Ready Binding

The user authorized continuous implementation of all indexed Requirements and
designated each Requirement document as the internal delivery ledger. With R02
already `fixed_dev`, the plan owner reviewed
`tmp/r13a-artifact-transfer-proposal.md` and the matching architecture conflict
ledger, bound this baseline/write scope/machine gates, and advanced R13A through
`reviewed` and `ready` to `in_progress`. This does not authorize production
probing, writes, release actions or `main` promotion.

- Reuse R02 `SafeBlobTransfer`; remove the material-private redirect/stream/
  staging/type/commit implementation after parity is proved.
- The fresh registered response authorizes its exact initial HTTPS host/path.
  Redirects are bounded and exact-same-host only. Existing production evidence
  observed zero material redirects, so verified local/Bytedance capability is
  preserved without pretending the future initial-host set is enumerable.
- Preserve the public CLI/SDK call shape and exact source-reference resolution.
  Directly migrate the unconsumed v1 result to `gravity.material-asset.v2`, which
  embeds `gravity.artifact-transfer.v1` and does not expose an absolute root.
- Resolve and validate the output root before the source read, validate it again
  at atomic commit, deny overwrite/reparse/traversal, and bind exact extension,
  MIME, magic, declared/stream byte caps and SHA-256 identity.
- Keep optional source MD5 as a secondary pre-commit integrity assertion. Return
  only standard value-free `gravity.result-audit.v1` HTTP Receipt references;
  never return signed URLs, request headers, raw rows/input or private roots.
- Do not expose a generic URL API, Plan node, file manager, upload target, second
  resolver/scheduler/registry/worker pool or any R12/R13B/R13C dependency.
- Exact acceptance is focused Artifact/material/blob/error/CLI/SDK/Agent tests,
  schema and public snapshots, interruption/tamper/privacy cases, real-wheel and
  canonical-consumer evidence, then every repository gate in `AGENTS.md`, Ruff,
  deterministic generators, doc-line ratchet and usability/security evaluation.

## Current Baseline

The repository already exposes materials fetch for governed local/Bytedance project references. Binary transfer rules are product-specific and there is no reusable Artifact identity/receipt contract.

## Scope

- Characterize and integrate the real materials fetch owner as the reference capability.
- Define exact source reference, allowed host/redirect, MIME/magic, byte limit, streaming, output root, extension and digest.
- Write through a temporary file and atomically commit only after validation.
- Return safe Artifact metadata and Receipt references.

## Non-goals

- No Analysis Result, renderer, Dashboard or Action dependency.
- No arbitrary URL, browser automation or raw signed URL exposure.
- No generic file manager or remote write target.

## Machine Contract

Artifact output contains a relative/local result reference, size, MIME, digest, source capability and limitations; it never exposes Cookie, Authorization or signed URL values. Transfer failures have stable reason categories.

## Migration And Compatibility

Existing materials fetch CLI/SDK behavior is characterized first and remains usable. The shared contract is extracted from the real path, not introduced as an unused abstraction.

## Safety And Operations

Prevent redirect escape, MIME/magic confusion, path traversal, symlink output, oversized content and visible partial files. Resolve output root before network access and preserve current identity/privacy boundaries.

## Acceptance

- A real/fake-transport materials fetch runs through the shared Artifact contract.
- Redirect/MIME/magic/size/path attack fixtures fail before final commit.
- Interrupted transfer leaves no visible partial artifact.
- Public output and Receipt contain no secret transport data.

## Verification

Current materials characterization, streaming/interruption, redirect/MIME/magic/path/size tests, atomic file cases, public snapshots, CLI/SDK parity and full gates.

## Rollback And Exit

The existing materials owner remains the rollback path. Failed transfer state is disposable and never changes source objects.

## Canonical Owners

Artifact Transfer schema/service, materials fetch owner/reference, export safety guide and Receipt projection.
