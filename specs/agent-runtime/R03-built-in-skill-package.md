# R03 Built-in Skill Package And Render Model

| Field | Value |
| --- | --- |
| Parent directive | `gravity-agent-runtime/v9.1` via `directive.json` |
| Status | `specified` |
| Track | Skill packaging foundation |
| Dependencies | R01 |
| Parallel group | `foundation-a` |
| Main integration | Frozen until whole program completion |

## Outcome

Built-in Runtime Skills have one authoritative JSON model that deterministically renders wheel resources, repository documentation and Agent Skills-compatible exports without becoming a second execution DSL.

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

## Acceptance

- JSON schema, determinism and parity gates pass.
- Installed wheel provides the same Skill identity and guide as the checkout.
- Agent Skills `SKILL.md` satisfies name/description/path constraints with deterministic namespace collision handling.
- Skill dependency or readiness gaps are machine-readable.
- Existing routing and execution behavior are unchanged.

## Verification

Render golden tests, repeated build digest equality, wheel installation test, package-data census, Agent Skills schema validation, tampered package rejection, docs generation check and full repository gates.

## Rollback And Exit

The old generated docs path may remain only as a generated compatibility view with an explicit removal gate. Removing the new package layer restores old guide generation without affecting execution.

## Canonical Owners

Skill schema, Built-in package resources, generator, Agent Skills exporter, `docs/agent-skills/` generated mirror and SDK/CLI reference.
