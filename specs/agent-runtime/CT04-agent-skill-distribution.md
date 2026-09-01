# CT04 Deterministic Agent Skill Distribution

| Field | Value |
| --- | --- |
| Status | `implementation_validated` |
| Owner | `scripts/generate_skill_library.py` |
| Canonical input | `skills/library/*.json` |
| Architecture | `docs/architecture.md` |
| Architecture digest | `4854651589223586a9407c907a382a4b5e68a1573da0c499262b95cab0384cab` |
| Directive version | `1.0.0` |
| Directive approval | `approved` |
| External approval | Owner approved in the 2026-09-01 Agent Skill productization directive |
| Publication target | GitHub Release `skill-library-v1` |
| Publication state | `pending_main_merge` |

## Requirement

Every canonical external-method Skill classified as `future_skill` must have a
deterministic, Host-Agent-installable projection in addition to its ordinary
Runtime Hub package. The projection contains a standard `SKILL.md` and bounded
progressive-disclosure references. It is a static distribution artifact, not a
third execution owner and not evidence that Runtime dependencies are ready.

The CT03 builder remains the single build owner. It renders one Agent Skill
directory and one reproducible ZIP for every canonical manifest, plus one
versioned machine index that binds the Agent name and archive digest to the
same manifest and Runtime package digests already used by the Hub index.

## Safety boundary

- Ordinary Runtime packages and Agent Skill exports remain distinct artifacts.
- Agent exports contain no scripts, executable files, arbitrary URL, HTTP,
  shell, SQL, environment-variable access, or bundled third-party source text.
- Export does not change `readiness`, `validation`, lifecycle, dependencies,
  routing, effects, authorization, claims, or execution ownership.
- A blocked Skill remains installable guidance but must remain blocked by the
  authoritative Runtime readiness path.
- The builder performs no network call, publication, activation, or Host Agent
  filesystem mutation.
- Source Registry entries classified `out_of_scope_alternative` do not enter
  the distribution unless an Owner decision first adds a vendor-neutral,
  independently authored canonical manifest.

## Acceptance

1. The current 40 canonical manifests produce exactly 40 unique Agent Skill
   directories and 40 reproducible Agent Skill ZIPs.
2. Every export contains only `SKILL.md`, `references/GUIDE.md`,
   `references/SCHEMA.json`, and `references/CLAIMS.md`.
3. A versioned Agent Skill index deterministically binds identity, display
   metadata, runtime compatibility, declared readiness/validation, manifest
   digest, Runtime package digest, and archive digest/size/media type.
4. Every ZIP has one stable Agent Skill root, normalized paths, fixed
   timestamps, regular non-executable files, no links, no duplicates, and
   content byte-equal to the unpacked projection.
5. Two clean builds are byte-identical and `generate_skill_library.py --check`
   covers the complete projection.
6. Tests inspect at least one declared executable and one declared blocked
   export and prove exportability does not promote Runtime readiness.
7. Existing Hub index, Runtime package, lock, CAS, and `gravity skills`
   contracts remain compatible.
8. The `skill-library-v1` Release publishes the Agent index and all Agent Skill
   archives; a downloaded archive validates outside the source checkout.

## Non-goals

This Requirement does not unlock Semantic, Context, Operator, Model, Trusted
Pack, completeness, or Data Quality dependencies. It does not make
`gravity models ... --source` an installation path, add automatic Text-to-SQL,
or copy vendor-specific skills that remain outside the approved Runtime scope.
