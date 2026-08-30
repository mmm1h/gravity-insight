"""Fail-closed Plan adapter for governed user-detail aggregate cells."""

from __future__ import annotations

import copy
import json
import math
import re
from collections.abc import Mapping, Sequence
from typing import Any

from .errors import ContractChangedError, PaginationError
from .actionable_error_values import actual_value
from .pagination_completeness import (
    PAGINATION_EVIDENCE_VALUES,
    collection_claims,
)
from .plan import AdapterContext
from .plan_adapter_support import (
    input_error,
    mapping,
    request_object,
    validate_exact_targets,
    validate_selected_fields,
)
from .result_audit import project_result_audit, result_receipt_references
from .result_source import GOVERNED_PRODUCT, result_source
from .user_detail_aggregate_contract import (
    INPUT_SCHEMA_VERSION,
    METADATA_OPERATION_ID,
    PRODUCT_OPERATION_ID,
    RESULT_SCHEMA_VERSION,
    SOURCE_OPERATION_ID,
    metric_definitions,
    normalize_user_detail_aggregate_inputs,
)


USER_DETAIL_AGGREGATE_NAME = "user_detail_aggregate"
REQUEST_FIELDS = frozenset({"name", "input_schema_version", "inputs"})
OUTPUT_FIELDS = frozenset(
    {
        "cell_count",
        "cells",
        "group_count",
        "pagination",
        "pagination_audit",
        "query",
        "result_audit",
        "source",
    }
)
_STRUCTURAL_FIELDS = frozenset(
    {
        "exit_code",
        "input_schema_version",
        "network_called",
        "ok",
        "operation_id",
        "query_executed",
        "result_source",
        "schema_version",
        "status",
    }
)
_VERSION = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def validate_user_detail_aggregate_plan(
    insight: Any,
    workspace: Any,
    request: Mapping[str, Any],
    context: AdapterContext,
) -> None:
    """Validate the closed product request entirely offline."""

    del insight, workspace
    request_object(request, REQUEST_FIELDS, USER_DETAIL_AGGREGATE_NAME)
    if request.get("name") != USER_DETAIL_AGGREGATE_NAME:
        raise input_error(
            f"actual value: {actual_value(request.get('name'))}; user-detail "
            "aggregate request name must be user_detail_aggregate",
            "name",
        )
    _require_version(request)
    validate_exact_targets(context, frozenset())
    validate_selected_fields(context.output_fields, OUTPUT_FIELDS, "output_fields")
    normalized = normalize_user_detail_aggregate_inputs(
        mapping(request.get("inputs"), "inputs")
    )
    if normalized["bounds"]["max_pages"] > context.max_pages:
        raise input_error(
            f"actual value: {actual_value(normalized['bounds']['max_pages'])}; "
            f"aggregate max_pages must not exceed the Plan node budget {context.max_pages}",
            "inputs.bounds.max_pages",
        )
    if normalized["bounds"]["max_cells"] > context.max_items:
        raise input_error(
            f"actual value: {actual_value(normalized['bounds']['max_cells'])}; "
            f"aggregate max_cells must not exceed the Plan node budget {context.max_items}",
            "inputs.bounds.max_cells",
        )


def execute_user_detail_aggregate_plan(
    sdk: Any,
    request: Mapping[str, Any],
    context: AdapterContext,
) -> dict[str, Any]:
    _require_version(request)
    normalized = normalize_user_detail_aggregate_inputs(
        mapping(request.get("inputs"), "inputs")
    )
    if normalized["bounds"]["max_pages"] > context.max_pages:
        raise PaginationError("aggregate max_pages exceeds the Plan node page budget")
    if normalized["bounds"]["max_cells"] > context.max_items:
        raise PaginationError("aggregate max_cells exceeds the Plan node item budget")

    from .user_detail_aggregate_product import run_user_detail_aggregate

    native = run_user_detail_aggregate(sdk.insight, normalized, max_workers=1)
    safe = sanitize_user_detail_aggregate_result(native, normalized)
    if safe["cell_count"] > context.max_items:
        raise PaginationError("user-detail aggregate exceeded its Plan item budget")
    return safe


def is_user_detail_aggregate_result(value: Any) -> bool:
    return (
        isinstance(value, Mapping)
        and value.get("schema_version") == RESULT_SCHEMA_VERSION
        and value.get("operation_id") == PRODUCT_OPERATION_ID
        and "cells" in value
    )


def project_user_detail_aggregate_result(
    result: Any,
    fields: tuple[str, ...],
    _context: AdapterContext,
) -> dict[str, Any]:
    if not isinstance(result, Mapping):
        raise ContractChangedError("user-detail aggregate result is invalid")
    query = result.get("query")
    if not isinstance(query, Mapping):
        raise ContractChangedError("user-detail aggregate query evidence changed")
    inputs = {
        "source": {"app_id": "projected", "date": "2026-01-01"},
        "filters": query.get("filters"),
        "group_by": query.get("group_by"),
        "measures": [
            {key: value for key, value in item.items() if key != "definition"}
            for item in query.get("measures", ())
            if isinstance(item, Mapping)
        ],
        "bounds": query.get("bounds"),
    }
    return sanitize_user_detail_aggregate_result(result, inputs, fields=fields)


