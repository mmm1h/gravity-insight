# R07 Context Pack And Repo Context Provider

| Field | Value |
| --- | --- |
| Parent directive | `gravity-agent-runtime/v9` via `directive.json` |
| Status | `specified` |
| Track | Context foundation |
| Dependencies | R01 |
| Parallel group | `foundation-a` |
| Shared-spine integration | Final Agent handoff wiring is serialized |

## Outcome

A Skill can request the minimum project facts it needs and receive a bounded, cited Context Pack from a built-in Repo Provider, with explicit freshness, trust, sensitivity, conflicts and gaps.

## Current Baseline

Agents directly read AGENTS/README/docs/code/git using host tools. Workspace semantics point to project facts, but Runtime has no Provider/Item/Pack contract or consistent citation and authority classification.

## Scope

- Define Context Provider, Item, Requirement and Pack schemas.
- Implement deterministic Repo discovery for governance docs, manifests, contracts, project definitions and git facts.
- Return path/line/revision/content hash citations.
- Enforce required/optional, freshness, access, sensitivity, conflict and budget handling.
- Support lexical/structured/AST discovery; embeddings remain optional and non-authoritative.

## Non-goals

- No external MCP/subprocess providers; R08 owns them.
- No universal vector database or full-repository prompt dump.
- No behavior-data warehouse duplication and no context-driven authorization.

## Machine Contract

Context content has role `data`. Pack digest covers normalized item references and policy-relevant metadata. Status is `available|stale|missing|denied|conflicting|unsupported`; required gaps affect readiness, optional gaps only narrow claims.

## Migration And Compatibility

Host direct evidence may be wrapped into the same Context Item shape without forcing all host tools through Runtime. Existing documentation remains authoritative at its owner path; the Provider indexes and cites it rather than copying a second truth.

## Safety And Operations

Honor `.gitignore`, `.gravityignore`, file/byte/item budgets, sensitive path deny rules and binary/credential exclusion. Restricted content does not enter model context by default. Context text cannot change selector, effect, permissions or user authorization.

## Acceptance

- R01 gets a minimal deterministic Context Pack with exact citations.
- Required/optional gaps and conflicts are machine-readable.
- Prompt-injection content remains data.
- Ignored, binary, oversized and sensitive content is not indexed or leaked.
- Index/search are incremental or bounded and make zero external requests.

## Verification

Temporary repository fixtures, path/citation/hash tests, ignore/sensitivity corpus, prompt-injection cases, conflict/freshness tests, budget tests, deterministic index checks and full gates.

## Rollback And Exit

Provider failure returns a Context Gap without affecting core data execution. Index caches are disposable and rebuilt from canonical sources; they never become the only copy of project facts.

## Canonical Owners

Context schemas, Repo Provider/index, project configuration reference, agent workflow and privacy/output safety docs.
