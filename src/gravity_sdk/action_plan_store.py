"""Principal-scoped immutable state and one-time claims for Action Plans."""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import stat
import threading
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .errors import InputValidationError
from .mutation_lifecycle import mutation_digest


PRIVATE_SCHEMA_VERSION = "gravity.action-plan-private.v1"
CLAIM_SCHEMA_VERSION = "gravity.action-plan-claim.v1"
MAX_ARTIFACT_BYTES = 64 * 1024
MAX_STORED_PLANS = 64
MAX_STORE_BYTES = 4 * 1024 * 1024

_HEX_32 = re.compile(r"^[0-9a-f]{32}$")
_HEX_64 = re.compile(r"^[0-9a-f]{64}$")
_REFERENCE = re.compile(r"^act1_([0-9a-f]{32})_([0-9a-f]{32})$")
_FIELDS = frozenset(
    {
        "schema_version",
        "nonce",
        "action_kind",
        "connector_id",
        "connector_version",
        "created_at",
        "expires_at",
        "request_digest",
        "authorization_digest",
        "principal_digest",
        "target_digest",
        "preimage_digest",
        "ownership_digest",
        "contract_fingerprint",
        "managed_fields",
        "preview_fingerprint",
        "artifact_digest",
    }
)


class ActionPlanStore:
    def __init__(self, root: Path, scope_key: str) -> None:
        self._root = root
        self._scope_key = scope_key
        self._lock = threading.Lock()

    def allocate(self) -> tuple[str, str]:
        self._ensure_root()
        for _attempt in range(8):
            nonce = secrets.token_hex(16)
            if not self._path(nonce).exists() and not self._claim_path(nonce).exists():
                return nonce, reference_for(nonce, self._scope_key)
        _fail("ACTION_STORE_BOUND_EXCEEDED")

    def create(
        self, nonce: str, values: Mapping[str, Any], *, now: datetime
    ) -> dict[str, Any]:
        with self._lock:
            self._ensure_root()
            self._purge_expired(now)
            artifact = {
                **dict(values),
                "schema_version": PRIVATE_SCHEMA_VERSION,
                "nonce": nonce,
            }
            artifact["artifact_digest"] = _artifact_digest(artifact)
            payload = _canonical_bytes(artifact) + b"\n"
            if len(payload) > MAX_ARTIFACT_BYTES:
                _fail("ACTION_STORE_BOUND_EXCEEDED")
            self._ensure_capacity(len(payload))
            _atomic_create(self._path(nonce), payload, "ACTION_PLAN_COLLISION")
            return artifact

    def load(self, plan_id: Any, *, now: datetime) -> dict[str, Any]:
        nonce = reference_nonce(plan_id, self._scope_key)
        self._ensure_root(existing=True)
        path = self._path(nonce)
        if not path.exists():
            _fail("ACTION_PLAN_NOT_FOUND")
        artifact = _read_artifact(path, nonce)
        if _parse_timestamp(artifact["expires_at"]) <= now:
            _fail("ACTION_PLAN_EXPIRED")
        return artifact

    def claim(
        self, plan_id: Any, artifact: Mapping[str, Any], *, now: datetime
    ) -> None:
        nonce = reference_nonce(plan_id, self._scope_key)
        claim = {
            "schema_version": CLAIM_SCHEMA_VERSION,
            "plan_digest": artifact["artifact_digest"],
            "claimed_at": timestamp(now),
        }
        _atomic_create(
            self._claim_path(nonce),
            _canonical_bytes(claim) + b"\n",
            "ACTION_PLAN_CONSUMED",
        )
        _atomic_create(
            self._field_claim_path(artifact),
            _canonical_bytes(claim) + b"\n",
            "ACTION_FIELD_OWNERSHIP_CONFLICT",
        )

    def _ensure_root(self, *, existing: bool = False) -> None:
        if self._root.is_symlink():
            _fail("ACTION_PLAN_TAMPERED")
        if self._root.exists():
            if not self._root.is_dir():
                _fail("ACTION_PLAN_TAMPERED")
            return
        if existing:
            _fail("ACTION_PLAN_NOT_FOUND")
        self._root.mkdir(parents=True, exist_ok=False)

    def _purge_expired(self, now: datetime) -> None:
        for path in self._root.glob("*.json"):
            if not _HEX_32.fullmatch(path.stem):
                continue
            try:
                artifact = _read_artifact(path, path.stem)
                expired = _parse_timestamp(artifact["expires_at"]) <= now
            except (InputValidationError, OSError, ValueError):
                expired = False
            if expired:
                path.unlink(missing_ok=True)
                self._claim_path(path.stem).unlink(missing_ok=True)
                self._field_claim_path(artifact).unlink(missing_ok=True)

    def _ensure_capacity(self, incoming: int) -> None:
        paths = [*self._root.glob("*.json"), *self._root.glob("*.claim")]
        total = sum(path.stat().st_size for path in paths if path.is_file())
        plans = list(self._root.glob("*.json"))
        if len(plans) >= MAX_STORED_PLANS or total + incoming > MAX_STORE_BYTES:
            _fail("ACTION_STORE_BOUND_EXCEEDED")

    def _path(self, nonce: str) -> Path:
        return self._root / f"{nonce}.json"

    def _claim_path(self, nonce: str) -> Path:
        return self._root / f"{nonce}.claim"

    def _field_claim_path(self, artifact: Mapping[str, Any]) -> Path:
        identity = mutation_digest(
            {
                "target_digest": artifact["target_digest"],
                "preimage_digest": artifact["preimage_digest"],
                "managed_fields": artifact["managed_fields"],
            }
        )
        return self._root / f"{identity}.fields.claim"


