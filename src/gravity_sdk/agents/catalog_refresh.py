"""Fail-closed publication for Agent-triggered metadata refreshes."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from ..metadata_sync import default_catalog_path, sync_all_apps
from ..runtime_scope import public_scoped_path
from ..support.documents import replace_atomic_durable


def refresh_complete_catalog(
    client: Any,
    *,
    include_table_lineage: bool,
    database: str | Path | None = None,
) -> dict[str, Any]:
    """Publish a refreshed catalog only when every requested source succeeds."""

    destination = (
        Path(database) if database is not None else default_catalog_path()
    ).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=destination.parent,
            prefix=f".{destination.name}.agent-",
            suffix=".sqlite3",
            delete=False,
        ) as handle:
            staging = Path(handle.name)
        result = sync_all_apps(
            client,
            database=staging,
            include_table_lineage=include_table_lineage,
        )
        if result.get("ok") is True and result.get("status") == "success":
            replace_atomic_durable(staging, destination)
            staging = None
        return {
            **result,
            "database": public_scoped_path(
                destination, explicit=database is not None
            ),
        }
    finally:
        if staging is not None:
            staging.unlink(missing_ok=True)


__all__ = ["refresh_complete_catalog"]
