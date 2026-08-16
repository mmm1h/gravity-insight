"""Value-free upstream schema evidence and runtime health overlays."""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import IntEnum
from pathlib import Path
from typing import Any, Callable, Mapping

from .errors import (
    AuthenticationError,
    ContractChangedError,
    PermissionUnavailableError,
)


HEALTHY = "healthy"
SUSPECT = "suspect"
CONTRACT_CHANGED_ADDITIVE = "contract_changed_additive"
UPSTREAM_CHANGED = "upstream_changed"
DEGRADED = "degraded"
AUTH_ERROR = "auth_error"
PERMISSION_UNAVAILABLE = "permission_unavailable"


class ProjectionDrift(IntEnum):
    NONE = 0
    ADDITIVE = 1
    BREAKING = 2

_HEALTH_STATUSES = frozenset(
    {
        HEALTHY,
        SUSPECT,
        CONTRACT_CHANGED_ADDITIVE,
        UPSTREAM_CHANGED,
        DEGRADED,
        AUTH_ERROR,
        PERMISSION_UNAVAILABLE,
    }
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class DriftSignal:
    operation_id: str
    kind: str
    census_complete: bool = False
    probe_confirmed: bool = False
    contract_updated: bool = False
    evidence_refs: tuple[str, ...] = ()


@dataclass(frozen=True)
class HealthEntry:
    status: str = HEALTHY
    reason: str = "no active upstream drift evidence"
    updated_at: str | None = None
    recovery_clean_probes: int = 0
    recovery_armed: bool = False
    resume_status: str | None = None
    evidence_refs: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "reason": self.reason,
            "updated_at": self.updated_at,
            "recovery_clean_probes": self.recovery_clean_probes,
            "recovery_armed": self.recovery_armed,
            "resume_status": self.resume_status,
            "evidence_refs": list(self.evidence_refs),
        }


class HealthOverlay:
    """Advisory runtime availability state; source contracts are never modified."""

    def __init__(
        self,
        state_path: Path | None = None,
        *,
        clock: Callable[[], datetime] = _utc_now,
        clean_probes_required: int = 2,
    ) -> None:
        if clean_probes_required < 1:
            raise ValueError("clean_probes_required must be positive")
        self._state_path = state_path
        self._clock = clock
        self._clean_probes_required = clean_probes_required
        self._entries: dict[str, HealthEntry] = {}
        self._lock = threading.RLock()
        self._load()

    @classmethod
    def from_environment(
        cls, explicit: "HealthOverlay | None"
    ) -> "HealthOverlay | None":
        if explicit is not None:
            return explicit
        path = os.environ.get("GRAVITY_INSIGHT_HEALTH_OVERLAY")
        return cls(Path(path)) if path else None

    def state_for(self, operation_id: str) -> HealthEntry:
        with self._lock:
            return self._entries.get(
                operation_id,
                self._entries.get("*", HealthEntry()),
            )

    def active_state_for(self, operation_id: str) -> HealthEntry | None:
        """Return only explicit operation or global overlay state."""

        with self._lock:
            return self._entries.get(operation_id, self._entries.get("*"))

    def apply(self, signal: DriftSignal) -> HealthEntry:
        if not signal.operation_id:
            raise ValueError("operation_id must not be empty")
        with self._lock:
            current = self._entries.get(signal.operation_id, HealthEntry())
            updated = self._transition(current, signal)
            self._entries[signal.operation_id] = updated
            self._persist()
            return updated

    def apply_impact_report(self, report: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
        results: dict[str, dict[str, Any]] = {}
        complete = bool(report.get("census_complete"))
        operations = report.get("operations")
        if not isinstance(operations, list):
            return results
        for operation in operations:
            if not isinstance(operation, Mapping):
                continue
            operation_id = str(operation.get("operation_id", ""))
            impact_types = {str(item) for item in operation.get("impact_types", ())}
            if "method_changed" in impact_types:
                kind = "method_changed"
            elif "route_removed" in impact_types or "path_changed" in impact_types:
                kind = "route_removed"
            elif "route_added" in impact_types:
                kind = "bundle_changed"
            else:
                continue
            entry = self.apply(
                DriftSignal(
                    operation_id=operation_id,
                    kind=kind,
                    census_complete=complete,
                    evidence_refs=tuple(
                        str(item) for item in operation.get("evidence_refs", ())
                    ),
                )
            )
            results[operation_id] = entry.to_dict()
        return results

    def apply_probe_evidence(
        self,
        operation_id: str,
        *,
        outcome: str,
        raw_schema_diff: Mapping[str, Any] | None = None,
        probe_confirmed: bool = False,
        contract_updated: bool = False,
        evidence_refs: tuple[str, ...] = (),
    ) -> HealthEntry:
        """Translate an explicit probe outcome without inferring from error text."""

        normalized = outcome.strip().casefold()
        if normalized in {"timeout", "http_5xx", "auth_failure", "permission_failure"}:
            return self.apply(
                DriftSignal(
                    operation_id,
                    normalized,
                    evidence_refs=evidence_refs,
                )
            )
        if normalized in {"route_missing", "method_rejected"}:
            return self.apply(
                DriftSignal(
                    operation_id,
                    normalized,
                    probe_confirmed=probe_confirmed,
                    evidence_refs=evidence_refs,
                )
            )
        if normalized not in {"success", "empty", "clean"}:
            raise ValueError(f"unsupported probe outcome: {outcome}")
        classification = (
            str(raw_schema_diff.get("classification", "unchanged"))
            if isinstance(raw_schema_diff, Mapping)
            else "unchanged"
        )
        if classification == "additive":
            kind = "schema_additive"
        elif classification == "potentially_breaking":
            removed = raw_schema_diff.get("removed_required_paths", ())
            kind = "required_field_missing" if removed else "type_breaking"
        elif classification in {"unchanged", "observational_expansion"}:
            kind = "clean_probe"
        else:
            raise ValueError(f"unsupported raw schema classification: {classification}")
        return self.apply(
            DriftSignal(
                operation_id,
                kind,
                probe_confirmed=probe_confirmed,
                contract_updated=contract_updated,
                evidence_refs=evidence_refs,
            )
        )

    def call_decision(self, operation_id: str) -> dict[str, Any]:
        entry = self.state_for(operation_id)
        if entry.status == UPSTREAM_CHANGED:
            return {
                "allowed": False,
                "error_code": "CONTRACT_CHANGED",
                "warning": entry.reason,
                "retry": False,
            }
        if entry.status == AUTH_ERROR:
            return {
                "allowed": False,
                "error_code": "AUTH_REJECTED",
                "warning": entry.reason,
                "retry": False,
            }
        if entry.status == PERMISSION_UNAVAILABLE:
            return {
                "allowed": False,
                "error_code": "PERMISSION_UNAVAILABLE",
                "warning": entry.reason,
                "retry": False,
            }
        warning = None if entry.status == HEALTHY else entry.reason
        return {
            "allowed": True,
            "error_code": None,
            "warning": warning,
            "retry": entry.status == DEGRADED,
        }

    def guard(self, operation_id: str) -> dict[str, Any]:
        decision = self.call_decision(operation_id)
        code = decision["error_code"]
        if code == "CONTRACT_CHANGED":
            raise ContractChangedError(decision["warning"] or "upstream contract changed")
        if code == "AUTH_REJECTED":
            raise AuthenticationError(decision["warning"] or "authentication failed")
        if code == "PERMISSION_UNAVAILABLE":
            raise PermissionUnavailableError(
                decision["warning"] or "permission is unavailable"
            )
        return decision

    def catalog_health(self, operation_id: str, base_status: str) -> str:
        entry = self.active_state_for(operation_id)
        return entry.status if entry is not None and base_status != "blocked" else base_status

    def catalog_availability(self, operation_id: str, base_status: str) -> str:
        if base_status not in {"available", "opt_in_required"}:
            return base_status
        code = self.call_decision(operation_id)["error_code"]
        return {
            "CONTRACT_CHANGED": "contract_changed",
            "AUTH_REJECTED": "auth_error",
            "PERMISSION_UNAVAILABLE": "permission_unavailable",
        }.get(str(code), base_status)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            entries = {
                operation_id: entry.to_dict()
                for operation_id, entry in sorted(self._entries.items())
            }
        return {
            "schema_version": "gravity-insight.health-overlay.v1",
            "clean_probes_required": self._clean_probes_required,
            "entries": entries,
        }

    def _transition(self, current: HealthEntry, signal: DriftSignal) -> HealthEntry:
        now = self._clock().astimezone(timezone.utc).isoformat(timespec="seconds").replace(
            "+00:00", "Z"
        )
        refs = tuple(sorted(set(current.evidence_refs) | set(signal.evidence_refs)))
        if signal.kind in {
            "route_removed", "method_changed", "path_changed", "bundle_changed",
            "schema_additive", "required_field_missing", "type_breaking",
            "route_missing", "method_rejected",
        }:
            return self._drift_transition(current, signal, now, refs)
        if signal.kind in {"timeout", "http_5xx", "auth_failure", "permission_failure"}:
            return self._temporary_transition(current, signal, now, refs)
        if signal.kind in {"contract_updated", "clean_probe"}:
            return self._recovery_transition(current, signal, now, refs)
        raise ValueError(f"unknown drift signal kind: {signal.kind}")

    def _drift_transition(
        self, current: HealthEntry, signal: DriftSignal, now: str, refs: tuple[str, ...]
    ) -> HealthEntry:
        label = signal.kind.replace("_", " ")
        if signal.kind in {"route_removed", "method_changed", "path_changed"}:
            completeness = "complete" if signal.census_complete else "incomplete"
            return HealthEntry(
                SUSPECT,
                f"{completeness} frontend census observed {label}; targeted probe required",
                now,
                evidence_refs=refs,
            )
        if signal.kind in {"route_missing", "method_rejected"}:
            status = UPSTREAM_CHANGED if signal.probe_confirmed else SUSPECT
            reason = (
                f"targeted probe confirmed {label}"
                if signal.probe_confirmed
                else f"unconfirmed {label}; explicit probe confirmation required"
            )
            return HealthEntry(status, reason, now, evidence_refs=refs)
        if signal.kind == "bundle_changed":
            if current.status in {UPSTREAM_CHANGED, CONTRACT_CHANGED_ADDITIVE}:
                return replace(current, updated_at=now, evidence_refs=refs)
            return HealthEntry(
                SUSPECT, "bundle changed without route or probe confirmation", now,
                evidence_refs=refs,
            )
        if signal.kind == "schema_additive":
            if current.status == UPSTREAM_CHANGED:
                return replace(current, updated_at=now, evidence_refs=refs)
            return HealthEntry(
                CONTRACT_CHANGED_ADDITIVE,
                "probe observed additive raw response fields; safe projection remains active",
                now, evidence_refs=refs,
            )
        status = UPSTREAM_CHANGED if signal.probe_confirmed else SUSPECT
        reason = f"probe confirmed {label}" if signal.probe_confirmed else (
            f"unconfirmed {label}; second evidence required"
        )
        return HealthEntry(status, reason, now, evidence_refs=refs)

    def _temporary_transition(
        self, current: HealthEntry, signal: DriftSignal, now: str, refs: tuple[str, ...]
    ) -> HealthEntry:
        if current.status == UPSTREAM_CHANGED:
            return replace(current, updated_at=now, evidence_refs=refs)
        resume = current.resume_status if current.status in {
            DEGRADED, AUTH_ERROR, PERMISSION_UNAVAILABLE
        } and current.resume_status else current.status
        if signal.kind in {"timeout", "http_5xx"}:
            return HealthEntry(
                DEGRADED, "transient upstream failure; use the registered retry policy", now,
                resume_status=resume, evidence_refs=refs,
            )
        status = AUTH_ERROR if signal.kind == "auth_failure" else PERMISSION_UNAVAILABLE
        subject = "authentication failed" if status == AUTH_ERROR else "permission unavailable"
        return HealthEntry(
            status, f"{subject}; this is not route drift evidence", now,
            resume_status=resume, evidence_refs=refs,
        )

    def _recovery_transition(
        self, current: HealthEntry, signal: DriftSignal, now: str, refs: tuple[str, ...]
    ) -> HealthEntry:
        contract_state = current.status in {UPSTREAM_CHANGED, CONTRACT_CHANGED_ADDITIVE}
        if signal.kind == "contract_updated":
            if not contract_state:
                return replace(current, updated_at=now, evidence_refs=refs)
            return replace(
                current, updated_at=now, recovery_armed=True,
                recovery_clean_probes=0, evidence_refs=refs,
            )
        if contract_state:
            armed = current.recovery_armed or signal.contract_updated
            count = current.recovery_clean_probes + 1 if armed else 0
            if armed and count >= self._clean_probes_required:
                return HealthEntry(
                    HEALTHY, "reviewed contract passed consecutive clean probes", now,
                    evidence_refs=refs,
                )
            return replace(
                current, updated_at=now, recovery_armed=armed,
                recovery_clean_probes=count, evidence_refs=refs,
            )
        if current.status in {DEGRADED, AUTH_ERROR, PERMISSION_UNAVAILABLE}:
            resume = current.resume_status or HEALTHY
            resume = HEALTHY if resume == SUSPECT else resume
            reason = "clean probe restored operation health" if resume == HEALTHY else current.reason
            return HealthEntry(resume, reason, now, evidence_refs=refs)
        return HealthEntry(HEALTHY, "targeted probe was clean", now, evidence_refs=refs)

    def _load(self) -> None:
        if self._state_path is None:
            return
        try:
            payload = json.loads(self._state_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return
        if not isinstance(payload, Mapping) or payload.get("schema_version") != (
            "gravity-insight.health-overlay.v1"
        ):
            return
        entries = payload.get("entries")
        if not isinstance(entries, Mapping):
            return
        for operation_id, value in entries.items():
            if not isinstance(value, Mapping) or value.get("status") not in _HEALTH_STATUSES:
                continue
            try:
                clean_probes = max(0, int(value.get("recovery_clean_probes", 0)))
            except (TypeError, ValueError):
                clean_probes = 0
            raw_refs = value.get("evidence_refs", ())
            refs = raw_refs if isinstance(raw_refs, (list, tuple)) else ()
            self._entries[str(operation_id)] = HealthEntry(
                status=str(value["status"]),
                reason=str(value.get("reason", ""))[:500],
                updated_at=str(value["updated_at"]) if value.get("updated_at") else None,
                recovery_clean_probes=clean_probes,
                recovery_armed=bool(value.get("recovery_armed")),
                resume_status=(
                    str(value["resume_status"])
                    if value.get("resume_status") in _HEALTH_STATUSES
                    else None
                ),
                evidence_refs=tuple(
                    sorted(str(item)[:500] for item in refs)
                ),
            )

    def _persist(self) -> None:
        if self._state_path is None:
            return
        payload = self.snapshot()
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self._state_path.with_name(
                f".{self._state_path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
            )
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                encoding="utf-8",
            )
            os.replace(temporary, self._state_path)
        except OSError:
            return


def operation_health(
    operation: Mapping[str, Any], probe_status: str,
    health_overlay: HealthOverlay | None = None, operation_id: str = "",
) -> str:
    if not bool(operation.get("executable", True)) or operation.get("stability") in {
        "permission_unavailable", "blocked_privacy", "blocked_write", "deprecated",
    }:
        status = "blocked"
    elif probe_status == "contract_changed":
        status = "upstream_changed"
    elif probe_status == "contract_changed_additive":
        status = CONTRACT_CHANGED_ADDITIVE
    elif probe_status in {"partial", "parent_required", "permission_unavailable",
                          "semantic_error", "unavailable", "error"}:
        status = "suspect"
    else:
        status = "stable"
    return health_overlay.catalog_health(operation_id, status) if health_overlay else status


def operation_availability(
    stability: str, *, executable: bool = True, block_reason: str | None = None,
    health_overlay: HealthOverlay | None = None, operation_id: str = "",
) -> str:
    if not executable:
        return block_reason or "catalog_only"
    status = {"stable": "available", "experimental": "opt_in_required",
              "permission_unavailable": "permission_unavailable", "blocked_privacy": "blocked_privacy",
              "blocked_write": "blocked_write", "deprecated": "deprecated"}.get(stability, "unavailable")
    return health_overlay.catalog_availability(operation_id, status) if health_overlay else status


def projection_drift_status(drift: ProjectionDrift) -> str:
    return {
        ProjectionDrift.ADDITIVE: "contract_changed_additive",
        ProjectionDrift.BREAKING: "contract_changed",
    }[drift]


def aggregate_contract_status(statuses: set[str]) -> str | None:
    if "contract_changed" in statuses:
        return "contract_changed"
    if "contract_changed_additive" in statuses:
        return "contract_changed_additive"
    return None
