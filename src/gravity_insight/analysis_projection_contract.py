"""Shared value-shape rules for dynamic Analysis response projection."""

from __future__ import annotations

import math
import re
from typing import TYPE_CHECKING, Any, Mapping, Sequence

from .errors import ManifestError

if TYPE_CHECKING:
    from .models import OperationSpec


ANALYSIS_SAFE_RESPONSE_SCALARS = frozenset(
    {
        "day",
        "hour",
        "minute",
        "month",
        "total",
        "week",
        "PresetAllCount",
        "PresetUserCount",
        # Retention v2 reports its aggregation mode alongside the buckets.
        "SUM",
        "WEIGHTED_AVG",
        "DAY",
        "WEEK",
        "MONTH",
    }
)
# Time-bucket keys: day with optional timestamp, plus the month (``2026-08``)
# and ISO week (``2026-W32``) buckets Retention v2 reports.
ANALYSIS_DATE_RESPONSE_KEY_RE = re.compile(
    r"^\d{4}-(?:W\d{2}"
    r"|\d{2}(?:-\d{2}(?:[T ]\d{2}(?::\d{2}){0,2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)?)?)$"
)
ANALYSIS_INDEX_RESPONSE_KEY_RE = re.compile(r"^(?:-?\d+(?:\.\d+)?%?|[xX]\d{1,3})$")
# Funnel aggregate_date.group keys are observed OS / empty-bucket labels, not
# request field names. Keep this closed: short identifier-like tokens only,
# and only under a ``group`` container so uid / group_cols stay fail-closed.
ANALYSIS_GROUP_LABEL_KEY_RE = re.compile(
    r"^(?:null|(?!uid$|group_cols$)[A-Za-z][A-Za-z0-9_]{0,31})$"
)
# Event-query innermost rows name the group with the property display name
# (``用户.设备类型`` for ``$os``), not the request field. Only that row
# container is opened; ``union_groups`` / ``y`` stay omitted as chart helpers,
# and uid / group_cols stay fail-closed because they are not 用户./事件. keys.
ANALYSIS_GROUP_DISPLAY_KEY_RE = re.compile(r"^(?:用户|事件)\.[^\x00-\x1f]{1,64}$")
# Scatter cells compose the group as ``{type}{field}`` (``user$os``). Only
# the innermost aggregate_date cell is opened; proc_zone / stat_total /
# aggregate_date_group stay omitted until they are themselves group labels.
ANALYSIS_COMPOSED_GROUP_KEY_RE = re.compile(
    r"^(?:user|event|default_event|default_user|user_property|user_re_attribute)"
    r"\$[A-Za-z][A-Za-z0-9_]{0,31}$"
)
_EVENT_QUERY_GROUP_ROW_PATH = ("list", "[]", "[]", "list", "[]")
ANALYSIS_EVENT_TOTAL_MEASURE_PATH = (*_EVENT_QUERY_GROUP_ROW_PATH, "cnt")
_SCATTER_GROUP_ROW_PATH = ("aggregate_date", "[]", "[]")
# Fingerprints are unique in the current catalog. A new groupable analysis
# route must match one of these data_key sets or the load-time invariant
# rejects it, so route 238 cannot silently reuse list-row allowlisting.
_ANALYSIS_GROUP_SHAPES: tuple[tuple[str, frozenset[str]], ...] = (
    ("event", frozenset({"list", "target_list"})),
    ("funnel", frozenset({"aggregate_date", "window_funnel_mode"})),
    ("scatter", frozenset({"aggregate_date", "zone_tags"})),
    ("retention", frozenset({"total", "date_to_week"})),
    ("property", frozenset({"list", "target"})),
)
# Sample labels prove the shape's opening exists. Shapes that keep the
# request field name itself (property) or a nested registered key
# (retention group_cols) have no extra dynamic-key opening.
ANALYSIS_GROUP_SHAPE_OPENINGS: Mapping[str, tuple[tuple[str, ...], str]] = {
    "event": (_EVENT_QUERY_GROUP_ROW_PATH, "用户.设备类型"),
    "funnel": (("aggregate_date", "group"), "android"),
    "scatter": (_SCATTER_GROUP_ROW_PATH, "user$os"),
}
ANALYSIS_NESTED_RESPONSE_KEYS_BY_SHAPE: Mapping[str, frozenset[str]] = {
    "event": frozenset(
        {
            "cname",
            "count",
            "data_type",
            "date_list",
            "end_date",
            "event_index",
            "field",
            "list",
            "name",
            "start_date",
            "target",
            "total",
            "value",
            "values",
            "阶段总和",
        }
    ),
    "funnel": frozenset(
        {"cnt", "count", "group", "rate", "ratio", "total", "value", "values"}
    ),
    "retention": frozenset(
        {
            "_final_one_result_sum",
            "_valid_day_count",
            "cumulative_average",
            "cumulative_total",
            "cumulative_uniques",
            "final_one_result",
            "final_one_result_day_count_sum",
            "first_event_user_total",
            "group_cols",
            "init_custom_before_components",
            "init_custom_before_num",
            "init_num",
            "is_total",
            "original_final_one_result",
            "percent_values",
            "percent_values_loss",
            "per_user",
            "period_calc_method",
            "period_event_total",
            "period_event_total_average",
            "period_user_total",
            "period_user_total_average",
            "time_diff",
            "to_use_final_one_result",
            "totals",
            "uniques",
            "values",
            "values_another_event",
            "values_loss",
        }
    ),
    "scatter": frozenset(
        {
            "aggregate_date",
            "count",
            "group",
            "total",
            "val",
            "val_list",
            "val_list_to_aggregate_date_group",
            "value",
            "values",
            "zone_tags",
        }
    ),
    "property": frozenset(
        {"cname", "data_type", "field", "method", "name", "target", "value"}
    ),
}
_DIMENSION_AXES = frozenset({"dims_list", "data_dims"})
_STRING_AXIS_ITEM_TYPES = frozenset({None, "string", "any"})


