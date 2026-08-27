"""Offline metadata helpers for the unified SDK facade."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

from .actionable_error_values import actual_value
from .errors import (
    GravityInsightError,
    LocalIOError,
    error_detail_from_exception,
    exit_code_for_error,
)
from .result_source import LOCAL_CATALOG, result_source


class MetadataSdkMixin:
    """Expose local catalogs without constructing an Insight or SQL client."""

    def sync_metadata_app(
        self,
        app_id: str | int,
        *,
        database: str | Path | None = None,
        max_pages: int = 2,
        concurrency: int = 8,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Refresh one App under a declared page/request bound."""

        from .metadata_onboarding import estimate_app_sync, sync_app

        if not isinstance(dry_run, bool):
            from .errors import InputValidationError

            raise InputValidationError(
                "metadata dry_run actual value must be a boolean: "
                f"{actual_value(dry_run)}",
                field="dry_run",
                next_action="Replace dry_run with true or false, then retry the same App sync.",
            )
        if dry_run:
            return estimate_app_sync(
                app_id, database=database, max_pages=max_pages
            )
        return sync_app(
            self.insight,
            app_id,
            database=database,
            max_pages=max_pages,
            concurrency=concurrency,
        )

    def metadata_status(
        self,
        *,
        database: str | Path | None = None,
        app_id: str | int | None = None,
        max_age_hours: int = 24,
    ) -> dict[str, Any]:
        """Inspect local App coverage and freshness with zero network access."""

        from .metadata_status import metadata_status

        return metadata_status(
            database=database,
            app_id=app_id,
            max_age_hours=max_age_hours,
        )

    def metadata_cache_stats(self) -> dict[str, int | float]:
        from .cache import metadata_cache_stats

        return metadata_cache_stats(self.insight)

    def clear_metadata_cache(self) -> dict[str, int | float]:
        from .cache import clear_metadata_cache

        return clear_metadata_cache(self.insight)

    def bypass_metadata_cache(self, enabled: bool = True) -> dict[str, int | float]:
        from .cache import bypass_metadata_cache

        return bypass_metadata_cache(self.insight, enabled)

    def resolve_capabilities(
        self,
        query: str,
        *,
        known_inputs: dict[str, Any],
        workspace: Any | None = None,
        domain: str | None = None,
        platform: str | None = None,
        limit: int = 3,
    ) -> dict[str, Any]:
        """Discover a capability and its complete live input catalogs."""

        from .agents.input_resolution import resolve_capabilities

        selected_workspace = self._select_workspace(workspace)
        return resolve_capabilities(
            query,
            known_inputs=known_inputs,
            client=self.insight,
            workspace=selected_workspace,
            domain=domain,
            platform=platform,
            limit=limit,
        )

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
        "result_source": result_source(LOCAL_CATALOG),
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
        "result_source": result_source(LOCAL_CATALOG),
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
