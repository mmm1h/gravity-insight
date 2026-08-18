"""Composable, typed fragments for the existing compact Analysis Spec v1.

These objects add an immutable Python composition surface.  They deliberately
render only the already-registered compact spec and remain ``Mapping``-compatible
with the existing compiler, SDK, batch, and Plan preflight paths.
"""

from __future__ import annotations

import copy
import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ._field_policy_conditions import validate_analysis_conditions
from ._field_policy_shared import (
    ANALYSIS_TARGET_METHODS,
    ANALYSIS_USER_TYPES,
    new_analysis_references,
)
from .analysis_spec_schema import ANALYSIS_SPEC_KINDS
from .analysis_spec_validation import bounded_string, choice
from .errors import InputValidationError
from .actionable_error_values import actual_value


_DATA_TYPES = frozenset({"STRING", "INT", "FLOAT", "BOOL", "DATE", "DATETIME", "LIST"})
_SEGMENT_TYPES = frozenset({"LATEST", "DYNAMIC_MATCHING", "FIXED_VERSION"})
_QUANTILE_METHOD = re.compile(r"^Quantile(?:_(?:[1-9]|[1-9][0-9]|100))?$")
_DATED_KINDS = frozenset({"event", "funnel", "retention", "scatter"})
_STEP_LIMITS = {
    "event": (1, 50),
    "funnel": (2, 20),
    "retention": (2, 2),
    "scatter": (1, 1),
}


@dataclass(frozen=True)
class AnalysisFilter:
    """One reusable condition in the public compact Analysis vocabulary."""

    field: str
    operator: str
    field_type: str
    values: tuple[str | int | float | bool | None, ...] = ()
    by_list_index: bool | None = None
    list_index: int | None = None
    segment_type: str | None = None
    version_id: str | int | None = None
    dimension_table: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.values, tuple):
            if not isinstance(self.values, Sequence) or isinstance(
                self.values, (str, bytes, bytearray)
            ):
                raise InputValidationError(
                    f"actual value: {actual_value(type(self.values).__name__)}; "
                    "Analysis filter values must be a scalar sequence",
                    field="values",
                )
            object.__setattr__(self, "values", tuple(self.values))
        validate_analysis_conditions(
            [self.to_spec()], new_analysis_references(), "condition"
        )

    def to_spec(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "operator": self.operator,
            "field": self.field,
            "type": self.field_type,
            "value": list(self.values),
        }
        for key, value in (
            ("by_list_index", self.by_list_index),
            ("list_index_val", self.list_index),
            ("segment_type", self.segment_type),
            ("version_id", self.version_id),
            ("dim_using_table_name", self.dimension_table),
        ):
            if value is not None:
                result[key] = value
        return result


@dataclass(frozen=True)
class AnalysisCohort:
    """A typed reference to an existing Gravity segment, never a CRUD definition."""

    field: str
    segment_type: str = "LATEST"
    version_id: str | int | None = None

    def __post_init__(self) -> None:
        bounded_string(self.field, "cohort.field")
        choice(self.segment_type, set(_SEGMENT_TYPES), "cohort.segment_type")
        if self.segment_type == "FIXED_VERSION":
            if not isinstance(self.version_id, (str, int)) or isinstance(
                self.version_id, bool
            ):
                raise InputValidationError(
                    f"actual value: {actual_value(self.version_id)}; " + ("A fixed-version cohort requires a string or integer version id"),
                    field="cohort.version_id",
                )
        elif self.version_id not in {None, ""}:
            raise InputValidationError(
                f"actual value: {actual_value(self.version_id)}; " + ("A cohort version id requires segment_type FIXED_VERSION"),
                field="cohort.version_id",
            )

    def as_filter(self) -> AnalysisFilter:
        """Render the registered Analysis condition for this existing segment."""

        return AnalysisFilter(
            field=self.field,
            operator="EQUALS",
            field_type="user_segment",
            values=(True,),
            segment_type=self.segment_type,
            version_id=self.version_id,
        )


