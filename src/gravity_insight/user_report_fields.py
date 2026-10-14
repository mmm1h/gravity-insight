"""Versioned, offline user-report field discovery."""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from ._field_policy_operations import ANALYSIS_USER_DETAIL
from .errors import ContractChangedError, InputValidationError
from .actionable_error_values import actual_value


SCHEMA_VERSION = "gravity.user-report-field-catalog.v1"
CATALOG_ID = "gravity.user-report-fields"
CATALOG_VERSION = 1
KIND = "user_report_field"
SOURCE = "user_report_fields"
OPERATION_ID = ANALYSIS_USER_DETAIL
GROUPS = (
    "base",
    "pay",
    "ad_revenue",
    "profile",
    "attribution",
    "re_attribute",
    "device",
)
_FIELD_TYPES = frozenset({"string", "integer", "float", "object"})
_SELECTIONS = frozenset({"static_projection", "live_metadata"})
_CATALOG_PATH = (
    Path(__file__).resolve().parent
    / "contracts"
    / "catalogs"
    / "user-report-fields.v1.json"
)
_DOCUMENT_KEYS = {
    "schema_version", "catalog_id", "catalog_version", "source", "groups", "fields"
}
_ROW_KEYS = {
    "name", "cname", "description", "group", "type", "default", "selection"
}


@lru_cache(maxsize=1)
def catalog_document() -> Mapping[str, Any]:
    try:
        document = json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ContractChangedError("user report field catalog is unavailable") from exc
    _validate_document(document)
    return MappingProxyType(document)


def catalog_rows() -> tuple[Mapping[str, Any], ...]:
    rows = catalog_document()["fields"]
    return tuple(MappingProxyType(dict(row)) for row in rows)


def catalog_metadata() -> dict[str, Any]:
    document = catalog_document()
    encoded = json.dumps(
        dict(document), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return {
        "catalog_id": CATALOG_ID,
        "catalog_version": CATALOG_VERSION,
        "catalog_sha256": hashlib.sha256(encoded).hexdigest(),
        "field_count": len(document["fields"]),
        "groups": list(GROUPS),
    }


def search_rows(query: str = "", *, group: str | None = None) -> list[dict[str, Any]]:
    if not isinstance(query, str):
        raise InputValidationError(
            f"actual value: {actual_value(query)}; user report field query must be a string",
            field="query",
        )
    selected_group = validate_group(group)
    normalized = query.strip().casefold()
    results: list[dict[str, Any]] = []
    for index, item in enumerate(catalog_rows()):
        if selected_group is not None and item["group"] != selected_group:
            continue
        score = _score(normalized, item)
        if normalized and score == 0:
            continue
        results.append({"row_index": index, "score": score, "payload": dict(item)})
    return sorted(results, key=lambda item: (-item["score"], item["row_index"]))


def validate_group(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or value not in GROUPS:
        raise InputValidationError(
            f"actual value: {actual_value(value)}; user report field group must be one of {actual_value(list(GROUPS))}",
            field="group",
        )
    return value


def _score(query: str, row: Mapping[str, Any]) -> int:
    if not query:
        return 0
    values = tuple(str(row[key]).casefold() for key in ("name", "cname"))
    if query in values:
        return 100
    if any(value.startswith(query) for value in values):
        return 80
    if any(query in value for value in values):
        return 60
    searchable = " ".join(str(row[key]).casefold() for key in _ROW_KEYS)
    return 20 if query in searchable else 0


def _validate_document(value: Any) -> None:
    if not isinstance(value, Mapping) or set(value) != _DOCUMENT_KEYS:
        raise ContractChangedError("user report field catalog shape changed")
    expected = {
        "schema_version": SCHEMA_VERSION,
        "catalog_id": CATALOG_ID,
        "catalog_version": CATALOG_VERSION,
    }
    if any(value.get(key) != expected_value for key, expected_value in expected.items()):
        raise ContractChangedError("user report field catalog identity changed")
    if not _valid_text(value.get("source")) or tuple(value.get("groups", ())) != GROUPS:
        raise ContractChangedError("user report field catalog identity changed")
    fields = value.get("fields")
    if not isinstance(fields, list) or not fields:
        raise ContractChangedError("user report field catalog has no fields")
    names: set[str] = set()
    for row in fields:
        _validate_row(row, names)


def _validate_row(value: Any, names: set[str]) -> None:
    if not isinstance(value, Mapping) or set(value) != _ROW_KEYS:
        raise ContractChangedError("user report field catalog row shape changed")
    validators = {
        "name": lambda item: _valid_text(item, limit=256),
        "cname": lambda item: _valid_text(item, limit=256),
        "description": lambda item: _valid_text(item, limit=500),
        "group": lambda item: item in GROUPS,
        "type": lambda item: isinstance(item, str) and item in _FIELD_TYPES,
        "default": lambda item: type(item) is bool,
        "selection": lambda item: isinstance(item, str) and item in _SELECTIONS,
    }
    if any(not validator(value.get(key)) for key, validator in validators.items()):
        raise ContractChangedError("user report field catalog row is invalid")
    name = str(value["name"])
    if name in names:
        raise ContractChangedError("user report field catalog row is invalid")
    names.add(name)


def _valid_text(value: Any, *, limit: int | None = None) -> bool:
    return isinstance(value, str) and bool(value) and (limit is None or len(value) <= limit)


__all__ = [
    "CATALOG_ID",
    "CATALOG_VERSION",
    "GROUPS",
    "KIND",
    "OPERATION_ID",
    "SCHEMA_VERSION",
    "SOURCE",
    "catalog_document",
    "catalog_metadata",
    "catalog_rows",
    "search_rows",
    "validate_group",
]
