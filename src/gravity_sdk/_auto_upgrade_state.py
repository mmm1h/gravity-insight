"""Lease and durable-state owner for startup update checks."""

from __future__ import annotations

import json
import hashlib
import os
import re
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


UPDATE_CHECK_LEASE = timedelta(minutes=1)
UPDATE_STATE_SCHEMA_VERSION = 3
UPGRADE_ATTEMPT_SCHEMA_VERSION = 1
_VERSION_PATTERN = re.compile(
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$"
)
_STATE_FIELDS = frozenset(
    {
        "schema_version",
        "successful_checked_at",
        "etag",
        "latest_version",
    }
)
_LEGACY_STATE_FIELDS = _STATE_FIELDS | frozenset(
    {"attempted_version", "attempted_at"}
)
_ATTEMPT_FIELDS = frozenset(
    {"schema_version", "attempted_version", "attempted_at", "status"}
)
_ATTEMPT_STATUSES = frozenset({"started", "failed", "verified"})
_LEASE_FIELDS = frozenset({"schema_version", "lease_id", "claimed_at"})


class UpdateStateBusy(Exception):
    pass


class UpdateStateError(Exception):
    pass


@contextmanager
def hold_update_lease(path: Path, now: datetime) -> Iterator[None]:
    """Hold a crash-recoverable lease without locking the replace target."""

    with _hold_lease_guard(path):
        lease_id = _acquire_lease(path, now)
        try:
            yield
        finally:
            _release_lease(path, lease_id)


def read_update_state(path: Path) -> dict[str, Any] | None:
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise UpdateStateError("update-check state is unreadable") from exc
    try:
        value = json.loads(raw.decode("utf-8"))
        return _validated_state(value)
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise UpdateStateError("update-check state is unreadable") from exc


def write_update_state(path: Path, state: Mapping[str, Any]) -> None:
    """Publish state with file durability followed by atomic replacement."""

    _write_state_file(path, _validated_state(dict(state)))


def read_upgrade_attempt(path: Path) -> dict[str, Any] | None:
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise UpdateStateError("upgrade-attempt state is unreadable") from exc
    try:
        value = json.loads(raw.decode("utf-8"))
        return _validated_attempt(value)
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise UpdateStateError("upgrade-attempt state is unreadable") from exc


def write_upgrade_attempt(path: Path, state: Mapping[str, Any]) -> None:
    _write_state_file(path, _validated_attempt(dict(state)))


def _write_state_file(path: Path, state: Mapping[str, Any]) -> None:
    payload = _render_json(state)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def build_update_state(
    *,
    successful_checked_at: datetime | None,
    etag: str | None,
    latest_version: str | None,
) -> dict[str, Any]:
    return {
        "schema_version": UPDATE_STATE_SCHEMA_VERSION,
        "successful_checked_at": (
            format_timestamp(successful_checked_at)
            if successful_checked_at is not None
            else None
        ),
        "etag": etag,
        "latest_version": latest_version,
    }


def build_upgrade_attempt(
    *, attempted_version: str, attempted_at: datetime, status: str
) -> dict[str, Any]:
    return {
        "schema_version": UPGRADE_ATTEMPT_SCHEMA_VERSION,
        "attempted_version": attempted_version,
        "attempted_at": format_timestamp(attempted_at),
        "status": status,
    }


def recent_incomplete_upgrade(
    path: Path, now: datetime, interval: timedelta
) -> dict[str, Any] | None:
    state = read_upgrade_attempt(path)
    if state is None or state.get("status") == "verified":
        return None
    attempted_at = optional_timestamp(state.get("attempted_at"))
    return state if attempted_at is None or now - attempted_at < interval else None


def record_upgrade_attempt(
    path: Path, version: str, now: datetime, interval: timedelta
) -> str:
    with hold_update_lease(path, now):
        state = read_upgrade_attempt(path)
        attempted_at = optional_timestamp(state.get("attempted_at")) if state else None
        if (
            state is not None
            and state.get("status") != "verified"
            and attempted_at is not None
            and now - attempted_at < interval
        ):
            return "suppressed"
        write_upgrade_attempt(
            path,
            build_upgrade_attempt(
                attempted_version=version,
                attempted_at=now,
                status="started",
            ),
        )
    return "due"


def mark_upgrade_attempt(
    path: Path, version: str, now: datetime, status: str
) -> None:
    with hold_update_lease(path, now):
        state = read_upgrade_attempt(path)
        if state is None or state.get("attempted_version") != version:
            raise UpdateStateError("the active upgrade attempt is missing")
        write_upgrade_attempt(
            path,
            build_upgrade_attempt(
                attempted_version=version,
                attempted_at=optional_timestamp(state.get("attempted_at")) or now,
                status=status,
            ),
        )


