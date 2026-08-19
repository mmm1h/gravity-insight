"""Process-local cache for non-business Gravity metadata, with optional disk."""

from __future__ import annotations

import copy
import json
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping

from .cache_disk import clear_snapshots, persist_dir, read_snapshot, write_snapshot
from .models import OperationSpec


DEFAULT_METADATA_TTL_SECONDS = 600.0
_MISS = object()


def is_metadata_operation(operation: OperationSpec | Mapping[str, Any]) -> bool:
    """Return whether an operation is safe for the metadata-only cache."""

    if isinstance(operation, OperationSpec):
        domain = operation.domain
        resource = operation.resource
        action = operation.action
    else:
        domain = str(operation.get("domain", ""))
        resource = str(operation.get("resource", ""))
        action = str(operation.get("action", ""))
    normalized_resource = resource.casefold().replace("-", "_")
    metadata_resources = {
        "business_metric",
        "custom_metric",
        "dimension",
        "dimensions",
        "event",
        "event_info",
        "event_property",
        "media_enum",
        "metric",
        "metric_tag",
        "metric_tag_category",
        "preset_template",
        "report_group",
        "schema",
        "template",
        "user_property",
    }
    return (
        action.casefold() in {"get", "list", "metadata", "schema", "tree"}
        and (domain.casefold() == "metadata" or normalized_resource in metadata_resources)
    )


@dataclass(frozen=True)
class _Entry:
    expires_at: float
    value: Any