def analysis_group_shape(projection: Any) -> str | None:
    """Return the unique aggregate shape named by ``data_keys``, if any."""

    keys = frozenset(getattr(projection, "data_keys", ()))
    matches = [name for name, required in _ANALYSIS_GROUP_SHAPES if required <= keys]
    if len(matches) != 1:
        return None
    return matches[0]


def nested_analysis_response_keys(projection: Any) -> frozenset[str]:
    shape = analysis_group_shape(projection)
    if shape is None:
        return frozenset()
    return ANALYSIS_NESTED_RESPONSE_KEYS_BY_SHAPE[shape]


def validate_required_analysis_measures(
    projection: Any,
    projected: Mapping[str, Any],
    values: Mapping[str, Any],
    warnings: tuple[str, ...],
    drift: Any,
) -> tuple[dict[str, Any], tuple[str, ...], Any]:
    """Fail closed when scalar event rows lose their contracted count."""

    result = dict(projected)
    if analysis_group_shape(projection) != "event":
        return result, warnings, drift
    groups = values.get("group_by_list")
    if not isinstance(groups, (list, tuple)):
        return result, warnings, drift
    total_requested = any(
        isinstance(group, Mapping)
        and group.get("type") == "default_event"
        and group.get("field") == "create_time"
        and group.get("group_by") == "total"
        for group in groups
    )
    if not total_requested:
        return result, warnings, drift
    parents = _analysis_path_values(result, ANALYSIS_EVENT_TOTAL_MEASURE_PATH[:-1])
    key = ANALYSIS_EVENT_TOTAL_MEASURE_PATH[-1]
    violations = sum(
        not isinstance(parent, Mapping)
        or key not in parent
        or not _is_finite_number(parent[key])
        for parent in parents
    )
    if not violations:
        return result, warnings, drift
    warning = (
        "required analysis numeric measures are absent or invalid "
        f"(count={violations})"
    )
    return result, (*warnings, warning), drift.__class__.BREAKING


def validate_required_analysis_projection(
    projection: Any,
    projected: Mapping[str, Any],
    values: Mapping[str, Any],
    warnings: tuple[str, ...],
    drift: Any,
) -> tuple[dict[str, Any], tuple[str, ...], Any]:
    """Apply the measure and dimension contracts in one pass."""

    projected, warnings, drift = validate_required_analysis_measures(
        projection, projected, values, tuple(warnings), drift
    )
    return validate_required_analysis_dimensions(
        projection, projected, values, warnings, drift
    )


def validate_required_analysis_dimensions(
    projection: Any,
    projected: Mapping[str, Any],
    values: Mapping[str, Any],
    warnings: tuple[str, ...],
    drift: Any,
) -> tuple[dict[str, Any], tuple[str, ...], Any]:
    """Fail closed when a non-empty Funnel result loses its requested group."""

    result = dict(projected)
    missing = missing_funnel_grouping_fields(projection, result, values)
    if not missing:
        return result, warnings, drift
    warning = (
        "requested funnel user-property grouping dimensions are absent or invalid; "
        f"the response contains date-priority aggregates (count={len(missing)})"
    )
    return result, (*warnings, warning), drift.__class__.BREAKING


def missing_funnel_grouping_fields(
    projection: Any, projected: Mapping[str, Any], values: Mapping[str, Any]
) -> tuple[str, ...]:
    """Name the requested user-property groups the response failed to keep."""

    if analysis_group_shape(projection) != "funnel":
        return ()
    requested = _requested_funnel_user_group_fields(values)
    if not requested:
        return ()
    root = (
        projected.get("aggregate_by_date")
        if values.get("to_calc_each_day") is True
        else projected.get("aggregate_date")
    )
    if not _contains_finite_number(root):
        return ()
    labels = _funnel_group_labels(projected, values.get("to_calc_each_day") is True)
    if any(_is_contracted_funnel_group_label(item) for item in labels):
        return ()
    return requested


def _requested_funnel_user_group_fields(
    values: Mapping[str, Any],
) -> tuple[str, ...]:
    groups = values.get("group_by_list")
    if not isinstance(groups, (list, tuple)):
        return ()
    result = []
    for group in groups:
        if not isinstance(group, Mapping):
            continue
        if group.get("type") not in {"user", "user_property"}:
            continue
        field = group.get("field")
        if isinstance(field, str) and field:
            result.append(field)
    return tuple(dict.fromkeys(result))


def _funnel_group_labels(
    projected: Mapping[str, Any], calculate_each_day: bool
) -> tuple[Any, ...]:
    if not calculate_each_day:
        aggregate = projected.get("aggregate_date")
        groups = aggregate.get("group") if isinstance(aggregate, Mapping) else None
        return tuple(groups) if isinstance(groups, Mapping) else ()
    labels = []
    date_list = projected.get("date_list")
    if not isinstance(date_list, (list, tuple)):
        return ()
    for date_entry in date_list:
        if not isinstance(date_entry, Mapping):
            continue
        for rows in date_entry.values():
            if not isinstance(rows, (list, tuple)):
                continue
            labels.extend(
                row.get("group")
                for row in rows
                if isinstance(row, Mapping) and "group" in row
            )
    return tuple(labels)


def _is_contracted_funnel_group_label(value: Any) -> bool:
    return isinstance(value, str) and bool(
        ANALYSIS_GROUP_LABEL_KEY_RE.fullmatch(value.strip())
    )


