"""Small, additive provenance contract for public execution results."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


SCHEMA_VERSION = "gravity.result-source.v1"
GOVERNED_PRODUCT = "governed_product"
CALLER_DEFINED = "caller_defined"
RAW_OPERATION = "raw_operation"
LOCAL_CATALOG = "local_catalog"
LOCAL_AUDIT = "local_audit"
MIXED = "mixed"

_SEMANTIC_VERIFICATION = {
    GOVERNED_PRODUCT: "product_contract",
    CALLER_DEFINED: "caller_responsible",
    RAW_OPERATION: "operation_contract_only",
    LOCAL_CATALOG: "catalog_contract",
    LOCAL_AUDIT: "audit_contract",
    MIXED: "per_result",
}
_GOVERNED_CARD_KINDS = {
    "analysis_query_spec",
    "composite",
    "custom_metric_list",
    "custom_metric_mutation",
    "export",
    "material_asset",
    "report_mutation",
    "segment_rule_spec",
    "segment_mutation",
}


def result_source(tier: str) -> dict[str, str]:
    """Return a fresh, machine-stable source statement for one result path."""

    try:
        verification = _SEMANTIC_VERIFICATION[tier]
    except KeyError as exc:
        raise ValueError(f"unknown result source tier: {tier}") from exc
    return {
        "schema_version": SCHEMA_VERSION,
        "tier": tier,
        "semantic_verification": verification,
    }


def add_result_source(
    value: Mapping[str, Any], tier: str, *, replace: bool = False
) -> dict[str, Any]:
    """Copy an envelope and add its source without changing existing fields."""

    selected = dict(value)
    expected = result_source(tier)
    current = selected.get("result_source")
    if current is not None and current != expected and not replace:
        raise ValueError("result envelope already declares a different source")
    selected["result_source"] = expected
    return selected


def selector_result_source(selector: object) -> dict[str, str]:
    """Classify the two public resolver selectors without inspecting values."""

    tier = CALLER_DEFINED if str(selector).startswith("@") else RAW_OPERATION
    return result_source(tier)


def plan_result_source(kind: object, request: object) -> dict[str, str]:
    """Classify a Plan node from its registered adapter kind and selector."""

    selected_kind = str(kind)
    selected_request = request if isinstance(request, Mapping) else {}
    if selected_kind == "run":
        return selector_result_source(selected_request.get("selector"))
    if selected_kind == "sql_product":
        return result_source(CALLER_DEFINED)
    if selected_kind == "metadata_search":
        return result_source(LOCAL_CATALOG)
    if selected_kind == "composite":
        if selected_request.get("name") == "derived_metrics":
            return result_source(CALLER_DEFINED)
        return result_source(GOVERNED_PRODUCT)
    if selected_kind == "receipt_query":
        return result_source(LOCAL_AUDIT)
    raise ValueError(f"unknown Plan result source kind: {selected_kind}")


def card_result_source(card: Mapping[str, Any]) -> dict[str, str]:
    """Declare the source of the execution result promised by an Agent card."""

    kind = str(card.get("kind", ""))
    if card.get("description_origin") == "caller_workspace":
        return result_source(CALLER_DEFINED)
    if kind == "composite" and card.get("composite") == "derived_metrics":
        return result_source(CALLER_DEFINED)
    if kind == "operation":
        return result_source(RAW_OPERATION)
    if kind in {"recipe", "sql_product"}:
        return result_source(CALLER_DEFINED)
    if kind in {"analysis_task", "metadata"}:
        return result_source(LOCAL_CATALOG)
    if kind in _GOVERNED_CARD_KINDS:
        return result_source(GOVERNED_PRODUCT)
    raise ValueError(f"unknown Agent card result source kind: {kind}")


def aggregate_result_sources(values: Sequence[Mapping[str, Any]]) -> dict[str, str]:
    """Preserve a uniform tier or identify an envelope as per-result mixed."""

    sources = [value.get("result_source") for value in values]
    normalized = [dict(value) for value in sources if isinstance(value, Mapping)]
    if normalized and len(normalized) == len(values) and all(
        value == normalized[0] for value in normalized[1:]
    ):
        return normalized[0]
    return result_source(MIXED)


__all__ = [
    "CALLER_DEFINED",
    "GOVERNED_PRODUCT",
    "LOCAL_CATALOG",
    "LOCAL_AUDIT",
    "MIXED",
    "RAW_OPERATION",
    "SCHEMA_VERSION",
    "add_result_source",
    "aggregate_result_sources",
    "card_result_source",
    "plan_result_source",
    "result_source",
    "selector_result_source",
]
