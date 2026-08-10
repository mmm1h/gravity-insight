"""Private batch resolution and ledger rendering for the empty-sample task."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from .nonempty_plan import (
    DEFAULT_CACHE_ROOT,
    DEFAULT_CANDIDATE_LIMIT,
    DEFAULT_INTERVAL_SECONDS,
)
from .nonempty_runtime import discover_nonempty
from .prober.core import DRAFT_ROOT, OPERATION_ROOT, REPO_ROOT, read_json, write_json


_TASK_EMPTY_SAMPLE_BLOCKER_SETS = frozenset(
    {
        frozenset({"empty_sample"}),
        frozenset({"empty_sample", "response_schema_unverified"}),
    }
)


def task_empty_sample_operation_ids(draft_root: Path = DRAFT_ROOT) -> list[str]:
    """Return the current operations matching the task's exact blocker sets."""

    operation_ids: list[str] = []
    for path in sorted(draft_root.glob("*.json")):
        source = read_json(path)
        blockers = source.get("draft", {}).get("blockers", [])
        codes = frozenset(
            str(item.get("code"))
            for item in blockers
            if isinstance(item, Mapping) and item.get("code")
        )
        if codes in _TASK_EMPTY_SAMPLE_BLOCKER_SETS:
            operation_ids.append(str(source["operation"]["operation_id"]))
    return operation_ids


def _failed_result(
    operation_id: str, request_budget: int, exc: Exception
) -> dict[str, Any]:
    error_type = type(exc).__name__
    return {
        "schema_version": "gravity-insight.nonempty-discovery.v1",
        "ok": True,
        "operation_id": operation_id,
        "resolution": "undetermined",
        "found": False,
        "inputs": None,
        "search": {
            "request_budget": request_budget,
            "planned_combinations": 0,
            "attempted_combinations": 0,
            "evaluated_combinations": 0,
            "dimensions": [],
            "unresolved_dimensions": [
                {"field": "execution", "reason": error_type}
            ],
            "outcomes": {},
        },
        "request_stats": {"total": 0},
        "draft_application": {
            "requested": True,
            "applied": False,
            "reason": f"execution_failed:{error_type}",
        },
    }


def _resolve_one(
    operation_id: str,
    *,
    request_budget: int,
    candidate_limit: int,
    interval_seconds: float,
    cache_root: Path,
    draft_root: Path,
    operation_root: Path,
) -> dict[str, Any]:
    try:
        return discover_nonempty(
            operation_id,
            request_budget=request_budget,
            candidate_limit=candidate_limit,
            interval_seconds=interval_seconds,
            refresh_cache=True,
            apply_draft=True,
            cache_root=cache_root,
            draft_root=draft_root,
            operation_root=operation_root,
        )
    except (OSError, RuntimeError, ValueError, TypeError) as exc:
        return _failed_result(operation_id, request_budget, exc)


def _distribution(results: list[dict[str, Any]]) -> dict[str, int]:
    return {
        resolution: sum(item.get("resolution") == resolution for item in results)
        for resolution in ("unblocked", "confirmed_empty", "undetermined")
    }


def run_task_empty_sample_resolution(
    *,
    request_budget_per_operation: int = 6,
    candidate_limit: int = DEFAULT_CANDIDATE_LIMIT,
    interval_seconds: float = DEFAULT_INTERVAL_SECONDS,
    draft_root: Path = DRAFT_ROOT,
    operation_root: Path = OPERATION_ROOT,
    cache_root: Path = DEFAULT_CACHE_ROOT,
    output_path: Path | None = None,
) -> dict[str, Any]:
    """Run the current exact-blocker scope serially and retain private results in tmp."""

    operation_ids = task_empty_sample_operation_ids(draft_root)
    results = [
        _resolve_one(
            operation_id,
            request_budget=request_budget_per_operation,
            candidate_limit=candidate_limit,
            interval_seconds=interval_seconds,
            cache_root=cache_root,
            draft_root=draft_root,
            operation_root=operation_root,
        )
        for operation_id in operation_ids
    ]
    document = {
        "schema_version": "gravity-insight.empty-sample-resolution.v1",
        "scope": {
            "definition": (
                "exact blocker sets: empty_sample alone, or empty_sample plus "
                "response_schema_unverified"
            ),
            "operation_count": len(operation_ids),
            "request_budget_per_operation": request_budget_per_operation,
            "candidate_limit": candidate_limit,
            "concurrency": 1,
        },
        "distribution": _distribution(results),
        "request_stats": {
            "total": sum(
                int(item.get("request_stats", {}).get("total", 0))
                for item in results
            ),
            "failed": sum(
                int(item.get("request_stats", {}).get("failed", 0))
                for item in results
            ),
        },
        "results": results,
    }
    selected_output = (
        output_path
        or REPO_ROOT
        / "tmp"
        / "codex"
        / "gi-nonempty"
        / "empty-sample-resolution.json"
    ).resolve()
    if not selected_output.is_relative_to((REPO_ROOT / "tmp").resolve()):
        raise ValueError("empty-sample resolution output must stay under tmp")
    write_json(selected_output, document)
    return {
        **{key: value for key, value in document.items() if key != "results"},
        "output": selected_output.relative_to(REPO_ROOT).as_posix(),
    }


