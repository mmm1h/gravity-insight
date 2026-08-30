# R13B Analysis Artifact And Non-Gravity Renderer

| Field | Value |
| --- | --- |
| Parent directive | `gravity-agent-runtime/v9.1` via `directive.json` |
| Status | `fixed_dev`; accepted on `dev@afcf84ccefea9c9c3533196f2b1e9e6ace93fead` 2026-08-22 |
| Track | Analysis delivery |
| Dependencies | R09A |
| Parallel group | `analysis-delivery` |
| Main integration | Frozen until whole program completion |
| Delivery ledger | This Requirement document; no internal GitHub Issue |
| Baseline | `dev@d2aa9b0c3c5fc4f99c967ccc4acced3ced834f8b` |
| Branch / worktree | `codex/r13b-analysis-artifact-renderer` / `D:\git-pjt\gravity-sdk-wt\r13b-analysis-artifact-renderer` |
| Integrator | Root Codex agent; public snapshot regeneration remains serial |
| Production requests | `0`; deterministic local delivery only |

## Outcome

`gravity.analysis-result.v1` compiles into a target-independent Analysis Artifact/Visualization Spec and renders through at least one non-Gravity target such as Markdown or HTML.

## Plan Owner Verdict And Ready Binding

The user authorized continuous implementation of all indexed Requirements and
designated each Requirement document as the internal delivery ledger. With R09A
already `fixed_dev`, the plan owner reviewed
`tmp/r13b-analysis-artifact-renderer-proposal.md` and the matching architecture
conflict ledger, bound this baseline/write scope/machine gates, and advanced
R13B through `reviewed` and `ready` to `in_progress`. This does not authorize
production probing, remote writes, release actions or `main` promotion.

- `compile_analysis_result()` remains the only source authority. Artifact fields
  copy governed findings, claims, limitations, completeness, DQ and evidence
  exactly; Context and execution bodies are reduced to typed references/digests.
- Metric/Dimension lists project only explicit `metric://`/`dimension://` URIs.
  Scope is preserved transparently as the filter source. Because Analysis Result
  has no visualization field, v1 records `unspecified` and a stable gap instead
  of guessing a chart.
- Deliver eight generic sections and one deterministic Markdown v1 renderer.
  Escape HTML/Markdown controls and flatten untrusted newlines; render no links,
  raw HTML, project template or department-specific prose.
- Exact limits are 8 MiB source, 8 MiB Artifact, 256 findings, eight sections and
  1 MiB rendered UTF-8. Any overflow fails closed without truncating conclusions.
- Bind canonical Result, execution snapshot, Receipt-reference, Artifact and
  rendered-content digests. Atomic JSON/Markdown publication reuses the existing
  local text writer and completes validation before replace.
- Public delivery is additive root compiler/validator/verifier/renderer exports
  plus lazy offline `GravitySDK.analysis_artifacts`. No CLI/shared spine, Plan,
  Agent routing, R13A, Action or Dashboard dependency is introduced.
- Acceptance includes success/blocked/invalid parity, a real R09A runner fixture,
  deterministic golden Markdown, injection/output-budget/tamper/privacy cases,
  public snapshot, real wheel, canonical-consumer evidence, full repository
  gates, touched-file Ruff, generators and usability/security evaluation.

## Current Baseline

R09A owns structured Analysis Result. Current reports are produced by callers and existing exports; no target-independent analysis delivery contract exists.

## Scope

- Define sections, findings, Metric/Dimension URIs, filters, visualization intent, evidence, claims and limitations.
- Compile only from governed Analysis Result and Context references.
- Implement a deterministic Markdown or HTML renderer.
- Bind rendered output digest to source Result/Receipt.

## Non-goals

- No Gravity Dashboard configuration or write; R13C owns it.
- No binary source transfer; R13A owns it.
- No department-specific prose or business decision template in Runtime.

## Machine Contract

Analysis Artifact cannot strengthen source completeness, DQ, evidence level or allowed claims. Renderer output is deterministic for normalized input and carries source/version metadata without sensitive Context bodies.

## Migration And Compatibility

Calling projects keep final report language. They may adopt the renderer incrementally. Existing exports remain unchanged and no Dashboard API is required.

## Safety And Operations

Escape untrusted text for each output format, enforce item/byte limits and keep restricted Context out of rendered output. No renderer performs network or mutation effects.

## Acceptance

