"""Multidimensional metadata validation and query orchestration.

This module owns the live portion of the Multidim vertical. Product input
normalization lives in :mod:`gravity_sdk.multidim_product`; the lower-level
``CompositeService`` delegates here for exact operation-oriented callers.
"""

from __future__ import annotations

import inspect
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Mapping, Protocol, Sequence

from .cache import is_metadata_operation
from .composite_batch import validate_composite_bounds
from .composite_result import multidim_envelope
from ._field_policy_operations import (
    REPORT_MULTIDIM_CUSTOM_METRIC,
    REPORT_MULTIDIM_METRIC,
    REPORT_MULTIDIM_QUERY,
    REPORT_MULTIDIM_SHARED_METRIC,
    REPORT_MULTIDIM_TOTAL,
)
from .errors import (
    ContractChangedError,
    GravityInsightError,
    InputValidationError,
    PaginationError,
    PolicyViolation,
)
from .actionable_error_values import actual_value


MULTIDIM_QUERY_OPERATION = REPORT_MULTIDIM_QUERY
MULTIDIM_TOTAL_OPERATION = REPORT_MULTIDIM_TOTAL
STANDARD_METRIC_OPERATION = REPORT_MULTIDIM_METRIC
CUSTOM_METRIC_OPERATIONS = (
    REPORT_MULTIDIM_CUSTOM_METRIC,
    REPORT_MULTIDIM_SHARED_METRIC,
)
MAX_MULTIDIM_WORKERS = 24
_SUCCESS_RESULT_STATUSES = frozenset({"success", "empty"})
_FAILURE_RESULT_STATUSES = frozenset(
    {
        "contract_changed",
        "contract_changed_additive",
        "semantic_error",
        "error",
        "unavailable",
        "parent_required",
        "permission_unavailable",
    }
)
_KNOWN_RESULT_STATUSES = _SUCCESS_RESULT_STATUSES | _FAILURE_RESULT_STATUSES


class _PublicClient(Protocol):
    def schema(self, operation_id: str | None = None) -> dict[str, object]: ...

    def read(
        self, operation_id: str, inputs: Mapping[str, Any] | None = None
    ) -> dict[str, Any]: ...

    def read_all(
        self,
        operation_id: str,
        inputs: Mapping[str, Any] | None = None,
        *,
        max_pages: int = 1_000,
        max_items: int = 100_000,
        max_workers: int = 6,
    ) -> dict[str, Any]: ...


