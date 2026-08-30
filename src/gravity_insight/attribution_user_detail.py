"""Governed F40 single-user attribution detail product."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from . import runtime
from .composite_catalog import stable_operation
from .errors import ErrorCode, ErrorDetail, InputValidationError, PermissionUnavailableError
from .errors import exit_code_for_error
from .metadata_sync import APP_OPERATION_ID
from .result_audit import project_result_audit
from .result_source import GOVERNED_PRODUCT, result_source


SCHEMA_VERSION = "gravity-insight.attribution-user-detail.v1"
OPERATION_ID = stable_operation(
    "attribution", "attribution_detail", action="query"
).operation_id
TESTING_DEVICE_OPERATION_ID = stable_operation(
    "app", "testing_tool", action="list"
).operation_id

_DEVICE_WHITE_TYPES = {
    "app_id": int,
    "create_time": str,
    "id": int,
    "is_template": bool,
    "modify_time": str,
    "name": str,
    "remark": str,
    "reuse_from_device_id": int,
    "testing_company": str,
    "testing_end_time": type(None),
    "testing_start_time": type(None),
    "testing_status": int,
}
_DEVICE_INFO_FIELDS = frozenset({"android_id", "imei", "oaid"})
_DETAIL_DATA_FIELDS = frozenset(
    {"device_white", "attribution_list", "postback_list", "pay_list"}
)


def read_user_detail(
    client: Any, app_id: str | int, device_id: str | int
) -> dict[str, Any]:
    """Read one caller-selected registered testing-device attribution detail."""

    app, device = validate_request(app_id, device_id)
    native = runtime.call_read(
        client, OPERATION_ID, {"app_id": app, "device_id": device}
    )
    return result(native, app_id=app, device_id=device)


def validate_request(app_id: str | int, device_id: str | int) -> tuple[int, int]:
    return _positive_id(app_id, "app_id"), _positive_id(device_id, "device_id")


def result(native: Any, *, app_id: int, device_id: int) -> dict[str, Any]:
    if not isinstance(native, Mapping):
        return _contract_failure(native, app_id, device_id)
    status = native.get("status")
    if (
        native.get("schema_version") != "gravity-insight.read.v1"
        or native.get("operation_id") != OPERATION_ID
        or status not in {"success", "empty"}
    ):
        return _native_failure(native, app_id, device_id)
    data = _safe_data(native.get("data"))
    if data is None:
        return _contract_failure(native, app_id, device_id)
    return project_result_audit(
        {
            "schema_version": SCHEMA_VERSION,
            "result_source": result_source(GOVERNED_PRODUCT),
            "ok": True,
            "status": "success",
            "exit_code": 0,
            "operation_id": OPERATION_ID,
            "app_id": app_id,
            "device_id": device_id,
            "data": data,
            "error": None,
        },
        native,
    )


def first_probe_testing_device_field(client: Any, field: str) -> int:
    """Resolve one bounded catalog row without persisting App/device values."""

    cache_key = "first_testing_device"
    with client._probe_lock:
        cached = client._probe_values.get(cache_key)
        if isinstance(cached, Mapping) and type(cached.get(field)) is int:
            return int(cached[field])
        catalog = _rows(client.read(APP_OPERATION_ID, {"page": 1, "page_size": 6000}))
        for app in catalog[:7]:
            app_id = _catalog_id(app.get("id"))
            if app_id is None:
                continue
            rows = _rows(
                client.read(
                    TESTING_DEVICE_OPERATION_ID,
                    {"app_id": app_id, "page": 1, "page_size": 1000},
                )
            )
            device_id = rows[0].get("id") if rows else None
            if type(device_id) is not int or device_id <= 0:
                continue
            resolved = {"app_id": app_id, "device_id": device_id}
            client._probe_values[cache_key] = resolved
            return resolved[field]
    raise PermissionUnavailableError(
        "no readable registered testing device is available for the minimum attribution-detail probe",
        next_action="Select an App with an existing testing-device row; do not create a probe device.",
    )


def _safe_data(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping) or set(value) != _DETAIL_DATA_FIELDS:
        return None
    device = value.get("device_white")
    if not isinstance(device, Mapping) or set(device) != {*_DEVICE_WHITE_TYPES, "device_info"}:
        return None
    if any(type(device[name]) is not kind for name, kind in _DEVICE_WHITE_TYPES.items()):
        return None
    device_info = device.get("device_info")
    if (
        not isinstance(device_info, Mapping)
        or set(device_info) != _DEVICE_INFO_FIELDS
        or any(not isinstance(item, str) for item in device_info.values())
    ):
        return None
    if any(value.get(name) != [] for name in ("attribution_list", "postback_list", "pay_list")):
        return None
    return copy.deepcopy(dict(value))


def _native_failure(
    native: Mapping[str, Any], app_id: int, device_id: int
) -> dict[str, Any]:
    error = native.get("error")
    if not isinstance(error, Mapping):
        return _contract_failure(native, app_id, device_id)
    code = error.get("code")
    allowed = {item.value for item in ErrorCode}
    selected = code if isinstance(code, str) and code in allowed else ErrorCode.CONTRACT_CHANGED
    detail = ErrorDetail.create(
        selected,
        "Attribution user detail could not complete its governed read.",
        operation_id=OPERATION_ID,
        next_action=(
            str(error["next_action"])
            if isinstance(error.get("next_action"), str) and error["next_action"]
            else None
        ),
    )
    return project_result_audit(
        _failure(app_id, device_id, str(native.get("status", "error")), detail), native
    )


def _contract_failure(native: Any, app_id: int, device_id: int) -> dict[str, Any]:
    detail = ErrorDetail.create(
        ErrorCode.CONTRACT_CHANGED,
        "Attribution user detail result no longer matches its registered contract.",
        operation_id=OPERATION_ID,
        next_action="Stop automation, refresh the F40 shape evidence, and retry after the contract is updated.",
    )
    return project_result_audit(_failure(app_id, device_id, "contract_changed", detail), native)


def _failure(
    app_id: int, device_id: int, status: str, detail: ErrorDetail
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "result_source": result_source(GOVERNED_PRODUCT),
        "ok": False,
        "status": status,
        "exit_code": exit_code_for_error(detail),
        "operation_id": OPERATION_ID,
        "app_id": app_id,
        "device_id": device_id,
        "data": {},
        "error": detail.to_dict(),
    }


def _positive_id(value: str | int, field: str) -> int:
    rendered = str(value).strip() if not isinstance(value, bool) and isinstance(value, (str, int)) else ""
    if not rendered.isascii() or not rendered.isdigit() or int(rendered) <= 0:
        raise InputValidationError(
            f"attribution user detail {field} has an invalid actual value; it must be a positive integer",
            field=field,
            next_action=f"Retry with a positive {field} selected from the governed parent catalog.",
        )
    return int(rendered)


def _rows(envelope: Any) -> list[Mapping[str, Any]]:
    data = envelope.get("data") if isinstance(envelope, Mapping) else None
    rows = data.get("list", data.get("items", [])) if isinstance(data, Mapping) else data
    return [item for item in rows if isinstance(item, Mapping)] if isinstance(rows, list) else []


def _catalog_id(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    rendered = str(value)
    return int(rendered) if rendered.isascii() and rendered.isdigit() and int(rendered) > 0 else None


__all__ = [
    "OPERATION_ID",
    "SCHEMA_VERSION",
    "TESTING_DEVICE_OPERATION_ID",
    "first_probe_testing_device_field",
    "read_user_detail",
    "result",
    "validate_request",
]
