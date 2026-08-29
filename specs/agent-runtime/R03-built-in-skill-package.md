# R03 Built-in Skill Package And Render Model

| Field | Value |
| --- | --- |
| Parent directive | `gravity-agent-runtime/v9.1` via `directive.json` |
| Status | `fixed_dev`; accepted on `dev@0ca8681f` 2026-08-22 |
| Track | Skill packaging foundation |
| Dependencies | R01 |
| Parallel group | `foundation-a` |
| Main integration | Frozen until whole program completion |
| Delivery ledger | This Requirement document; no internal GitHub Issue |
| Baseline | `dev@4f8195e5c51d7df0bd2a84387d98af9efb431367` |
| Branch / worktree | `codex/r03-built-in-skill-package` / `D:\git-pjt\gravity-sdk-wt\r03-built-in-skill-package` |
| Integrator | Root Codex agent; root CLI registration remains serial |
| Canonical consumer | Existing R01 consumer smoke only; no consumer file migration required for the additive package surface |
| Production requests | `0`; live evidence not authorized |

## Outcome

Built-in Runtime Skills have one authoritative JSON model that deterministically renders wheel resources, repository documentation and Agent Skills-compatible exports without becoming a second execution DSL.

## Plan Owner Verdict And Ready Binding

The user authorized continuous implementation without repeated Requirement
approval. R01/R02 are `fixed_dev`; the plan owner reviewed
`tmp/r03-built-in-skill-package-proposal.md` and its architecture conflict
ledger, bound the baseline/worktree/safety gates below, and advanced R03 through
`reviewed` and `ready` to `in_progress`. This does not authorize production
probing, remote Hub activity, environment mutation, release or `main` promotion.

- The current R01 manifest becomes the sole structured Render Model. Package
  resources, docs and Agent Skills output are generated views, never a second
  hand-edited authority.
- The manifest gains orthogonal specification/lifecycle/readiness/validation
  and complete typed dependencies. Routing remains hints-only and cannot alter
  host catalog, recognizer, effects or Plan execution.
- `LocalSkillResolver` scans only fixed Built-in manifests/resources, reads no
  remote source and imports no package code. R02 Capability Trust supplies
  current dependency readiness without executing the Skill.
- Ordinary Skill packages remain stricter than the open Agent Skills format:
  no `scripts/`, executable bits, links, absolute/parent paths, duplicate/case
  collisions or unbounded content.
- Official Agent Skills name/description/path constraints are bound from
  `https://agentskills.io/specification` as read on 2026-08-22. Export names
  include namespace and use a deterministic hash suffix for normalization or
  length collisions.
- Public targets are `LocalSkillResolver` and
  `gravity skills list|show|export-agent`; Hub sync/CAS/locks and Trusted Packs
  remain R04. Existing R01 Journey and generated docs paths retain parity.
- Exact acceptance includes schema/path/tamper/determinism tests, repeated
  digest equality, docs/export parity, public snapshot, installed-wheel
  parity, current R01 blocked readiness, full repository gates, usability and
  existing consumer smoke.

## Current Baseline

`scripts/generate_agent_skills.py` currently generates task guides from product cards and schemas. Guides work from the checkout, but there is no formal Skill Manifest/package lifecycle, package digest or wheel-to-docs parity contract.

## Scope

- Define `gravity.skill.v1` manifest and package schemas exercised by the R01 Skill.
- Establish orthogonal specification, lifecycle, readiness and validation fields.
- Build one Render Model for package resources, docs mirror and Agent Skills export.
- Include deterministic content digest and provenance.
- Make Built-in Skill discovery and reading work from an installed wheel without checkout docs.

## Non-goals

- No remote Hub sync, CAS download, lock resolver or third-party package execution.
- No arbitrary scripts in packages.
- No Skill-controlled selector, adapter, HTTP, SQL or authorization.

## Machine Contract

