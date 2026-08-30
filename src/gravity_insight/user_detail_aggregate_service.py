"""Live field-catalog validation and private reduction for user-detail rows."""

from __future__ import annotations

import copy
import json
import math
from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any, Protocol

from ._field_policy_shared import (
    is_direct_personal_response_field,
    is_sensitive_analysis_field,
)
from .errors import ContractChangedError, ErrorCode, GravityInsightError
from .pagination_audit import pagination_audit
from .pagination_completeness import collection_claims
from .result_audit import (
    add_result_audit,
    bind_error_receipts,
    result_receipt_references,
)
from .result_source import GOVERNED_PRODUCT, result_source
from .user_detail_aggregate_contract import (
    AggregateCardinalityError,
    AggregateFieldUnsupportedError,
    AggregateMixedTypeError,
    INPUT_SCHEMA_VERSION,
    METADATA_OPERATION_ID,
    PRODUCT_OPERATION_ID,
    RESULT_SCHEMA_VERSION,
    SOURCE_OPERATION_ID,
    metric_definitions,
    numeric_measure_fields,
    referenced_fields,
)


_NUMERIC_METADATA_TYPES = frozenset(
    {"DECIMAL", "DOUBLE", "FLOAT", "INT", "INTEGER", "LONG", "NUMBER"}
)
_SCALAR_METADATA_TYPES = _NUMERIC_METADATA_TYPES | frozenset(
    {"BOOL", "BOOLEAN", "DATE", "DATETIME", "STRING"}
)
_DIRECT_IDENTIFIERS = frozenset(
    {
        "clientid",
        "deviceid",
        "name",
        "userid",
        "useraccountid",
        "userdeviceid",
        "userloginid",
        "userlongid",
        "userrolename",
        "usertadistinctid",
        "wxopenid",
    }
)


class _PublicClient(Protocol):
    def schema(self, operation_id: str) -> Mapping[str, Any]: ...

    def read_all(
        self,
        operation_id: str,
        inputs: Mapping[str, Any],
        *,
        max_pages: int,
        max_items: int,
        max_workers: int,
    ) -> Mapping[str, Any]: ...


class _FieldCatalog:
    def __init__(self, allowed: set[str], numeric: set[str]) -> None:
        self.allowed = frozenset(allowed)
        self.numeric = frozenset(numeric)


class UserDetailAggregateService:
    """Execute one bounded source read and discard every source row after reduction."""

    def __init__(self, client: _PublicClient) -> None:
        if any(not callable(getattr(client, name, None)) for name in ("schema", "read_all")):
            raise TypeError("user-detail aggregate requires the public Insight client")
        self._client = client

    def aggregate(
        self, inputs: Mapping[str, Any], *, max_workers: int = 6
    ) -> dict[str, Any]:
        bounds = inputs["bounds"]
        _workers(max_workers)
        if len(inputs["measures"]) > bounds["max_cells"]:
            raise AggregateCardinalityError(
                "aggregate measure count exceeds the explicit cell bound",
                field="bounds.max_cells",
            )
        try:
            metadata = self._metadata(
                inputs["source"]["app_id"], max_workers=max_workers
            )
            catalog = _field_catalog(self._client.schema(SOURCE_OPERATION_ID), metadata)
            _validate_fields(inputs, catalog)
            source_inputs = {
                **inputs["source"],
                "fields": sorted(referenced_fields(inputs)),
                "page": 1,
                "page_size": 100,
            }
            source = self._client.read_all(
                SOURCE_OPERATION_ID,
                source_inputs,
                max_pages=bounds["max_pages"],
                max_items=bounds["max_items"],
                max_workers=max_workers,
            )
            _validate_source_envelope(source)
            rows = _source_rows(source)
            _validate_row_types(rows, inputs)
            cells = _aggregate_cells(rows, inputs)
            result = _result(inputs, source, metadata, source_inputs, cells, len(rows))
            return add_result_audit(
                result,
                [
                    *result_receipt_references(metadata),
                    *result_receipt_references(source),
                ],
            )
        except GravityInsightError as exc:
            bind_error_receipts(
                exc,
                [
                    *result_receipt_references(locals().get("metadata")),
                    *result_receipt_references(locals().get("source")),
                ],
            )
            raise

    def _metadata(self, app_id: str, *, max_workers: int) -> Mapping[str, Any]:
        result = self._client.read_all(
            METADATA_OPERATION_ID,
            {"app_id": app_id, "page": 1, "page_size": 100},
            max_pages=1_000,
            max_items=100_000,
            max_workers=max_workers,
        )
        if not _successful(result):
            raise ContractChangedError(
                "user-property metadata is unavailable for aggregate field governance"
            )
        _source_rows(result)
        return result


