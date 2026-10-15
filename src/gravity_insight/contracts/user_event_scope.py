"""Value-free scope facts for projected user-event reads, independent of rows."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any


SCHEMA_VERSION = "gravity.user-event-result-scope.v1"
CONTENT_GAP_CODE = "USER_EVENT_CONTENT_CLOSURE_UNPROVEN"
_OPERATION = ".".join(("analysis", "user_event", "list"))


class QueryConditionScope(str, Enum):
    PRESENT = "present"
    NOT_REQUESTED = "not_requested"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class UserEventScope:
    conditions: QueryConditionScope

    def to_dict(self) -> dict[str, Any]:
        comparison = {
            QueryConditionScope.PRESENT: "not_comparable",
            QueryConditionScope.NOT_REQUESTED: "requires_identical_scope",
            QueryConditionScope.UNAVAILABLE: "unavailable",
        }
        return {
            "schema_version": SCHEMA_VERSION,
            "timeline_scope": "requested_event_window_and_query_item_conditions",
            "summary_scope": "unfiltered_event_window",
            "query_item_conditions": self.conditions.value,
            "summary_reconciliation": comparison[self.conditions],
            "filtered_matching_record_total": None,
            "filtered_total_availability": "unavailable",
            "content_completeness": "unknown",
            "content_gap_code": CONTENT_GAP_CODE,
            "ordering_evidence": "unavailable",
            "cursor_evidence": "unavailable",
            "equal_total_proves_content_closure": False,
            "empty_terminator_proves_content_closure": False,
        }


def _request_conditions(inputs: Mapping[str, Any]) -> QueryConditionScope:
    items = inputs.get("query_item_list")
    if not isinstance(items, (list, tuple)) or len(items) > 100:
        return QueryConditionScope.UNAVAILABLE
    for item in items:
        if not isinstance(item, Mapping):
            return QueryConditionScope.UNAVAILABLE
        conditions = item.get("conditions", ())
        if not isinstance(conditions, (list, tuple)):
            return QueryConditionScope.UNAVAILABLE
        if conditions:
            return QueryConditionScope.PRESENT
    return QueryConditionScope.NOT_REQUESTED


def _existing_scope(value: Any) -> UserEventScope:
    unknown = UserEventScope(QueryConditionScope.UNAVAILABLE)
    if not isinstance(value, Mapping):
        return unknown
    try:
        scope = UserEventScope(QueryConditionScope(value.get("query_item_conditions")))
    except (TypeError, ValueError):
        return unknown
    return scope if value == scope.to_dict() else unknown


def annotate_user_event_scope(value: Mapping[str, Any]) -> dict[str, Any]:
    """Attach contract facts after execution has decided emptiness and shape."""
    result = dict(value)
    if result.get("operation_id") != _OPERATION or result.get("schema_version") != "gravity-insight.read.v1":
        return result
    request = result.get("request")
    inputs = request.get("inputs") if isinstance(request, Mapping) else None
    scope = (
        UserEventScope(_request_conditions(inputs)) if isinstance(inputs, Mapping)
        else _existing_scope(result.get("user_event_scope"))
    )
    result["user_event_scope"] = scope.to_dict()
    return result
