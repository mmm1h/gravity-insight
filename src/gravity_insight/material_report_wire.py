"""Canonical wire codec for the App-bound material report."""

from __future__ import annotations

import json
from typing import Any, Mapping

from .errors import PolicyViolation
from .material_metrics import DEFAULT_GRAVITY_METRICS, DEFAULT_MEDIA_METRICS
from .wire import canonical_wire_snapshot


_TIME_LINES = {
    "tencent": frozenset({"REPORTING_TIME", "REQUEST_TIME", "ACTIVE_TIME"}),
    "bytedance": frozenset({"bytedance_std"}),
}


def material_report_request_parts(
    values: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build an App-bound material report from catalog-validated inputs."""

    platform = values.get("platform")
    metrics = values.get("metrics_list", DEFAULT_MEDIA_METRICS.get(str(platform)))
    if metrics is None:
        raise PolicyViolation(
            "aggregate material reports require an explicit metrics_list"
        )
    gravity_metrics = values.get("gravity_metrics_list", DEFAULT_GRAVITY_METRICS)
    date_dims = values.get("date_dims", "total")
    data_dims = values.get("data_dims", ["material"])
    relate_dims = values.get("relate_dims", [])
    stat_list = values.get("stat_list", [])
    order_by = values.get("order_by", [])
    _validate_unique_inputs(
        metrics, gravity_metrics, data_dims, relate_dims, stat_list
    )
    time_line = values.get("time_line")
    if time_line is not None and time_line not in _TIME_LINES.get(
        str(platform), frozenset()
    ):
        raise PolicyViolation(
            "material report time_line does not match the selected platform"
        )
    order_fields = set(metrics) | set(gravity_metrics)
    if date_dims != "total":
        order_fields.add("stat_time")
    if any(
        not isinstance(item, Mapping) or item.get("field") not in order_fields
        for item in order_by
    ):
        raise PolicyViolation(
            "material report order_by must use selected metrics or stat_time"
        )
    body = _body(
        values,
        platform=platform,
        metrics=metrics,
        gravity_metrics=gravity_metrics,
        date_dims=date_dims,
        data_dims=data_dims,
        relate_dims=relate_dims,
        stat_list=stat_list,
        order_by=order_by,
    )
    if values.get("decimal_point") is not None:
        body["decimal_point"] = values["decimal_point"]
    if time_line is not None:
        body["time_line"] = time_line
    isolated = json.loads(canonical_wire_snapshot({}, body))
    return isolated["query"], isolated["body"]


def _validate_unique_inputs(*values: Any) -> None:
    fields = (
        "metrics_list", "gravity_metrics_list", "data_dims", "relate_dims",
        "stat_list",
    )
    for field, selected in zip(fields, values, strict=True):
        if len(set(selected)) != len(selected):
            raise PolicyViolation(f"material report {field} must be unique")


def _body(
    values: Mapping[str, Any],
    **parts: Any,
) -> dict[str, Any]:
    return {
        "data_dims": list(parts["data_dims"]),
        "date_dims": parts["date_dims"],
        "metrics_list": list(parts["metrics"]),
        "gravity_metrics_list": list(parts["gravity_metrics"]),
        "stat_list": list(parts["stat_list"]),
        "filters": [
            {
                "field": "ad_platform",
                "operator": "EQUALS",
                "values": [parts["platform"]],
            },
            {
                "field": "app_id",
                "operator": "IN",
                "values": values.get("app_list"),
            },
        ],
        "date_list": values.get("date_list"),
        "relate_dims": list(parts["relate_dims"]),
        "order_by": [dict(item) for item in parts["order_by"]],
        "page": values.get("page", 1),
        "page_size": values.get("page_size", 10),
    }


__all__ = ["material_report_request_parts"]
