# R01 Reference Vertical Journey Slice

| Field | Value |
| --- | --- |
| Parent directive | `gravity-agent-runtime/v9.1` via `directive.json` |
| Status | `in_progress`; validation complete, pending `dev` integration |
| Track | Reference implementation |
| Dependencies | R00 |
| Parallel group | `reference` |
| Delivery ledger | This Requirement document; no internal GitHub Issue |
| Baseline | `dev@05f01c8da13c8414412611eb3c34612862530803` |
| Branch / worktree | `codex/r01-reference-vertical-slice` / `D:\git-pjt\gravity-sdk-wt\r01-reference-vertical-slice` |
| Integrator | Root Codex agent; shared-spine wiring remains serial |
| Main integration | Frozen until whole program completion |

## Outcome

One real project analysis Journey runs end to end through a Journey Contract, same-layer Capability Trust and Data Quality, one project Semantic, one deterministic Operator, one Built-in Skill, one bounded Repo Context Pack, the existing execution owner, a structured Analysis Result and Receipt/Evidence.

## Owner Verdict And Ready Binding

The user approved `tmp/r01-reference-vertical-slice-proposal.md` on 2026-08-21
and designated this Requirement as the internal delivery ledger. The same
message authorizes Codex to continue through later indexed requirements without
requesting another per-Requirement approval once their dependencies and machine
gates are satisfied. This does not authorize production probing, writes,
credential changes, release actions, or early `main` promotion.

- **Journey ID**: `analysis.merge2.ap-cost-anomaly-localization`.
- **Calling project / owner**: `work-dashboard` project `merge2` / `growth-data`.
- **Question**: did the sum of returned `click_company` `ap_cost` rows change
  between equal, non-overlapping windows, and did one caller-selected slice move
  in the same observed direction?
- **Success**: Journey readiness is machine-decidable; exact Trust/DQ,
  project Semantic, deterministic Operator, Built-in Skill, bounded Repo Context
  and Receipt references compose around the existing executor; missing or
  degraded evidence produces no conclusion.
- **Existing execution path**:
  `metric-anomaly-localization@1 -> Plan v1 -> semantic_compose -> report.multidim.query`.
- **Physical input scope**: configured `merge2-legacy` App binding, two equal
  explicit ISO windows, one exact `click_company`, physical `ap_cost`.
- **Business input scope**: project acquisition-spend Semantic and canonical
  acquisition/attribution Context citations.
- **Required completeness**: `complete` for every required query step.
- **Allowed claims**: returned-row window change, returned-key change and the
  selected-slice observation already bounded by `metric-anomaly-localization@1`.
- **Forbidden claims**: complete App total, unreturned values, causality,
  incrementality, ROI, natural-volume attribution or an unproved semantic
  equivalence.
- **Production request maximum / live evidence**: `0` / not authorized.
- **Canonical consumer target**: current `work-dashboard` Gravity contract,
  references and focused consumer tests, modified only in a clean worktree.
- **Acceptance commands**: focused R01/playbook/semantic/Plan tests, real-wheel
  no-checkout tests, focused consumer tests, both repositories' complete gates,
  the development usability evaluation and `git diff --check`.

## Current Baseline

The repository already has closed analysis journeys, host catalog/recognizer routing, Product/Composite/Plan execution, generated task guides, semantic caller bindings, completeness and Receipt behavior. It does not have the target Journey/Skill/Trust/Semantic/Operator/Context composition contract.

## Scope

- Implement only the minimum contracts needed by the selected Journey.
- Use one Built-in reference Skill; do not require Team Skill Hub Stage A.
- Preserve exact selector, host catalog and recognizer authority.
- Return honest `verified`, `unknown`, `blocked` or `invalid` outcomes.
- Capture characterization sufficient for R02-R08 extraction.

## Non-goals

- No generic registry for cases not exercised by the slice.
- No OCI, TUF, MCP, PAP, adaptive variant selection, SQL Explorer or action execution.
- No attempt to make all ThinkingAI Skills executable.

## Machine Contract

The slice must define versioned Journey, Skill, Semantic, Operator, Context Pack and Analysis Result schemas or narrow provisional equivalents. Each identity has one authority and a value-free digest/reference in Receipt metadata. R02-R08 may revise provisional R01 contracts only with current-behavior characterization, consumer migration and no-capability-loss gates.

## Migration And Compatibility

The current Product/Composite/Plan owner remains the only executor. Public CLI/SDK/Plan and canonical consumer behavior must be characterized before changes. Any new result layer wraps governed results without changing existing envelope semantics silently.

## Safety And Operations

Invalid input and blocked readiness perform zero target network calls. Any authorized production evidence follows maintainer probing rules and records exact request count, scope and value-free evidence.

## Acceptance

- One named real Journey is machine-decidable end to end.
- No second router, executor, binder, pagination or permission system exists.
- Missing same-layer trust, semantic, operator or context produces a stable gap.
- Complete/partial/unknown and allowed claims remain honest.
- The slice produces an extraction ledger for R02-R08.

## Verification

Focused happy/empty/partial/gap/invalid/privacy tests, current surface characterization, real wheel execution without checkout-only resources, relevant consumer tests, complete repository gates and the development usability evaluation.