def _field_catalog(schema: Mapping[str, Any], metadata: Mapping[str, Any]) -> _FieldCatalog:
    allowed = _schema_scalar_fields(schema)
    numeric: set[str] = set()
    for row in _source_rows(metadata):
        safe_names, numeric_names = _metadata_scalar_fields(row)
        allowed.update(safe_names)
        numeric.update(numeric_names)
    return _FieldCatalog(allowed, numeric)


def _schema_scalar_fields(schema: Mapping[str, Any]) -> set[str]:
    projection = schema.get("response_projection")
    if not isinstance(projection, Mapping):
        raise ContractChangedError("user-detail response schema is unavailable")
    item_keys = projection.get("item_keys")
    nested = projection.get("nested_item_keys", {})
    if not isinstance(item_keys, (list, tuple)) or not isinstance(nested, Mapping):
        raise ContractChangedError("user-detail response field schema changed")
    return {
        item
        for item in item_keys
        if isinstance(item, str)
        and item not in nested
        and not _privacy_excluded(item)
    }


def _metadata_scalar_fields(
    row: Mapping[str, Any],
) -> tuple[set[str], set[str]]:
    name, data_type = row.get("name"), row.get("data_type")
    normalized_type = data_type.upper() if isinstance(data_type, str) else ""
    if (
        not isinstance(name, str)
        or not name
        or len(name) > 256
        or normalized_type not in _SCALAR_METADATA_TYPES
    ):
        return set(), set()
    wire_names = {name, f"user{name}"}
    safe_names = {item for item in wire_names if not _privacy_excluded(item)}
    numeric = safe_names if normalized_type in _NUMERIC_METADATA_TYPES else set()
    return safe_names, numeric


def _privacy_excluded(field: str) -> bool:
    compact = "".join(character for character in field.casefold() if character.isalnum())
    return (
        compact in _DIRECT_IDENTIFIERS
        or is_direct_personal_response_field(field)
        or is_sensitive_analysis_field(field)
        or compact.startswith("bytedancemid")
    )


def _validate_fields(inputs: Mapping[str, Any], catalog: _FieldCatalog) -> None:
    missing = sorted(referenced_fields(inputs) - catalog.allowed)
    nonnumeric = sorted(numeric_measure_fields(inputs) - catalog.numeric)
    if missing or nonnumeric:
        raise AggregateFieldUnsupportedError(
            "aggregate field is not an allowlisted scalar field with the required registered type",
            field="fields",
            next_action=(
                "Use contracted user-detail scalar fields; sum requires numeric "
                "user-property metadata."
            ),
        )


def _validate_source_envelope(value: Any) -> None:
    if not isinstance(value, Mapping):
        raise ContractChangedError("user-detail aggregate source envelope changed")
    if not _successful(value):
        code = value.get("error", {}).get("code") if isinstance(value.get("error"), Mapping) else None
        raise ContractChangedError(
            "user-detail aggregate source read failed",
            code=code if code == ErrorCode.CONTRACT_CHANGED.value else ErrorCode.UPSTREAM_UNAVAILABLE,
        )
    if value.get("operation_id") != SOURCE_OPERATION_ID:
        raise ContractChangedError("user-detail aggregate source identity changed")


def _successful(value: Any) -> bool:
    return (
        isinstance(value, Mapping)
        and value.get("ok") is not False
        and value.get("status") in {"success", "empty"}
    )


