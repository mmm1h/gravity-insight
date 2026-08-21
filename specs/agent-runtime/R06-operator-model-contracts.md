# R06 Analysis Operator And Model Contracts

| Field | Value |
| --- | --- |
| Parent directive | `gravity-agent-runtime/v9.1` via `directive.json` |
| Status | `in_progress`; plan-owner ready verdict 2026-08-22 |
| Track | Deterministic analysis methods |
| Dependencies | R01 |
| Parallel group | `foundation-a` |
| Delivery ledger | This Requirement document; no internal GitHub Issue |
| Baseline | `dev@4c2d96d5b626449463e9609419e1f10aa64f3a53` |
| Branch / worktree | `codex/r06-operator-model-contracts` / `D:\git-pjt\gravity-sdk-wt\r06-operator-model-contracts` |
| Integrator | Root Codex agent; offline root CLI wiring remains serial |
| Production requests | `0`; live evidence not authorized |
| Main integration | Frozen until whole program completion |

## Outcome

Reusable analysis methods execute as explicitly installed, deterministic Operators with versioned input/output, assumptions, claims and golden evidence. Predictive artifacts have separate model lineage and validation contracts.

## Plan Owner Verdict And Ready Binding

The user authorized continuous implementation without repeated Requirement
approval. R01-R03 and R05 are `fixed_dev`; the plan owner reviewed
`tmp/r06-operator-model-contracts-proposal.md` and its conflict ledger, bound
the current baseline/worktree/safety gates below, and advanced R06 through
`reviewed` and `ready` to `in_progress`. This does not authorize production
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
