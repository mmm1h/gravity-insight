"""Shared safety primitives for the closed Action connector set."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .errors import InputValidationError
from .result_audit import error_receipt_references, result_receipt_references


def current_principal(client: Any) -> str:
    try:
        value = client._current_principal_id()
    except Exception:
        value = None
    if (
        not isinstance(value, (str, int))
        or isinstance(value, bool)
        or not str(value).strip()
    ):
        raise InputValidationError(
            "actual value: current Gravity principal is unavailable; allowed value: one authenticated principal bound by GravitySDK.from_env()",
            field="principal",
            code="ACTION_IDENTITY_UNAVAILABLE",
            next_action="Refresh authentication, construct a new scoped SDK, and preview a new Action Plan.",
        )
    return str(value).strip()


def deduplicate_receipts(
    values: list[Mapping[str, Any]],
) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for value in values:
        receipt_id = str(value.get("receipt_id", ""))
        if receipt_id in seen:
            continue
        seen.add(receipt_id)
        result.append(
            {
                "receipt_id": receipt_id,
                "storage_status": str(value.get("storage_status", "")),
            }
        )
    return result


def attempted_receipts(attempted: Mapping[str, Any]) -> list[dict[str, str]]:
    error = attempted.get("error")
    result = attempted.get("result")
    references = (
        error_receipt_references(error) if isinstance(error, BaseException) else []
    )
    if isinstance(result, Mapping):
        references.extend(result_receipt_references(result))
        references.extend(result_receipt_references(result.get("mutation")))
    return deduplicate_receipts(references)


class WriteTrackingClient:
    """Delegate every client operation while allowing at most one mutation."""

    def __init__(self, client: Any) -> None:
        self._client = client
        self.write_attempts = 0

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)

    def _execute_mutation(
        self, operation_id: str, inputs: Mapping[str, Any]
    ) -> Any:
        self.write_attempts += 1
        if self.write_attempts > 1:
            raise RuntimeError("Action connector attempted more than one mutation")
        return self._client._execute_mutation(operation_id, inputs)


__all__ = [
    "WriteTrackingClient",
    "attempted_receipts",
    "current_principal",
    "deduplicate_receipts",
]
