"""Small structural primitives for aggregating product components."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .errors import ErrorCategory, exit_code_for_category


def component_exit_code(value: Mapping[str, Any]) -> int:
    """Map one controlled component error category to its process exit."""

    error = value.get("error")
    category = error.get("category") if isinstance(error, Mapping) else None
    return exit_code_for_category(str(category), default=ErrorCategory.LOCAL)


def aggregate_exit_code(failures: Sequence[Mapping[str, Any]]) -> int:
    """Return the highest process exit among failed components."""

    return max((component_exit_code(item) for item in failures), default=0)


def aggregate_status(
    results: Sequence[Mapping[str, Any]],
    failures: Sequence[Mapping[str, Any]],
) -> str:
    """Return the stable status implied only by component structure."""

    success_count = len(results) - len(failures)
    if any(item.get("status") == "contract_changed" for item in failures):
        return "contract_changed"
    if failures and success_count:
        return "partial"
    if failures:
        return "error"
    if all(item.get("status") == "empty" for item in results):
        return "empty"
    return "success"
