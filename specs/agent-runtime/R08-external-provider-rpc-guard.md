# R08 External Context Provider And RPC Guard

| Field | Value |
| --- | --- |
| Parent directive | `gravity-agent-runtime/v9.1` via `directive.json` |
| Status | `specified` |
| Track | Provider boundary |
| Dependencies | R07 |
| Parallel group | `foundation-b` |
| Main integration | Frozen until whole program completion |

## Outcome

External MCP, subprocess or host-provided Context sources project into the R07 contracts through a fail-closed RPC Guard. Runtime governs the call boundary without claiming control over Provider-internal networking.

## Current Baseline

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

## Rollback And Exit

Removing a Provider descriptor removes only its Context availability. Circuit and cache state are local and disposable. No core Journey without an explicit required dependency may fail merely because an optional Provider is absent.

## Canonical Owners

Provider/RPC schemas and guard, deployment/sandbox guide, Context reference, observability and security documentation.
