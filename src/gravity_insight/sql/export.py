from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from time import perf_counter
from typing import Callable, Protocol

try:
    from gravity_insight.errors import GravityExportError
except ModuleNotFoundError:  # pragma: no cover - source checkout without install.
    from gravity_insight.errors import GravityExportError


ProgressCallback = Callable[[str], None]
DEFAULT_EXPORT_CONCURRENCY = 2
MAX_EXPORT_CONCURRENCY = 2


class SqlClient(Protocol):
    def execute_sql(self, sql: str) -> list[dict]:
        ...


@dataclass(frozen=True)
class ExportPage:
    page_index: int
    offset: int
    requested_limit: int
    rows: int


@dataclass(frozen=True)
class ExportAudit:
    total_rows: int
    page_size: int
    pages: list[ExportPage]
    duplicate_user_ids: int
    status: str
    reason: str


def build_paged_sql(sql: str, page_size: int, offset: int) -> str:
    if page_size <= 0:
        raise ValueError("export page size must be positive")
    if offset < 0:
        raise ValueError("export offset cannot be negative")
    body = sql.strip().rstrip(";")
    return (
        "SELECT * FROM (\n"
        f"{body}\n"
        ") rfm_export_page\n"
        "ORDER BY user_id\n"
        f"LIMIT {page_size} OFFSET {offset}"
    )


def fetch_all_rows(
    client: SqlClient,
    sql: str,
    page_size: int,
    progress: ProgressCallback | None = None,
    *,
    max_concurrency: int = DEFAULT_EXPORT_CONCURRENCY,
) -> list[dict]:
    rows, _audit = fetch_all_rows_with_audit(
        client,
        sql,
        page_size,
        progress=progress,
        max_concurrency=max_concurrency,
    )
    return rows


def fetch_all_rows_with_audit(
    client: SqlClient,
    sql: str,
    page_size: int,
    progress: ProgressCallback | None = None,
    label: str = "export",
    *,
    max_concurrency: int = DEFAULT_EXPORT_CONCURRENCY,
) -> tuple[list[dict], ExportAudit]:
    _validate_concurrency(max_concurrency)
    rows: list[dict] = []
    pages: list[ExportPage] = []

    # Keep the first page synchronous. Besides preserving the existing first-page
    # guard, this avoids launching speculative SQL when the export fits in one page.
    first_page, first_elapsed = _fetch_page(client, sql, page_size, 0, label, progress)
    _record_page(rows, pages, first_page, first_elapsed, page_size, 0, label, progress)

    if len(first_page) == page_size:
        # The synchronous first request is the initial width=1 stage. Later
        # windows stay at the live-verified SQL ceiling of two.
        next_page_index = 1
        window_size = min(2, max_concurrency)
        with ThreadPoolExecutor(max_workers=max_concurrency, thread_name_prefix="gravity-export") as executor:
            while True:
                futures: list[tuple[int, Future[tuple[list[dict], float]]]] = []
                for page_index in range(next_page_index, next_page_index + window_size):
                    offset = page_index * page_size
                    _report_request(label, page_index, offset, page_size, progress)
                    future = executor.submit(_execute_page, client, sql, page_size, offset)
                    futures.append((page_index, future))

                terminal_page_seen = False
                for position, (page_index, future) in enumerate(futures):
                    offset = page_index * page_size
                    try:
                        page, elapsed = future.result()
                    except Exception as exc:
                        raise GravityExportError(f"{label}: page={page_index} request failed") from exc
                    _record_page(rows, pages, page, elapsed, page_size, offset, label, progress)
                    if len(page) < page_size:
                        terminal_page_seen = True
                        # Later pages in this window are speculative. They must not
                        # affect row order, audit output, or export success.
                        for _, later_future in futures[position + 1 :]:
                            later_future.cancel()
                        break

                if terminal_page_seen:
                    break
                next_page_index += window_size
                window_size = min(window_size * 2, max_concurrency)

    audit = _build_audit(rows, page_size, pages)
    return rows, audit


def _validate_concurrency(value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_EXPORT_CONCURRENCY:
        raise ValueError(f"export concurrency must be between 1 and {MAX_EXPORT_CONCURRENCY}")


def _fetch_page(
    client: SqlClient,
    sql: str,
    page_size: int,
    page_index: int,
    label: str,
    progress: ProgressCallback | None,
) -> tuple[list[dict], float]:
    offset = page_index * page_size
    _report_request(label, page_index, offset, page_size, progress)
    try:
        return _execute_page(client, sql, page_size, offset)
    except Exception as exc:
        raise GravityExportError(f"{label}: page={page_index} request failed") from exc


def _execute_page(
    client: SqlClient,
    sql: str,
    page_size: int,
    offset: int,
) -> tuple[list[dict], float]:
    started = perf_counter()
    page = client.execute_sql(build_paged_sql(sql, page_size, offset))
    return page, perf_counter() - started


def _report_request(
    label: str,
    page_index: int,
    offset: int,
    page_size: int,
    progress: ProgressCallback | None,
) -> None:
    if progress:
        progress(f"{label}: request page={page_index} offset={offset} limit={page_size}")


def _record_page(
    rows: list[dict],
    pages: list[ExportPage],
    page: list[dict],
    elapsed: float,
    page_size: int,
    offset: int,
    label: str,
    progress: ProgressCallback | None,
) -> None:
    _guard_page_shape(page, page_size, offset)
    page_index = offset // page_size
    pages.append(ExportPage(page_index, offset, page_size, len(page)))
    rows.extend(page)
    if progress:
        progress(f"{label}: page={page_index} rows={len(page)} total_rows={len(rows)} elapsed={elapsed:.1f}s")


def audit_rows(audit: ExportAudit) -> list[dict]:
    rows = [
        {
            "row_type": "summary",
            "total_rows": audit.total_rows,
            "page_size": audit.page_size,
            "pages": len(audit.pages),
            "duplicate_user_ids": audit.duplicate_user_ids,
            "status": audit.status,
            "reason": audit.reason,
        }
    ]
    rows.extend(
        {
            "row_type": "page",
            "page_index": page.page_index,
            "offset": page.offset,
            "requested_limit": page.requested_limit,
            "rows": page.rows,
        }
        for page in audit.pages
    )
    return rows


def _guard_page_shape(page: list[dict], page_size: int, offset: int) -> None:
    if offset == 0 and page_size > 100 and len(page) == 100:
        raise GravityExportError(
            "Paged export returned exactly 100 rows on the first page. "
            "This looks like Gravity's default limit; full export is not trusted."
        )


def _build_audit(rows: list[dict], page_size: int, pages: list[ExportPage]) -> ExportAudit:
    duplicate_user_ids = _duplicate_user_ids(rows)
    status = "PASS" if rows and duplicate_user_ids == 0 else "FAIL"
    reason = "Export completed without duplicate user_id." if status == "PASS" else "Export has no rows or duplicate user_id."
    return ExportAudit(len(rows), page_size, pages, duplicate_user_ids, status, reason)


def _duplicate_user_ids(rows: list[dict]) -> int:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for row in rows:
        user_id = str(row.get("user_id", ""))
        if not user_id:
            continue
        if user_id in seen:
            duplicates.add(user_id)
        seen.add(user_id)
    return len(duplicates)
