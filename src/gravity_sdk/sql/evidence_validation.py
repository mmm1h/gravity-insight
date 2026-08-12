"""Fail-closed validation for governed SQL Evidence documents."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime
from typing import Any

from gravity_sdk.sql.time_window import day_window, normalize_window


_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_REQUIRED_FIELDS = frozenset(
    {
        "schema_version",
        "datasource_id",
        "generated_at",
        "verified_for_date",
        "window",
        "verification_status",
        "products",
        "warnings",
        "forbidden_claims",
        "hashes",
    }
)


class EvidenceFormatError(ValueError):
    pass


def validate_evidence_document(
    evidence: Any,
    *,
    configured_products: tuple[str, ...],
    datasource_id: str,
    hash_json: Callable[[Any], str],
) -> None:
    root = _root(evidence)
    _validate_identity(root, datasource_id)
    window = _validate_window(root)
    products = _product_map(root, configured_products)
    _validate_products(products, configured_products, window)
    _validate_aggregate(root, products, configured_products, hash_json)


def _root(evidence: Any) -> dict[str, Any]:
    if not isinstance(evidence, dict):
        raise EvidenceFormatError("evidence root must be an object")
    missing = sorted(_REQUIRED_FIELDS - set(evidence))
    if missing:
        raise EvidenceFormatError(f"evidence is missing fields: {', '.join(missing)}")
    unknown = sorted(set(evidence) - _REQUIRED_FIELDS)
    if unknown:
        raise EvidenceFormatError(f"evidence has unknown fields: {', '.join(unknown)}")
    if not isinstance(evidence["datasource_id"], str):
        raise EvidenceFormatError("evidence datasource_id must be a string")
    return evidence


def _validate_identity(evidence: Mapping[str, Any], datasource_id: str) -> None:
    schema_version = evidence["schema_version"]
    if (
        type(schema_version) is not int
        or schema_version != 1
        or evidence["datasource_id"] != datasource_id
    ):
        raise EvidenceFormatError("unsupported evidence schema or datasource")
    if evidence["verification_status"] not in {"verified", "verified_with_gaps"}:
        raise EvidenceFormatError("invalid evidence verification_status")
    try:
        date.fromisoformat(str(evidence["verified_for_date"]))
        datetime.fromisoformat(str(evidence["generated_at"]))
    except ValueError as exc:
        raise EvidenceFormatError("evidence contains an invalid date/time") from exc


def _validate_window(evidence: Mapping[str, Any]) -> Mapping[str, Any]:
    window = evidence["window"]
    if not isinstance(window, Mapping) or {"start", "end", "timezone"} - set(window):
        raise EvidenceFormatError("evidence window is incomplete")
    if window["timezone"] != "Asia/Shanghai":
        raise EvidenceFormatError("evidence timezone must be Asia/Shanghai")
    try:
        start_at, end_at = normalize_window(str(window["start"]), str(window["end"]))
    except ValueError as exc:
        raise EvidenceFormatError(str(exc)) from exc
    expected = day_window(date.fromisoformat(str(evidence["verified_for_date"])))
    if (start_at, end_at) != expected:
        raise EvidenceFormatError("evidence must describe one Beijing calendar day")
    return window


def _product_map(
    evidence: Mapping[str, Any], configured: tuple[str, ...]
) -> Mapping[str, Any]:
    products = evidence["products"]
    if not isinstance(products, Mapping) or set(products) != set(configured):
        raise EvidenceFormatError("evidence must contain exactly the configured SQL products")
    return products


def _validate_products(
    products: Mapping[str, Any],
    configured: tuple[str, ...],
    window: Mapping[str, Any],
) -> None:
    for product in configured:
        _validate_product(product, products[product], window)


def _validate_product(
    product: str, result: Any, window: Mapping[str, Any]
) -> None:
    if not isinstance(result, Mapping) or result.get("product") != product:
        raise EvidenceFormatError(f"invalid product evidence: {product}")
    if result.get("status") not in {"complete", "partial"}:
        raise EvidenceFormatError(f"invalid product status: {product}")
    if not isinstance(result.get("summary"), Mapping):
        raise EvidenceFormatError(f"missing product summary: {product}")
    _validate_claims(product, result)
    if result.get("window") != window:
        raise EvidenceFormatError(f"product window differs from evidence window: {product}")
    _validate_app_ids(product, result.get("app_ids"))
    _validate_hashes(result.get("hashes"), f"product {product}")


def _validate_claims(product: str, result: Mapping[str, Any]) -> None:
    warnings = result.get("warnings")
    claims = result.get("forbidden_claims")
    if not _string_list(warnings) or not _nonempty_string_list(claims):
        raise EvidenceFormatError(f"invalid product warnings/claims: {product}")
    if result["status"] == "partial" and not warnings:
        raise EvidenceFormatError(f"partial product must contain warnings: {product}")


def _validate_app_ids(product: str, value: Any) -> None:
    if (
        not isinstance(value, list)
        or not value
        or any(type(app_id) is not int or app_id <= 0 for app_id in value)
    ):
        raise EvidenceFormatError(f"invalid product app_ids: {product}")


def _validate_aggregate(
    evidence: Mapping[str, Any],
    products: Mapping[str, Any],
    configured: tuple[str, ...],
    hash_json: Callable[[Any], str],
) -> None:
    warnings = _expected_warnings(products, configured)
    claims = _expected_claims(products, configured)
    expected_status = "verified_with_gaps" if warnings else "verified"
    if evidence["warnings"] != warnings:
        raise EvidenceFormatError("evidence warnings differ from product warnings")
    if evidence["forbidden_claims"] != claims:
        raise EvidenceFormatError("evidence forbidden_claims differ from product claims")
    if evidence["verification_status"] != expected_status:
        raise EvidenceFormatError("evidence verification_status differs from product statuses")
    _validate_aggregate_lists(evidence)
    _validate_hashes(evidence["hashes"], "evidence")
    if evidence["hashes"] != _evidence_hashes(products, configured, hash_json):
        raise EvidenceFormatError("evidence content does not match its top-level hashes")


def _validate_aggregate_lists(evidence: Mapping[str, Any]) -> None:
    if not _string_list(evidence["warnings"]):
        raise EvidenceFormatError("evidence warnings and forbidden_claims must be lists")
    if not _nonempty_string_list(evidence["forbidden_claims"]):
        raise EvidenceFormatError("evidence warnings and forbidden_claims must be lists")
    if evidence["verification_status"] == "verified_with_gaps" and not evidence["warnings"]:
        raise EvidenceFormatError("verified_with_gaps evidence must contain warnings")


def _string_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _nonempty_string_list(value: Any) -> bool:
    return bool(value) and _string_list(value)


def _expected_warnings(
    products: Mapping[str, Any], configured: Sequence[str]
) -> list[str]:
    return [
        f"{product}: {warning}"
        for product in configured
        for warning in products[product]["warnings"]
    ]


def _expected_claims(
    products: Mapping[str, Any], configured: Sequence[str]
) -> list[str]:
    return list(
        dict.fromkeys(
            claim
            for product in configured
            for claim in products[product]["forbidden_claims"]
        )
    )


def _validate_hashes(value: Any, label: str) -> None:
    if not isinstance(value, Mapping):
        raise EvidenceFormatError(f"{label} hashes must be an object")
    for name in ("sql_sha256", "result_sha256", "contract_sha256"):
        if not _HASH_RE.fullmatch(str(value.get(name, ""))):
            raise EvidenceFormatError(f"{label} contains invalid {name}")


def _evidence_hashes(
    products: Mapping[str, Any],
    configured: Sequence[str],
    hash_json: Callable[[Any], str],
) -> dict[str, str]:
    return {
        "sql_sha256": hash_json(
            {product: products[product]["hashes"]["sql_sha256"] for product in configured}
        ),
        "result_sha256": hash_json(products),
        "contract_sha256": hash_json(
            {
                product: products[product]["hashes"]["contract_sha256"]
                for product in configured
            }
        ),
    }


__all__ = ["EvidenceFormatError", "validate_evidence_document"]
