"""Immutable caller-request binding for the registered user-event workbook."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime
import hashlib
import hmac
import json
import re
import secrets
from typing import Any


SCHEMA_VERSION = "gravity.user-event-export-scope.v1"
COMPLETENESS_SCHEMA = "gravity.user-event-export-completeness.v1"
OPERATION = ".".join(("export", "analysis", "user_event", "start"))
_FIELDS = frozenset({
    "schema_version", "operation_id", "job_id", "salt", "request_fingerprint",
    "client_fingerprint", "date_list", "event_aliases", "ambiguous_aliases",
    "conditions_verification", "integrity_sha256",
})
_HEX = re.compile(r"[0-9a-f]+")
_REASONS = frozenset({
    "request_scope_invalid", "task_binding_mismatch", "request_binding_mismatch",
    "scope_receipt_invalid", "scope_receipt_unavailable", "client_mismatch",
    "timestamp_unverifiable", "date_out_of_scope", "event_identity_unverifiable",
    "event_out_of_scope", "event_metadata_unavailable",
})


class UserEventScopeError(ValueError):
    """A fixed reason without any expected or observed user value."""

    def __init__(self, reason: str) -> None:
        super().__init__("user-event export scope could not be verified")
        self.reason = reason if reason in _REASONS else "scope_receipt_invalid"


def _canonical(value: Any) -> bytes:
    return json.dumps(dict(value) if isinstance(value, Mapping) else value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _fingerprint(salt: str, value: Any) -> str:
    return hmac.new(bytes.fromhex(salt), _canonical(value), hashlib.sha256).hexdigest()


@dataclass(frozen=True)
class UserEventExportScope:
    salt: str
    request_fingerprint: str
    client_fingerprint: str
    dates: tuple[str, str]
    event_aliases: frozenset[str] | None
    ambiguous_aliases: frozenset[str]
    conditions_verification: str
    job_id: str | None = None

    @classmethod
    def capture(cls, payload: Mapping[str, Any], metadata: Sequence[Mapping[str, Any]] = ()) -> UserEventExportScope:
        salt = secrets.token_hex(16)
        try:
            days = tuple(payload["date_list"])
            if len(days) != 2 or any(not isinstance(day, str) or date.fromisoformat(day).isoformat() != day for day in days) or days[0] > days[1]:
                raise ValueError("date shape")
            client = payload["client_id"]
            if not isinstance(client, str) or not 1 <= len(client) <= 256:
                raise ValueError("client shape")
            items = payload.get("query_item_list", [])
            requested = set(payload.get("event_list", []))
            if not requested:
                requested.update(item["event_name"] for item in items)
            aliases, ambiguous = _event_aliases(requested, metadata, str(payload["app_id"]))
            conditions = "unavailable" if any(item.get("conditions") for item in items) else "not_requested"
            return cls(salt, _fingerprint(salt, payload), _fingerprint(salt, client), days, aliases, ambiguous, conditions)
        except UserEventScopeError:
            raise
        except (KeyError, TypeError, ValueError):
            raise UserEventScopeError("request_scope_invalid") from None

    def bind_job(self, job_id: str) -> UserEventExportScope:
        if not isinstance(job_id, str) or not 1 <= len(job_id) <= 256 or self.job_id not in (None, job_id):
            raise UserEventScopeError("task_binding_mismatch")
        return replace(self, job_id=job_id)

    def receipt(self) -> dict[str, Any]:
        value = {
            "schema_version": SCHEMA_VERSION, "operation_id": OPERATION,
            "job_id": self.job_id, "salt": self.salt,
            "request_fingerprint": self.request_fingerprint, "client_fingerprint": self.client_fingerprint,
            "date_list": list(self.dates),
            "event_aliases": None if self.event_aliases is None else sorted(self.event_aliases),
            "ambiguous_aliases": sorted(self.ambiguous_aliases),
            "conditions_verification": self.conditions_verification,
        }
        return {**value, "integrity_sha256": hashlib.sha256(_canonical(value)).hexdigest()}

    @classmethod
    def from_receipt(
        cls, value: Any, *, job_id: str | None = None, payload: Mapping[str, Any] | None = None,
    ) -> UserEventExportScope:
        try:
            _receipt_shape(value)
            days = _receipt_days(value["date_list"])
            aliases = _receipt_aliases(value["event_aliases"], optional=True)
            ambiguous = _receipt_aliases(value["ambiguous_aliases"], optional=False)
            bound = value["job_id"]
            scope = cls(value["salt"], value["request_fingerprint"], value["client_fingerprint"], tuple(days), aliases, ambiguous, value["conditions_verification"], bound)
            if scope.receipt() != value:
                raise ValueError("receipt integrity")
            if job_id is not None and bound != job_id:
                raise UserEventScopeError("task_binding_mismatch")
            if payload is not None and not hmac.compare_digest(scope.request_fingerprint, _fingerprint(scope.salt, payload)):
                raise UserEventScopeError("request_binding_mismatch")
            return scope
        except UserEventScopeError:
            raise
        except (KeyError, TypeError, ValueError):
            raise UserEventScopeError("scope_receipt_invalid") from None

    def verify_row(self, client: str, timestamp: str, event: str) -> None:
        if not hmac.compare_digest(self.client_fingerprint, _fingerprint(self.salt, client)):
            raise UserEventScopeError("client_mismatch")
        try:
            if not isinstance(timestamp, str) or not 19 <= len(timestamp) <= 64:
                raise ValueError("timestamp shape")
            observed_day = datetime.fromisoformat(timestamp.replace("Z", "+00:00")).date().isoformat()
        except ValueError:
            raise UserEventScopeError("timestamp_unverifiable") from None
        if not self.dates[0] <= observed_day <= self.dates[1]:
            raise UserEventScopeError("date_out_of_scope")
        if self.event_aliases is not None and event not in self.event_aliases:
            raise UserEventScopeError("event_identity_unverifiable" if event in self.ambiguous_aliases else "event_out_of_scope")

    def completeness(self, rows: int | None = None) -> dict[str, Any]:
        return {
            "schema_version": COMPLETENESS_SCHEMA, "scope": self.receipt(),
            "file_scope_verification": "pending" if rows is None else "verified",
            "file_rows": rows, "source_completeness": "unknown",
            "conditions_verification": self.conditions_verification,
            "date_check_basis": "file_timestamp_date_without_timezone_conversion",
            "app_scope_verification": "create_request_only_not_in_file_projection",
            "native_summary_reconciliation": "unavailable_without_snapshot_binding",
            "snapshot_id_availability": "unavailable", "dataset_as_of_availability": "unavailable",
            "ordering_verification": "unavailable",
            "binding_evidence": "caller_request_receipt_not_upstream_attestation",
            "integrity_semantics": "checksum_not_authenticated_signature",
        }


def scope_from_completeness(value: Any, *, job_id: str | None = None, payload: Mapping[str, Any] | None = None) -> UserEventExportScope:
    if not isinstance(value, Mapping) or value.get("schema_version") != COMPLETENESS_SCHEMA:
        raise UserEventScopeError("scope_receipt_unavailable")
    scope = UserEventExportScope.from_receipt(value.get("scope"), job_id=job_id, payload=payload)
    rows = value.get("file_rows")
    if rows is not None and (type(rows) is not int or rows < 0):
        raise UserEventScopeError("scope_receipt_invalid")
    if value != scope.completeness(rows):
        raise UserEventScopeError("scope_receipt_invalid")
    return scope


def is_user_event_completeness(value: Any) -> bool:
    return isinstance(value, Mapping) and value.get("schema_version") == COMPLETENESS_SCHEMA


def scope_failure_reason(stage: Any, details: Any) -> str | None:
    if stage not in {"scope_validation", "scope_receipt"} or not isinstance(details, Mapping):
        return None
    reason = details.get("reason")
    return reason if isinstance(reason, str) and reason in _REASONS else None


def _receipt_aliases(value: Any, *, optional: bool) -> frozenset[str] | None:
    if value is None and optional:
        return None
    if not isinstance(value, (list, tuple)) or len(value) > 4200 or any(not isinstance(item, str) or not 1 <= len(item) <= 4096 for item in value) or list(value) != sorted(set(value)):
        raise ValueError("alias shape")
    return frozenset(value)


def _receipt_shape(value: Any) -> None:
    if not isinstance(value, Mapping) or set(value) != _FIELDS or value["schema_version"] != SCHEMA_VERSION or value["operation_id"] != OPERATION:
        raise ValueError("receipt shape")
    if any(not isinstance(value[key], str) or len(value[key]) != size or _HEX.fullmatch(value[key]) is None for key, size in (("salt", 32), ("client_fingerprint", 64), ("request_fingerprint", 64), ("integrity_sha256", 64))):
        raise ValueError("digest shape")
    if value["conditions_verification"] not in {"not_requested", "unavailable"}:
        raise ValueError("condition evidence")
    bound = value["job_id"]
    if bound is not None and (not isinstance(bound, str) or not 1 <= len(bound) <= 256):
        raise ValueError("task shape")


def _receipt_days(value: Any) -> tuple[str, str]:
    if not isinstance(value, (list, tuple)) or len(value) != 2 or any(not isinstance(day, str) or date.fromisoformat(day).isoformat() != day for day in value) or value[0] > value[1]:
        raise ValueError("date shape")
    return tuple(value)


def _event_aliases(requested: set[str], rows: Sequence[Mapping[str, Any]], app_id: str) -> tuple[frozenset[str] | None, frozenset[str]]:
    if not requested:
        return None, frozenset()
    by_name, owners = _event_index(rows, app_id)
    aliases, ambiguous = set(), set()
    for name in requested:
        candidates = by_name.get(name, [])
        if len(candidates) != 1:
            raise UserEventScopeError("event_metadata_unavailable")
        unique = set()
        for token in (name, candidates[0].get("cname")):
            if not isinstance(token, str) or not 1 <= len(token) <= 4096:
                continue
            if owners[token] == {name}:
                unique.add(token)
            else:
                ambiguous.add(token)
        if not unique:
            raise UserEventScopeError("event_identity_unverifiable")
        aliases.update(unique)
    return frozenset(aliases), frozenset(ambiguous)


def _event_index(rows: Sequence[Mapping[str, Any]], app_id: str) -> tuple[dict[str, list[Mapping[str, Any]]], dict[str, set[str]]]:
    by_name: dict[str, list[Mapping[str, Any]]] = {}
    owners: dict[str, set[str]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            raise UserEventScopeError("event_metadata_unavailable")
        name = row.get("name")
        if not isinstance(name, str) or row.get("visible") is False or (row.get("app_id") is not None and str(row["app_id"]) != app_id):
            continue
        by_name.setdefault(name, []).append(row)
        for token in (name, row.get("cname")):
            if isinstance(token, str) and token:
                owners.setdefault(token, set()).add(name)
    return by_name, owners