Manifest dependencies reference versioned Capability, Semantic, Operator/Model, Context and Journey identities. Routing contains hints only; host catalog/recognizer remain authoritative. Package bytes, normalized paths and digest are deterministic across supported platforms.

## Migration And Compatibility

Existing generated Agent guides remain reachable until parity proves the new Render Model. Generated output must not become a hand-edited source. Any path migration updates docs links and true wheel package data in the same unit.

## Safety And Operations

Ordinary packages contain reviewed static content only. Reject absolute/parent paths, links, executable bits and unbounded files. External text is data and cannot change effects or instructions above the Skill boundary.

Package materialization writes only to an explicit caller-selected local path,
uses a same-parent temporary directory plus atomic rename, and refuses an
existing target. It never mutates Python environments or Runtime configuration.

## Acceptance

- JSON schema, determinism and parity gates pass.
- Installed wheel provides the same Skill identity and guide as the checkout.
- Agent Skills `SKILL.md` satisfies name/description/path constraints with deterministic namespace collision handling.
- Skill dependency or readiness gaps are machine-readable.
- Existing routing and execution behavior are unchanged.

## Verification

Render golden tests, repeated build digest equality, wheel installation test, package-data census, Agent Skills schema validation, tampered package rejection, docs generation check and full repository gates.

## Delivered Evidence

- Implementation `5116a0d` was merged as
  `dev@0ca8681f5c5206580fac86c1889ba66a3b032453`. The R01 manifest is now
  the sole `gravity.skill.v1` Render Model with orthogonal specification,
  lifecycle, readiness and validation plus typed dependencies, claims, budget,
  provenance and guide structure.
- Deterministic package digest is
  `7dc30f8468cb3be33dc4df6c68a102d63af6f629d81ff60c879bbda72e6b4516`.
  Five exact package files, the docs mirror and four-file Agent Skills export
  render from that manifest; both package/docs generators pass byte-level
  UTF-8/LF `--check` gates.
- Package validation rejects absolute/drive/parent paths, scripts,
  case-fold collisions, missing/extra/tampered files, links, hardlinks,
  executable bits, excessive count, file/total bytes and depth. Agent names
  meet the official 1..64/name-directory rules with deterministic collision
  and overlength suffixes; materialization is atomic and refuses overwrite.
- `LocalSkillResolver` and `gravity skills list|show|export-agent` load only
  fixed Built-in resources. Current R01 Skill readiness is
  `blocked/COMPLETENESS_INSUFFICIENT/network_called=false`; routing and the
  existing Journey/Plan executor are unchanged.
- Complete SDK gates: `1464` unittest tests; `1464 passed, 3687 subtests passed`
  under pytest; compiler `237 operations, 11 manifests`; quality PASS;
  actionable errors `1296 = 1132 A + 164 B + 0 C`; CLI and diff checks PASS.
- Development usability is unchanged at selection `296/336`, fillability
  `248/248`, offline terminal `53/53`, recovery `5/5`, security PASS and
  production HTTP requests `0`. Canonical consumer adoption/R01 remains
  `10 passed, 94 subtests` with no consumer file migration.
- Final isolated wheel `gravity_sdk-0.3.0-py3-none-any.whl` has SHA-256
  `2bfc8f9d09dba361a91dbc674cdb626bb9ddcac449d9ed7c31bd0fa9e82703bf`.
  It loaded the exact package from isolated `site-packages`, rendered the
  Agent export outside the checkout and preserved consumer R01 exit 4.
- Remote Hub calls, package code execution, environment mutation, production
  requests/writes, releases and `main` promotion performed by R03: `0`.

## Rollback And Exit

The old generated docs path may remain only as a generated compatibility view with an explicit removal gate. Removing the new package layer restores old guide generation without affecting execution.

## Canonical Owners

Skill schema, Built-in package resources, generator, Agent Skills exporter, `docs/agent-skills/` generated mirror and SDK/CLI reference.