class MultidimService:
    """Validate live metric metadata, then execute one bounded query."""

    def __init__(self, client: _PublicClient) -> None:
        required = ("schema", "read", "read_all")
        if any(not callable(getattr(client, name, None)) for name in required):
            raise TypeError("MultidimService requires the public GravityInsightClient facade")
        self._client = client

    def query(
        self,
        inputs: Mapping[str, Any],
        *,
        include_total: bool = False,
        read_all: bool = False,
        metadata_inputs: Mapping[str, Mapping[str, Any]] | None = None,
        max_pages: int = 1_000,
        max_items: int = 100_000,
        max_workers: int = 6,
    ) -> dict[str, Any]:
        if not isinstance(inputs, Mapping):
            raise InputValidationError(
                "multidimensional inputs must be an object",
                field="inputs",
            )
        if metadata_inputs is not None and not isinstance(metadata_inputs, Mapping):
            raise InputValidationError(
                f"actual value: {actual_value(metadata_inputs)}; " + ("multidimensional metadata_inputs must be an object"),
                field="metadata_inputs",
            )
        _boolean(include_total, "include_total")
        _boolean(read_all, "read_all")
        pages, items = validate_composite_bounds(max_pages, max_items, minimum_items=1)
        workers = _workers(max_workers)
        supplied = dict(inputs)
        validation = self.validate(
            supplied,
            metadata_inputs or {},
            max_workers=workers,
        )
        query = (
            self._client.read_all(
                MULTIDIM_QUERY_OPERATION,
                supplied,
                max_pages=pages,
                max_items=items,
                max_workers=workers,
            )
            if read_all
            else self._client.read(MULTIDIM_QUERY_OPERATION, supplied)
        )
        _validate_result_component(
            query,
            operation_id=MULTIDIM_QUERY_OPERATION,
            label="query",
        )
        if query["status"] in _SUCCESS_RESULT_STATUSES:
            _enforce_query_item_budget(query, items)
        total: dict[str, Any] | None = None
        if include_total and query["status"] == "success":
            calc_schema = self._client.schema(MULTIDIM_TOTAL_OPERATION)
            input_schema = calc_schema.get("input_fields", {})
            if not isinstance(input_schema, Mapping) or "data_list" not in input_schema:
                raise PolicyViolation(
                    "the registered calc-total contract does not accept data_list"
                )
            allowed = set(str(key) for key in input_schema)
            calc_inputs = {key: value for key, value in supplied.items() if key in allowed}
            calc_inputs["data_list"] = _rows(query)
            total = self._client.read(MULTIDIM_TOTAL_OPERATION, calc_inputs)
            _validate_result_component(
                total,
                operation_id=MULTIDIM_TOTAL_OPERATION,
                label="total",
            )
        return multidim_envelope(
            validation,
            query,
            total,
            query_operation=MULTIDIM_QUERY_OPERATION,
            total_operation=MULTIDIM_TOTAL_OPERATION,
        )

    def validate(
        self,
        inputs: Mapping[str, Any],
        metadata_inputs: Mapping[str, Mapping[str, Any]],
        *,
        max_workers: int,
    ) -> dict[str, Any]:
        metrics = _string_values(inputs.get("metrics_list", []), "metrics_list")
        custom_metrics = _string_values(
            inputs.get("custom_metrics_list", []), "custom_metrics_list"
        )
        data_dims = _string_values(inputs.get("data_dims", []), "data_dims")
        relate_dims = _string_values(inputs.get("relate_dims", []), "relate_dims")
        dimensions = [*data_dims, *relate_dims]
        if not metrics and not custom_metrics:
            return _no_metric_validation(dimensions)

        requested_operations = (
            ((STANDARD_METRIC_OPERATION,) if metrics else ())
            + (CUSTOM_METRIC_OPERATIONS if custom_metrics else ())
        )
        sources = self._load_metric_sources(
            requested_operations,
            metadata_inputs,
            max_workers=max_workers,
        )
        selected_rows = _selected_metric_rows(metrics, custom_metrics, sources)
        _validate_exclusions(selected_rows, dimensions)
        return {
            "status": "validated" if not dimensions else "validated_exclusions_only",
            "metrics": "validated_live",
            "data_dims": "exclusion_checked" if dimensions else "not_requested",
            "metrics_checked": len(selected_rows),
            "data_dims_checked": len(dimensions),
            "metadata_operations": list(sources),
        }

    def _load_metric_sources(
        self,
        operation_ids: Sequence[str],
        metadata_inputs: Mapping[str, Mapping[str, Any]],
        *,
        max_workers: int,
    ) -> dict[str, list[Mapping[str, Any]]]:
        def load(
            assignment: tuple[str, int],
        ) -> tuple[str, list[Mapping[str, Any]]] | None:
            operation_id, operation_workers = assignment
            try:
                schema = self._client.schema(operation_id)
                if not is_metadata_operation(schema):
                    return None
                options = _read_all_worker_option(
                    self._client.read_all, operation_workers
                )
                envelope = self._client.read_all(
                    operation_id,
                    dict(metadata_inputs.get(operation_id, {})),
                    **options,
                )
            except (GravityInsightError, KeyError, TypeError, ValueError):
                return None
            if envelope.get("status") not in {"success", "empty"}:
                return None
            return operation_id, [
                item for item in _rows(envelope) if isinstance(item, Mapping)
            ]

        selected = list(dict.fromkeys(operation_ids))
        source_workers = min(max_workers, len(selected))
        assignments = list(
            zip(selected, _worker_shares(max_workers, len(selected)), strict=True)
        )
        if source_workers <= 1:
            loaded = [load(assignment) for assignment in assignments]
        else:
            with ThreadPoolExecutor(
                max_workers=source_workers,
                thread_name_prefix="gravity-metadata",
            ) as pool:
                loaded = list(pool.map(load, assignments))
        return {operation_id: rows for item in loaded if item for operation_id, rows in (item,)}


