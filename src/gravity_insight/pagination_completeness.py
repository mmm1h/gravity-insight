"""Contract and result semantics for collection completeness."""

from __future__ import annotations

import copy
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from .actionable_error_values import actual_value
from .contracts.envelope_obligations import classify_data_completeness
from .errors import ErrorCategory, ErrorDetail, ManifestError, exit_code_for_error


COMPLETE = "complete"
PREFIX = "prefix"
UNKNOWN = "unknown"
COMPLETENESS_VALUES = frozenset({COMPLETE, PREFIX, UNKNOWN})
PAGINATION_EVIDENCE_VALUES = frozenset({"production", "wire", "template", "none"})
_COMPLETE_EVIDENCE = frozenset({"production", "wire"})


def compact_pagination(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {
            "supported": False,
            "kind": "none",
            "completeness": "unknown",
            "pagination_evidence": "none",
        }
    kind = str(value.get("kind", "none"))
    return {
        "supported": kind != "none",
        "kind": kind,
        "completeness": value.get("completeness", "unknown"),
        "pagination_evidence": value.get("pagination_evidence", "none"),
        "page_field": value.get("page_field"),
        "page_size_field": value.get("page_size_field"),
        "max_page_size": value.get("max_page_size"),
    }


def contract_dimensions(value: Mapping[str, Any]) -> tuple[str, str]:
    """Parse fail-closed pagination dimensions from a runtime manifest."""

    completeness = str(value.get("completeness", UNKNOWN)).strip().lower()
    evidence = str(value.get("pagination_evidence", "none")).strip().lower()
    if completeness not in COMPLETENESS_VALUES:
        raise ManifestError(
            f"actual value: {actual_value(completeness)}; pagination.completeness "
            "must be complete, prefix, or unknown",
            field="pagination.completeness",
            next_action="Correct the operation pagination contract and recompile manifests.",
        )
    if evidence not in PAGINATION_EVIDENCE_VALUES:
        raise ManifestError(
            f"actual value: {actual_value(evidence)}; pagination.pagination_evidence "
            "must be production, wire, template, or none",
            field="pagination.pagination_evidence",
            next_action="Correct the operation pagination contract and recompile manifests.",
        )
    if completeness == COMPLETE and evidence not in _COMPLETE_EVIDENCE:
        raise ManifestError(
            f"actual value: {actual_value({'completeness': completeness, 'pagination_evidence': evidence})}; "
            "template or absent pagination evidence cannot prove a complete collection",
            field="pagination.completeness",
            next_action="Set completeness to unknown or cite existing production/wire evidence.",
        )
    return completeness, evidence


def page_completeness(
    contract: str,
    page: Mapping[str, Any] | None,
    *,
    all_pages: bool,
) -> str:
    """Classify one returned collection without promoting contract evidence."""

    if page is None:
        return UNKNOWN
    has_more = page.get("has_more")
    number = page.get("number")
    if has_more is True and (all_pages or number in (None, 1)):
        return PREFIX
    if contract != COMPLETE or has_more is not False:
        return UNKNOWN
    if not all_pages and number not in (None, 1):
        return UNKNOWN
    returned, total = page.get("item_count"), page.get("total_items")
    if not _nonnegative_int(returned) or not _nonnegative_int(total):
        return UNKNOWN
    return COMPLETE if returned == total else PREFIX


def force_prefix(result: dict[str, Any], truncated: bool) -> None:
    """Mark a known bounded truncation without changing other result fields."""

    if truncated:
        result["completeness"] = PREFIX


def aggregate_completeness(value: Any) -> str:
    """Propagate any nested result completeness into an aggregate envelope."""

    return classify_data_completeness(value).state.value


def require_complete_product(
    result: Mapping[str, Any], *, operation_id: str, product: str
) -> dict[str, Any]:
    """Return a machine-readable gap when a product requires a full collection."""

    selected = copy.deepcopy(dict(result))
    observed = aggregate_completeness(selected)
    if observed == COMPLETE:
        return selected
    detail = ErrorDetail.create(
        "COMPLETENESS_UNPROVEN",
        f"actual value: {actual_value(observed)}; {product} requires a proven complete collection.",
        category=ErrorCategory.CALLER,
        field="completeness",
        operation_id=operation_id,
        next_action=(
            "Use returned rows only as a prefix, or obtain production/wire pagination "
            "evidence and update the operation contract before retrying this product."
        ),
    )
    selected.update(
        ok=False,
        status="capability_gap",
        exit_code=exit_code_for_error(detail),
        required_completeness=COMPLETE,
        error=detail.to_dict(),
        next_action=detail.next_action,
    )
    return selected


def collection_claims(completeness: str) -> tuple[list[str], list[str]]:
    """Expose only claims justified by the operation completeness contract."""

    allowed = ["returned_items"]
    forbidden: list[str] = []
    if completeness == COMPLETE:
        allowed.extend(["complete_collection", "complete_collection_count"])
    else:
        forbidden.extend(["complete_collection", "complete_collection_count"])
    return allowed, forbidden


def _nonnegative_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


SURFACE_PARITY_OUTCOMES = ("empty", "partial", "error")
SURFACE_ERROR_TAXONOMY = ("caller", "upstream", "local")


@dataclass(frozen=True)
class SurfaceDeclaration:
    input_contract: str
    result_schema: str
    completeness: str
    allowed_claims: str
    privacy: str
    error_taxonomy: tuple[str, ...]


@dataclass(frozen=True)
class StableProductSurface:
    name: str
    direct: SurfaceDeclaration
    plan: SurfaceDeclaration
    outcomes: tuple[str, ...]
    forbidden_result_keys: tuple[str, ...] = ()


def _surface(
    name: str,
    input_contract: str,
    result_schema: str,
    privacy: str,
    *,
    forbidden_result_keys: tuple[str, ...] = (),
) -> StableProductSurface:
    declaration = SurfaceDeclaration(
        input_contract,
        result_schema,
        "nested-propagation",
        "producer-preserved",
        privacy,
        SURFACE_ERROR_TAXONOMY,
    )
    return StableProductSurface(
        name,
        declaration,
        replace(declaration),
        SURFACE_PARITY_OUTCOMES,
        forbidden_result_keys,
    )


STABLE_PRODUCT_SURFACES = (
    _surface(
        "business_pulse",
        "unversioned:business_pulse(apps,start,end,platforms,include_hourly)",
        "gravity-insight.business-pulse.v1",
        "aggregate",
    ),
    _surface(
        "multidim",
        "gravity-insight.multidim-input.v1",
        "gravity-insight.composite.multidim.v1",
        "aggregate",
    ),
    _surface(
        "user_detail_aggregate",
        "gravity-insight.user-detail-aggregate-input.v1",
        "gravity-insight.user-detail-aggregate.v1",
        "aggregate-no-user-rows",
        forbidden_result_keys=("data", "request", "next_page_input"),
    ),
    _surface(
        "material_performance",
        "unversioned:material_performance(apps,start,end,platforms)",
        "gravity-insight.material-performance.v1",
        "aggregate",
    ),
    _surface(
        "promotion_performance",
        "gravity-insight.promotion-performance-input.v1",
        "gravity-insight.promotion-performance.v1",
        "aggregate",
    ),
    _surface(
        "dashboard_analysis",
        "unversioned:dashboard_analysis(app,ref,mode,bounds)",
        "gravity-insight.dashboard-analysis.v1",
        "governed-analysis",
    ),
    _surface(
        "order_directory",
        "unversioned:order_directory(app,date,bounds)",
        "gravity-insight.order-directory.v1",
        "governed-product-projection",
    ),
    _surface(
        "order_split_trace",
        "unversioned:order_split_trace(app,date,trace_id,bounds)",
        "gravity-insight.order-split-trace.v1",
        "governed-product-projection",
    ),
)
_SURFACE_BY_NAME = {item.name: item for item in STABLE_PRODUCT_SURFACES}


def stable_product_surface_matrix() -> tuple[dict[str, Any], ...]:
    """Generate the JSON-safe matrix from the single machine registry."""

    return tuple(
        {
            "name": item.name,
            "direct": _surface_declaration_dict(item.direct),
            "plan": _surface_declaration_dict(item.plan),
            "outcomes": list(item.outcomes),
            "forbidden_result_keys": list(item.forbidden_result_keys),
        }
        for item in STABLE_PRODUCT_SURFACES
    )


def surface_contract(name: object) -> StableProductSurface | None:
    return _SURFACE_BY_NAME.get(str(name))


def validate_surface_registry() -> None:
    """Fail offline if a surface declaration or sample cannot be enveloped."""

    if len(_SURFACE_BY_NAME) != len(STABLE_PRODUCT_SURFACES):
        raise RuntimeError("stable product surface names must be unique")
    for contract in STABLE_PRODUCT_SURFACES:
        if contract.outcomes != SURFACE_PARITY_OUTCOMES:
            raise RuntimeError(f"surface {contract.name} must cover empty, partial, and error")
        for outcome in contract.outcomes:
            direct, plan = surface_parity_sample(contract, outcome)
            validate_surface_pair(contract, direct, plan)


def surface_parity_sample(
    contract: StableProductSurface, outcome: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    if outcome not in SURFACE_PARITY_OUTCOMES:
        raise ValueError("surface parity outcome is invalid")
    ok = outcome == "empty"
    error = None if ok else {
        "code": "UPSTREAM_UNAVAILABLE" if outcome == "partial" else "INPUT_INVALID",
        "category": "upstream" if outcome == "partial" else "caller",
        "retryable": outcome == "partial",
    }
    result = {
        "schema_version": contract.direct.result_schema,
        "ok": ok,
        "status": outcome,
        "pagination": {
            "completeness": "unknown",
            "claims": {
                "allowed": ["returned_items"],
                "forbidden": ["complete_collection", "complete_collection_count"],
            },
        },
        "pagination_audit": {
            "completeness": {
                "status": "unknown",
                "criterion": "source contract does not prove collection completeness",
            }
        },
        "error": error,
    }
    return copy.deepcopy(result), copy.deepcopy(result)


def validate_surface_pair(
    contract: StableProductSurface,
    direct: Mapping[str, Any],
    plan: Mapping[str, Any],
) -> None:
    """Compare the six governed parity dimensions for one product result pair."""

    comparisons = {
        "input contract": (contract.direct.input_contract, contract.plan.input_contract),
        "result schema": (direct.get("schema_version"), plan.get("schema_version")),
        "completeness": (aggregate_completeness(direct), aggregate_completeness(plan)),
        "allowed claims": (_surface_allowed_claims(direct), _surface_allowed_claims(plan)),
        "privacy": (contract.direct.privacy, contract.plan.privacy),
        "error taxonomy": (_surface_error_taxonomy(direct), _surface_error_taxonomy(plan)),
    }
    declarations = (
        ("result schema", contract.direct.result_schema, contract.plan.result_schema),
        ("allowed claims", contract.direct.allowed_claims, contract.plan.allowed_claims),
        ("error taxonomy", contract.direct.error_taxonomy, contract.plan.error_taxonomy),
    )
    for dimension, (direct_value, plan_value) in comparisons.items():
        if direct_value != plan_value:
            raise RuntimeError(f"surface {contract.name} {dimension} parity changed")
    for dimension, direct_value, plan_value in declarations:
        if direct_value != plan_value:
            raise RuntimeError(f"surface {contract.name} declared {dimension} parity changed")
    _validate_surface_privacy(contract, direct, "Direct")
    _validate_surface_privacy(contract, plan, "Plan")


def _surface_declaration_dict(value: SurfaceDeclaration) -> dict[str, Any]:
    return {
        "input_contract": value.input_contract,
        "result_schema": value.result_schema,
        "completeness": value.completeness,
        "allowed_claims": value.allowed_claims,
        "privacy": value.privacy,
        "error_taxonomy": list(value.error_taxonomy),
    }


def _surface_allowed_claims(value: Any) -> tuple[str, ...]:
    selected: list[str] = []
    if isinstance(value, Mapping):
        candidates = (value.get("allowed_claims"),)
        claims = value.get("claims")
        if isinstance(claims, Mapping):
            candidates += (claims.get("allowed"),)
        for candidate in candidates:
            if isinstance(candidate, Sequence) and not isinstance(candidate, (str, bytes)):
                selected.extend(_stable_surface_claim(claim) for claim in candidate)
        for nested in value.values():
            if isinstance(nested, (Mapping, list, tuple)):
                selected.extend(_surface_allowed_claims(nested))
    elif isinstance(value, (list, tuple)):
        for nested in value:
            selected.extend(_surface_allowed_claims(nested))
    return tuple(sorted(selected))


def _stable_surface_claim(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _surface_error_taxonomy(value: Mapping[str, Any]) -> tuple[Any, Any, Any] | None:
    error = value.get("error")
    if not isinstance(error, Mapping):
        return None
    return error.get("code"), error.get("category"), error.get("retryable")


def _validate_surface_privacy(
    contract: StableProductSurface, value: Mapping[str, Any], surface: str
) -> None:
    forbidden = set(contract.forbidden_result_keys)
    if forbidden and _surface_contains_key(value, forbidden):
        raise RuntimeError(f"surface {contract.name} {surface} privacy parity changed")


def _surface_contains_key(value: Any, forbidden: set[str]) -> bool:
    if isinstance(value, Mapping):
        return bool(set(value) & forbidden) or any(
            _surface_contains_key(nested, forbidden) for nested in value.values()
        )
    if isinstance(value, (list, tuple)):
        return any(_surface_contains_key(nested, forbidden) for nested in value)
    return False


__all__ = [
    "COMPLETE",
    "COMPLETENESS_VALUES",
    "PAGINATION_EVIDENCE_VALUES",
    "PREFIX",
    "STABLE_PRODUCT_SURFACES",
    "SURFACE_PARITY_OUTCOMES",
    "StableProductSurface",
    "SurfaceDeclaration",
    "UNKNOWN",
    "aggregate_completeness",
    "collection_claims",
    "compact_pagination",
    "contract_dimensions",
    "force_prefix",
    "page_completeness",
    "require_complete_product",
    "stable_product_surface_matrix",
    "surface_contract",
    "surface_parity_sample",
    "validate_surface_pair",
    "validate_surface_registry",
]
