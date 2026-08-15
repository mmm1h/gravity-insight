"""Read-only orchestration built exclusively on the public client facade."""

from __future__ import annotations

from typing import Any, Mapping, Protocol, Sequence

from .cache import is_metadata_operation
from .composite_result import combined_status as _combined_status
from .errors import InputValidationError, PolicyViolation
from .multidim_service import (
    CUSTOM_METRIC_OPERATIONS,
    MULTIDIM_QUERY_OPERATION,
    MULTIDIM_TOTAL_OPERATION,
    STANDARD_METRIC_OPERATION,
    MultidimService,
)
from .result_source import RAW_OPERATION, result_source


class _PublicClient(Protocol):
    def operations(
        self,
        *,
        domain: str | None = None,
        platform: str | None = None,
        stability: str | None = "stable",
        include_probe_metadata: bool = True,
    ) -> list[dict[str, object]]: ...

    def schema(self, operation_id: str | None = None) -> dict[str, object]: ...

    def read(self, operation_id: str, inputs: Mapping[str, Any] | None = None) -> dict[str, Any]: ...

    def read_all(
        self,
        operation_id: str,
        inputs: Mapping[str, Any] | None = None,
        *,
        max_pages: int = 1_000,
        max_items: int = 100_000,
        max_workers: int = 6,
    ) -> dict[str, Any]: ...

    def batch(
        self,
        requests: Sequence[Mapping[str, Any]],
        *,
        max_workers: int = 6,
        fail_fast: bool = False,
    ) -> list[dict[str, Any]]: ...


class CompositeService:
    """Compose safe reads without direct registry, executor, or transport access."""

    def __init__(self, client: _PublicClient) -> None:
        required = ("operations", "schema", "read", "read_all", "batch")
        if any(not callable(getattr(client, name, None)) for name in required):
            raise TypeError("CompositeService requires the public GravityInsightClient facade")
        self._client = client

    def metadata_snapshot(
        self,
        operation_ids: Sequence[str] | None = None,
        *,
        inputs_by_operation: Mapping[str, Mapping[str, Any]] | None = None,
        max_workers: int = 6,
    ) -> dict[str, Any]:
        explicit_selection = operation_ids is not None
        inputs_map = dict(inputs_by_operation or {})
        if operation_ids is None:
            operations = self._client.operations(stability="stable")
            selected = sorted(
                str(item["operation_id"])
                for item in operations
                if is_metadata_operation(item)
            )
        else:
            selected = list(dict.fromkeys(_operation_ids(operation_ids)))
        unknown_inputs = set(inputs_map) - set(selected)
        if unknown_inputs:
            raise InputValidationError("metadata inputs reference an unselected operation")
        requests: list[dict[str, Any]] = []
        skipped_input_required: list[dict[str, Any]] = []
        for operation_id in selected:
            schema = self._client.schema(operation_id)
            if not is_metadata_operation(schema):
                raise PolicyViolation("CompositeService metadata reads are restricted to metadata operations")
            operation_inputs = dict(inputs_map.get(operation_id, {}))
            input_fields = schema.get("input_fields", {})
            required_fields = (
                sorted(
                    str(name)
                    for name, field in input_fields.items()
                    if isinstance(field, Mapping)
                    and field.get("required") is True
                    and "default" not in field
                )
                if isinstance(input_fields, Mapping)
                else []
            )
            missing_fields = [name for name in required_fields if name not in operation_inputs]
            if missing_fields:
                if explicit_selection:
                    raise InputValidationError(
                        f"metadata operation {operation_id} requires inputs: "
                        + ", ".join(missing_fields)
                    )
                skipped_input_required.append(
                    {
                        "operation_id": operation_id,
                        "required_fields": missing_fields,
                    }
                )
                continue
            requests.append(
                {
                    "operation_id": operation_id,
                    "inputs": operation_inputs,
                    "request_id": operation_id,
                    "read_all": True,
                }
            )
        results = self._client.batch(requests, max_workers=max_workers) if requests else []
        return {
            "schema_version": "gravity-insight.composite.metadata.v1",
            "result_source": result_source(RAW_OPERATION),
            "status": _batch_status(results),
            "coverage": {
                **_batch_coverage(len(requests), results),
                "discovered": len(selected),
                "skipped_input_required": len(skipped_input_required),
            },
            "skipped_input_required": skipped_input_required,
            "results": results,
        }

    def multidim_query(
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
        return MultidimService(self._client).query(
            inputs,
            include_total=include_total,
            read_all=read_all,
            metadata_inputs=metadata_inputs,
            max_pages=max_pages,
            max_items=max_items,
            max_workers=max_workers,
        )

    def promotion_snapshot(
        self,
        platforms: Sequence[str],
        *,
        resource: str = "primary",
        common_inputs: Mapping[str, Any] | None = None,
        inputs_by_platform: Mapping[str, Mapping[str, Any]] | None = None,
        read_all: bool = False,
        max_workers: int = 6,
    ) -> dict[str, Any]:
        from .promotion_snapshot_compat import promotion_snapshot_compat

        return promotion_snapshot_compat(
            self._client,
            platforms,
            resource=resource,
            common_inputs=common_inputs,
            inputs_by_platform=inputs_by_platform,
            read_all=read_all,
            max_workers=max_workers,
        )

def _operation_ids(values: Sequence[str]) -> list[str]:
    if isinstance(values, (str, bytes)) or any(not isinstance(item, str) or not item for item in values):
        raise InputValidationError("operation/platform identifiers must be non-empty strings")
    return list(values)


def _batch_status(results: Sequence[Mapping[str, Any]]) -> str:
    if not results:
        return "empty"
    statuses = [str(item.get("status", "error")) for item in results]
    successes = sum(bool(item.get("ok")) for item in results)
    if successes == len(results):
        return _combined_status(statuses)
    return "partial" if successes else "unavailable"


def _batch_coverage(requested: int, results: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    successful = sum(bool(item.get("ok")) for item in results)
    unavailable = sum(str(item.get("status")) == "unavailable" for item in results)
    return {
        "requested": requested,
        "completed": len(results),
        "successful": successful,
        "failed": len(results) - successful,
        "unavailable": unavailable,
    }
