# R08 External Context Provider And RPC Guard

| Field | Value |
| --- | --- |
| Parent directive | `gravity-agent-runtime/v9.1` via `directive.json` |
| Status | `fixed_dev`; integrated and validated on `dev` 2026-08-22 |
| Track | Provider boundary |
| Dependencies | R07 |
| Parallel group | `foundation-b` |
| Delivery ledger | This Requirement document; no internal GitHub Issue |
| Baseline | `dev@30687b1` |
| Branch / worktree | `codex/r08-external-provider-rpc-guard` / `D:\\git-pjt\\gravity-sdk-wt\\r08-external-provider-rpc-guard` |
| Integrator | Root Codex agent; no shared-spine wiring is authorized |
| Production/external requests | `0`; tests use injected callables and local fixture processes only |
| Main integration | Frozen until whole program completion |

## Outcome

External MCP, subprocess or host-provided Context sources project into the R07 contracts through a fail-closed RPC Guard. Runtime governs the call boundary without claiming control over Provider-internal networking.

## Plan Owner Verdict And Ready Binding

The user authorized continuous implementation without repeated Requirement
approval. R07 is `fixed_dev`; the plan owner reviewed
`tmp/r08-external-provider-rpc-guard-proposal.md` and its conflict ledger,
bound the current baseline/worktree/safety gates below, and advanced R08 through
`reviewed` and `ready`, and accepted the validated implementation as
`fixed_dev`. This does not authorize a live Provider, credentials,
production/external requests, package installation, release or `main`
promotion.

- External descriptors are read-only and explicit. RPC requests allow only
  `list/search/read/list_changed`; returned URLs, tool names and text are inert
  data and cannot select a Product, effect or authorization.
- One process-wide Provider executor plus per-descriptor semaphore/call budget
  owns concurrency. It does not nest a Plan worker pool or govern Provider-
  internal I/O. Enforced and self-reported statistics remain separate.
- Timeout/cancel/retry/output/circuit rules are fail-closed. Retry occurs only
  after a pre-response unavailable failure and consumes the same call budget;
  one half-open probe follows cooldown.
- MCP/Host are injected callable transports. Subprocess is an explicit absolute
  executable/fixed argv/in-root cwd with no shell, sanitized environment,
  bounded streams and process-tree termination. Only local fixtures execute.
- R08 normalizes exact reads to R07 Context Items or stable gaps and broadens
  reusable source revisions beyond Git SHA without changing existing Repo bytes.
  R07 remains Pack/alignment owner; R09C alone binds external dependencies.
- R10 MCP Server, R14 adaptive Runtime I/O, external writes, work-dashboard
  migration and shared-spine changes remain out of scope.
- Exact acceptance includes fake MCP/Host, real local subprocess timeout/cancel/
  cleanup/output/credential cases, permissions, retry/budget/concurrency,
  circuit/half-open, Context normalization, public API/docs, real wheel, full
  gates and unchanged usability/security with production HTTP zero.

## Fixed Dev Evidence

- `e7558e9` implements four external Provider/RPC schemas, exact descriptor and
  strict JSON compilers, a process-wide eight-slot Provider budget, per-session
  call/concurrency limits, timeout/cancel/retry/output/circuit enforcement,
  callable MCP/Host and bounded subprocess transports, and an agent-facing
  read-only facade; merge `17ca140` integrates it without shared-spine wiring.
- Runtime-enforced counters are separate from `provider_reported` internal
  I/O/retry/cache audit values and every result states internal networking is
  not observable or controlled. Circuit/metrics are isolated per Provider;
  unavailable alone retries, while timeout/malformed/oversize/error do not.
- Permission prefixes block unauthorized reads before RPC and silently filter
  list/search output without identities or provider error text. Strict UTF-8,
  duplicate-key/non-finite JSON, request ID, content hash, byte/token, URI and
  exact response/result schemas fail closed; search order grants no authority.
