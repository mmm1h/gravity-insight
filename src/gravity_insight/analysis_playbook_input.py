"""Closed caller input contract for metric-anomaly-localization@1."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import Any

from .errors import InputValidationError
from .semantic_compose import actual_value


INPUT_SCHEMA_VERSION = "gravity.metric-anomaly-localization-input.v1"
PLAYBOOK_INPUT_ACTION = (
    "Correct the named playbook field with the allowed value, then retry the same command."
)
_INPUT_FIELDS = frozenset(
    {"schema_version", "question", "app", "current_window", "reference_window", "hypothesis"}
)
_HYPOTHESIS_FIELDS = frozenset({"statement", "values"})
_WINDOW_FIELDS = frozenset({"start", "end"})


def metric_anomaly_input_schema() -> dict[str, Any]:
    return {
        "schema_version": INPUT_SCHEMA_VERSION,
        "type": "object",
        "additionalProperties": False,
        "required": [
            "schema_version", "question", "app", "current_window",
            "reference_window", "hypothesis",
        ],
        "properties": {
            "schema_version": {"const": INPUT_SCHEMA_VERSION},
            "question": {"type": "string", "minLength": 1, "maxLength": 2048},
            "app": {"type": "string|positive integer"},
            "current_window": _window_schema(),
            "reference_window": _window_schema(),
            "hypothesis": {
                "type": "object",
                "additionalProperties": False,
                "required": ["statement", "values"],
                "properties": {
                    "statement": {"type": "string", "minLength": 1, "maxLength": 2048},
                    "values": {
                        "type": "array", "minItems": 1, "maxItems": 1,
                        "items": {"type": "string", "minLength": 1, "maxLength": 128},
                    },
                },
            },
        },
        "cross_field_rules": [
            "current and reference windows have the same inclusive day count",
            "reference_window.end is before current_window.start",
        ],
    }


def normalize_metric_anomaly_inputs(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise playbook_input_error("playbook input must be an object", "input", actual_value(value), sorted(_INPUT_FIELDS), next_action=PLAYBOOK_INPUT_ACTION)
    if set(value) != _INPUT_FIELDS:
        raise playbook_input_error("playbook input fields do not match the closed schema", "input", actual_value(sorted(value)), sorted(_INPUT_FIELDS), next_action=PLAYBOOK_INPUT_ACTION)
    if value.get("schema_version") != INPUT_SCHEMA_VERSION:
        raise playbook_input_error("playbook input schema version is invalid", "schema_version", actual_value(value.get("schema_version")), INPUT_SCHEMA_VERSION, next_action=PLAYBOOK_INPUT_ACTION)
    question = _bounded_text(value.get("question"), "question", 2048)
    app = _app(value.get("app"))
    current, current_dates = _window(value.get("current_window"), "current_window")
    reference, reference_dates = _window(value.get("reference_window"), "reference_window")
    if (current_dates[1] - current_dates[0]).days != (reference_dates[1] - reference_dates[0]).days:
        raise playbook_input_error("playbook windows must have equal inclusive lengths", "current_window", actual_value(current), "the same inclusive day count as reference_window", next_action=PLAYBOOK_INPUT_ACTION)
    if reference_dates[1] >= current_dates[0]:
        raise playbook_input_error("reference window must end before the current window starts", "reference_window.end", actual_value(reference["end"]), f"a date before {current['start']}", next_action=PLAYBOOK_INPUT_ACTION)
    return {
        "schema_version": INPUT_SCHEMA_VERSION,
        "question": question,
        "app": app,
        "current_window": current,
        "reference_window": reference,
        "hypothesis": _hypothesis(value.get("hypothesis")),
    }


def playbook_input_error(
    message: str, field: str, observed: str, allowed: Any, *, next_action: str,
) -> InputValidationError:
    return InputValidationError(
        f"{message}; actual value: {observed}; allowed value: {actual_value(allowed)}",
        field=field,
        next_action=next_action,
    )


def _hypothesis(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _HYPOTHESIS_FIELDS:
        raise playbook_input_error("playbook hypothesis fields are invalid", "hypothesis", actual_value(sorted(value) if isinstance(value, Mapping) else value), sorted(_HYPOTHESIS_FIELDS), next_action=PLAYBOOK_INPUT_ACTION)
    statement = _bounded_text(value.get("statement"), "hypothesis.statement", 2048)
    values = value.get("values")
    if not isinstance(values, list) or len(values) != 1:
        raise playbook_input_error("playbook hypothesis requires exactly one channel value", "hypothesis.values", actual_value(values), "an array containing one exact click_company code", next_action=PLAYBOOK_INPUT_ACTION)
    return {"statement": statement, "values": [_bounded_text(values[0], "hypothesis.values[0]", 128)]}


def _window(value: Any, field: str) -> tuple[dict[str, str], tuple[date, date]]:
    if not isinstance(value, Mapping) or set(value) != _WINDOW_FIELDS:
        raise playbook_input_error("playbook window fields are invalid", field, actual_value(sorted(value) if isinstance(value, Mapping) else value), sorted(_WINDOW_FIELDS), next_action=PLAYBOOK_INPUT_ACTION)
    parsed: list[date] = []
    rendered: list[str] = []
    for name in ("start", "end"):
        item = value.get(name)
        try:
            selected = date.fromisoformat(item) if isinstance(item, str) else None
        except ValueError:
            selected = None
        if selected is None or selected.isoformat() != item:
            raise playbook_input_error("playbook window requires canonical ISO dates", f"{field}.{name}", actual_value(item), "YYYY-MM-DD", next_action=PLAYBOOK_INPUT_ACTION)
        parsed.append(selected)
        rendered.append(item)
    if parsed[0] > parsed[1]:
        raise playbook_input_error("playbook window start is after end", field, actual_value(dict(value)), "start <= end", next_action=PLAYBOOK_INPUT_ACTION)
    return {"start": rendered[0], "end": rendered[1]}, (parsed[0], parsed[1])


def _app(value: Any) -> str | int:
    if type(value) is int and value > 0:
        return value
    if isinstance(value, str) and value.strip() and len(value) <= 128:
        return value.strip()
    raise playbook_input_error("playbook App is invalid", "app", actual_value(value), "a configured App alias or positive integer id", next_action=PLAYBOOK_INPUT_ACTION)


def _bounded_text(value: Any, field: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise playbook_input_error("playbook text is invalid", field, actual_value(value), f"a non-empty string of at most {maximum} characters", next_action=PLAYBOOK_INPUT_ACTION)
    return value.strip()


def _window_schema() -> dict[str, Any]:
    return {
        "type": "object", "additionalProperties": False,
        "required": ["start", "end"],
        "properties": {
            "start": {"type": "string", "format": "date"},
            "end": {"type": "string", "format": "date"},
        },
    }


__all__ = [
    "INPUT_SCHEMA_VERSION",
    "PLAYBOOK_INPUT_ACTION",
    "metric_anomaly_input_schema",
    "normalize_metric_anomaly_inputs",
    "playbook_input_error",
]
