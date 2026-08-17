"""Origin-aware source records and effect authorization assessment."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from collections.abc import Mapping
from typing import Any

from .plan_binding import validate_json


SOURCE_SCHEMA_VERSION = "gravity.host-source.v1"
ACTION_SCHEMA_VERSION = "gravity.host-action.v1"
PERMISSION_SCHEMA_VERSION = "gravity.effect-permission.v1"
CONFIRMATION_SCHEMA_VERSION = "gravity.effect-confirmation.v1"

_SOURCE_FIELDS = frozenset({"schema_version", "origin", "role", "value"})
_ACTION_FIELDS = frozenset(
    {
        "schema_version", "task_source", "effect", "phase", "controls",
        "request", "permission_source", "confirmation_source",
        "preview_fingerprint",
    }
)
_CONTROL_FIELDS = frozenset(
    {"tool", "operation", "path", "object_ids", "destination"}
)
_ORIGINS = frozenset({"user", "tool_result", "sdk_contract"})
_ROLES = frozenset({"data", "instruction", "authorization"})
_SOURCE_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,127}$")
_PHASES = {
    "read": frozenset({"read"}),
    "mutation": frozenset({"preview", "execute"}),
}


def host_source(origin: str, role: str, value: Any) -> dict[str, Any]:
    """Build one source record without interpreting or changing its value."""

    return {
        "schema_version": SOURCE_SCHEMA_VERSION,
        "origin": origin,
        "role": role,
        "value": copy.deepcopy(value),
    }


def assess_host_action(
    action: Any,
    sources: Mapping[str, Any],
) -> dict[str, Any]:
    """Assess an origin-aware action without raising or executing an effect."""

    violations: list[dict[str, str]] = []
    if not isinstance(sources, Mapping):
        _violate(violations, "SOURCE_MAP_INVALID", "sources")
        sources = {}
    selected = _action_mapping(action, violations)
    effect, phase = selected.get("effect"), selected.get("phase")
    _validate_effect_phase(effect, phase, violations)
    task = _source(
        selected.get("task_source"), sources, "action.task_source", violations
    )
    _expect_source(
        task, origin="user", roles=frozenset({"instruction"}),
        code="TASK_SOURCE_NOT_USER_INSTRUCTION", field="action.task_source",
        violations=violations,
    )
    controls = _resolve_controls(selected.get("controls"), sources, violations)
    request = selected.get("request")
    try:
        validate_json(request)
    except TypeError:
        _violate(violations, "ACTION_REQUEST_INVALID", "action.request")
    request_sha256 = _request_sha256(effect, controls, request)
    permission = _source(
        selected.get("permission_source"), sources, "action.permission_source",
        violations, optional=True,
    )
    confirmation = _source(
        selected.get("confirmation_source"), sources,
        "action.confirmation_source", violations, optional=True,
    )
    _validate_authority(
        selected, effect, phase, request_sha256, permission, confirmation,
        violations,
    )
    return {
        "schema_version": "gravity.host-action-assessment.v1",
        "allowed": not violations,
        "effect": effect,
        "phase": phase,
        "request_sha256": request_sha256,
        "controls": controls,
        "violations": violations,
    }


def _action_mapping(
    action: Any, violations: list[dict[str, str]]
) -> Mapping[str, Any]:
    if not isinstance(action, Mapping):
        _violate(violations, "ACTION_SCHEMA_INVALID", "action")
        return {}
    if set(action) != _ACTION_FIELDS or action.get("schema_version") != ACTION_SCHEMA_VERSION:
        _violate(violations, "ACTION_SCHEMA_INVALID", "action")
    return action


def _validate_effect_phase(
    effect: Any, phase: Any, violations: list[dict[str, str]]
) -> None:
    if effect not in _PHASES or phase not in _PHASES.get(effect, frozenset()):
        _violate(violations, "EFFECT_PHASE_INVALID", "action.effect")


def _resolve_controls(
    controls: Any,
    sources: Mapping[str, Any],
    violations: list[dict[str, str]],
) -> dict[str, Any]:
    if not isinstance(controls, Mapping) or set(controls) != _CONTROL_FIELDS:
        _violate(violations, "CONTROL_SCHEMA_INVALID", "action.controls")
        controls = {}
    resolved = _resolve_sdk_controls(controls, sources, violations)
    resolved["object_ids"] = _resolve_objects(
        controls.get("object_ids"), sources, violations
    )
    resolved["destination"] = _resolve_destination(
        controls.get("destination"), sources, violations
    )
    return resolved


def _resolve_sdk_controls(
    controls: Mapping[str, Any],
    sources: Mapping[str, Any],
    violations: list[dict[str, str]],
) -> dict[str, Any]:
    resolved: dict[str, Any] = {}
    for name in ("tool", "operation", "path"):
        field = f"action.controls.{name}"
        source = _source(controls.get(name), sources, field, violations)
        _expect_source(
            source, origin="sdk_contract", roles=frozenset({"instruction"}),
            code=f"{name.upper()}_CONTROL_NOT_SDK_ORIGIN", field=field,
            violations=violations,
        )
        value = _source_value(source)
        if not isinstance(value, str) or not value.strip():
            _violate(violations, "CONTROL_VALUE_INVALID", field)
        resolved[name] = copy.deepcopy(value)
    return resolved


def _resolve_objects(
    references: Any,
    sources: Mapping[str, Any],
    violations: list[dict[str, str]],
) -> list[Any]:
    if not isinstance(references, list) or len(references) > 64:
        _violate(
            violations, "OBJECT_CONTROL_SCHEMA_INVALID",
            "action.controls.object_ids",
        )
        return []
    resolved: list[Any] = []
    for index, reference in enumerate(references):
        field = f"action.controls.object_ids[{index}]"
        source = _source(reference, sources, field, violations)
        _expect_user_control(source, "OBJECT_ID_NOT_USER_ORIGIN", field, violations)
        value = _source_value(source)
        if not isinstance(value, (str, int)) or isinstance(value, bool):
            _violate(violations, "OBJECT_ID_VALUE_INVALID", field)
        resolved.append(copy.deepcopy(value))
    return resolved


def _resolve_destination(
    reference: Any,
    sources: Mapping[str, Any],
    violations: list[dict[str, str]],
) -> Any:
    if reference is None:
        return None
    field = "action.controls.destination"
    source = _source(reference, sources, field, violations)
    _expect_user_control(source, "DESTINATION_NOT_USER_ORIGIN", field, violations)
    value = _source_value(source)
    if not isinstance(value, str) or not value.strip():
        _violate(violations, "DESTINATION_VALUE_INVALID", field)
    return copy.deepcopy(value)


def _validate_authority(
    action: Mapping[str, Any],
    effect: Any,
    phase: Any,
    request_sha256: str,
    permission: Mapping[str, Any] | None,
    confirmation: Mapping[str, Any] | None,
    violations: list[dict[str, str]],
) -> None:
    preview_fingerprint = action.get("preview_fingerprint")
    if effect != "mutation":
        if permission is not None or confirmation is not None or preview_fingerprint is not None:
            _violate(
                violations, "READ_ACTION_HAS_EFFECT_AUTHORITY",
                "action.permission_source",
            )
        return
    _validate_permission(permission, request_sha256, violations)
    if phase == "execute":
        _validate_confirmation(
            confirmation, preview_fingerprint, request_sha256, violations
        )
    elif confirmation is not None or preview_fingerprint is not None:
        _violate(
            violations, "PREVIEW_CANNOT_CONFIRM_EXECUTE",
            "action.confirmation_source",
        )


def _validate_permission(
    permission: Mapping[str, Any] | None,
    request_sha256: str,
    violations: list[dict[str, str]],
) -> None:
    _expect_source(
        permission, origin="user", roles=frozenset({"authorization"}),
        code="MUTATION_PERMISSION_NOT_USER_AUTHORIZATION",
        field="action.permission_source", violations=violations,
    )
    expected = {
        "schema_version": PERMISSION_SCHEMA_VERSION,
        "effect": "mutation",
        "request_sha256": request_sha256,
    }
    if _source_value(permission) != expected:
        _violate(
            violations, "MUTATION_PERMISSION_MISMATCH",
            "action.permission_source",
        )


def _validate_confirmation(
    confirmation: Mapping[str, Any] | None,
    preview_fingerprint: Any,
    request_sha256: str,
    violations: list[dict[str, str]],
) -> None:
    if not isinstance(preview_fingerprint, str) or not preview_fingerprint.strip():
        _violate(
            violations, "PREVIEW_FINGERPRINT_REQUIRED",
            "action.preview_fingerprint",
        )
    _expect_source(
        confirmation, origin="user", roles=frozenset({"authorization"}),
        code="EXECUTE_CONFIRMATION_NOT_USER_AUTHORIZATION",
        field="action.confirmation_source", violations=violations,
    )
    expected = {
        "schema_version": CONFIRMATION_SCHEMA_VERSION,
        "confirmed": True,
        "preview_fingerprint": preview_fingerprint,
        "request_sha256": request_sha256,
    }
    if _source_value(confirmation) != expected:
        _violate(
            violations, "EXECUTE_CONFIRMATION_MISMATCH",
            "action.confirmation_source",
        )


def _source(
    reference: Any,
    sources: Mapping[str, Any],
    field: str,
    violations: list[dict[str, str]],
    *,
    optional: bool = False,
) -> Mapping[str, Any] | None:
    if reference is None and optional:
        return None
    if not isinstance(reference, str) or not _SOURCE_ID.fullmatch(reference):
        _violate(violations, "SOURCE_REFERENCE_INVALID", field)
        return None
    value = sources.get(reference)
    if not isinstance(value, Mapping) or set(value) != _SOURCE_FIELDS:
        _violate(violations, "SOURCE_RECORD_INVALID", field)
        return None
    _validate_source_record(value, field, violations)
    return value


def _validate_source_record(
    source: Mapping[str, Any],
    field: str,
    violations: list[dict[str, str]],
) -> None:
    if source.get("schema_version") != SOURCE_SCHEMA_VERSION:
        _violate(violations, "SOURCE_SCHEMA_UNKNOWN", field)
    origin, role = source.get("origin"), source.get("role")
    if origin not in _ORIGINS or role not in _ROLES:
        _violate(violations, "SOURCE_CLASS_INVALID", field)
    if (
        origin == "tool_result" and role != "data"
        or origin == "sdk_contract" and role != "instruction"
    ):
        _violate(violations, "SOURCE_CLASS_CONTRADICTORY", field)
    try:
        validate_json(source.get("value"))
    except TypeError:
        _violate(violations, "SOURCE_VALUE_INVALID", field)


def expect_sdk_source(
    source: Mapping[str, Any] | None,
    *,
    code: str,
    field: str,
    violations: list[dict[str, str]],
) -> None:
    _expect_source(
        source, origin="sdk_contract", roles=frozenset({"instruction"}),
        code=code, field=field, violations=violations,
    )


def source_for_plan(
    reference: Any,
    sources: Mapping[str, Any],
    field: str,
    violations: list[dict[str, str]],
) -> Mapping[str, Any] | None:
    return _source(reference, sources, field, violations)


def source_value(source: Mapping[str, Any] | None) -> Any:
    return _source_value(source)


def add_violation(
    violations: list[dict[str, str]], code: str, field: str
) -> None:
    _violate(violations, code, field)


def _expect_source(
    source: Mapping[str, Any] | None,
    *,
    origin: str,
    roles: frozenset[str],
    code: str,
    field: str,
    violations: list[dict[str, str]],
) -> None:
    if source is None or source.get("origin") != origin or source.get("role") not in roles:
        _violate(violations, code, field)


def _expect_user_control(
    source: Mapping[str, Any] | None,
    code: str,
    field: str,
    violations: list[dict[str, str]],
) -> None:
    _expect_source(
        source, origin="user", roles=frozenset({"instruction", "authorization"}),
        code=code, field=field, violations=violations,
    )


def _source_value(source: Mapping[str, Any] | None) -> Any:
    return None if source is None else source.get("value")


def _request_sha256(effect: Any, controls: Mapping[str, Any], request: Any) -> str:
    payload = {"effect": effect, "controls": controls, "request": request}
    try:
        encoded = json.dumps(
            payload, ensure_ascii=False, sort_keys=True,
            separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError):
        encoded = b"invalid-host-action"
    return hashlib.sha256(encoded).hexdigest()


def _violate(violations: list[dict[str, str]], code: str, field: str) -> None:
    item = {"code": code, "field": field}
    if item not in violations:
        violations.append(item)


__all__ = [
    "ACTION_SCHEMA_VERSION",
    "CONFIRMATION_SCHEMA_VERSION",
    "PERMISSION_SCHEMA_VERSION",
    "SOURCE_SCHEMA_VERSION",
    "add_violation",
    "assess_host_action",
    "expect_sdk_source",
    "host_source",
    "source_for_plan",
    "source_value",
]
