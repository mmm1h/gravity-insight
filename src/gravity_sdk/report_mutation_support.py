"""Input and payload helpers shared by governed report mutations."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from .actionable_error_values import actual_value
from .errors import ContractChangedError, InputValidationError
from .segment_mutation_support import MARKER_PREFIX


def positive_id(value: Any, field: str) -> str:
    selected = str(value).strip() if isinstance(value, (str, int)) and not isinstance(value, bool) else ""
    if not selected.isdecimal() or int(selected or 0) < 1 or len(selected) > 64:
        raise InputValidationError(
            f"actual value: {actual_value(value)}; allowed value: a positive integer identifier",
            field=field,
            next_action=f"Use the exact positive {field} returned by the parent list and run dry-run again.",
        )
    return selected


def response_id(value: Any, field: str) -> str:
    selected = str(value).strip() if isinstance(value, (str, int)) and not isinstance(value, bool) else ""
    if not selected.isdecimal() or int(selected or 0) < 1 or len(selected) > 64:
        raise ContractChangedError(
            f"{field} changed type or range",
            next_action="Stop writes until the parent list/detail identity contract is re-verified.",
        )
    return selected


def optional_nonnegative_id(value: Any, field: str) -> str:
    if value is None:
        return "0"
    selected = str(value).strip() if isinstance(value, (str, int)) and not isinstance(value, bool) else ""
    if not selected.isdecimal() or len(selected) > 64:
        raise ContractChangedError(
            f"{field} changed type",
            next_action="Stop writes until the report detail contract is re-verified.",
        )
    return selected


def caller_text(value: Any, field: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise InputValidationError(
            f"actual value: {actual_value(value)}; allowed range: 1 through {maximum} characters",
            field=field,
            next_action=f"Use a non-empty {field} within the documented limit and run dry-run again.",
        )
    return value


def optional_caller_text(value: Any, field: str, maximum: int) -> str:
    if not isinstance(value, str) or len(value) > maximum or MARKER_PREFIX in value:
        raise InputValidationError(
            f"actual value: {actual_value({'type': type(value).__name__, 'length': len(value) if isinstance(value, str) else None, 'contains_marker': isinstance(value, str) and MARKER_PREFIX in value})}; allowed value: caller text without an SDK marker, at most {maximum} characters",
            field=field,
            next_action="Remove marker-like text; the SDK owns marker generation, then run dry-run again.",
        )
    return value.strip()


def contract_text(value: Any, field: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ContractChangedError(
            f"{field} changed type or range",
            next_action="Stop writes until the report detail contract is re-verified.",
        )
    return value


def two_texts(value: Any, field: str) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or len(value) != 2:
        raise InputValidationError(
            f"actual value: {actual_value(value)}; allowed value: exactly two timestamp strings",
            field=field,
            next_action="Provide [start_time, end_time] from the frontend contract and run dry-run again.",
        )
    return [caller_text(item, field, 64) for item in value]


def text_sequence(value: Any, field: str, maximum: int) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or not value:
        raise InputValidationError(
            f"actual value: {actual_value(value)}; allowed value: one or more text values",
            field=field,
            next_action=f"Provide at least one exact {field} value and run dry-run again.",
        )
    return [caller_text(item, field, maximum) for item in value]


def json_text(value: Any, field: str) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise InputValidationError(
            f"actual value: {actual_value({'type': type(value).__name__})}; allowed value: JSON-serializable data",
            field=field,
            next_action="Remove non-JSON values and run dry-run again.",
        ) from exc


def subscription_report_config(app_id: str) -> dict[str, Any]:
    """Return the smallest structurally complete adreport config from the UI builder."""

    return {
        "columns": [
            {"label": "产品", "prop": "app_id", "type": "dim", "width": 150},
            {"label": "激活数", "prop": "activation", "type": "metric", "width": 150},
        ],
        "filterForm": {
            "appFormModel": {"app_id": app_id, "project_id": "0"},
            "dateListFormModel": {"resultDate": []},
        },
        "formModel": {
            "multi_days": 7, "minigame_pay_shared_ratio_switch": False,
            "minigame_pay_shared_ratio": 60, "minigame_pay_shared_ratio_ios": 100,
            "decimal_point_switch": False, "roi_version": 1,
            "accumulate": False, "asa_time_zone": "UTC",
        },
        "extra_data": {
            "summaryTypeObj": {}, "sortTypeObj": {}, "sortList": [],
            "tableDetail": {
                "dimsResult": {"view": "table", "dims": ["app_id"], "relateDims": []},
                "metricsResult": [{"name": "activation", "cname": "激活数"}],
            },
            "dayRadioValue": "", "hideChart": True, "dateSum": "day",
        },
        "dateList": [],
        "conditionFilterData": {
            "conditions": [{"relation": {"value": "or"}, "field": "", "field_type": "", "operator": "", "value": []}],
            "outRelation": "and",
        },
    }


__all__ = [
    "caller_text", "contract_text", "json_text", "optional_caller_text",
    "optional_nonnegative_id", "positive_id", "response_id",
    "subscription_report_config", "text_sequence", "two_texts",
]
