# R13B Analysis Artifact And Non-Gravity Renderer

| Field | Value |
| --- | --- |
| Parent directive | `gravity-agent-runtime/v9.1` via `directive.json` |
| Status | `in_progress`; reviewed/ready binding accepted 2026-08-22 |
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

## Rollback And Exit

Disable the renderer without changing Analysis Result. Artifacts remain portable to future target adapters.

## Canonical Owners

Analysis Artifact schema/compiler, non-Gravity renderer, delivery guide and source binding evidence.
