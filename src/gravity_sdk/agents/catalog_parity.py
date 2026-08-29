"""Fail-closed parity checks for the derived Agent catalog."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


PRODUCT_SOURCES = frozenset({"composite", "product"})


def validate_catalog_parity(
    inventory: Sequence[Mapping[str, Any]],
    *,
    product_cards: Sequence[Mapping[str, Any]],
    operations: Sequence[Mapping[str, Any]],
    gaps: Sequence[Mapping[str, Any]],
) -> None:
    """Prove catalog identities and executable flags match their owners."""

    expected_products = _expected(product_cards, "selector", "product card")
    expected_operations = _expected(operations, "operation_id", "operation")
    expected_gaps = {
        f"gap:{code}": item
        for code, item in _expected(gaps, "code", "registered gap").items()
    }
    actual_products = _actual(inventory, PRODUCT_SOURCES)
    actual_operations = _actual(inventory, {"operation"})
    actual_gaps = _actual(inventory, {"gap"})
    selectors = [str(item.get("selector", "")) for item in inventory]
    if any(not selector for selector in selectors) or len(set(selectors)) != len(selectors):
        raise RuntimeError("catalog selectors must be globally unique")
    _same_identities("product card", expected_products, actual_products)
    _same_identities("registered gap", expected_gaps, actual_gaps)
    _same_executable("product card", expected_products, actual_products)
    _same_operation_contracts(expected_operations, inventory, actual_operations)
    if any(bool(item.get("executable")) for item in actual_gaps.values()):
        raise RuntimeError("registered catalog gaps must never be executable")
    if set(actual_products) & set(actual_gaps):
        raise RuntimeError("catalog identities cannot be both products and gaps")


def _expected(
    items: Sequence[Mapping[str, Any]], key: str, label: str
) -> dict[str, Mapping[str, Any]]:
    selected = {str(item.get(key, "")): item for item in items}
    if "" in selected or len(selected) != len(items):
        raise RuntimeError(f"canonical {label} identities must be unique")
    return selected


def _actual(
    inventory: Sequence[Mapping[str, Any]], sources: set[str] | frozenset[str]
) -> dict[str, Mapping[str, Any]]:
    selected = [item for item in inventory if item.get("source") in sources]
    result = {str(item.get("selector", "")): item for item in selected}
    if "" in result or len(result) != len(selected):
        raise RuntimeError("catalog selectors must be unique within each identity class")
    return result


def _same_identities(
    label: str,
    expected: Mapping[str, Mapping[str, Any]],
    actual: Mapping[str, Mapping[str, Any]],
) -> None:
    missing = sorted(set(expected) - set(actual))
    extra = sorted(set(actual) - set(expected))
    if missing or extra:
        raise RuntimeError(
            f"catalog {label} identity drift: missing={missing!r}, extra={extra!r}"
        )


def _same_executable(
    label: str,
    expected: Mapping[str, Mapping[str, Any]],
    actual: Mapping[str, Mapping[str, Any]],
) -> None:
    conflicts = sorted(
        selector
        for selector, item in expected.items()
        if bool(item.get("executable")) != bool(actual[selector].get("executable"))
    )
    if conflicts:
        raise RuntimeError(
            f"catalog {label} executable-status drift: {conflicts!r}"
        )


def _same_operation_contracts(
    expected: Mapping[str, Mapping[str, Any]],
    inventory: Sequence[Mapping[str, Any]],
    raw_operations: Mapping[str, Mapping[str, Any]],
) -> None:
    extra = sorted(set(raw_operations) - set(expected))
    indexed = {str(item["selector"]): item for item in inventory}
    missing = sorted(set(expected) - set(indexed))
    conflicts = sorted(
        selector
        for selector, item in expected.items()
        if selector in indexed
        and bool(item.get("executable")) != bool(indexed[selector].get("executable"))
    )
    if missing or extra:
        raise RuntimeError(
            f"catalog operation identity drift: missing={missing!r}, extra={extra!r}"
        )
    if conflicts:
        raise RuntimeError(
            f"catalog operation executable-status drift: {conflicts!r}"
        )


__all__ = ["PRODUCT_SOURCES", "validate_catalog_parity"]