def _source_rows(value: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    data = value.get("data")
    rows = data.get("list") if isinstance(data, Mapping) else None
    if not isinstance(rows, list) or any(not isinstance(row, Mapping) for row in rows):
        raise ContractChangedError("aggregate source no longer returns a row list")
    return rows


def _validate_row_types(
    rows: Sequence[Mapping[str, Any]],
    inputs: Mapping[str, Any],
) -> None:
    observed = _observed_row_types(rows, referenced_fields(inputs))
    if any(len(types) > 1 for types in observed.values()):
        raise _mixed_type_error()
    if any(observed[field] - {"number"} for field in numeric_measure_fields(inputs)):
        raise _mixed_type_error()
    _validate_condition_types(observed, _all_conditions(inputs))


def _observed_row_types(
    rows: Sequence[Mapping[str, Any]], fields: Sequence[str] | frozenset[str]
) -> dict[str, set[str]]:
    observed = {field: set() for field in fields}
    for row in rows:
        for field, types in observed.items():
            value = row.get(field)
            if value is None:
                continue
            kind = _scalar_kind(value)
            if kind is None:
                raise _mixed_type_error()
            types.add(kind)
    return observed


def _validate_condition_types(
    observed: Mapping[str, set[str]], conditions: Sequence[Mapping[str, Any]]
) -> None:
    for condition in conditions:
        types = observed[condition["field"]]
        value_types = {
            kind
            for value in condition["values"]
            if value is not None and (kind := _scalar_kind(value)) is not None
        }
        if types and value_types and types != value_types:
            raise _mixed_type_error()


def _mixed_type_error() -> AggregateMixedTypeError:
    return AggregateMixedTypeError(
        "aggregate input rows contain inconsistent or non-scalar field types",
        field="source.data.list",
        next_action=(
            "Stop using this aggregate until the user-detail field type is stable "
            "and its metadata contract is corrected."
        ),
    )


def _scalar_kind(value: Any) -> str | None:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int) and value.bit_length() <= 13_607:
        return "number"
    if isinstance(value, float):
        return "number" if math.isfinite(value) else None
    if isinstance(value, str) and len(value) <= 4_096:
        return "string"
    return None


