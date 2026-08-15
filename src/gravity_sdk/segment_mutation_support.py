"""Shared safety and evidence helpers for governed Segment mutations."""

from __future__ import annotations

import copy
import hashlib
import json
import re
import threading
from collections.abc import Mapping
from typing import Any, Callable

from .actionable_error_values import actual_value
from .errors import (
    ContractChangedError,
    GravityInsightError,
    InputValidationError,
    MutationReadbackError,
    ObjectAlreadyExistsError,
    PaginationError,
)
from .result_source import GOVERNED_PRODUCT, result_source
from .segment_mutation_contracts import DETAIL_OPERATION, LIST_OPERATION, SAVE


SCHEMA_VERSION = "gravity-insight.segment-mutation.v1"
MARKER_PREFIX = "GSDK-"
_LEGACY_MARKER_PREFIX = "gravity_sdk_v1_"
MARKER_PATTERN = re.compile(
    r"^(?:GSDK-[0-9a-f]{12}|gravity_sdk_v1_[0-9a-f]{16})(?:\s*\||$)"
)
MAX_NAME_LENGTH = 20
MAX_REMARK_LENGTH = 2_000
_SUCCESS = frozenset({"success", "empty", "contract_changed_additive"})
WRITE_LOCK = threading.Lock()


def segment_marker(
    create_kind: str,
    semantic_request: Mapping[str, Any],
    *,
    idempotency_key: str | None = None,
) -> str:
    """Return the deterministic, visible ownership marker for one create."""

    selected_kind = text(create_kind, "create_kind", 64)
    key = "" if idempotency_key is None else text(
        idempotency_key, "idempotency_key", 128
    )
    payload = json.dumps(
        {
            "create_kind": selected_kind,
            "idempotency_key": key,
            "request": semantic_request,
        },
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return MARKER_PREFIX + hashlib.sha256(payload).hexdigest()[:12]


def is_sdk_segment_remark(value: Any) -> bool:
    return isinstance(value, str) and MARKER_PATTERN.match(value) is not None


def execute_create(
    client: Any,
    *,
    operation_id: str,
    inputs: Mapping[str, Any],
    app_id: str,
    name: str,
    marker: str,
    preview: Mapping[str, Any],
    before_write: Callable[[], None] | None = None,
) -> dict[str, Any]:
    with WRITE_LOCK:
        existing = create_preflight(client, app_id, name, marker)
        if existing is not None:
            return idempotent(preview, existing)
        if before_write is not None:
            before_write()
        mutation = client._execute_mutation(operation_id, inputs)
        created = readback_created(client, app_id, name, marker)
        return completed(preview, mutation, created, status="created")


def run_analysis(
    client: Any, operation_id: str, inputs: Mapping[str, Any]
) -> None:
    result = client.read(operation_id, inputs)
    if (
        not isinstance(result, Mapping)
        or result.get("error") is not None
        or result.get("status") not in {"success", "contract_changed_additive"}
    ):
        raise InputValidationError(
            f"actual value: {actual_value({'ok': result.get('ok'), 'status': result.get('status')} if isinstance(result, Mapping) else {'type': type(result).__name__})}; allowed result: a successful selectable funnel response",
            field="spec",
            next_action="Correct the funnel or choose a non-empty period, then dry-run the segment create again.",
        )


def create_preflight(
    client: Any, app_id: str, name: str, marker: str
) -> Mapping[str, Any] | None:
    rows = segment_catalog(client, app_id)
    owned = [row for row in rows if marker_from_remark(row.get("segment_remark")) == marker]
    if len(owned) > 1:
        raise MutationReadbackError(
            "more than one segment has the same SDK idempotency marker",
            next_action="List the marker matches and remove only confirmed SDK-owned duplicates before retrying.",
        )
    if owned:
        if owned[0].get("segment_name") != name:
            raise ObjectAlreadyExistsError(
                "the idempotency marker already belongs to a differently named segment",
                field="name",
                next_action="Reuse the existing SDK-owned segment or choose a new idempotency key and unique name.",
            )
        return segment_detail(client, row_id(owned[0]))
    if any(row.get("segment_name") == name for row in rows):
        raise ObjectAlreadyExistsError(
            "a segment with the requested name already exists",
            field="name",
            next_action="Choose a unique segment name, or use the existing segment's exact ID without claiming SDK ownership.",
        )
    return None


def readback_created(
    client: Any, app_id: str, name: str, marker: str
) -> Mapping[str, Any]:
    rows = segment_catalog(client, app_id)
    matches = [row for row in rows if marker_from_remark(row.get("segment_remark")) == marker]
    if len(matches) != 1 or matches[0].get("segment_name") != name:
        raise MutationReadbackError(
            "created segment did not round-trip through the segment list",
            next_action="List segments for the App and inspect this SDK marker before deciding whether another create is safe.",
        )
    detail = segment_detail(client, row_id(matches[0]))
    if marker_from_remark(detail.get("segment_remark")) != marker:
        raise MutationReadbackError(
            "created segment marker did not round-trip through segment detail",
            next_action="Stop writes and inspect the exact segment detail before cleanup.",
        )
    return detail


def segment_catalog(client: Any, app_id: str) -> list[Mapping[str, Any]]:
    value = client.read_all(
        LIST_OPERATION,
        {"app_id": app_id, "page": 1, "page_size": 100},
        max_pages=1_000,
        max_items=100_000,
        max_workers=1,
    )
    if (
        not isinstance(value, Mapping)
        or value.get("error") is not None
        or value.get("status") not in _SUCCESS
    ):
        raise MutationReadbackError(
            "segment catalog could not be read before or after the mutation",
            next_action="Restore the segment list read, then inspect current state before issuing another write.",
        )
    if value.get("truncated") is True or value.get("next_page_input") not in (None, {}):
        raise PaginationError(
            "segment catalog is incomplete; mutation preflight failed closed",
            field="segment_catalog",
            next_action="Reduce the workspace segment count or raise the SDK safety bound before retrying; do not bypass the preflight.",
        )
    data = value.get("data")
    rows = data.get("list") if isinstance(data, Mapping) else None
    if not isinstance(rows, list) or any(not isinstance(row, Mapping) for row in rows):
        raise ContractChangedError(
            "segment catalog no longer returns data.list",
            next_action="Stop mutation automation until the segment list contract is re-verified.",
        )
    return rows


def segment_detail(client: Any, segment_id: str) -> Mapping[str, Any]:
    value = client.read(DETAIL_OPERATION, {"segment_id": segment_id})
    if (
        not isinstance(value, Mapping)
        or value.get("error") is not None
        or value.get("status") not in _SUCCESS
    ):
        raise MutationReadbackError(
            "segment detail could not be read for the mutation preimage/readback",
            next_action="Read the segment by exact ID and resolve the upstream error before issuing another write.",
        )
    data = value.get("data")
    if not isinstance(data, Mapping) or row_id(data) != segment_id:
        raise ContractChangedError(
            "segment detail identity changed",
            next_action="Stop mutation automation until the segment detail contract is re-verified.",
        )
    return data


def create_preview(
    preview: Mapping[str, Any], *, app_id: str, name: str, marker: str,
    impact: str, analysis_request: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    result = effect_preview(
        preview,
        target={"app_id": app_id, "name": name, "marker": marker},
        impact=impact,
        preconditions=[
            "Read the complete segment list for this App before writing.",
            "Return the existing object without writing when the same marker already exists.",
            "Fail with caller/2 when the name belongs to another object.",
            "Read the created object back through list and detail after the one-shot write.",
        ],
    )
    if analysis_request is not None:
        result["source_analysis"] = copy.deepcopy(dict(analysis_request))
    return result


def effect_preview(
    preview: Mapping[str, Any], *, target: Mapping[str, Any], impact: str,
    preconditions: list[str],
) -> dict[str, Any]:
    return {
        **copy.deepcopy(dict(preview)),
        "schema_version": SCHEMA_VERSION,
        "status": "preview",
        "result_source": result_source(GOVERNED_PRODUCT),
        "dry_run": True,
        "confirmation_required": True,
        "target": copy.deepcopy(dict(target)),
        "impact": impact,
        "preconditions": list(preconditions),
        "automatic_retry": False,
        "next_action": "Review this zero-network preview, then repeat the same request with execute=true or `--execute`.",
    }


def dependent_preview(
    operation_id: str, segment_id: str, *, action: str,
    target: Mapping[str, Any], impact: str,
) -> dict[str, Any]:
    update_rule = operation_id != SAVE
    return {
        "schema_version": SCHEMA_VERSION,
        "result_source": result_source(GOVERNED_PRODUCT),
        "ok": True,
        "status": "preview",
        "operation_id": operation_id,
        "effect": "mutation",
        "offline": True,
        "network_called": False,
        "dry_run": True,
        "confirmation_required": True,
        "target": copy.deepcopy(dict(target)),
        "impact": impact,
        "preconditions": [
            f"GET segment detail for exact ID {segment_id} at execution time.",
            "Use the upstream name and remark from that preimage; never trust caller-supplied ownership data.",
            "For DEL, refuse unless the readback remark starts with a valid Gravity SDK marker.",
        ],
        "request_template": {
            "method": "POST",
            "path": (
                "/report/api/v3/dataanalysis/segment/from_rule/update/"
                if update_rule
                else "/report/api/v3/dataanalysis/segment/save/"
            ),
            "body": {
                "segment_id": segment_id,
                "segment_name": "<resolved-from-preimage-or-validated-input>",
                "segment_remark": "<resolved-from-preimage-and-marker-policy>",
                "action": action,
            },
        },
        "automatic_retry": False,
        "attempts": 0,
        "next_action": "Review the preimage and request template, then repeat with execute=true or `--execute`.",
    }


def completed(
    preview: Mapping[str, Any], mutation: Mapping[str, Any],
    target: Mapping[str, Any], *, preimage: Mapping[str, Any] | None = None,
    status: str = "updated",
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "result_source": result_source(GOVERNED_PRODUCT),
        "ok": True,
        "status": status,
        "operation_id": mutation.get("operation_id"),
        "effect": "mutation",
        "offline": False,
        "network_called": True,
        "dry_run": False,
        "confirmation_required": False,
        "automatic_retry": False,
        "attempts": mutation.get("attempts", 1),
        "target": safe_target(target),
        "preimage": safe_target(preimage) if preimage is not None else None,
        "mutation": copy.deepcopy(dict(mutation)),
        "preview_fingerprint": digest(preview),
        "error": None,
    }


def idempotent(
    preview: Mapping[str, Any], existing: Mapping[str, Any]
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "result_source": result_source(GOVERNED_PRODUCT),
        "ok": True,
        "status": "already_exists",
        "operation_id": preview.get("operation_id"),
        "effect": "mutation",
        "offline": False,
        "network_called": True,
        "write_sent": False,
        "attempts": 0,
        "idempotent_reuse": True,
        "target": safe_target(existing),
        "error": None,
    }


def safe_target(value: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if value is None:
        return None
    return {
        key: copy.deepcopy(value[key])
        for key in (
            "id", "segment_id", "app_id", "segment_name", "segment_remark",
            "analysis_scene", "update_type", "operation_status", "deleted", "marker",
        )
        if key in value
    }


def marked_remark(marker: str, remark: Any) -> str:
    if not re.fullmatch(
        r"(?:GSDK-[0-9a-f]{12}|gravity_sdk_v1_[0-9a-f]{16})", marker
    ):
        raise InputValidationError(
            f"actual value: {actual_value(marker)}; allowed value: compact GSDK marker or its legacy long form",
            field="marker",
        )
    note = caller_remark(remark)
    if not note:
        return marker
    room = MAX_REMARK_LENGTH - len(marker) - 3
    return f"{marker} | {note[:room]}"


def caller_remark(value: Any) -> str:
    if not isinstance(value, str):
        raise InputValidationError(
            f"actual value: {actual_value({'type': type(value).__name__})}; allowed value: a string remark",
            field="remark",
        )
    if MARKER_PREFIX in value or _LEGACY_MARKER_PREFIX in value:
        raise InputValidationError(
            f"actual value: {actual_value({'contains_sdk_marker': True, 'length': len(value)})}; allowed value: caller text without an SDK ownership marker",
            field="remark",
            next_action="Remove the marker-like text; the SDK adds its own marker only when it creates an object.",
        )
    return value[:MAX_REMARK_LENGTH]


def marker_from_remark(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    match = MARKER_PATTERN.match(value)
    return value.split("|", 1)[0].strip() if match is not None else None


def fixed_date(date_list: Any) -> dict[str, list[int]]:
    if (
        not isinstance(date_list, list)
        or len(date_list) != 1
        or not isinstance(date_list[0], Mapping)
    ):
        raise InputValidationError(
            f"actual value: {actual_value({'type': type(date_list).__name__, 'length': len(date_list) if isinstance(date_list, list) else None})}; allowed value: exactly one funnel date range",
            field="spec",
        )
    selected = date_list[0]
    return {
        "fixed_date": [
            int(str(selected["start_date"]).replace("-", "")),
            int(str(selected["end_date"]).replace("-", "")),
        ]
    }


def same_app(detail: Mapping[str, Any], app_id: str) -> None:
    if detail.get("app_id") is not None and str(detail["app_id"]) != app_id:
        raise InputValidationError(
            f"actual value: {actual_value(app_id)}; allowed value: segment App {actual_value(detail.get('app_id'))}",
            field="app",
            next_action="Use the App returned by segment detail and dry-run the update again.",
        )


def row_id(row: Mapping[str, Any]) -> str:
    return identifier(row.get("segment_id", row.get("id")), "segment_id")


def identifier(value: Any, field: str) -> str:
    selected = (
        str(value).strip()
        if isinstance(value, (str, int)) and not isinstance(value, bool)
        else ""
    )
    if (
        not selected
        or len(selected) > 64
        or not selected.isascii()
        or not selected.isdecimal()
        or int(selected) < 1
    ):
        raise InputValidationError(
            f"actual value: {actual_value(value)}; allowed value: a positive decimal identifier of at most 64 characters",
            field=field,
        )
    return selected


def name(value: Any) -> str:
    return text(value, "name", MAX_NAME_LENGTH)


def text(value: Any, field: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise InputValidationError(
            f"actual value: {actual_value(value)}; allowed range: 1 through {maximum} characters",
            field=field,
            next_action=f"Use a non-empty {field} of at most {maximum} characters, then run the dry-run again.",
        )
    return value


def step(value: Any) -> int:
    if type(value) is not int or value < 0 or value > 19:
        raise InputValidationError(
            f"actual value: {actual_value(value)}; allowed range: integer from 0 through 19",
            field="step",
        )
    return value


def digest(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