@dataclass(frozen=True)
class AnalysisMetric:
    """A metric that renders correctly for step and property-query positions."""

    field: str
    aggregation: str
    data_type: str | None = None
    source: str | None = None
    label: str | None = None
    dimension_table: str | None = None
    quantile: int | float | None = None

    def __post_init__(self) -> None:
        bounded_string(self.field, "metric.field")
        bounded_string(self.aggregation, "metric.aggregation")
        if self.aggregation not in ANALYSIS_TARGET_METHODS and not _QUANTILE_METHOD.fullmatch(
            self.aggregation
        ):
            raise InputValidationError(
                f"actual value: {actual_value(self.aggregation)}; " + ("Analysis metric aggregation must use a registered target method"),
                field="metric.aggregation",
            )
        if self.data_type is not None:
            choice(self.data_type, set(_DATA_TYPES), "metric.data_type")
        if self.source is not None:
            choice(self.source, set(ANALYSIS_USER_TYPES), "metric.source")
        if self.label is not None and (
            not isinstance(self.label, str) or len(self.label) > 256
        ):
            raise InputValidationError(
                f"actual value: {actual_value(self.label)}; " + ("Analysis metric label must be at most 256 characters"), field="metric.label"
            )
        if self.dimension_table is not None:
            bounded_string(self.dimension_table, "metric.dimension_table")
        if self.quantile is not None and (
            not isinstance(self.quantile, (int, float))
            or isinstance(self.quantile, bool)
            or not 0 < self.quantile <= 100
        ):
            raise InputValidationError(
                f"actual value: {actual_value(self.quantile)}; " + ("Analysis metric quantile must be greater than 0 through 100"),
                field="metric.quantile",
            )

    def for_step(self) -> dict[str, Any]:
        result = {"field": self.field, "aggregation": self.aggregation}
        if self.dimension_table is not None:
            result["dimension_table"] = self.dimension_table
        if self.quantile is not None:
            result["quantile"] = self.quantile
        return result

    def for_property(self) -> dict[str, Any]:
        if self.data_type is None:
            raise InputValidationError(
                f"actual value: {actual_value(self.data_type)}; " + ("A property Analysis metric requires data_type"), field="metric.data_type"
            )
        if self.aggregation not in ANALYSIS_TARGET_METHODS or self.quantile is not None:
            raise InputValidationError(
                f"actual value: {actual_value(self.aggregation)}; " + ("Remove quantile controls from a property Analysis metric"),
                field="metric.aggregation",
            )
        result = {
            "field": self.field,
            "aggregation": self.aggregation,
            "data_type": self.data_type,
        }
        for key, value in (
            ("source", self.source),
            ("label", self.label),
            ("dimension_table", self.dimension_table),
        ):
            if value is not None:
                result[key] = value
        return result


@dataclass(frozen=True)
class AnalysisStep:
    """One event step shared by event, funnel, retention, and scatter specs."""

    event: str
    metric: AnalysisMetric
    label: str | None = None
    filters: tuple[AnalysisFilter, ...] = ()
    filter_logic: str = "AND"

    def __post_init__(self) -> None:
        bounded_string(self.event, "step.event")
        if not isinstance(self.metric, AnalysisMetric):
            raise InputValidationError(
                f"actual value: {actual_value(self.metric)}; " + ("Analysis step metric must be an AnalysisMetric"), field="step.metric"
            )
        if not isinstance(self.filters, tuple):
            object.__setattr__(self, "filters", tuple(self.filters))
        if any(not isinstance(item, AnalysisFilter) for item in self.filters):
            raise InputValidationError(
                f"actual value: {actual_value(self.filters)}; " + ("Analysis step filters must be AnalysisFilter objects"),
                field="step.filters",
            )
        choice(self.filter_logic, {"AND", "OR"}, "step.filter_logic")
        if self.label is not None and (
            not isinstance(self.label, str) or len(self.label) > 256
        ):
            raise InputValidationError(
                f"actual value: {actual_value(self.label)}; " + ("Analysis step label must be at most 256 characters"), field="step.label"
            )

    def to_spec(self) -> dict[str, Any]:
        result: dict[str, Any] = {"event": self.event, "metric": self.metric.for_step()}
        if self.label is not None:
            result["label"] = self.label
        if self.filters:
            result["conditions"] = [item.to_spec() for item in self.filters]
        if self.filter_logic != "AND":
            result["condition_logic"] = self.filter_logic
        return result


