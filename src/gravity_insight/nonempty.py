"""Public facade for budgeted non-empty input discovery."""

from .nonempty_plan import (
    DEFAULT_CACHE_ROOT,
    DEFAULT_CANDIDATE_LIMIT,
    DEFAULT_INTERVAL_SECONDS,
    DEFAULT_REQUEST_BUDGET,
    SearchDimension,
    _build_plan,
    _iter_combinations,
)
from .nonempty_runtime import discover_nonempty
from .nonempty_support import DEFAULT_EVIDENCE_ROOT, _apply_found_draft
from .nonempty_task import (
    run_task_empty_sample_resolution,
    task_empty_sample_operation_ids,
    write_task_resolution_markdown,
)


__all__ = [
    "DEFAULT_CACHE_ROOT",
    "DEFAULT_CANDIDATE_LIMIT",
    "DEFAULT_EVIDENCE_ROOT",
    "DEFAULT_INTERVAL_SECONDS",
    "DEFAULT_REQUEST_BUDGET",
    "SearchDimension",
    "_apply_found_draft",
    "_build_plan",
    "_iter_combinations",
    "discover_nonempty",
    "run_task_empty_sample_resolution",
    "task_empty_sample_operation_ids",
    "write_task_resolution_markdown",
]
