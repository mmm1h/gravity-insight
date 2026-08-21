# R01 Reference Vertical Journey Slice

| Field | Value |
| --- | --- |
| Parent directive | `gravity-agent-runtime/v9.1` via `directive.json` |
| Status | `specified`; cannot become `ready` until the reference Journey is owner-approved |
| Track | Reference implementation |
| Dependencies | R00 |
| Parallel group | `reference` |
| Main integration | Frozen until whole program completion |

## Outcome

One real project analysis Journey runs end to end through a Journey Contract, same-layer Capability Trust and Data Quality, one project Semantic, one deterministic Operator, one Built-in Skill, one bounded Repo Context Pack, the existing execution owner, a structured Analysis Result and Receipt/Evidence.

## Ready Gate

Before approval, bind all of the following in this document or its Issue:

```text
journey_id
calling project and owner
question and success criteria
current Product/Composite/Plan selector path
physical and business input scope
required completeness and allowed claims
maximum production requests and whether live evidence is authorized
canonical consumer migration target
```

Codex must not choose the easiest Journey. A candidate is acceptable only when it exercises Capability, Semantic, Operator and Context boundaries and represents a recurring analysis task.

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

The slice must define versioned Journey, Skill, Semantic, Operator, Context Pack and Analysis Result schemas or narrow provisional equivalents. Each identity has one authority and a value-free digest/reference in Receipt metadata. Provisional contracts must state whether R02-R08 may revise them.

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
