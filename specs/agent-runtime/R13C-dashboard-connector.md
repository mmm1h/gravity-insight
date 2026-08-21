# R13C Gravity Dashboard Connector

| Field | Value |
| --- | --- |
| Parent directive | `gravity-agent-runtime/v9.1` via `directive.json` |
| Status | `specified` |
| Track | Governed Gravity delivery |
| Dependencies | R12-A, R13B |
| Parallel group | `dashboard-delivery` |
| Shared-spine integration | Required and serialized |

## Outcome

A validated Analysis Artifact can be translated by a bounded Gravity Dashboard Connector into Preview, explicit confirmation, Execute and Readback without exposing raw Web configuration to a Skill or LLM.

## Current Baseline

The repository can replay selected persisted Dashboard charts and perform governed kanban mutations. R13B provides target-independent output, while R12-A provides the Action Plan/Reference Connector governance actually needed here; R12-B/C are not prerequisites.

## Scope

- Define supported visualization/filter/layout subset and deterministic target compilation.
- Validate Metric/Dimension identities, dates, filters, source bindings and claims.
- Produce an R12 Action Preview and exact readback assertions.
- Bind Analysis Artifact, target Dashboard and Receipt evidence.

## Non-goals

- No Dashboard UI, favourites, drag/drop or member permission management.
- No Skill/LLM-authored raw Gravity Web configuration.
- No dependency from R13A or R13B back to Dashboard availability.

## Machine Contract

Connector input is `gravity.analysis-artifact.v1`; output is an R12 governed plan. Unsupported visualization/layout returns a stable gap. Target compilation cannot alter source meaning or claims.

## Migration And Compatibility

Existing Dashboard replay remains a read path. Existing kanban mutations remain governed owners. The connector is a new explicit target adapter and does not repurpose either silently.

## Safety And Operations

User confirmation, ownership, preimage, managed fields, idempotency and readback follow R12. Target schema drift fails closed before mutation.

## Acceptance

- A supported R13B Artifact reaches Preview/Execute/Readback.
- Unsupported layout/visualization stops safely.
- Skill/LLM never sees or submits raw target configuration.
- Dashboard failure does not affect non-Gravity rendering or Artifact Transfer.

## Verification

Compiler fixtures, identity/filter/date validation, preview/execute/readback, ownership/stale/drift cases, Receipt binding, canonical consumer tests and full gates.

## Rollback And Exit

Disable the connector while preserving Analysis Artifact and other renderers. Failed writes follow R12 uncertainty/readback policy.

## Canonical Owners

Dashboard compiler/connector, supported-subset reference, Action integration and Artifact-to-Dashboard Receipt evidence.
