"""Offline cache inventory. Absence of reference evidence never authorizes GC."""

from __future__ import annotations

import os
import re
import stat
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .contracts.envelope_obligations import (
    CompletenessState, DataCompleteness, DiagnosticCategory, DiagnosticEvidence,
    DiagnosticState, EnvelopeObligations, ExecutionState, ExecutionStatus,
    MutationCertainty, MutationState, SemanticState, SemanticValidity, serialize_envelope,
)
from .receipt_retention import (
    HTTP_RECEIPT_SWEEP_INTERVAL, _process_is_alive, _receipt_process_id,
    http_receipt_retention_policy,
)
from .support.cache_files import allocated_bytes, assert_unlinked, identity, linked, unlink_unchanged
from .support.cache_paths import cache_roots


_SCOPE = re.compile(r"[0-9a-f]{32}\Z")
_PICKLE = re.compile(r"[0-9a-f]{64}\.pkl\Z")
_STAGING = re.compile(r"\.operation-catalog\.json\.([1-9][0-9]*)\.([0-9]+)\.tmp\Z")
_CATEGORIES = ("principals", "receipts", "skill-hub-cas", "skill-maintenance/generations",
               "field-policy", "metadata", "operation-catalog", "other")
REASONS = {
    "OBSOLETE_PICKLE_NO_READER": "Pre-JSON field-policy format; current reader uses digest.json only. Exact writer version unknown.",
    "ORPHAN_CATALOG_STAGING": "Catalog PID/thread staging file; owner exited, grace elapsed, final reader uses operation-catalog.json. Writer version unknown.",
    "REFERENCES_UNCERTAIN": "No complete persistent principal retirement/lease/reference inventory; retain even when old.",
    "AUDIT_REFERENCES_UNCERTAIN": "Audit holds and external result_audit.http_receipts references cannot be disproved offline; retain.",
    "PROJECT_LOCK_REFERENCES_UNCERTAIN": "Project locks outside the cache and concurrent readers are not exhaustively registered; retain all CAS blobs.",
    "ACTIVE_OR_ROLLBACK_UNCERTAIN": "No complete active/rollback reference proof; retain every seed generation.",
    "ACCOUNT_SNAPSHOT": "Account-scoped network snapshot; size similarity does not prove equivalence or obsolescence.",
    "UNKNOWN_ARTIFACT": "No current reader/retention proof for this artifact.",
    "LIVE_PROCESS": "Owner PID is alive or process status is inaccessible.",
    "RECENT_FILE": "Deletion grace has not elapsed.",
    "MULTIPLE_LINKS": "Allocation may be shared through hard links; do not claim reclaimable bytes.",
    "PROTECTION_STATE_PRESENT": "A hold/lease marker is present; its state is not interpreted or overridden.",
    "SCAN_INCOMPLETE": "An inaccessible or linked subtree prevents a complete safety inventory.",
    "FILE_CHANGED_OR_BUSY": "Execution revalidation failed; nothing was deleted for this item.",
}


@dataclass(repr=False)
class Entry:
    root: Path
    path: Path
    root_id: str
    item_id: str
    category: str
    kind: str
    info: os.stat_result
    disk: int | None
    reason: str
    reclaimable: bool

    def public(self) -> dict[str, Any]:
        return {"root_id": self.root_id, "item_id": self.item_id,
                "category": self.category, "kind": self.kind,
                "logical_bytes": self.info.st_size, "disk_bytes": self.disk,
                "action": "delete" if self.reclaimable else "retain",
                "reason_code": self.reason}


def _classify(relative: Path) -> tuple[str, str]:
    parts = relative.parts
    if len(parts) >= 2 and _SCOPE.fullmatch(parts[0]):
        return _account_kind(parts[1:])
    state = parts[1:] if parts[:1] == ("default",) else parts[2:] if parts[:1] == ("workspaces",) else ()
    if state[:1] == ("principals",) and len(state) >= 3 and _SCOPE.fullmatch(state[1]):
        return "principals", _receipt_kind(state[2:]) or "private_state"
    if state[:1] == ("receipts",):
        return "receipts", _receipt_kind(state) or "unknown"
    if state[:1] == ("skill-hub-cas",):
        return "skill-hub-cas", "cas_artifact"
    if state[:2] == ("skill-maintenance", "generations"):
        return "skill-maintenance/generations", "seed_generation"
    return "other", "unknown"


