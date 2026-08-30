"""Fail-closed loader for export-only route contracts."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import json
from pathlib import Path
from types import MappingProxyType
from typing import Any, Iterable, Mapping

from .errors import InputValidationError, ManifestError, UnknownOperationError
from .export_describe_actions import describe_next_action, describe_workflow
from .export_models import _export_error
from .export_policy import EffectRoute


@dataclass(frozen=True)
class ExportRouteContract:
    operation_id: str
    effect: str
    method: str
    path: str
    contract_status: str
    executable: bool
    block_reason: str | None
    request: Mapping[str, Any]
    response: Mapping[str, Any]
    privacy: Mapping[str, Any]
    verification: Mapping[str, Any]

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ExportRouteContract":
        required = {
            "operation_id",
            "effect",
            "method",
            "path",
            "contract_status",
            "executable",
            "request",
            "response",
            "privacy",
            "verification",
        }
        missing = sorted(required - set(value))
        if missing:
            raise ManifestError(
                "export contract is missing fields: " + ", ".join(missing)
            )
        request = _mapping(value["request"], "request")
        response = _mapping(value["response"], "response")
        privacy = _mapping(value["privacy"], "privacy")
        verification = _mapping(value["verification"], "verification")
        route = EffectRoute(
            operation_id=_string(value["operation_id"], "operation_id"),
            effect=_string(value["effect"], "effect"),
            method=_string(value["method"], "method"),
            path=_string(value["path"], "path"),
            request_location=_string(request.get("location"), "request.location"),
            allowed_fields=frozenset(
                _string_list(request.get("allowed_fields", []), "allowed_fields")
            ),
            required_fields=frozenset(
                _string_list(request.get("required_fields", []), "required_fields")
            ),
            fixed_fields=_mapping(request.get("fixed_fields", {}), "fixed_fields"),
            executable=bool(value["executable"]),
            contract_status=_string(value["contract_status"], "contract_status"),
            block_reason=(
                str(value["block_reason"])
                if value.get("block_reason") is not None
                else None
            ),
        )
        return cls(
            operation_id=route.operation_id,
            effect=route.effect,
            method=route.method,
            path=route.path,
            contract_status=route.contract_status,
            executable=route.executable,
            block_reason=route.block_reason,
            request=MappingProxyType(dict(request)),
            response=MappingProxyType(dict(response)),
            privacy=MappingProxyType(dict(privacy)),
            verification=MappingProxyType(dict(verification)),
        )

    def effect_route(self) -> EffectRoute:
        return EffectRoute(
            operation_id=self.operation_id,
            effect=self.effect,
            method=self.method,
            path=self.path,
            request_location=str(self.request["location"]),
            allowed_fields=frozenset(self.request.get("allowed_fields", [])),
            required_fields=frozenset(self.request.get("required_fields", [])),
            fixed_fields=_mapping(self.request.get("fixed_fields", {}), "fixed_fields"),
            executable=self.executable,
            contract_status=self.contract_status,
            block_reason=self.block_reason,
        )

    def capability(self) -> dict[str, Any]:
        currently_callable = (
            self.executable
            and self.contract_status == "verified"
            and self.method != "UNKNOWN"
        )
        return {
            "operation_id": self.operation_id,
            "effect": self.effect,
            "method": self.method,
            "path": self.path,
            "contract_status": self.contract_status,
            "executable": self.executable,
            "currently_callable": currently_callable,
            "completion_status": None if currently_callable else "gap",
            "block_reason": self.block_reason,
            "describe_command": (
                "gravity export describe "
                f"{self.operation_id}"
            ),
            "verification": _plain(self.verification),
        }

    def description(self) -> dict[str, Any]:
        input_schema = self.request.get("input_schema")
        if not isinstance(input_schema, Mapping):
            input_schema = _fallback_input_schema(self.request)
        examples = self.request.get("examples")
        if not isinstance(examples, list):
            examples = []
        currently_callable = (
            self.executable
            and self.contract_status == "verified"
            and self.method != "UNKNOWN"
        )
        result = {
            "schema_version": "gravity-insight.export-description.v1",
            "ok": True,
            "status": "success",
            "operation_id": self.operation_id,
            "effect": self.effect,
            "contract_status": self.contract_status,
            "executable": self.executable,
            "currently_callable": currently_callable,
            "completion_status": None if currently_callable else "gap",
            "block_reason": self.block_reason,
            "input_schema": _plain(input_schema),
            "columns": _column_description(self.privacy),
            "wire": {
                "method": self.method,
                "path": self.path,
                "location": self.request.get("location"),
                "fixed_fields": _plain(self.request.get("fixed_fields", {})),
            },
            "pagination_and_scale": _plain(
                self.request.get(
                    "scale_controls",
                    {
                        "page_size_limits_total_rows": None,
                        "controls": [],
                        "status": "not_verified",
                    },
                )
            ),
            "examples": _plain(examples),
            "examples_status": "complete" if examples else "not_provided",
            "workflow": describe_workflow(self.operation_id, self.effect),
            "verification": _plain(self.verification),
        }
        result["next_action"] = describe_next_action(
            self.operation_id, self.effect, currently_callable
        )
        return result


class ExportContractRegistry:
    def __init__(self, contracts: Iterable[ExportRouteContract]) -> None:
        by_id: dict[str, ExportRouteContract] = {}
        routes: set[tuple[str, str]] = set()
        for contract in contracts:
            if contract.operation_id in by_id:
                raise ManifestError(
                    f"duplicate export operation_id: {contract.operation_id}"
                )
            route = (contract.method, contract.path)
            if contract.method != "UNKNOWN" and route in routes:
                raise ManifestError("duplicate export method and path")
            by_id[contract.operation_id] = contract
            routes.add(route)
        if len(by_id) != 22:
            raise ManifestError("export registry must contain the 22 census routes")
        self._contracts: Mapping[str, ExportRouteContract] = MappingProxyType(by_id)

    @classmethod
    def from_file(cls, path: str | Path) -> "ExportContractRegistry":
        source = Path(path)
        try:
            document = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ManifestError("could not load export route contracts") from exc
        if not isinstance(document, Mapping) or document.get("schema_version") != 1:
            raise ManifestError("unsupported export route schema version")
        values = document.get("routes")
        if not isinstance(values, list):
            raise ManifestError("export route registry requires a routes array")
        return cls(
            ExportRouteContract.from_dict(_mapping(item, "routes[]"))
            for item in values
        )

    def get(self, operation_id: str) -> ExportRouteContract:
        try:
            return self._contracts[operation_id]
        except KeyError as exc:
            from .actionable_error_values import actual_value; raise UnknownOperationError(
                f"actual value: {actual_value(operation_id)}; unknown Gravity export operation: {operation_id}",
                field="operation_id",
                next_action="Run `gravity export list-capabilities` and use an operation_id from the results.",
            ) from exc

    def describe(self, operation_id: str) -> dict[str, Any]:
        return self.get(operation_id).description()

    def all(self) -> tuple[ExportRouteContract, ...]:
        return tuple(self._contracts[key] for key in sorted(self._contracts))

    def effect_routes(self) -> tuple[EffectRoute, ...]:
        return tuple(contract.effect_route() for contract in self.all())


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ManifestError(f"export {label} must be an object")
    return value


def _string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ManifestError(f"export {label} must be a non-empty string")
    return value.strip()


def _string_list(value: Any, label: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ManifestError(f"export {label} must be an array")
    result = tuple(_string(item, label) for item in value)
    if len(result) != len(set(result)):
        raise ManifestError(f"export {label} contains duplicates")
    return result


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def _fallback_input_schema(request: Mapping[str, Any]) -> dict[str, Any]:
    allowed = [str(value) for value in request.get("allowed_fields", [])]
    required = {str(value) for value in request.get("required_fields", [])}
    fixed = request.get("fixed_fields", {})
    if not isinstance(fixed, Mapping):
        fixed = {}
    return {
        "type": "object",
        "additional_properties": False,
        "required": sorted(required),
        "optional": sorted(set(allowed) - required),
        "properties": {
            field: {
                "type": "unknown",
                "required": field in required,
                "default": _plain(fixed.get(field)),
                "has_default": field in fixed,
            }
            for field in allowed
        },
    }


def _column_description(privacy: Mapping[str, Any]) -> dict[str, Any]:
    physical_columns = [str(value) for value in privacy.get("allowed_columns", [])]
    request_columns = [
        str(value)
        for value in privacy.get("request_columns", physical_columns)
    ]
    required_request_columns = [
        str(value)
        for value in privacy.get("request_required_columns", request_columns)
    ]
    file_schema = privacy.get("file_schema")
    if not isinstance(file_schema, Mapping):
        file_schema = {}
    labels = {
        code: physical_columns[index] if index < len(physical_columns) else None
        for index, code in enumerate(request_columns)
    }
    return {
        "cli_argument": "--columns",
        "input_field": privacy.get("request_column_field"),
        "must_match_input_order_exactly": bool(
            privacy.get("request_column_field")
        ),
        "allowed_codes": request_columns,
        "required_codes": required_request_columns,
        "output_headers_by_code": labels,
        "required_output_headers": [
            str(value) for value in privacy.get("required_columns", [])
        ],
        "format": privacy.get("format"),
        "file_schema": _plain(file_schema),
    }


def validate_export_payload(contract: Any, payload: Mapping[str, Any]) -> None:
    allowed = [str(value) for value in contract.request.get("allowed_fields", [])]
    required = [str(value) for value in contract.request.get("required_fields", [])]
    unknown = sorted(set(payload) - set(allowed))
    if unknown:
        _raise_export_input(
            contract.operation_id,
            "unknown export input fields: " + ", ".join(unknown)
            + "; allowed fields: " + ", ".join(allowed),
            unknown[0],
        )
    missing = sorted(set(required) - set(payload))
    if missing:
        _raise_export_input(
            contract.operation_id,
            "missing required export input fields: " + ", ".join(missing),
            missing[0],
        )
    schema = contract.request.get("input_schema")
    properties = schema.get("properties") if isinstance(schema, Mapping) else None
    if not isinstance(properties, Mapping):
        return
    for field, value in payload.items():
        field_schema = properties.get(field)
        if isinstance(field_schema, Mapping):
            _validate_export_field(
                contract.operation_id, field, value, field_schema
            )


def validate_wire_projection(contract: Any, request: Any) -> None:
    column_field = contract.privacy.get("request_column_field")
    if column_field is None:
        return
    actual = request.payload.get(str(column_field))
    if isinstance(actual, Mapping):
        actual_columns = tuple(str(value) for value in actual)
    elif isinstance(actual, (list, tuple)):
        actual_columns = tuple(str(value) for value in actual)
    else:
        actual_columns = ()
    matches = actual_columns == request.requested_columns
    if not matches:
        raise _export_error(
            "wire export columns do not match the approved request projection",
            code="EXPORT_COLUMNS_INVALID",
            stage="creating",
        )


def _validate_export_field(
    operation_id: str,
    field: str,
    value: Any,
    schema: Mapping[str, Any],
) -> None:
    expected = str(schema.get("type", "unknown"))
    if not _matches_export_type(value, expected):
        _raise_export_input(
            operation_id, f"export input {field!r} must be {expected}", field
        )
    enum = schema.get("enum")
    if isinstance(enum, list) and value not in enum:
        _raise_export_input(
            operation_id,
            f"export input {field!r} is outside its allowed values",
            field,
        )
    if expected == "integer":
        _validate_integer(operation_id, field, value, schema)
    elif expected == "string":
        _validate_string(operation_id, field, value, schema)
    elif expected == "array":
        _validate_array(operation_id, field, value, schema)


def _matches_export_type(value: Any, expected: str) -> bool:
    checks = {
        "array": lambda: isinstance(value, list),
        "object": lambda: isinstance(value, Mapping),
        "string": lambda: isinstance(value, str),
        "integer": lambda: isinstance(value, int) and not isinstance(value, bool),
        "boolean": lambda: isinstance(value, bool),
        "unknown": lambda: True,
    }
    check = checks.get(expected)
    return check() if check is not None else False


def _validate_integer(
    operation_id: str, field: str, value: int, schema: Mapping[str, Any]
) -> None:
    minimum, maximum = schema.get("minimum"), schema.get("maximum")
    if isinstance(minimum, int) and value < minimum:
        _raise_export_input(
            operation_id, f"export input {field!r} is below its minimum", field
        )
    if isinstance(maximum, int) and value > maximum:
        _raise_export_input(
            operation_id, f"export input {field!r} exceeds its maximum", field
        )


def _validate_string(
    operation_id: str, field: str, value: str, schema: Mapping[str, Any]
) -> None:
    minimum, maximum = schema.get("min_length"), schema.get("max_length")
    if isinstance(minimum, int) and len(value) < minimum:
        _raise_export_input(
            operation_id, f"export input {field!r} is too short", field
        )
    if isinstance(maximum, int) and len(value) > maximum:
        _raise_export_input(
            operation_id, f"export input {field!r} is too long", field
        )


def _validate_array(
    operation_id: str, field: str, value: list[Any], schema: Mapping[str, Any]
) -> None:
    minimum, maximum = schema.get("min_items"), schema.get("max_items")
    if isinstance(minimum, int) and len(value) < minimum:
        _raise_export_input(
            operation_id, f"export input {field!r} has too few items", field
        )
    if isinstance(maximum, int) and len(value) > maximum:
        _raise_export_input(
            operation_id, f"export input {field!r} has too many items", field
        )
    item_type = schema.get("item_type")
    if isinstance(item_type, str) and any(
        not _matches_export_item(item, item_type) for item in value
    ):
        _raise_export_input(
            operation_id,
            f"export input {field!r} must contain only {item_type} items",
            field,
        )
    item_enum = schema.get("item_enum")
    if isinstance(item_enum, list) and any(item not in item_enum for item in value):
        _raise_export_input(
            operation_id,
            f"export input {field!r} contains an item outside its allowed values",
            field,
        )


def _matches_export_item(value: Any, expected: str) -> bool:
    if expected == "string":
        return isinstance(value, str)
    if expected == "object":
        return isinstance(value, Mapping)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected != "date" or not isinstance(value, str):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _raise_export_input(operation_id: str, message: str, field: str) -> None:
    from .actionable_error_values import actual_value; raise InputValidationError(
        f"actual value: {actual_value(field)}; {message}", field=field,
        next_action=f"Run `gravity export describe {operation_id}` and retry with the documented input.",
    )


def export_error_field(code: str) -> str | None:
    return {
        "EXPORT_COLUMNS_INVALID": "columns",
        "EXPORT_JOB_INVALID": "job_id",
        "EXPORT_IDEMPOTENCY_KEY_INVALID": "idempotency_key",
        "EXPORT_TIMEOUT_INVALID": "timeout",
    }.get(code)