def sanitize_user_detail_aggregate_result(
    result: Mapping[str, Any],
    inputs: Mapping[str, Any],
    *,
    fields: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Rebuild the Plan result without copying unknown containers or row values."""

    normalized = normalize_user_detail_aggregate_inputs(inputs)
    _validate_identity(result)
    cells = _safe_cells(result.get("cells"), normalized)
    cell_count = result.get("cell_count")
    group_count = result.get("group_count")
    actual_group_count = len(
        {
            json.dumps(item["group"], ensure_ascii=True, sort_keys=True)
            for item in cells
        }
    )
    if cell_count != len(cells) or group_count != actual_group_count:
        raise ContractChangedError("user-detail aggregate result counts changed")
    if len(cells) > normalized["bounds"]["max_cells"]:
        raise PaginationError("user-detail aggregate exceeded its explicit cell bound")

    pagination = _safe_pagination(result.get("pagination"), normalized)
    selected: dict[str, Any] = {
        "schema_version": RESULT_SCHEMA_VERSION,
        "input_schema_version": INPUT_SCHEMA_VERSION,
        "result_source": result_source(GOVERNED_PRODUCT),
        "ok": True,
        "status": result["status"],
        "exit_code": 0,
        "operation_id": PRODUCT_OPERATION_ID,
        "network_called": True,
        "query_executed": True,
        "query": {
            "filters": copy.deepcopy(normalized["filters"]),
            "group_by": list(normalized["group_by"]),
            "measures": metric_definitions(normalized),
            "bounds": dict(normalized["bounds"]),
        },
        "cells": cells,
        "cell_count": len(cells),
        "group_count": actual_group_count,
        "pagination": pagination,
        "source": _safe_source(result.get("source")),
        "pagination_audit": _safe_pagination_audit(
            pagination, result_receipt_references(result)
        ),
    }
    selected = project_result_audit(selected, result)
    if not fields:
        return selected
    return {
        key: copy.deepcopy(value)
        for key, value in selected.items()
        if key in _STRUCTURAL_FIELDS or key in fields
    }


def _require_version(request: Mapping[str, Any]) -> None:
    if request.get("input_schema_version") != INPUT_SCHEMA_VERSION:
        raise input_error(
            f"actual value: {actual_value(request.get('input_schema_version'))}; "
            "user-detail aggregate requests must use the current input schema version",
            "input_schema_version",
        )


def _validate_identity(value: Mapping[str, Any]) -> None:
    expected = {
        "schema_version": RESULT_SCHEMA_VERSION,
        "input_schema_version": INPUT_SCHEMA_VERSION,
        "operation_id": PRODUCT_OPERATION_ID,
        "ok": True,
        "exit_code": 0,
        "network_called": True,
        "query_executed": True,
    }
    if any(value.get(key) != expected_value for key, expected_value in expected.items()):
        raise ContractChangedError("user-detail aggregate result identity changed")
    if value.get("status") not in {"success", "empty"}:
        raise ContractChangedError("user-detail aggregate result status changed")


def _safe_cells(value: Any, inputs: Mapping[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ContractChangedError("user-detail aggregate cells changed")
    group_fields = tuple(inputs["group_by"])
    measures = tuple(item["name"] for item in inputs["measures"])
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    groups: dict[str, set[str]] = {}
    for item in value:
        if not isinstance(item, Mapping) or set(item) != {"group", "measure", "value"}:
            raise ContractChangedError("user-detail aggregate cell shape changed")
        group = item.get("group")
        if not isinstance(group, Mapping) or tuple(group) != group_fields:
            raise ContractChangedError("user-detail aggregate group shape changed")
        safe_group = {field: _safe_scalar(group[field]) for field in group_fields}
        measure = item.get("measure")
        number = item.get("value")
        if measure not in measures or not _finite_number(number):
            raise ContractChangedError("user-detail aggregate measure shape changed")
        group_key = json.dumps(safe_group, ensure_ascii=True, sort_keys=True)
        identity = (group_key, str(measure))
        if identity in seen:
            raise ContractChangedError("user-detail aggregate cells are duplicated")
        seen.add(identity)
        groups.setdefault(group_key, set()).add(str(measure))
        result.append(
            {
                "group": safe_group,
                "measure": str(measure),
                "value": number,
            }
        )
    if any(selected != set(measures) for selected in groups.values()):
        raise ContractChangedError("user-detail aggregate measure coverage changed")
    return result


def _safe_pagination(value: Any, inputs: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractChangedError("user-detail aggregate pagination evidence changed")
    completeness = value.get("completeness")
    evidence = value.get("pagination_evidence")
    if completeness not in {"complete", "prefix", "unknown"}:
        raise ContractChangedError("user-detail aggregate completeness changed")
    if evidence not in PAGINATION_EVIDENCE_VALUES:
        raise ContractChangedError("user-detail aggregate pagination evidence changed")
    consumed_pages = _bounded_count(
        value.get("consumed_pages"), inputs["bounds"]["max_pages"], "consumed pages"
    )
    consumed_items = _bounded_count(
        value.get("consumed_items"), inputs["bounds"]["max_items"], "consumed items"
    )
    allowed, forbidden = collection_claims(str(completeness))
    return {
        "completeness": completeness,
        "pagination_evidence": evidence,
        "consumed_pages": consumed_pages,
        "consumed_items": consumed_items,
        "source_total_pages": _optional_count(value.get("source_total_pages")),
        "source_total_items": _optional_count(value.get("source_total_items")),
        "fetch_strategy": _fetch_strategy(value.get("fetch_strategy")),
        "claims": {"allowed": allowed, "forbidden": forbidden},
    }


def _safe_source(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractChangedError("user-detail aggregate source evidence changed")
    metadata = value.get("field_catalog")
    if not isinstance(metadata, Mapping):
        raise ContractChangedError("user-detail aggregate field catalog evidence changed")
    return {
        "operation_id": SOURCE_OPERATION_ID,
        "schema_version": _safe_version(value.get("schema_version")),
        "contract_version": _safe_version(value.get("contract_version")),
        "schema_fingerprint": _safe_fingerprint(value.get("schema_fingerprint")),
        "contract_fingerprint": _safe_fingerprint(value.get("contract_fingerprint")),
        "field_catalog": {
            "operation_id": METADATA_OPERATION_ID,
            "schema_version": _safe_version(metadata.get("schema_version")),
            "contract_version": _safe_version(metadata.get("contract_version")),
            "schema_fingerprint": _safe_fingerprint(metadata.get("schema_fingerprint")),
            "contract_fingerprint": _safe_fingerprint(metadata.get("contract_fingerprint")),
        },
    }


def _safe_pagination_audit(
    pagination: Mapping[str, Any], receipts: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    completeness = str(pagination["completeness"])
    criterion = {
        "complete": "source contract reports the consumed collection complete",
        "prefix": "source contract reports only a collection prefix",
        "unknown": "source contract does not prove collection completeness",
    }[completeness]
    return {
        "mode": "all_pages",
        "operation_requests_made": pagination["consumed_pages"],
        "http_requests_made": len(receipts),
        "requested_page_size": 100,
        "effective_page_size": None,
        "page_size_clamped": False,
        "completeness": {
            "criterion": criterion,
            "status": completeness,
            "has_more": False if completeness == "complete" else None,
            "returned_items": pagination["consumed_items"],
            "total_items": pagination["source_total_items"],
        },
    }


def _safe_scalar(value: Any) -> Any:
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, str) and len(value) <= 4_096:
        return value
    if _finite_number(value):
        return value
    raise ContractChangedError("user-detail aggregate group value changed type")


def _finite_number(value: Any) -> bool:
    return (
        type(value) is int and value.bit_length() <= 13_607
        or isinstance(value, float) and math.isfinite(value)
    )


def _bounded_count(value: Any, maximum: int, label: str) -> int:
    if type(value) is not int or not 0 <= value <= maximum:
        raise ContractChangedError(f"user-detail aggregate {label} changed")
    return value


def _optional_count(value: Any) -> int | None:
    if value is None:
        return None
    if type(value) is not int or value < 0:
        raise ContractChangedError("user-detail aggregate source total changed")
    return value


def _safe_version(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or _VERSION.fullmatch(value) is None:
        raise ContractChangedError("user-detail aggregate source version changed")
    return value


def _safe_fingerprint(value: Any) -> str | None:
    if value is None:
        return None
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value.casefold())
    ):
        raise ContractChangedError("user-detail aggregate source fingerprint changed")
    return value.casefold()


def _fetch_strategy(value: Any) -> str | None:
    allowed = {
        "parallel_known_total",
        "serial_known_total",
        "serial_unknown_total",
        "single_page",
        "stopped_missing_total_page",
    }
    if value is None:
        return None
    if value not in allowed:
        raise ContractChangedError("user-detail aggregate fetch strategy changed")
    return str(value)


__all__ = [
    "OUTPUT_FIELDS",
    "USER_DETAIL_AGGREGATE_NAME",
    "execute_user_detail_aggregate_plan",
    "is_user_detail_aggregate_result",
    "project_user_detail_aggregate_result",
    "sanitize_user_detail_aggregate_result",
    "validate_user_detail_aggregate_plan",
]
