"""Opaque links from execution envelopes to durable HTTP receipts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .response_drift import merge_response_drifts, normalize_response_drift


SCHEMA_VERSION = "gravity.result-audit.v1"
STORED = "stored"
WRITE_FAILED = "write_failed"
_STORAGE_STATUSES = frozenset({STORED, WRITE_FAILED})
_FACT_POINTERS = {
    "operation_id": frozenset({"/operation_id", "/result/operation_id"}),
    "contract_version": frozenset({"/contract_version", "/result/contract_version"}),
    "evidence_reference": frozenset({"/evidence_reference", "/result/evidence_reference"}),
    "call_bound": frozenset({"/call_bound", "/result/call_bound"}),
}
_FACT_FIELDS = {name: sorted(pointers)[0] for name, pointers in _FACT_POINTERS.items()}


def receipt_reference(receipt_id: object, storage_status: str) -> dict[str, str]:
    """Build one value-free reference without exposing storage coordinates."""

    normalized_id = str(receipt_id)
    if not _receipt_id(normalized_id):
        raise ValueError("HTTP receipt reference has an invalid receipt_id")
    if storage_status not in _STORAGE_STATUSES:
        raise ValueError("HTTP receipt reference has an invalid storage_status")
    return {"receipt_id": normalized_id, "storage_status": storage_status}


def add_result_audit(
    value: Mapping[str, Any],
    references: Sequence[Mapping[str, Any]],
    *,
    fact_paths: Mapping[str, str] | None = None,
    response_drift: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Add or merge the independent audit sub-contract without copying facts."""

    selected = dict(value)
    normalized = _references(references)
    current = selected.get("result_audit")
    existing_references: list[dict[str, str]] = []
    existing_paths: dict[str, str] = {}
    existing_drift: dict[str, Any] | None = None
    if current is not None:
        if not isinstance(current, Mapping) or current.get("schema_version") != SCHEMA_VERSION:
            raise ValueError("result envelope has an incompatible result_audit")
        existing_references = _references(current.get("http_receipts", ()))
        existing_paths = _paths(current.get("fact_paths", {}))
        if current.get("response_drift") is not None:
            existing_drift = normalize_response_drift(current["response_drift"])
    paths = {
        **existing_paths,
        **(_paths(fact_paths) if fact_paths is not None else infer_fact_paths(selected)),
    }
    receipts = _deduplicate([*existing_references, *normalized])
    drift = merge_response_drifts((existing_drift, response_drift))
    if not paths and not receipts and drift is None:
        return selected
    selected["result_audit"] = {
        "schema_version": SCHEMA_VERSION,
        "fact_paths": paths,
        "http_receipts": receipts,
        **({"response_drift": drift} if drift is not None else {}),
    }
    return selected


def infer_fact_paths(value: Mapping[str, Any]) -> dict[str, str]:
    """Point at existing stable facts; their values deliberately stay in place."""

    return {
        name: pointer
        for name, pointer in _FACT_FIELDS.items()
        if name in value
    }


def error_receipt_references(error: BaseException) -> list[dict[str, str]]:
    raw = getattr(error, "http_receipt_references", ())
    try:
        return _references(raw)
    except ValueError:
        return []


def result_receipt_references(value: object) -> list[dict[str, str]]:
    if not isinstance(value, Mapping):
        return []
    audit = value.get("result_audit")
    if not isinstance(audit, Mapping) or audit.get("schema_version") != SCHEMA_VERSION:
        return []
    try:
        return _references(audit.get("http_receipts", ()))
    except ValueError:
        return []


def result_response_drift(value: object) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    audit = value.get("result_audit")
    if not isinstance(audit, Mapping) or audit.get("schema_version") != SCHEMA_VERSION:
        return None
    drift = audit.get("response_drift")
    if drift is None:
        return None
    try:
        return normalize_response_drift(drift)
    except ValueError:
        return None


def project_result_audit(
    target: Mapping[str, Any], source: object
) -> dict[str, Any]:
    """Carry only receipt references through a safe result reconstruction."""

    references = (
        error_receipt_references(source)
        if isinstance(source, BaseException)
        else result_receipt_references(source)
    )
    if isinstance(source, Mapping):
        references.extend(result_receipt_references(source.get("data")))
        references.extend(result_receipt_references(source.get("result")))
    drifts = [result_response_drift(source)]
    if isinstance(source, Mapping):
        drifts.extend(
            (
                result_response_drift(source.get("data")),
                result_response_drift(source.get("result")),
            )
        )
    return add_result_audit(
        target,
        references,
        response_drift=merge_response_drifts(drifts),
    )


def aggregate_result_audit(
    target: Mapping[str, Any], sources: Sequence[object]
) -> dict[str, Any]:
    """Aggregate opaque references while inferring facts only from the target."""

    selected = dict(target)
    for source in sources:
        selected = project_result_audit(selected, source)
    return selected


def bind_error_receipts(
    error: BaseException, references: Sequence[Mapping[str, Any]]
) -> None:
    """Carry completed-response facts across a later local processing error."""

    normalized = _references(references)
    if not normalized:
        return
    current = error_receipt_references(error)
    try:
        setattr(error, "http_receipt_references", tuple(_deduplicate([*current, *normalized])))
    except Exception:
        pass


def _references(value: object) -> list[dict[str, str]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ValueError("http_receipts must be an array")
    result: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, Mapping) or set(item) != {"receipt_id", "storage_status"}:
            raise ValueError("HTTP receipt reference has unsupported fields")
        result.append(receipt_reference(item["receipt_id"], str(item["storage_status"])))
    return _deduplicate(result)


def _paths(value: object) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise ValueError("result audit fact_paths must be an object")
    result: dict[str, str] = {}
    for name, pointer in value.items():
        if name not in _FACT_POINTERS or pointer not in _FACT_POINTERS[name]:
            raise ValueError("result audit fact_paths contains an unsupported pointer")
        result[str(name)] = str(pointer)
    return result


def _deduplicate(values: Sequence[Mapping[str, str]]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for value in values:
        receipt_id = value["receipt_id"]
        if receipt_id in seen:
            continue
        seen.add(receipt_id)
        result.append(dict(value))
    return result


def _receipt_id(value: str) -> bool:
    return len(value) == 32 and all(character in "0123456789abcdef" for character in value)


__all__ = [
    "SCHEMA_VERSION",
    "STORED",
    "WRITE_FAILED",
    "add_result_audit",
    "bind_error_receipts",
    "error_receipt_references",
    "infer_fact_paths",
    "aggregate_result_audit",
    "project_result_audit",
    "receipt_reference",
    "result_receipt_references",
    "result_response_drift",
]
