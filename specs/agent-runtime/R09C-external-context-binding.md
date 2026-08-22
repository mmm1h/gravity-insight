# R09C External Context Binding

| Field | Value |
| --- | --- |
| Parent directive | `gravity-agent-runtime/v9.1` via `directive.json` |
| Status | `fixed_dev`; integrated and validated on `dev` 2026-08-22 |
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
the baseline/worktree/gates below, advanced R09C through `reviewed` and `ready`
to `in_progress`, then accepted the validated implementation as `fixed_dev`.
This does not authorize live Providers, credentials,
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

## Fixed Dev Evidence

- Feature commit `debd481` and merge `52dbd57` add the tracked
  `gravity.external-context.json` registry, strict external requirement and
  public Context Item reference schemas, and one public
  `ExternalContextBindingResolver`. Root public API now has `127` lazy exports
  and `gravity_sdk.__all__` has `128` entries including `__version__`.
- Binding compilation normalizes exact R08 descriptors and Skill/Journey/
  resource requirements, rejects unsafe/duplicate/out-of-prefix resources and
  requires one tracked, clean Git snapshot. Runtime accepts only explicitly
  injected Provider instances with the same URI/digest. A committed subprocess
  descriptor without injection produces a gap and cannot construct a transport
  or call `Popen`; no list/search/discovery/credential fallback exists.
- R07's existing Pack state moved into `ContextPackBroker`; Repo Context
  behavior remains characterized and byte-equivalent. External exact reads use
  the same entity alias, valid/effective time, authority, sensitivity,
  freshness, total budget, supersession, conflict, readiness, digest and
  public-content-redaction gates. Prompt-injection bodies never enter Core,
  snapshot, playbook or Analysis Result.
- R08 remains the only RPC execution owner. R09C performs one exact `read` per
  resource per resolution and adds no executor, pool, retry, cache or
  pagination. Provider absence, descriptor mismatch, unavailable, timeout,
  circuit, denied, stale, unaligned, conflicting and over-budget outcomes keep
  stable reasons; Pack audit distinguishes `provider_rpc_called` while internal
  I/O is uncontrolled and internal networking stays `not_observable`.
- Core reads no external file and calls no Provider for Repo-only Skills.
  Required gaps block before `ReferenceJourneyRunner`; optional gaps keep the
  existing owner executable and move `forbidden_without_context` claims from
  allowed to forbidden. Test-only optional success restores the claim, performs
  exactly two reads for the runner's before/after snapshot comparison and
  executes the unchanged playbook/Plan/Operator path.
- Formal `gravity.analysis-result.v1` directly replaces singular
  `context_pack` with ordered `context_packs[]`; snapshot was already plural.
  Each old one-Pack result is preserved as an array of one with identical
  fields/digest, while Repo plus external Packs remain lossless. Strict public
  item-reference and Pack compilers reject missing/reordered/extra/private
  fields. Repository and canonical-consumer search found no singular Result
  field consumer, so the breaking surface loses no read capability.
- Extended R07-R09C and R09A/R09B/public/docs focused gates pass `137` tests and
  `60` subtests; integrated R09C/public/docs gates pass `48` tests and `16`
  subtests. Complete gates pass `1609` unittest; `1609 passed, 3830 subtests`
  pytest; compiler `237 operations / 11 manifests`; quality, both generators,
  CLI, targeted Ruff and diff checks PASS; active docs remain exactly `5500`
  lines.
- Development usability remains `296/336` selection, `248/248` fillability,
  `53/53` offline terminal and `5/5` recovery; security PASS and production HTTP
  requests `0`. No production/external Provider request was made. The isolated
  installed-wheel import/export/schema/empty-dependency gates pass from
  `site-packages`; wheel SHA-256 is
  `ff08a7622a5a690453b6a05a4d62860b2d6923c572cb0e0bb51810c7f214628c`.
- Retained work-dashboard consumer `e4369ce8` declares only Built-in/Repo
  Context, has no external binding and has no singular Analysis Result field
  consumer. Its current-SDK focused suite passes `11` tests and `94` subtests;
  the branch remains clean and no unrelated frozen or business path changed.

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
