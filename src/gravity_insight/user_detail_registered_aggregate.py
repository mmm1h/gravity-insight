"""Static-field, shared-read aggregation using the governed user-detail reducer."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from .errors import ContractChangedError, GravityInsightError, exit_code_for_error
from .result_audit import result_receipt_references
from .user_detail_aggregate_contract import SOURCE_OPERATION_ID, referenced_fields
from .user_detail_aggregate_service import (
    _FieldCatalog,
    _schema_scalar_fields,
    _validate_fields,
    _workers,
    _validate_source_envelope,
    _source_rows,
    _validate_row_types,
    _matches,
    _aggregate_cells,
)


def aggregate_registered_day(
    client: Any,
    source: Mapping[str, str],
    groups: Sequence[Mapping[str, Any]],
    metrics: Mapping[str, Mapping[str, Any]],
    *,
    max_pages: int,
    max_items: int,
    max_workers: int = 6,
) -> dict[str, Any]:
    """Share one static-field read; deliver only independently checked cells.

    Unlike aggregate(), this path cannot load dynamic metadata or authorize
    sums. The caller supplies proven, typed material join conditions.
    """
    _workers(max_workers)
    requests, failures, fields = _registered_requests(client, source, groups, metrics, max_pages, max_items)
    if not requests:
        return {"cells": failures, "scan": None, "http_receipts": []}
    native = client.read_limited(
        SOURCE_OPERATION_ID,
        {**source, "fields": sorted(fields), "page": 1, "page_size": 100},
        max_pages=max_pages,
        max_items=max_items,
        max_workers=max_workers,
    )
    _validate_source_envelope(native)
    rows = _source_rows(native)
    from .material_game_result import scan_receipt

    scan = scan_receipt(native, max_pages=max_pages, max_items=max_items)
    if scan["items_scanned"] != len(rows):
        raise ContractChangedError("user source row count contradicts pagination")
    cells = dict(failures)
    try:
        cohort = _registered_cohort_rows(rows, source["date"])
    except GravityInsightError as exc:
        cells.update({key: _registered_failure(exc) for key in requests})
    else:
        for key, inputs in requests.items():
            try:
                # Validate against all observed rows, as the original product
                # does, before applying material or acquisition-date filters.
                _validate_row_types(rows, inputs)
                selected = [
                    row
                    for row in cohort
                    if _matches(row.get(inputs["filters"][0]["field"]), inputs["filters"][0])
                ]
                metric_fields = referenced_fields({**inputs, "filters": []})
                if metric_fields and not any(
                    row.get(field) is not None for row in selected for field in metric_fields
                ):
                    cells[key] = {
                        "status": "unavailable",
                        "value": None,
                        "reason": "METRIC_VALUES_UNAVAILABLE",
                    }
                    continue
                cells[key] = {"status": "obtained", "value": _aggregate_cells(cohort, inputs)[0]["value"]}
                if inputs["measures"][0]["op"] != "count":
                    cells[key]["definition"] = _registered_definition(inputs["measures"][0])
            except GravityInsightError as exc:
                cells[key] = _registered_failure(exc)
    return {"cells": cells, "scan": scan, "http_receipts": result_receipt_references(native)}


def _registered_definition(measure: Mapping[str, Any]) -> dict[str, Any]:
    definition = dict(measure)
    condition = measure.get("condition")
    if condition and any(isinstance(value, str) for value in condition["values"]):
        definition["condition"] = {
            "field": condition["field"],
            "operator": condition["operator"],
            "values_redacted": True,
        }
    return definition


def _registered_failure(exc: GravityInsightError) -> dict[str, Any]:
    return {
        "status": "unavailable",
        "value": None,
        "reason": exc.to_error_detail().code,
        "error": exc.to_error_detail().to_dict(),
        "exit_code": exit_code_for_error(exc),
    }


def _registered_cohort_rows(
    rows: Sequence[Mapping[str, Any]],
    day: str,
) -> list[Mapping[str, Any]]:
    selected = []
    for row in rows:
        value = row.get("CreateTime")
        try:
            if not isinstance(value, str) or len(value) > 64:
                raise ValueError
            parsed = datetime.fromisoformat(value)
            if value[:10] != parsed.date().isoformat():
                raise ValueError
        except (ValueError, TypeError):
            raise ContractChangedError(
                "CreateTime cannot establish a disjoint acquisition calendar date",
                code="MATERIAL_COHORT_DATE_UNAVAILABLE",
                next_action="Confirm the source acquisition-date contract; do not sum overlapping snapshots.",
            ) from None
        if parsed.date().isoformat() == day:
            selected.append(row)
    return selected


def _registered_requests(
    client: Any,
    source: Mapping[str, str],
    groups: Sequence[Mapping[str, Any]],
    metrics: Mapping[str, Mapping[str, Any]],
    max_pages: int,
    max_items: int,
) -> tuple[Any, ...]:
    catalog = _FieldCatalog(_schema_scalar_fields(client.schema(SOURCE_OPERATION_ID)), set())
    requests: dict[str, dict[str, Any]] = {}
    failures: dict[str, dict[str, Any]] = {}
    fields = {"CreateTime"}
    for group in groups:
        for name, measure in {"matched_users": {"name": "matched_users", "op": "count"}, **metrics}.items():
            key = f"{group['key']}:{name}"
            inputs = {
                "source": dict(source),
                "filters": [dict(group["condition"])],
                "group_by": [],
                "measures": [dict(measure)],
                "bounds": {"max_pages": max_pages, "max_items": max_items, "max_cells": 200},
            }
            try:
                _validate_fields(inputs, catalog)
            except GravityInsightError as exc:
                failures[key] = _registered_failure(exc)
                continue
            requests[key] = inputs
            fields.update(referenced_fields(inputs))
    return requests, failures, fields