def bound_scope_key(workspace: Any, scope_bound: bool) -> str:
    state_root = getattr(workspace, "state_root", None)
    scope = Path(state_root).name if state_root is not None else ""
    if not scope_bound or not _HEX_32.fullmatch(scope):
        _fail("ACTION_SCOPE_UNBOUND", field="workspace")
    return scope


def reference_for(nonce: str, scope_key: str) -> str:
    tag = hashlib.sha256(
        f"gravity-action-reference-v1\0{scope_key}\0{nonce}".encode("ascii")
    ).hexdigest()[:32]
    return f"act1_{nonce}_{tag}"


def reference_nonce(value: Any, scope_key: str) -> str:
    match = _REFERENCE.fullmatch(value) if isinstance(value, str) else None
    if match is None:
        _fail("ACTION_PLAN_REFERENCE_INVALID")
    nonce, tag = match.groups()
    if reference_for(nonce, scope_key).rsplit("_", 1)[1] != tag:
        _fail("ACTION_IDENTITY_CHANGED")
    return nonce


def timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def _read_artifact(path: Path, nonce: str) -> dict[str, Any]:
    try:
        info = path.lstat()
        if (
            not stat.S_ISREG(info.st_mode)
            or path.is_symlink()
            or info.st_nlink != 1
            or info.st_size <= 0
            or info.st_size > MAX_ARTIFACT_BYTES
        ):
            _fail("ACTION_PLAN_TAMPERED")
        value = json.loads(
            path.read_bytes().decode("utf-8"), object_pairs_hook=_unique_object
        )
        _validate_artifact(value, nonce)
        return value
    except InputValidationError:
        raise
    except (OSError, UnicodeError, ValueError, TypeError):
        _fail("ACTION_PLAN_TAMPERED")


def _validate_artifact(value: Any, nonce: str) -> None:
    if not isinstance(value, dict) or set(value) != _FIELDS:
        _fail("ACTION_PLAN_TAMPERED")
    if (
        value.get("schema_version") != PRIVATE_SCHEMA_VERSION
        or value.get("nonce") != nonce
        or value.get("action_kind") != "segment.update_metadata"
        or value.get("connector_id") != "gravity.segment-metadata-update"
        or value.get("connector_version") != 1
        or value.get("managed_fields") != ["segment_name", "segment_remark"]
    ):
        _fail("ACTION_PLAN_TAMPERED")
    for field in (
        "request_digest",
        "authorization_digest",
        "principal_digest",
        "target_digest",
        "preimage_digest",
        "ownership_digest",
        "contract_fingerprint",
        "preview_fingerprint",
        "artifact_digest",
    ):
        if not isinstance(value.get(field), str) or not _HEX_64.fullmatch(value[field]):
            _fail("ACTION_PLAN_TAMPERED")
    created = _parse_timestamp(value.get("created_at"))
    expires = _parse_timestamp(value.get("expires_at"))
    if expires <= created or _artifact_digest(value) != value["artifact_digest"]:
        _fail("ACTION_PLAN_TAMPERED")


def _parse_timestamp(value: Any) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError("invalid timestamp")
    parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    if parsed.tzinfo != timezone.utc or timestamp(parsed) != value:
        raise ValueError("invalid timestamp")
    return parsed


def _artifact_digest(value: Mapping[str, Any]) -> str:
    selected = {key: item for key, item in value.items() if key != "artifact_digest"}
    return mutation_digest(selected)


def _atomic_create(path: Path, payload: bytes, collision_code: str) -> None:
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        _fail(collision_code)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        path.chmod(0o600)
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def _canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError):
        _fail("ACTION_PLAN_TAMPERED")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _fail(code: str, *, field: str = "plan_id") -> None:
    raise InputValidationError(
        f"Action Plan stopped before mutation ({code}).",
        field=field,
        code=code,
        next_action="Do not retry this plan; inspect current state and preview a new explicitly authorized Action Plan.",
    )


__all__ = [
    "ActionPlanStore",
    "CLAIM_SCHEMA_VERSION",
    "PRIVATE_SCHEMA_VERSION",
    "bound_scope_key",
    "reference_for",
    "timestamp",
]
