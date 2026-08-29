# R10 MCP Thin Surface

| Field | Value |
| --- | --- |
| Parent directive | `gravity-agent-runtime/v9.1` via `directive.json` |
| Status | `in_progress`; bounded local pilot; `owner_review: pending` |
| Track | Host protocol surface |
| Dependencies | R09A plus trigger |
| Parallel group | `optional-surface` |
| Shared-spine integration | None for the pilot; standalone `gravity-mcp` entry point |

## Trigger

At least two real Host/consumer integrations require MCP and a CLI/SDK parity corpus is frozen, or the user explicitly approves a bounded pilot with exit conditions. Architecture inclusion alone does not make this requirement ready. R09B/R09C capabilities are exposed only when installed; they are not R10 prerequisites.

The second trigger branch was satisfied by the 2026-08-28 task directive: it
explicitly authorizes one removable local stdio pilot and binds the stop line
below. The recorded transition through `reviewed` and `ready` is
`agent_under_standing_owner_delegation`, with `owner_review: pending`; it is not
represented as retrospective item-by-item owner approval. Implementation is
bound to baseline `824f92524f5703d7cb7ba0b2d6a671befb51a45f`, branch
`codex/r10-mcp-stdio-pilot` and worktree `D:/git-pjt/gravity-sdk-r10mcp`.
A GitHub search found no matching R10/MCP issue, so `github_issue=null` is
recorded rather than inventing a binding.

## Outcome

MCP exposes Skill, Journey, Semantic, Context, Capability and Receipt references primarily as Resources and delegates a small set of execution Tools to existing Runtime services with no independent business logic.

## Current Baseline

CLI, Python SDK and Plan remain authoritative. The feasibility report's
`185 operations` baseline is historical; the implementation baseline compiles
`237 operations, 11 manifests`. MCP adds no operation. The later paired routing
evidence (`195/240` recognizer versus `235/240` host arm on holdout) strengthens
the reason to test host-native selection but does not itself prove MCP adoption.

## Scope

- Implement resource listing/templates/read with pagination and access filtering.
- Expose a minimal inspect, can-run, capability describe, execute, export and context-pack Tool set.
- Generate versioned server metadata for configured discovery.
- Prove CLI/SDK/MCP semantic parity.

The pilot publishes six experimental Tools: `gravity.inspect`,
`gravity.journey_can_run`, `gravity.capability_describe`, `gravity.execute`,
`gravity.export` and `gravity.context_pack`. `gravity.execute` accepts only an
exact registered Journey and never an operation/wire payload. `gravity.export`
requires explicit confirmation and delegates local JSON/Markdown delivery.

The resource contract publishes server metadata, Capability, Journey, Skill,
workspace App, SQL product and Receipt catalogs; saved analyses by configured
App; table-lineage search; and workspace-scoped analysis-vocabulary search.
The feasibility report's App-scoped vocabulary URI was changed because the
current public SDK owner is workspace-scoped. Dashboard and Segment directories
remain absent because there is no current public access-filtered directory owner.
Cache entries are bounded and keyed by opaque principal plus workspace scope;
access checks happen before cache lookup or SDK dispatch.

## Non-goals

- No per-Skill Tool explosion.
- No MCP-owned router, binder, pagination, cache, permission, error mapping or execution engine.
- No dependency on a public Registry for local operation.
- No Streamable HTTP, OAuth, prompt primitive, dual-era protocol mode or raw
  operation Tool.

## Machine Contract

Custom URIs are RFC3986-compliant and versioned. MCP errors map existing stable Runtime reasons without inventing alternate statuses. Resource listing never discloses unauthorized identities.

The server implements the released modern `2026-07-28` stdio protocol subset:
newline-delimited JSON-RPC 2.0, `server/discover`, per-request protocol metadata,
version rejection, Tools and Resources. It deliberately does not claim legacy
`2025-11-25` initialization compatibility. Server metadata schema
`gravity.mcp-server-metadata.v1` versions the experimental surface separately.

Dependency decision is `(b)`: the pilot owns a minimal JSON-RPC stdio adapter
and adds no Runtime dependency. The official `mcp` v2 package was rejected for
this removable leaf because its broad HTTP/auth/telemetry-oriented dependency
surface is disproportionate to one local transport. This concentrates the
explicit protocol-version maintenance cost in `src/gravity_sdk/mcp/server.py`.

