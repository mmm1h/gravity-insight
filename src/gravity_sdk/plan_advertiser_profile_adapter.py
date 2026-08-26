"""Plan v1 boundary for the Bytedance advertiser profile product."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .agents.advertiser_profile import ADVERTISER_PROFILE_NAME
from .errors import InputValidationError
from .plan import AdapterContext
from .plan_adapter_support import (
    input_error,
    validate_exact_targets,
    validate_selected_fields,
)
from .promotion_performance_request import normalize_promotion_window
from .actionable_error_values import actual_value


ADVERTISER_PROFILE_FIELDS = frozenset({"name", "start", "end"})
_TARGETS = frozenset({"/start", "/end"})


def validate_advertiser_profile_plan(
    request: Mapping[str, Any],
    context: AdapterContext,
    output_fields: frozenset[str],
) -> None:
    if set(request) - ADVERTISER_PROFILE_FIELDS:
        raise input_error(
            f"actual value: {actual_value(sorted(set(request) - ADVERTISER_PROFILE_FIELDS))}; "
            "advertiser_profile request contains an unknown field; must use only declared fields; remove extras",
            "request",
        )
    validate_exact_targets(context, _TARGETS)
    dynamic = set(context.dynamic_targets)
    start = "2026-01-01" if "/start" in dynamic else request.get("start")
    end = "2026-01-02" if "/end" in dynamic else request.get("end")
    try:
        normalize_promotion_window(start, end)
    except InputValidationError as exc:
        raise input_error(("must correct: " + str(str(exc))), "start/end") from None
    if context.max_pages < 1 or context.max_items < 1:
        raise input_error(
            f"actual value: {actual_value((context.max_pages, context.max_items))}; " + ("advertiser_profile requires positive pagination limits"), "limits"
        )
    validate_selected_fields(context.output_fields, output_fields, "output_fields")


def execute_advertiser_profile_plan(
    sdk: Any, request: Mapping[str, Any], context: AdapterContext
) -> Any:
    return sdk.advertiser_profile(
        request["start"],
        request["end"],
        max_pages=context.max_pages,
        max_items=context.max_items,
    )


__all__ = [
    "ADVERTISER_PROFILE_FIELDS",
    "ADVERTISER_PROFILE_NAME",
    "execute_advertiser_profile_plan",
    "validate_advertiser_profile_plan",
]