def _read_all_worker_option(read_all: Any, max_workers: int) -> dict[str, int]:
    parameters = inspect.signature(read_all).parameters
    supports_workers = "max_workers" in parameters or any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD
        for parameter in parameters.values()
    )
    return {"max_workers": max_workers} if supports_workers else {}


def _worker_shares(max_workers: int, source_count: int) -> list[int]:
    if source_count <= 0:
        return []
    if max_workers < source_count:
        return [1] * source_count
    base, remainder = divmod(max_workers, source_count)
    return [base + (index < remainder) for index in range(source_count)]


def _select_metrics(
    rows: Sequence[Mapping[str, Any]], requested: Sequence[str], label: str
) -> list[Mapping[str, Any]]:
    by_identifier: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        for key in ("id", "name", "cname", "label"):
            value = row.get(key)
            if isinstance(value, (str, int)) and not isinstance(value, bool):
                by_identifier[str(value)] = row
    missing = [item for item in requested if item not in by_identifier]
    if missing:
        raise InputValidationError(
            f"{label} must use values present in live metadata (count={len(missing)}); "
            "run `gravity metadata properties \"\"` and retry with listed names",
            field=label,
        )
    return [by_identifier[item] for item in requested]


def _selected_metric_rows(
    metrics: Sequence[str],
    custom_metrics: Sequence[str],
    sources: Mapping[str, Sequence[Mapping[str, Any]]],
) -> list[Mapping[str, Any]]:
    selected: list[Mapping[str, Any]] = []
    if metrics:
        standard_rows = sources.get(STANDARD_METRIC_OPERATION, ())
        if not standard_rows:
            raise _metadata_unavailable(
                field="metrics_list",
                next_action='Run `gravity metadata properties ""` then retry.',
            )
        selected.extend(_select_metrics(standard_rows, metrics, "metrics_list"))
    if custom_metrics:
        custom_rows = [
            row
            for operation_id in CUSTOM_METRIC_OPERATIONS
            for row in sources.get(operation_id, ())
        ]
        if not custom_rows:
            raise _metadata_unavailable(
                field="custom_metrics_list",
                next_action='Run `gravity metadata properties ""` then retry.',
            )
        selected.extend(
            _select_metrics(custom_rows, custom_metrics, "custom_metrics_list")
        )
    return selected


def _validate_exclusions(
    selected_rows: Sequence[Mapping[str, Any]], data_dims: Sequence[str]
) -> None:
    excluded: set[str] = set()
    incomplete = False
    for row in selected_rows:
        exclusion_dims = row.get("exclusion_dims")
        if "exclusion_dims" not in row or (
            exclusion_dims not in (None, "")
            and (
                not isinstance(exclusion_dims, (list, tuple))
                or any(not isinstance(item, str) for item in exclusion_dims)
            )
        ):
            incomplete = True
            continue
        if isinstance(exclusion_dims, (list, tuple)):
            excluded.update(exclusion_dims)
    if data_dims and incomplete:
        raise InputValidationError(
            "live metric metadata must include exclusion_dims before data_dims can be sent; "
            "run `gravity metadata properties \"\"` and retry",
            field="data_dims",
        )
    if set(data_dims) & excluded:
        raise InputValidationError(
            "selected data_dims must not overlap live metric exclusion_dims; remove the excluded names",
            field="data_dims",
        )


