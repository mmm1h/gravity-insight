"""Durable FieldPolicy metadata snapshots, scoped by env fingerprint."""

from __future__ import annotations

import hashlib
import os
import pickle
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .runtime_scope import field_policy_cache_dir


DISK_SCHEMA = "gravity.field-policy-cache.v1"


def persist_dir(scope: str) -> Path:
    return field_policy_cache_dir(scope)


def read_snapshot(
    persist: bool, directory: Path, key: tuple[str, str], ttl_seconds: float, now: float
) -> tuple[float, Any] | None:
    if not persist:
        return None
    path = _path(directory, key)
    try:
        payload = pickle.loads(path.read_bytes())
    except (OSError, pickle.UnpicklingError, EOFError, AttributeError, ValueError):
        return None
    if not _usable(payload, key):
        return None
    written = payload["written_at"]
    age = now - float(written)
    if age >= ttl_seconds:
        _unlink(path)
        return None
    return ttl_seconds - age, payload.get("value")


def write_snapshot(
    persist: bool,
    directory: Path,
    key: tuple[str, str],
    value: Any,
    ttl_seconds: float,
    now: float,
) -> None:
    if not persist:
        return
    payload = {
        "schema": DISK_SCHEMA,
        "key": list(key),
        "written_at": now,
        "ttl_seconds": ttl_seconds,
        "value": value,
    }
    staging: str | None = None
    try:
        directory.mkdir(parents=True, exist_ok=True)
        handle, staging = tempfile.mkstemp(prefix=".tmp-", suffix=".part", dir=directory)
        with os.fdopen(handle, "wb") as stream:
            pickle.dump(payload, stream, protocol=pickle.HIGHEST_PROTOCOL)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(staging, _path(directory, key))
        staging = None
    except (OSError, pickle.PicklingError, TypeError):
        if staging is not None:
            _unlink(Path(staging))


def clear_snapshots(persist: bool, directory: Path) -> None:
    if not persist or not directory.is_dir():
        return
    for path in directory.glob("*.pkl"):
        _unlink(path)


def _usable(payload: Any, key: tuple[str, str]) -> bool:
    if not isinstance(payload, Mapping):
        return False
    if payload.get("schema") != DISK_SCHEMA:
        return False
    if tuple(payload.get("key") or ()) != key:
        return False
    return isinstance(payload.get("written_at"), (int, float))


def _path(directory: Path, key: tuple[str, str]) -> Path:
    digest = hashlib.sha256(f"{key[0]}\0{key[1]}".encode("utf-8")).hexdigest()
    return directory / f"{digest}.pkl"


def _unlink(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass
