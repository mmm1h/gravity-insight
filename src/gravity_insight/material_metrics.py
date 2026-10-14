"""Versioned material metric discovery and execution validation."""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from .actionable_error_values import actual_value
from .errors import ContractChangedError, InputValidationError


SCHEMA_VERSION = "gravity.material-metric-catalog.v1"
CATALOG_ID = "gravity.material-metrics"
CATALOG_VERSION = 1
KIND = "material_metric"
SOURCE = "material_metrics"
OPERATION_ID = ".".join(("material", "report", "query"))
CATALOG_PLATFORMS = (
    "aggregate",
    "bytedance",
    "tencent",
    "kuaishou",
    "gravity",
)
REPORT_PLATFORMS = (
    "aggregate",
    "bytedance",
    "tencent",
    "kuaishou",
    "bilibili",
)
DEFAULT_MEDIA_METRICS: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {
        "bytedance": ("stat_cost", "ctr", "convert_rate"),
        "tencent": ("cost", "ctr", "conversions_rate"),
        "kuaishou": ("charge", "action_ratio", "conversion_ratio"),
        "bilibili": ("cost", "click_rate"),
    }
)
DEFAULT_GRAVITY_METRICS = (
    "AppRealRegisterCnt",
    "AppGamePayUserCntStandardAtv",
)
_CATALOG_PATH = (
    Path(__file__).resolve().parent
    / "contracts"
    / "catalogs"
    / "material-metrics.v1.json"
)
_DOCUMENT_KEYS = {
    "schema_version",
    "catalog_id",
    "catalog_version",
    "source",
    "platforms",
    "metrics",
}
_ROW_KEYS = {"platform", "name", "cname", "tip"}


@lru_cache(maxsize=1)
def catalog_document() -> Mapping[str, Any]:
    try:
        document = json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ContractChangedError("material metric catalog is unavailable") from exc
    _validate_document(document)
    return MappingProxyType(document)


def catalog_rows(platform: str | None = None) -> tuple[Mapping[str, Any], ...]:
    selected = validate_catalog_platform(platform) if platform is not None else None
    return tuple(
        MappingProxyType(dict(row))
        for row in catalog_document()["metrics"]
        if selected is None or row["platform"] == selected
    )


