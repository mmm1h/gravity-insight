"""Canonical JSON isolation shared by request codecs and policy receipts."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from .errors import PolicyViolation


def canonical_wire_snapshot(
    query: Mapping[str, Any], body: Mapping[str, Any]
) -> str:
    try:
        return json.dumps(
            {"query": _plain_json(query), "body": _plain_json(body)},
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise PolicyViolation("request payload is not a canonical JSON value") from exc


def isolated_wire(
    query: Mapping[str, Any], body: Mapping[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    isolated = json.loads(canonical_wire_snapshot(query, body))
    return isolated["query"], isolated["body"]


def _plain_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _plain_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain_json(item) for item in value]
    return value


__all__ = ["canonical_wire_snapshot", "isolated_wire"]
