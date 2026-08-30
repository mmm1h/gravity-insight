"""Concurrent Evidence verification over configured SQL products."""

from __future__ import annotations

from datetime import date
from typing import Any

from gravity_insight.http_runtime import MAX_SQL_CONCURRENCY
from gravity_insight.sql import products
from gravity_insight.workspace import Workspace, load_workspace


def verify_all(
    client: Any,
    day: date,
    *,
    max_workers: int = MAX_SQL_CONCURRENCY,
    workspace: Workspace | None = None,
) -> dict[str, Any]:
    _validate_concurrency(max_workers)
    selected = load_workspace() if workspace is None else workspace
    start_at, end_at = products.day_window(day)
    names = products.product_names(selected)
    results = _run_all(client, names, start_at, end_at, max_workers, selected)
    return products.build_evidence(day, results, workspace=selected)


def _run_all(
    client: Any,
    names: tuple[str, ...],
    start_at: Any,
    end_at: Any,
    max_workers: int,
    workspace: Workspace,
) -> list[dict[str, Any]]:
    if len(names) == 1 or max_workers == 1:
        return [
            products.run_product(
                client, product, start_at, end_at, workspace=workspace
            )
            for product in names
        ]
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(
        max_workers=min(max_workers, len(names)),
        thread_name_prefix="gravity-sql-verify",
    ) as pool:
        return list(
            pool.map(
                lambda product: products.run_product(
                    client, product, start_at, end_at, workspace=workspace
                ),
                names,
            )
        )


def _validate_concurrency(value: int) -> None:
    if type(value) is not int or not 1 <= value <= MAX_SQL_CONCURRENCY:
        raise ValueError(
            f"SQL product concurrency must be between 1 and {MAX_SQL_CONCURRENCY}"
        )
