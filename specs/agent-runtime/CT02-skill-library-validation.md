# CT02 Canonical Skill Library Validation

| Field | Value |
| --- | --- |
| Status | `fixed_dev` |
| Owner | `skills/library/*.json` |
| Dependencies | `CT01`, `R09B` |

## Contract

Each independently authored Skill has exactly one checked-in canonical manifest.
Machine identities use `gravity.core.*`, `gravity.game.*`,
`gravity.game.<genre>.*`, `org.<company>.*`, or `project.<game>.*`. The current
cross-game library uses `gravity.core` for reusable data and contract methods and
`gravity.game` for game-analysis methods; no genre namespace is asserted without
genre-specific evidence.

Machine IDs, URIs, schemas, reason codes, and artifact kinds are stable English.
Names, methods, diagnostic steps, example questions, output sections, and repair
guidance default to `zh-CN`. Provenance contains only an opaque Source Registry
reference and independent-authorship decision.

## Acceptance

- All canonical manifests validate against `gravity.skill.v1`.
- Skill and Journey identities use the same neutral namespace and dependency
  contract.
- Canonical manifests contain no vendor name, URL, source title, marketing
  effect number, or imported source body.
- No second JSON, Markdown, package tree, ZIP, Hub index, or lock copy is
  checked in for the same Skill.
