# Local MCP stdio pilot

`gravity-mcp` is an experimental, removable local MCP server for Host trials. CLI, SDK and Plan remain authoritative. The process reads newline-delimited JSON-RPC 2.0 from stdin, writes protocol messages only to stdout and writes value-free diagnostics to stderr.

## Host configuration

Configure the Host to launch this command from the intended Gravity workspace:

```text
gravity-mcp
```

Credentials and workspace configuration come from the same local environment as `GravitySDK.from_env`. Never put credentials in Tool arguments, Resource URIs or Host-visible server configuration fields.

The server implements modern MCP protocol `2026-07-28`. Clients start with `server/discover` or send a request containing these `_meta` fields:

```json
{
  "io.modelcontextprotocol/protocolVersion": "2026-07-28",
  "io.modelcontextprotocol/clientInfo": {"name": "host", "version": "1"},
  "io.modelcontextprotocol/clientCapabilities": {}
}
```

Legacy `initialize` and `2025-11-25` session behavior are not supported by this pilot. There is no HTTP transport, OAuth flow, prompt catalog or remote server.

## Tools

| Tool | Effect | Existing owner |
| --- | --- | --- |
| `gravity.inspect` | Local metadata read | server/Journey/Skill owners |
| `gravity.journey_can_run` | Readiness read | `JourneyService.can_run` |
| `gravity.capability_describe` | Trust read | `CapabilityTrustService.trust` |
| `gravity.execute` | Registered Journey read execution | `JourneyService.run` |
| `gravity.export` | Confirmed local file write | `AnalysisArtifactService` |
| `gravity.context_pack` | Bounded local repository read | `RepoContextProvider` |

`gravity.execute` accepts a registered `journey_id` and closed inputs. It does not accept an operation ID, URL, HTTP method, raw SQL or wire JSON. Export requires `confirm: true`; rejected or unconfirmed calls perform no target network request and no local write.

## Resources

Static Resources expose server metadata and the current Capability, Journey, Skill, App, SQL-product and Receipt catalogs. The server also exposes:

```text
gravity://apps/{app}/saved-analyses
gravity://metadata/table-lineage/{query}
gravity://workspace/analysis-vocabulary/{query}
```

Only configured, access-allowed App aliases are readable. Resource pages are stably sorted and cursor-paginated. Cached values are bounded and isolated by opaque principal plus workspace scope.

The feasibility draft also proposed App-scoped vocabulary, Dashboard and Segment directories. Vocabulary is workspace-scoped because that is the current public SDK contract; Dashboard and Segment directories are omitted until a public access-filtered directory owner exists.

## Pilot evidence

- CLI/SDK/MCP parity: `tests/fixtures/mcp_parity_corpus.json` and `MCPParityTests.test_frozen_cli_sdk_mcp_parity_corpus`.
- Removability: `tests/fixtures/mcp_removability_surfaces.json` and `MCPRemovabilityTests`.
- Zero target requests and stdout isolation: `MCPProtocolTests` and `MCPResourceTests.test_access_filtering_happens_before_cache_or_sdk_access`.

The dependency choice is a minimal in-repository JSON-RPC stdio layer. No official `mcp` SDK or transitive Runtime dependency is added. Protocol evolution is therefore an explicit maintenance responsibility of this removable package.

Graduation and rollback are governed by [R10 MCP Thin Surface](../../specs/agent-runtime/R10-mcp-thin-surface.md).
