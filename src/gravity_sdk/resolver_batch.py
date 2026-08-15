"""Ordered, failure-isolated batches over the public Resolver pipeline."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from . import runtime
from .errors import (
    ErrorCategory,
    ErrorCode,
    ErrorDetail,
    GravityInsightError,
    InputValidationError,
    error_detail_from_exception,
    exit_code_for_category,
)
from .resolver import resolve_and_run


SCHEMA_VERSION = "gravity-insight.resolver-batch.v1"
SCHEMA_SCHEMA_VERSION = "gravity-insight.resolver-batch-schema.v1"
ITEM_FIELDS = frozenset(
    {
        "selector",
        "input",
        "inputs",
        "parameters",
        "app",
        "apps",
        "start",
        "end",
        "request_id",
        "all_pages",
        "output_fields",
    }
)
DEFAULT_MAX_PAGES = 5
DEFAULT_MAX_ITEMS = 200
MAX_CONCURRENCY = 24
MAX_EXPANDED_ITEMS = 256
MAX_AGGREGATE_ITEMS = 100_000


@dataclass(frozen=True)
class _RunItem:
    request_id: str
    selector: str
    inputs: Mapping[str, Any]
    parameters: Mapping[str, Any]
    app: str | int | None
    start: str | None
    end: str | None
    all_pages: bool
    output_fields: tuple[str, ...] | None


def run_many(
    requests: Mapping[str, Any] | Sequence[Mapping[str, Any]],
    *,
    client: Any,
    workspace: Any,
    max_workers: int = 6,
    max_pages: int = DEFAULT_MAX_PAGES,
    max_items: int = DEFAULT_MAX_ITEMS,
    metadata_database: Any | None = None,
    output_fields: Sequence[str] | None = None,
    read: Callable[..., Any] = runtime.call_read,
) -> dict[str, Any]:
    """Resolve independent selectors concurrently while preserving input order."""

    _validate_limits(max_workers, max_pages, max_items)
    source = _request_payload(requests)
    if len(source) > MAX_EXPANDED_ITEMS:
        raise _input_error(
            f"resolver batch contains more than {MAX_EXPANDED_ITEMS} requests",
            "requests",
        )
    default_fields = _output_fields(output_fields)
    expanded = _expand_requests(source, workspace, default_fields)
    if len(expanded) > MAX_EXPANDED_ITEMS:
        raise _input_error(
            f"resolver batch expands to more than {MAX_EXPANDED_ITEMS} items",
            "requests",
        )
    if len(expanded) * max_items > MAX_AGGREGATE_ITEMS:
        raise _input_error(
            f"resolver batch aggregate max_items exceeds {MAX_AGGREGATE_ITEMS}",
            "max_items",
        )

    def execute(item: _RunItem) -> dict[str, Any]:
        try:
            result = resolve_and_run(
                item.selector,
                client=client,
                workspace=workspace,
                supplied_input=item.inputs,
                parameters=item.parameters,
                app=item.app,
                start=item.start,
                end=item.end,
                read=read,
                read_all=item.all_pages,
                max_pages=max_pages,
                max_items=max_items,
                max_workers=1,
                metadata_database=metadata_database,
                output_fields=item.output_fields,
            )
            return _result_item(item, result)
        except Exception as exc:  # independent items must not cancel their siblings
            return _exception_item(item, exc)

    workers = min(max_workers, len(expanded))
    with ThreadPoolExecutor(
        max_workers=workers, thread_name_prefix="gravity-resolver-batch"
    ) as pool:
        results = list(pool.map(execute, expanded))
    failed = [item for item in results if item["ok"] is not True]
    success_count = len(results) - len(failed)
    return {
        "schema_version": SCHEMA_VERSION,
        "ok": not failed,
        "status": "success" if not failed else "partial" if success_count else "error",
        "request_count": len(source),
        "total_count": len(results),
        "success_count": success_count,
        "failure_count": len(failed),
        "exit_code": max((_item_exit_code(item) for item in failed), default=0),
        "results": results,
    }


def resolver_batch_schema() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_SCHEMA_VERSION,
        "ok": True,
        "status": "success",
        "command": "gravity batch run --input <batch.json> --concurrency 6",
        "wrapper": {
            "type": "object",
            "additional_properties": False,
            "required": ["requests"],
            "properties": {
                "requests": {
                    "type": "array",
                    "min_items": 1,
                    "items": {
                        "type": "object",
                        "additional_properties": False,
                        "required": ["selector"],
                        "allowed_fields": sorted(ITEM_FIELDS),
                        "properties": _schema_properties(),
                    },
                }
            },
        },
        "example": {
            "requests": [
                {
                    "selector": "@retention-weekly",
                    "parameters": {"event": "purchase"},
                    "apps": "*",
                    "start": "2026-08-01",
                    "end": "2026-08-07",
                    "request_id": "retention",
                },
                {
                    "selector": "<operation-id>",
                    "inputs": {"page": 1, "page_size": 20},
                    "request_id": "apps",
                },
            ]
        },
        "expansion": {
            "apps_star": "sorted workspace app aliases only",
            "request_id": "apps expansion appends :<app-ref> to the supplied or generated request_id",
            "order": "request order, then declared apps order; apps='*' uses sorted aliases",
        },
        "execution": {
            "outer_concurrency_default": 6,
            "outer_concurrency_max": MAX_CONCURRENCY,
            "inner_page_workers": 1,
            "default_max_pages": DEFAULT_MAX_PAGES,
            "default_max_items": DEFAULT_MAX_ITEMS,
            "max_expanded_items": MAX_EXPANDED_ITEMS,
            "max_aggregate_items": MAX_AGGREGATE_ITEMS,
        },
        "output": {
            "schema_version": SCHEMA_VERSION,
            "fields": [
                "ok", "status", "request_count", "total_count", "success_count",
                "failure_count", "exit_code", "results",
            ],
            "result_fields": [
                "request_id", "selector", "app", "operation_id", "ok", "status",
                "result", "error",
            ],
            "echoes_inputs": False,
        },
        "exit_codes": {
            "0": "every expanded item succeeded",
            "2": "at least one caller failure and no upstream/local failure",
            "3": "at least one upstream failure and no local failure",
            "4": "at least one local or unclassified failure",
            "aggregation": "highest item exit code wins: local 4 > upstream 3 > caller 2",
        },
    }


def _schema_properties() -> dict[str, Any]:
    return {
        "selector": {"type": "string", "required": True, "description": "@recipe or operation_id"},
        "input": {"type": "object", "required": False, "default": {}, "alias_of": "inputs"},
        "inputs": {"type": "object", "required": False, "default": {}, "mutually_exclusive_with": "input"},
        "parameters": {"type": "object", "required": False, "default": {}},
        "app": {"type": ["string", "integer"], "required": False, "mutually_exclusive_with": "apps"},
        "apps": {"one_of": [{"type": "array", "items": ["string", "integer"]}, {"const": "*"}], "required": False, "mutually_exclusive_with": "app"},
        "start": {"type": "string", "required": False},
        "end": {"type": "string", "required": False},
        "request_id": {"type": "string", "required": False},
        "all_pages": {"type": "boolean", "required": False, "default": False},
        "output_fields": {
            "type": "array",
            "items": "string",
            "required": False,
            "description": "Contracted data-relative output field paths.",
        },
    }


def _request_payload(
    payload: Mapping[str, Any] | Sequence[Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    value: Any = payload
    if isinstance(value, Mapping):
        unknown = sorted(set(value) - {"requests"})
        if unknown:
            raise _input_error(
                "unknown resolver batch wrapper fields: " + ", ".join(unknown),
                unknown[0],
            )
        value = value.get("requests")
    if not isinstance(value, (list, tuple)) or not value:
        raise _input_error("resolver batch requires a non-empty requests array", "requests")
    if not all(isinstance(item, Mapping) for item in value):
        raise _input_error("resolver batch requests must be objects", "requests")
    return [dict(item) for item in value]


def _expand_requests(
    requests: Sequence[Mapping[str, Any]],
    workspace: Any,
    default_output_fields: tuple[str, ...] | None = None,
) -> list[_RunItem]:
    expanded: list[_RunItem] = []
    for index, value in enumerate(requests):
        item = _validate_item(value, index, default_output_fields)
        apps, suffix_ids = _item_apps(value, workspace)
        base_request_id = item.request_id
        for position, app in enumerate(apps):
            request_id = (
                f"{base_request_id}:{suffix_ids[position]}"
                if suffix_ids
                else base_request_id
            )
            expanded.append(
                _RunItem(
                    request_id=request_id,
                    selector=item.selector,
                    inputs=item.inputs,
                    parameters=item.parameters,
                    app=app,
                    start=item.start,
                    end=item.end,
                    all_pages=item.all_pages,
                    output_fields=item.output_fields,
                )
            )
            if len(expanded) > MAX_EXPANDED_ITEMS:
                raise _input_error(
                    f"resolver batch expands to more than {MAX_EXPANDED_ITEMS} items",
                    "requests",
                )
    return expanded


def _validate_item(
    value: Mapping[str, Any],
    index: int,
    default_output_fields: tuple[str, ...] | None = None,
) -> _RunItem:
    unknown = sorted(set(value) - ITEM_FIELDS)
    if unknown:
        raise _input_error(
            "unknown resolver batch request fields: " + ", ".join(unknown)
            + "; allowed fields: " + ", ".join(sorted(ITEM_FIELDS)),
            unknown[0],
        )
    selector = value.get("selector")
    if not isinstance(selector, str) or not selector.strip():
        raise _input_error("resolver batch selector must be a non-empty string", "selector")
    inputs, parameters = _item_bindings(value)
    if "app" in value and "apps" in value:
        raise _input_error("resolver batch app and apps cannot be combined", "apps")
    start, end = value.get("start"), value.get("end")
    if start is not None and not isinstance(start, str):
        raise _input_error("resolver batch start must be a string", "start")
    if end is not None and not isinstance(end, str):
        raise _input_error("resolver batch end must be a string", "end")
    all_pages = value.get("all_pages", False)
    if not isinstance(all_pages, bool):
        raise _input_error("resolver batch all_pages must be a boolean", "all_pages")
    request_id = value.get("request_id", f"item-{index + 1}")
    if not isinstance(request_id, str) or not request_id.strip():
        raise _input_error("resolver batch request_id must be a non-empty string", "request_id")
    output_fields = (
        _output_fields(value.get("output_fields"))
        if "output_fields" in value
        else default_output_fields
    )
    return _RunItem(
        request_id=request_id,
        selector=selector,
        inputs=dict(inputs),
        parameters=dict(parameters),
        app=value.get("app"),
        start=start,
        end=end,
        all_pages=all_pages,
        output_fields=output_fields,
    )


def _output_fields(value: Any) -> tuple[str, ...] | None:
    if value is None:
        return None
    if not isinstance(value, (list, tuple)) or not value or not all(
        isinstance(item, str) and item.strip() for item in value
    ):
        raise _input_error("resolver batch output_fields must be a non-empty string array", "output_fields")
    return tuple(item.strip() for item in value)


def _item_bindings(value: Mapping[str, Any]) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    if "input" in value and "inputs" in value:
        raise _input_error("resolver batch input and inputs aliases cannot be combined", "inputs")
    inputs = value.get("input", value.get("inputs", {}))
    parameters = value.get("parameters", {})
    if not isinstance(inputs, Mapping):
        raise _input_error("resolver batch inputs must be an object", "inputs")
    if not isinstance(parameters, Mapping):
        raise _input_error("resolver batch parameters must be an object", "parameters")
    return inputs, parameters


def _item_apps(
    value: Mapping[str, Any], workspace: Any
) -> tuple[list[str | int | None], list[str]]:
    if "apps" not in value:
        app = value.get("app")
        _validate_app(app, "app")
        return [app], []
    selected = value["apps"]
    if selected == "*":
        aliases = sorted(
            (str(alias) for alias in getattr(workspace, "apps", {})),
            key=lambda alias: (alias.casefold(), alias),
        )
        if not aliases:
            raise _input_error("apps='*' requires bound workspace apps", "apps")
        return aliases, aliases
    if not isinstance(selected, (list, tuple)) or not selected:
        raise _input_error("resolver batch apps must be '*' or a non-empty array", "apps")
    apps = list(selected)
    for app in apps:
        _validate_app(app, "apps")
    return apps, [str(app) for app in apps]


def _validate_app(value: Any, field: str) -> None:
    if value is None:
        return
    valid = (
        isinstance(value, str) and bool(value.strip()) and value != "*"
    ) or (type(value) is int and value > 0)
    if not valid:
        raise _input_error("resolver batch app references must be aliases or positive ids", field)


def _result_item(item: _RunItem, result: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(result, Mapping):
        raise RuntimeError("resolver returned a non-object envelope")
    ok = result.get("ok") is not False
    wrapped: dict[str, Any] = {
        "request_id": item.request_id,
        "selector": item.selector,
        "app": item.app,
        "operation_id": result.get("operation_id"),
        "ok": ok,
        "status": str(result.get("status", "success" if ok else "error")),
    }
    if ok:
        wrapped["result"] = dict(result)
    else:
        wrapped["error"] = _result_error(result).to_dict()
        wrapped["result"] = None
    return wrapped


def _exception_item(item: _RunItem, exc: Exception) -> dict[str, Any]:
    detail = (
        error_detail_from_exception(exc)
        if isinstance(exc, GravityInsightError)
        else ErrorDetail.create(
            ErrorCode.LOCAL_IO_ERROR,
            "Resolver batch item failed locally.",
            next_action="Retry this request_id alone; do not replay successful siblings.",
        )
    )
    return {
        "request_id": item.request_id,
        "selector": item.selector,
        "app": item.app,
        "operation_id": None,
        "ok": False,
        "status": "error",
        "error": detail.to_dict(),
        "result": None,
    }


def _result_error(result: Mapping[str, Any]) -> ErrorDetail:
    nested_result = result.get("result")
    candidates: list[Any] = [
        nested_result.get("error") if isinstance(nested_result, Mapping) else None,
        *(
            item.get("error")
            for item in result.get("diagnostics", [])
            if isinstance(item, Mapping)
        ),
    ]
    for candidate in candidates:
        if isinstance(candidate, Mapping) and candidate.get("code"):
            try:
                detail = ErrorDetail.create(
                    str(candidate["code"]),
                    "Resolver item failed.",
                    category=candidate.get("category"),
                    field=candidate.get("field"),
                    retryable=candidate.get("retryable"),
                    retry_after_ms=candidate.get("retry_after_ms"),
                )
            except (TypeError, ValueError):
                break
            return _caller_safe_result_error(detail)
    status = str(result.get("status", "error"))
    if status == "needs_parent":
        return ErrorDetail.create(ErrorCode.PARENT_REQUIRED, "Resolver item needs a parent selection.")
    if status in {"invalid", "stale"}:
        return ErrorDetail.create(
            "RESOLVER_INPUT_INVALID",
            "Resolver could not bind or validate this item.",
            category=ErrorCategory.CALLER,
        )
    return ErrorDetail.create(
        ErrorCode.LOCAL_IO_ERROR,
        "Resolver item failed without a structured upstream error.",
        next_action="Retry this request_id alone; do not replay successful siblings.",
    )


def _caller_safe_result_error(detail: ErrorDetail) -> ErrorDetail:
    if detail.code in {ErrorCode.AUTH_MISSING.value, ErrorCode.AUTH_REJECTED.value}:
        message = "Resolver item could not authenticate with Gravity."
        next_action = "Run `gravity auth status`, then retry this request_id alone."
    elif detail.category == ErrorCategory.CALLER.value:
        message = "Resolver item was rejected by its declared input contract."
        next_action = "Correct this request_id's selector or inputs, then retry it alone."
    elif detail.category == ErrorCategory.UPSTREAM.value:
        message = "Resolver item failed in Gravity."
        next_action = "Retry this request_id alone; do not replay successful siblings."
    else:
        message = "Resolver item failed while processing a local dependency."
        next_action = "Check the local workspace and paths, then retry this request_id alone."
    return ErrorDetail.create(
        detail.code,
        message,
        category=detail.category,
        field=detail.field,
        retryable=detail.retryable,
        retry_after_ms=detail.retry_after_ms,
        next_action=next_action,
    )


def _item_exit_code(item: Mapping[str, Any]) -> int:
    error = item.get("error")
    category = error.get("category") if isinstance(error, Mapping) else None
    return exit_code_for_category(str(category), default=ErrorCategory.LOCAL)


def _validate_limits(max_workers: int, max_pages: int, max_items: int) -> None:
    if type(max_workers) is not int or not 1 <= max_workers <= MAX_CONCURRENCY:
        raise _input_error("resolver batch concurrency must be between 1 and 24", "concurrency")
    for field, value in (("max_pages", max_pages), ("max_items", max_items)):
        if type(value) is not int or value <= 0:
            raise _input_error(f"resolver batch {field} must be a positive integer", field)


def _input_error(message: str, field: str) -> InputValidationError:
    return InputValidationError(
        message,
        field=field,
        next_action="Run `gravity batch schema --mode run` and retry with the documented fields.",
    )


__all__ = [
    "DEFAULT_MAX_ITEMS",
    "DEFAULT_MAX_PAGES",
    "ITEM_FIELDS",
    "MAX_AGGREGATE_ITEMS",
    "MAX_EXPANDED_ITEMS",
    "SCHEMA_SCHEMA_VERSION",
    "SCHEMA_VERSION",
    "resolver_batch_schema",
    "run_many",
]
