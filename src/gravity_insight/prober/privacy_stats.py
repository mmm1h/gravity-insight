"""Aggregate response value shapes without retaining or emitting business values."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
import math
import re
from typing import Any, Mapping, Sequence

from .privacy import safe_schema_key


_EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_PHONE = re.compile(r"^(?:\+?86[- ]?)?1[3-9]\d{9}$")
_CN_ID = re.compile(r"^(?:\d{15}|\d{17}[0-9Xx])$")
_CN_NAME = re.compile(r"^[\u3400-\u9fff]{2,4}$")
_ORGANIZATION_MARKER = re.compile(
    r"(?:公司|集团|科技|网络|信息|传媒|文化|有限|股份|企业|"
    r"工作室|商行|经营部|合作社|事务所|研究院|学校|医院|中心|厂|店)"
)
_INDIVIDUAL_BUSINESS_MARKER = re.compile(
    r"(?:个体工商户|个人经营|工作室|商行|经营部|店)"
)
_URL = re.compile(r"^(?:https?|ftp)://", re.IGNORECASE)
_ENUM_TOKEN = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]*$")
_NUMERIC_TEXT = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$")


def _json_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, Mapping):
        return "object"
    return "unknown"


def _digest(value: Any) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _percentile(values: Sequence[int], percentile: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return ordered[index]


class _FieldProfile:
    def __init__(self) -> None:
        self.occurrences = 0
        self.types: Counter[str] = Counter()
        self.scalar_types: Counter[str] = Counter()
        self.string_lengths: list[int] = []
        self.container_lengths: list[int] = []
        self.distinct_digests: set[str] = set()
        self.patterns: Counter[str] = Counter()
        self.object_keys: Counter[str] = Counter()

    def add(self, value: Any) -> None:
        self.occurrences += 1
        value_type = _json_type(value)
        self.types[value_type] += 1
        self.distinct_digests.add(_digest(value))
        if isinstance(value, Mapping):
            self.container_lengths.append(len(value))
            self.object_keys.update(safe_schema_key(key) for key in value)
            for child in value.values():
                self._add_scalar(child)
        elif isinstance(value, list):
            self.container_lengths.append(len(value))
            for child in value:
                self._add_scalar(child)
        else:
            self._add_scalar(value)

    def _add_scalar(self, value: Any) -> None:
        if isinstance(value, list):
            for child in value:
                self._add_scalar(child)
            return
        if isinstance(value, Mapping):
            self.object_keys.update(safe_schema_key(key) for key in value)
            return
        value_type = _json_type(value)
        self.scalar_types[value_type] += 1
        if not isinstance(value, str):
            return
        self.string_lengths.append(len(value))
        stripped = value.strip()
        checks = {
            "blank": not stripped,
            "email": bool(_EMAIL.fullmatch(stripped)),
            "phone": bool(_PHONE.fullmatch(stripped)),
            "cn_id": bool(_CN_ID.fullmatch(stripped)),
            "cn_name_shape": bool(_CN_NAME.fullmatch(stripped)),
            "organization_marker": bool(_ORGANIZATION_MARKER.search(stripped)),
            "individual_business_marker": bool(
                _INDIVIDUAL_BUSINESS_MARKER.search(stripped)
            ),
            "url": bool(_URL.match(stripped)),
            "enum_token": bool(_ENUM_TOKEN.fullmatch(stripped)),
            "numeric_text": bool(_NUMERIC_TEXT.fullmatch(stripped)),
            "multiline": "\n" in value or "\r" in value,
            "long_text": len(value) > 80,
        }
        self.patterns.update(name for name, matched in checks.items() if matched)

    def document(self) -> dict[str, Any]:
        scalar_count = sum(self.scalar_types.values())
        string_count = self.scalar_types.get("string", 0)
        result: dict[str, Any] = {
            "occurrences": self.occurrences,
            "types": dict(sorted(self.types.items())),
            "scalar_types": dict(sorted(self.scalar_types.items())),
            "distinct_count": len(self.distinct_digests),
            "distinct_ratio": round(
                len(self.distinct_digests) / self.occurrences, 4
            ) if self.occurrences else 0.0,
            "pii_shape_matches": {
                name: self.patterns.get(name, 0)
                for name in ("email", "phone", "cn_id", "cn_name_shape")
            },
        }
        if self.string_lengths:
            result["string_length"] = {
                "min": min(self.string_lengths),
                "p50": _percentile(self.string_lengths, 0.5),
                "p95": _percentile(self.string_lengths, 0.95),
                "max": max(self.string_lengths),
            }
            result["string_patterns"] = {
                name: {
                    "count": self.patterns.get(name, 0),
                    "ratio": round(self.patterns.get(name, 0) / string_count, 4),
                }
                for name in (
                    "blank", "enum_token", "numeric_text", "url", "multiline",
                    "long_text", "organization_marker",
                    "individual_business_marker",
                )
            }
        if self.container_lengths:
            result["container_length"] = {
                "min": min(self.container_lengths),
                "p50": _percentile(self.container_lengths, 0.5),
                "p95": _percentile(self.container_lengths, 0.95),
                "max": max(self.container_lengths),
            }
        if self.object_keys:
            result["object_keys"] = sorted(self.object_keys)
        result["scalar_count"] = scalar_count
        return result


def profile_named_fields(
    payload: Any, field_names: Sequence[str]
) -> dict[str, dict[str, Any]]:
    """Profile matching mapping keys recursively, returning no source values."""

    requested = {str(name).casefold() for name in field_names}
    profiles = {name: _FieldProfile() for name in sorted(requested)}

    def visit(value: Any) -> None:
        if isinstance(value, Mapping):
            for raw_key, child in value.items():
                name = str(raw_key).casefold()
                if name in profiles:
                    profiles[name].add(child)
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(payload)
    return {
        name: profile.document()
        for name, profile in profiles.items()
        if profile.occurrences
    }
