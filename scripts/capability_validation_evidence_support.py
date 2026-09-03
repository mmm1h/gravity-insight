"""Value-free qualification helpers for production Capability evidence."""

from __future__ import annotations

import re
import threading
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from gravity_insight.capability_contract import _operations, capability_contracts
from gravity_insight.capability_trust import CapabilityTrustService
from gravity_insight.capability_validation import CapabilityValidationStore, SCHEMA_VERSION
from gravity_insight.data_quality import data_quality_result
from gravity_insight.errors import GravityInsightError
from gravity_insight.receipt_query import get_http_receipt
from gravity_insight.result_audit import result_response_drift
from gravity_insight.read_result_support import result_warnings
from gravity_insight.semantic_status import response_data_nonempty


RUN_SCHEMA_VERSION = "gravity.capability-validation-run.v1"
MAX_PRODUCTION_REQUESTS = 500
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_SUCCESS_HTTP = range(200, 300)
_APP_PLACEHOLDERS = frozenset({"$first_app_id", "$parent:app_id"})


class RequestBudgetExceeded(RuntimeError):
    """Raised before a request would exceed the explicit upstream budget."""


class BudgetedSession:
    """Delegate to one requests Session while enforcing an exact send cap."""

    def __init__(self, session: Any, limit: int) -> None:
        if type(limit) is not int or limit < 0:
            raise ValueError("request budget must be a non-negative integer")
        self._session = session
        self.limit = limit
        self.sent = 0
        self._lock = threading.Lock()

    def request(self, *args: Any, **kwargs: Any) -> Any:
        with self._lock:
            if self.sent >= self.limit:
                raise RequestBudgetExceeded(
                    "Capability evidence request budget is exhausted"
                )
            self.sent += 1
        return self._session.request(*args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._session, name)


def inventory() -> dict[str, Any]:
    contracts = capability_contracts()
    operations = _operations()
    counts = Counter()
    entries: list[dict[str, Any]] = []
    for artifact in contracts:
        contract = artifact["contract"]
        kind = str(contract["identity_kind"])
        selector = str(contract["selector"])
        if kind != "operation":
            category = "execution_path_unproven"
        elif contract["effect"] != "read":
            category = "requires_production_write"
        elif not operations[selector].live_probe.enabled:
            category = "live_probe_unavailable"
        else:
            category = "read_probe_candidate"
        counts[category] += 1
        entries.append(
            {
                "identity_kind": kind,
                "selector": selector,
                "effect": contract["effect"],
                "category": category,
            }
        )
    return {
        "capabilities": len(contracts),
        "counts": dict(sorted(counts.items())),
        "entries": entries,
        "network_called": False,
    }


def bind_probe_app(value: Any, app_id: str) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): bind_probe_app(item, app_id)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [bind_probe_app(item, app_id) for item in value]
    return app_id if value in _APP_PLACEHOLDERS else value


def validation_from_execution(
    artifact: Mapping[str, Any],
    result: Mapping[str, Any],
    receipts: Sequence[Mapping[str, Any]],
    *,
    started_at: datetime,
    observed_at: datetime,
) -> tuple[dict[str, Any] | None, list[str]]:
    contract = artifact["contract"]
    selector = str(contract["selector"])
    exact = [
        item
        for item in receipts
        if item.get("operation_id") == selector
        and item.get("http_status") in _SUCCESS_HTTP
        and _receipt_is_current(item, started_at, observed_at)
    ]
    reasons = _qualification_reasons(
        contract, selector, result, exact, started_at, observed_at
    )
    if reasons:
        return None, reasons
    validated_at = observed_at.astimezone(timezone.utc).replace(microsecond=0)
    expires_at = validated_at + timedelta(
        seconds=int(contract["validation_ttl_seconds"])
    )
    checks = [
        {"check_id": name, "status": "pass", "scope": selector}
        for name in (
            "execution.receipt", "execution.semantic-status", "response.nonempty",
            "response.schema-and-type", "response.freshness", "response.no-drift",
        )
    ]
    validation = {
        "schema_version": SCHEMA_VERSION,
        "identity_kind": contract["identity_kind"],
        "selector": selector,
        "contract_version": contract["contract_version"],
        "contract_digest": artifact["digest"],
        "provider_fingerprint": contract["provider"]["fingerprint"],
        "validated_at": timestamp(validated_at),
        "expires_at": timestamp(expires_at),
        "trust_status": "stable",
        "completeness": contract["declared_completeness"],
        "data_quality": data_quality_result(checks),
        "evidence_references": [
            {"kind": "receipt", "reference": f"receipt:{item['receipt_id']}"}
            for item in exact
        ],
        "reason_codes": [],
    }
    return validation, []