class MetadataCache:
    """Thread-safe ten-minute TTL cache with per-key request coalescing.

    The client supplies the exact operation allowlist derived from its immutable
    registry. Calls for every other operation bypass storage, so business report
    results cannot accidentally enter this cache.
    """

    def __init__(
        self,
        metadata_operation_ids: Iterable[str],
        *,
        ttl_seconds: float = DEFAULT_METADATA_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        isolation_key: str = "",
        persist: bool = False,
        persist_scope: str = "",
        wall_clock: Callable[[], float] = time.time,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("metadata cache TTL must be positive")
        operation_ids = frozenset(str(item) for item in metadata_operation_ids if str(item))
        self._operation_ids = operation_ids
        self._ttl_seconds = float(ttl_seconds)
        self._clock = clock
        self._isolation_key = str(isolation_key)
        self._persist = bool(persist)
        self._persist_scope = str(persist_scope)
        self._persist_dir = persist_dir(self._persist_scope)
        self._wall_clock = wall_clock
        self._condition = threading.Condition(threading.RLock())
        self._entries: dict[tuple[str, str], _Entry] = {}
        self._inflight: set[tuple[str, str]] = set()
        self._hits = 0
        self._misses = 0
        self._bypassed = 0
        self._bypass = False

    @property
    def ttl_seconds(self) -> float:
        return self._ttl_seconds

    def is_cacheable(self, operation_id: str) -> bool:
        return operation_id in self._operation_ids

    def set_bypass(self, enabled: bool) -> None:
        """Skip storage for later loads; existing snapshots stay until `clear()`."""

        with self._condition:
            self._bypass = bool(enabled)

    def get_or_load(
        self,
        operation_id: str,
        inputs: Mapping[str, Any] | None,
        loader: Callable[[], Any],
        *,
        isolation_key: str | None = None,
    ) -> Any:
        if not self.is_cacheable(operation_id):
            return loader()
        if self._note_bypass():
            return loader()
        scope = self._isolation_key if isolation_key is None else str(isolation_key)
        key = _cache_key(operation_id, inputs or {}, scope)
        if key is None:
            return loader()
        remembered = self._await_or_claim(key)
        if remembered is not _MISS:
            return remembered
        try:
            stored = copy.deepcopy(loader())
        except BaseException:
            self._finish(key, None)
            raise
        return self._finish(key, stored)

    def clear(self) -> None:
        with self._condition:
            self._entries.clear()
            clear_snapshots(self._persist, self._persist_dir)

    def stats(self) -> dict[str, int | float]:
        with self._condition:
            now = self._clock()
            expired = [key for key, entry in self._entries.items() if entry.expires_at <= now]
            for key in expired:
                self._entries.pop(key, None)
            return {
                "ttl_seconds": self._ttl_seconds,
                "entries": len(self._entries),
                "hits": self._hits,
                "misses": self._misses,
                "bypassed": self._bypassed,
            }

    def _note_bypass(self) -> bool:
        with self._condition:
            if self._bypass:
                self._bypassed += 1
                return True
        return False

    def _await_or_claim(self, key: tuple[str, str]) -> Any:
        with self._condition:
            while True:
                now = self._clock()
                entry = self._entries.get(key)
                if entry is not None and entry.expires_at > now:
                    self._hits += 1
                    return copy.deepcopy(entry.value)
                if entry is not None:
                    self._entries.pop(key, None)
                disk = read_snapshot(
                    self._persist, self._persist_dir, key, self._ttl_seconds, self._wall_clock()
                )
                if disk is not None:
                    remaining, value = disk
                    self._entries[key] = _Entry(self._clock() + remaining, value)
                    self._hits += 1
                    return copy.deepcopy(value)
                if key not in self._inflight:
                    self._inflight.add(key)
                    self._misses += 1
                    return _MISS
                self._condition.wait()

    def _finish(self, key: tuple[str, str], stored: Any | None) -> Any:
        with self._condition:
            if stored is not None:
                self._entries[key] = _Entry(self._clock() + self._ttl_seconds, stored)
                write_snapshot(
                    self._persist,
                    self._persist_dir,
                    key,
                    stored,
                    self._ttl_seconds,
                    self._wall_clock(),
                )
            self._inflight.discard(key)
            self._condition.notify_all()
        return copy.deepcopy(stored) if stored is not None else None


def persisted_metadata_cache(registry: Any, isolation_key: str, isolated: bool) -> MetadataCache:
    """Persist FieldPolicy snapshots; default env stays on the unscoped path."""

    return MetadataCache(
        (
            operation.operation_id
            for operation in registry.all()
            if is_metadata_operation(operation)
        ),
        isolation_key=isolation_key,
        persist=True,
        persist_scope=isolation_key if isolated else "",
    )


def _cache_key(
    operation_id: str, inputs: Mapping[str, Any], isolation_key: str = ""
) -> tuple[str, str] | None:
    try:
        normalized = _normalize(inputs)
        encoded = json.dumps(
            normalized,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError, OverflowError):
        return None
    scoped_id = f"{isolation_key}:{operation_id}" if isolation_key else operation_id
    return scoped_id, encoded


def _normalize(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _normalize(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_normalize(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError("metadata cache inputs must be JSON-compatible")


def _client_cache(client: Any) -> MetadataCache | None:
    target = getattr(client, "insight", None) or getattr(client, "_client", None) or client
    cache = getattr(target, "_metadata_cache", None)
    return cache if isinstance(cache, MetadataCache) else None


def metadata_cache_stats(client: Any) -> dict[str, int | float]:
    """Return process-local hit/miss/bypass counters; never includes snapshot values."""

    cache = _client_cache(client)
    if cache is None:
        raise TypeError("client does not expose a process-local metadata cache")
    return cache.stats()


def clear_metadata_cache(client: Any) -> dict[str, int | float]:
    """Drop stored snapshots so the next metadata load hits upstream."""

    cache = _client_cache(client)
    if cache is None:
        raise TypeError("client does not expose a process-local metadata cache")
    cache.clear()
    return cache.stats()


def bypass_metadata_cache(client: Any, enabled: bool = True) -> dict[str, int | float]:
    """Skip later snapshot reuse without changing FieldPolicy or contracts."""

    cache = _client_cache(client)
    if cache is None:
        raise TypeError("client does not expose a process-local metadata cache")
    cache.set_bypass(enabled)
    return cache.stats()
