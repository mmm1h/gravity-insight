# R09C External Context Binding

| Field | Value |
| --- | --- |
| Parent directive | `gravity-agent-runtime/v9.1` via `directive.json` |
| Status | `in_progress`; plan-owner ready verdict 2026-08-22 |
| Track | Optional external Context binding |
| Dependencies | R08, R09A |
| Parallel group | `optional-binding` |
| Shared-spine integration | Required and serialized |
| Delivery ledger | This Requirement document; no internal GitHub Issue |
| Baseline | `dev@e7a0536a4836ef363bce0e8753e29b5eeba4d628` |
| Branch / worktree | `codex/r09c-external-context-binding` / `D:\\git-pjt\\gravity-sdk-wt\\r09c-external-context-binding` |
| Consumer | Retained R09A stack `work-dashboard@e4369ce8`; non-regression only |
| Integrator | Root Codex agent; shared-spine wiring remains serial |
| Production / external requests | `0`; injected local fixtures only |
| Main integration | Frozen until whole program completion |

## Outcome

Skills may declare required or optional external Context dependencies and receive R08-governed, entity/time/authority-aligned Context Items without making external Provider availability a prerequisite for Core Skill Runtime.

## Plan Owner Verdict And Ready Binding

The user designated the Requirement document as the internal delivery ledger
and authorized continuous implementation without repeated approval. R08 and
R09A are `fixed_dev`; the plan owner reviewed
`tmp/r09c-external-context-binding-proposal.md` and its conflict ledger, bound
the baseline/worktree/gates below, and advanced R09C through `reviewed` and
`ready` to `in_progress`. This does not authorize live Providers, credentials,
production/external requests, package installation, release or `main`
promotion.

- Add fixed tracked `gravity.external-context.json` containing exact R08
  descriptors and explicit Skill/Journey/resource requirements. Project data
  cannot route, authorize, carry credentials or construct a transport/process.
  Runtime accepts only explicitly injected `ExternalContextProvider` instances
  whose URI/digest exactly match the tracked descriptor; no discovery,
  list/search fallback or guessed resource is allowed.
- Built-in/Repo-only dependencies resolve before reading external state. A
  required absent Provider/dependency blocks only its declaring Skill; an
  optional gap stays executable and moves Skill
  `forbidden_without_context` claims from allowed to forbidden. Provider text
  is data and never reaches the existing playbook/Plan/Operator owner.
- Extract the existing R07 Pack state machine into one reusable Context Broker,
  preserving Repo bytes. Exact R08 reads enter the same entity alias,
  valid/effective time, authority, sensitivity, freshness, budget,
  supersession, conflict, digest and public-content-redaction gates. Unaligned
  items remain excluded and cannot support confirmed claims.
- Perform exactly one R08 `read` per declared resource. R08 remains the sole
  owner of process capacity, concurrency, call count, timeout, cancellation,
  retry, output and circuit rules. R09C adds no pool, retry, cache or pagination
  and records only whether Provider RPC was called; Provider-internal network
  remains `not_observable`.
- Directly migrate formal `gravity.analysis-result.v1` from singular
  `context_pack` to ordered `context_packs[]`. Each old one-pack result becomes
  an array of one with the same fields/digest, while Repo plus external Packs
  remain exact instead of being discarded or falsely merged. Repository and
  canonical-consumer search found no work-dashboard consumer of the singular
  Analysis Result field, so no read capability is lost; SDK docs/tests migrate
  in the same unit.
- Add only one root export, `ExternalContextBindingResolver`. No CLI command,
  Journey, Product, Agent card, MCP Server, router, executor, Plan adapter,
  operation, permission system or worker pool is added. Test-only dependency
  fixtures reuse `ReferenceJourneyRunner` and its existing executor.
- Acceptance covers tracked/dirty/tampered/conflicting bindings; required and
  optional Provider matrices; denied/unavailable/timeout/circuit/budget cases;
  entity/time/authority/freshness/sensitivity/supersession/conflict alignment;
  claim narrowing, plural Result parity, prompt-injection exclusion, RPC call
  counts and unchanged Repo/Built-in behavior.
- Final gates include focused public/Core/R07/R08 tests, isolated installed
  wheel, both complete collectors, compiler/quality/generators, development
  usability/security, CLI help, retained consumer non-regression and
  `git diff --check`; active human docs remain exactly 5500 lines.

## Bound Baseline

At the bound baseline, R09A consumed Repo Context only. R08 defined external
Provider/RPC boundaries but intentionally did not bind them into Skill
readiness or Analysis Result claims.

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
