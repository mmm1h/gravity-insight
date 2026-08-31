# CT01 External Method Source Registry

| Field | Value |
| --- | --- |
| Status | `fixed_dev` |
| Owner | `skills/sources/registry.json` |
| Runtime visibility | `agent_default_visible=false` |

## Contract

The repository keeps one isolated Source Registry for externally researched
method topics. It contains only source URLs, legal and copyright review state,
source versions, content hashes, and independent-authorship evidence. Runtime
Skill, Product, Journey, Schema, Reason Code, Artifact Kind, module, path, and
environment-variable identities must remain vendor neutral.

Canonical Skills reference registry entries only through
`source://external-method/<opaque-id>`. The registry is not imported by Agent
catalog, routing, Plan, CLI, or SDK surfaces. Source text, customer cases,
marketing claims, and effect figures are not distributable content.

## Acceptance

- `skills/sources/registry.json` validates against
  `gravity.external-method-source-registry.v1` and its canonical digest.
- Opaque IDs are deterministic, unique, and sorted.
- Every mapping declares legal review and independent-authorship evidence.
- Vendor-specific topics fail closed with `VENDOR_SPECIFIC_CAPABILITY`.
- The repository neutrality gate permits vendor names only inside this file.
