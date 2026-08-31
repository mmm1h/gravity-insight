"""Build a value-free Governor descriptor from an authorized HTTP attempt."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import urlsplit

from .adaptive_governor_contract import (
    MAX_WAIT_SECONDS,
    PROCESS_SCOPE,
    GovernorRequest,
    current_journey_key,
    private_host_key,
    private_scope_key,
)


MAX_REQUEST_KEY_BYTES = 1_048_576
_SAFE_NAME_CHARACTERS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:-"
)
_HTTP_METHODS = frozenset({"DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"})


def build_governor_request(
    request_args: Sequence[Any],
    request_kwargs: Mapping[str, Any],
    *,
    receipt_context: Mapping[str, Any] | None,
    governor_context: Mapping[str, Any] | None,
    cancellation: Any = None,
) -> GovernorRequest:
    receipt = dict(receipt_context or {})
    governor = dict(governor_context or {})
    effect = str(receipt.get("_governor_effect", "other"))
    operation = _safe_name(receipt.get("operation_id"), "runtime_http")
    profile = _profile(governor.get("profile"), operation, effect)
    scope_material = governor.get("scope_key", PROCESS_SCOPE)
    coalesce_safe = _coalesce_safe(receipt, request_kwargs, effect, profile)
    request_key = (
        _request_key(request_args, request_kwargs, operation)
        if coalesce_safe
        else None
    )
    return GovernorRequest(
        scope_key=private_scope_key(scope_material),
        host_key=private_host_key(_hostname(request_args)),
        operation_class=operation,
        profile=profile,
        journey_key=current_journey_key(),
        request_key=request_key,
        coalesce_safe=request_key is not None,
        timeout_seconds=_wait_timeout(governor, request_kwargs),
        cancellation=cancellation,
        target_host=_hostname(request_args),
        attempt=_attempt(receipt.get("attempt")),
    )


def _coalesce_safe(
    receipt: Mapping[str, Any],
    request_kwargs: Mapping[str, Any],
    effect: str,
    profile: str,
) -> bool:
    return bool(
        effect == "read"
        and receipt.get("_governor_coalesce_safe") is True
        and profile != "login"
        and request_kwargs.get("stream") is not True
        and not any(key in request_kwargs for key in ("data", "files"))
    )


def _request_key(
    request_args: Sequence[Any], request_kwargs: Mapping[str, Any], operation: str
) -> str | None:
    try:
        value = {
            "operation": operation,
            "args": _json_value(list(request_args)),
            "kwargs": _json_value(dict(request_kwargs)),
        }
        rendered = json.dumps(
            value,
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError, OverflowError):
        return None
    if len(rendered) > MAX_REQUEST_KEY_BYTES:
        return None
    return hashlib.sha256(b"gravity-http-request-v1\0" + rendered).hexdigest()


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("non-finite request number")
        return value
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise TypeError("request mapping keys must be strings")
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    raise TypeError("request value is not canonical JSON")


def _hostname(arguments: Sequence[Any]) -> str:
    for argument in arguments:
        if not isinstance(argument, str):
            continue
        parsed = urlsplit(argument)
        if parsed.scheme in {"http", "https"} and parsed.hostname:
            selected = parsed.hostname.casefold()
            if len(selected) <= 253 and all(
                character in "abcdefghijklmnopqrstuvwxyz0123456789.:-"
                for character in selected
            ):
                return selected
    return "unknown"


def _attempt(value: Any) -> int:
    return value if type(value) is int and 1 <= value <= 100 else 1


def _profile(value: Any, operation: str, effect: str) -> str:
    selected = _safe_name(value, "")
    if selected:
        return selected
    if effect == "login" or operation == "authentication":
        return "login"
    if operation.startswith("sql."):
        return "sql"
    if effect in {"mutation", "stream"} or "artifact" in operation or "blob" in operation:
        return "artifact"
    return "runtime"


def _safe_name(value: Any, fallback: str) -> str:
    selected = str(value or "").strip()[:128]
    if selected and all(character in _SAFE_NAME_CHARACTERS for character in selected):
        return selected
    return fallback


def _wait_timeout(
    governor: Mapping[str, Any], request_kwargs: Mapping[str, Any]
) -> float:
    value = governor.get("timeout_seconds", request_kwargs.get("timeout"))
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return MAX_WAIT_SECONDS
    selected = float(value)
    if not math.isfinite(selected) or selected <= 0:
        return MAX_WAIT_SECONDS
    return min(selected, MAX_WAIT_SECONDS)


__all__ = ["MAX_REQUEST_KEY_BYTES", "build_governor_request"]
