# R13A Governed Binary Artifact Transfer

| Field | Value |
| --- | --- |
| Parent directive | `gravity-agent-runtime/v9.1` via `directive.json` |
| Status | `specified` |
| Track | Binary/file delivery |
| Dependencies | R02 |
| Parallel group | `artifact-transfer` |
| Shared-spine integration | Public CLI wiring is serialized |

## Outcome

The existing `material.asset.fetch`/`gravity materials fetch` capability is carried through one governed Artifact Transfer contract with exact reference resolution, bounded streaming, validation, atomic output and value-free evidence.

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