def _all_conditions(inputs: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    result = list(inputs["filters"])
    result.extend(
        item["condition"]
        for item in inputs["measures"]
        if item["op"] == "count_if"
    )
    return result


def _aggregate_cells(
    rows: Sequence[Mapping[str, Any]], inputs: Mapping[str, Any]
) -> list[dict[str, Any]]:
    groups: dict[tuple[tuple[str, Any], ...], dict[str, Any]] = {}
    if not inputs["group_by"]:
        groups[()] = _new_group({}, inputs["measures"])
    for row in rows:
        if not all(_matches(row.get(item["field"]), item) for item in inputs["filters"]):
            continue
        values = {field: copy.deepcopy(row.get(field)) for field in inputs["group_by"]}
        key = tuple(_key_part(values[field]) for field in inputs["group_by"])
        if key not in groups:
            if (len(groups) + 1) * len(inputs["measures"]) > inputs["bounds"]["max_cells"]:
                raise AggregateCardinalityError(
                    "aggregate grouping exceeds the explicit cell bound",
                    field="bounds.max_cells",
                    next_action="Reduce group_by cardinality or request fewer measures.",
                )
            groups[key] = _new_group(values, inputs["measures"])
        _accumulate(groups[key], row, inputs["measures"])
    return _flatten_cells(groups, inputs["measures"])


def _new_group(values: Mapping[str, Any], measures: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "group": dict(values),
        "values": {
            item["name"]: Decimal(0) if item["op"] == "sum" else 0
            for item in measures
        },
        "float_sums": set(),
    }


def _accumulate(
    group: dict[str, Any], row: Mapping[str, Any], measures: Sequence[Mapping[str, Any]]
) -> None:
    for measure in measures:
        name, operation = measure["name"], measure["op"]
        if operation == "count":
            group["values"][name] += 1
        elif operation == "count_if":
            if _matches(row.get(measure["condition"]["field"]), measure["condition"]):
                group["values"][name] += 1
        else:
            value = row.get(measure["field"])
            if value is not None:
                group["values"][name] += Decimal(str(value))
                if isinstance(value, float):
                    group["float_sums"].add(name)


def _flatten_cells(
    groups: Mapping[tuple[tuple[str, Any], ...], Mapping[str, Any]],
    measures: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    cells: list[dict[str, Any]] = []
    ordered = sorted(
        groups.values(),
        key=lambda item: json.dumps(
            item["group"], ensure_ascii=True, sort_keys=True, separators=(",", ":")
        ),
    )
    for group in ordered:
        for measure in measures:
            value = group["values"][measure["name"]]
            if isinstance(value, Decimal):
                value = float(value) if measure["name"] in group["float_sums"] else int(value)
                if isinstance(value, float) and not math.isfinite(value):
                    raise _mixed_type_error()
            cells.append(
                {
                    "group": copy.deepcopy(group["group"]),
                    "measure": measure["name"],
                    "value": value,
                }
            )
    return cells


def _matches(value: Any, condition: Mapping[str, Any]) -> bool:
    operator, values = condition["operator"], condition["values"]
    if operator == "WITH_VAL":
        return value is not None
    if operator == "WITHOUT_VAL":
        return value is None
    if operator == "EQUALS":
        return _typed_equal(value, values[0])
    if operator == "NOT_EQUALS":
        return not _typed_equal(value, values[0])
    if operator == "IN":
        return any(_typed_equal(value, item) for item in values)
    if operator == "NOT_IN":
        return all(not _typed_equal(value, item) for item in values)
    if value is None:
        return False
    target = values[0]
    return {
        "GT": value > target,
        "GTE": value >= target,
        "LT": value < target,
        "LTE": value <= target,
    }[operator]


def _typed_equal(left: Any, right: Any) -> bool:
    if left is None or right is None:
        return left is right
    return _scalar_kind(left) == _scalar_kind(right) and left == right


def _key_part(value: Any) -> tuple[str, Any]:
    return ("null", None) if value is None else (str(_scalar_kind(value)), value)


def _result(
    inputs: Mapping[str, Any],
    source: Mapping[str, Any],
    metadata: Mapping[str, Any],
    source_inputs: Mapping[str, Any],
    cells: Sequence[Mapping[str, Any]],
    consumed_items: int,
) -> dict[str, Any]:
    page = source.get("page") if isinstance(source.get("page"), Mapping) else {}
    completeness = source.get("completeness")
    completeness = completeness if completeness in {"complete", "prefix", "unknown"} else "unknown"
    allowed, forbidden = collection_claims(completeness)
    return {
        "schema_version": RESULT_SCHEMA_VERSION,
        "input_schema_version": INPUT_SCHEMA_VERSION,
        "result_source": result_source(GOVERNED_PRODUCT),
        "ok": True,
        "status": "empty" if consumed_items == 0 else "success",
        "exit_code": 0,
        "operation_id": PRODUCT_OPERATION_ID,
        "query": {
            "filters": copy.deepcopy(inputs["filters"]),
            "group_by": list(inputs["group_by"]),
            "measures": metric_definitions(inputs),
            "bounds": dict(inputs["bounds"]),
        },
        "cells": [copy.deepcopy(dict(item)) for item in cells],
        "cell_count": len(cells),
        "group_count": len({json.dumps(item["group"], sort_keys=True) for item in cells}),
        "pagination": {
            "completeness": completeness,
            "pagination_evidence": source.get("pagination_evidence", "none"),
            "consumed_pages": page.get("pages_fetched"),
            "consumed_items": consumed_items,
            "source_total_pages": page.get("total_pages"),
            "source_total_items": page.get("total_items"),
            "fetch_strategy": page.get("fetch_strategy"),
            "claims": {"allowed": allowed, "forbidden": forbidden},
        },
        "source": {
            "operation_id": SOURCE_OPERATION_ID,
            "schema_version": source.get("schema_version"),
            "contract_version": source.get("contract_version"),
            "schema_fingerprint": source.get("schema_fingerprint"),
            "contract_fingerprint": _contract_fingerprint(source),
            "field_catalog": {
                "operation_id": METADATA_OPERATION_ID,
                "schema_version": metadata.get("schema_version"),
                "contract_version": metadata.get("contract_version"),
                "schema_fingerprint": metadata.get("schema_fingerprint"),
                "contract_fingerprint": _contract_fingerprint(metadata),
            },
        },
        "pagination_audit": pagination_audit(source, source_inputs, all_pages=True),
    }


def _contract_fingerprint(value: Mapping[str, Any]) -> Any:
    source = value.get("source")
    return source.get("contract_fingerprint") if isinstance(source, Mapping) else None


def _workers(value: Any) -> None:
    if type(value) is not int or not 1 <= value <= 24:
        from .errors import InputValidationError

        raise InputValidationError(
            "max_workers must be between 1 and 24", field="max_workers"
        )


__all__ = ["UserDetailAggregateService"]
