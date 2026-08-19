"""Durable FieldPolicy metadata snapshots, scoped by env fingerprint.

Snapshots are JSON, not pickle. The payload is an upstream metadata
envelope that arrived as JSON in the first place, so nothing is lost --
and a cache file is attacker-reachable in a way the process is not:
``pickle.loads`` executes whatever the file says before any schema check
could reject it. JSON parses to plain containers and cannot execute.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from pathlib import Path
from typing import Any

from .runtime_scope import field_policy_cache_dir


DISK_SCHEMA = "gravity.field-policy-cache.v1"
_DATACLASS_TAG = "__read_result__"


def _encode(value: Any) -> Any:
    """Render the cached ReadResult as plain JSON containers."""

    if is_dataclass(value) and not isinstance(value, type):
        return {
            _DATACLASS_TAG: type(value).__name__,
            "fields": {item.name: getattr(value, item.name) for item in fields(value)},
        }
    return value


def _decode(value: Any) -> Any:
    if not isinstance(value, Mapping) or _DATACLASS_TAG not in value:
        return value
    from .models import ReadResult

    if value[_DATACLASS_TAG] != ReadResult.__name__:
        raise ValueError("unknown cached dataclass")
    stored = value.get("fields")
    if not isinstance(stored, Mapping):
        raise ValueError("cached dataclass has no fields")
    # JSON has no tuples. Restore them from the annotations rather than a
    # hand-kept name list, so a new tuple field on ReadResult is covered
    # the day it is added.
    rebuilt = {
        item.name: (
            tuple(stored[item.name])
            if str(item.type).startswith("tuple[") and isinstance(stored[item.name], list)
            else stored[item.name]
        )
        for item in fields(ReadResult)
        if item.name in stored
    }
    return ReadResult(**rebuilt)


def persist_dir(scope: str) -> Path:
    return field_policy_cache_dir(scope)


def read_snapshot(
    persist: bool, directory: Path, key: tuple[str, str], ttl_seconds: float, now: float
) -> tuple[float, Any] | None:
    if not persist:
        return None
    path = _path(directory, key)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return None
    if not _usable(payload, key):
        return None
    try:
        value = _decode(payload.get("value"))
    except (ValueError, TypeError):
        _unlink(path)
        return None
    written = payload["written_at"]
    age = now - float(written)
    if age >= ttl_seconds:
        _unlink(path)
        return None
    return ttl_seconds - age, value


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
        "value": _encode(value),
    }
    staging: str | None = None
    try:
        # Serialize before touching the filesystem: a value the upstream
        # envelope cannot express as JSON simply stays memory-only.
        encoded = json.dumps(payload, ensure_ascii=False)
        directory.mkdir(parents=True, exist_ok=True)
        handle, staging = tempfile.mkstemp(prefix=".tmp-", suffix=".part", dir=directory)
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(staging, _path(directory, key))
        staging = None
    except (OSError, TypeError, ValueError):
        if staging is not None:
            _unlink(Path(staging))


def clear_snapshots(persist: bool, directory: Path) -> None:
    if not persist or not directory.is_dir():
        return
    for path in directory.glob("*.json"):
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
    return directory / f"{digest}.json"


def _unlink(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass
