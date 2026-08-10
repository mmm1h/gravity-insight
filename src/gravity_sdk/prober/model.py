"""Compatibility facade for the contract probe model helpers."""

from .core import (
    CONTRACT_ROOT,
    COVERAGE_PATH,
    DRAFT_ROOT,
    EVIDENCE_ROOT,
    OPERATION_ROOT,
    REPO_ROOT,
    TMP_ROOT,
    canonical_fingerprint,
    display_path as _display_path,
    read_json as _read_json,
    write_json as _write_json,
)
from .drafts import (
    build_draft,
    build_conservative_draft,
    create_bulk_drafts,
    create_drafts,
    create_write_registry,
    existing_operations as _existing_operations,
    infer_identity,
    refresh_structured_blockers,
    route_family_id as _route_family_id,
    select_routes,
)
from .privacy import (
    build_projection,
    candidate_fields,
    classify_field,
    response_schema_sketch,
)
from .promotion import (
    evaluate_gate,
    promote_drafts,
    reevaluate_drafts,
    save_draft,
    status_report,
    update_draft_from_probe,
)

__all__ = [
    "CONTRACT_ROOT", "COVERAGE_PATH", "DRAFT_ROOT", "EVIDENCE_ROOT",
    "OPERATION_ROOT", "REPO_ROOT", "TMP_ROOT", "build_draft",
    "build_conservative_draft", "build_projection", "candidate_fields",
    "canonical_fingerprint", "classify_field", "create_bulk_drafts",
    "create_drafts", "create_write_registry", "evaluate_gate", "infer_identity",
    "promote_drafts", "reevaluate_drafts", "response_schema_sketch", "save_draft", "select_routes",
    "status_report", "update_draft_from_probe", "refresh_structured_blockers",
    "_display_path",
    "_existing_operations", "_read_json", "_route_family_id", "_write_json",
]