def _account_kind(parts: tuple[str, ...]) -> tuple[str, str]:
    if parts[0] == "field-policy":
        obsolete = len(parts) == 2 and parts[1].endswith(".pkl")
        return "field-policy", "obsolete_pickle" if obsolete else "snapshot"
    if parts[0] == "metadata":
        return "metadata", "catalog_snapshot" if parts[1:] == ("catalog.sqlite3",) else "snapshot_sidecar"
    if len(parts) == 1 and _STAGING.fullmatch(parts[0]):
        return "operation-catalog", "catalog_staging"
    if parts == ("operation-catalog.json",):
        return "operation-catalog", "snapshot"
    return "other", "unknown"


def _receipt_kind(parts: tuple[str, ...]) -> str | None:
    if parts[:2] == ("receipts", "http") and len(parts) == 3 and parts[-1].endswith(".json"):
        return "http_receipt"
    if parts[:1] == ("receipts",) and len(parts) == 2 and parts[-1].endswith(".json"):
        return "execution_receipt"
    return None


def _decision(path: Path, category: str, kind: str, info: os.stat_result,
              now: float, min_age_days: int) -> tuple[str, bool]:
    if info.st_nlink != 1:
        return "MULTIPLE_LINKS", False
    if kind in {"catalog_staging", "http_receipt"}:
        match = _STAGING.fullmatch(path.name)
        pid = int(match[1]) if match else _receipt_process_id(path.name)
        if pid is not None and _process_is_alive(pid):
            return "LIVE_PROCESS", False
    if kind in {"obsolete_pickle", "catalog_staging"}:
        if kind == "obsolete_pickle" and not _PICKLE.fullmatch(path.name):
            return "UNKNOWN_ARTIFACT", False
        if info.st_mtime > now - min_age_days * 86400:
            return "RECENT_FILE", False
        return ("OBSOLETE_PICKLE_NO_READER" if kind == "obsolete_pickle" else "ORPHAN_CATALOG_STAGING"), True
    if kind in {"http_receipt", "execution_receipt"}:
        return "AUDIT_REFERENCES_UNCERTAIN", False
    reason = {"principals": "REFERENCES_UNCERTAIN", "receipts": "AUDIT_REFERENCES_UNCERTAIN",
              "skill-hub-cas": "PROJECT_LOCK_REFERENCES_UNCERTAIN",
              "skill-maintenance/generations": "ACTIVE_OR_ROLLBACK_UNCERTAIN",
              "field-policy": "ACCOUNT_SNAPSHOT", "metadata": "ACCOUNT_SNAPSHOT",
              "operation-catalog": "ACCOUNT_SNAPSHOT"}
    return reason.get(category, "UNKNOWN_ARTIFACT"), False


def _measure(entries: Iterable[Entry]) -> dict[str, Any]:
    rows = list(entries)
    known = sum(row.disk for row in rows if row.disk is not None)
    unknown = sum(row.disk is None for row in rows)
    return {"files": len(rows), "logical_bytes": sum(row.info.st_size for row in rows),
            "disk_bytes": None if unknown else known, "known_disk_bytes": known,
            "allocation_unknown_files": unknown}


def _summary(entries: Iterable[Entry]) -> dict[str, Any]:
    rows = list(entries)
    return {**_measure(rows), "reclaimable": _measure(row for row in rows if row.reclaimable),
            "retained": _measure(row for row in rows if not row.reclaimable),
            "retained_reasons": dict(sorted(Counter(row.reason for row in rows if not row.reclaimable).items()))}


def inventory(*, roots: Iterable[Path] | None = None, now: float | None = None,
              min_age_days: int = 7, max_files: int | None = None,
              max_disk_bytes: int | None = None) -> tuple[dict[str, Any], list[Entry]]:
    if min_age_days < 0 or any(value is not None and value < 0 for value in (max_files, max_disk_bytes)):
        raise ValueError("Cache budgets and grace must be non-negative")
    selected = tuple(dict.fromkeys(Path(root).absolute() for root in (cache_roots() if roots is None else roots)))
    timestamp = time.time() if now is None else now
    entries: list[Entry] = []
    root_rows = []
    scan_errors: list[dict[str, str]] = []
    for number, root in enumerate(selected, 1):
        root_id = f"root-{number}"
        present, rows, errors = _scan_root(root, selected, root_id, len(entries), timestamp, min_age_days)
        entries.extend(rows)
        scan_errors.extend({"root_id": root_id, "reason_code": error} for error in errors)
        root_rows.append({"root_id": root_id, "location": "canonical" if number == 1 else "legacy_residue",
                          "exists": present, **_summary(rows)})
    return _report(entries, root_rows, scan_errors, timestamp, max_files, max_disk_bytes), entries