class AnalysisSpec(Mapping[str, Any]):
    """Immutable Mapping wrapper supporting typed construction and narrow edits."""

    __slots__ = ("_kind", "_spec")

    def __init__(self, kind: str, spec: Mapping[str, Any]) -> None:
        selected = str(kind or "").strip().casefold()
        if selected not in ANALYSIS_SPEC_KINDS:
            raise InputValidationError(
                f"actual value: {actual_value(selected)}; " + ("Analysis kind must be event, funnel, retention, property, or scatter"),
                field="kind",
            )
        if not isinstance(spec, Mapping):
            raise InputValidationError(f"actual value: {actual_value(spec)}; " + ("Analysis spec must be an object"), field="spec")
        self._kind = selected
        self._spec = copy.deepcopy(dict(spec))

    @property
    def kind(self) -> str:
        return self._kind

    def __getitem__(self, key: str) -> Any:
        return copy.deepcopy(self._spec[key])

    def __iter__(self) -> Iterator[str]:
        return iter(self._spec)

    def __len__(self) -> int:
        return len(self._spec)

    def to_dict(self) -> dict[str, Any]:
        return copy.deepcopy(self._spec)

    @classmethod
    def from_mapping(cls, kind: str, spec: Mapping[str, Any]) -> AnalysisSpec:
        """Wrap any existing compact spec without changing or reinterpreting it."""

        return cls(kind, spec)

    @classmethod
    def event(
        cls, start: str, end: str, steps: Sequence[AnalysisStep], **identity: Any
    ) -> AnalysisSpec:
        return cls("event", _dated_spec("event", start, end, steps, identity))

    @classmethod
    def funnel(
        cls,
        start: str,
        end: str,
        steps: Sequence[AnalysisStep],
        *,
        window_unit: str,
        window_value: int,
        **identity: Any,
    ) -> AnalysisSpec:
        spec = _dated_spec("funnel", start, end, steps, identity)
        spec["window"] = {"unit": window_unit, "value": window_value}
        return cls("funnel", spec)

    @classmethod
    def retention(
        cls,
        start: str,
        end: str,
        steps: Sequence[AnalysisStep],
        *,
        offset: int,
        period_calc_method: str,
        custom_before_method: str,
        total_calc_type: str,
        week_first_day: int,
        **identity: Any,
    ) -> AnalysisSpec:
        spec = _dated_spec("retention", start, end, steps, identity)
        spec.update(
            offset=offset,
            period_calc_method=period_calc_method,
            custom_before_method=custom_before_method,
            total_calc_type=total_calc_type,
            week_first_day=week_first_day,
        )
        return cls("retention", spec)

    @classmethod
    def property(
        cls,
        metric: AnalysisMetric,
        *,
        filters: Sequence[AnalysisFilter] = (),
        **identity: Any,
    ) -> AnalysisSpec:
        spec = _identity(identity)
        spec["property"] = metric.for_property()
        if filters:
            spec["conditions"] = _filter_specs(filters)
        return cls("property", spec)

    @classmethod
    def scatter(
        cls, start: str, end: str, step: AnalysisStep, **identity: Any
    ) -> AnalysisSpec:
        return cls("scatter", _dated_spec("scatter", start, end, [step], identity))

    def with_app(self, app: str | int) -> AnalysisSpec:
        return self._updated(lambda spec: spec.__setitem__("app", app))

    def with_dates(self, start: str, end: str) -> AnalysisSpec:
        if self.kind not in _DATED_KINDS:
            raise InputValidationError(
                f"actual value: {actual_value(self.kind)}; " + ("Remove date overrides from property Analysis"), field="start/end"
            )
        return self._updated(lambda spec: spec.update(start=start, end=end))

    def replace_step_metric(self, metric: AnalysisMetric, *, step: int = 0) -> AnalysisSpec:
        if self.kind not in _DATED_KINDS:
            raise InputValidationError(
                f"actual value: {actual_value(self.kind)}; " + ("Use replace_property_metric for property Analysis"), field="steps"
            )
        return self._updated(
            lambda spec: _step_at(spec, step).__setitem__("metric", metric.for_step())
        )

    def replace_property_metric(self, metric: AnalysisMetric) -> AnalysisSpec:
        if self.kind != "property":
            raise InputValidationError(
                f"actual value: {actual_value(self.kind)}; " + ("A property metric requires property Analysis"), field="property"
            )
        return self._updated(
            lambda spec: spec.__setitem__("property", metric.for_property())
        )

    def add_step_filter(
        self, condition: AnalysisFilter, *, step: int = 0
    ) -> AnalysisSpec:
        if self.kind not in _DATED_KINDS:
            raise InputValidationError(
                f"actual value: {actual_value(self.kind)}; " + ("Property Analysis event-step filters must use add_property_filter"),
                field="steps",
            )

        def add(spec: dict[str, Any]) -> None:
            selected = _step_at(spec, step)
            selected.setdefault("conditions", []).append(condition.to_spec())

        return self._updated(add)

    def add_global_filter(self, condition: AnalysisFilter) -> AnalysisSpec:
        if self.kind not in {"event", "funnel"}:
            raise InputValidationError(
                f"actual value: {actual_value(self.kind)}; " + ("Global filters must use event or funnel Analysis"),
                field="global_filters",
            )
        return self._updated(
            lambda spec: spec.setdefault("global_filters", []).append(condition.to_spec())
        )

    def add_property_filter(self, condition: AnalysisFilter) -> AnalysisSpec:
        if self.kind != "property":
            raise InputValidationError(
                f"actual value: {actual_value(self.kind)}; " + ("A query-item property filter requires property Analysis"),
                field="conditions",
            )
        return self._updated(
            lambda spec: spec.setdefault("conditions", []).append(condition.to_spec())
        )

    def add_property_condition(self, condition: AnalysisFilter) -> AnalysisSpec:
        if self.kind not in {"retention", "property"}:
            raise InputValidationError(
                f"actual value: {actual_value(self.kind)}; " + ("A shared property condition requires retention or property Analysis"),
                field="property_conditions",
            )
        return self._updated(
            lambda spec: spec.setdefault("property_conditions", []).append(
                condition.to_spec()
            )
        )

    def _updated(self, change: Any) -> AnalysisSpec:
        spec = self.to_dict()
        change(spec)
        return AnalysisSpec(self.kind, spec)


