"""Public product boundary for governed user-detail aggregation."""

from __future__ import annotations

import copy
from typing import Any, Mapping

from .user_detail_aggregate_contract import (
    INPUT_SCHEMA_VERSION,
    PRODUCT_OPERATION_ID,
    metric_definitions,
    normalize_user_detail_aggregate_inputs,
    user_detail_aggregate_input_schema,
)
from .user_detail_aggregate_service import UserDetailAggregateService


PREVIEW_SCHEMA_VERSION = "gravity-insight.user-detail-aggregate-preview.v1"


def prepare_user_detail_aggregate(inputs: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the closed request shape without constructing a client."""

    normalized = normalize_user_detail_aggregate_inputs(inputs)
    return {
        "schema_version": PREVIEW_SCHEMA_VERSION,
        "input_schema_version": INPUT_SCHEMA_VERSION,
        "ok": True,
        "status": "needs_live_metadata",
        "exit_code": 0,
        "operation_id": PRODUCT_OPERATION_ID,
        "network_called": False,
        "query_executed": False,
        "query": {
            "filters": copy.deepcopy(normalized["filters"]),
            "group_by": list(normalized["group_by"]),
            "measures": metric_definitions(normalized),
            "bounds": dict(normalized["bounds"]),
        },
        "next_action": (
            "Execute the same request to validate live field metadata and aggregate "
            "the bounded user-detail collection."
        ),
    }


def run_user_detail_aggregate(
    client: Any,
    inputs: Mapping[str, Any],
    *,
    max_workers: int = 6,
) -> dict[str, Any]:
    """Execute the one versioned product core through the public Insight facade."""

    normalized = normalize_user_detail_aggregate_inputs(inputs)
    result = UserDetailAggregateService(client).aggregate(
        normalized, max_workers=max_workers
    )
    return {**result, "network_called": True, "query_executed": True}


__all__ = [
    "INPUT_SCHEMA_VERSION",
    "PREVIEW_SCHEMA_VERSION",
    "prepare_user_detail_aggregate",
    "run_user_detail_aggregate",
    "user_detail_aggregate_input_schema",
]
