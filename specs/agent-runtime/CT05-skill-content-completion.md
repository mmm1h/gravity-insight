# CT05 Skill Content Completion

| Field | Value |
| --- | --- |
| Status | `in_progress` |
| Delivery type | `staged_epic` |
| Owner | `skills/library/*.json` |
| Canonical input | `skills/library/*.json` |
| Architecture | `docs/architecture.md` |
| Architecture digest | `4854651589223586a9407c907a382a4b5e68a1573da0c499262b95cab0384cab` |
| Directive version | `1.0.0` |
| Directive approval | `approved` |
| External approval | Owner required 100% complete and usable Skill content on 2026-09-02 |
| Applicable target | `43` independently authored canonical Skills |
| Current milestone | `M4` Runtime dependencies closed; project templates ready (`43/43` executable and validated) |

## Requirement

Every applicable external method has one vendor-neutral canonical Skill that
satisfies all 17 Method Complete criteria. Agent packages expose the method in
the GUIDE and provide structured success, empty/partial, and blocked/gap run
examples. Content completeness remains orthogonal to Runtime readiness.

Runtime-owned dependencies must be implemented and validated before program
exit. Calling-project Semantic and Context values remain project-owned; each
such dependency must instead have a validated fill-in template and an exact
fail-closed remedy. No milestone may promote readiness by documentation alone.

## Milestones

| Milestone | Scope | Exit |
| --- | --- | --- |
| `M1` | Example contract and rendering; three newly approved topics; core diagnostics/data engineering; two method-less executable analysis Skills | Every in-scope Skill is 17/17 and has three scenario-complete run examples |
| `M2` | Community, operations, campaign, device and game analysis | Every in-scope Skill is 17/17 with package/eval coverage |
| `M3` | Monetization, LTV/LT, retention, churn and user analysis | Canonical library reaches 43/43 Method Complete |
| `M4` | Runtime-owned dependency closure and project binding templates | Zero Runtime-owned dependency gaps; every project gap has a validated template |
| `M5` | Final deterministic publication and external readback | All 43 Agent archives validate outside the checkout |

## Acceptance

1. Applicable inventory is exactly 43; the remaining 12 source topics stay
   fail-closed as vendor/platform alternatives.
2. Method Complete is exactly 43/43 and every Skill is 17/17.
3. Each Skill has at least three structured run examples covering `success`,
   `empty_or_partial`, and `blocked_or_gap`.
4. Run examples bind an input template to expected status, completeness,
   sections, reason codes, network behavior, and claim boundaries.
5. `SKILL.md` stays concise; GUIDE, EXAMPLES, SCHEMA, and CLAIMS provide bounded
   progressive disclosure and pass the official Agent Skill validator.
6. Runtime execution, project bindings, effects, authorization, Trust,
   completeness and Data Quality remain owned by their existing contracts.
7. Final Full Gate, integrated validation, canary, deterministic build,
   publication, digest verification and external download/readback all pass.

## Safety Boundary

- No third-party source body, example, customer data, claim, or effect figure is
  copied. Source URLs and hashes remain isolated in the Source Registry.
- Skill packages contain no executable code, shell, SQL, arbitrary network
  target, credential, or write authorization.
- Project activity names, event bindings, SKU values, formula parameters,
  effective windows and private Context are never invented by Runtime content.
- A complete method may remain blocked; the exact dependency or project gap is
  itself a usable, deterministic outcome.

## Non-goals

This Requirement does not add Text-to-SQL, duplicate a vendor platform, create
a second execution owner, copy third-party content, or make project-bound
analysis executable without project-owned definitions and Context.