def runtime_scope_id(executable: str, package_root: Path) -> str:
    identity = "\0".join(
        (
            os.path.normcase(str(Path(executable).resolve())),
            os.path.normcase(str(package_root.resolve())),
        )
    )
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]


def success_is_recent(
    state: Mapping[str, Any], now: datetime, interval: timedelta
) -> bool:
    successful = optional_timestamp(state.get("successful_checked_at"))
    return successful is not None and now - successful < interval


def optional_text(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def optional_timestamp(value: Any) -> datetime | None:
    return parse_timestamp(value) if isinstance(value, str) else None


def parse_timestamp(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("update-check timestamp is invalid")
    return utc(datetime.fromisoformat(value.replace("Z", "+00:00")))


def format_timestamp(value: datetime) -> str:
    return utc(value).isoformat(timespec="seconds").replace("+00:00", "Z")


def utc(value: datetime | None) -> datetime:
    selected = datetime.now(timezone.utc) if value is None else value
    if selected.tzinfo is None:
        raise ValueError("update-check time must include a timezone")
    return selected.astimezone(timezone.utc)


def valid_etag(value: str) -> bool:
    return bool(value) and len(value) <= 512 and "\r" not in value and "\n" not in value


def version_tuple(version: str) -> tuple[int, int, int] | None:
    matched = _VERSION_PATTERN.fullmatch(version)
    return tuple(int(part) for part in matched.groups()) if matched else None  # type: ignore[return-value]


def is_newer(available_version: str, current_version: str) -> bool:
    available = version_tuple(available_version)
    current = version_tuple(current_version)
    return available is not None and current is not None and available > current


def _validated_state(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("update-check state fields are invalid")
    if value.get("schema_version") == 2:
        return _migrate_legacy_state(value)
    if set(value) != _STATE_FIELDS:
        raise ValueError("update-check state fields are invalid")
    if value.get("schema_version") != UPDATE_STATE_SCHEMA_VERSION:
        raise ValueError("update-check state schema is invalid")
    _validate_optional_types(value, ("successful_checked_at", "etag", "latest_version"))
    _validate_state_relationships(value)
    return value


def _migrate_legacy_state(value: dict[str, Any]) -> dict[str, Any]:
    if set(value) != _LEGACY_STATE_FIELDS:
        raise ValueError("update-check state fields are invalid")
    _validate_optional_types(
        value,
        (
            "successful_checked_at",
            "etag",
            "latest_version",
            "attempted_version",
            "attempted_at",
        ),
    )
    successful = optional_timestamp(value.get("successful_checked_at"))
    attempted = optional_timestamp(value.get("attempted_at"))
    if (
        value.get("latest_version") is not None or value.get("etag") is not None
    ) and successful is None:
        raise ValueError("update-check success values lack a timestamp")
    if (value.get("attempted_version") is None) != (attempted is None):
        raise ValueError("update-attempt values are incomplete")
    _validate_versions_and_etag(value)
    latest = optional_text(value.get("latest_version"))
    if latest is None:
        return build_update_state(
            successful_checked_at=None,
            etag=None,
            latest_version=None,
        )
    return build_update_state(
        successful_checked_at=successful,
        etag=optional_text(value.get("etag")),
        latest_version=latest,
    )


def _validate_optional_types(
    value: Mapping[str, Any], fields: tuple[str, ...]
) -> None:
    for field in fields:
        if value.get(field) is not None and not isinstance(value.get(field), str):
            raise ValueError("update-check state values are invalid")


def _validate_state_relationships(value: Mapping[str, Any]) -> None:
    successful = optional_timestamp(value.get("successful_checked_at"))
    if (value.get("latest_version") is None) != (successful is None):
        raise ValueError("update-check success values are incomplete")
    if value.get("etag") is not None and successful is None:
        raise ValueError("update-check ETag lacks a timestamp")
    _validate_versions_and_etag(value)


def _validate_versions_and_etag(value: Mapping[str, Any]) -> None:
    versions = tuple(
        value.get(field)
        for field in ("latest_version", "attempted_version")
        if field in value
    )
    if any(version is not None and version_tuple(version) is None for version in versions):
        raise ValueError("update-check version is invalid")
    etag = value.get("etag")
    if etag is not None and not valid_etag(etag):
        raise ValueError("update-check ETag is invalid")


def _validated_attempt(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != _ATTEMPT_FIELDS:
        raise ValueError("upgrade-attempt state fields are invalid")
    if value.get("schema_version") != UPGRADE_ATTEMPT_SCHEMA_VERSION:
        raise ValueError("upgrade-attempt state schema is invalid")
    attempted_version = value.get("attempted_version")
    if not isinstance(attempted_version, str) or version_tuple(attempted_version) is None:
        raise ValueError("upgrade-attempt version is invalid")
    parse_timestamp(value.get("attempted_at"))
    if value.get("status") not in _ATTEMPT_STATUSES:
        raise ValueError("upgrade-attempt status is invalid")
    return value


@contextmanager
def _hold_lease_guard(path: Path) -> Iterator[None]:
    guard_path = _lease_guard_path(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(guard_path, os.O_RDWR | os.O_CREAT, 0o600)
    except OSError as exc:
        raise UpdateStateError("update-check lease guard is unavailable") from exc
    locked = False
    try:
        if os.fstat(descriptor).st_size == 0:
            os.write(descriptor, b"\0")
            os.fsync(descriptor)
        try:
            _lock_descriptor(descriptor)
            locked = True
        except OSError as exc:
            raise UpdateStateBusy from exc
        yield
    finally:
        if locked:
            try:
                _unlock_descriptor(descriptor)
            except OSError:
                pass
        os.close(descriptor)


def _lock_descriptor(descriptor: int) -> None:
    if os.name == "nt":
        import msvcrt

        os.lseek(descriptor, 0, os.SEEK_SET)
        msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
        return
    import fcntl

    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock_descriptor(descriptor: int) -> None:
    if os.name == "nt":
        import msvcrt

        os.lseek(descriptor, 0, os.SEEK_SET)
        msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
        return
    import fcntl

    fcntl.flock(descriptor, fcntl.LOCK_UN)


def _acquire_lease(path: Path, now: datetime) -> str:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise UpdateStateError("update-check state is not writable") from exc
    lease_path = _lease_path(path)
    for _attempt in range(2):
        lease_id = uuid.uuid4().hex
        try:
            descriptor = os.open(
                lease_path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
        except FileExistsError:
            if not _lease_is_expired(lease_path, now):
                raise UpdateStateBusy
            _remove_stale_lease(lease_path)
            continue
        except OSError as exc:
            raise UpdateStateError("update-check lease is unavailable") from exc
        _write_lease(descriptor, lease_path, lease_id, now)
        return lease_id
    raise UpdateStateBusy


def _write_lease(
    descriptor: int, path: Path, lease_id: str, now: datetime
) -> None:
    payload = {
        "schema_version": UPDATE_STATE_SCHEMA_VERSION,
        "lease_id": lease_id,
        "claimed_at": format_timestamp(now),
    }
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(_render_json(payload))
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        try:
            path.unlink()
        except OSError:
            pass
        raise UpdateStateError("update-check lease is unavailable") from exc


def _remove_stale_lease(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except OSError as exc:
        raise UpdateStateBusy from exc


def _lease_is_expired(path: Path, now: datetime) -> bool:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        claimed_at = _validated_lease_timestamp(value)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
        try:
            claimed_at = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
        except OSError:
            return False
    return now - claimed_at >= UPDATE_CHECK_LEASE


def _validated_lease_timestamp(value: Any) -> datetime:
    if not isinstance(value, dict) or set(value) != _LEASE_FIELDS:
        raise ValueError("update-check lease fields are invalid")
    if value.get("schema_version") != UPDATE_STATE_SCHEMA_VERSION:
        raise ValueError("update-check lease schema is invalid")
    if not isinstance(value.get("lease_id"), str):
        raise ValueError("update-check lease id is invalid")
    return parse_timestamp(value.get("claimed_at"))


def _release_lease(path: Path, lease_id: str) -> None:
    lease_path = _lease_path(path)
    try:
        value = json.loads(lease_path.read_text(encoding="utf-8"))
        if isinstance(value, Mapping) and value.get("lease_id") == lease_id:
            lease_path.unlink()
    except (OSError, UnicodeError, json.JSONDecodeError):
        pass


def _lease_path(path: Path) -> Path:
    return path.with_name(f"{path.name}.lease")


def _lease_guard_path(path: Path) -> Path:
    return path.with_name(f"{path.name}.lease.guard")


def _render_json(value: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(dict(value), sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


__all__ = [
    "UpdateStateBusy",
    "UpdateStateError",
    "build_upgrade_attempt",
    "build_update_state",
    "format_timestamp",
    "hold_update_lease",
    "is_newer",
    "mark_upgrade_attempt",
    "optional_text",
    "optional_timestamp",
    "recent_incomplete_upgrade",
    "read_upgrade_attempt",
    "read_update_state",
    "record_upgrade_attempt",
    "runtime_scope_id",
    "success_is_recent",
    "utc",
    "valid_etag",
    "version_tuple",
    "write_upgrade_attempt",
    "write_update_state",
]
