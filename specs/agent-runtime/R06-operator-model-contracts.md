# R06 Analysis Operator And Model Contracts

| Field | Value |
| --- | --- |
| Parent directive | `gravity-agent-runtime/v9.1` via `directive.json` |
| Status | `fixed_dev`; integrated and validated on `dev` 2026-08-22 |
| Track | Deterministic analysis methods |
| Dependencies | R01 |
| Parallel group | `foundation-a` |
| Delivery ledger | This Requirement document; no internal GitHub Issue |
| Baseline | `dev@4c2d96d5b626449463e9609419e1f10aa64f3a53` |
| Branch / worktree | `codex/r06-operator-model-contracts` / `D:\git-pjt\gravity-sdk-wt\r06-operator-model-contracts` |
| Integrator | Root Codex agent; offline root CLI wiring remains serial |
| Production requests | `0`; live evidence not authorized |
| Implementation / merge | `508a13c` / `bc07d531` |
| Main integration | Frozen until whole program completion |

## Outcome

Reusable analysis methods execute as explicitly installed, deterministic Operators with versioned input/output, assumptions, claims and golden evidence. Predictive artifacts have separate model lineage and validation contracts.

## Plan Owner Verdict And Ready Binding

The user authorized continuous implementation without repeated Requirement
approval. R01-R03 and R05 are `fixed_dev`; the plan owner reviewed
`tmp/r06-operator-model-contracts-proposal.md` and its conflict ledger, bound
the current baseline/worktree/safety gates below, advanced R06 through
`reviewed` and `ready`, and accepted the validated implementation as
`fixed_dev`. This does not authorize production
probing, writes, releases or `main` promotion.

- Runtime initially ships only the characterized R01
  `operator://gravity/returned-dimension-change@1`; its direct provisional
  module migrates to one closed `OperatorRegistry` runner table with exact
  packaged input/output schemas and golden cases.
- Existing derived metrics stay a separate caller-defined arithmetic product;
  no method is inferred or bulk-wrapped into the Registry.
- `ModelRegistry` validates identity, Operator/code binding, artifact digest,
  fitting lineage/window, evaluation/calibration, safe horizon, approval and
  expiry but performs no prediction. R06 ships no Model Artifact, so the LTV
  Journey keeps `OPERATOR_UNAVAILABLE` and `MODEL_UNVALIDATED`.
- R04 receives a code-free trusted-pack descriptor for exact distribution,
  version, wheel digest and allowed groups. R06 does not implement Hub, CAS,
  lock, installer, entry-point discovery or Runtime environment scanning.
- R01 Analysis Result gains exact method/version/assumption/limitation metadata;
  `gravity.receipt.v1` gains only an optional value-free `operator_model` facet.
  Existing callers retain their current receipt shape when the facet is absent.
- Exact acceptance includes numerical/resource/contract failures, deterministic
  digests, Model lifecycle gates, package separation/no-scan tests, public
  snapshot/docs, real wheel, R01 consumer parity, full gates and usability.

## Fixed Dev Evidence

- `OperatorRegistry` packages exactly
  `operator://gravity/returned-dimension-change@1`, binds its formal Definition,
  input/output schemas and full golden result to artifact digest
  `ced105700b412be087322c7634402db356089ce5c904e625d758a9c8c41e4f59`,
  and selects its sole runner from a closed code table. The provisional direct
  R01 module owner was removed; arithmetic, rounding, ordering, fact paths and
  statement remain characterized through the Registry.
- Unit/additivity, sample, canonical JSON, row/input/output byte, dimension-key,
  decimal coefficient/exponent span, selected-slice cross-check and output
  schema gates fail closed. `gravity operators list|describe|validate` and the
  root SDK export are offline; there is no entry-point or environment scan.
