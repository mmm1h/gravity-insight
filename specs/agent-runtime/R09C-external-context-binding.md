# R09C External Context Binding

| Field | Value |
| --- | --- |
| Parent directive | `gravity-agent-runtime/v9.1` via `directive.json` |
| Status | `specified` |
| Track | Optional external Context binding |
| Dependencies | R08, R09A |
| Parallel group | `optional-binding` |
| Shared-spine integration | Required and serialized |

## Outcome

Skills may declare required or optional external Context dependencies and receive R08-governed, entity/time/authority-aligned Context Items without making external Provider availability a prerequisite for Core Skill Runtime.

## Current Baseline

R09A consumes Repo Context only. R08 defines external Provider/RPC boundaries but does not bind them into Skill readiness or Analysis Result claims.

## Scope

- Resolve explicit Provider/resource requirements from Skill dependencies.
- Request external items through RPC Guard and R07 Context Broker.
- Align entity refs, valid/effective time, authority and supersession before inclusion.
- Map required/optional missing, denied, stale, conflicting and unsupported outcomes into readiness/claim policy.

## Non-goals

- No implicit provider discovery for Skills that do not declare a dependency.
- No Provider-controlled routing, effects or user authorization.
- No claim that Runtime controls Provider-internal networking.

## Machine Contract

Required external Context gaps block only the declaring Skill. Optional gaps narrow allowed claims. Unaligned items remain excluded/unverified and cannot support confirmed facts. Analysis Result references Pack/item digests without storing restricted content.

## Migration And Compatibility

R09A behavior is unchanged when R09C is absent. Projects add Provider descriptors and bindings explicitly. Direct Host evidence may still be wrapped into Context Items without mandatory Runtime Provider adoption.

## Safety And Operations

RPC budgets, cancellation, output limits and circuits come from R08. Context is data. Unauthorized resources are not enumerated or leaked through errors.

## Acceptance

- Provider absence blocks only explicitly required dependencies.
- Optional Provider failure leaves the Skill executable with narrowed claims.
- Entity/time/authority misalignment is machine-visible and excluded.
- R09A Built-in/Repo-only Skills remain green with all external Providers disabled.

## Verification

Required/optional provider matrices, entity/time alignment, stale/conflict/denied cases, prompt injection, RPC budgets, Result/Receipt privacy and full gates.

## Rollback And Exit

Remove the external binding or Provider descriptor; only dependent Skills change readiness. No core data execution path is removed.

## Canonical Owners

External Context dependency resolver, readiness/claim mapping, Analysis Result Context references and Provider setup docs.
