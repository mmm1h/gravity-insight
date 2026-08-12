"""Safe discovery and replay for saved Gravity Analysis definitions.

The upstream saved-report API stores an opaque JSON string.  This module does
not implement a Web configuration translator: a definition is replayable only
when its registered ``subject`` selects one of the five stable Analysis Spec
kinds and the decoded JSON already satisfies the public Analysis Spec and
FieldPolicy contracts.  Unknown subjects and Web-only config shapes therefore
fail closed before an Analysis query is sent.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .analysis_spec import compile_query_spec, prepare_query_spec, validate_query_spec
from .composite_catalog import stable_operation
from .errors import (
    ContractChangedError,
    ErrorCode,
    ErrorDetail,
    InputValidationError,
    UnsupportedOperationError,
)
from .runtime import call_read
from .saved_analysis_support import (
    DEFAULT_MAX_ITEMS,
    DEFAULT_MAX_PAGES,
    SUCCESS_STATUSES,
    SUBJECT_KINDS,
    bounds,
    catalog_rows,
    decoded_config,
    normalize_definition,
    require_one_source,
    require_success,
    safe_metadata,
    safe_query_envelope,
    safe_validation,
    select_reference,
    selected_workspace as _select_workspace,
    supported_subject,
)
from .workspace import Workspace
from .workspace_app import resolve_workspace_app


CATALOG_SCHEMA_VERSION = "gravity-insight.saved-analysis-catalog.v1"
PREVIEW_SCHEMA_VERSION = "gravity-insight.saved-analysis-preview.v1"
REPLAY_SCHEMA_VERSION = "gravity-insight.saved-analysis-replay.v1"
INSPECT_SCHEMA_VERSION = "gravity-insight.saved-analysis-inspect.v1"
LIST_OPERATION_ID = stable_operation(
    "analysis", "report_config", action="list"
).operation_id
GET_OPERATION_ID = stable_operation(
    "analysis", "report_config", action="get"
).operation_id


def list_saved_analyses(
    client: Any,
    app: str | int | None = None,
    *,
    workspace: Workspace | str | Any | None = None,
    max_pages: int = DEFAULT_MAX_PAGES,
    max_items: int = DEFAULT_MAX_ITEMS,
) -> dict[str, Any]:
    """Return the complete safe saved-analysis catalog for one workspace App.

    Only fields already projected by ``analysis.report_config.list`` are
    returned.  The opaque config is neither fetched nor included.  Pagination
    is bounded and uses a single pagination worker because the route's
    contracted maximum page size is one.
    """

    selected = _select_workspace(workspace)
    app_id = str(resolve_workspace_app(selected, app))
    pages, items = bounds(max_pages, max_items)
    envelope = call_read(
        client,
        LIST_OPERATION_ID,
        {"app_id": app_id, "page": 1, "page_size": 1},
        read_all=True,
        max_pages=pages,
        max_items=items,
        max_workers=1,
    )
    require_success(envelope, LIST_OPERATION_ID, "saved Analysis catalog")
    rows = catalog_rows(envelope, app_id)
    return {
        "schema_version": CATALOG_SCHEMA_VERSION,
        "ok": True,
        "status": "empty" if not rows else "success",
        "exit_code": 0,
        "operation_id": LIST_OPERATION_ID,
        "app_id": app_id,
        "count": len(rows),
        "items": rows,
        "network_called": True,
        "next_action": (
            "Select one item by explicit id or exact name, then prepare or execute it."
            if rows
            else "Create a saved Analysis in Gravity or select another workspace App."
        ),
    }


def resolve_saved_analysis(
    client: Any,
    reference: str | int | Mapping[str, Any],
    app: str | int | None = None,
    *,
    workspace: Workspace | str | Any | None = None,
    max_pages: int = DEFAULT_MAX_PAGES,
    max_items: int = DEFAULT_MAX_ITEMS,
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
    )


def inspect_saved_analysis(
    client: Any,
    reference: str | int | Mapping[str, Any],
    app: str | int | None = None,
    *,
    workspace: Workspace | str | Any | None = None,
    max_pages: int = DEFAULT_MAX_PAGES,
    max_items: int = DEFAULT_MAX_ITEMS,
) -> dict[str, Any]:
    """Read safe metadata and report replay eligibility without returning config."""

    selected = _select_workspace(workspace)
    definition, metadata = _read_definition(
        client,
        reference,
        app,
        workspace=selected,
        max_pages=max_pages,
        max_items=max_items,
    )
    blocker = None
    try:
        kind = supported_subject(definition.get("subject"))
        compile_query_spec(
            kind,
            decoded_config(definition.get("config")),
            workspace=selected,
            app=metadata["app_id"],
        )
        replay_status = "supported"
    except (InputValidationError, UnsupportedOperationError):
        kind = SUBJECT_KINDS.get(str(definition.get("subject")))
        replay_status = "unsupported"
        blocker = ErrorDetail.create(
            ErrorCode.UNSUPPORTED,
            "saved Analysis definition cannot be replayed through Analysis Spec v1",
            field="config",
            next_action=(
                "Use prepare to validate a supported compact definition, or run "
                "the saved configuration through Gravity Web."
            ),
        ).to_dict()
    metadata = {**metadata, "replay_supported": replay_status == "supported"}
    return {
        "schema_version": INSPECT_SCHEMA_VERSION,
        "ok": True,
        "status": "success",
        "exit_code": 0,
        "network_called": True,
        "query_executed": False,
        "saved_analysis": metadata,
        "kind": kind,
        "replay_status": replay_status,
        "blocker": blocker,
        "next_action": (
            "Prepare or execute this saved Analysis by the same explicit reference."
            if replay_status == "supported"
            else blocker["next_action"]
        ),
    }


def compile_saved_analysis_definition(
    client: Any,
    definition: Mapping[str, Any],
    app: str | int | None = None,
    *,
    workspace: Workspace | str | Any | None = None,
) -> dict[str, Any]:
    """Compile a caller-supplied definition with zero network requests.

    ``definition.config`` may be a JSON object or a JSON-encoded object.  It is
    passed unchanged to the existing Analysis Spec compiler after decoding;
    this function never translates unknown Web fields or guesses semantics.
    """

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
) -> dict[str, Any]:
    """Prepare either an upstream reference or an explicit local definition.

    An explicit definition is a true offline compile.  A reference requires
    catalog and detail reads, so its preview truthfully reports
    ``network_called=true`` while still reporting ``query_executed=false``.
    """

    require_one_source(reference, definition)
    if definition is not None:
        return compile_saved_analysis_definition(
            client,
            definition,
            app,
            workspace=workspace,
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
    )
    return _prepare_definition(
        client,
        normalized,
        app=metadata["app_id"],
        workspace=selected,
        network_called=True,
        source="catalog",
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
) -> dict[str, Any]:
    """Validate and execute one supported saved Analysis definition.

    The query is dispatched only after the saved JSON passes the existing
    Analysis Spec compiler and FieldPolicy validator.  The returned query
    envelope omits its request section so saved values are not echoed.
    """

    require_one_source(reference, definition)
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
            max_pages=max_pages,
            max_items=max_items,
        )
        app_id = metadata["app_id"]
    else:
        app_id = str(resolve_workspace_app(selected, app))
        normalized, metadata = normalize_definition(definition, expected_app_id=app_id)

    compiled, validation = _compile(
        client,
        normalized,
        app=app_id,
        workspace=selected,
    )
    query = call_read(client, compiled.operation_id, compiled.inputs)
    safe_query = safe_query_envelope(query)
    status = str(safe_query.get("status", "error"))
    ok = status in SUCCESS_STATUSES and safe_query.get("error") in (None, {})
    exit_code = _result_exit_code(safe_query) if not ok else 0
    return {
        "schema_version": REPLAY_SCHEMA_VERSION,
        "ok": ok,
        "status": status,
        "exit_code": exit_code,
        "source": source,
        "network_called": True,
        "definition_network_called": network_called,
        "query_executed": True,
        "saved_analysis": metadata,
        "kind": compiled.kind,
        "operation_id": compiled.operation_id,
        "validation": safe_validation(validation),
        "result": safe_query,
        "next_action": (
            "Consume the governed Analysis result."
            if ok
            else "Follow result.error.next_action; do not consume a failed replay."
        ),
    }


def _resolve_definition(
    client: Any,
    reference: str | int | Mapping[str, Any],
    app: str | int | None,
    *,
    workspace: Workspace | str | Any | None,
    max_pages: int,
    max_items: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    definition, metadata = _read_definition(
        client,
        reference,
        app,
        workspace=workspace,
        max_pages=max_pages,
        max_items=max_items,
    )
    return normalize_definition(definition, expected_app_id=metadata["app_id"])


def _read_definition(
    client: Any,
    reference: str | int | Mapping[str, Any],
    app: str | int | None,
    *,
    workspace: Workspace | str | Any | None,
    max_pages: int,
    max_items: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    selected = _select_workspace(workspace)
    catalog = list_saved_analyses(
        client,
        app,
        workspace=selected,
        max_pages=max_pages,
        max_items=max_items,
    )
    selected = select_reference(catalog["items"], reference)
    detail = call_read(
        client,
        GET_OPERATION_ID,
        {"app_id": catalog["app_id"], "id": selected["id"]},
    )
    require_success(detail, GET_OPERATION_ID, "saved Analysis definition")
    data = detail.get("data") if isinstance(detail, Mapping) else None
    if not isinstance(data, Mapping) or "config" not in data:
        raise ContractChangedError(
            "saved Analysis detail did not match its projected contract",
            next_action="Stop replay until analysis.report_config.get is re-verified.",
        )
    detail_name = data.get("name")
    if detail_name is not None and detail_name != selected["name"]:
        raise ContractChangedError(
            "saved Analysis identity changed between catalog and detail reads",
            next_action="List saved analyses again and retry by explicit id.",
        )
    combined = {
        key: selected[key]
        for key in ("id", "app_id", "name", "subject", "modify_time")
        if key in selected
    }
    combined["config"] = data["config"]
    return combined, safe_metadata(combined, app_id=catalog["app_id"])


def _prepare_definition(
    client: Any,
    definition: Mapping[str, Any],
    *,
    app: str,
    workspace: Any,
    network_called: bool,
    source: str,
) -> dict[str, Any]:
    kind = supported_subject(definition.get("subject"))
    spec = decoded_config(definition.get("config"))
    preview = prepare_query_spec(client, kind, spec, workspace=workspace, app=app)
    metadata = safe_metadata(definition, app_id=app)
    return {
        "schema_version": PREVIEW_SCHEMA_VERSION,
        "ok": True,
        "status": "compiled",
        "exit_code": 0,
        "source": source,
        "network_called": network_called,
        "query_executed": False,
        "saved_analysis": metadata,
        "kind": kind,
        "operation_id": preview["operation_id"],
        "compiled_input": preview["compiled_input"],
        "input_values_redacted": preview["input_values_redacted"],
        "validation": preview["validation"],
        "plan_node": preview["plan_node"],
        "next_action": preview["next_action"],
    }


def _compile(
    client: Any,
    definition: Mapping[str, Any],
    *,
    app: str,
    workspace: Any,
) -> tuple[Any, Mapping[str, Any]]:
    kind = supported_subject(definition.get("subject"))
    spec = decoded_config(definition.get("config"))
    return validate_query_spec(client, kind, spec, workspace=workspace, app=app)


def _result_exit_code(value: Mapping[str, Any]) -> int:
    error = value.get("error")
    category = error.get("category") if isinstance(error, Mapping) else None
    return {"caller": 2, "upstream": 3, "local": 4}.get(str(category), 3)


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