def _no_metric_validation(data_dims: Sequence[str]) -> dict[str, Any]:
    if data_dims:
        raise InputValidationError(
            "data_dims must be paired with selected metrics before live validation; "
            "add metrics_list or custom_metrics_list, then retry",
            field="data_dims",
        )
    return {
        "status": "not_required",
        "metrics": "not_requested",
        "data_dims": "not_validated_without_selected_metrics",
        "metadata_operations": [],
    }


def _rows(envelope: Mapping[str, Any]) -> list[Any]:
    data = envelope.get("data")
    if isinstance(data, list):
        return list(data)
    if isinstance(data, Mapping):
        for key in ("list", "items"):
            value = data.get(key)
            if isinstance(value, list):
                return list(value)
    return []


def _query_item_count(envelope: Mapping[str, Any]) -> int:
    counts = [len(_rows(envelope))]
    page = envelope.get("page")
    if isinstance(page, Mapping):
        count = page.get("item_count")
        if isinstance(count, int) and not isinstance(count, bool) and count >= 0:
            counts.append(count)
    return max(counts)


def _validate_result_component(
    envelope: Any, *, operation_id: str, label: str
) -> None:
    if not isinstance(envelope, Mapping):
        raise ContractChangedError(
            f"multidimensional {label} returned an invalid envelope"
        )
    status = envelope.get("status")
    if not isinstance(status, str) or status not in _KNOWN_RESULT_STATUSES:
        raise ContractChangedError(
            f"multidimensional {label} returned an unknown status"
        )
    identity = envelope.get("operation_id")
    if identity is not None and identity != operation_id:
        raise ContractChangedError(
            f"multidimensional {label} operation identity changed"
        )
    if status not in _SUCCESS_RESULT_STATUSES:
        if envelope.get("ok") is True:
            raise ContractChangedError(
                f"multidimensional {label} failure has a success marker"
            )
        return
    if envelope.get("ok") is False:
        raise ContractChangedError(
            f"multidimensional {label} success has a failure marker"
        )
    data = envelope.get("data")
    rows = data.get("list") if isinstance(data, Mapping) else None
    if not isinstance(rows, list) or any(not isinstance(row, Mapping) for row in rows):
        raise ContractChangedError(
            f"multidimensional {label} no longer returns mapped data.list rows"
        )
    if status == "empty" and rows:
        raise ContractChangedError(
            f"multidimensional {label} empty status contains rows"
        )


def _enforce_query_item_budget(envelope: Mapping[str, Any], max_items: int) -> None:
    if _query_item_count(envelope) > max_items:
        raise PaginationError("multidimensional query exceeded its item safety bound")


def _string_values(value: Any, label: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, (list, tuple)) or any(
        not isinstance(item, str) for item in value
    ):
        raise InputValidationError(
            f"{label} must be a list of strings",
            field=label,
        )
    return list(value)


def _workers(value: Any) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 1 <= value <= MAX_MULTIDIM_WORKERS
    ):
        raise InputValidationError(
            f"actual value: {actual_value(value)}; " + (f"max_workers must be between 1 and {MAX_MULTIDIM_WORKERS}"),
            field="max_workers",
        )
    return value


def _boolean(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise InputValidationError(f"actual value: {actual_value(value)}; " + (f"{field} must be boolean"), field=field)
    return value


def _metadata_unavailable(*, field: str, next_action: str) -> InputValidationError:
    return InputValidationError(
        "live metric metadata is unavailable; run `gravity metadata properties \"\"` then retry; multidimensional query was not executed",
        field=field,
        next_action=next_action,
    )


__all__ = [
    "CUSTOM_METRIC_OPERATIONS",
    "MAX_MULTIDIM_WORKERS",
    "MULTIDIM_QUERY_OPERATION",
    "MULTIDIM_TOTAL_OPERATION",
    "MultidimService",
    "STANDARD_METRIC_OPERATION",
]
