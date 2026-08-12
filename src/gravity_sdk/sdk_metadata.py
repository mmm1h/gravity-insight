"""Offline metadata helpers for the unified SDK facade."""

from __future__ import annotations

from dataclasses import replace
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

    def analysis_vocabulary(
        self,
        query: str = "",
        *,
        kind: str = "vocabulary",
        database: str | Path | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Search synchronized Analysis vocabulary without creating clients.

        The local catalog is the complete execution boundary: this method never
        falls back to the online Analysis context when the snapshot is missing or
        stale.  Setup failures remain normal ErrorDetail envelopes so an Agent can
        synchronize once and retry without inspecting Python exceptions.
        """

        from .find_metadata import SCHEMA_VERSION, search_metadata

        try:
            result = search_metadata(
                query,
                database=database,
                kind=kind,
                limit=limit,
                offset=offset,
            )
        except GravityInsightError as error:
            return _vocabulary_failure(SCHEMA_VERSION, kind, error)
        except Exception:
            return _vocabulary_failure(
                SCHEMA_VERSION,
                kind,
                LocalIOError(
                    "analysis vocabulary catalog could not be read",
                    field="database",
                ),
            )
        safe = dict(result)
        safe.pop("database", None)
        safe["exit_code"] = 0
        return safe

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


_VOCABULARY_SYNC_ACTION = (
    "Run `gravity metadata sync --all-apps`, then retry the same offline "
    "analysis vocabulary search."
)


def _vocabulary_failure(
    schema_version: str,
    kind: str,
    error: GravityInsightError,
) -> dict[str, Any]:
    if error.field == "database":
        detail = replace(
            error_detail_from_exception(
                error,
                next_action=_VOCABULARY_SYNC_ACTION,
            ),
            message="analysis vocabulary catalog is missing or incompatible",
        )
    else:
        detail = error_detail_from_exception(error)
    return {
        "schema_version": schema_version,
        "ok": False,
        "status": "error",
        "exit_code": exit_code_for_error(detail),
        "offline": True,
        "scope": "workspace",
        "kind": kind,
        "count": 0,
        "total": 0,
        "results": [],
        "error": detail.to_dict(),
    }


__all__ = ["MetadataSdkMixin"]
