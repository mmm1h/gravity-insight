# R00 Product Constitution And Directive Governance

| Field | Value |
| --- | --- |
| Parent directive | `gravity-agent-runtime/v9.1` via `directive.json` |
| Status | `fixed_dev` |
| Track | Program bootstrap |
| Dependencies | None |
| Parallel group | `bootstrap` |
| Main integration | Frozen until whole program completion |

## Outcome

The repository consistently describes `gravity-insight` as the implementation repository for Gravity Agent Runtime. Codex can distinguish approved target architecture from current behavior, classify old rules, and select only an explicitly ready derived requirement.

## Current Baseline

At `dev@c1a8656`, `AGENTS.md`, README, roadmap, architecture and package metadata describe a standalone SDK whose long-term product boundary excludes most reusable business methods and registries. The current execution, routing, privacy, identity and consumer contracts remain valid behavior facts.

## Scope

- Store the complete approved architecture at the stable repository path `specs/agent-runtime/architecture-source.md` and bind it by ID, version and SHA-256.
- Establish the Requirement Index, dependency graph and status lifecycle.
- Update product goal, repository scope and controlled extension policy.
- Classify safety invariants, current behavior, transitional rules, legacy product assumptions and historical evidence.
- Freeze program work to `codex/* → dev`; no `main` integration before whole-program completion and new user approval.

## Non-goals

- No Runtime, Hub, Context, Trust, Operator, MCP or SQL Explorer implementation.
- No current public command, envelope, request budget or execution behavior change.
- No GitHub issue creation, release, tag or `main` mutation.

## Machine Contract

- `directive.json` is the machine binding to the single approved architecture source.
- `index.json` is the authority for requirement IDs, dependencies, status and main integration policy.
- A document cannot self-promote to `ready`; approval is external and recorded in the index or issue workflow.
- `fixed_dev` and `released` are distinct states.

## Migration And Compatibility

Existing safety, fixed route, fail-closed, privacy, identity, request budget and canonical consumer rules remain binding. Legacy product-scope rules may be superseded only through an explicit conflict-ledger decision; a safety rule cannot be superseded without user approval.

## Safety And Operations

This requirement is documentation-only and performs zero production requests. The repository-canonical architecture source is fully readable by Codex; the original download file is provenance only, not an inaccessible authority.

## Acceptance

- All constitutional documents agree on target product and current-vs-target distinction.
- Requirement graph is complete, acyclic and references existing files.
- Program-wide `main` freeze is explicit.
- No feature implementation or current capability claim is introduced.

## Verification

Run documentation tests, JSON parsing and dependency validation, link checks, `python -m gravity_insight --help`, and `git diff --check`. Full runtime tests are not required solely for prose unless repository documentation gates import or generate runtime artifacts.

Validation record at `dev@c1a8656` working baseline on 2026-08-21:

```text
v9 requirement graph: 20 requirements, acyclic, all files present
documentation unittest: 11 passed
documentation pytest: 11 passed
full unittest: 1389 passed
full pytest: 1389 passed, 3632 subtests passed
compiler check: 237 operations, 11 manifests
quality check: PASS
development usability: 336 cases, security gate PASS, production requests 0
CLI help: PASS
git diff --check and specs whitespace/link checks: PASS
```

v9.1 review-correction record at `dev@fcdf10d` working baseline on 2026-08-21:

```text
canonical architecture source: repository-readable, directive digest verified
requirement graph: 24 executable requirements, 7 staged-epic milestones, acyclic
R09: split into R09A/R09B/R09C
R13: split into R13A/R13B/R13C
R12/R14: staged-epic delivery gates recorded
Team Trusted Pack and Context entity/time/authority contracts: recorded
documentation unittest/pytest: 11/11 passed on both runners
full unittest: 1389 passed
full pytest: 1389 passed, 3632 subtests passed
compiler and quality checks: PASS
development usability: 336 cases, security gate PASS, production requests 0
CLI help, local links, whitespace and diff checks: PASS
```

## Rollback And Exit

Rollback is the documentation diff. R00 reaches `fixed_dev` after validation but remains unreleased until the whole program is promoted to `main` under a later user decision.

## Canonical Owners

`architecture-source.md`, `AGENTS.md`, README, `docs/roadmap.md`, `docs/architecture.md`, `docs/index.md`, `pyproject.toml`, `directive.json` and Requirement Index.