- Exact reads normalize to R07 Context Items with `role=data`. Reusable Context
  revisions now accept bounded exact external revisions while preserving Git
  SHA behavior byte-for-byte. Missing alignment is a stable gap; observed or
  untrusted sources become `authority=unverified` and cannot confirm claims.
- Local subprocess fixtures prove explicit absolute executable/fixed argv,
  in-root real cwd, no shell, no ambient `GRAVITY_*`, explicit provider env,
  bounded stdin/stdout/stderr, nonzero/malformed/output-bomb privacy, active
  cancellation and Windows/POSIX process-tree timeout cleanup. Public describe
  excludes executable, argv, cwd and environment values.
- Focused R08/R07/public/docs tests pass `58` tests and `28` subtests. Full gates
  pass `1574` unittest; `1574 passed, 3820 subtests` pytest; compiler
  `237 operations / 11 manifests`; quality PASS; public exports `121`; active
  docs remain exactly `5500` lines; CLI and staged diff checks PASS.
- Usability remains `296/336` selection, `248/248` fillability, `53/53` offline
  terminal and `5/5` recovery; security PASS and production HTTP requests `0`.
  The isolated wheel loaded all Provider schemas/exports and an empty Host RPC
  outside the checkout; wheel SHA-256 is
  `3fd61d667878746d7f2364e596d41c8f07d3c19b074874cab99effc68f66c074`.

## Starting Baseline

Host agents may already access GitHub, files, Feishu or other connectors independently. Runtime has no unified external Provider descriptor, RPC budget, cancellation or failure-isolation contract.

## Scope

- Define descriptor transport, effects, auth scope, resources, capabilities, freshness and trust.
- Govern RPC concurrency, call count, timeout, cancellation, retry boundary, output byte/token limits and circuit state.
- Require Provider-reported RPC statistics and optional self-reported internal I/O/cache statistics.
- Normalize resources into Context Items with entity/time/authority/supersession fields, or return an explicit alignment capability gap.
- Isolate Provider failure from core Gravity data execution.

## Non-goals

- Runtime does not control Provider-internal HTTP, SDK, database calls or egress.
- No external write tools; writes require a separate governed Action Connector.
- No inherited Gravity credentials or automatic execution of returned URLs/tool names.

## Machine Contract

Descriptor capabilities include list/search/read/list-changed, cancellation, caching, output formats, freshness and entity/time alignment semantics. Unsupported capabilities return stable reasons. Provider search rank is not entity/time authority; R07 Broker performs final alignment. Self-reported internal statistics are audit data, never proof that Runtime enforced those requests.

## Migration And Compatibility

Host-owned tools remain usable directly. A Provider integration is optional and cannot become a precondition for core data queries unless a Skill explicitly marks its Context as required.

## Safety And Operations

Subprocess launch uses a sanitized environment, bounded working directory, explicit executable/arguments, no inherited Gravity credentials, output limits and process-tree termination. Provider deployment owns egress/host allowlists and must declare them.

## Acceptance

- Timeout, cancellation, oversize, malformed and unavailable Providers return Context Gaps.
- Unauthorized resources are neither listed nor disclosed through errors.
- Runtime metrics distinguish enforced RPC counts from self-reported internal counts.
- Items without provable entity/time/authority metadata remain unverified and cannot support confirmed claims.
- Provider failure cannot consume the core request pool indefinitely.
- No returned content becomes instruction or authorization.

## Verification

Fake MCP/subprocess/host Providers, timeout/cancel/process cleanup, credential-environment tests, output bombs, permission filtering, circuit behavior, Context normalization and full gates.

Focused acceptance commands cover external Provider contracts/guard/transports,
R07 Context compatibility and public API. Final acceptance additionally runs
both complete test collectors, compiler/quality, development usability, isolated
wheel loading, CLI help and `git diff --check`.

## Rollback And Exit

Removing a Provider descriptor removes only its Context availability. Circuit and cache state are local and disposable. No core Journey without an explicit required dependency may fail merely because an optional Provider is absent.

## Canonical Owners

Provider/RPC schemas and guard, deployment/sandbox guide, Context reference, observability and security documentation.
