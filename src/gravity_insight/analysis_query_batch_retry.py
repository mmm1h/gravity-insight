"""Bounded adaptive retries for independent Analysis batch components."""

from __future__ import annotations

import copy
import time
from collections.abc import Mapping, Sequence
from typing import Any

from .plan_execution import result_envelope
from .plan_validation import validate_plan


ADAPTIVE_CONCURRENCY_POLICY = "gravity.analysis-query-batch.adaptive-concurrency.v1"
BASE_BACKOFF_MS = 1_000
MAX_BACKOFF_MS = 30_000


def execute_adaptive_analysis_batch(
    sdk: Any,
    plan: Mapping[str, Any],
    *,
    workspace: Any,
    max_workers: int,
) -> dict[str, Any]:
    """Execute retryable upstream failures at successively lower concurrency."""

    nodes = _plan_nodes(plan)
    node_order = tuple(nodes)
    pending = node_order
    final_items: dict[str, dict[str, Any]] = {}
    attempts: list[dict[str, Any]] = []
    workers = max_workers
    backoff_ms = 0
    latest: Mapping[str, Any] | None = None

    while pending:
        if backoff_ms:
            time.sleep(backoff_ms / 1_000)
        latest = sdk.execute_plan(
            _attempt_plan(plan, nodes, pending, workers),
            workspace=workspace,
            max_workers=workers,
        )
        items = _result_items(latest, pending)
        final_items.update(items)
        retryable = tuple(
            node_id for node_id in pending if _retryable_upstream(items[node_id])
        )
        scheduled = retryable if workers > 1 else ()
        attempts.append(
            _attempt_observation(
                len(attempts) + 1,
                workers,
                backoff_ms,
                items,
                retryable,
                scheduled,
            )
        )
        if not scheduled:
            break
        backoff_ms = _retry_backoff_ms(len(attempts), items, scheduled)
        workers = _lower_workers(workers, len(scheduled))
        pending = scheduled

    if latest is None:
        raise RuntimeError("Analysis batch adaptive execution made no progress")
    serial_exhausted = workers == 1 and any(
        _retryable_upstream(final_items[node_id]) for node_id in pending
    )
    if serial_exhausted:
        for node_id in pending:
            if _retryable_upstream(final_items[node_id]):
                final_items[node_id] = _serial_failure_item(final_items[node_id])
    merged = _merged_result(plan, latest, node_order, final_items, max_workers, attempts)
    merged["adaptive_execution"] = {
        "policy": ADAPTIVE_CONCURRENCY_POLICY,
        "requested_max_workers": max_workers,
        "final_max_workers": workers,
        "degraded": len(attempts) > 1,
        "retry_count": len(attempts) - 1,
        "total_component_attempts": sum(
            int(attempt["component_count"]) for attempt in attempts
        ),
        "terminal_reason": _terminal_reason(final_items, serial_exhausted),
        "attempts": attempts,
    }
    return merged


def _plan_nodes(plan: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    source = plan.get("nodes")
    if not isinstance(source, Sequence) or isinstance(source, (str, bytes, bytearray)):
        raise RuntimeError("Analysis batch Plan nodes are invalid")
    nodes = {
        str(node.get("id")): node
        for node in source
        if isinstance(node, Mapping) and isinstance(node.get("id"), str)
    }
    if len(nodes) != len(source):
        raise RuntimeError("Analysis batch Plan node identities are invalid")
    return nodes


def _attempt_plan(
    plan: Mapping[str, Any],
    nodes: Mapping[str, Mapping[str, Any]],
    pending: Sequence[str],
    workers: int,
) -> dict[str, Any]:
    selected = copy.deepcopy(dict(plan))
    selected["nodes"] = [copy.deepcopy(dict(nodes[node_id])) for node_id in pending]
    selected["budget"] = {
        "max_workers": workers,
        "max_total_items": sum(
            int(nodes[node_id]["limits"]["max_items"]) for node_id in pending
        ),
    }
    return selected


def _result_items(
    result: Any, pending: Sequence[str]
) -> dict[str, dict[str, Any]]:
    if not isinstance(result, Mapping):
        raise RuntimeError("Plan returned an invalid Analysis batch result")
    source = result.get("results")
    if not isinstance(source, Sequence) or isinstance(source, (str, bytes, bytearray)):
        raise RuntimeError("Plan returned invalid Analysis batch component results")
    items = {
        str(item.get("node_id")): copy.deepcopy(dict(item))
        for item in source
        if isinstance(item, Mapping) and isinstance(item.get("node_id"), str)
    }
    if len(items) != len(source) or set(items) != set(pending):
        raise RuntimeError("Plan returned mismatched Analysis batch component results")
    return items


def _retryable_upstream(item: Mapping[str, Any]) -> bool:
    error = item.get("error")
    return (
        item.get("ok") is False
        and item.get("status") == "error"
        and isinstance(error, Mapping)
        and error.get("category") == "upstream"
        and error.get("retryable") is True
    )


def _attempt_observation(
    attempt: int,
    workers: int,
    backoff_ms: int,
    items: Mapping[str, Mapping[str, Any]],
    retryable: Sequence[str],
    scheduled: Sequence[str],
) -> dict[str, Any]:
    failures = sum(
        item.get("ok") is not True and item.get("status") != "skipped"
        for item in items.values()
    )
    return {
        "attempt": attempt,
        "max_workers": workers,
        "component_count": len(items),
        "success_count": sum(item.get("ok") is True for item in items.values()),
        "retryable_upstream_failure_count": len(retryable),
        "scheduled_retry_count": len(scheduled),
        "terminal_failure_count": failures - len(scheduled),
        "backoff_ms_before_attempt": backoff_ms,
    }


def _retry_backoff_ms(
    retry_round: int,
    items: Mapping[str, Mapping[str, Any]],
    scheduled: Sequence[str],
) -> int:
    exponential = min(MAX_BACKOFF_MS, BASE_BACKOFF_MS * (2 ** (retry_round - 1)))
    upstream = max((_retry_after_ms(items[node_id]) for node_id in scheduled), default=0)
    return min(MAX_BACKOFF_MS, max(exponential, upstream))


def _retry_after_ms(item: Mapping[str, Any]) -> int:
    error = item.get("error")
    value = error.get("retry_after_ms") if isinstance(error, Mapping) else None
    return value if type(value) is int and value >= 0 else 0


def _lower_workers(current: int, pending_count: int) -> int:
    return max(1, min(current // 2, pending_count))


def _serial_failure_item(item: Mapping[str, Any]) -> dict[str, Any]:
    selected = copy.deepcopy(dict(item))
    error = selected.get("error")
    if isinstance(error, Mapping):
        selected["error"] = {
            **dict(error),
            "next_action": (
                "Automatic Analysis batch retries reached concurrency 1 and the "
                "retryable upstream rejection persisted. Retry after a longer "
                "cooldown or report sanitized capacity evidence; do not increase "
                "concurrency."
            ),
        }
    return selected


def _merged_result(
    plan: Mapping[str, Any],
    latest: Mapping[str, Any],
    node_order: Sequence[str],
    final_items: Mapping[str, dict[str, Any]],
    requested_workers: int,
    attempts: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    ordered = [final_items[node_id] for node_id in node_order]
    if len(attempts) == 1:
        selected = copy.deepcopy(dict(latest))
        selected["results"] = ordered
        return selected
    return result_envelope(validate_plan(plan), ordered, requested_workers)


def _terminal_reason(
    items: Mapping[str, Mapping[str, Any]], serial_exhausted: bool
) -> str:
    if serial_exhausted:
        return "serial_retryable_failure"
    if any(item.get("ok") is not True for item in items.values()):
        return "non_retryable_failure"
    return "completed"


__all__ = [
    "ADAPTIVE_CONCURRENCY_POLICY",
    "BASE_BACKOFF_MS",
    "MAX_BACKOFF_MS",
    "execute_adaptive_analysis_batch",
]
