"""Value-free diagnostics for rejected local SQL Evidence."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import date, datetime
from pathlib import Path
from typing import Any

from gravity_insight.sql.evidence_validation import validate_evidence_document
from gravity_insight.sql.time_window import EvidenceFormatError
from gravity_insight.support.evidence import EvidenceBinding, resolve_json_evidence


class EvidenceContractError(EvidenceFormatError):
    def __init__(self, message: str, diagnostic: dict[str, str | int]) -> None:
        super().__init__(message)
        self.diagnostic = diagnostic


def _type(value: Any) -> str:
    if value is _MISSING:
        return "missing"
    if value is None:
        return "null"
    if type(value) is bool:
        return "boolean"
    if type(value) is int:
        return "integer"
    if type(value) is float:
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, Mapping):
        return "object"
    if isinstance(value, list):
        return "array"
    return "unsupported"


_MISSING = object()


def _revision(evidence: Any) -> str:
    value = evidence.get("schema_version") if isinstance(evidence, Mapping) else None
    return str(value) if type(value) is int and value in (1, 2) else "unknown"


def _at(
    evidence: Any, path: str, configured_products: tuple[str, ...],
    selected_product: str | None = None,
) -> Any:
    value = evidence
    for part in path.removeprefix("evidence.").split("."):
        if part == "evidence":
            continue
        if part == "*":
            if not isinstance(value, Mapping):
                return _MISSING
            names = (selected_product,) if selected_product else configured_products
            value = next((value[name] for name in names if name in value), _MISSING)
        elif part == "[*]":
            value = value[0] if isinstance(value, list) and value else _MISSING
        elif isinstance(value, Mapping):
            value = value.get(part, _MISSING)
        else:
            return _MISSING
    return value


def _diagnostic(path: str, expected: str, observed: Any, revision: str, reason: str) -> dict[str, str]:
    return {
        "path": path,
        "expected_type": expected,
        "observed_type": _type(observed),
        "schema_version": revision,
        "reason": reason,
    }


def missing_current_evidence() -> dict[str, str]:
    return _diagnostic(
        "evidence.daily-verification.latest.yaml", "file", _MISSING,
        "unknown", "missing_current_snapshot",
    )


def invalid_snapshot() -> dict[str, str]:
    return {
        "path": "evidence.snapshot",
        "expected_type": "object",
        "observed_type": "unknown",
        "schema_version": "unknown",
        "reason": "snapshot_integrity_invalid",
    }


_MESSAGE_PATHS: tuple[tuple[str, str, str], ...] = (
    ("evidence root must be an object", "evidence", "object"),
    ("evidence datasource_id must be a string", "evidence.datasource_id", "string"),
    ("unsupported evidence schema or datasource", "evidence.schema_version", "integer"),
    ("invalid evidence verification_status", "evidence.verification_status", "string"),
    ("evidence contains an invalid date/time", "evidence.generated_at", "string"),
    ("evidence window is incomplete", "evidence.window", "object"),
    ("evidence timezone must be Asia/Shanghai", "evidence.window.timezone", "string"),
    ("evidence must describe one Beijing calendar day", "evidence.window", "object"),
    ("evidence must contain exactly the configured SQL products", "evidence.products", "object"),
    ("invalid product evidence:", "evidence.products.*", "object"),
    ("invalid product status:", "evidence.products.*.status", "string"),
    ("missing product summary:", "evidence.products.*.summary", "object"),
    ("product window differs", "evidence.products.*.window", "object"),
    ("invalid product app_ids:", "evidence.products.*.app_ids", "array"),
    ("invalid product warnings/claims:", "evidence.products.*.warnings", "array"),
    ("partial product must contain warnings:", "evidence.products.*.warnings", "array"),
    ("incomplete product completeness signal:", "evidence.products.*.completeness", "string"),
    ("invalid product completeness signal:", "evidence.products.*.completeness", "string"),
    ("invalid product row-cap signal:", "evidence.products.*.summary", "object"),
    ("evidence warnings differ", "evidence.warnings", "array"),
    ("evidence forbidden_claims differ", "evidence.forbidden_claims", "array"),
    ("evidence verification_status differs", "evidence.verification_status", "string"),
    ("evidence warnings and forbidden_claims", "evidence.warnings", "array"),
    ("verified_with_gaps evidence", "evidence.warnings", "array"),
    ("evidence hashes must be an object", "evidence.hashes", "object"),
    ("evidence contains invalid", "evidence.hashes", "object"),
    ("evidence content does not match", "evidence.hashes", "object"),
    ("verification history", "evidence.verification", "object"),
    ("verification mode", "evidence.verification.mode", "string"),
    ("verification segments", "evidence.verification.segments", "array"),
    ("verification segment", "evidence.verification.segments.[*]", "object"),
    ("complete verification", "evidence.verification", "object"),
    ("rate-limited segment", "evidence.verification.segments.[*]", "object"),
)


def _structural_type(evidence: Mapping[str, Any], names: tuple[str, ...], revision: str) -> dict[str, str] | None:
    expected_types = (
        ("schema_version", "integer"), ("datasource_id", "string"),
        ("generated_at", "string"), ("verified_for_date", "string"),
        ("window", "object"), ("verification_status", "string"),
        ("products", "object"), ("warnings", "array"),
        ("forbidden_claims", "array"), ("hashes", "object"),
    )
    for field, expected in expected_types:
        value = evidence.get(field, _MISSING)
        if _type(value) != expected:
            return _diagnostic(f"evidence.{field}", expected, value, revision, "invalid_type")
    return None


def _datetime_field(evidence: Mapping[str, Any], revision: str) -> dict[str, str] | None:
    for field, parser in (("verified_for_date", date.fromisoformat), ("generated_at", datetime.fromisoformat)):
        value = evidence.get(field, _MISSING)
        try:
            if not isinstance(value, str):
                raise ValueError
            parser(value)
        except ValueError:
            return _diagnostic(f"evidence.{field}", "string", value, revision, "invalid_datetime")
    return None


def _product_lists(evidence: Any, names: tuple[str, ...], selected: str | None, revision: str) -> dict[str, str] | None:
    for field in ("warnings", "forbidden_claims"):
        path = f"evidence.products.*.{field}"
        value = _at(evidence, path, names, selected)
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value) or (field == "forbidden_claims" and not value):
            return _diagnostic(path, "array", value, revision, "invalid_list")
    return None


def _product_set(evidence: Any, names: tuple[str, ...], revision: str) -> dict[str, str | int]:
    products = evidence.get("products") if isinstance(evidence, Mapping) else None
    diagnostic: dict[str, str | int] = _diagnostic(
        "evidence.products", "object", products if products is not None else _MISSING,
        revision, "configured_product_set_mismatch",
    )
    diagnostic["expected_count"] = len(names)
    if isinstance(products, Mapping):
        diagnostic["observed_count"] = len(products)
        diagnostic["matching_count"] = len(set(products) & set(names))
    return diagnostic


def _known_failure(
    evidence: Any, message: str, names: tuple[str, ...], selected: str | None, revision: str
) -> dict[str, str | int] | None:
    if message == "invalid structural type" and isinstance(evidence, Mapping):
        return _structural_type(evidence, names, revision)
    if message == "evidence contains an invalid date/time" and isinstance(evidence, Mapping):
        return _datetime_field(evidence, revision)
    if message.startswith("invalid product warnings/claims:"):
        return _product_lists(evidence, names, selected, revision)
    if message == "evidence must contain exactly the configured SQL products":
        return _product_set(evidence, names, revision)
    if message == "unsupported evidence schema or datasource" and isinstance(evidence, Mapping):
        version = evidence.get("schema_version", _MISSING)
        if type(version) is int and version in (1, 2):
            return _diagnostic("evidence.datasource_id", "string", evidence.get("datasource_id", _MISSING), revision, "identity_mismatch")
    if message.startswith("evidence contains invalid "):
        name = message.removeprefix("evidence contains invalid ")
        if name in {"sql_sha256", "result_sha256", "contract_sha256"}:
            path = f"evidence.hashes.{name}"
            return _diagnostic(path, "string", _at(evidence, path, names), revision, "invalid_hash")
    return None


def diagnose_evidence_failure(
    evidence: Any, error: EvidenceFormatError, configured_products: tuple[str, ...]
) -> dict[str, str | int]:
    """Interpret only reviewed validator messages; never serialize their text."""
    revision, message = _revision(evidence), str(error)
    selected = next(
        (name for name in configured_products if message.endswith(name) or f"product {name} " in message),
        None,
    )
    specific = _known_failure(evidence, message, configured_products, selected, revision)
    if specific is not None:
        return specific
    if message.startswith("evidence is missing fields:"):
        name = message.partition(":")[2].strip().split(",")[0].strip()
        expected_types = {
            "schema_version": "integer", "datasource_id": "string",
            "generated_at": "string", "verified_for_date": "string",
            "window": "object", "verification_status": "string",
            "verification": "object", "products": "object",
            "warnings": "array", "forbidden_claims": "array", "hashes": "object",
        }
        if name in expected_types:
            return _diagnostic(f"evidence.{name}", expected_types[name], _MISSING, revision, "missing_field")
    if message.startswith("evidence has unknown fields:"):
        return _diagnostic("evidence", "object", evidence, revision, "unknown_field")
    if message.startswith("product ") and "hashes" in message:
        path = "evidence.products.*.hashes"
        return _diagnostic(path, "object", _at(evidence, path, configured_products, selected), revision, "contract_mismatch")
    for prefix, path, expected in _MESSAGE_PATHS:
        if message.startswith(prefix):
            return _diagnostic(path, expected, _at(evidence, path, configured_products, selected), revision, "contract_mismatch")
    return _diagnostic("evidence", "object", evidence, revision, "contract_mismatch")


def validate_document_with_diagnostic(
    evidence: Any, *, configured_products: tuple[str, ...], datasource_id: str,
    hash_json: Callable[[Any], str],
) -> None:
    try:
        validate_evidence_document(
            evidence, configured_products=configured_products,
            datasource_id=datasource_id, hash_json=hash_json,
        )
    except EvidenceFormatError as exc:
        raise EvidenceContractError(
            str(exc), diagnose_evidence_failure(evidence, exc, configured_products)
        ) from exc
    except (TypeError, KeyError, OverflowError) as exc:
        raise EvidenceContractError(
            "SQL Evidence has an invalid structural type",
            diagnose_evidence_failure(
                evidence, EvidenceFormatError("invalid structural type"), configured_products
            ),
        ) from exc


def resolve_evidence_with_diagnostic(
    product_root: Path, *, validator: Callable[[Any], None],
) -> EvidenceBinding:
    if not (product_root / "latest.yaml").is_file():
        raise EvidenceContractError(
            "current immutable Evidence is missing", missing_current_evidence()
        )
    try:
        return resolve_json_evidence(product_root, result_validator=validator)
    except EvidenceContractError:
        raise
    except (ValueError, OSError) as exc:
        raise EvidenceContractError(
            f"cannot resolve immutable Evidence: {exc}", invalid_snapshot()
        ) from exc
