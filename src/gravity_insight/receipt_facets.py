"""Value-free additive facets for ``gravity.receipt.v1``."""

from __future__ import annotations

import copy
import re
from collections.abc import Mapping, Sequence
from typing import Any

from .agent_runtime_contracts import canonical_digest, validate_schema
from .context_contract import public_context_reference
from .data_quality import validate_data_quality_result
from .execution_snapshot import compile_execution_snapshot
from .operator_model_receipt import validate_operator_model_receipt_facet
from .receipt import validate_receipt_facets


_SKILL_URI = re.compile(
    r"^skill://(?P<namespace>[a-z][a-z0-9-]*(?:\.[a-z][a-z0-9-]*)*)/"
    r"(?P<skill_id>[a-z0-9]+(?:-[a-z0-9]+)*)@"
    r"(?P<version>(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\."
    r"(?:0|[1-9][0-9]*)(?:-[0-9A-Za-z.-]+)?)$"
)


def compile_receipt_facets(
    *,
    run: Mapping[str, Any] | None = None,
    execution_snapshot: Mapping[str, Any] | None = None,
    context_packs: Sequence[Mapping[str, Any]] = (),
    operator_model: Mapping[str, Any] | None = None,
    pagination: Mapping[str, Any] | None = None,
    data_quality: Mapping[str, Any] | None = None,
    policy: Mapping[str, Any] | None = None,
    action: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Project validated Runtime evidence into closed, value-free facets."""

    facets: dict[str, Any] = {}
    snapshot = None
    if run is not None:
        facets["run"] = _run_facet(run)
    if execution_snapshot is not None:
        snapshot = compile_execution_snapshot(execution_snapshot)
        facets.update(_snapshot_facets(snapshot))
    packs = _context_facet(
        snapshot.get("context_packs", ()) if snapshot is not None else (),
        context_packs,
    )
    if packs is not None:
        facets["context"] = packs
    if operator_model is not None:
        compiled_operator_model = validate_operator_model_receipt_facet(
            operator_model
        )
        if snapshot is not None:
            _match_operator_model(snapshot, compiled_operator_model)
        facets["operator_model"] = compiled_operator_model
    if pagination is not None:
        facets["pagination"] = _pagination_facet(pagination)
    if data_quality is not None:
        facets["data_quality"] = _data_quality_facet(data_quality)
    compiled_policy = _policy_facet(policy) if policy is not None else None
    compiled_action = None
    if action is not None:
        compiled_action = _action_facet(action)
        action_policy = _policy_facet(
            _mapping(_required(action, "policy", "action"), "action policy")
        )
        if compiled_policy is not None and compiled_policy != action_policy:
            raise ValueError("Action and Receipt Policy facets disagree")
        compiled_policy = action_policy
    if compiled_policy is not None:
        facets["policy"] = compiled_policy
    if compiled_action is not None:
        facets["action"] = compiled_action
    return validate_receipt_facets(facets)


def _run_facet(value: Mapping[str, Any]) -> dict[str, Any]:
    selected = _mapping(value, "run")
    return {
        "schema_version": "gravity.receipt-run-facet.v1",
        "run_id": _required(selected, "run_id", "run"),
        "root_run_id": _required(selected, "root_run_id", "run"),
        "parent_run_id": selected.get("parent_run_id"),
        "event_type": _required(selected, "event_type", "run"),
    }


def _snapshot_facets(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    facets: dict[str, Any] = {
        "journey": {
            "schema_version": "gravity.receipt-journey-facet.v1",
            **_select(snapshot["journey"], ("journey_id", "version", "digest")),
        }
    }
    skill = snapshot.get("skill")
    if skill is not None:
        match = _SKILL_URI.fullmatch(str(skill.get("uri", "")))
        if match is None or match.group("version") != skill.get("version"):
            raise ValueError("execution snapshot Skill URI is not receipt-safe")
        facets["skill"] = {
            "schema_version": "gravity.receipt-skill-facet.v1",
            "namespace": match.group("namespace"),
            "skill_id": match.group("skill_id"),
            "version": match.group("version"),
            "digest": skill["package_digest"],
        }
    capabilities = [
        {
            "identity_kind": item["identity_kind"],
            "selector": item["selector"],
            "contract_version": item["contract_version"],
            "contract_digest": item["contract_digest"],
            "validation_digest": item["trust_digest"],
            "status": item["status"],
        }
        for item in snapshot["capabilities"]
    ]
    if capabilities:
        facets["capability"] = {
            "schema_version": "gravity.receipt-capability-facet.v1",
            "references": sorted(
                capabilities,
                key=lambda item: (item["identity_kind"], item["selector"]),
            ),
        }
    semantics = [
        {
            "uri": item["uri"],
            "version": item["version"],
            "definition_digest": item["definition_digest"],
            "binding_digest": item["binding_digest"],
            "registry_digest": item["registry_digest"],
            "status": item["status"],
        }
        for item in snapshot["semantics"]
    ]
    if semantics:
        facets["semantics"] = {
            "schema_version": "gravity.receipt-semantics-facet.v1",
            "references": sorted(semantics, key=lambda item: item["uri"]),
        }
    return facets


def _context_facet(
    snapshot_references: Sequence[Mapping[str, Any]],
    context_packs: Sequence[Mapping[str, Any]],
) -> dict[str, Any] | None:
    supplied = _sequence(context_packs, "context_packs")
    public_by_digest: dict[str, dict[str, Any]] = {}
    for pack in supplied:
        public = public_context_reference(_mapping(pack, "Context Pack"))
        digest = str(public["pack_digest"])
        if digest in public_by_digest:
            raise ValueError("Context receipt facet contains duplicate Pack digests")
        public_by_digest[digest] = public

    references = [_mapping(item, "Context snapshot reference") for item in snapshot_references]
    expected_digests = {
        str(item["pack_digest"])
        for item in references
        if item.get("pack_digest") is not None
    }
    if references and set(public_by_digest) - expected_digests:
        raise ValueError("Context Pack is not bound by the execution snapshot")

    packs: list[dict[str, Any]] = []
    if references:
        for reference in references:
            digest = reference.get("pack_digest")
            public = public_by_digest.get(str(digest)) if digest is not None else None
            if public is not None:
                _match_context_reference(reference, public)
            packs.append(_context_pack_reference(reference, public))
    else:
        packs.extend(
            _context_pack_reference(
                {
                    "requirement_uri": public["requirement"]["requirement_id"],
                    "provider_uri": public["provider"]["uri"],
                    "pack_digest": public["pack_digest"],
                    "status": public["status"],
                },
                public,
            )
            for public in public_by_digest.values()
        )
    if not packs:
        return None
    return {
        "schema_version": "gravity.receipt-context-facet.v1",
        "packs": sorted(
            packs,
            key=lambda item: (
                item["requirement_uri"],
                item["pack_digest"] or "",
            ),
        ),
    }


def _match_operator_model(
    snapshot: Mapping[str, Any], facet: Mapping[str, Any]
) -> None:
    operator_fields = ("uri", "version", "digest", "assumptions_digest")
    expected_operators = sorted(
        (_select(item, operator_fields) for item in snapshot["operators"]),
        key=lambda item: item["uri"],
    )
    if expected_operators != facet["operators"]:
        raise ValueError("Operator receipt facet contradicts the execution snapshot")
    model_fields = ("uri", "version", "digest")
    expected_models = sorted(
        (_select(item, model_fields) for item in snapshot["models"]),
        key=lambda item: item["uri"],
    )
    actual_models = [
        _select(item, model_fields) for item in facet["models"]
    ]
    if expected_models != actual_models:
        raise ValueError("Model receipt facet contradicts the execution snapshot")


def _match_context_reference(
    reference: Mapping[str, Any], public: Mapping[str, Any]
) -> None:
    expected = (
        public["requirement"]["requirement_id"],
        public["provider"]["uri"],
        public["status"],
    )
    actual = (
        reference.get("requirement_uri"),
        reference.get("provider_uri"),
        reference.get("status"),
    )
    if actual != expected:
        raise ValueError("Context Pack contradicts its execution snapshot reference")


def _context_pack_reference(
    reference: Mapping[str, Any], public: Mapping[str, Any] | None
) -> dict[str, Any]:
    resources = []
    if public is not None:
        resources = [
            {
                "uri": item["uri"],
                "digest": item["content_hash"],
                "trust": item["source_trust"],
                "freshness": item["freshness"],
                "sensitivity": item["sensitivity"],
            }
            for item in public["items"]
        ]
        resources.sort(key=lambda item: item["uri"])
    return {
        "requirement_uri": reference["requirement_uri"],
        "provider_uri": reference.get("provider_uri"),
        "pack_digest": reference.get("pack_digest"),
        "status": reference["status"],
        "resources": resources,
    }


def _pagination_facet(value: Mapping[str, Any]) -> dict[str, Any]:
    selected = _mapping(value, "pagination")
    return {
        "schema_version": "gravity.receipt-pagination-facet.v1",
        "completeness": _required(selected, "completeness", "pagination"),
        "pagination_evidence": _required(
            selected, "pagination_evidence", "pagination"
        ),
        "truncated": _required(selected, "truncated", "pagination"),
    }


def _data_quality_facet(value: Mapping[str, Any]) -> dict[str, Any]:
    selected = copy.deepcopy(_mapping(value, "data_quality"))
    validate_data_quality_result(selected)
    check_ids = [str(item["check_id"]) for item in selected["checks"]]
    if len(check_ids) != len(set(check_ids)):
        raise ValueError("Data Quality receipt check IDs are not unique")
    return {
        "schema_version": "gravity.receipt-data-quality-facet.v1",
        "status": selected["status"],
        "check_ids": sorted(check_ids),
        "result_digest": canonical_digest(selected),
    }


def _policy_facet(value: Mapping[str, Any]) -> dict[str, Any]:
    selected = copy.deepcopy(_mapping(value, "policy"))
    validate_schema(selected, "policy-decision-v1.schema.json", "Policy Decision")
    reasons = [str(item) for item in selected["reason_codes"]]
    masked = [str(item) for item in selected["masked_paths"]]
    if len(reasons) != len(set(reasons)) or len(masked) != len(set(masked)):
        raise ValueError("Policy receipt references are not unique")
    return {
        "schema_version": "gravity.receipt-policy-facet.v1",
        "decision_id": selected["decision_id"],
        "policy_revision": selected["policy_revision"],
        "decision": selected["decision"],
        "reason_codes": sorted(reasons),
        "evaluated_effect": selected["evaluated_effect"],
        "masked_paths": sorted(masked),
    }


def _action_facet(value: Mapping[str, Any]) -> dict[str, Any]:
    selected = copy.deepcopy(_mapping(value, "action"))
    schema_version = selected.get("schema_version")
    schemas = {
        "gravity.action-plan.v1": "action-plan-v1.schema.json",
        "gravity.action-execution.v1": "action-execution-v1.schema.json",
    }
    if not isinstance(schema_version, str) or schema_version not in schemas:
        raise ValueError("Action receipt source schema is unsupported")
    validate_schema(selected, schemas[schema_version], "Action receipt source")
    connector = _mapping(_required(selected, "connector", "action"), "connector")
    if schema_version == "gravity.action-plan.v1":
        summary = _mapping(
            _required(selected, "confirmation_summary", "action"),
            "confirmation_summary",
        )
        assertion_ids = list(
            _sequence(
                _required(summary, "readback_assertions", "confirmation_summary"),
                "readback_assertions",
            )
        )
        readback_status = "not_performed"
    else:
        readback = _mapping(_required(selected, "readback", "action"), "readback")
        assertions = _sequence(
            _required(readback, "assertions", "readback"), "readback assertions"
        )
        assertion_ids = [
            _required(_mapping(item, "readback assertion"), "id", "readback assertion")
            for item in assertions
        ]
        readback_status = _required(readback, "status", "readback")
    if any(not isinstance(item, str) for item in assertion_ids):
        raise ValueError("Action readback assertion IDs must be strings")
    if len(assertion_ids) != len(set(assertion_ids)):
        raise ValueError("Action readback assertion IDs are not unique")
    return {
        "schema_version": "gravity.receipt-action-facet.v1",
        "plan_id": _required(selected, "plan_id", "action"),
        "action_kind": _required(selected, "action_kind", "action"),
        "connector": {
            "id": _required(connector, "id", "connector"),
            "version": _required(connector, "version", "connector"),
        },
        "execution_status": _required(selected, "status", "action"),
        "readback": {
            "status": readback_status,
            "assertion_ids": sorted(assertion_ids),
        },
    }


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return value


def _sequence(value: Any, label: str) -> Sequence[Any]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ValueError(f"{label} must be an array")
    return value


def _required(value: Mapping[str, Any], key: str, label: str) -> Any:
    if key not in value:
        raise ValueError(f"{label} is missing {key}")
    return value[key]


def _select(value: Mapping[str, Any], fields: Sequence[str]) -> dict[str, Any]:
    return {field: copy.deepcopy(value[field]) for field in fields}


__all__ = ["compile_receipt_facets"]
