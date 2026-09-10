"""Bounded material report to registration-day aggregate composition."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, timedelta
import math
from typing import Any

from .contracts.join_key import (
    JoinKeyContractError,
    join_key_registry,
    normalize_join_value,
    resolve_proven_join_key,
)
from .errors import ContractChangedError, GravityInsightError
from .material_game_contract import METRICS, normalize_request
from .material_game_result import envelope, gap, safe_failure, scan_receipt
from .material_performance_result import MATERIAL_REPORT_OPERATION, MATERIAL_ROW_FIELDS
from .result_audit import result_receipt_references
from .user_detail_registered_aggregate import aggregate_registered_day


def material_game_performance(
    client: Any, app_id: str | int, material_ids: Any, platform: str, **options: Any
) -> dict[str, Any]:
    request = normalize_request(app_id, material_ids, platform, **options)
    bounds = request["bounds"]
    materials = [_initial_material(value) for value in request["material_ids"]]
    days: list[dict[str, Any]] = []
    receipts: list[dict[str, Any]] = []
    budget = {
        **bounds,
        "user_pages_used": 0,
        "user_items_used": 0,
        "attempted_days": 0,
        "remaining_days": 0,
        "remaining_pages": None,
        "stopped_reason": None,
    }
    if request["object_type"] != "material":
        reason = _join_gap(request, None)
        for item in materials:
            item["join_key"] = reason
            item["matched_users"] = reason
        return envelope(request, materials, None, days, budget, receipts)
    if not _material_namespace_proven(platform):
        for item in materials:
            item["join_key"] = _join_gap(request, None)
            item["matched_users"] = item["join_key"]
        return envelope(request, materials, None, days, budget, receipts)
    try:
        native = client.read_limited(
            MATERIAL_REPORT_OPERATION,
            {
                "app_list": [request["app_id"]],
                "platform": platform,
                "date_list": [request["window"]["start"], request["window"]["end"]],
                "page": 1,
                "page_size": 10,
            },
            max_pages=bounds["max_report_pages"],
            max_items=bounds["max_report_pages"] * 10,
            max_workers=request["max_workers"],
        )
        rows, report_scan = _report_rows(native, bounds["max_report_pages"])
        receipts.extend(result_receipt_references(native))
    except GravityInsightError as exc:
        for item in materials:
            item["advertising"] = safe_failure(exc)
        budget["stopped_reason"] = "MATERIAL_REPORT_UNAVAILABLE"
        return envelope(request, materials, None, days, budget, receipts)
    report_scan["window"] = dict(request["window"])
    groups = []
    for index, item in enumerate(materials):
        group = _resolve_material(index, item, rows, report_scan, request)
        if group is not None:
            groups.append(group)
    if groups:
        _read_days(client, request, groups, materials, days, budget, receipts)
    _finish_metrics(materials, days)
    return envelope(request, materials, report_scan, days, budget, receipts)


def _initial_material(value: Any) -> dict[str, Any]:
    return {
        "material_id": value,
        "advertising": gap("MATERIAL_NOT_SCANNED", "Read the material report."),
        "join_key": gap("JOIN_KEY_NOT_RESOLVED", "Resolve the proven material namespace."),
        "matched_users": gap("USER_DATES_NOT_SCANNED", "Read the registration-day cohorts."),
        "metrics": {
            name: gap(
                "RETENTION_UNAVAILABLE" if name == "retention" else "METRIC_BINDING_REQUIRED",
                "Retention needs a separately proven cohort product."
                if name == "retention"
                else "Bind a project-owned scalar field and count_if condition; native numeric thresholds require numeric rows.",
            )
            for name in METRICS
        },
    }


def _join_gap(request: Mapping[str, Any], subtype: Any) -> dict[str, Any]:
    states = sorted(
        {
            item["namespace_status"]
            for item in join_key_registry()["mappings"]
            if item["platform"] == request["platform"] and item["object_type"] == request["object_type"]
        }
    )
    # The resolver, never the registry inspection, makes the eligibility decision.
    try:
        resolve_proven_join_key(request["platform"], request["object_type"], object_subtype=subtype)
    except JoinKeyContractError:
        pass
    return {
        **gap(
            "JOIN_KEY_NOT_SUPPORTED",
            "Only a proven material-level mapping can be used; no alternative slot will be tried.",
        ),
        "namespace_states": states or ["unregistered"],
    }


def _report_rows(native: Any, max_pages: int) -> tuple[list[Mapping[str, Any]], dict[str, Any]]:
    if (
        not isinstance(native, Mapping)
        or native.get("ok") is not True
        or native.get("status") not in {"success", "empty"}
    ):
        raise ContractChangedError("material report is unavailable")
    if native.get("operation_id") != MATERIAL_REPORT_OPERATION:
        raise ContractChangedError("material report source identity changed")
    data = native.get("data")
    rows = data.get("list") if isinstance(data, Mapping) else None
    if not isinstance(rows, list) or any(not isinstance(row, Mapping) for row in rows):
        raise ContractChangedError("material report row contract changed")
    scan = scan_receipt(native, max_pages=max_pages, max_items=max_pages * 10)
    if scan["items_scanned"] != len(rows):
        raise ContractChangedError("material report row count contradicts pagination")
    return rows, scan


def _advertising(rows: list[Mapping[str, Any]], scan: Mapping[str, Any]) -> dict[str, Any]:
    if not rows:
        code = (
            "MATERIAL_NOT_FOUND_IN_WINDOW"
            if scan["completeness"] == "complete" and scan["pagination_finished"]
            else "MATERIAL_NOT_FOUND_IN_SCANNED_PREFIX"
        )
        return gap(
            code,
            "Check the supplied App/platform/date window or increase the report budget; absence is not proven globally.",
        )
    if len(rows) != 1:
        return {
            **gap(
                "MATERIAL_REPORT_DUPLICATE_ROWS",
                "Resolve report row additivity before reporting a material total.",
            ),
            "observed_rows": len(rows),
        }
    values = {}
    for field in MATERIAL_ROW_FIELDS - {"material_id", "gravity_material_id", "file_name"}:
        value = rows[0].get(field)
        if (
            value is None
            or (isinstance(value, str) and len(value) <= 64)
            or (type(value) in {int, float} and math.isfinite(value))
        ):
            values[field] = value
    return {
        "status": "obtained"
        if scan["completeness"] == "complete" and scan["pagination_finished"]
        else "partial",
        "values": values,
        "observed_rows": 1,
        "completeness": scan["completeness"],
        "reason": None if scan["pagination_finished"] else "REPORT_SCAN_INCOMPLETE",
    }


def _window(rows: list[Mapping[str, Any]], requested: Mapping[str, Any]) -> dict[str, Any]:
    if requested["mode"] == "explicit":
        return dict(requested)
    dates = []
    for row in rows:
        value = row.get("create_time")
        try:
            if not isinstance(value, str) or len(value) > 64:
                raise ValueError
            dates.append(datetime.fromisoformat(value).date().isoformat())
        except (TypeError, ValueError):
            return gap(
                "MATERIAL_WINDOW_UNRESOLVED",
                "Supply explicit start/end; report create_time is missing or malformed.",
            )
    if not dates:
        return gap(
            "MATERIAL_WINDOW_UNRESOLVED",
            "Locate the material in the bounded report or supply explicit start/end.",
        )
    return {
        **requested,
        "start": min(requested["start"], min(dates)),
        "earliest_observed_create_date": min(dates),
        "delivery_bounds_proven": False,
    }


def _read_days(
    client: Any,
    request: Mapping[str, Any],
    groups: list[dict[str, Any]],
    materials: list[dict[str, Any]],
    days: list[dict[str, Any]],
    budget: dict[str, Any],
    receipts: list[dict[str, Any]],
) -> None:
    first = min(materials[int(group["key"])]["window"]["start"] for group in groups)
    start, end = date.fromisoformat(first), date.fromisoformat(request["window"]["end"])
    total_days = (end - start).days + 1
    budget.update({"total_days": total_days, "remaining_days": total_days, "next_date": first})
    for offset in range(min(total_days, budget["max_days"])):
        remaining_pages = budget["max_user_pages"] - budget["user_pages_used"]
        remaining_items = budget["max_user_items"] - budget["user_items_used"]
        if remaining_pages <= 0 or remaining_items <= 0:
            budget["stopped_reason"] = "USER_SCAN_BUDGET_EXHAUSTED"
            break
        day = (start + timedelta(days=offset)).isoformat()
        active = [group for group in groups if materials[int(group["key"])]["window"]["start"] <= day]
        budget["attempted_days"] += 1
        try:
            result = aggregate_registered_day(
                client,
                {"app_id": request["app_id"], "date": day},
                active,
                {key: value for key, value in request["metrics"].items() if key != "retention"},
                max_pages=remaining_pages,
                max_items=remaining_items,
                max_workers=request["max_workers"],
            )
        except GravityInsightError as exc:
            days.append(_failed_day(day, active, request["metrics"], exc))
            budget.update(
                {
                    "stopped_reason": "USER_SOURCE_FAILED",
                    "failed_date": day,
                    "failed_read_page_reservation": remaining_pages,
                    "failed_read_item_reservation": remaining_items,
                }
            )
            break
        scan = result["scan"]
        days.append({"date": day, "scan": scan, "cells": result["cells"]})
        receipts.extend(result["http_receipts"])
        budget["remaining_days"] -= 1
        _charge_scan(budget, scan)
        budget["next_date"] = (
            (start + timedelta(days=offset + 1)).isoformat() if offset + 1 < total_days else None
        )
        if scan and not scan["pagination_finished"]:
            budget.update(
                {
                    "stopped_reason": "USER_DAY_INCOMPLETE",
                    "incomplete_date": day,
                    "next_page": scan["next_page"],
                    "remaining_pages": scan["remaining_pages"],
                }
            )
            break
    if budget["stopped_reason"] is None and budget["remaining_days"]:
        budget["stopped_reason"] = "DAY_BUDGET_EXHAUSTED"


def _failed_day(
    day: str, groups: list[dict[str, Any]], metrics: Mapping[str, Any], exc: GravityInsightError
) -> dict[str, Any]:
    failure = safe_failure(exc)
    cells = {
        f"{group['key']}:{name}": failure
        for group in groups
        for name in ("matched_users", *metrics)
        if name != "retention"
    }
    return {"date": day, "scan": None, "error": failure, "cells": cells}


def _finish_metrics(materials: list[dict[str, Any]], days: list[dict[str, Any]]) -> None:
    for index, item in enumerate(materials):
        window = item.get("window", {})
        if "start" not in window or item["join_key"]["status"] != "proven":
            continue
        total = (date.fromisoformat(window["end"]) - date.fromisoformat(window["start"])).days + 1
        for name in ("matched_users", *METRICS):
            result = _metric_summary(index, name, window, total, days)
            if result is None:
                continue
            if result.get("observed_value") is not None:
                result = _platform_unverified(result)
            if name == "matched_users":
                result.update({"unit": "platform_scoped_users", "distinct_users": None})
                item[name] = result
            else:
                item["metrics"][name] = result


def _matching_material_rows(rows: list[Mapping[str, Any]], material_id: str | int) -> list[Mapping[str, Any]]:
    return [
        row
        for row in rows
        if type(row.get("material_id")) is type(material_id) and row["material_id"] == material_id
    ]


def _platform_unverified(result: Mapping[str, Any]) -> dict[str, Any]:
    return {
        **gap(
            "USER_PLATFORM_SCOPE_UNPROVEN",
            "Provide an independently proven user-side platform discriminator contract; slot evidence alone cannot exclude cross-platform ID collisions.",
        ),
        "candidate_observations": {
            **result,
            "value": None,
            "status": "diagnostic_only",
            "unit": "same_id_acquisition_rows",
            "platform_scope": "unproven",
        },
        "failures": result["failures"],
    }


def _resolve_material(
    index: int,
    item: dict[str, Any],
    rows: list[Mapping[str, Any]],
    report_scan: Mapping[str, Any],
    request: Mapping[str, Any],
) -> dict[str, Any] | None:
    platform = request["platform"]
    matches = _matching_material_rows(rows, item["material_id"])
    item["advertising"] = _advertising(matches, report_scan)
    if not matches and str(item["material_id"]) in {str(row.get("material_id")) for row in rows}:
        item["advertising"] = gap(
            "MATERIAL_ID_TYPE_MISMATCH",
            "Use the report ID JSON type; CLI --material-ids-json preserves integer or string IDs.",
        )
    item["window"] = _window(matches, request["window"])
    subtype = None
    if platform == "bytedance":
        types = {row.get("file_type") for row in matches if isinstance(row.get("file_type"), str)}
        if (
            len(types) != 1
            or not types <= {"image", "video"}
            or any(row.get("file_type") not in types for row in matches)
        ):
            item["join_key"] = gap(
                "MATERIAL_SUBTYPE_UNRESOLVED",
                "Supply a report window containing one unambiguous image/video subtype.",
            )
            item["matched_users"] = item["join_key"]
            return None
        subtype = next(iter(types))
    try:
        resolved = resolve_proven_join_key(platform, "material", object_subtype=subtype)
        value = normalize_join_value(resolved["mapping_id"], item["material_id"], side="left")
    except JoinKeyContractError:
        item["join_key"] = _join_gap(request, subtype)
        item["matched_users"] = item["join_key"]
        return None
    item["join_key"] = {"status": "proven", **resolved}
    if item["window"].get("status") == "unavailable":
        item["matched_users"] = item["window"]
        return None
    field = resolved["right"]["path"].rsplit(".", 1)[-1]
    return {"key": str(index), "condition": {"field": field, "operator": "EQUALS", "values": [value]}}


def _metric_summary(
    index: int, name: str, window: Mapping[str, Any], total: int, days: list[dict[str, Any]]
) -> dict[str, Any] | None:
    available, failures = _metric_observations(index, name, window, days)
    if not available and not failures:
        return None
    complete = len(available) == total and all(
        day["scan"]["completeness"] == "complete" for day, _ in available
    )
    value = sum(cell["value"] for _, cell in available) if available else None
    result = {
        "status": "obtained" if complete else "partial" if available else "unavailable",
        "observed_value": value,
        "value": value if complete else None,
        "requested_days": total,
        "observed_days": len(available),
        "missing_days": total - len(available),
        "failures": failures,
        "reason": "NO_SAME_ID_ROWS_OBSERVED"
        if value == 0
        else None
        if complete
        else "INCOMPLETE_OR_UNKNOWN_SOURCE",
    }
    if available and name != "matched_users":
        result["definition"] = available[0][1]["definition"]
    return result


def _metric_observations(
    index: int, name: str, window: Mapping[str, Any], days: list[dict[str, Any]]
) -> tuple[list[Any], list[Any]]:
    observations = [
        (day, day.get("cells", {}).get(f"{index}:{name}"))
        for day in days
        if window["start"] <= day["date"] <= window["end"]
    ]
    available = [(day, cell) for day, cell in observations if cell and cell["status"] == "obtained"]
    failures = [
        {"date": day["date"], **cell} for day, cell in observations if cell and cell["status"] != "obtained"
    ]
    return available, failures


def _charge_scan(budget: dict[str, Any], scan: Mapping[str, Any] | None) -> None:
    if scan is not None:
        budget["user_pages_used"] += scan["pages_scanned"]
        budget["user_items_used"] += scan["items_scanned"]


def _material_namespace_proven(platform: str) -> bool:
    return any(
        item["namespace_status"] == "proven"
        for item in join_key_registry()["mappings"]
        if item["platform"] == platform and item["object_type"] == "material"
    )
