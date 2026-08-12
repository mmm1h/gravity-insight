"""Bounded page orchestration shared by the public Insight client.

The first request is always synchronous.  Once Gravity reports an explicit
``total_page`` value, the remaining independent page-number requests can be
fetched in small concurrent windows while preserving result order.  Unknown
length pagination stays serial because each response decides whether another
request is valid.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any

from .drift import aggregate_contract_status
from .errors import InputValidationError, PaginationError
from .fingerprints import shape_fingerprint
from .http_runtime import MAX_CONCURRENCY
from .models import OperationSpec, ReadResult


PageExecutor = Callable[[str, Mapping[str, Any]], ReadResult]


def read_all_pages(
    execute: PageExecutor,
    operation_id: str,
    operation: OperationSpec,
    inputs: Mapping[str, Any] | None,
    *,
    max_pages: int,
    max_items: int,
    max_workers: int,
) -> dict[str, Any]:
    """Read every page within explicit bounds, parallelizing known page ranges."""

    _validate_bounds(max_pages, max_items, max_workers, input_errors=False)
    supplied = dict(inputs or {})
    first = execute(operation_id, supplied)
    if len(first.items) > max_items:
        raise PaginationError("read_all exceeded its item safety bound")
    if operation.pagination.kind == "none":
        return first.to_dict()

    page_number, page_size, total_pages = _page_state(first, operation, supplied)
    pages = [first]
    items = list(first.items)
    strategy = "serial_unknown_total"

    if total_pages is not None and page_number is not None:
        remaining = max(0, total_pages - page_number)
        if remaining + 1 > max_pages:
            raise PaginationError("read_all exceeded its page safety bound")
        expected_pages = list(range(page_number + 1, total_pages + 1))
        strategy = _fetch_known_pages(
            execute,
            operation_id,
            operation,
            supplied,
            expected_pages,
            pages,
            items,
            max_items=max_items,
            max_workers=max_workers,
        )
    else:
        current = first
        while _has_next_page(len(current.items), page_number, page_size, total_pages):
            if len(pages) >= max_pages:
                raise PaginationError("read_all exceeded its page safety bound")
            next_page = (page_number or 0) + 1
            current = _execute_page(
                execute, operation_id, operation, supplied, next_page
            )
            observed = _observed_page(current, operation, next_page)
            if observed <= (page_number or 0):
                raise PaginationError("Gravity pagination did not advance")
            page_number = observed
            candidate_total = _integer(
                current.page_info.get(operation.pagination.total_page_field),
                total_pages,
                default=total_pages,
            )
            if candidate_total is not None:
                total_pages = candidate_total
            pages.append(current)
            items.extend(current.items)
            if len(items) > max_items:
                raise PaginationError("read_all exceeded its item safety bound")

    return _merge_pages(
        operation,
        pages,
        items,
        page_size=page_size,
        total_pages=total_pages,
        has_more=False,
        strategy=strategy,
        max_workers=max_workers,
    )


def read_limited_pages(
    execute: PageExecutor,
    operation_id: str,
    operation: OperationSpec,
    inputs: Mapping[str, Any] | None,
    *,
    max_pages: int,
    max_items: int,
    max_workers: int,
) -> dict[str, Any]:
    """Read an agent-safe prefix and return a resumable next-page input."""

    _validate_bounds(max_pages, max_items, max_workers, input_errors=True)
    supplied = dict(inputs or {})
    requested_page_size, safe_page_size = _clamp_limited_page_size(
        operation, supplied, max_pages=max_pages, max_items=max_items
    )
    first = execute(operation_id, supplied)
    if operation.pagination.kind == "none":
        return _limited_nonpaginated_result(
            first, max_pages=max_pages, max_items=max_items
        )
    return _limited_paginated_result(
        execute,
        operation_id,
        operation,
        supplied,
        first,
        requested_page_size=requested_page_size,
        safe_page_size=safe_page_size,
        max_pages=max_pages,
        max_items=max_items,
        max_workers=max_workers,
    )


def _clamp_limited_page_size(
    operation: OperationSpec, supplied: dict[str, Any], *, max_pages: int, max_items: int
) -> tuple[int | None, int | None]:
    if operation.pagination.kind != "page_info":
        return None, None
    requested = _integer(
        supplied.get(operation.pagination.page_size_field),
        operation.request.defaults.get(
            operation.pagination.page_size_field,
            operation.pagination.default_page_size,
        ),
        default=max_items,
    )
    per_page_budget = max(1, max_items // max_pages)
    effective = min(requested or max_items, per_page_budget)
    supplied[operation.pagination.page_size_field] = effective
    return requested, effective


def _limited_nonpaginated_result(
    first: ReadResult, *, max_pages: int, max_items: int
) -> dict[str, Any]:
    result = first.to_dict()
    returned, original = _truncate_nonpaginated_result(result, max_items)
    result["truncated"] = original > returned
    result["next_page_input"] = None
    result["total"] = {
        "items": original,
        "pages": 1,
        "returned_items": returned,
        "returned_pages": 1,
    }
    result["safety_limits"] = {
        "max_pages": max_pages,
        "max_items": max_items,
        "page_size_clamped": False,
    }
    return result


def _limited_paginated_result(
    execute: PageExecutor, operation_id: str, operation: OperationSpec,
    supplied: Mapping[str, Any], first: ReadResult, *,
    requested_page_size: int | None, safe_page_size: int | None,
    max_pages: int, max_items: int, max_workers: int,
) -> dict[str, Any]:

    page_number, page_size, total_pages = _page_state(first, operation, supplied)
    pages = [first]
    items = list(first.items)
    next_page_number, strategy = None, "serial_unknown_total"

    if total_pages is not None and page_number is not None:
        last_allowed = min(total_pages, page_number + max_pages - 1)
        expected_pages = list(range(page_number + 1, last_allowed + 1))
        strategy, next_page_number = _fetch_known_pages_limited(
            execute, operation_id, operation, supplied, expected_pages, pages, items,
            max_items=max_items, max_workers=max_workers,
        )
        if next_page_number is None and last_allowed < total_pages:
            next_page_number = last_allowed + 1
    else:
        current = first
        while _has_next_page(len(current.items), page_number, page_size, total_pages):
            next_page = (page_number or 0) + 1
            if len(pages) >= max_pages or len(items) >= max_items:
                next_page_number = next_page
                break
            candidate = _execute_page(
                execute, operation_id, operation, supplied, next_page
            )
            observed = _observed_page(candidate, operation, next_page)
            if observed <= (page_number or 0):
                raise PaginationError("Gravity pagination did not advance")
            if len(items) + len(candidate.items) > max_items:
                next_page_number = next_page
                break
            page_number = observed
            candidate_total = _integer(
                candidate.page_info.get(operation.pagination.total_page_field),
                total_pages,
                default=total_pages,
            )
            if candidate_total is not None:
                total_pages = candidate_total
            pages.append(candidate)
            items.extend(candidate.items)
            current = candidate

    next_page_input = (
        {
            **supplied,
            operation.pagination.page_field: next_page_number,
        }
        if next_page_number is not None
        else None
    )
    result = _merge_pages(
        operation,
        pages,
        items,
        page_size=page_size,
        total_pages=total_pages,
        has_more=next_page_input is not None,
        strategy=strategy,
        max_workers=max_workers,
    )
    result["truncated"] = next_page_input is not None
    result["next_page_input"] = next_page_input
    result["total"] = {
        "items": result["page"].get("total_items"),
        "pages": total_pages,
        "returned_items": len(items),
        "returned_pages": len(pages),
    }
    result["safety_limits"] = {
        "max_pages": max_pages,
        "max_items": max_items,
        "requested_page_size": requested_page_size,
        "effective_page_size": safe_page_size,
        "page_size_clamped": requested_page_size != safe_page_size,
    }
    return result


def _fetch_known_pages(
    execute: PageExecutor,
    operation_id: str,
    operation: OperationSpec,
    supplied: Mapping[str, Any],
    expected_pages: Sequence[int],
    pages: list[ReadResult],
    items: list[Any],
    *,
    max_items: int,
    max_workers: int,
) -> str:
    if not expected_pages:
        return "single_page"
    workers = min(max_workers, len(expected_pages))
    strategy = "parallel_known_total" if workers > 1 else "serial_known_total"
    with ThreadPoolExecutor(
        max_workers=workers, thread_name_prefix="gravity-pages"
    ) as pool:
        for start in range(0, len(expected_pages), workers):
            window = list(expected_pages[start : start + workers])
            futures = _submit_window(
                pool, execute, operation_id, operation, supplied, window
            )
            for expected, future in zip(window, futures, strict=True):
                current = future.result()
                _require_expected_page(current, operation, expected)
                pages.append(current)
                items.extend(current.items)
                if len(items) > max_items:
                    for pending in futures:
                        pending.cancel()
                    raise PaginationError("read_all exceeded its item safety bound")
    return strategy


def _fetch_known_pages_limited(
    execute: PageExecutor,
    operation_id: str,
    operation: OperationSpec,
    supplied: Mapping[str, Any],
    expected_pages: Sequence[int],
    pages: list[ReadResult],
    items: list[Any],
    *,
    max_items: int,
    max_workers: int,
) -> tuple[str, int | None]:
    if not expected_pages:
        return "single_page", None
    workers = min(max_workers, len(expected_pages))
    strategy = "parallel_known_total" if workers > 1 else "serial_known_total"
    with ThreadPoolExecutor(
        max_workers=workers, thread_name_prefix="gravity-pages"
    ) as pool:
        for start in range(0, len(expected_pages), workers):
            window = list(expected_pages[start : start + workers])
            futures = _submit_window(
                pool, execute, operation_id, operation, supplied, window
            )
            for expected, future in zip(window, futures, strict=True):
                current = future.result()
                _require_expected_page(current, operation, expected)
                if len(items) + len(current.items) > max_items:
                    for pending in futures:
                        pending.cancel()
                    return strategy, expected
                pages.append(current)
                items.extend(current.items)
    return strategy, None


def _submit_window(
    pool: ThreadPoolExecutor,
    execute: PageExecutor,
    operation_id: str,
    operation: OperationSpec,
    supplied: Mapping[str, Any],
    page_numbers: Sequence[int],
) -> list[Future[ReadResult]]:
    return [
        pool.submit(
            _execute_page,
            execute,
            operation_id,
            operation,
            supplied,
            page_number,
        )
        for page_number in page_numbers
    ]


def _execute_page(
    execute: PageExecutor,
    operation_id: str,
    operation: OperationSpec,
    supplied: Mapping[str, Any],
    page_number: int,
) -> ReadResult:
    page_input = dict(supplied)
    page_input[operation.pagination.page_field] = page_number
    return execute(operation_id, page_input)


def _page_state(
    page: ReadResult,
    operation: OperationSpec,
    supplied: Mapping[str, Any],
) -> tuple[int | None, int | None, int | None]:
    page_number = _integer(
        page.page_info.get(operation.pagination.page_field),
        supplied.get(
            operation.pagination.page_field,
            operation.request.defaults.get(operation.pagination.page_field, 1),
        ),
        default=1,
    )
    page_size = _integer(
        page.page_info.get(operation.pagination.page_size_field),
        supplied.get(
            operation.pagination.page_size_field,
            operation.request.defaults.get(operation.pagination.page_size_field),
        ),
        default=None,
    )
    total_pages = _integer(
        page.page_info.get(operation.pagination.total_page_field),
        None,
        default=None,
    )
    return page_number, page_size, total_pages


def _observed_page(
    page: ReadResult, operation: OperationSpec, expected: int
) -> int:
    return _integer(
        page.page_info.get(operation.pagination.page_field),
        expected,
        default=expected,
    ) or expected


def _require_expected_page(
    page: ReadResult, operation: OperationSpec, expected: int
) -> None:
    if _observed_page(page, operation, expected) != expected:
        raise PaginationError(
            "Gravity pagination returned a different page than requested"
        )


def _merge_pages(
    operation: OperationSpec,
    pages: Sequence[ReadResult],
    items: Sequence[Any],
    *,
    page_size: int | None,
    total_pages: int | None,
    has_more: bool,
    strategy: str,
    max_workers: int,
) -> dict[str, Any]:
    result = pages[0].to_dict()
    item_field = operation.pagination.list_path.rsplit(".", 1)[-1] or "list"
    if isinstance(result["data"], Mapping):
        result["data"] = dict(result["data"])
        result["data"][item_field] = list(items)
    else:
        result["data"] = list(items)
    result["fetched_at"] = pages[-1].fetched_at
    result["warnings"] = list(
        dict.fromkeys(warning for page in pages for warning in page.warnings)
    )
    result["status"] = (
        contract_status
        if (contract_status := aggregate_contract_status({page.status for page in pages}))
        else "empty"
        if not items
        else "success"
    )
    final_page = pages[-1].page or {}
    first_page = pages[0].page or {}
    result["page"] = {
        "number": first_page.get("number", 1),
        "size": page_size,
        "item_count": len(items),
        "total_pages": total_pages,
        "total_items": final_page.get("total_items"),
        "has_more": has_more,
        "pages_fetched": len(pages),
        "fetch_strategy": strategy,
        "max_workers": max_workers,
    }
    result["schema_fingerprint"] = shape_fingerprint(result["data"])
    return result


def _validate_bounds(
    max_pages: int,
    max_items: int,
    max_workers: int,
    *,
    input_errors: bool,
) -> None:
    error_type = InputValidationError if input_errors else ValueError
    for name, value, upper in (
        ("max_pages", max_pages, 1_000),
        ("max_items", max_items, 100_000),
        ("max_workers", max_workers, MAX_CONCURRENCY),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= upper:
            message = f"{name} must be between 1 and {upper}"
            if input_errors:
                raise error_type(message, field=name)
            raise error_type(message)


def _truncate_nonpaginated_result(
    result: dict[str, Any], max_items: int
) -> tuple[int, int]:
    data = result.get("data")
    if isinstance(data, list):
        original = len(data)
        result["data"] = data[:max_items]
        return len(result["data"]), original
    if isinstance(data, Mapping):
        for key in ("list", "items"):
            rows = data.get(key)
            if isinstance(rows, list):
                original = len(rows)
                result["data"] = {**dict(data), key: rows[:max_items]}
                return min(original, max_items), original
    count = _envelope_item_count(result)
    return count, count


def _envelope_item_count(envelope: Mapping[str, Any]) -> int:
    page = envelope.get("page")
    if isinstance(page, Mapping):
        count = page.get("item_count")
        if isinstance(count, int) and not isinstance(count, bool) and count >= 0:
            return count
    data = envelope.get("data")
    if isinstance(data, list):
        return len(data)
    if isinstance(data, Mapping):
        for key in ("list", "items"):
            rows = data.get(key)
            if isinstance(rows, list):
                return len(rows)
    return 0


def _integer(primary: Any, fallback: Any, *, default: int | None) -> int | None:
    value = primary if primary is not None else fallback
    if isinstance(value, bool):
        return default
    try:
        return int(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def _has_next_page(
    item_count: int,
    page_number: int | None,
    page_size: int | None,
    total_pages: int | None,
) -> bool:
    if page_number is not None and total_pages is not None:
        return page_number < total_pages
    return bool(page_size and item_count >= page_size)


__all__ = ["read_all_pages", "read_limited_pages"]
