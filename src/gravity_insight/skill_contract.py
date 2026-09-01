"""Schema-validated Built-in Skill manifests and dependency bindings."""

from __future__ import annotations

import copy
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

from .actionable_error_values import actual_value
from .agent_runtime_contracts import (
    AgentRuntimeContractError,
    canonical_digest,
    load_json_object,
    validate_schema,
)
from .capability_contract import capability_contract
from .errors import InputValidationError
from .journey_contract import journey_artifact


SCHEMA_VERSION = "gravity.skill.v1"
_SCHEMA_NAME = "skill-v1.schema.json"
_MANIFEST_ROOT = Path(__file__).resolve().parent / "contracts" / "skills"
_COMPACT_IDENTITY = re.compile(
    r"^(?P<namespace>[a-z][a-z0-9.-]*)/(?P<skill_id>[a-z0-9-]+)@(?P<version>[0-9A-Za-z.-]+)$"
)
_AVAILABLE_METHOD_DEPENDENCY_STATUSES = frozenset({"available", "optional"})
_EXECUTION_BLOCKING_METHOD_DEPENDENCY_STATUSES = frozenset({"unavailable"})
_RUN_EXAMPLE_STATUSES = {
    "success": frozenset({"success"}),
    "empty_or_partial": frozenset({"empty", "partial"}),
    "blocked_or_gap": frozenset({"blocked", "gap"}),
}


class SkillContractError(AgentRuntimeContractError):
    """A Built-in Skill manifest or its dependency binding is invalid."""


def skill_uri(contract: Mapping[str, Any]) -> str:
    return (
        f"skill://{contract['namespace']}/{contract['skill_id']}"
        f"@{contract['version']}"
    )


def skill_artifacts() -> tuple[dict[str, Any], ...]:
    return tuple(copy.deepcopy(item) for _, item in sorted(_artifacts().items()))


def skill_artifact(identifier: str) -> dict[str, Any] | None:
    try:
        identity = normalize_skill_identity(identifier)
    except InputValidationError:
        return None
    value = _artifacts().get(identity)
    return copy.deepcopy(value) if value is not None else None


def normalize_skill_identity(identifier: Any) -> str:
    if not isinstance(identifier, str) or not identifier.strip():
        raise InputValidationError(
            f"actual value: {actual_value(identifier)}; Skill identity must be a "
            "non-empty versioned URI",
            field="skill",
            next_action="Run `gravity skills list` and use an exact skill_uri.",
        )
    selected = identifier.strip()
    compact = selected.removeprefix("skill://")
    if _COMPACT_IDENTITY.fullmatch(compact) is None:
        raise InputValidationError(
            f"actual value: {actual_value(identifier)}; Skill identity must use "
            "skill://<namespace>/<skill-id>@<version>",
            field="skill",
            next_action="Run `gravity skills list` and use an exact skill_uri.",
        )
    return "skill://" + compact


def load_skill_manifest(path: Path) -> dict[str, Any]:
    value = load_json_object(path, f"Skill manifest {path.name}")
    return compile_skill_manifest(value, label=f"Skill manifest {path.name}")


