"""Fixed R12-A connector delegating to the governed Segment update owner."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from .action_connector_support import (
    WriteTrackingClient,
    attempted_receipts,
    current_principal,
    deduplicate_receipts,
)
from .errors import InputValidationError
from .mutation_lifecycle import mutation_digest
from .result_audit import result_receipt_references
from .segment_mutation import update_segment_metadata
from .segment_mutation_contracts import DETAIL_OPERATION, SAVE
from .segment_mutation_support import (
    caller_remark,
    identifier,
    name,
    require_segment_authority,
    segment_detail,
    segment_preimage_digest,
    marker_from_remark,
)


ACTION_KIND = "segment.update_metadata"
CONNECTOR_ID = "gravity.segment-metadata-update"
CONNECTOR_VERSION = 1
REQUEST_SCHEMA_VERSION = "gravity.segment-metadata-update-request.v1"
MANAGED_FIELDS = ("segment_name", "segment_remark")
_REQUEST_FIELDS = frozenset({"schema_version", "segment_id", "name", "remark"})


def prepare_segment_update(
    client: Any, request: Mapping[str, Any]
) -> dict[str, Any]:
    """Resolve the current exact preimage without sending a mutation."""

    normalized = normalize_request(client, request)
    preimage = segment_detail(client, normalized["segment_id"])
    ownership = require_segment_authority(client, preimage)
    principal = current_principal(client)
    return {
        "normalized": normalized,
        "principal_digest": mutation_digest({"principal_id": principal}),
        "target_digest": mutation_digest(
            {"segment_id": normalized["segment_id"]}
        ),
        "preimage_digest": segment_preimage_digest(preimage),
        "ownership_digest": mutation_digest(ownership.public()),
        "ownership_basis": ownership.basis,
        "contract_fingerprint": connector_contract_fingerprint(client),
    }


def current_execution_binding(
    client: Any, request: Mapping[str, Any]
) -> dict[str, Any]:
    normalized = normalize_request(client, request)
    principal = current_principal(client)
    return {
        "normalized": normalized,
        "principal_digest": mutation_digest({"principal_id": principal}),
        "target_digest": mutation_digest(
            {"segment_id": normalized["segment_id"]}
        ),
        "contract_fingerprint": connector_contract_fingerprint(client),
    }


def execute_segment_update(
    client: Any,
    normalized: Mapping[str, Any],
    *,
    expected_preimage_digest: str,
) -> dict[str, Any]:
    """Call the existing owner once and report whether a write was attempted."""

    tracking = WriteTrackingClient(client)
    try:
        result = update_segment_metadata(
            tracking,
            normalized["segment_id"],
            name=normalized["name"],
            remark=normalized["remark"],
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
    if not isinstance(target, Mapping):
        return None
    ownership = target.get("ownership")
    actual_remark = str(target.get("segment_remark", ""))
    marker = marker_from_remark(actual_remark)
    remark_matches = (
        actual_remark == normalized["remark"]
        if marker is None
        else not normalized["remark"]
        or actual_remark.endswith(f"| {normalized['remark']}")
    )
    if (
        target.get("segment_id") != normalized["segment_id"]
        or target.get("segment_name") != normalized["name"]
        or not remark_matches
        or not isinstance(ownership, Mapping)
        or ownership.get("basis") not in {"sdk_source_marker", "upstream_owner"}
    ):
        return None
    references = result_receipt_references(result)
    references.extend(result_receipt_references(result.get("mutation")))
    return {
        "target": {
            "kind": "segment",
            "segment_id": normalized["segment_id"],
        },
        "assertions": [
            {"id": "segment_name", "status": "verified"},
            {"id": "segment_remark", "status": "verified"},
            {"id": "field_ownership", "status": "verified"},
        ],
        "receipt_references": deduplicate_receipts(references),
    }


def normalize_request(
    client: Any, request: Mapping[str, Any]
) -> dict[str, str]:
    if not isinstance(request, Mapping) or set(request) - _REQUEST_FIELDS:
        _invalid("request must use only the declared Segment update fields", "request")
    if request.get("schema_version") != REQUEST_SCHEMA_VERSION:
        _invalid(
            f"request schema_version must be {REQUEST_SCHEMA_VERSION}",
            "request.schema_version",
        )
    if isinstance(request.get("remark", ""), str) and len(request.get("remark", "")) > 2_000:
        _invalid("remark must contain at most 2000 characters", "request.remark")
    selected = {
        "segment_id": identifier(request.get("segment_id"), "segment_id"),
        "name": name(request.get("name")),
        "remark": caller_remark(request.get("remark", "")),
    }
    update_segment_metadata(
        client,
        selected["segment_id"],
        name=selected["name"],
        remark=selected["remark"],
        execute=False,
    )
    return selected


def connector_contract_fingerprint(client: Any) -> str:
    contracts = []
    for operation_id in (DETAIL_OPERATION, SAVE):
        value = client.describe(operation_id)
        if not isinstance(value, Mapping):
            _invalid("connector operation contract must be available", "connector")
        contracts.append(
            {"operation_id": operation_id, "contract": copy.deepcopy(dict(value))}
        )
    return mutation_digest({"contracts": contracts})


def _invalid(message: str, field: str) -> None:
    raise InputValidationError(
        f"actual value: invalid Action request shape; allowed value: {message}",
        field=field,
        code="ACTION_REQUEST_INVALID",
        next_action="Correct the exact Segment metadata update request and preview a new Action Plan.",
    )


__all__ = [
    "ACTION_KIND",
    "CONNECTOR_ID",
    "CONNECTOR_VERSION",
    "MANAGED_FIELDS",
    "REQUEST_SCHEMA_VERSION",
    "current_execution_binding",
    "execute_segment_update",
    "normalize_request",
    "prepare_segment_update",
    "attempted_receipts",
    "verified_readback",
]