## Delivery Verdict

Accepted for `dev` integration on 2026-08-22. The Runtime slice and canonical
consumer migration satisfy the R01 behavior and safety boundary. The live
Journey is intentionally **blocked**, not successful: the authoritative
`report.multidim.query` contract declares `completeness=unknown`, below R01's
required `complete`. Both `can-run` and `run` therefore return exit 4 with
`COMPLETENESS_INSUFFICIENT`, no findings, claims or Receipt references, and
`network_called=false`. Returned rows and `page_info` hints do not promote that
contract truth.

No read capability is removed. The public change is additive (`GravitySDK.journeys`,
`ReferenceJourneyService`, and `gravity journey`); the existing playbook keeps
its envelope and execution owner, with the extracted deterministic Operator
covered by characterization tests. No Agent card, router, executor, binder,
Plan adapter, pagination owner or worker pool is added.

### Acceptance Evidence

- SDK focused R01/playbook/public-surface suite: `35 passed, 24 subtests passed`.
- SDK complete `unittest`: `1418 tests`; complete CI `pytest`: `1418 passed,
  3655 subtests passed`.
- Compiler: `237 operations, 11 manifests`; quality: PASS with `237` provenance
  records and operation-literal ratchets unchanged; CLI help and
  `git diff --check`: PASS.
- Development usability: selection `296/336`, parameter fillability `248/248`,
  offline terminal `53/53`, error recovery `5/5`, security hard gate PASS,
  production HTTP requests `0`.
- Isolated real wheel: `gravity_sdk-0.3.0-py3-none-any.whl`, SHA-256
  `8860e4ff34ddec2c8a6c9456b4341b4f6d75c707bf9418d16e40078e2785807c`;
  imported from isolated `site-packages`, packaged resources loaded,
  `describe=0`, `can-run=4`, `run=4`, and no network call.
- Canonical consumer focused adoption/R01/LTV: `18 passed, 114 subtests passed`;
  privacy: `10 passed`; complete business suite: `303 tests`.

The consumer's complete governance command still reports unrelated baseline
failures outside the R01 commit paths: two missing historical migration assets,
one GM SQL provenance drift, one expired topic-directory exception, and one
frozen historical HTML link to a removed `tmp` JSON. The latter accounts for
the two failures in the `270`-test `tools/common` suite. R01 adoption and tracked
privacy pass inside that same full gate; these baseline defects neither weaken
R01's fail-closed result nor authorize changes to frozen consumer history.

## R02-R08 Extraction Ledger

| Target | R01 provisional owner | Behavior that must survive extraction | Deliberately not generalized in R01 |
| --- | --- | --- | --- |
| R02 | `reference_journey.py`, `reference_journey_trust.py`, Journey/Trust/DQ/Analysis Result artifacts | `describe/can-run/run`; exact dependency snapshot; `verified/unknown/blocked/invalid`; same-layer fingerprint, TTL, completeness and DQ; no conclusion when readiness degrades | Multi-Journey registration, reusable Trust/DQ registries and shared result composition |
| R03 | `contracts/skills/...`, `skills/.../GUIDE.md`, generated Agent guide | Immutable Built-in package identity/digest; static no-code instructions; no installer, imports, dependency resolver or execution authority | General package loader, render variants, locale negotiation and lifecycle registry |
| R04 | No Hub runtime dependency | Built-in execution must remain usable with no Team Hub; later Hub artifacts cannot silently override Built-in identity or authority | Hub discovery, publication, trust distribution and cache behavior |
| R05 | Consumer `r01-ap-cost-anomaly.json`, `reference_project_contract.py` | Project-owned Semantic URI/version, physical bindings, App/effective-time scope, unit/additivity/grain and allowed/forbidden claims remain machine checked | Reusable Semantic registry, cross-project resolution, formula/dependency/conflict catalog |
| R06 | `reference_journey_operator.py`, Operator artifact | Pure deterministic returned-row calculation; exact fact paths; selected-slice cross-check; inconsistent, empty or non-finite facts fail closed | Operator registry, Model contracts, generic parameter/result schemas and selection policy |
| R07 | `reference_project_contract.py`, Context Provider artifact | Bounded committed Git snapshot; normalized in-root paths; entity/time alignment; hashes/revision/observation; `role=data`; Context bodies excluded from public Analysis Result/Receipt references | Provider registry, reusable alignment engine, conflict/supersession policy and cache lifecycle |
| R08 | No external Provider or RPC path | Zero external RPC remains the baseline; missing external capability cannot affect the Built-in path; later external results must enter through explicit trust and fail-closed guards | RPC protocol, authentication, request budget, response validation, quarantine and retry policy |

R02-R08 may replace these provisional owners only with characterized migration,
canonical consumer updates and proof that no current read or fail-closed
capability is lost.

## Rollback And Exit

The slice may stop at a proved blocker. Rollback restores current public behavior and removes provisional unused contracts; it must not delete existing read capability.

## Canonical Owners

Journey machine artifact, `docs/analysis-journeys.md`, affected reference pages, generated Agent guide and the selected calling project's canonical contract.
