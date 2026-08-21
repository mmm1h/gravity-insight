# R10 MCP Thin Surface

| Field | Value |
| --- | --- |
| Parent directive | `gravity-agent-runtime/v9` via `directive.json` |
| Status | `specified`; conditional |
| Track | Host protocol surface |
| Dependencies | R09 plus trigger |
| Parallel group | `optional-surface` |
| Shared-spine integration | Required and serialized |

## Trigger

At least two real Host/consumer integrations require MCP and a CLI/SDK parity corpus is frozen, or the user explicitly approves a bounded pilot with exit conditions. Architecture inclusion alone does not make this requirement ready.

## Outcome

MCP exposes Skill, Journey, Semantic, Context, Capability and Receipt references primarily as Resources and delegates a small set of execution Tools to existing Runtime services with no independent business logic.

## Current Baseline

CLI, Python SDK and Plan are authoritative. Current research deliberately defers MCP without a second consumer and frozen acceptance corpus.

## Scope

- Implement resource listing/templates/read with pagination and access filtering.
- Expose a minimal inspect, can-run, capability describe, execute, export and context-pack Tool set.
- Generate versioned server metadata for configured discovery.
- Prove CLI/SDK/MCP semantic parity.

## Non-goals

- No per-Skill Tool explosion.
- No MCP-owned router, binder, pagination, cache, permission, error mapping or execution engine.
- No dependency on a public Registry for local operation.

## Machine Contract

Custom URIs are RFC3986-compliant and versioned. MCP errors map existing stable Runtime reasons without inventing alternate statuses. Resource listing never discloses unauthorized identities.

## Migration And Compatibility

Removing MCP must leave every Journey available through CLI/SDK/Plan. Server artifacts version separately from Skill packages. Public Registry discovery is optional and non-authoritative.

## Safety And Operations

Tool annotations are untrusted metadata, not authorization. Output budgets, identity, privacy and effects delegate to Runtime. Invalid/blocked calls perform zero target network requests.

## Acceptance

- Trigger evidence is recorded.
- Frozen parity corpus passes across CLI, SDK and MCP.
- MCP removal changes no Runtime capability.
- Resources/Tools and read/mutation effects are correctly separated.
- Registry or network discovery outage does not affect locked local execution.

## Verification

Protocol conformance, pagination, access filtering, parity corpus, malformed requests, output budgets, mutation confirmation, local/offline behavior and full gates.

## Rollback And Exit

Disable or remove the adapter without data migration. A pilot that fails parity or consumer value returns to `blocked` and does not create compatibility obligations.

## Canonical Owners

MCP server metadata/adapter, protocol reference, plugin/host setup docs and consumer parity corpus.
