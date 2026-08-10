"""Read-only orchestration built exclusively on the public client facade."""

from __future__ import annotations

from typing import Any, Mapping, Protocol, Sequence

from .cache import is_metadata_operation
from .errors import GravityInsightError, InputValidationError, PolicyViolation


MULTIDIM_QUERY_OPERATION = "report.multidim.query"
MULTIDIM_TOTAL_OPERATION = "report.multidim.calc_total"
STANDARD_METRIC_OPERATION = "report.multidim.metric.list"
CUSTOM_METRIC_OPERATIONS = (
    "report.multidim.custom_metric.list",
    "report.multidim.custom_metric.shared.list",
)
_PROMOTION_PRIMARY_RESOURCES = {
    "ubix": "group",
    "taptap": "group",
    "wechat_video": "report",
}


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
    ) -> dict[str, Any]:
        if not isinstance(inputs, Mapping):
            raise InputValidationError("multidimensional inputs must be an object")
        supplied = dict(inputs)
        validation = self._validate_multidim(supplied, metadata_inputs or {})
        query = (
            self._client.read_all(MULTIDIM_QUERY_OPERATION, supplied)
            if read_all
            else self._client.read(MULTIDIM_QUERY_OPERATION, supplied)
        )
        total: dict[str, Any] | None = None
        if include_total and query.get("status") not in {"contract_changed", "error"}:
            calc_schema = self._client.schema(MULTIDIM_TOTAL_OPERATION)
            input_schema = calc_schema.get("input_fields", {})
            if not isinstance(input_schema, Mapping) or "data_list" not in input_schema:
                raise PolicyViolation("the registered calc-total contract does not accept data_list")
            allowed = set(str(key) for key in input_schema)
            calc_inputs = {key: value for key, value in supplied.items() if key in allowed}
            calc_inputs["data_list"] = _rows(query)
            total = self._client.read(MULTIDIM_TOTAL_OPERATION, calc_inputs)
        statuses = [str(query.get("status", "error"))]
        if total is not None:
            statuses.append(str(total.get("status", "error")))
        return {
            "schema_version": "gravity-insight.composite.multidim.v1",
            "status": _combined_status(statuses),
            "validation": validation,
            "query": query,
            "total": total,
        }

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
        selected_platforms = list(dict.fromkeys(_operation_ids(platforms)))
        if not selected_platforms:
            raise InputValidationError("promotion snapshot requires at least one platform")
        if not isinstance(resource, str) or not resource:
            raise InputValidationError("promotion snapshot resource must be a non-empty string")
        platform_inputs = dict(inputs_by_platform or {})
        if set(platform_inputs) - set(selected_platforms):
            raise InputValidationError("promotion inputs reference an unselected platform")
        shared = dict(common_inputs or {})
        requests: list[dict[str, Any]] = []
        unavailable: list[dict[str, Any]] = []
        selected_resources: dict[str, str] = {}
        for platform in selected_platforms:
            selected_resource = (
                _PROMOTION_PRIMARY_RESOURCES.get(platform, "advertiser")
                if resource == "primary"
                else resource
            )
            selected_resources[platform] = selected_resource
            matches = [
                item
                for item in self._client.operations(
                    domain="promotion", platform=platform, stability="stable"
                )
                if item.get("resource") == selected_resource
                and item.get("action") in {"list", "query"}
            ]
            if not matches:
                unavailable.append(
                    {
                        "operation_id": None,
                        "platform": platform,
                        "resource": selected_resource,
                        "ok": False,
                        "status": "unavailable",
                        "data": None,
                        "error": "no stable read operation is registered for this platform/resource",
                    }
                )
                continue
            operation = sorted(matches, key=lambda item: str(item["operation_id"]))[0]
            operation_id = str(operation["operation_id"])
            operation_inputs = dict(shared)
            operation_inputs.update(platform_inputs.get(platform, {}))
            requests.append(
                {
                    "request_id": platform,
                    "operation_id": operation_id,
                    "inputs": operation_inputs,
                    "read_all": read_all,
                }
            )
        completed = self._client.batch(requests, max_workers=max_workers) if requests else []
        results: list[dict[str, Any]] = []
        by_platform = {
            str(item.get("request_id")): {
                **item,
                "platform": str(item.get("request_id")),
                "resource": selected_resources.get(str(item.get("request_id"))),
            }
            for item in completed
        }
        unavailable_by_platform = {str(item["platform"]): item for item in unavailable}
        for platform in selected_platforms:
            results.append(
                by_platform.get(platform)
                or unavailable_by_platform.get(platform)
                or {
                    "operation_id": None,
                    "platform": platform,
                    "resource": selected_resources[platform],
                    "ok": False,
                    "status": "error",
                    "data": None,
                    "error": "the batch did not return a result for this platform",
                }
            )
        return {
            "schema_version": "gravity-insight.composite.promotion.v1",
            "status": _batch_status(results),
            "resource": resource,
            "coverage": _batch_coverage(len(selected_platforms), results),
            "results": results,
        }

    def _validate_multidim(
        self,
        inputs: Mapping[str, Any],
        metadata_inputs: Mapping[str, Mapping[str, Any]],
    ) -> dict[str, Any]:
        metrics = _string_values(inputs.get("metrics_list", []), "metrics_list")
        custom_metrics = _string_values(
            inputs.get("custom_metrics_list", []), "custom_metrics_list"
        )
        data_dims = _string_values(inputs.get("data_dims", []), "data_dims")
        if not metrics and not custom_metrics:
            if data_dims:
                raise InputValidationError(
                    "data_dims cannot be live-validated without selected metrics; query was not executed"
                )
            return {
                "status": "not_required",
                "metrics": "not_requested",
                "data_dims": "not_validated_without_selected_metrics",
                "metadata_operations": [],
            }

        selected_rows: list[Mapping[str, Any]] = []
        used_operations: list[str] = []
        if metrics:
            rows, verified_operations = self._load_metric_rows(
                (STANDARD_METRIC_OPERATION,), metadata_inputs, required=True
            )
            selected_rows.extend(_select_metrics(rows, metrics, "metrics_list"))
            used_operations.extend(verified_operations)
        if custom_metrics:
            rows, verified_operations = self._load_metric_rows(
                CUSTOM_METRIC_OPERATIONS, metadata_inputs, required=True
            )
            selected_rows.extend(_select_metrics(rows, custom_metrics, "custom_metrics_list"))
            used_operations.extend(verified_operations)

        excluded: set[str] = set()
        incomplete_exclusions = False
        for row in selected_rows:
            if "exclusion_dims" not in row:
                incomplete_exclusions = True
                continue
            exclusion_dims = row.get("exclusion_dims")
            if exclusion_dims in (None, ""):
                continue
            if not isinstance(exclusion_dims, (list, tuple)):
                incomplete_exclusions = True
                continue
            if any(not isinstance(item, str) for item in exclusion_dims):
                incomplete_exclusions = True
                continue
            excluded.update(item for item in exclusion_dims if isinstance(item, str))
        if data_dims and incomplete_exclusions:
            raise InputValidationError(
                "live metric metadata is incomplete; data_dims were not sent upstream"
            )
        if set(data_dims) & excluded:
            raise InputValidationError(
                "selected data_dims conflict with live metric exclusion metadata"
            )
        return {
            "status": "validated" if not data_dims else "validated_exclusions_only",
            "metrics": "validated_live",
            "data_dims": "exclusion_checked" if data_dims else "not_requested",
            "metrics_checked": len(selected_rows),
            "data_dims_checked": len(data_dims),
            "metadata_operations": list(dict.fromkeys(used_operations)),
        }

    def _load_metric_rows(
        self,
        operation_ids: Sequence[str],
        metadata_inputs: Mapping[str, Mapping[str, Any]],
        *,
        required: bool,
    ) -> tuple[list[Mapping[str, Any]], list[str]]:
        rows: list[Mapping[str, Any]] = []
        successful = False
        verified_operations: list[str] = []
        for operation_id in operation_ids:
            try:
                schema = self._client.schema(operation_id)
                if not is_metadata_operation(schema):
                    continue
                envelope = self._client.read_all(
                    operation_id, dict(metadata_inputs.get(operation_id, {}))
                )
            except (GravityInsightError, KeyError, TypeError, ValueError):
                continue
            if envelope.get("status") == "contract_changed":
                continue
            if envelope.get("status") in {"success", "empty"}:
                successful = True
                verified_operations.append(operation_id)
                rows.extend(item for item in _rows(envelope) if isinstance(item, Mapping))
        if required and (not successful or not rows):
            raise InputValidationError(
                "live metric metadata is unavailable; multidimensional query was not executed"
            )
        return rows, verified_operations


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
            f"{label} contains values absent from live metadata (count={len(missing)})"
        )
    return [by_identifier[item] for item in requested]


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


def _string_values(value: Any, label: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, (list, tuple)) or any(not isinstance(item, str) for item in value):
        raise InputValidationError(f"{label} must be a list of strings")
    return list(value)


def _operation_ids(values: Sequence[str]) -> list[str]:
    if isinstance(values, (str, bytes)) or any(not isinstance(item, str) or not item for item in values):
        raise InputValidationError("operation/platform identifiers must be non-empty strings")
    return list(values)


def _combined_status(statuses: Sequence[str]) -> str:
    if any(
        status
        in {
            "error",
            "semantic_error",
            "unavailable",
            "parent_required",
            "permission_unavailable",
        }
        for status in statuses
    ):
        return "partial" if any(status in {"success", "empty", "contract_changed"} for status in statuses) else "error"
    if any(status == "contract_changed" for status in statuses):
        return "contract_changed"
    if statuses and all(status == "empty" for status in statuses):
        return "empty"
    return "success"


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
