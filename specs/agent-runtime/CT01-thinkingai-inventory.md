# CT01 ThinkingAI Source Inventory

| Field | Value |
| --- | --- |
| Parent directive | `gravity-agent-runtime/v9.1` via `directive.json` |
| Status | `specified` |
| Track | Parallel content |
| Dependencies | R00 |
| Parallel group | `content-a` |
| Main integration | Frozen until whole program completion |

## Outcome

Every publicly discoverable ThinkingAI Skill topic in an approved source snapshot is represented once in a reproducible inventory and migration matrix with source identity, change state, independent-authorship and license-review status.

## Current Baseline

The public catalog is dynamic and mixes advertised totals, categories and detail pages. The repository has research references but no current source adapter, closed link inventory or machine migration matrix.

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
