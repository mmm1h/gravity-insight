"""Closed R13C Analysis Artifact to Dashboard notes connector."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from .action_connector_support import (
    WriteTrackingClient,
    current_principal,
    deduplicate_receipts,
)
from .agent_runtime_contracts import (
    AgentRuntimeContractError,
    canonical_digest,
    is_sha256,
    validate_schema,
)
from .analysis_artifact import validate_analysis_artifact
from .analysis_artifact_markdown import (
    AnalysisArtifactRenderError,
    render_analysis_artifact_markdown,
)
from .errors import InputValidationError
from .kanban_content_mutation import replace_notes
from .kanban_mutation_contracts import DASHBOARD_UPDATE, DETAIL
from .kanban_mutation_support import (
    dashboard_preimage_digest,
    read_detail,
    report_list,
    require_dashboard_authority,
)
from .mutation_lifecycle import mutation_digest, mutation_marker
from .result_audit import result_receipt_references


ACTION_KIND = "dashboard.publish_analysis_artifact"
CONNECTOR_ID = "gravity.analysis-dashboard-notes"
CONNECTOR_VERSION = 1
REQUEST_SCHEMA_VERSION = "gravity.analysis-dashboard-request.v1"
MANAGED_FIELDS = ("dashboard_notes",)
MAX_NOTES = 20
MAX_NOTE_CHARACTERS = 4_000
MASKED_PATHS = ("/request/artifact",)

_REQUEST_SCHEMA_NAME = "analysis-dashboard-request-v1.schema.json"
_PRESENTATION = {
    "visualization": "markdown_notes",
    "filter_mode": "artifact_scope",
    "layout": "single_column",
}
_SCOPE_FIELDS = frozenset({"app", "start", "end", "timezone", "filters"})
_DIGEST_FIELDS = (
    "definition_digest",
    "binding_digest",
    "source_digest",
    "registry_digest",
)


def prepare_dashboard_delivery(
    client: Any, workspace: Any, request: Mapping[str, Any]
) -> dict[str, Any]:
    """Compile the target and read its exact preimage without mutation."""

    normalized = normalize_request(workspace, request)
    target = normalized["target"]
    detail = read_detail(
        client, target["app_id"], target["space_id"], target["dashboard_id"]
    )
    _require_target_coordinates(detail, target)
    if report_list(detail):
        _gap(
            "DASHBOARD_TARGET_UNSUPPORTED",
            "request.target.dashboard_id",
            "a note-only Dashboard with no report associations",
        )
    ownership = require_dashboard_authority(
        client, detail, target["dashboard_id"]
    )
    principal = current_principal(client)
    return {
        "normalized": normalized,
        "principal_digest": mutation_digest({"principal_id": principal}),
        "target_digest": _target_digest(target),
        "preimage_digest": dashboard_preimage_digest(detail),
        "ownership_digest": mutation_digest(ownership.public()),
        "ownership_basis": ownership.basis,
        "contract_fingerprint": connector_contract_fingerprint(client),
    }


def current_execution_binding(
    client: Any, workspace: Any, request: Mapping[str, Any]
) -> dict[str, Any]:
    normalized = normalize_request(workspace, request)
    principal = current_principal(client)
    return {
        "normalized": normalized,
        "principal_digest": mutation_digest({"principal_id": principal}),
        "target_digest": _target_digest(normalized["target"]),
        "contract_fingerprint": connector_contract_fingerprint(client),
    }


def execute_dashboard_delivery(
    client: Any,
    normalized: Mapping[str, Any],
    *,
    expected_preimage_digest: str,
) -> dict[str, Any]:
    """Delegate exactly one write and exact readback to the Kanban owner."""

    tracking = WriteTrackingClient(client)
    target = normalized["target"]
    try:
        result = replace_notes(
            tracking,
            app_id=target["app_id"],
            space_id=target["space_id"],
            dashboard_id=target["dashboard_id"],
            notes=normalized["notes"],
            execute=True,
            _expected_preimage_digest=expected_preimage_digest,
        )
    except Exception as error:
        return {
            "result": None,
            "error": error,
            "write_attempts": tracking.write_attempts,
        }
    return {
        "result": result,
        "error": None,
        "write_attempts": tracking.write_attempts,
    }


def verified_readback(
    result: Any, normalized: Mapping[str, Any]
) -> dict[str, Any] | None:
    if not isinstance(result, Mapping) or result.get("status") != "updated":
        return None
    target = result.get("target")
    expected_target = normalized["target"]
    if not isinstance(target, Mapping):
        return None
    notes = target.get("notes")
    markers = (
        [item.get("marker") for item in notes]
        if isinstance(notes, list) and all(isinstance(item, Mapping) for item in notes)
        else None
    )
    if (
        target.get("id") != expected_target["dashboard_id"]
        or target.get("space_id") != expected_target["space_id"]
        or target.get("note_count") != len(normalized["notes"])
        or markers != normalized["expected_markers"]
    ):
        return None
    references = copy.deepcopy(normalized["artifact"]["evidence"]["receipt_references"])
    references.extend(result_receipt_references(result))
    references.extend(result_receipt_references(result.get("mutation")))
    return {
        "target": {
            "kind": "dashboard",
            **copy.deepcopy(expected_target),
            "note_count": len(markers),
            "note_markers": list(markers),
            "presentation": copy.deepcopy(normalized["presentation"]),
            "source_binding": copy.deepcopy(normalized["source_binding"]),
        },
        "assertions": [
            {"id": "dashboard_identity", "status": "verified"},
            {"id": "note_content_markers", "status": "verified"},
            {"id": "source_artifact_binding", "status": "verified"},
        ],
        "receipt_references": deduplicate_receipts(references),
    }


def confirmation_summary(
    normalized: Mapping[str, Any], ownership_basis: str
) -> dict[str, Any]:
    target = normalized["target"]
    return {
        "target": {"kind": "dashboard", **copy.deepcopy(target)},
        "expected_changes": [
            {
                "field": "dashboard_notes",
                "value_summary": {
                    "count": len(normalized["notes"]),
                    "notes_digest": normalized["notes_digest"],
                },
            },
            {
                "field": "source_artifact",
                "value_summary": copy.deepcopy(normalized["source_binding"]),
            },
        ],
        "managed_fields": list(MANAGED_FIELDS),
        "ownership_basis": ownership_basis,
        "readback_assertions": [
            "dashboard_identity",
            "note_content_markers",
            "source_artifact_binding",
        ],
        "limitations": [
            "note_only_dashboard_required",
            "markdown_notes_artifact_scope_single_column_only",
        ],
    }


def normalize_request(
    workspace: Any, request: Mapping[str, Any]
) -> dict[str, Any]:
    if not isinstance(request, Mapping):
        _invalid("request must be an object")
    selected = copy.deepcopy(dict(request))
    try:
        validate_schema(selected, _REQUEST_SCHEMA_NAME, "Dashboard Action request")
    except AgentRuntimeContractError:
        _invalid("request must match gravity.analysis-dashboard-request.v1")
    try:
        artifact = validate_analysis_artifact(selected["artifact"])
    except AgentRuntimeContractError:
        _gap(
            "DASHBOARD_ARTIFACT_INVALID",
            "request.artifact",
            "one intact gravity.analysis-artifact.v1",
        )
    if artifact["status"] != "success" or artifact["can_run_status"] != "verified":
        _gap(
            "DASHBOARD_ARTIFACT_UNDELIVERABLE",
            "request.artifact.status",
            "a successful verified Analysis Artifact",
        )
    presentation = selected["presentation"]
    _require_presentation(presentation)
    target = selected["target"]
    _require_semantic_bindings(artifact)
    _require_scope_binding(artifact["filters"]["values"], target["app_id"], workspace)
    _require_claims(artifact["claims"])
    try:
        rendering = render_analysis_artifact_markdown(artifact)
    except AnalysisArtifactRenderError:
        _gap(
            "DASHBOARD_CONTENT_UNREPRESENTABLE",
            "request.artifact",
            "Artifact Markdown within the Dashboard note budget",
        )
    chunks = _line_chunks(rendering["content"])
    notes = _notes(artifact["artifact_digest"], chunks)
    expected_markers = _note_markers(target["dashboard_id"], notes)
    source_binding = _source_binding(artifact, rendering)
    return {
        "artifact": artifact,
        "target": copy.deepcopy(target),
        "presentation": copy.deepcopy(presentation),
        "rendering": rendering,
        "notes": notes,
        "notes_digest": canonical_digest(notes),
        "expected_markers": expected_markers,
        "source_binding": source_binding,
    }


def connector_contract_fingerprint(client: Any) -> str:
    contracts = []
    for operation_id in (DETAIL, DASHBOARD_UPDATE):
        value = client.describe(operation_id)
        if not isinstance(value, Mapping):
            _invalid("connector operation contracts must be available")
        contracts.append(
            {"operation_id": operation_id, "contract": copy.deepcopy(dict(value))}
        )
    return mutation_digest({"contracts": contracts})


def _require_presentation(value: Mapping[str, Any]) -> None:
    checks = (
        (
            "visualization",
            "DASHBOARD_VISUALIZATION_UNSUPPORTED",
            "markdown_notes",
        ),
        ("filter_mode", "DASHBOARD_FILTER_MODE_UNSUPPORTED", "artifact_scope"),
        ("layout", "DASHBOARD_LAYOUT_UNSUPPORTED", "single_column"),
    )
    for field, code, expected in checks:
        if value.get(field) != expected:
            _gap(code, f"request.presentation.{field}", expected)


def _require_semantic_bindings(artifact: Mapping[str, Any]) -> None:
    references: dict[str, Mapping[str, Any]] = {}
    for item in artifact["semantic_references"]:
        uri = item["uri"]
        if uri in references:
            _gap(
                "DASHBOARD_SEMANTIC_BINDING_UNRESOLVED",
                "request.artifact.semantic_references",
                "unique resolved Semantic identities",
            )
        references[uri] = item
    typed = [*artifact["metric_uris"], *artifact["dimension_uris"]]
    if len(typed) != len(set(typed)):
        _gap(
            "DASHBOARD_SEMANTIC_BINDING_UNRESOLVED",
            "request.artifact.metric_uris",
            "disjoint Metric and Dimension identities",
        )
    for uri in typed:
        reference = references.get(uri)
        valid = (
            reference is not None
            and reference.get("status") == "resolved"
            and type(reference.get("version")) is int
            and all(is_sha256(reference.get(field)) for field in _DIGEST_FIELDS)
        )
        if not valid:
            _gap(
                "DASHBOARD_SEMANTIC_BINDING_UNRESOLVED",
                "request.artifact.semantic_references",
                "resolved versioned Metric/Dimension references with complete digests",
            )


def _require_scope_binding(scope: Any, app_id: int, workspace: Any) -> None:
    if not isinstance(scope, Mapping) or set(scope) - _SCOPE_FIELDS:
        _gap(
            "DASHBOARD_FILTER_MODE_UNSUPPORTED",
            "request.artifact.filters",
            "artifact scope fields app/start/end/timezone/filters",
        )
    if _scope_app_id(scope.get("app"), workspace) != app_id:
        _gap(
            "DASHBOARD_SOURCE_BINDING_UNRESOLVED",
            "request.artifact.filters.values.app",
            "a Workspace App bound to request.target.app_id",
        )
    timezone_name = scope.get("timezone")
    if timezone_name is not None and (
        not isinstance(timezone_name, str)
        or not timezone_name.strip()
        or len(timezone_name) > 64
    ):
        _gap(
            "DASHBOARD_FILTER_MODE_UNSUPPORTED",
            "request.artifact.filters.values.timezone",
            "a non-empty timezone name of at most 64 characters",
        )
    start, end = scope.get("start"), scope.get("end")
    if (start is None) != (end is None):
        _date_gap()
    if start is not None:
        left, right = _date(start), _date(end)
        if left is None or right is None or right < left:
            _date_gap()


def _scope_app_id(value: Any, workspace: Any) -> int | None:
    if type(value) is int:
        return value if value > 0 else None
    if isinstance(value, str):
        selected = value.strip()
        if selected.isdecimal() and int(selected) > 0:
            return int(selected)
        apps = getattr(workspace, "apps", None)
        if isinstance(apps, Mapping) and selected in apps:
            bound = apps[selected]
            if type(bound) is int and bound > 0:
                return bound
    return None


def _date(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=parsed.tzinfo or timezone.utc).astimezone(timezone.utc)


def _date_gap() -> None:
    _gap(
        "DASHBOARD_DATE_FILTER_INVALID",
        "request.artifact.filters.values.start/end",
        "paired ordered ISO start/end values",
    )


def _require_claims(claims: Mapping[str, Any]) -> None:
    claim_ids = [item["claim_id"] for item in claims["allowed"]]
    if len(claim_ids) != len(set(claim_ids)):
        _gap(
            "DASHBOARD_ARTIFACT_INVALID",
            "request.artifact.claims.allowed",
            "unique allowed claim identities",
        )


def _line_chunks(content: str) -> list[str]:
    chunks: list[str] = []
    current = ""
    for line in content.splitlines(keepends=True):
        if len(line) > MAX_NOTE_CHARACTERS:
            _content_gap()
        if current and len(current) + len(line) > MAX_NOTE_CHARACTERS:
            chunks.append(current.strip())
            current = ""
        current += line
    if current.strip():
        chunks.append(current.strip())
    if not chunks or len(chunks) > MAX_NOTES:
        _content_gap()
    return chunks


def _notes(artifact_digest: str, chunks: list[str]) -> list[dict[str, str]]:
    total = len(chunks)
    return [
        {
            "title": f"Analysis Artifact {index}/{total}",
            "content": content,
            "idempotency_key": f"{artifact_digest}:{index}",
        }
        for index, content in enumerate(chunks, 1)
    ]


def _note_markers(
    dashboard_id: int, notes: list[Mapping[str, str]]
) -> list[str]:
    return [
        mutation_marker(
            "kanban_note",
            {
                "dashboard_id": dashboard_id,
                "index": index,
                "title": item["title"],
                "content": item["content"],
            },
            idempotency_key=item["idempotency_key"],
        )
        for index, item in enumerate(notes)
    ]


def _source_binding(
    artifact: Mapping[str, Any], rendering: Mapping[str, Any]
) -> dict[str, str]:
    return {
        "artifact_id": artifact["artifact_id"],
        "artifact_digest": artifact["artifact_digest"],
        "result_digest": artifact["source"]["result_digest"],
        "execution_snapshot_digest": artifact["source"]["execution_snapshot_digest"],
        "receipt_references_digest": artifact["source"]["receipt_references_digest"],
        "semantic_references_digest": canonical_digest(
            {
                "metric_uris": artifact["metric_uris"],
                "dimension_uris": artifact["dimension_uris"],
                "references": artifact["semantic_references"],
            }
        ),
        "filters_digest": canonical_digest(artifact["filters"]),
        "claims_digest": canonical_digest(artifact["claims"]),
        "rendering_binding_digest": rendering["binding_digest"],
        "rendered_content_sha256": rendering["content_sha256"],
    }


def _target_digest(target: Mapping[str, Any]) -> str:
    return mutation_digest(
        {
            "app_id": target["app_id"],
            "space_id": target["space_id"],
            "dashboard_id": target["dashboard_id"],
        }
    )


def _require_target_coordinates(
    detail: Mapping[str, Any], target: Mapping[str, Any]
) -> None:
    for field in ("app_id", "space_id"):
        value = detail.get(field)
        if value is not None and str(value) != str(target[field]):
            _gap(
                "DASHBOARD_SOURCE_BINDING_UNRESOLVED",
                f"request.target.{field}",
                f"Dashboard detail {field} {value}",
            )


def _content_gap() -> None:
    _gap(
        "DASHBOARD_CONTENT_UNREPRESENTABLE",
        "request.artifact",
        f"at most {MAX_NOTES} complete notes of {MAX_NOTE_CHARACTERS} characters",
    )


def _invalid(allowed: str) -> None:
    raise InputValidationError(
        f"actual value: invalid Dashboard Action request; allowed value: {allowed}",
        field="request",
        code="ACTION_REQUEST_INVALID",
        next_action="Correct the exact Dashboard delivery request and preview a new Action Plan.",
    )


def _gap(code: str, field: str, allowed: str) -> None:
    raise InputValidationError(
        f"actual value: unsupported Dashboard delivery binding; allowed value: {allowed}",
        field=field,
        code=code,
        next_action="Use the documented R13C subset and preview a new explicitly authorized Action Plan.",
    )


__all__ = [
    "ACTION_KIND",
    "CONNECTOR_ID",
    "CONNECTOR_VERSION",
    "MANAGED_FIELDS",
    "MASKED_PATHS",
    "REQUEST_SCHEMA_VERSION",
    "confirmation_summary",
    "current_execution_binding",
    "execute_dashboard_delivery",
    "normalize_request",
    "prepare_dashboard_delivery",
    "verified_readback",
]
