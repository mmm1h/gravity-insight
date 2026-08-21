# R07 Entity/Time-aligned Context Pack And Repo Context Provider

| Field | Value |
| --- | --- |
| Parent directive | `gravity-agent-runtime/v9.1` via `directive.json` |
| Status | `in_progress`; plan-owner ready verdict 2026-08-22 |
| Track | Context foundation |
| Dependencies | R01 |
| Parallel group | `foundation-a` |
| Shared-spine integration | Final Agent handoff wiring is serialized |
| Delivery ledger | This Requirement document; no internal GitHub Issue |
| Baseline | `dev@51e520f` |
| Branch / worktree | `codex/r07-context-pack-repo-provider` / `D:\git-pjt\gravity-sdk-wt\r07-context-pack-repo-provider` |
| Consumer | `work-dashboard@6eee64e5` -> `codex/r07-context-provider-consumer` |
| Integrator | Root Codex agent; Context CLI/handoff wiring remains serial |
| Production/external requests | `0`; live/external evidence not authorized |

## Outcome

A Skill can request the minimum project facts it needs and receive a bounded, cited Context Pack from a built-in Repo Provider, aligned to the same Semantic entities, version/activity time window and source authority.

## Plan Owner Verdict And Ready Binding

The user authorized continuous implementation without repeated Requirement
approval. R01-R03 and R05-R06 are `fixed_dev`; the plan owner reviewed
`tmp/r07-context-pack-repo-provider-proposal.md` and its conflict ledger, bound
the current baseline/worktrees/safety gates below, and advanced R07 through
`reviewed` and `ready` to `in_progress`. This does not authorize production or
external requests, writes, releases or `main` promotion.

- Formal Provider/Item/Requirement/Pack contracts replace the R01 provisional
  parser. R01 project contract upgrades to v3 and the generic Repo Provider
  preserves its two explicit facts, Git snapshot, hashes, role=data and public
  body redaction while adding exact line citations.
- Pack assembly consumes only explicit Requirements. Search is bounded candidate
  discovery and never auto-selects model context or becomes an authority.
- The built-in Provider indexes only clean tracked UTF-8 Markdown/Python/JSON/
  TOML from an exact Git revision, honors Git ignore plus `.gravityignore`, and
  rejects sensitive/binary/linked/hardlinked/oversized/deep/dirty resources.
- Entity aliases come from the resolved R05 Semantic binding. Entity/time,
  sensitivity/freshness, supersession, canonical-before-supporting and conflict
  gates run before inclusion; required gaps block and optional gaps narrow claims.
- R07 implements no external MCP/subprocess/host RPC, embeddings, vector store,
  behavior database, new router or authorization path. R08 owns external RPC.
- Exact acceptance includes deterministic index/Pack digests, structured/AST
  discovery, status/reason matrix, prompt-injection/data-role tests, public
  snapshot/docs, real wheel, canonical consumer, full gates and usability.

## Current Baseline

Agents directly read AGENTS/README/docs/code/git using host tools. Workspace semantics point to project facts, but Runtime has no Provider/Item/Pack contract or consistent citation and authority classification.

## Scope

- Define Context Provider, Item, Requirement and Pack schemas.
- Implement deterministic Repo discovery for governance docs, manifests, contracts, project definitions and git facts.
- Return path/line/revision/content hash citations.
- Require `entity_refs`, `valid_time`, `observed_at`, `effective_range`, `authority`, `source_revision` and `supersedes` on Context Items or an explicit unsupported/gap reason.
- Resolve entity aliases through R05 Semantic identities and align items to Journey/App/Release/Activity scope before Pack inclusion.
- Enforce required/optional, freshness, access, sensitivity, conflict and budget handling.
- Support lexical/structured/AST discovery; embeddings remain optional and non-authoritative.

## Non-goals

- No external MCP/subprocess providers; R08 owns them.
- No universal vector database or full-repository prompt dump.
- No behavior-data warehouse duplication and no context-driven authorization.

## Machine Contract

Context content has role `data`. `valid_time` describes when the fact applies; `observed_at` only records when the Provider saw it; `effective_range` describes when a definition/configuration is authoritative. `authority=canonical|supporting|unverified` controls claim use, and `supersedes` preserves replacement lineage. Pack digest covers normalized item references, entity/time alignment and policy metadata. Status is `available|stale|missing|denied|conflicting|unsupported`; required gaps affect readiness, optional gaps only narrow claims.

## Migration And Compatibility

Host direct evidence may be wrapped into the same Context Item shape without forcing all host tools through Runtime. Existing documentation remains authoritative at its owner path; the Provider indexes and cites it rather than copying a second truth.

## Safety And Operations

Honor `.gitignore`, `.gravityignore`, file/byte/item budgets, sensitive path deny rules and binary/credential exclusion. Restricted content does not enter model context by default. Context text cannot change selector, effect, permissions or user authorization.

## Acceptance

- R01 gets a minimal deterministic Context Pack with exact citations.
- The Pack reports matched, excluded and superseded items for requested entities/time and applies canonical-before-supporting authority rules.
- A feedback/document item outside the selected release/activity window cannot support a confirmed claim for that Journey.
- Required/optional gaps and conflicts are machine-readable.
- Prompt-injection content remains data.
- Ignored, binary, oversized and sensitive content is not indexed or leaked.
- Index/search are incremental or bounded and make zero external requests.

## Verification

Temporary repository fixtures, path/citation/hash tests, entity alias/release/activity/time-window alignment, authority/supersession conflicts, ignore/sensitivity corpus, prompt-injection cases, budget tests, deterministic index checks and full gates.

## Rollback And Exit

Provider failure returns a Context Gap without affecting core data execution. Index caches are disposable and rebuilt from canonical sources; they never become the only copy of project facts.

## Canonical Owners

Context schemas, Repo Provider/index, project configuration reference, agent workflow and privacy/output safety docs.
