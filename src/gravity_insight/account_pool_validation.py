"""Admission checks for existing principal-scoped Capability Validation records."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from .errors import PolicyViolation


def require_sql_products(lease: Any, requests: Any) -> None:
    try:
        names = {request["product"] for request in requests}
    except (TypeError, KeyError):
        names = set()
    if not names or not names <= lease.sql_products:
        failure = unavailable()
        lease.reject(failure)
        raise failure


def validate_sql_capability(sdk: Any, store: Any, selector: str) -> str:
    from .capability_validation import parse_utc_timestamp
    from .sql.products import contract_hash

    name = selector.removeprefix("sql-product:")
    value = store.get("product", selector)
    if value is None:
        raise unavailable()
    product = sdk.workspace.product(name)
    fingerprint = contract_hash(name, sdk.workspace)
    current = datetime.now(timezone.utc)
    start, end = (parse_utc_timestamp(value[key]) for key in ("validated_at", "expires_at"))
    if not (
        value["contract_digest"] == value["provider_fingerprint"] == fingerprint
        and value["contract_version"] == str(product.get("contract_version", "1"))
        and start <= current < end and end - start <= timedelta(days=1)
        and value["trust_status"] == "stable" and value["completeness"] == "complete"
        and value["data_quality"]["status"] == "pass" and value["evidence_references"]
    ):
        raise unavailable()
    return name


def unavailable() -> PolicyViolation:
    return PolicyViolation(
        "ACCOUNT_CAPABILITY_UNAVAILABLE", code="ACCOUNT_CAPABILITY_UNAVAILABLE",
        next_action="Provide current same-scope Capability Validation for the requested read.",
    )
