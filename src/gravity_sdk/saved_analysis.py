"""Safe discovery and replay for saved Gravity Analysis definitions.

The upstream saved-report API stores an opaque JSON string.  This module keeps
catalog and identity orchestration separate from compilation.  Compact caller
definitions use Analysis Spec v1; persisted ``calculateBody`` artifacts use
the same five statically proven compilers as Dashboard Analysis.  Unknown
subjects and unregistered Web fields fail closed before a query is sent.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .errors import (
    ErrorCode,
    ErrorDetail,
    InputValidationError,
    PaginationError,
    UnsupportedOperationError,
)
from .saved_analysis_catalog import (
    CATALOG_SCHEMA_VERSION,
    GET_OPERATION_ID,
    LIST_OPERATION_ID,
    list_saved_analyses,
    read_saved_definition,
)
from .saved_analysis_result import (
    execute_compiled,
    replay_envelope,
    saved_result_item_count,
)
from .result_source import GOVERNED_PRODUCT, result_source
from .saved_analysis_artifact import (
    compile_saved_artifact,
    inspect_saved_artifact,
    prepare_saved_artifact,
    validate_saved_window,
)
from .saved_analysis_support import (
    DEFAULT_MAX_ITEMS,
    DEFAULT_MAX_PAGES,
    DEFAULT_MAX_WORKERS,
    SUBJECT_KINDS,
    bounds,
    normalize_definition,
    replay_capability,
    require_one_source,
    safe_metadata,
    selected_workspace as _select_workspace,
    workers,
)
from .workspace import Workspace
from .workspace_app import resolve_workspace_app


PREVIEW_SCHEMA_VERSION = "gravity-insight.saved-analysis-preview.v1"
REPLAY_SCHEMA_VERSION = "gravity-insight.saved-analysis-replay.v1"
INSPECT_SCHEMA_VERSION = "gravity-insight.saved-analysis-inspect.v1"


def resolve_saved_analysis(
    client: Any,
    reference: str | int | Mapping[str, Any],
    app: str | int | None = None,
    *,
    workspace: Workspace | str | Any | None = None,
    max_pages: int = DEFAULT_MAX_PAGES,
    max_items: int = DEFAULT_MAX_ITEMS,
    max_workers: int = DEFAULT_MAX_WORKERS,
    start: str | None = None,
    end: str | None = None,
) -> dict[str, Any]:
    """Resolve and inspect one saved definition without exposing its config.

    Resolution first reads the safe catalog and then reads the selected config.
    The returned object reports replay eligibility, but never returns the
    upstream config, its decoded values, or compiled query input.
    """

    return inspect_saved_analysis(
        client,
        reference,
        app,
        workspace=workspace,
        max_pages=max_pages,
        max_items=max_items,
        max_workers=max_workers,
        start=start,
        end=end,
    )


def inspect_saved_analysis(
    client: Any,
    reference: str | int | Mapping[str, Any],
    app: str | int | None = None,
    *,
    workspace: Workspace | str | Any | None = None,
    max_pages: int = DEFAULT_MAX_PAGES,
    max_items: int = DEFAULT_MAX_ITEMS,
    max_workers: int = DEFAULT_MAX_WORKERS,
    start: str | None = None,
    end: str | None = None,
) -> dict[str, Any]:
    """Read safe metadata and report replay eligibility without returning config."""

    validate_saved_window(start, end)
    selected = _select_workspace(workspace)
    definition, metadata = read_saved_definition(
        client,
        reference,
        app,
        workspace=selected,
        max_pages=max_pages,
        max_items=max_items,
        max_workers=max_workers,
    )
    try:
        inspection = inspect_saved_artifact(
            client,
            definition,
            app=metadata["app_id"],
            workspace=selected,
            start=start,
            end=end,
        )
        blocker = None
    except (InputValidationError, UnsupportedOperationError):
        inspection, blocker = _unsupported_inspection(definition)
    return _inspection_envelope(metadata, inspection, blocker)


def _inspection_envelope(
    metadata: Mapping[str, Any],
    inspection: Mapping[str, Any],
    blocker: Mapping[str, Any] | None,
) -> dict[str, Any]:
    replay_status = str(inspection["replay_status"])
    metadata = {
        **metadata,
        **replay_capability(replay_status),
    }
    next_action = (
        "Prepare or execute this saved Analysis by the same explicit reference."
        if replay_status == "supported"
        else (
            "Provide an explicit inclusive start/end window, then prepare or execute."
            if replay_status == "requires_window"
            else blocker["next_action"]
        )
    )
    return {
        "schema_version": INSPECT_SCHEMA_VERSION,
        "result_source": result_source(GOVERNED_PRODUCT),
        "ok": True,
        "status": "success",
        "exit_code": 0,
        "network_called": True,
        "query_executed": False,
        "saved_analysis": metadata,
        "kind": inspection.get("kind"),
        "artifact_mode": inspection.get("artifact_mode"),
        "date_range": inspection.get("date_range"),
        "date_override_applied": inspection.get("date_override_applied", False),
        "limitations": list(inspection.get("limitations", [])),
        "validation": inspection.get("validation"),
        "replay_status": replay_status,
        "blocker": blocker,
        "next_action": next_action,
    }


def _unsupported_inspection(
    definition: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    inspection = {
        "kind": SUBJECT_KINDS.get(str(definition.get("subject"))),
        "artifact_mode": None,
        "date_range": None,
        "date_override_applied": False,
        "limitations": [],
        "validation": None,
        "replay_status": "unsupported",
    }
    blocker = ErrorDetail.create(
        ErrorCode.UNSUPPORTED,
        "saved Analysis definition cannot be replayed through a proven stable contract",
        field="config",
        next_action=(
            "Correct the compact definition or keep the unregistered Web artifact "
            "unsupported until its semantics are proven."
        ),
    ).to_dict()
    return inspection, blocker


def compile_saved_analysis_definition(
    client: Any,
    definition: Mapping[str, Any],
    app: str | int | None = None,
    *,
    workspace: Workspace | str | Any | None = None,
    start: str | None = None,
    end: str | None = None,
) -> dict[str, Any]:
    """Compile a caller-supplied definition with zero network requests.

    ``definition.config`` may be a JSON object or a JSON-encoded object.  It is
    passed unchanged to the existing Analysis Spec compiler after decoding;
    this function never translates unknown Web fields or guesses semantics.
    """

    validate_saved_window(start, end)
    selected = _select_workspace(workspace)
    app_id = str(resolve_workspace_app(selected, app))
    normalized, _metadata = normalize_definition(definition, expected_app_id=app_id)
    return _prepare_definition(
        client,
        normalized,
        app=app_id,
        workspace=selected,
        network_called=False,
        source="definition",
        start=start,
        end=end,
    )


def prepare_saved_analysis(
    client: Any,
    *,
    app: str | int | None = None,
    reference: str | int | Mapping[str, Any] | None = None,
    definition: Mapping[str, Any] | None = None,
    workspace: Workspace | str | Any | None = None,
    max_pages: int = DEFAULT_MAX_PAGES,
    max_items: int = DEFAULT_MAX_ITEMS,
    max_workers: int = DEFAULT_MAX_WORKERS,
    start: str | None = None,
    end: str | None = None,
) -> dict[str, Any]:
    """Prepare either an upstream reference or an explicit local definition.

    An explicit definition is a true offline compile.  A reference requires
    catalog and detail reads, so its preview truthfully reports
    ``network_called=true`` while still reporting ``query_executed=false``.
    """

    require_one_source(reference, definition)
    validate_saved_window(start, end)
    if definition is not None:
        return compile_saved_analysis_definition(
            client,
            definition,
            app,
            workspace=workspace,
            start=start,
            end=end,
        )
    assert reference is not None
    selected = _select_workspace(workspace)
    normalized, metadata = _resolve_definition(
        client,
        reference,
        app,
        workspace=selected,
        max_pages=max_pages,
        max_items=max_items,
        max_workers=max_workers,
    )
    return _prepare_definition(
        client,
        normalized,
        app=metadata["app_id"],
        workspace=selected,
        network_called=True,
        source="catalog",
        start=start,
        end=end,
    )


def execute_saved_analysis(
    client: Any,
    *,
    app: str | int | None = None,
    reference: str | int | Mapping[str, Any] | None = None,
    definition: Mapping[str, Any] | None = None,
    workspace: Workspace | str | Any | None = None,
    max_pages: int = DEFAULT_MAX_PAGES,
    max_items: int = DEFAULT_MAX_ITEMS,
    max_workers: int = DEFAULT_MAX_WORKERS,
    start: str | None = None,
    end: str | None = None,
) -> dict[str, Any]:
    """Validate and execute one supported saved Analysis definition.

    The query is dispatched only after the saved JSON passes the existing
    Analysis Spec compiler and FieldPolicy validator.  The returned query
    envelope omits its request section so saved values are not echoed.
    """

    require_one_source(reference, definition)
    validate_saved_window(start, end)
    pages, items = bounds(max_pages, max_items)
    page_workers = workers(max_workers)
    selected = _select_workspace(workspace)
    network_called = reference is not None
    source = "catalog" if network_called else "definition"
    if definition is None:
        assert reference is not None
        normalized, metadata = _resolve_definition(
            client,
            reference,
            app,
            workspace=selected,
            max_pages=pages,
            max_items=items,
            max_workers=page_workers,
        )
        app_id = metadata["app_id"]
    else:
        app_id = str(resolve_workspace_app(selected, app))
        normalized, metadata = normalize_definition(definition, expected_app_id=app_id)

    compiled = compile_saved_artifact(
        client,
        normalized,
        app=app_id,
        workspace=selected,
        start=start,
        end=end,
    )
    safe_query = execute_compiled(client, compiled)
    if saved_result_item_count(compiled.operation_id, safe_query) > items:
        raise PaginationError(
            "saved Analysis query exceeded its result item safety bound",
            next_action="Increase max_items within the documented limit and retry.",
        )
    return replay_envelope(
        REPLAY_SCHEMA_VERSION,
        compiled,
        safe_query,
        metadata,
        source=source,
        definition_network_called=network_called,
    )


def _resolve_definition(
    client: Any,
    reference: str | int | Mapping[str, Any],
    app: str | int | None,
    *,
    workspace: Workspace | str | Any | None,
    max_pages: int,
    max_items: int,
    max_workers: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    definition, metadata = read_saved_definition(
        client,
        reference,
        app,
        workspace=workspace,
        max_pages=max_pages,
        max_items=max_items,
        max_workers=max_workers,
    )
    return normalize_definition(definition, expected_app_id=metadata["app_id"])


def _prepare_definition(
    client: Any,
    definition: Mapping[str, Any],
    *,
    app: str,
    workspace: Any,
    network_called: bool,
    source: str,
    start: str | None,
    end: str | None,
) -> dict[str, Any]:
    preview = prepare_saved_artifact(
        client,
        definition,
        app=app,
        workspace=workspace,
        start=start,
        end=end,
    )
    if source == "catalog":
        preview = {
            **preview,
            "compiled_input": None,
            "input_values_redacted": True,
            "plan_node": None,
            "next_action": (
                "Execute the saved reference through the governed replay entrypoint; "
                "catalog-derived query inputs are intentionally not returned."
            ),
        }
    metadata = safe_metadata(definition, app_id=app)
    capability = replay_capability("supported")
    return {
        "schema_version": PREVIEW_SCHEMA_VERSION,
        "result_source": result_source(GOVERNED_PRODUCT),
        "ok": True,
        "status": "compiled",
        "exit_code": 0,
        "source": source,
        "network_called": network_called,
        "definition_network_called": network_called,
        "query_executed": False,
        "saved_analysis": {**metadata, **capability},
        "replay_status": capability["replay_status"],
        "artifact_mode": preview["artifact_mode"],
        "kind": preview["kind"],
        "operation_id": preview["operation_id"],
        "date_range": preview.get("date_range"),
        "date_override_applied": preview.get("date_override_applied", False),
        "limitations": list(preview.get("limitations", [])),
        "compiled_input": preview["compiled_input"],
        "input_values_redacted": preview["input_values_redacted"],
        "validation": preview["validation"],
        "plan_node": preview["plan_node"],
        "next_action": preview["next_action"],
    }


__all__ = [
    "CATALOG_SCHEMA_VERSION",
    "PREVIEW_SCHEMA_VERSION",
    "REPLAY_SCHEMA_VERSION",
    "INSPECT_SCHEMA_VERSION",
    "SUBJECT_KINDS",
    "compile_saved_analysis_definition",
    "execute_saved_analysis",
    "inspect_saved_analysis",
    "list_saved_analyses",
    "prepare_saved_analysis",
    "resolve_saved_analysis",
]