- `ModelRegistry` ships with count `0` and never predicts. Explicit artifacts
  require lineage, fitting window, calibration, approval, expiry and safe
  horizon, plus an externally verified startup trusted digest before production
  claims. Self-declared local approval returns `MODEL_SOURCE_UNTRUSTED` and only
  scenario claims. The LTV Journey remains zero-network blocked with exact
  `OPERATOR_UNAVAILABLE` and `MODEL_UNVALIDATED` reasons.
- The code-free `gravity.trusted-pack-descriptor.v1` freezes exact
  distribution/version/wheel digest/runtime range/allowed groups for R04; it
  contains no URL, path, command or entry point. `gravity.receipt.v1` accepts an
  optional value-free Operator/Model facet and preserves every old caller shape
  when absent. R01 Analysis Result records method/version/schema/assumptions
  digest/limitations plus an empty models list.
- Full gates: `1498` unittest tests; `1498 passed, 3769 subtests` under pytest;
  compiler `237 operations / 11 manifests`; quality PASS; actionable errors
  `1310 = A1146 / B164 / C0`; active docs exactly `5500` lines. Canonical R01
  consumer remains `5 passed` and retains exit 4
  `blocked/COMPLETENESS_INSUFFICIENT` with zero network.
- Usability remains `296/336` selection, `248/248` fillability, `53/53` offline
  terminal and `5/5` recovery; security PASS; production HTTP requests `0`.
  Isolated wheel install passed without checkout docs. Wheel SHA-256:
  `09b22c219f63e9db03e640ffb6e588c5c392ae7b4b93b0f36336e2bb5b3da65c`.

## Current Baseline

The repository contains local derived metric operations and product-specific calculations but no formal Operator registry or Model Artifact lifecycle. Host agents may currently perform additional arithmetic outside a versioned method contract.

## Scope

- Define Operator identity/version/owner, schemas, assumptions, safe domain and failure reasons.
- Implement the R01 reference Operator and extract a narrow registry.
- Define the trusted-pack descriptor and exact distribution identity consumed later by R04.
- Define Model Artifact identity, parameters/artifact digest, fitting lineage, evaluation, expiry and safe horizon when first required.
- Record method/model references in Analysis Result and Receipt.
- Establish deterministic/golden test protocol.

## Non-goals

- Operators do not fetch data, choose products or access credentials.
- No remote Skill-supplied code, Runtime-time installation or implicit Python environment/plugin discovery.
- No MLflow service requirement and no LLM-selected prediction model.

## Machine Contract

Stage A initially runs Built-in Operators from the Runtime wheel. A team-shared Operator may later come from an R04 Team Trusted Pack: exact distribution/version/wheel digest, external installation and explicit allowed group. Registry lookup is by exact URI/version and never scans unlisted distributions. Insufficient sample, unit mismatch, invalid assumptions and unsupported domain return stable failures. Model validation is distinct from current data quality.

## Migration And Compatibility

Existing local derived operations remain valid until characterized and mapped. No result may silently change mathematical method; breaking method changes create a new major version and migrate consumers explicitly.

## Safety And Operations

Operators consume bounded governed results and Context summaries, never raw credentials or unrestricted user rows. Resource budgets cover rows, bytes, memory/time and numerical stability.

## Acceptance

- Reference Operator has schemas, assumptions, golden cases and negative boundaries.
- Repeated runs on identical normalized input are deterministic.
- Unapproved/expired models cannot produce production claims.
- Method/version/limitations appear in structured output.
- Remote Skill packages cannot introduce executable code.
- The trusted-pack contract is distributable by R04 without changing Operator identity or allowing Skill-triggered installation.

## Verification

Golden fixtures, property/numerical edge tests, resource-limit tests, serialization/digest checks, model calibration/expiry cases when applicable, package security tests and full repository gates.

## Rollback And Exit

Keep prior Operator versions addressable while active consumers migrate. Built-in rollback pins the prior Runtime wheel; trusted-pack rollback pins the prior exact external distribution/digest. Revocation prevents new execution but preserves historical Receipt resolution.

## Canonical Owners

Operator/Model schemas and registry, method reference documentation, affected Skill/Journey contracts and result safety guide.