def _dated_spec(
    kind: str,
    start: str,
    end: str,
    steps: Sequence[AnalysisStep],
    identity: Mapping[str, Any],
) -> dict[str, Any]:
    selected = tuple(steps)
    minimum, maximum = _STEP_LIMITS[kind]
    if not minimum <= len(selected) <= maximum or any(
        not isinstance(item, AnalysisStep) for item in selected
    ):
        raise InputValidationError(
            f"actual value: {actual_value(selected)}; " + (f"{kind} Analysis requires {minimum} through {maximum} typed steps"),
            field="steps",
        )
    return {
        **_identity(identity),
        "start": start,
        "end": end,
        "steps": [item.to_spec() for item in selected],
    }


def _identity(value: Mapping[str, Any]) -> dict[str, Any]:
    unknown = sorted(set(value) - {"app", "query_id"})
    if unknown:
        raise InputValidationError(
            f"actual value: {actual_value(unknown[0])}; " + (f"Remove unsupported typed Analysis identity field: {unknown[0]}"),
            field=unknown[0],
        )
    return {key: copy.deepcopy(item) for key, item in value.items() if item is not None}


def _filter_specs(values: Sequence[AnalysisFilter]) -> list[dict[str, Any]]:
    if any(not isinstance(item, AnalysisFilter) for item in values):
        raise InputValidationError(
            f"actual value: {actual_value(values)}; " + ("Analysis filters must be AnalysisFilter objects"), field="filters"
        )
    return [item.to_spec() for item in values]


def _step_at(spec: dict[str, Any], index: int) -> dict[str, Any]:
    steps = spec.get("steps")
    if type(index) is not int or not isinstance(steps, list) or not 0 <= index < len(steps):
        raise InputValidationError(
            f"actual value: {actual_value(index)}; " + ("Analysis step index must identify an existing step"), field="steps"
        )
    selected = steps[index]
    if not isinstance(selected, dict):
        raise InputValidationError(f"actual value: {actual_value(selected)}; " + ("Analysis step must be an object"), field=f"steps[{index}]")
    return selected


__all__ = [
    "AnalysisCohort",
    "AnalysisFilter",
    "AnalysisMetric",
    "AnalysisSpec",
    "AnalysisStep",
]
