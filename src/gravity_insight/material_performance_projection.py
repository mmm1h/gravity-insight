"""Fail-closed row, summary, and query projection for material performance."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .errors import InputValidationError, ManifestError
from .models import load_operation_manifest
from .paths import MANIFEST_ROOT
from .promotion_performance_rows import safe_promotion_rows
from .composite_catalog import stable_operation


MATERIAL_REPORT_OPERATION = stable_operation(
    "material", "report", action="query"
).operation_id
MATERIAL_ROW_FIELDS = frozenset(
    {
        "file_name", "gravity_material_id", "material_id", "stat_cost", "ctr",
        "convert_rate", "cost", "conversions_rate", "charge", "action_ratio",
        "conversion_ratio", "click_rate", "AppRealRegisterCnt",
        "AppGamePayUserCntStandardAtv",
    }
)
MATERIAL_IDENTITY_FIELDS = frozenset(
    {"file_name", "gravity_material_id", "material_id"}
)


def material_performance_item_count(value: Any) -> int:
    if not isinstance(value, Mapping):
        return 0
    results = value.get("results")
    if not isinstance(results, list):
        return 0
    return sum(material_component_item_count(item) for item in results)


def material_component_item_count(value: Any) -> int:
    if not isinstance(value, Mapping) or value.get("ok") is not True:
        return 0
    data = value.get("data")
    rows = data.get("list") if isinstance(data, Mapping) else None
    return len(rows) if isinstance(rows, list) else 0


def _source_row_contract() -> tuple[frozenset[str], frozenset[str]]:
    operations = load_operation_manifest(MANIFEST_ROOT / "candidates.json")
    matches = tuple(
        operation
        for operation in operations
        if operation.operation_id == MATERIAL_REPORT_OPERATION
    )
    if len(matches) != 1:
        raise ManifestError(
            "compiled candidate manifest must contain one material report operation"
        )
    projection = matches[0].response_projection
    fields = frozenset(projection.item_keys)
    opaque = frozenset(projection.opaque_json_item_keys)
    if not fields or opaque - fields:
        raise ManifestError(
            "compiled material report row projection is internally inconsistent"
        )
    return fields, opaque


_SOURCE_FIELDS, _OPAQUE_FIELDS = _source_row_contract()
if MATERIAL_ROW_FIELDS - _SOURCE_FIELDS:
    raise ManifestError("material performance row fields must be registered source fields")


def safe_rows(value: Any) -> list[dict[str, Any]] | None:
    rows, failure = safe_rows_with_failure(value)
    return rows if failure is None else None


def safe_rows_with_failure(
    value: Any, *, profile: Any | None = None
) -> tuple[list[dict[str, Any]] | None, tuple[str, str] | None]:
    allowed = set(_SOURCE_FIELDS)
    public = set(MATERIAL_ROW_FIELDS)
    if profile is not None:
        dynamic = profile_row_fields(profile)
        allowed.update(dynamic)
        public = set(MATERIAL_IDENTITY_FIELDS) | dynamic
    rows, failure = safe_promotion_rows(
        value,
        allowed_fields=frozenset(allowed),
        opaque_fields=_OPAQUE_FIELDS,
    )
    if rows is None or failure is not None:
        return rows, failure
    return [
        {str(key): item for key, item in row.items() if key in public}
        for row in rows
    ], None


def project_success_data(
    data: Mapping[str, Any], profile: Any
) -> tuple[dict[str, Any] | None, tuple[str, str] | None]:
    rows, failure = safe_rows_with_failure(data.get("list"), profile=profile)
    if failure is not None or rows is None:
        return None, failure or ("row_projection", "$.data.data.list")
    result: dict[str, Any] = {"list": rows}
    if "total" in data:
        total, failure = safe_total(data.get("total"), profile)
        if failure is not None:
            return None, failure
        result["total"] = total
    if "update_at" in data:
        update_at = safe_update_at(data.get("update_at"))
        if update_at is None:
            return None, ("update_at_projection", "$.data.data.update_at")
        result["update_at"] = update_at
    return result, None


def profile_row_fields(profile: Any) -> set[str]:
    fields = set(profile.metrics) | set(profile.gravity_metrics)
    dimension = profile.data_dims[0]
    fields.add("material_id" if dimension == "material" else dimension)
    fields.update(profile.relate_dims)
    fields.update(profile.stat_list)
    if profile.date_dims != "total":
        fields.add("stat_time")
    return fields


def safe_total(
    value: Any, profile: Any
) -> tuple[dict[str, Any] | None, tuple[str, str] | None]:
    if value is None:
        return None, None
    rows, failure = safe_promotion_rows(
        [value],
        allowed_fields=frozenset(set(profile.metrics) | set(profile.gravity_metrics)),
        opaque_fields=frozenset(),
    )
    if failure is not None or rows is None or len(rows) != 1:
        return None, ("total_projection", "$.data.data.total")
    return rows[0], None


def safe_update_at(value: Any) -> dict[str, str | None] | None:
    allowed = {"aggregate", "bytedance", "tencent", "kuaishou", "bilibili"}
    if not isinstance(value, Mapping) or set(map(str, value)) - allowed:
        return None
    result: dict[str, str | None] = {}
    for key, item in value.items():
        if item is not None and (not isinstance(item, str) or len(item) > 128):
            return None
        result[str(key)] = item
    return result


def coerce_profile(value: Any) -> Any | None:
    if isinstance(value, Mapping):
        platform = value.get("platform")
        query = dict(value)
    else:
        platform = value if isinstance(value, str) else getattr(value, "platform", None)
        receipt = None if isinstance(value, str) else getattr(value, "receipt", None)
        query = receipt() if callable(receipt) else None
    try:
        from .material_performance import normalize_material_profiles

        query = query or {}
        profiles = normalize_material_profiles(
            (str(platform),),
            metrics={str(platform): query.get("metrics_list")}
            if "metrics_list" in query else None,
            gravity_metrics=query.get(
                "gravity_metrics_list",
                ("AppRealRegisterCnt", "AppGamePayUserCntStandardAtv"),
            ),
            date_grain=query.get("date_dims", "total"),
            data_dimension=(query.get("data_dims") or ["material"])[0],
            relate_dimensions=query.get("relate_dims", ()),
            statistics=query.get("stat_list", ()),
            order_by={str(platform): query.get("order_by", ())},
            decimal_point=query.get("decimal_point"),
            time_lines={str(platform): query["time_line"]}
            if query.get("time_line") is not None else None,
        )
        return profiles[0]
    except (InputValidationError, KeyError, TypeError, ValueError):
        return None


__all__ = [
    "MATERIAL_IDENTITY_FIELDS",
    "MATERIAL_REPORT_OPERATION",
    "MATERIAL_ROW_FIELDS",
    "coerce_profile",
    "material_component_item_count",
    "material_performance_item_count",
    "project_success_data",
    "safe_rows",
]