def catalog_metadata() -> dict[str, Any]:
    document = catalog_document()
    encoded = json.dumps(
        dict(document), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    counts = {
        platform: len(catalog_rows(platform)) for platform in CATALOG_PLATFORMS
    }
    return {
        "catalog_id": CATALOG_ID,
        "catalog_version": CATALOG_VERSION,
        "catalog_sha256": hashlib.sha256(encoded).hexdigest(),
        "metric_count": len(document["metrics"]),
        "platforms": list(CATALOG_PLATFORMS),
        "platform_counts": counts,
    }


def metric_names(platform: str) -> frozenset[str]:
    selected = validate_catalog_platform(platform)
    return frozenset(str(row["name"]) for row in catalog_rows(selected))


def search_rows(
    query: str = "", *, platform: str | None = None
) -> list[dict[str, Any]]:
    if not isinstance(query, str):
        raise InputValidationError(
            f"actual value: {actual_value(query)}; material metric query must be a string",
            field="query",
        )
    selected = validate_catalog_platform(platform) if platform is not None else None
    normalized = query.strip().casefold()
    results: list[dict[str, Any]] = []
    for index, row in enumerate(catalog_rows(selected)):
        score = _score(normalized, row)
        if normalized and score == 0:
            continue
        results.append({"row_index": index, "score": score, "payload": dict(row)})
    return sorted(results, key=lambda item: (-item["score"], item["row_index"]))


def is_metric_identity(value: str) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    selected = value.strip().casefold()
    return any(
        selected in {str(row["name"]).casefold(), str(row["cname"]).casefold()}
        for row in catalog_rows()
    )


def validate_catalog_platform(value: Any) -> str:
    if not isinstance(value, str) or value not in CATALOG_PLATFORMS:
        raise InputValidationError(
            f"actual value: {actual_value(value)}; material metric platform must be one of "
            f"{actual_value(list(CATALOG_PLATFORMS))}",
            field="platform",
        )
    return value


def validate_report_metrics(
    platform: str,
    metrics: Sequence[str],
    gravity_metrics: Sequence[str],
) -> None:
    if platform not in REPORT_PLATFORMS:
        raise InputValidationError(
            f"actual value: {actual_value(platform)}; allowed material report platforms: "
            f"{actual_value(list(REPORT_PLATFORMS))}",
            field="platform",
            next_action="Choose a documented material report platform and retry.",
        )
    selected = _metric_tuple(metrics, "metrics_list", minimum=1)
    gravity = _metric_tuple(gravity_metrics, "gravity_metrics_list", minimum=0)
    media_allowed = (
        frozenset(DEFAULT_MEDIA_METRICS[platform])
        if platform == "bilibili"
        else metric_names(platform)
    )
    missing = sorted(set(selected) - media_allowed)
    if missing:
        action = (
            "Use the fixed bilibili material profile."
            if platform == "bilibili"
            else "Run `gravity metadata vocabulary --kind material_metric "
            f"--platform {platform}` and retry with listed metrics."
        )
        raise InputValidationError(
            f"actual value: {actual_value(missing)}; metrics are outside the versioned "
            f"{platform} material catalog",
            field="metrics_list",
            next_action=action,
        )
    gravity_missing = sorted(set(gravity) - metric_names("gravity"))
    if gravity_missing:
        raise InputValidationError(
            f"actual value: {actual_value(gravity_missing)}; metrics are outside the "
            "versioned Gravity material catalog",
            field="gravity_metrics_list",
            next_action=(
                "Run `gravity metadata vocabulary --kind material_metric --platform "
                "gravity` and retry with listed metrics."
            ),
        )


def _metric_tuple(value: Sequence[str], field: str, *, minimum: int) -> tuple[str, ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise InputValidationError(
            f"actual value: {actual_value(value)}; {field} must be an array",
            field=field,
        )
    selected = tuple(value)
    if (
        not minimum <= len(selected) <= 500
        or any(not isinstance(item, str) or not item or len(item) > 256 for item in selected)
        or len(set(selected)) != len(selected)
    ):
        raise InputValidationError(
            f"actual value: {actual_value(selected)}; {field} must contain {minimum} "
            "through 500 unique metric names",
            field=field,
        )
    return selected


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
    return 20 if query in str(row["tip"]).casefold() else 0


def _validate_document(value: Any) -> None:
    if not isinstance(value, Mapping) or set(value) != _DOCUMENT_KEYS:
        raise ContractChangedError("material metric catalog shape changed")
    _validate_identity(value)
    rows = value.get("metrics")
    if not isinstance(rows, list) or not rows:
        raise ContractChangedError("material metric catalog has no metrics")
    identities: set[tuple[str, str]] = set()
    names_by_platform = {platform: set() for platform in CATALOG_PLATFORMS}
    for row in rows:
        platform, name = _validate_row(row, identities)
        names_by_platform[platform].add(name)
    _validate_coverage(names_by_platform)


def _validate_identity(value: Mapping[str, Any]) -> None:
    invalid = (
        value.get("schema_version") != SCHEMA_VERSION
        or value.get("catalog_id") != CATALOG_ID
        or value.get("catalog_version") != CATALOG_VERSION
        or tuple(value.get("platforms", ())) != CATALOG_PLATFORMS
        or not isinstance(value.get("source"), str)
        or not value["source"]
    )
    if invalid:
        raise ContractChangedError("material metric catalog identity changed")


def _validate_coverage(names: Mapping[str, set[str]]) -> None:
    if set(names) != set(CATALOG_PLATFORMS) or any(not value for value in names.values()):
        raise ContractChangedError("material metric catalog platform coverage changed")
    for platform, defaults in DEFAULT_MEDIA_METRICS.items():
        if platform != "bilibili" and not set(defaults) <= names[platform]:
            raise ContractChangedError("material metric defaults left the catalog")
    if not set(DEFAULT_GRAVITY_METRICS) <= names["gravity"]:
        raise ContractChangedError("Gravity material defaults left the catalog")


def _valid_text(value: Any, limit: int) -> bool:
    return isinstance(value, str) and bool(value) and len(value) <= limit


def _validate_row(
    row: Any, identities: set[tuple[str, str]]
) -> tuple[str, str]:
    if not isinstance(row, Mapping) or set(row) != _ROW_KEYS:
        raise ContractChangedError("material metric catalog row shape changed")
    platform = row.get("platform")
    name = row.get("name")
    identity = str(platform), str(name)
    valid = (
        platform in CATALOG_PLATFORMS
        and _valid_text(name, 256)
        and _valid_text(row.get("cname"), 256)
        and isinstance(row.get("tip"), str)
        and len(row["tip"]) <= 1000
        and identity not in identities
    )
    if not valid:
        raise ContractChangedError("material metric catalog row is invalid")
    identities.add(identity)
    return identity


__all__ = [
    "CATALOG_ID",
    "CATALOG_PLATFORMS",
    "CATALOG_VERSION",
    "DEFAULT_GRAVITY_METRICS",
    "DEFAULT_MEDIA_METRICS",
    "KIND",
    "OPERATION_ID",
    "REPORT_PLATFORMS",
    "SCHEMA_VERSION",
    "SOURCE",
    "catalog_document",
    "catalog_metadata",
    "catalog_rows",
    "metric_names",
    "is_metric_identity",
    "search_rows",
    "validate_catalog_platform",
    "validate_report_metrics",
]