- One real R09A Analysis Result compiles and renders end to end.
- Renderer output is deterministic and target-independent schema validates.
- Claims/evidence/limitations match the source exactly.
- R13B works with R12/R13C absent.

## Verification

Schema/golden render tests, escaping/injection cases, output budgets, claim preservation, source digest binding and full gates.

## Delivered Evidence

- Implementation `2ec74fe17eac98c4912fafa61f11af90048b2932` was merged as
  `dev@afcf84ccefea9c9c3533196f2b1e9e6ace93fead`. The existing
  `gravity.analysis-result.v1` schema, compiler and R09A executor were not
  changed; the new layer always invokes that compiler before delivery.
- `gravity.analysis-artifact.v1` preserves source status, scope, Semantic
  references, findings, exclusions, hypotheses, claims, recommendations,
  limitations, completeness, DQ, evidence level, Context references and Receipt
  references. Result, execution-snapshot, Receipt-set and self digests bind the
  Artifact; Context bodies, full execution snapshots and query rows are absent.
- Metric/Dimension projections accept only explicit `metric://` and
  `dimension://` schemes. Filters transparently bind `/scope`, while
  visualization remains `unspecified/SOURCE_VISUALIZATION_UNDECLARED`; no chart,
  operator or target filter is inferred.
- Eight fixed generic sections feed deterministic `gravity.analysis-rendering.v1`
  Markdown. All variable text is single-line HTML/Markdown escaped; links/raw
  HTML/project templates/department prose are not produced. The rendering
  envelope explicitly binds Result, Artifact, Receipt-set and content digests.
- Compiler limits are 8 MiB source, 8 MiB Artifact, 256 findings and eight
  sections; Markdown is capped at 1 MiB. Overflow fails without truncating
  conclusions. `gravity.analysis-delivery.v1` atomically writes validated JSON
  or complete Markdown through the existing durable writer and preserves an old
  file when a staged write is interrupted.
- Current blocked/invalid Results remain conclusion-free. The real R09A
  `ReferenceJourneyRunner` with the existing synthetic verified Trust fixture
  reached Analysis Result -> Artifact -> Markdown through the unchanged
  playbook owner; this proves composition only and does not promote current
  production completeness or Trust.
- Final focused delivery/surface coverage was `27 tests, 6 subtests`; post-merge
  coverage was `48 tests, 6 subtests`. Complete SDK gates passed `1685` unittest
  tests and `1685 passed, 3886 subtests passed` under pytest. Compiler remained
  `237 operations, 11 manifests`; quality, all three deterministic generators,
  CLI help, diff checks and touched-file Ruff passed.
- Public API is additive at `135` lazy exports / `136` `__all__` entries.
  `GravitySDK.analysis_artifacts` is lazy/cached and constructs no Insight/SQL
  client. Active human docs remain exactly `5500` lines.
- Actionable errors remain `1330 = 1163 A + 167 B + 0 C`. Development usability
  remains selection `296/336`, fillability `248/248`, offline terminal `53/53`,
  recovery `5/5`, security violations `0`, and production HTTP requests `0`.
- Isolated real wheel `gravity_insight-0.3.0-py3-none-any.whl` has SHA-256
  `875be2a600d1c2f04ab7338a71e8d3bfcde340a6caadbe3da4d163e702b7557c`.
  From external `site-packages` it loaded all three packaged schemas, reached
  the five new root exports, validated a written Artifact and rendered the same
  deterministic Markdown.
- Canonical consumer search found no Analysis Result/Artifact consumer; its
  current-SDK adoption/Journey suite remains green at `11 tests, 94 subtests`,
  so no consumer branch change was needed.
- Production probes, target requests, remote writes, releases and `main`
  promotion performed by R13B: `0`.

## Known Limits

- Markdown v1 is the only renderer. Visualization remains explicitly
  unspecified until a governed source declares intent; R13C must return a gap
  for unsupported/undeclared target visualization instead of guessing.
- R13B exposes offline root/SDK surfaces only. It adds no CLI/shared-spine,
  natural-language Agent route, Plan adapter, arbitrary template registry or
  target mutation; final report wording remains in the calling project.

## Rollback And Exit

Disable the renderer without changing Analysis Result. Artifacts remain portable to future target adapters.

## Canonical Owners

Analysis Artifact schema/compiler, non-Gravity renderer, delivery guide and source binding evidence.