def _walk(root: Path, selected: tuple[Path, ...], errors: list[str]):
    pending = [root]
    while pending:
        directory = pending.pop()
        try:
            assert_unlinked(directory)
            with os.scandir(directory) as iterator:
                children = sorted(iterator, key=lambda child: child.name)
            for child in children:
                path = Path(child.path)
                if path in selected:
                    continue
                # Windows DirEntry.stat can omit the stable file ID.
                info = path.lstat()
                if linked(info):
                    errors.append("LINK_REFUSED")
                elif stat.S_ISDIR(info.st_mode):
                    pending.append(path)
                    yield path, info
                elif stat.S_ISREG(info.st_mode):
                    yield path, info
                else:
                    errors.append("SPECIAL_FILE_REFUSED")
        except OSError:
            errors.append("SCAN_INCOMPLETE")


def _scan_root(root, selected, root_id, offset, timestamp, min_age_days):
    rows: list[Entry] = []
    errors: list[str] = []
    protected = False
    try:
        root.lstat()
    except FileNotFoundError:
        return False, rows, errors
    except OSError:
        return True, rows, ["SCAN_INCOMPLETE"]
    for path, info in _walk(root, selected, errors):
        name = path.name.casefold()
        protected |= "hold" in name or "lease" in name
        if stat.S_ISDIR(info.st_mode):
            continue
        try:
            row = _entry(root, path, root_id, offset + len(rows) + 1, info, timestamp, min_age_days)
            rows.append(row)
        except OSError:
            errors.append("SCAN_INCOMPLETE")
    if protected or errors:
        for row in rows:
            if row.reclaimable:
                row.reclaimable = False
                row.reason = "PROTECTION_STATE_PRESENT" if protected else "SCAN_INCOMPLETE"
    return True, rows, errors


def _entry(root, path, root_id, number, info, timestamp, min_age_days):
    category, kind = _classify(path.relative_to(root))
    reason, reclaimable = _decision(path, category, kind, info, timestamp, min_age_days)
    name = path.name.casefold()
    sensitive = name.startswith(".env") or any(word in name for word in (
        "credential", "password", "token", "cookie", "session"
    ))
    disk = None if sensitive else allocated_bytes(path, info)
    if identity(path.lstat()) != identity(info):
        raise OSError("CACHE_SCAN_CHANGED")
    return Entry(root, path, root_id, f"item-{number}", category, kind, info, disk, reason, reclaimable)


def _budget(retained, scan_errors, max_files, max_disk_bytes):
    over = []
    if max_files is not None and retained["files"] > max_files:
        over.append("FILE_BUDGET_EXCEEDED")
    if max_disk_bytes is not None and retained["known_disk_bytes"] > max_disk_bytes:
        over.append("DISK_BUDGET_EXCEEDED")
    return {"max_files": max_files, "max_disk_bytes": max_disk_bytes,
            "retained_over_budget": bool(over), "reason_codes": over,
            "assessment_complete": not scan_errors and (max_disk_bytes is None or not retained["allocation_unknown_files"])}


def _report(entries, root_rows, scan_errors, timestamp, max_files, max_disk_bytes):
    summary = _summary(entries)
    payload = {"schema_version": "gravity.cache-inventory.v1", "status": "partial" if scan_errors else "ok",
            "scope": "standard_roots_and_current_override; historical_custom_roots_not_discoverable",
            "roots": root_rows, "summary": summary,
            "categories": [{"category": name, **_summary(row for row in entries if row.category == name)} for name in _CATEGORIES],
            "residues": [{"kind": kind, **_summary(row for row in entries if row.kind == kind)} for kind in ("obsolete_pickle", "catalog_staging", "catalog_snapshot")],
            "metadata_size_peers": _metadata_peers(entries),
            "http_receipts": _http_report(entries, timestamp),
            "budget": _budget(summary["retained"], scan_errors, max_files, max_disk_bytes),
            "scan_errors": scan_errors, "reason_codes": REASONS}
    return serialize_envelope(payload, _obligations(payload))


def _metadata_peers(entries):
    duplicates: dict[int, list[Entry]] = defaultdict(list)
    for row in entries:
        if row.kind == "catalog_snapshot":
            duplicates[row.info.st_size].append(row)
    return [{"logical_bytes_each": size, "files": len(rows), "verified_duplicate": False,
             "items": [row.item_id for row in rows]} for size, rows in sorted(duplicates.items()) if len(rows) > 1]


