"""Layered Plan v1 scheduler and stable result envelopes."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any

from .errors import ErrorCategory, ErrorDetail, GravityInsightError, InputValidationError
from .plan import (
    MAX_EXPANDED_NODES,
    MAX_WORKERS,
    NODE_KINDS,
    RESULT_SCHEMA_VERSION,
    AdapterContext,
    PlanAdapter,
    PlanAdapters,
    PlanNode,
    ValidatedPlan,
)
from .plan_binding import prepare_executions, validate_json
from .plan_validation import bounded_int, validate_plan


def execute_plan(
    plan: Mapping[str, Any],
    *,
    adapters: PlanAdapters | Mapping[str, PlanAdapter],
    workspace: Any,
    max_workers: int | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    validated = validate_plan(plan)
    workers = validated.max_workers if max_workers is None else bounded_int(
        max_workers, 1, MAX_WORKERS, "max_workers"
    )
    if not isinstance(dry_run, bool):
        raise ValueError("dry_run must be a boolean")
    selected = adapter_map(adapters, validated.nodes)
    preflight_adapters(validated, selected, workspace)
    if dry_run:
        return dry_run_result(validated, workers)
    registry, results = run_layers(validated, selected, workspace, workers)
    del registry
    return result_envelope(validated, results, workers)


def run_layers(
    plan: ValidatedPlan,
    adapters: Mapping[str, PlanAdapter],
    workspace: Any,
    workers: int,
) -> tuple[dict[str, Mapping[str, Any]], list[dict[str, Any]]]:
    registry: dict[str, Mapping[str, Any]] = {}
    results: list[dict[str, Any]] = []
    unresolved = {node.node_id for node in plan.nodes}
    expanded_count = 0
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="gravity-plan") as pool:
        while unresolved:
            ready = ready_nodes(plan.nodes, unresolved, registry)
            if not ready:
                raise RuntimeError("validated plan scheduler made no progress")
            runnable: list[tuple[PlanNode, list[tuple[str, int | None, Mapping[str, Any]]]]] = []
            for node in ready:
                executions = prepare_node(node, registry, results, unresolved)
                if executions is not None:
                    expanded_count += len(executions)
                    if expanded_count > MAX_EXPANDED_NODES:
                        raise RuntimeError("validated plan exceeded its expansion budget")
                    runnable.append((node, executions))
            groups = submit_layer(pool, runnable, adapters, workspace)
            collect_layer(groups, registry, results, unresolved)
    return registry, declaration_order(plan.nodes, results)


def ready_nodes(
    nodes: tuple[PlanNode, ...],
    unresolved: set[str],
    registry: Mapping[str, Mapping[str, Any]],
) -> list[PlanNode]:
    return [
        node
        for node in nodes
        if node.node_id in unresolved
        and all(dependency in registry for dependency in node.depends_on)
    ]


def prepare_node(
    node: PlanNode,
    registry: dict[str, Mapping[str, Any]],
    results: list[dict[str, Any]],
    unresolved: set[str],
) -> list[tuple[str, int | None, Mapping[str, Any]]] | None:
    blocked = [
        dependency
        for dependency in node.depends_on
        if registry[dependency].get("ok") is not True
    ]
    if blocked:
        finish_without_execution(node, skipped_item(node, blocked), registry, results, unresolved)
        return None
    try:
        executions = prepare_executions(node, registry)
    except (KeyError, IndexError, TypeError, ValueError):
        finish_without_execution(
            node, binding_failure_item(node), registry, results, unresolved
        )
        return None
    if not executions:
        finish_without_execution(node, empty_item(node), registry, results, unresolved)
        return None
    return executions


def finish_without_execution(
    node: PlanNode,
    item: dict[str, Any],
    registry: dict[str, Mapping[str, Any]],
    results: list[dict[str, Any]],
    unresolved: set[str],
) -> None:
    results.append(item)
    registry[node.node_id] = item
    unresolved.remove(node.node_id)


def submit_layer(
    pool: ThreadPoolExecutor,
    runnable: list[tuple[PlanNode, list[tuple[str, int | None, Mapping[str, Any]]]]],
    adapters: Mapping[str, PlanAdapter],
    workspace: Any,
) -> list[tuple[PlanNode, list[Future[dict[str, Any]]]]]:
    groups: list[tuple[PlanNode, list[Future[dict[str, Any]]]]] = []
    for node, executions in runnable:
        futures = [
            pool.submit(
                execute_one,
                node,
                execution_id,
                foreach_index,
                request,
                adapters[node.kind],
                workspace,
            )
            for execution_id, foreach_index, request in executions
        ]
        groups.append((node, futures))
    return groups


def collect_layer(
    groups: list[tuple[PlanNode, list[Future[dict[str, Any]]]]],
    registry: dict[str, Mapping[str, Any]],
    results: list[dict[str, Any]],
    unresolved: set[str],
) -> None:
    for node, futures in groups:
        items = [future.result() for future in futures]
        results.extend(items)
        registry[node.node_id] = node_view(node, items)
        unresolved.remove(node.node_id)


def execute_one(
    node: PlanNode,
    execution_id: str,
    foreach_index: int | None,
    request: Mapping[str, Any],
    adapter: PlanAdapter,
    workspace: Any,
) -> dict[str, Any]:
    context = AdapterContext(
        node_id=node.node_id,
        execution_id=execution_id,
        kind=node.kind,
        workspace=workspace,
        output_fields=node.output_fields,
        dynamic_targets=tuple(
            [binding.target for binding in node.bindings]
            + ([node.foreach.target] if node.foreach is not None else [])
        ),
        max_pages=node.limits.max_pages,
        max_items=node.limits.max_items,
    )
    try:
        result = adapter.execute(copy.deepcopy(dict(request)), context)
        if not isinstance(result, Mapping):
            raise TypeError("adapter result must be an object")
        if native_failure(result):
            return adapter_failure_item(node, execution_id, foreach_index, result)
        projected: Any = copy.deepcopy(dict(result))
        if node.output_fields:
            projected = adapter.project(projected, node.output_fields, context)  # type: ignore[misc]
        validate_json(projected)
        if result_item_count(projected) > node.limits.max_items:
            raise RuntimeError("plan adapter result exceeded its item budget")
        return result_item(
            node, execution_id, foreach_index, True,
            str(result.get("status", "success")), 0, projected, None, [],
        )
    except Exception as exc:
        return exception_item(node, execution_id, foreach_index, exc)


def adapter_map(
    adapters: PlanAdapters | Mapping[str, PlanAdapter],
    nodes: tuple[PlanNode, ...],
) -> dict[str, PlanAdapter]:
    if isinstance(adapters, PlanAdapters):
        raw = {kind: getattr(adapters, kind) for kind in NODE_KINDS}
    elif isinstance(adapters, Mapping):
        raw = dict(adapters)
    else:
        raise TypeError("plan adapters must be PlanAdapters or a mapping")
    if set(raw) - set(NODE_KINDS):
        raise ValueError("plan adapters contain an unknown kind")
    selected: dict[str, PlanAdapter] = {}
    for kind in {node.kind for node in nodes}:
        value = raw.get(kind)
        if not isinstance(value, PlanAdapter):
            raise ValueError(f"plan adapter is missing for {kind}")
        adapter = value
        if not callable(adapter.execute) or not callable(adapter.validate):
            raise ValueError(f"plan adapter is invalid for {kind}")
        if any(node.kind == kind and node.output_fields for node in nodes):
            if not callable(adapter.project):
                raise ValueError(f"output_fields require the {kind} adapter projector")
        selected[kind] = adapter
    return selected


def preflight_adapters(
    plan: ValidatedPlan,
    adapters: Mapping[str, PlanAdapter],
    workspace: Any,
) -> None:
    """Validate every declared request before any execution may begin."""

    for index, node in enumerate(plan.nodes):
        context = AdapterContext(
            node_id=node.node_id,
            execution_id=node.node_id,
            kind=node.kind,
            workspace=workspace,
            output_fields=node.output_fields,
            dynamic_targets=tuple(
                [binding.target for binding in node.bindings]
                + ([node.foreach.target] if node.foreach is not None else [])
            ),
            max_pages=node.limits.max_pages,
            max_items=node.limits.max_items,
        )
        try:
            adapters[node.kind].validate(copy.deepcopy(dict(node.request)), context)
        except InputValidationError as exc:
            from .plan import PlanValidationError

            suffix = f".{exc.field}" if exc.field else ""
            raise PlanValidationError(
                str(exc),
                field=f"nodes[{index}].request{suffix}",
            ) from None
        except Exception:
            from .plan import PlanValidationError

            raise PlanValidationError(
                "plan adapter rejected a declared request",
                field=f"nodes[{index}].request",
            ) from None


def native_failure(result: Mapping[str, Any]) -> bool:
    return result.get("ok") is False or str(result.get("status", "")).casefold() in {
        "error", "failed", "unavailable", "partial",
    }


def adapter_failure_item(
    node: PlanNode,
    execution_id: str,
    foreach_index: int | None,
    result: Mapping[str, Any],
) -> dict[str, Any]:
    detail = safe_native_error(result)
    return result_item(
        node, execution_id, foreach_index, False, "error", detail_exit_code(detail),
        None, detail.to_dict(), [],
    )


def safe_native_error(result: Mapping[str, Any]) -> ErrorDetail:
    candidates: list[Any] = [result.get("error")]
    nested = result.get("result")
    if isinstance(nested, Mapping):
        candidates.append(nested.get("error"))
    candidate = next((item for item in candidates if isinstance(item, Mapping)), None)
    if candidate is None:
        return safe_detail("PLAN_ADAPTER_FAILED", ErrorCategory.LOCAL.value)
    category = normalized_category(candidate.get("category"))
    code = candidate.get("code")
    return ErrorDetail.create(
        str(code) if isinstance(code, str) and code else "PLAN_ADAPTER_FAILED",
        "Plan adapter reported a failure.",
        category=category,
        field=candidate.get("field") if isinstance(candidate.get("field"), str) else None,
        retryable=candidate.get("retryable") if isinstance(candidate.get("retryable"), bool) else None,
        retry_after_ms=candidate.get("retry_after_ms") if type(candidate.get("retry_after_ms")) is int else None,
        next_action=category_action(category, str(code or "")),
    )


def normalized_category(value: Any) -> str:
    if value in {item.value for item in ErrorCategory}:
        return str(value)
    if value in {"input", "authentication"}:
        return ErrorCategory.CALLER.value
    if value == "runtime":
        return ErrorCategory.UPSTREAM.value
    return ErrorCategory.LOCAL.value


def exception_item(
    node: PlanNode,
    execution_id: str,
    foreach_index: int | None,
    exc: Exception,
) -> dict[str, Any]:
    if isinstance(exc, GravityInsightError):
        native = exc.to_error_detail()
        detail = ErrorDetail.create(
            native.code, "Plan adapter failed.", category=native.category,
            field=native.field, retryable=native.retryable,
            retry_after_ms=native.retry_after_ms,
            next_action=native.next_action or category_action(native.category, native.code),
        )
    else:
        detail = safe_detail("PLAN_ADAPTER_EXCEPTION", ErrorCategory.LOCAL.value)
    return result_item(
        node, execution_id, foreach_index, False, "error", detail_exit_code(detail),
        None, detail.to_dict(), [],
    )


def safe_detail(code: str, category: str) -> ErrorDetail:
    return ErrorDetail.create(
        code,
        "Plan adapter failed locally." if category == "local" else "Plan adapter failed.",
        category=category,
        next_action=category_action(category, code),
    )


def binding_failure_item(node: PlanNode) -> dict[str, Any]:
    detail = ErrorDetail.create(
        "BINDING_FAILED",
        "A dependency binding could not produce the required scalar value.",
        category=ErrorCategory.CALLER,
        field="bindings",
        next_action="Correct the source JSON Pointer or target path, then retry.",
    )
    return result_item(
        node, node.node_id, None, False, "error", 2, None, detail.to_dict(), []
    )


def skipped_item(node: PlanNode, blocked: list[str]) -> dict[str, Any]:
    detail = ErrorDetail.create(
        "DEPENDENCY_FAILED",
        "The node was skipped because a dependency did not succeed.",
        category=ErrorCategory.CALLER,
        field="depends_on",
        next_action="Inspect the failed dependency; retry only after it succeeds.",
    )
    return result_item(
        node, node.node_id, None, False, "skipped", 0, None, detail.to_dict(), blocked
    )


def empty_item(node: PlanNode) -> dict[str, Any]:
    return result_item(node, node.node_id, None, True, "empty", 0, None, None, [])


def result_item(
    node: PlanNode,
    execution_id: str,
    foreach_index: int | None,
    ok: bool,
    status: str,
    exit_code: int,
    result: Any,
    error: Mapping[str, Any] | None,
    blocked_by: list[str],
) -> dict[str, Any]:
    return {
        "node_id": node.node_id,
        "execution_id": execution_id,
        "kind": node.kind,
        "foreach_index": foreach_index,
        "ok": ok,
        "status": status,
        "exit_code": exit_code,
        "result": result,
        "error": dict(error) if error is not None else None,
        "blocked_by": list(blocked_by),
    }


def node_view(node: PlanNode, items: list[dict[str, Any]]) -> Mapping[str, Any]:
    if node.foreach is None:
        return items[0]
    succeeded = sum(item["ok"] is True for item in items)
    failed = len(items) - succeeded
    return {
        "node_id": node.node_id,
        "ok": failed == 0,
        "status": "success" if not failed else "partial" if succeeded else "error",
        "results": items,
    }


def declaration_order(
    nodes: tuple[PlanNode, ...], results: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    rank = {node.node_id: index for index, node in enumerate(nodes)}
    return sorted(
        results,
        key=lambda item: (
            rank[str(item["node_id"])],
            -1 if item["foreach_index"] is None else int(item["foreach_index"]),
        ),
    )


def result_envelope(
    plan: ValidatedPlan, results: list[dict[str, Any]], workers: int
) -> dict[str, Any]:
    succeeded = sum(item["ok"] is True for item in results)
    empty = sum(item["status"] == "empty" for item in results)
    skipped = sum(item["status"] == "skipped" for item in results)
    failed = len(results) - succeeded - skipped
    exit_code = max(
        (int(item["exit_code"]) for item in results if item["status"] != "skipped"),
        default=0,
    )
    ok = failed == 0 and skipped == 0
    return {
        "schema_version": RESULT_SCHEMA_VERSION,
        "ok": ok,
        "status": "success" if ok else "partial" if succeeded else "error",
        "dry_run": False,
        "declared_count": len(plan.nodes),
        "expanded_count": sum(item["status"] not in {"skipped", "empty"} for item in results),
        "success_count": succeeded,
        "empty_count": empty,
        "failure_count": failed,
        "skipped_count": skipped,
        "exit_code": exit_code,
        "max_workers": workers,
        "results": results,
    }


def dry_run_result(plan: ValidatedPlan, workers: int) -> dict[str, Any]:
    return {
        "schema_version": RESULT_SCHEMA_VERSION,
        "ok": True,
        "status": "validated",
        "dry_run": True,
        "declared_count": len(plan.nodes),
        "max_expanded_count": plan.max_expanded_nodes,
        "max_aggregate_items": plan.max_aggregate_items,
        "max_workers": workers,
        "exit_code": 0,
        "results": [],
    }


def detail_exit_code(detail: ErrorDetail) -> int:
    return {"caller": 2, "upstream": 3, "local": 4}[detail.category]


def category_action(category: str, code: str) -> str:
    if code.startswith("AUTH_") or "AUTH" in code:
        return "Run `gravity auth status`; refresh or configure credentials, then retry."
    if category == ErrorCategory.CALLER.value:
        return "Correct this node request, then retry."
    if category == ErrorCategory.UPSTREAM.value:
        return "Retry the failed node after checking Gravity availability and permissions."
    return "Inspect the controlled adapter and its governed contract before retrying."


def result_item_count(value: Any) -> int:
    """Count primary result containers without counting metadata arrays twice."""

    if not isinstance(value, Mapping):
        return len(value) if isinstance(value, list) else 0
    page = value.get("page")
    if isinstance(page, Mapping):
        count = page.get("item_count")
        if type(count) is int and count >= 0:
            return count
    data_count = _container_count(value.get("data"))
    if data_count is not None:
        return data_count
    for key in ("rows", "list", "items"):
        rows = value.get(key)
        if isinstance(rows, list):
            return len(rows)
    results = value.get("results")
    if isinstance(results, list):
        return sum(max(1, result_item_count(item)) for item in results)
    nested_result = value.get("result")
    if isinstance(nested_result, Mapping):
        return result_item_count(nested_result)
    summary = value.get("summary")
    return result_item_count(summary) if isinstance(summary, Mapping) else 0


def _container_count(value: Any) -> int | None:
    if isinstance(value, list):
        return len(value)
    if isinstance(value, Mapping):
        for key in ("list", "items", "rows"):
            rows = value.get(key)
            if isinstance(rows, list):
                return len(rows)
    return None


__all__ = ["execute_plan"]
