"""Bounded, non-blocking retention for private HTTP receipt artifacts."""

from __future__ import annotations

import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Mapping


DEFAULT_HTTP_RECEIPT_MAX_FILES = 10_000
DEFAULT_HTTP_RECEIPT_MAX_AGE_DAYS = 7
HTTP_RECEIPT_SWEEP_INTERVAL = 64
_RUN_ID = uuid.uuid4().hex
_LOGGER = logging.getLogger("gravity_sdk")
_WRITE_COUNTS: dict[str, int] = {}
_STATE_LOCK = threading.Lock()


@dataclass(frozen=True)
class HttpReceiptRetentionPolicy:
    max_files: int
    max_age_days: int


def http_receipt_retention_policy(
    environ: Mapping[str, str] | None = None,
) -> HttpReceiptRetentionPolicy:
    """Resolve safe finite defaults when retention overrides are absent or invalid."""

    selected = os.environ if environ is None else environ
    return HttpReceiptRetentionPolicy(
        max_files=_positive_setting(
            selected,
            "GRAVITY_HTTP_RECEIPT_MAX_FILES",
            DEFAULT_HTTP_RECEIPT_MAX_FILES,
        ),
        max_age_days=_positive_setting(
            selected,
            "GRAVITY_HTTP_RECEIPT_MAX_AGE_DAYS",
            DEFAULT_HTTP_RECEIPT_MAX_AGE_DAYS,
        ),
    )


def http_receipt_path(state_root: Path, receipt_id: str) -> Path:
    """Name a receipt with its private run identity; the JSON schema is unchanged."""

    name = f"{os.getpid()}-{_RUN_ID}-{receipt_id}.json"
    return state_root / "receipts" / "http" / name


def prune_http_receipts_after_write(state_root: Path) -> None:
    """Amortize best-effort pruning after the current receipt is durable."""

    directory = state_root / "receipts" / "http"
    key = _root_key(directory)
    with _STATE_LOCK:
        count = _WRITE_COUNTS.get(key, 0) + 1
        _WRITE_COUNTS[key] = count
    if (count - 1) % HTTP_RECEIPT_SWEEP_INTERVAL:
        return
    lease: BinaryIO | None = None
    locked = False
    try:
        lease = open(directory / ".prune.lock", "a+b")
        if not _try_lock(lease):
            return
        locked = True
        _prune(directory, http_receipt_retention_policy(), time.time())
    except Exception:
        _report_retention_failure("gravity_http_receipt_prune_failed")
    finally:
        if lease is not None and locked:
            _unlock(lease)
        if lease is not None:
            lease.close()


def _prune(
    directory: Path,
    policy: HttpReceiptRetentionPolicy,
    now: float,
) -> None:
    receipts: list[tuple[int, str, Path]] = []
    for path in directory.glob("*.json"):
        try:
            receipts.append((path.stat().st_mtime_ns, path.name, path))
        except OSError:
            _report_retention_failure("gravity_http_receipt_prune_failed")
    receipts.sort()
    receipt_processes = {
        pid
        for _, name, _ in receipts
        if (pid := _receipt_process_id(name)) is not None
    }
    live_processes = {pid for pid in receipt_processes if _process_is_alive(pid)}
    candidates = [
        item for item in receipts if _receipt_process_id(item[1]) not in live_processes
    ]
    overflow = max(0, len(receipts) - policy.max_files)
    targets = {path for _, _, path in candidates[:overflow]}
    cutoff_ns = int((now - policy.max_age_days * 86_400) * 1_000_000_000)
    targets.update(path for modified, _, path in candidates if modified < cutoff_ns)
    for path in targets:
        try:
            path.unlink()
        except OSError:
            _report_retention_failure("gravity_http_receipt_prune_failed")


def _receipt_process_id(name: str) -> int | None:
    pid, separator, suffix = name.partition("-")
    run_id, second_separator, _ = suffix.partition("-")
    if not separator or not second_separator or len(run_id) != 32:
        return None
    try:
        return int(pid)
    except ValueError:
        return None


def _positive_setting(
    environ: Mapping[str, str], name: str, default: int
) -> int:
    raw = environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        value = 0
    if value > 0:
        return value
    _report_retention_failure("gravity_http_receipt_retention_config_invalid")
    return default


def _root_key(directory: Path) -> str:
    return os.path.normcase(os.path.abspath(directory))


def _process_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError as error:
        return getattr(error, "winerror", None) not in {87, 1168}
    return True


def _try_lock(handle: BinaryIO) -> bool:
    try:
        handle.seek(0)
        if not handle.read(1):
            handle.write(b"1")
            handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def _unlock(handle: BinaryIO) -> None:
    try:
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass


def _report_retention_failure(event: str) -> None:
    try:
        _LOGGER.warning(event)
    except Exception:
        pass


__all__ = [
    "DEFAULT_HTTP_RECEIPT_MAX_AGE_DAYS",
    "DEFAULT_HTTP_RECEIPT_MAX_FILES",
    "HTTP_RECEIPT_SWEEP_INTERVAL",
    "HttpReceiptRetentionPolicy",
    "http_receipt_path",
    "http_receipt_retention_policy",
    "prune_http_receipts_after_write",
]
