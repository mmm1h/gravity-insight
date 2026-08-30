"""Generate proven Gravity Web configs from compact Analysis specs."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from ._field_policy_analysis import validate_analysis_shape
from .analysis_spec import compile_query_spec
from .dashboard_artifact import compile_dashboard_chart
from .dashboard_artifact_contract import BODY_FIELDS, SUBJECT_KINDS, UI_FIELDS
from .domains import ANALYSIS_QUERY_OPERATIONS
from .errors import UnsupportedOperationError


_ENVELOPE_FIELDS = frozenset(
    {"app_id", "date_list", "offset", "query_id", "total_calc_type", "week_first_day"}
)
_SUBJECTS = {kind: subject for subject, kind in SUBJECT_KINDS.items()}
_SYNTHETIC_DATE = "2000-01-01"


def generate_saved_analysis_config(
    kind: str,
    spec: Mapping[str, Any],
    *,
    workspace: Any,
    app: str | int,
    start: str | None = None,
    end: str | None = None,
) -> dict[str, Any]:
    """Compile one compact spec into a strict, round-trip-safe Web config."""

    compiled = compile_query_spec(
        kind, spec, workspace=workspace, app=app, start=start, end=end
    )
    inputs = compiled.inputs
    body = {
        key: copy.deepcopy(value)
        for key, value in inputs.items()
        if key in BODY_FIELDS[compiled.kind] and key not in _ENVELOPE_FIELDS
    }
    if compiled.kind == "event":
        body.update(
            {
                "app_id": int(inputs["app_id"]),
                "date_list": copy.deepcopy(inputs["date_list"]),
                "custom_query_item_list": [],
            }
        )
    config = _web_config(compiled.kind, inputs, body)
    _require_registered_fields(compiled.kind, config)
    replay_start, replay_end = _replay_window(compiled.kind, inputs)
    replay = compile_dashboard_chart(
        _OfflineValidator(),
        {
            "report_id": "generated",
            "name": "generated",
            "subject": _SUBJECTS[compiled.kind],
            "config": config,
        },
        app_id=inputs["app_id"],
        start=replay_start,
        end=replay_end,
    )
    _require_semantic_round_trip(compiled.kind, inputs, replay.inputs)
    return config


def _web_config(
    kind: str, inputs: Mapping[str, Any], body: dict[str, Any]
) -> dict[str, Any]:
    config: dict[str, Any] = {"calculateBody": body}
    if kind == "event":
        config.update(
            {
                "aggregate_config": copy.deepcopy(inputs.get("aggregate_config", {})),
                "tableShowType": (
                    "level" if inputs.get("return_hierarchy_list") is True else "table"
                ),
            }
        )
        grain = _create_time_grain(inputs.get("group_by_list"))
        if grain is not None:
            config["groupByCreateTime"] = {"value": grain}
    elif kind == "funnel":
        config["seriesType"] = (
            "line" if inputs.get("to_calc_each_day") is True else "bar"
        )
    elif kind == "retention":
        grain = _single_time_group(body)
        body["group_by_list"] = []
        config.update(
            {
                "cascaderValue": [grain, "custom"],
                "cascaderInput": inputs["offset"],
                "is_total_calc": inputs["total_calc_type"] != "DAY",
                "total_calc_type": {
                    "WEEK": "total_week",
                    "MONTH": "total_month",
                }.get(inputs["total_calc_type"], "total_week"),
                "week_first_day": inputs["week_first_day"],
            }
        )
    elif kind == "scatter":
        grain = _single_time_group(body)
        config.update(
            {
                "groupByCreateTime": {"value": grain},
                "seriesType": "scatter_bar",
            }
        )
    return config


def _single_time_group(body: dict[str, Any]) -> Any:
    groups = body.get("group_by_list")
    if not isinstance(groups, list) or len(groups) != 1:
        _unsupported_round_trip("group_by_list")
    group = groups[0]
    if not isinstance(group, Mapping) or group.get("field") != "create_time":
        _unsupported_round_trip("group_by_list")
    grain = group.get("group_by")
    return grain


def _create_time_grain(value: Any) -> Any:
    if not isinstance(value, list):
        return None
    groups = [
        item
        for item in value
        if isinstance(item, Mapping) and item.get("field") == "create_time"
    ]
    if not groups:
        return None
    if len(groups) != 1:
        _unsupported_round_trip("group_by_list")
    return groups[0].get("granularity", groups[0].get("group_by"))


def _require_registered_fields(kind: str, config: Mapping[str, Any]) -> None:
    unknown_ui = set(config) - UI_FIELDS[kind]
    body = config.get("calculateBody")
    unknown_body = (
        set(body) - BODY_FIELDS[kind]
        if isinstance(body, Mapping)
        else {"calculateBody"}
    )
    if unknown_ui or unknown_body:
        _unsupported_round_trip("registered_fields")


def _replay_window(kind: str, inputs: Mapping[str, Any]) -> tuple[str, str]:
    if kind == "property":
        return _SYNTHETIC_DATE, _SYNTHETIC_DATE
    date_list = inputs.get("date_list")
    if not isinstance(date_list, list) or len(date_list) != 1:
        _unsupported_round_trip("date_list")
    item = date_list[0]
    if not isinstance(item, Mapping):
        _unsupported_round_trip("date_list")
    return str(item.get("start_date")), str(item.get("end_date"))


def _require_semantic_round_trip(
    kind: str, direct: Mapping[str, Any], replay: Mapping[str, Any]
) -> None:
    left, right = _semantic_inputs(direct), _semantic_inputs(replay)
    if left == right:
        return
    differing = sorted(
        key for key in set(left) | set(right) if left.get(key) != right.get(key)
    )
    _unsupported_round_trip(",".join(differing) or kind)


def _semantic_inputs(value: Mapping[str, Any]) -> dict[str, Any]:
    normalized = copy.deepcopy(dict(value))
    normalized.pop("query_id", None)
    for key, empty in (
        ("custom_query_item_list", []),
        ("aggregate_config", {}),
        ("return_hierarchy_list", False),
        ("split_event", {}),
        ("user_re_attribute_filtering", {}),
    ):
        if normalized.get(key) == empty:
            normalized.pop(key)
    return normalized


def _unsupported_round_trip(fields: str) -> None:
    raise UnsupportedOperationError(
        "compact Analysis spec cannot be represented by the proven saved Web config "
        f"without changing semantics ({fields})",
        field="config",
        next_action=(
            "Remove the reported non-representable controls, or provide a proven Web "
            "artifact whose config already contains calculateBody."
        ),
    )


class _OfflineValidator:
    @staticmethod
    def validate(operation_id: str, inputs: Mapping[str, Any]) -> dict[str, Any]:
        kind = next(
            (
                name
                for name, selected in ANALYSIS_QUERY_OPERATIONS.items()
                if selected == operation_id
            ),
            None,
        )
        if kind is None:
            _unsupported_round_trip("operation_id")
        validate_analysis_shape(kind, inputs)
        return {"ok": True, "status": "valid_offline"}

__all__ = ["generate_saved_analysis_config"]