def _qualification_reasons(
    contract: Mapping[str, Any], selector: str, result: Mapping[str, Any],
    exact: Sequence[Mapping[str, Any]], started_at: datetime, observed_at: datetime,
) -> list[str]:
    reasons: list[str] = []
    if not exact:
        reasons.append("EXECUTION_RECEIPT_MISSING")
    if result.get("ok") is not True or result.get("status") != "success":
        reasons.append(_result_status_reason(result))
    if result.get("error") not in (None, {}):
        reasons.append("EXECUTION_ERROR_PRESENT")
    if result.get("operation_id") != selector:
        reasons.append("EXECUTION_IDENTITY_MISMATCH")
    if result.get("contract_version") != contract["contract_version"]:
        reasons.append("EXECUTION_CONTRACT_MISMATCH")
    source = result.get("source")
    fingerprint = source.get("contract_fingerprint") if isinstance(source, Mapping) else None
    if fingerprint != contract["provider"]["fingerprint"]:
        reasons.append("EXECUTION_PROVIDER_MISMATCH")
    schema = result.get("schema_fingerprint")
    if not isinstance(schema, str) or _DIGEST.fullmatch(schema) is None:
        reasons.append("EXECUTION_SCHEMA_UNPROVEN")
    if not response_data_nonempty({"data": result.get("data")}):
        reasons.append("EXECUTION_DATA_EMPTY")
    operation = _operations()[selector]
    expected_warnings = list(result_warnings(operation, ()))
    if list(result.get("warnings") or ()) != expected_warnings:
        reasons.append("EXECUTION_WARNINGS_PRESENT")
    if result_response_drift(result) is not None:
        reasons.append("EXECUTION_RESPONSE_DRIFT")
    if not _result_is_current(result, started_at, observed_at):
        reasons.append("EXECUTION_FRESHNESS_UNPROVEN")
    return list(dict.fromkeys(reasons))


def static_outcomes(
    artifacts: Mapping[tuple[str, str], Mapping[str, Any]],
) -> dict[tuple[str, str], dict[str, Any]]:
    outcomes = {}
    for key, artifact in artifacts.items():
        contract = artifact["contract"]
        category = (
            "execution_path_unproven"
            if key[0] != "operation"
            else "requires_production_write"
            if contract["effect"] != "read"
            else None
        )
        if category is not None:
            outcomes[key] = _base_outcome(key, contract["effect"], category)
    return outcomes


def ranked_candidates(
    artifacts: Mapping[tuple[str, str], Mapping[str, Any]], selected: set[str]
) -> list[Mapping[str, Any]]:
    values = [
        artifact for key, artifact in artifacts.items()
        if key[0] == "operation"
        and artifact["contract"]["effect"] == "read"
        and _operations()[key[1]].live_probe.enabled
        and (not selected or key[1] in selected)
    ]
    return sorted(values, key=_candidate_rank)


def _candidate_rank(artifact: Mapping[str, Any]) -> tuple[int, int, str]:
    selector = str(artifact["contract"]["selector"])
    placeholders = _placeholders(_operations()[selector].live_probe.inputs)
    return (
        0 if placeholders & _APP_PLACEHOLDERS else 1,
        len(placeholders - _APP_PLACEHOLDERS),
        selector,
    )


def _placeholders(value: Any) -> set[str]:
    if isinstance(value, Mapping):
        return set().union(*(_placeholders(item) for item in value.values()), set())
    if isinstance(value, (list, tuple)):
        return set().union(*(_placeholders(item) for item in value), set())
    return {value} if isinstance(value, str) and value.startswith("$") else set()