def _resolution_detail(item: Mapping[str, Any], search: Mapping[str, Any]) -> Any:
    if item.get("resolution") == "unblocked":
        return item.get("inputs")
    diagnostics = search.get("diagnostics", {})
    if isinstance(diagnostics, Mapping) and (
        diagnostics.get("local_error_types")
        or diagnostics.get("semantic_parameter_hints")
    ):
        diagnostic_detail: Any = diagnostics
    else:
        diagnostic_detail = None
    return (
        search.get("unresolved_dimensions")
        or diagnostic_detail
        or search.get("outcomes")
    )


def _resolution_row(item: Mapping[str, Any]) -> str:
    search = item.get("search", {})
    search = search if isinstance(search, Mapping) else {}
    stats = item.get("request_stats", {})
    stats = stats if isinstance(stats, Mapping) else {}
    dimensions = ", ".join(
        f"{dimension.get('field')}:{dimension.get('source')}[{dimension.get('candidate_count')}]"
        for dimension in search.get("dimensions", [])
        if isinstance(dimension, Mapping)
    ) or "none"
    coverage = (
        f"{search.get('attempted_combinations', 0)}/"
        f"{search.get('planned_combinations', 0)}; budget="
        f"{search.get('request_budget', 0)}"
    )
    detail = json.dumps(
        _resolution_detail(item, search), ensure_ascii=False, sort_keys=True
    ).replace("|", "\\|")
    return (
        f"| `{item.get('operation_id')}` | `{item.get('resolution')}` | "
        f"{stats.get('total', 0)} | {coverage} | {dimensions} | `{detail}` |"
    )


def write_task_resolution_markdown(
    resolution_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    """Render the private per-operation resolution ledger requested by the task."""

    document = read_json(resolution_path)
    results = document.get("results", []) if isinstance(document, Mapping) else []
    distribution = (
        document.get("distribution", {}) if isinstance(document, Mapping) else {}
    )
    lines = [
        "# Empty Sample Resolution",
        "",
        "Scope: exact blocker sets `empty_sample` and `empty_sample + response_schema_unverified`.",
        "",
        (
            f"Distribution: unblocked={distribution.get('unblocked', 0)}, "
            f"confirmed_empty={distribution.get('confirmed_empty', 0)}, "
            f"undetermined={distribution.get('undetermined', 0)}."
        ),
        "",
        "| Operation | Resolution | HTTP | Coverage | Dimensions | Inputs / remaining evidence |",
        "| --- | --- | ---: | --- | --- | --- |",
        *(_resolution_row(item) for item in results if isinstance(item, Mapping)),
    ]
    selected_output = output_path.resolve()
    if not selected_output.is_relative_to((REPO_ROOT / "tmp").resolve()):
        raise ValueError("empty-sample Markdown output must stay under tmp")
    selected_output.parent.mkdir(parents=True, exist_ok=True)
    selected_output.write_text(
        "\n".join(lines) + "\n", encoding="utf-8", newline="\n"
    )
    return {
        "operation_count": len(results),
        "output": selected_output.relative_to(REPO_ROOT).as_posix(),
    }


__all__ = [
    "run_task_empty_sample_resolution",
    "task_empty_sample_operation_ids",
    "write_task_resolution_markdown",
]
