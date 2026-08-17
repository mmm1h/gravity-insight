"""Scalar JSON Pointer binding primitives for Plan v1."""

from __future__ import annotations

import copy
import math
from collections.abc import Mapping, Sequence
from typing import Any

from .plan import PlanNode, PlanValidationError
from .actionable_error_values import actual_value


_JSON_SCALAR = (type(None), bool, int, float, str)


def prepare_executions(
    node: PlanNode, registry: Mapping[str, Mapping[str, Any]]
) -> list[tuple[str, int | None, Mapping[str, Any]]]:
    """Bind one request and optionally expand a single foreach array."""

    request = copy.deepcopy(dict(node.request))
    for binding in node.bindings:
        value = resolve_pointer(registry[binding.source_node], binding.source)
        require_scalar(value)
        set_pointer(request, binding.target, copy.deepcopy(value))
    if node.foreach is None:
        return [(node.node_id, None, request)]
    values = resolve_pointer(registry[node.foreach.source_node], node.foreach.source)
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes, bytearray)):
        raise TypeError("foreach source is not an array")
    if len(values) > node.foreach.max_items:
        raise ValueError("foreach source exceeds its declared bound")
    executions: list[tuple[str, int | None, Mapping[str, Any]]] = []
    for index, value in enumerate(values):
        require_scalar(value)
        selected = copy.deepcopy(request)
        set_pointer(selected, node.foreach.target, copy.deepcopy(value))
        executions.append((f"{node.node_id}[{index}]", index, selected))
    return executions


def resolve_pointer(document: Any, pointer: str) -> Any:
    selected = document
    for token in pointer_tokens(pointer):
        if isinstance(selected, Mapping):
            selected = selected[token]
        elif isinstance(selected, Sequence) and not isinstance(
            selected, (str, bytes, bytearray)
        ):
            selected = selected[array_index(token, len(selected))]
        else:
            raise TypeError("JSON Pointer crosses a scalar")
    return selected


def set_pointer(document: dict[str, Any], pointer: str, value: Any) -> None:
    tokens = pointer_tokens(pointer)
    if not tokens:
        raise ValueError("request root cannot be replaced")
    selected: Any = document
    for token in tokens[:-1]:
        if isinstance(selected, dict):
            if token not in selected:
                selected[token] = {}
            selected = selected[token]
        elif isinstance(selected, list):
            selected = selected[array_index(token, len(selected))]
        else:
            raise TypeError("JSON Pointer target crosses a scalar")
    leaf = tokens[-1]
    if isinstance(selected, dict):
        selected[leaf] = value
    elif isinstance(selected, list):
        selected[array_index(leaf, len(selected))] = value
    else:
        raise TypeError("JSON Pointer target parent is a scalar")


def validate_pointer(value: Any, field: str, *, allow_root: bool) -> str:
    if not isinstance(value, str) or (not allow_root and not value):
        raise PlanValidationError(
            "JSON Pointer must start with / and use only RFC 6901 escapes",
            field=field,
        )
    if value and not value.startswith("/"):
        raise PlanValidationError(f"actual value: {actual_value(value)}; " + ("JSON Pointer must start with /"), field=field)
    try:
        pointer_tokens(value)
    except ValueError as exc:
        raise PlanValidationError(
            "JSON Pointer escape must use ~0 or ~1 only",
            field=field,
        ) from exc
    return value


def pointer_tokens(pointer: str) -> list[str]:
    if pointer == "":
        return []
    return [_decode_token(raw) for raw in pointer[1:].split("/")]


def _decode_token(raw: str) -> str:
    index = 0
    decoded = ""
    while index < len(raw):
        if raw[index] != "~":
            decoded += raw[index]
            index += 1
            continue
        if index + 1 >= len(raw) or raw[index + 1] not in {"0", "1"}:
            raise ValueError("invalid JSON Pointer escape")
        decoded += "~" if raw[index + 1] == "0" else "/"
        index += 2
    return decoded


def array_index(token: str, length: int) -> int:
    if not token.isascii() or not token.isdigit():
        raise ValueError("array JSON Pointer token must be an index")
    index = int(token)
    if index >= length:
        raise IndexError("array JSON Pointer index is out of range")
    return index


def require_scalar(value: Any) -> None:
    if not isinstance(value, _JSON_SCALAR) or (
        isinstance(value, float) and not math.isfinite(value)
    ):
        raise TypeError("binding values must be finite JSON scalars")


def validate_json(value: Any) -> None:
    if isinstance(value, _JSON_SCALAR):
        if isinstance(value, float) and not math.isfinite(value):
            raise TypeError("adapter result contains a non-finite number")
        return
    if isinstance(value, list):
        for item in value:
            validate_json(item)
        return
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise TypeError("adapter result keys must be strings")
        for item in value.values():
            validate_json(item)
        return
    raise TypeError("adapter result is not JSON-compatible")


__all__ = ["prepare_executions", "validate_json", "validate_pointer"]