def compile_skill_manifest(
    value: Mapping[str, Any], *, label: str = "Skill manifest"
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise SkillContractError(f"{label} must be an object")
    contract = copy.deepcopy(dict(value))
    try:
        validate_schema(contract, _SCHEMA_NAME, label)
    except AgentRuntimeContractError as exc:
        raise SkillContractError(str(exc)) from exc
    if contract["request_budget"]["known_requests_min"] > contract["request_budget"]["known_requests_max"]:
        raise SkillContractError("Skill request budget range is invalid")
    if set(contract["context_dependencies"]["required"]).intersection(
        contract["context_dependencies"]["optional"]
    ):
        raise SkillContractError("Skill Context dependency cannot be required and optional")
    method_errors = validate_method_structure(contract)
    if method_errors:
        raise SkillContractError("; ".join(method_errors))
    return contract


def validate_method_structure(manifest: Mapping[str, Any]) -> list[str]:
    """Return Method cross-field errors not expressible in JSON Schema."""

    method = manifest.get("method")
    if method is None:
        return []
    errors: list[str] = []
    _unique_method_ids(method["procedure"], "step_id", "procedure", errors)
    _unique_method_ids(method["formulas"], "formula_id", "formulas", errors)
    _unique_method_ids(
        method["dimension_scan"]["dimensions"],
        "dimension_id",
        "dimensions",
        errors,
    )
    _unique_method_ids(
        method["diagnostic_tree"]["branches"],
        "branch_id",
        "diagnostic branches",
        errors,
    )
    leaves = [
        leaf
        for branch in method["diagnostic_tree"]["branches"]
        for leaf in branch["leaves"]
    ]
    _unique_method_ids(leaves, "leaf_id", "diagnostic leaves", errors)
    _unique_method_ids(
        method["result"]["sections"], "section_id", "result sections", errors
    )
    _unique_method_ids(
        method["examples"]["eval_cases"], "eval_id", "Eval cases", errors
    )
    _unique_method_ids(
        method["examples"]["run_examples"],
        "example_id",
        "run examples",
        errors,
    )
    _validate_method_step_dependencies(method["procedure"], errors)
    _validate_method_formula_calibrations(method, errors)
    _validate_method_eval_references(manifest, method, errors)
    _validate_method_run_examples(manifest, method, errors)
    _validate_method_dependency_status(manifest, method, errors)
    return errors


def _unique_method_ids(
    values: list[dict[str, Any]], key: str, label: str, errors: list[str]
) -> None:
    identities = [item[key] for item in values]
    if len(identities) != len(set(identities)):
        errors.append(f"Method {label} must use unique {key} values")


def _validate_method_step_dependencies(
    steps: list[dict[str, Any]], errors: list[str]
) -> None:
    prior: set[str] = set()
    for step in steps:
        if set(step["depends_on"]) - prior:
            errors.append(
                f"Method step {step['step_id']} depends on unknown or later steps"
            )
        prior.add(step["step_id"])


def _validate_method_formula_calibrations(
    method: Mapping[str, Any], errors: list[str]
) -> None:
    declared = {
        item["calibration_id"]
        for item in method["assumptions"]["requires_project_calibration"]
    }
    for formula in method["formulas"]:
        if not set(formula["requires_project_calibration"]).issubset(declared):
            errors.append(
                f"Method formula {formula['formula_id']} references undeclared "
                "project calibration"
            )


def _validate_method_eval_references(
    manifest: Mapping[str, Any], method: Mapping[str, Any], errors: list[str]
) -> None:
    sections = {item["section_id"] for item in method["result"]["sections"]}
    forbidden = set(manifest["claim_policy"]["forbidden"])
    for case in method["examples"]["eval_cases"]:
        if not set(case["expected_sections"]).issubset(sections):
            errors.append(
                f"Method Eval {case['eval_id']} references an unknown result section"
            )
        if not set(case["forbidden_claims"]).issubset(forbidden):
            errors.append(
                f"Method Eval {case['eval_id']} references an undeclared forbidden claim"
            )


def _validate_method_run_examples(
    manifest: Mapping[str, Any], method: Mapping[str, Any], errors: list[str]
) -> None:
    sections = {item["section_id"] for item in method["result"]["sections"]}
    allowed = set(manifest["claim_policy"]["allowed"])
    forbidden = set(manifest["claim_policy"]["forbidden"])
    selectors = {
        item["selector"] for item in manifest["capability_dependencies"]
    }
    examples = method["examples"]["run_examples"]
    scenarios = {item["scenario"] for item in examples}
    if scenarios != set(_RUN_EXAMPLE_STATUSES):
        errors.append(
            "Method run examples must cover success, empty_or_partial, and "
            "blocked_or_gap scenarios"
        )
    for example in examples:
        _validate_method_run_example(
            example,
            selectors=selectors,
            sections=sections,
            allowed=allowed,
            forbidden=forbidden,
            errors=errors,
        )


def _validate_method_run_example(
    example: Mapping[str, Any],
    *,
    selectors: set[str],
    sections: set[str],
    allowed: set[str],
    forbidden: set[str],
    errors: list[str],
) -> None:
    identity = example["example_id"]
    expected = example["expected"]
    _validate_run_example_selector(identity, example["selector"], selectors, errors)
    _validate_run_example_references(
        identity,
        expected,
        sections=sections,
        allowed=allowed,
        forbidden=forbidden,
        errors=errors,
    )
    _validate_run_example_outcome(identity, example, errors)


def _validate_run_example_selector(
    identity: str,
    selector: Any,
    selectors: set[str],
    errors: list[str],
) -> None:
    if selector is None and selectors:
        errors.append(f"Method run example {identity} omits a declared selector")
    elif selector is not None and selector not in selectors:
        errors.append(
            f"Method run example {identity} references an undeclared selector"
        )


def _validate_run_example_references(
    identity: str,
    expected: Mapping[str, Any],
    *,
    sections: set[str],
    allowed: set[str],
    forbidden: set[str],
    errors: list[str],
) -> None:
    checks = (
        ("sections", sections, "an unknown result section"),
        ("allowed_claims", allowed, "an undeclared allowed claim"),
        ("forbidden_claims", forbidden, "an undeclared forbidden claim"),
    )
    for key, declared, message in checks:
        if not set(expected[key]).issubset(declared):
            errors.append(f"Method run example {identity} references {message}")


def _validate_run_example_outcome(
    identity: str,
    example: Mapping[str, Any],
    errors: list[str],
) -> None:
    expected = example["expected"]
    scenario = example["scenario"]
    if expected["status"] not in _RUN_EXAMPLE_STATUSES[scenario]:
        errors.append(
            f"Method run example {identity} status does not match its scenario"
        )
    if expected["status"] != "success" and not expected["reason_codes"]:
        errors.append(
            f"Method run example {identity} non-success outcome needs a reason code"
        )
    if scenario == "blocked_or_gap" and expected["network_called"]:
        errors.append(
            f"Method run example {identity} blocked/gap preflight must use zero network"
        )


def _declared_method_dependencies(
    manifest: Mapping[str, Any],
) -> set[tuple[str, str]]:
    values = {
        ("capability", item["selector"])
        for item in manifest["capability_dependencies"]
    }
    values.update(("semantic", item) for item in manifest["semantic_dependencies"])
    values.update(("operator", item) for item in manifest["operator_dependencies"])
    values.update(("model", item) for item in manifest["model_dependencies"])
    values.update(
        ("context", item)
        for item in manifest["context_dependencies"]["required"]
    )
    values.update(
        ("context", item)
        for item in manifest["context_dependencies"]["optional"]
    )
    return values


def _validate_method_dependency_status(
    manifest: Mapping[str, Any], method: Mapping[str, Any], errors: list[str]
) -> None:
    rows = method["dependency_status"]
    identities = [(item["kind"], item["identity"]) for item in rows]
    if len(identities) != len(set(identities)):
        errors.append("Method dependency_status identities must be unique")
    if set(identities) != _declared_method_dependencies(manifest):
        errors.append(
            "Method dependency_status must exactly cover declared dependencies"
        )
    optional_context = set(manifest["context_dependencies"]["optional"])
    for row in rows:
        errors.extend(
            _method_dependency_status_errors(manifest, row, optional_context)
        )
    if (
        any(
            row["status"] in _EXECUTION_BLOCKING_METHOD_DEPENDENCY_STATUSES
            for row in rows
        )
        and manifest["readiness"] != "blocked"
    ):
        errors.append(
            "Skill with unavailable Runtime Method dependencies must declare blocked readiness"
        )


def _method_dependency_status_errors(
    manifest: Mapping[str, Any],
    row: Mapping[str, Any],
    optional_context: set[str],
) -> list[str]:
    kind, identity, status = row["kind"], row["identity"], row["status"]
    errors: list[str] = []
    if status == "requires_project_binding" and not (
        kind == "semantic" and "://project/" in identity
    ):
        errors.append(
            "requires_project_binding is valid only for project Semantic dependencies"
        )
    if status == "requires_project_context" and not (
        kind == "context" and "://project/" in identity
    ):
        errors.append(
            "requires_project_context is valid only for project Context dependencies"
        )
    if status == "optional" and not (
        kind == "context" and identity in optional_context
    ):
        errors.append(
            "optional status is valid only for optional Context dependencies"
        )
    if status == "available" and not _method_dependency_available(
        manifest, kind, identity
    ):
        errors.append(
            f"Method dependency {kind}:{identity} is marked available but is not "
            "registered"
        )
    return errors


def _method_dependency_available(
    manifest: Mapping[str, Any], kind: str, identity: str
) -> bool:
    if kind == "capability":
        requirement = next(
            (
                item
                for item in manifest["capability_dependencies"]
                if item["selector"] == identity
            ),
            None,
        )
        return bool(
            requirement
            and capability_contract(requirement["identity_kind"], identity) is not None
        )
    roots = {
        "operator": Path(__file__).resolve().parent / "contracts" / "operators",
        "semantic": Path(__file__).resolve().parent / "contracts" / "semantics",
    }
    root = roots.get(kind)
    if root is None:
        return False
    return identity in {
        str(load_json_object(path, f"{kind} dependency {path.name}").get("uri"))
        for path in sorted(root.glob("*.json"))
    }


@lru_cache(maxsize=1)
def _artifacts() -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for path in sorted(_MANIFEST_ROOT.glob("*.json")):
        contract = load_skill_manifest(path)
        identity = skill_uri(contract)
        if identity in result:
            raise SkillContractError("Skill identity is duplicated")
        artifact = {
            "contract": contract,
            "digest": canonical_digest(contract),
            "skill_uri": identity,
        }
        _validate_dependencies(artifact)
        result[identity] = artifact
    if not result:
        raise SkillContractError("Built-in Skill registry is empty")
    return result


def _validate_dependencies(artifact: Mapping[str, Any]) -> None:
    contract = artifact["contract"]
    identity = artifact["skill_uri"]
    for journey_id in contract["covers_journeys"]:
        journey = journey_artifact(str(journey_id))
        if journey is None or journey["contract"]["required_skill"] != identity:
            raise SkillContractError("Skill Journey dependency is missing or drifted")
        if len(contract["covers_journeys"]) == 1:
            validate_skill_journey_parity(contract, journey["contract"])
    for requirement in contract["capability_dependencies"]:
        capability = capability_contract(
            str(requirement["identity_kind"]), str(requirement["selector"])
        )
        if capability is None:
            raise SkillContractError("Skill Capability dependency is missing")
        if capability["contract"]["contract_version"] != requirement["contract_version"]:
            raise SkillContractError("Skill Capability dependency version drifted")
    hints = set(contract["routing"]["product_hints"])
    selectors = {item["selector"] for item in contract["capability_dependencies"]}
    if not hints.issubset(selectors):
        raise SkillContractError("Skill routing hints are not declared dependencies")


def validate_skill_journey_parity(
    contract: Mapping[str, Any], journey: Mapping[str, Any]
) -> None:
    try:
        checks = (
            journey["journey_id"] in contract["covers_journeys"],
            contract["capability_dependencies"] == journey["required_capabilities"],
            contract["semantic_dependencies"] == journey["required_semantics"],
            contract["operator_dependencies"] == journey["required_operators"],
            contract["model_dependencies"] == journey["required_models"],
            contract["context_dependencies"]["required"]
            == journey["required_context"],
            contract["requirements"]["completeness"]
            == journey["required_capabilities"][0]["completeness"],
            contract["requirements"]["data_quality"]
            == journey["required_capabilities"][0]["data_quality"],
            contract["claim_policy"]["allowed"]
            == journey["claim_policy"]["allowed"],
            contract["claim_policy"]["forbidden"]
            == journey["claim_policy"]["forbidden"],
            contract["request_budget"]["known_requests_min"]
            == journey["request_budget"]["known_requests_min"],
            contract["request_budget"]["known_requests_max"]
            == journey["request_budget"]["known_requests_max"],
            contract["request_budget"]["unknown_discovery_max"]
            == journey["request_budget"]["unknown_discovery_max"],
            contract["request_budget"]["runtime_additional_requests"]
            == journey["request_budget"]["runtime_additional_requests"],
            contract["output_schema"] == "gravity.analysis-result.v1",
        )
    except (KeyError, IndexError, TypeError) as exc:
        raise SkillContractError(
            "Skill and Journey dependency contracts drifted"
        ) from exc
    if not all(checks):
        raise SkillContractError("Skill and Journey dependency contracts drifted")


__all__ = [
    "SCHEMA_VERSION",
    "SkillContractError",
    "compile_skill_manifest",
    "load_skill_manifest",
    "normalize_skill_identity",
    "skill_artifact",
    "skill_artifacts",
    "skill_uri",
    "validate_method_structure",
    "validate_skill_journey_parity",
]
