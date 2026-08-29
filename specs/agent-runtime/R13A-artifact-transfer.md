# R13A Governed Binary Artifact Transfer

| Field | Value |
| --- | --- |
| Parent directive | `gravity-agent-runtime/v9.1` via `directive.json` |
| Status | `fixed_dev`; accepted on `dev@46b317518e576f61877e44ace36ec5cf2f242fe6` 2026-08-22 |
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

## Delivered Evidence

- Implementation `175af94d36c87bacbaecdbb75689a495d3fe30ff` was merged as
  `dev@46b317518e576f61877e44ace36ec5cf2f242fe6`. The material-private
  redirect/stream/staging/type/commit loop was removed; the real
  `material.asset.fetch` owner now invokes the existing R02 `SafeBlobTransfer`
  core through one internal trusted-adapter service.
- `gravity.material-asset.v2` embeds schema-validated
  `gravity.artifact-transfer.v1`. The source contract is
  `gravity.material-asset-contract.v2`: fresh exact HTTPS host/path authorizes
  the first request, at most three redirects remain on that exact host, JPEG
  `.jpg/.jpeg` is capped at 16 MiB and MP4 `.mp4` at 1 GiB, and
  MIME/extension/magic/size/optional MD5/SHA-256 must pass before atomic
  no-clobber commit.
- Output root, ancestors, traversal, absolute-under-explicit-root,
  symlink/reparse, overwrite and extension are checked before the source read
  and again at commit. Relative output metadata contains only `local_ref`;
  signed URLs, query/headers, source input/raw rows and absolute roots are
  absent. Source and binary HTTP calls propagate only opaque standard
  `gravity.result-audit.v1` references, including failure paths.
- Focused attack/parity gates cover same-host redirect success, cross-host
  escape before request two, redirect limit, HTTP category parity, missing/
  duplicate/oversized reference, declared and streaming caps, Content-Length,
  MIME/magic/extension, source size/MD5, interruption, schema tamper and
  pre-commit metadata failure. Final focused core was `44 tests, 35 subtests`;
  post-merge surface coverage was `189 tests, 370 subtests`.
- Complete SDK gates: `1676` unittest tests; `1676 passed, 3880 subtests passed`
  under pytest; compiler `237 operations, 11 manifests`; quality PASS; all
  three deterministic generators, CLI help, diff checks and touched-file Ruff
  PASS. Active human docs remain exactly `5500` lines.
- Actionable errors remain fully classified at
  `1330 = 1163 A + 167 B + 0 C`. Development usability remains selection
  `296/336`, fillability `248/248`, offline terminal `53/53`, recovery `5/5`,
  security violations `0`, and production HTTP requests `0`.
- Isolated real wheel `gravity_sdk-0.3.0-py3-none-any.whl` has SHA-256
  `ccb13cf1867d0b3f2b551c9ef71401d2a2ce0756ca972fdc4e552a417aaae18b`.
  It imported from isolated `site-packages`, loaded the packaged v2 source
  contract and Artifact schema, discovered the updated Agent card and passed
  installed CLI help outside the checkout.
- Canonical consumer search found no material fetch command, selector, method or
  envelope consumer. Its current-SDK adoption/Journey suite still passes
  `11 tests, 94 subtests` against this R13A worktree. No consumer branch change
  was necessary.
- Production probes, target requests, remote writes, releases and `main`
  promotion performed by R13A: `0`.

## Known Limits

- Cross-host material redirects are intentionally unsupported because all
  verified production samples had zero redirects and the complete future host
  set is unproven. A real cross-host requirement needs value-free evidence and
  an explicit source-contract upgrade; it must not be inferred from a URL.
- Artifact Transfer remains a local binary effect behind trusted source
  adapters. There is no arbitrary URL API, upload/remote target, generic file
  manager or Plan node; R13B/R13C remain independent later units.

## Rollback And Exit

The existing materials owner remains the rollback path. Failed transfer state is disposable and never changes source objects.

## Canonical Owners

Artifact Transfer schema/service, materials fetch owner/reference, export safety guide and Receipt projection.
