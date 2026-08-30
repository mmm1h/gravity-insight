"""Cross-platform advisory process locks for controlled operations."""

from __future__ import annotations

import os
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO, Iterator


DEFAULT_LOCK_TIMEOUT_SECONDS = 5.0
DEFAULT_LOCK_POLL_INTERVAL_SECONDS = 0.1
LOCK_RECOVERY_GUIDANCE = (
    "wait for the active command to finish, then retry. If the previous process crashed, "
    "rerun the command to reclaim the retained lock file; do not delete it manually"
)


class FileLockTimeout(TimeoutError):
    """An advisory file lock remained held until its acquisition deadline."""

    def __init__(self, path: Path) -> None:
        self.path = path
        super().__init__(f"timed out waiting for process lock {path}")


@contextmanager
def advisory_file_lock(
    path: Path,
    *,
    owner: str,
    timeout: float = DEFAULT_LOCK_TIMEOUT_SECONDS,
    poll_interval: float = DEFAULT_LOCK_POLL_INTERVAL_SECONDS,
) -> Iterator[None]:
    """Hold one kernel-managed lock while retaining the file as diagnostic metadata."""

    if timeout < 0:
        raise ValueError("lock timeout must not be negative")
    if poll_interval <= 0:
        raise ValueError("lock poll interval must be positive")

    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_BINARY", 0)
    descriptor = os.open(path, flags, 0o600)
    try:
        handle = os.fdopen(descriptor, "r+b", buffering=0)
    except BaseException:
        os.close(descriptor)
        raise

    acquired = False
    try:
        deadline = time.monotonic() + timeout
        while not acquired:
            handle.seek(0)
            try:
                _lock_nonblocking(handle)
                acquired = True
            except OSError as exc:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise FileLockTimeout(path) from exc
                time.sleep(min(poll_interval, remaining))
        _write_owner_metadata(handle, owner)
        yield
    finally:
        if acquired:
            try:
                handle.seek(0)
                _unlock(handle)
            except OSError:
                pass
        try:
            handle.close()
        except OSError:
            pass


def _lock_nonblocking(handle: BinaryIO) -> None:
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    else:  # pragma: no cover - local coverage runs on Windows; POSIX CI exercises this branch
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock(handle: BinaryIO) -> None:
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:  # pragma: no cover - local coverage runs on Windows; POSIX CI exercises this branch
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _write_owner_metadata(handle: BinaryIO, owner: str) -> None:
    safe_owner = " ".join(owner.splitlines()).strip() or "unknown"
    acquired_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    metadata = (
        f"pid={os.getpid()}\n"
        f"acquired_at_utc={acquired_at}\n"
        f"owner={safe_owner}\n"
    ).encode("utf-8")
    handle.seek(0)
    handle.write(metadata)
    handle.truncate()
    handle.flush()
    os.fsync(handle.fileno())
