"""Offline metadata helpers for the unified SDK facade."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .errors import (
    GravityInsightError,
    LocalIOError,
    error_detail_from_exception,
    exit_code_for_error,
)


class MetadataSdkMixin:
    """Expose local catalogs without constructing an Insight or SQL client."""

    def table_lineage(
        self,
        query: str = "",
        *,
        database: str | Path | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Search observed table versions and operations from the local catalog.

        Expected setup failures are returned as a caller-safe ErrorDetail envelope,
        making this method convenient for Agents that should not need exception
        introspection merely to discover that lineage has not been synchronized.
        """

        from .metadata_lineage import SCHEMA_VERSION, search_table_lineage

        try:
            result = search_table_lineage(
                query,
                database=database,
                limit=limit,
                offset=offset,
            )
        except GravityInsightError as error:
            return _lineage_failure(SCHEMA_VERSION, error)
        except Exception:
            return _lineage_failure(
                SCHEMA_VERSION,
                LocalIOError(
                    "metadata table lineage catalog could not be read",
                    field="database",
                ),
            )
        safe = dict(result)
        safe.pop("database", None)
        safe["exit_code"] = 0
        return safe


def _lineage_failure(schema_version: str, error: GravityInsightError) -> dict[str, Any]:
    detail = error_detail_from_exception(error)
    return {
        "schema_version": schema_version,
        "ok": False,
        "status": "error",
        "exit_code": exit_code_for_error(detail),
        "offline": True,
        "scope": "account",
        "observed": False,
        "count": 0,
        "total": 0,
        "results": [],
        "error": detail.to_dict(),
    }


__all__ = ["MetadataSdkMixin"]
