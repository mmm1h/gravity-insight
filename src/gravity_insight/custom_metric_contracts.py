"""Exact operation identities for the current confmetric custom-metric family."""

from __future__ import annotations

from .composite_catalog import stable_operation


def _operation(action: str) -> str:
    return stable_operation(
        "report", "confmetric_custom_metric_current", action=action
    ).operation_id


CUSTOM_METRIC_LIST = _operation("list")
CUSTOM_METRIC_UPSERT = _operation("update")
CUSTOM_METRIC_DELETE = _operation("delete")
CUSTOM_METRIC_MUTATIONS = frozenset({CUSTOM_METRIC_UPSERT, CUSTOM_METRIC_DELETE})


__all__ = [
    "CUSTOM_METRIC_DELETE",
    "CUSTOM_METRIC_LIST",
    "CUSTOM_METRIC_MUTATIONS",
    "CUSTOM_METRIC_UPSERT",
]