## Migration And Compatibility

Removing MCP must leave every Journey available through CLI/SDK/Plan. Server artifacts version separately from Skill packages. Public Registry discovery is optional and non-authoritative.

## Safety And Operations

Tool annotations are untrusted metadata, not authorization. Output budgets, identity, privacy and effects delegate to Runtime. Invalid/blocked calls perform zero target network requests.

`stdout` contains protocol frames only. Suppressed owner output and value-free
adapter diagnostics go to `stderr`; neither stream logs tokens or production
response values. All pilot tests use offline SDK factories and make no real
production request.

## Acceptance

- Trigger evidence is recorded.
- Frozen parity corpus passes across CLI, SDK and MCP.
- MCP removal changes no Runtime capability.
- Resources/Tools and read/mutation effects are correctly separated.
- Registry or network discovery outage does not affect locked local execution.

Development parity is frozen in `tests/fixtures/mcp_parity_corpus.json` and
proves four inspect/readiness/trust/blocked-execution cases across CLI, SDK and
MCP on the same semantic fields. Removability is frozen in
`tests/fixtures/mcp_removability_surfaces.json`: every Journey retains its
CLI/SDK/Plan surface state, and non-MCP Runtime modules may not import MCP.

## Verification

Protocol conformance, pagination, access filtering, parity corpus, malformed requests, output budgets, mutation confirmation, local/offline behavior and full gates.

## Rollback And Exit

Disable or remove the adapter without data migration by deleting the standalone
package, entry point, reference and MCP-only tests/fixtures. No Runtime module,
Journey artifact or user data requires migration.

The pilot does not graduate unless both real-host evidence and adoption pass.
For development, run the frozen 20-question set on each declared Host version
without host-specific prompts and record first-choice Tool/variant, legal final
answer, MCP RPCs and internal HTTP requests. The required floor is at least
`18/20` first-choice correct (baseline `12/20`) and `12/20` legal answers
(baseline `4/20`). Final graduation also runs a blind 20-question holdout written
after implementation by a reviewer who did not build the adapter, at the same
threshold. At least one existing consumer must complete a real trial and a
second independent Host/consumer must confirm adoption intent.

The plan owner judges the recorded evidence; this branch cannot self-approve
graduation. Failure of any threshold, loss of structured errors in a target
Host, or absence of the second adopter returns R10 to `blocked`, removes/disables
the server, and retains at most the versioned schema descriptions. It must not
be promoted to a permanent fifth surface.

## Canonical Owners

MCP server metadata/adapter, protocol reference, plugin/host setup docs and consumer parity corpus.

## Status Adjudication (2026-08-29)

- The frozen development 20-question set is the `fixed_dev` gate. R10 lines
  122-126 explicitly say "For development" and set the `18/20` first-choice and
  `12/20` legal-answer floors. Architecture source lines 267-268 define
  `fixed_dev` as dev acceptance and cap all program features at that state
  before program completion.
- The blind holdout and second independent Host/consumer bind final graduation,
  `released`, and permanent-surface retention. R10 lines 126-129 add the blind
  holdout with "Final graduation also" and require the second adopter;
  architecture source line 269 reserves `released` for later main promotion,
  while R10 line 135 protects the permanent fifth-surface decision.
- The blind holdout and second-adopter requirements are not cancelled or
  weakened. Under this adjudication, the broad failure language at R10 lines
  132-135 applies those final-graduation failures to the `released`/permanent
  surface side; the development thresholds continue to govern `fixed_dev`.
- The newly frozen development suite is
  `tests/fixtures/mcp_host_development_questions.json`, with evidence in
  `tests/fixtures/mcp_host_development_evidence.json`. The offline surrogate
  scored `15/20` first-choice and `15/20` legal answers across `120` MCP RPCs,
  with `0` internal and production HTTP requests. No real Host versions are
  declared or locally available, so this is not Claude Desktop or Cursor
  evidence. Because first-choice is below `18/20`, R10 remains `in_progress`.

`recorded_by: agent_under_standing_owner_delegation`

`owner_review: pending`