def _contains_finite_number(value: Any) -> bool:
    if _is_finite_number(value):
        return True
    if isinstance(value, Mapping):
        return any(_contains_finite_number(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_contains_finite_number(item) for item in value)
    return False


def accepts_property_grouping(fields: Sequence[Any]) -> bool:
    """True when the caller can request a non-time property partition."""

    for field in fields:
        if field.name != "group_by_list":
            continue
        if field.type != "array" or field.item_type != "object":
            return False
        return field.max_items is None or field.max_items > 0
    return False


def is_groupable_analysis_query(fields: Sequence[Any], projection: Any) -> bool:
    return accepts_property_grouping(fields) and analysis_group_shape(projection) is not None


def operation_uses_dynamic_aggregate(operation: "OperationSpec") -> bool:
    return is_groupable_analysis_query(
        operation.input_fields, operation.response_projection
    )


def allowed_analysis_response_key(
    name: str,
    response_keys: set[str],
    path: tuple[str, ...] = (),
    numeric_paths: tuple[tuple[str, ...], ...] = (),
) -> bool:
    # A date under Funnel's group container is a mislabeled group, not a time
    # bucket. Apply the path-specific rule before the global date-key opening.
    if len(path) >= 2 and path[-2:] == ("aggregate_date", "group"):
        return _allowed_dynamic_group_label_key(name, path)
    if (
        name in response_keys
        or ANALYSIS_DATE_RESPONSE_KEY_RE.fullmatch(name)
        or ANALYSIS_INDEX_RESPONSE_KEY_RE.fullmatch(name)
        or _contracted_numeric_key_allowed((*path, name), numeric_paths)
    ):
        return True
    return _allowed_dynamic_group_label_key(name, path)


def analysis_numeric_path_allowed(
    path: tuple[str, ...], numeric_paths: tuple[tuple[str, ...], ...]
) -> bool:
    return any(
        len(pattern) == len(path)
        and all(
            expected == "*" or expected == actual
            for expected, actual in zip(pattern, path)
        )
        for pattern in numeric_paths
    )


def _contracted_numeric_key_allowed(
    path: tuple[str, ...], numeric_paths: tuple[tuple[str, ...], ...]
) -> bool:
    return any(
        pattern
        and pattern[-1] not in {"*", "[]"}
        and analysis_numeric_path_allowed(path, (pattern,))
        for pattern in numeric_paths
    )


def _analysis_path_values(value: Any, path: tuple[str, ...]) -> tuple[Any, ...]:
    if not path:
        return (value,)
    head, *tail = path
    remaining = tuple(tail)
    if head == "[]":
        if not isinstance(value, (list, tuple)):
            return ()
        return tuple(
            nested
            for item in value
            for nested in _analysis_path_values(item, remaining)
        )
    if not isinstance(value, Mapping) or head not in value:
        return ()
    return _analysis_path_values(value[head], remaining)


def _is_finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and (
        not isinstance(value, float) or math.isfinite(value)
    )


def allowed_analysis_response_scalar(
    value: str, response_keys: set[str], path: tuple[str, ...]
) -> bool:
    """Apply the Funnel daily group-value contract before scalar openings."""

    stripped = value.strip()
    if funnel_group_label_value_path(path):
        return bool(ANALYSIS_GROUP_LABEL_KEY_RE.fullmatch(stripped))
    return bool(
        stripped in response_keys
        or stripped in ANALYSIS_SAFE_RESPONSE_SCALARS
        or ANALYSIS_DATE_RESPONSE_KEY_RE.fullmatch(stripped)
        or ANALYSIS_INDEX_RESPONSE_KEY_RE.fullmatch(stripped)
    )


def funnel_group_label_value_path(path: tuple[str, ...]) -> bool:
    return bool(
        len(path) == 5
        and path[0:2] == ("date_list", "[]")
        and ANALYSIS_DATE_RESPONSE_KEY_RE.fullmatch(path[2])
        and path[3:] == ("[]", "group")
    )


def _allowed_dynamic_group_label_key(name: str, path: tuple[str, ...]) -> bool:
    if len(path) >= 2 and path[-2:] == ("aggregate_date", "group"):
        return bool(ANALYSIS_GROUP_LABEL_KEY_RE.fullmatch(name))
    if path == _EVENT_QUERY_GROUP_ROW_PATH:
        return bool(ANALYSIS_GROUP_DISPLAY_KEY_RE.fullmatch(name))
    return path == _SCATTER_GROUP_ROW_PATH and bool(
        ANALYSIS_COMPOSED_GROUP_KEY_RE.fullmatch(name)
    )


def funnel_mode_shape_changed(
    operation: "OperationSpec",
    data: Mapping[str, Any],
    values: Mapping[str, Any],
) -> bool:
    """Require the aggregate root selected by the requested funnel mode."""

    if analysis_group_shape(operation.response_projection) != "funnel":
        return False
    required_projection = (
        "aggregate_by_date" if values.get("to_calc_each_day") is True else "aggregate_date"
    )
    return not isinstance(data.get(required_projection), Mapping)


def validate_group_identity_invariant(
    fields: Sequence[Any],
    projection: Any,
    *,
    executable: bool = True,
    effect: str = "read",
) -> None:
    """Reject contracts that can request a group or identity they cannot keep.

    This is not "project every key". Chart helpers, ``uid``, and ``group_cols``
    stay fail-closed. The check only requires a known opening for the group
    or identity the caller actually asked for.
    """

    _validate_groupable_analysis_shape(fields, projection)
    if executable and effect == "read":
        _validate_dimension_axis_bindings(fields, projection)
    _validate_gravity_identity_aliases(projection)


def _validate_groupable_analysis_shape(fields: Sequence[Any], projection: Any) -> None:
    if not accepts_property_grouping(fields):
        return
    shape = analysis_group_shape(projection)
    if shape is None:
        raise ManifestError(
            "groupable analysis query must declare a known aggregate "
            "response shape so requested group labels survive projection"
        )
    opening = ANALYSIS_GROUP_SHAPE_OPENINGS.get(shape)
    if opening is None:
        return
    path, sample = opening
    if not allowed_analysis_response_key(sample, set(), path):
        raise ManifestError(
            "groupable analysis shape is registered but has no group-label opening"
        )


def _validate_dimension_axis_bindings(fields: Sequence[Any], projection: Any) -> None:
    bound_axes = _dynamically_bound_inputs(projection)
    declared = _projected_item_names(projection)
    for field in fields:
        if not _is_dimension_axis(field):
            continue
        if field.name in bound_axes:
            continue
        enum = {str(item) for item in field.item_enum or ()}
        if enum and enum <= declared:
            continue
        raise ManifestError(
            "requested dimension axis must stay visible: bind it as a "
            "dynamic item field or project every closed-enum dimension key"
        )


def _is_dimension_axis(field: Any) -> bool:
    if field.name not in _DIMENSION_AXES or field.type != "array":
        return False
    if field.max_items == 0:
        return False
    return field.item_type in _STRING_AXIS_ITEM_TYPES


def _dynamically_bound_inputs(projection: Any) -> set[str]:
    names = set(projection.dynamic_item_fields)
    for bound in projection.data_dynamic_item_fields.values():
        names.update(bound)
    return names


def _projected_item_names(projection: Any) -> set[str]:
    names = set(projection.item_keys)
    for keys in projection.data_item_keys.values():
        names.update(keys)
    return names


def _validate_gravity_identity_aliases(projection: Any) -> None:
    names = _projected_item_names(projection)
    if any(
        name.startswith("gravity_") and name[8:] and name[8:] not in names
        for name in names
    ):
        raise ManifestError(
            "gravity_* identity alias requires the real identifier to stay projected"
        )


__all__ = [
    "ANALYSIS_COMPOSED_GROUP_KEY_RE",
    "ANALYSIS_DATE_RESPONSE_KEY_RE",
    "ANALYSIS_EVENT_TOTAL_MEASURE_PATH",
    "ANALYSIS_GROUP_DISPLAY_KEY_RE",
    "ANALYSIS_GROUP_LABEL_KEY_RE",
    "ANALYSIS_INDEX_RESPONSE_KEY_RE",
    "ANALYSIS_GROUP_SHAPE_OPENINGS",
    "ANALYSIS_NESTED_RESPONSE_KEYS_BY_SHAPE",
    "ANALYSIS_SAFE_RESPONSE_SCALARS",
    "accepts_property_grouping",
    "allowed_analysis_response_scalar",
    "analysis_numeric_path_allowed",
    "allowed_analysis_response_key",
    "analysis_group_shape",
    "funnel_group_label_value_path",
    "funnel_mode_shape_changed",
    "is_groupable_analysis_query",
    "missing_funnel_grouping_fields",
    "nested_analysis_response_keys",
    "operation_uses_dynamic_aggregate",
    "validate_required_analysis_dimensions",
    "validate_required_analysis_measures",
    "validate_required_analysis_projection",
    "validate_group_identity_invariant",
]
