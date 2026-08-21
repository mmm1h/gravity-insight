# R13B Analysis Artifact And Non-Gravity Renderer

| Field | Value |
| --- | --- |
| Parent directive | `gravity-agent-runtime/v9.1` via `directive.json` |
| Status | `specified` |
| Track | Analysis delivery |
| Dependencies | R09A |
| Parallel group | `analysis-delivery` |
| Main integration | Frozen until whole program completion |

## Outcome

`gravity.analysis-result.v1` compiles into a target-independent Analysis Artifact/Visualization Spec and renders through at least one non-Gravity target such as Markdown or HTML.

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