def resolve_receipts(
    state_root: Path, references: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    receipts = []
    for reference in references:
        queried = get_http_receipt(state_root, reference)
        items = queried.get("items", [])
        if len(items) == 1 and items[0].get("run_status") in {
            "complete",
            "run_in_progress",
        }:
            receipts.append(dict(items[0]))
    return receipts


def result_outcome(
    selector: str, result: Mapping[str, Any], request_count: int,
    receipts: Sequence[Mapping[str, Any]], recorded: bool, reasons: Sequence[str],
) -> dict[str, Any]:
    return {
        **_base_outcome(("operation", selector), "read", (
            "validated" if recorded else _category_for_result(result, reasons)
        )),
        "attempted": True,
        "request_count": request_count,
        "result_status": str(result.get("status", "unknown")),
        "result_nonempty": response_data_nonempty({"data": result.get("data")}),
        "receipt_ids": _receipt_ids(receipts, selector),
        "schema_fingerprint": result.get("schema_fingerprint"),
        "validation_recorded": recorded,
        "reason_codes": list(reasons),
    }


def error_outcome(
    selector: str, error: BaseException, request_count: int,
    receipts: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    category = (
        "request_budget_exhausted"
        if isinstance(error, RequestBudgetExceeded)
        else _category_for_error(error)
        if isinstance(error, GravityInsightError)
        else "local_or_transport_failure"
    )
    return {
        **_base_outcome(("operation", selector), "read", category),
        "attempted": True,
        "request_count": request_count,
        "result_status": None,
        "result_nonempty": False,
        "receipt_ids": _receipt_ids(receipts, selector),
        "schema_fingerprint": None,
        "reason_codes": [_error_reason(error)],
    }


def mark_budget_exhausted(
    outcomes: dict[tuple[str, str], dict[str, Any]],
    candidates: Sequence[Mapping[str, Any]], current: Mapping[str, Any],
) -> None:
    for artifact in candidates[candidates.index(current):]:
        selector = str(artifact["contract"]["selector"])
        outcomes.setdefault(
            ("operation", selector),
            {
                **_base_outcome(
                    ("operation", selector), "read", "request_budget_exhausted"
                ),
                "reason_codes": ["EXECUTION_REQUEST_BUDGET_EXHAUSTED"],
            },
        )


def mark_terminal_stop(
    outcomes: dict[tuple[str, str], dict[str, Any]],
    candidates: Sequence[Mapping[str, Any]], current: Mapping[str, Any],
    category: str,
) -> None:
    reason = {
        "stopped_after_rate_limit": "EXECUTION_STOPPED_AFTER_RATE_LIMIT",
        "stopped_after_authentication_failure": "EXECUTION_STOPPED_AFTER_AUTH_FAILURE",
    }[category]
    start = candidates.index(current) + 1
    for artifact in candidates[start:]:
        selector = str(artifact["contract"]["selector"])
        outcomes.setdefault(
            ("operation", selector),
            {
                **_base_outcome(("operation", selector), "read", category),
                "reason_codes": [reason],
            },
        )


def terminal_stop_category(
    *, error: BaseException | None = None, result: Mapping[str, Any] | None = None
) -> str | None:
    code: Any = getattr(error, "code", None) if error is not None else None
    if isinstance(result, Mapping) and isinstance(result.get("error"), Mapping):
        code = result["error"].get("code")
    code = getattr(code, "value", code)
    if code == "RATE_LIMITED":
        return "stopped_after_rate_limit"
    if code in {"AUTH_MISSING", "AUTH_REJECTED"}:
        return "stopped_after_authentication_failure"
    return None


def trust_counts(store: CapabilityValidationStore) -> dict[str, int]:
    service = CapabilityTrustService(store)
    results = [
        service.trust(
            str(item["contract"]["identity_kind"]),
            str(item["contract"]["selector"]),
        )
        for item in capability_contracts()
    ]
    return {
        "stable": sum(item["trust_status"] == "stable" for item in results),
        "complete": sum(item["completeness"] == "complete" for item in results),
        "data_quality_pass": sum(item["data_quality"]["status"] == "pass" for item in results),
        "provider_matched": sum(item["provider"]["status"] == "matched" for item in results),
        "total": len(results),
    }


def _base_outcome(
    key: tuple[str, str], effect: str, category: str
) -> dict[str, Any]:
    return {
        "identity_kind": key[0], "selector": key[1], "effect": effect,
        "attempted": False, "category": category, "request_count": 0,
        "validation_recorded": False, "reason_codes": [],
    }


def _receipt_ids(receipts: Sequence[Mapping[str, Any]], selector: str) -> list[str]:
    return [
        str(item["receipt_id"])
        for item in receipts if item.get("operation_id") == selector
    ]


def _receipt_is_current(
    receipt: Mapping[str, Any], started_at: datetime, observed_at: datetime
) -> bool:
    completed = _parse_timestamp(receipt.get("completed_at"))
    return completed is not None and started_at <= completed <= observed_at + timedelta(seconds=1)


def _result_is_current(
    result: Mapping[str, Any], started_at: datetime, observed_at: datetime
) -> bool:
    fetched = _parse_timestamp(result.get("fetched_at"))
    return fetched is not None and started_at - timedelta(seconds=1) <= fetched <= observed_at + timedelta(seconds=1)


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.endswith("Z"):
        return None
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00").astimezone(timezone.utc)
    except ValueError:
        return None


def _result_status_reason(result: Mapping[str, Any]) -> str:
    status = str(result.get("status", "unknown"))
    if status == "empty":
        return "EXECUTION_DATA_EMPTY"
    if status.startswith("contract_changed"):
        return "EXECUTION_RESPONSE_DRIFT"
    if status == "permission_unavailable":
        return "EXECUTION_PERMISSION_UNAVAILABLE"
    if status == "auth_error":
        return "EXECUTION_AUTHENTICATION_FAILED"
    return "EXECUTION_NOT_SUCCESSFUL"


def _category_for_result(result: Mapping[str, Any], reasons: Sequence[str]) -> str:
    status = str(result.get("status", "unknown"))
    if "EXECUTION_PERMISSION_UNAVAILABLE" in reasons:
        return "permission_unavailable"
    if "EXECUTION_AUTHENTICATION_FAILED" in reasons:
        return "authentication_failed"
    if "EXECUTION_DATA_EMPTY" in reasons:
        return "no_data_in_current_scope"
    if "EXECUTION_RESPONSE_DRIFT" in reasons or status.startswith("contract_changed"):
        return "response_contract_drift"
    error = result.get("error")
    if isinstance(error, Mapping) and error.get("category") == "permission":
        return "permission_unavailable"
    return "data_quality_unproven"


def _category_for_error(error: GravityInsightError) -> str:
    name = type(error).__name__
    if name == "PermissionUnavailableError":
        return "permission_unavailable"
    if name in {"ParentRequiredError", "InputValidationError", "PolicyViolation"}:
        return "probe_input_or_parent_unavailable"
    if name == "AuthenticationError":
        return "authentication_failed"
    if name in {"ContractChangedError", "ManifestError"}:
        return "response_contract_drift"
    return "upstream_or_runtime_rejected"


def _error_reason(error: BaseException) -> str:
    raw = getattr(error, "code", "")
    value = str(getattr(raw, "value", raw)).upper()
    if re.fullmatch(r"[A-Z][A-Z0-9_]{1,127}", value):
        return value
    return f"EXECUTION_{type(error).__name__.upper()}"


def timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


__all__ = [
    "MAX_PRODUCTION_REQUESTS", "RUN_SCHEMA_VERSION", "BudgetedSession",
    "RequestBudgetExceeded", "bind_probe_app", "error_outcome", "inventory",
    "mark_budget_exhausted", "mark_terminal_stop", "ranked_candidates",
    "resolve_receipts", "result_outcome", "static_outcomes", "timestamp",
    "terminal_stop_category", "trust_counts",
    "validation_from_execution",
]