def _http_report(entries, timestamp):
    policy = http_receipt_retention_policy()
    http = [row for row in entries if row.kind == "http_receipt"]
    directories: dict[Path, list[Entry]] = defaultdict(list)
    for row in http:
        directories[row.path.parent].append(row)
    http_over = sum(len(rows) > policy.max_files or any(
        row.info.st_mtime < timestamp - policy.max_age_days * 86400 for row in rows
    ) for rows in directories.values())
    return {**_summary(http), "max_files_per_directory": policy.max_files,
                                "max_age_days": policy.max_age_days, "sweep_interval": HTTP_RECEIPT_SWEEP_INTERVAL,
                                "hard_limit": False, "byte_quota": None, "retained_over_budget_directories": http_over,
                                "exceptions": ["current_directory_only", "after_successful_write_only", "live_pid_exempt", "lock_or_unlink_failure_best_effort", "no_global_or_byte_quota"],
            "cache_prune_policy": "retain_without_audit_release_proof"}


def prune(*, execute: bool = False, **options: Any) -> dict[str, Any]:
    if options.get("roots") is not None:
        options["roots"] = tuple(options["roots"])
    report, entries = inventory(**options)
    decisions = []
    deleted: list[Entry] = []
    # Re-inventory immediately before mutation: changed protection markers or
    # candidates invalidate the preview instead of broadening the deletion set.
    current = {}
    if execute:
        _, refreshed = inventory(**options)
        current = {row.path: row for row in refreshed}
    for row in entries:
        decision = row.public()
        if execute and row.reclaimable:
            if _delete_candidate(row, current.get(row.path), options):
                decision["action"] = "deleted"
                deleted.append(row)
            else:
                decision.update(action="retain", reason_code="FILE_CHANGED_OR_BUSY")
        decisions.append(decision)
    report.update(mode="execute" if execute else "dry-run", decisions=decisions,
                  deleted=_measure(deleted), network_called=False)
    if execute:
        after, _ = inventory(**options)
        report["after"] = after["summary"]
        report["budget"] = _budget(after["summary"], after["scan_errors"],
                                   options.get("max_files"), options.get("max_disk_bytes"))
        if after["status"] != "ok" or any(row["reason_code"] == "FILE_CHANGED_OR_BUSY" for row in decisions):
            report["status"] = "partial"
    report.pop("obligations")
    return serialize_envelope(report, _obligations(report))


def _delete_candidate(row: Entry, fresh: Entry | None, options: dict) -> bool:
    try:
        if fresh is None or not fresh.reclaimable or identity(fresh.info) != identity(row.info):
            return False
        _, allowed = _decision(row.path, row.category, row.kind, row.info,
                               time.time() if options.get("now") is None else options["now"],
                               options.get("min_age_days", 7))
        if not allowed:
            return False
        unlink_unchanged(row.root, row.path, row.info)
    except OSError:
        return False
    return True


def inventory_error() -> dict[str, Any]:
    payload = {"schema_version": "gravity.cache-inventory.v1", "status": "error",
               "reason_code": "CACHE_INVENTORY_FAILED", "network_called": False}
    return serialize_envelope(payload, _obligations(payload))


def _obligations(report: dict) -> EnvelopeObligations:
    ok = report["status"] == "ok"
    code = "CACHE_SCAN_COMPLETE" if ok else "CACHE_SCAN_INCOMPLETE"
    unknown_allocation = report.get("summary", {}).get("allocation_unknown_files", 0)
    execution = {"ok": ExecutionState.COMPLETE, "partial": ExecutionState.PARTIAL,
                 "error": ExecutionState.FAILED}[report["status"]]
    mutation = MutationState.NOT_APPLICABLE
    if report.get("mode") == "dry-run":
        mutation = MutationState.NOT_ATTEMPTED
    elif report.get("mode") == "execute":
        mutation = MutationState.CONFIRMED if ok else MutationState.UNCERTAIN
    diagnostics = DiagnosticEvidence(DiagnosticState.NONE) if ok else DiagnosticEvidence(
        DiagnosticState.AVAILABLE, (code,), code, DiagnosticCategory.LOCAL, True
    )
    return EnvelopeObligations(
        ExecutionStatus(execution, code),
        DataCompleteness(CompletenessState.COMPLETE if ok and not unknown_allocation else CompletenessState.UNKNOWN,
                         code, {"scope": "enumerated_cache_roots_only", "allocation_unknown_files": unknown_allocation}),
        SemanticValidity(SemanticState.NOT_APPLICABLE, ()),
        diagnostics, MutationCertainty(mutation, "CACHE_" + mutation.value.upper()),
    )
