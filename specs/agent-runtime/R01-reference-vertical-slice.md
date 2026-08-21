# R01 Reference Vertical Journey Slice

| Field | Value |
| --- | --- |
| Parent directive | `gravity-agent-runtime/v9.1` via `directive.json` |
| Status | `in_progress`; owner-approved 2026-08-21 |
| Track | Reference implementation |
| Dependencies | R00 |
| Parallel group | `reference` |
| Delivery ledger | This Requirement document; no internal GitHub Issue |
| Baseline | `dev@05f01c8da13c8414412611eb3c34612862530803` |
| Branch / worktree | `codex/r01-reference-vertical-slice` / `D:\git-pjt\gravity-sdk-wt\r01-reference-vertical-slice` |
| Integrator | Root Codex agent; shared-spine wiring remains serial |
| Main integration | Frozen until whole program completion |

## Outcome

One real project analysis Journey runs end to end through a Journey Contract, same-layer Capability Trust and Data Quality, one project Semantic, one deterministic Operator, one Built-in Skill, one bounded Repo Context Pack, the existing execution owner, a structured Analysis Result and Receipt/Evidence.

## Owner Verdict And Ready Binding

The user approved `tmp/r01-reference-vertical-slice-proposal.md` on 2026-08-21
and designated this Requirement as the internal delivery ledger. The same
message authorizes Codex to continue through later indexed requirements without
requesting another per-Requirement approval once their dependencies and machine
gates are satisfied. This does not authorize production probing, writes,
credential changes, release actions, or early `main` promotion.

- **Journey ID**: `analysis.merge2.ap-cost-anomaly-localization`.
- **Calling project / owner**: `work-dashboard` project `merge2` / `growth-data`.
- **Question**: did the sum of returned `click_company` `ap_cost` rows change
  between equal, non-overlapping windows, and did one caller-selected slice move
  in the same observed direction?
- **Success**: Journey readiness is machine-decidable; exact Trust/DQ,
  project Semantic, deterministic Operator, Built-in Skill, bounded Repo Context
  and Receipt references compose around the existing executor; missing or
  degraded evidence produces no conclusion.
- **Existing execution path**:
  `metric-anomaly-localization@1 -> Plan v1 -> semantic_compose -> report.multidim.query`.
- **Physical input scope**: configured `merge2-legacy` App binding, two equal
  explicit ISO windows, one exact `click_company`, physical `ap_cost`.
- **Business input scope**: project acquisition-spend Semantic and canonical
  acquisition/attribution Context citations.
- **Required completeness**: `complete` for every required query step.
- **Allowed claims**: returned-row window change, returned-key change and the
  selected-slice observation already bounded by `metric-anomaly-localization@1`.
- **Forbidden claims**: complete App total, unreturned values, causality,
  incrementality, ROI, natural-volume attribution or an unproved semantic
  equivalence.
- **Production request maximum / live evidence**: `0` / not authorized.
- **Canonical consumer target**: current `work-dashboard` Gravity contract,
  references and focused consumer tests, modified only in a clean worktree.
- **Acceptance commands**: focused R01/playbook/semantic/Plan tests, real-wheel
  no-checkout tests, focused consumer tests, both repositories' complete gates,
  the development usability evaluation and `git diff --check`.

## Current Baseline

The repository already has closed analysis journeys, host catalog/recognizer routing, Product/Composite/Plan execution, generated task guides, semantic caller bindings, completeness and Receipt behavior. It does not have the target Journey/Skill/Trust/Semantic/Operator/Context composition contract.

## Scope

- Implement only the minimum contracts needed by the selected Journey.
- Use one Built-in reference Skill; do not require Team Skill Hub Stage A.
- Preserve exact selector, host catalog and recognizer authority.
- Return honest `verified`, `unknown`, `blocked` or `invalid` outcomes.
- Capture characterization sufficient for R02-R08 extraction.

## Non-goals

- No generic registry for cases not exercised by the slice.
- No OCI, TUF, MCP, PAP, adaptive variant selection, SQL Explorer or action execution.
- No attempt to make all ThinkingAI Skills executable.

## Machine Contract

The slice must define versioned Journey, Skill, Semantic, Operator, Context Pack and Analysis Result schemas or narrow provisional equivalents. Each identity has one authority and a value-free digest/reference in Receipt metadata. R02-R08 may revise provisional R01 contracts only with current-behavior characterization, consumer migration and no-capability-loss gates.

## Migration And Compatibility

The current Product/Composite/Plan owner remains the only executor. Public CLI/SDK/Plan and canonical consumer behavior must be characterized before changes. Any new result layer wraps governed results without changing existing envelope semantics silently.

## Safety And Operations

Invalid input and blocked readiness perform zero target network calls. Any authorized production evidence follows maintainer probing rules and records exact request count, scope and value-free evidence.

## Acceptance

- One named real Journey is machine-decidable end to end.
- No second router, executor, binder, pagination or permission system exists.
- Missing same-layer trust, semantic, operator or context produces a stable gap.
- Complete/partial/unknown and allowed claims remain honest.
- The slice produces an extraction ledger for R02-R08.

## Verification

Focused happy/empty/partial/gap/invalid/privacy tests, current surface characterization, real wheel execution without checkout-only resources, relevant consumer tests, complete repository gates and the development usability evaluation.

## Rollback And Exit

The slice may stop at a proved blocker. Rollback restores current public behavior and removes provisional unused contracts; it must not delete existing read capability.

## Canonical Owners

Journey machine artifact, `docs/analysis-journeys.md`, affected reference pages, generated Agent guide and the selected calling project's canonical contract.
