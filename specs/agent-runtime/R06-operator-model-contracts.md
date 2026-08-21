# R06 Analysis Operator And Model Contracts

| Field | Value |
| --- | --- |
| Parent directive | `gravity-agent-runtime/v9` via `directive.json` |
| Status | `specified` |
| Track | Deterministic analysis methods |
| Dependencies | R01 |
| Parallel group | `foundation-a` |
| Main integration | Frozen until whole program completion |

## Outcome

Reusable analysis methods execute as explicitly installed, deterministic Operators with versioned input/output, assumptions, claims and golden evidence. Predictive artifacts have separate model lineage and validation contracts.

## Current Baseline

The repository contains local derived metric operations and product-specific calculations but no formal Operator registry or Model Artifact lifecycle. Host agents may currently perform additional arithmetic outside a versioned method contract.

## Scope

- Define Operator identity/version/owner, schemas, assumptions, safe domain and failure reasons.
- Implement the R01 reference Operator and extract a narrow registry.
- Define Model Artifact identity, parameters/artifact digest, fitting lineage, evaluation, expiry and safe horizon when first required.
- Record method/model references in Analysis Result and Receipt.
- Establish deterministic/golden test protocol.

## Non-goals

- Operators do not fetch data, choose products or access credentials.
- No remote Skill-supplied code or implicit Python plugin discovery.
- No MLflow service requirement and no LLM-selected prediction model.

## Machine Contract

Operator code is part of the Runtime wheel or an explicitly installed trusted pack. Registry lookup is by exact URI/version. Insufficient sample, unit mismatch, invalid assumptions and unsupported domain return stable failures. Model validation is distinct from current data quality.

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

## Verification

Golden fixtures, property/numerical edge tests, resource-limit tests, serialization/digest checks, model calibration/expiry cases when applicable, package security tests and full repository gates.

## Rollback And Exit

Keep prior Operator versions addressable while active consumers migrate. Revocation prevents new execution but preserves historical Receipt resolution. Rollback pins the prior exact version.

## Canonical Owners

Operator/Model schemas and registry, method reference documentation, affected Skill/Journey contracts and result safety guide.
