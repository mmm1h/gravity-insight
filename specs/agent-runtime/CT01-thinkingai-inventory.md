# CT01 ThinkingAI Source Inventory

| Field | Value |
| --- | --- |
| Parent directive | `gravity-agent-runtime/v9.1` via `directive.json` |
| Status | `in_progress` |
| Track | Parallel content |
| Dependencies | R00 |
| Parallel group | `content-a` |
| Main integration | Frozen until whole program completion |
| Delivery ledger | This Requirement document; no internal GitHub Issue |
| Baseline | `dev@6dace728670d4a295cd51e3d395b70631f6d19bc` |
| Branch / worktree | `codex/ct01-thinkingai-inventory` / `D:\git-pjt\gravity-sdk-wt\ct01-thinkingai-inventory` |
| Approved source snapshot | Chinese public `/skills/` observed `2026-08-24T10:10:30.857Z` |
| Gravity production requests | `0` |

## Outcome

Every publicly discoverable ThinkingAI Skill topic in an approved source snapshot is represented once in a reproducible inventory and migration matrix with source identity, change state, independent-authorship and license-review status.

## Current Baseline

The public catalog is dynamic and mixes advertised totals, categories and detail pages. The repository has research references but no current source adapter, closed link inventory or machine migration matrix.

## Plan Owner Verdict And Ready Binding

R00 is `fixed_dev`. Under the user's continuous implementation authorization,
the plan owner reviewed `tmp/ct01-thinkingai-inventory-proposal.md` and its
architecture conflict ledger, bound the approved public scope/copyright/license/
mapping/gates, and advanced CT01 through `reviewed` and `ready` to
`in_progress`. This does not authorize source-body retention, distributable
Skill content, production Gravity access, release or `main`.

- Bind source adapter `thinkingai-public-catalog-dom@1` to the public Chinese
  `/skills/` root, its visible category/detail links, robots and sitemap. The
  frozen observation has 55 unique detail links, no pagination, exact 55-link
  sitemap closure, HTTP 200 and matching final/canonical/H1 for every item.
- Detail body text was hashed inside the browser only. Commit URL, title,
  categories, status/closure and SHA-256 metadata; never body, descriptions,
  examples, images, charts, customer/effect numbers, raw HTML or marketing prose.
- Add strict observation/snapshot/diff schemas, append-only current artifacts and
  a deterministic generator/check. Counts derive from sorted items; duplicate,
  orphan, missing, unknown-category or unmapped items fail closed.
- Map source categories to closed Gravity taxonomy. Generic topics get future
  Skill IDs and `license_review=approved` only for metadata plus fully independent
  rewrite. `ae-*`/`te-*` proprietary operations are blocked and map to an
  out-of-scope alternative; automatic SQL generation also maps to the explicit
  Registered SQL/Explorer alternative.
- All CT01 items remain `distribution_allowed=false`; independent generic content
  is merely `required`. Blocked/needs-review items cannot advance to a
  distributable specification.
- Acceptance covers all diff states, link/category coverage, digest/order,
  unmapped/license gates, protected-content leakage, full gates, wheel and
  canonical consumer. Active human docs remain exactly 5,500 lines.

## Scope

- Define source snapshot and inventory schemas.
- Discover approved root/category/pagination/detail routes under bounded crawl rules.
- Record stable source ID, canonical URL, title, category, content hash, observed time and added/changed/removed/redirect/orphan state.
- Map each source topic to Gravity taxonomy and a future Skill ID or explicit out-of-scope alternative.
- Record `license_review = approved|blocked|needs_review` and independent-authorship state.

## Non-goals

- No Runtime schema changes, Skill execution or claim that vendor capabilities work in Gravity.
- No copying of page prose, examples, images, charts, customer/effect numbers or proprietary wording into distributable artifacts.
- No use of vendor marketing as operational evidence.

## Machine Contract

An inventory snapshot has source adapter/version, crawl scope, observed time, item count derived from items, sorted normalized entries and content digest. New unmapped discoverable pages fail the coverage gate; inaccessible/non-public content is outside the stated snapshot scope.

## Safety And Operations

Respect robots, terms, rate limits, caching and manual approval. Raw snapshots, if legally retained, live only in restricted research storage with retention/access controls and never in public packages or model output.

## Acceptance

- Root/category/detail link closure is explainable for the snapshot.
- Added/changed/removed/redirect/orphan diff is deterministic.
- No distributable artifact contains protected source body or marketing numbers.
- License-blocked items cannot advance to distributable specification content.
- Inventory activity does not block R00/R01 or access production Gravity.

## Verification

Frozen source fixtures, pagination/link closure, canonicalization, diff, unmapped failure, license status, marketing leakage and deterministic snapshot tests.

## Rollback And Exit

Source updates create a new immutable snapshot; they do not rewrite historical snapshots. Adapter failure retains the last valid inventory with stale/failed status and never fabricates coverage.

## Canonical Owners

Source adapter, inventory/migration matrix artifacts, research summary and content-track index.
