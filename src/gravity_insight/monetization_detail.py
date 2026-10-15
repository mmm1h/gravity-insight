"""Complete, single-day monetization detail product."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from . import runtime
from ._order_read import validate_order_read_request
from .monetization_projection import (
    DEVICE_INFO_FIELDS,
    SAFE_RE_ATTRIBUTE_FIELDS,
    SAFE_ROW_FIELDS,
)
from .monetization_query import (
    normalize_monetization_query,
    validate_monetization_operation_request,
)
from .monetization_result import (
    OPERATION_ID,
    SCHEMA_VERSION,
    monetization_detail_item_count,
    result_from_read,
    sanitize_monetization_detail_result,
)


def monetization_detail(
    client: Any,
    app_id: str | int,
    date: str,
    *,
    fields: Sequence[str] = SAFE_ROW_FIELDS,
    global_conditions: Sequence[Mapping[str, Any]] = (),
    cond_logic: str = "AND",
    local_conditions: Sequence[Mapping[str, Any]] = (),
    local_cond_logic: str = "AND",
    order_by: Sequence[Mapping[str, Any]] = (),
    segment_id: str | int | None = None,
    tmp_segment_id: str | int | None = None,
    max_workers: int = 6,
    max_pages: int = 1_000,
    max_items: int = 100_000,
) -> dict[str, Any]:
    """Read all contracted monetization rows for one natural day."""

    app, day, workers, pages, items = validate_monetization_detail_request(
        app_id,
        date,
        max_workers=max_workers,
        max_pages=max_pages,
        max_items=max_items,
    )
    profile = normalize_monetization_query(
        fields=fields,
        global_conditions=global_conditions,
        cond_logic=cond_logic,
        local_conditions=local_conditions,
        local_cond_logic=local_cond_logic,
        order_by=order_by,
        segment_id=segment_id,
        tmp_segment_id=tmp_segment_id,
    )
    inputs = {
        "app_id": app,
        "date": day,
        **profile.receipt(),
        "page": 1,
        "page_size": 100,
    }
    try:
        value = runtime.call_read(
            client,
            OPERATION_ID,
            inputs,
            read_all=True,
            max_pages=pages,
            max_items=items,
            max_workers=workers,
            forward_var_kwargs=True,
        )
    except Exception as exc:
        value = exc
    return result_from_read(
        value,
        app=app,
        day=day,
        pages=pages,
        items=items,
        workers=workers,
        query=profile.receipt(),
    )


def validate_monetization_detail_request(
    app_id: str | int,
    date: str,
    *,
    max_workers: int = 6,
    max_pages: int = 1_000,
    max_items: int = 100_000,
) -> tuple[str, str, int, int, int]:
    """Validate the caller-owned product inputs before client creation."""

    return validate_order_read_request(
        app_id,
        date,
        max_workers=max_workers,
        max_pages=max_pages,
        max_items=max_items,
        product="monetization detail",
    )


__all__ = [
    "DEVICE_INFO_FIELDS",
    "OPERATION_ID",
    "SAFE_RE_ATTRIBUTE_FIELDS",
    "SAFE_ROW_FIELDS",
    "SCHEMA_VERSION",
    "monetization_detail",
    "monetization_detail_item_count",
    "sanitize_monetization_detail_result",
    "validate_monetization_detail_request",
    "validate_monetization_operation_request",
]
