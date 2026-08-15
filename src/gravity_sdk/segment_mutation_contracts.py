"""Catalog-derived identities for the governed segment mutation family."""

from __future__ import annotations

from .composite_catalog import stable_operation


def _operation(resource: str, action: str) -> str:
    return stable_operation("analysis", resource, action=action).operation_id


LIST_OPERATION = _operation("segment", "list")
DETAIL_OPERATION = _operation("segment", "get")
FROM_ANALYSIS_CREATE = _operation("segment_from_analysis", "create")
FROM_RULE_CREATE = _operation("segment_from_rule", "create")
FROM_RULE_UPDATE = _operation("segment_from_rule", "update")
MANUAL_UPDATE = _operation("segment_by_manual", "update")
SAVE = _operation("dataanalysis_segment", "update")
FROM_HISTORY_CREATE = _operation("from_history_version", "create")
FROM_TMP_CREATE = _operation("from_tmp_segment", "create")

MUTATION_OPERATIONS = frozenset(
    {
        FROM_ANALYSIS_CREATE,
        FROM_RULE_CREATE,
        FROM_RULE_UPDATE,
        MANUAL_UPDATE,
        SAVE,
        FROM_HISTORY_CREATE,
        FROM_TMP_CREATE,
    }
)


__all__ = [
    "DETAIL_OPERATION",
    "FROM_ANALYSIS_CREATE",
    "FROM_HISTORY_CREATE",
    "FROM_RULE_CREATE",
    "FROM_RULE_UPDATE",
    "FROM_TMP_CREATE",
    "LIST_OPERATION",
    "MANUAL_UPDATE",
    "MUTATION_OPERATIONS",
    "SAVE",
]
