"""Private, expiring preparation records for one host-origin Plan pilot."""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import stat
import threading
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .agent_sources import workspace_catalog_fingerprint
from .errors import InputValidationError
from .host_effects import HOST_PLAN_SCHEMA_VERSION, compile_host_plan
from .host_plan_execution import execute_host_plan
from .plan import MAX_DECLARED_NODES, MAX_WORKERS, PLAN_SCHEMA_VERSION, validate_plan


PAP_SCHEMA_VERSION = "gravity.prepared-analysis-plan.v1"
PAP_SUMMARY_SCHEMA_VERSION = "gravity.prepared-analysis-plan-summary.v1"
DEFAULT_TTL_SECONDS = 900
MAX_TTL_SECONDS = 86_400
MAX_STORED_ARTIFACTS = 64
MAX_ARTIFACT_BYTES = 64 * 1024
MAX_STORE_BYTES = 4 * 1024 * 1024

_STORE_DIRECTORY = "prepared-analysis-plans"
_HEX_32 = re.compile(r"^[0-9a-f]{32}$")
_HEX_64 = re.compile(r"^[0-9a-f]{64}$")
_REFERENCE = re.compile(r"^pap1_([0-9a-f]{32})_([0-9a-f]{32})$")
_ARTIFACT_FIELDS = frozenset(
    {
        "schema_version",
        "source_kind",
        "nonce",
        "created_at",
        "expires_at",
        "host_plan_schema_version",
        "plan_schema_version",
        "node_count",
        "max_workers",
        "plan_binding_sha256",
        "source_binding_sha256",
        "contract_fingerprint",
        "catalog_fingerprint",
        "workspace_catalog_fingerprint",
        "preflight_fingerprint",
        "artifact_sha256",
    }
)


class PreparedAnalysisPlanService:
    """Prepare and execute exact host Plans without persisting their values."""

    def __init__(self, sdk: Any) -> None:
        workspace = sdk.workspace
        self._sdk = sdk
        self._workspace = workspace
        self._scope_key = _bound_scope_key(
            workspace, bool(getattr(sdk, "_runtime_scope_bound", False))
        )
        self._store = _PreparedAnalysisPlanStore(
            Path(workspace.state_root) / _STORE_DIRECTORY,
            self._scope_key,
        )

    def __repr__(self) -> str:
        return "<PreparedAnalysisPlanService private>"

    def prepare_host(
        self,
        host_plan: Mapping[str, Any],
        sources: Mapping[str, Any],
        *,
        max_workers: int = 6,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
    ) -> dict[str, Any]:
        """Preflight an exact read-only host Plan and persist only its bindings."""

        _bounded_integer(max_workers, 1, MAX_WORKERS, "PAP_WORKER_BUDGET_INVALID")
        _bounded_integer(ttl_seconds, 1, MAX_TTL_SECONDS, "PAP_TTL_INVALID")
        now = _utcnow()
        binding = _pilot_binding(
            self._sdk, self._workspace, host_plan, sources, preparing=True
        )
        preflight = execute_host_plan(
            self._sdk,
            host_plan,
            sources,
            max_workers=max_workers,
            dry_run=True,
        )
        artifact = {
            **binding,
            "schema_version": PAP_SCHEMA_VERSION,
            "source_kind": "host_plan",
            "created_at": _timestamp(now),
            "expires_at": _timestamp(now + timedelta(seconds=ttl_seconds)),
            "max_workers": max_workers,
            "preflight_fingerprint": _digest(preflight),
        }
        stored = self._store.create(artifact, now=now)
        return _summary(stored, self._scope_key)

    def execute_host(
        self,
        pap_id: str,
        host_plan: Mapping[str, Any],
        sources: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Validate one PAP and re-enter the existing host-aware Plan owner."""

        artifact = self._store.load(pap_id, now=_utcnow())
        current = _pilot_binding(
            self._sdk, self._workspace, host_plan, sources, preparing=False
        )
        _compare_binding(artifact, current)
        preflight = execute_host_plan(
            self._sdk,
            host_plan,
            sources,
            max_workers=artifact["max_workers"],
            dry_run=True,
        )
        if _digest(preflight) != artifact["preflight_fingerprint"]:
            _fail("PAP_CONTRACT_DRIFT")
        return execute_host_plan(
            self._sdk,
            host_plan,
            sources,
            max_workers=artifact["max_workers"],
        )


class _PreparedAnalysisPlanStore:
    def __init__(self, root: Path, scope_key: str) -> None:
        self._root = root
        self._scope_key = scope_key
        self._lock = threading.Lock()

    def create(
        self, values: Mapping[str, Any], *, now: datetime
    ) -> dict[str, Any]:
        with self._lock:
            self._ensure_root()
            self._purge_expired(now)
            nonce = self._allocate_nonce()
            artifact = {**dict(values), "nonce": nonce}
            artifact["artifact_sha256"] = _artifact_digest(artifact)
            payload = _canonical_bytes(artifact) + b"\n"
            if len(payload) > MAX_ARTIFACT_BYTES:
                _fail("PAP_STORE_BOUND_EXCEEDED")
            self._ensure_capacity(len(payload))
            self._atomic_create(nonce, payload)
            return artifact

    def load(self, pap_id: Any, *, now: datetime) -> dict[str, Any]:
        nonce = _reference_nonce(pap_id, self._scope_key)
        self._ensure_root(existing=True)
        path = self._root / f"{nonce}.json"
        if not path.exists():
            _fail("PAP_NOT_FOUND")
        artifact = _read_artifact(path, nonce)
        if _parse_timestamp(artifact["expires_at"]) <= now:
            _fail("PAP_EXPIRED")
        return artifact

    def _ensure_root(self, *, existing: bool = False) -> None:
        if self._root.is_symlink():
            _fail("PAP_TAMPERED")
        if self._root.exists():
            if not self._root.is_dir():
                _fail("PAP_TAMPERED")
            return
        if existing:
            _fail("PAP_NOT_FOUND")
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

    def _ensure_capacity(self, incoming_bytes: int) -> None:
        paths = list(self._root.glob("*.json"))
        total = sum(path.stat().st_size for path in paths if path.is_file())
        if len(paths) >= MAX_STORED_ARTIFACTS or total + incoming_bytes > MAX_STORE_BYTES:
            _fail("PAP_STORE_BOUND_EXCEEDED")

    def _allocate_nonce(self) -> str:
        for _attempt in range(8):
            nonce = secrets.token_hex(16)
            if not (self._root / f"{nonce}.json").exists():
                return nonce
        _fail("PAP_STORE_BOUND_EXCEEDED")

    def _atomic_create(self, nonce: str, payload: bytes) -> None:
        target = self._root / f"{nonce}.json"
        temporary = self._root / f".{nonce}.{secrets.token_hex(8)}.tmp"
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            if target.exists():
                _fail("PAP_STORE_BOUND_EXCEEDED")
            os.replace(temporary, target)
            target.chmod(0o600)
        finally:
            temporary.unlink(missing_ok=True)


def _pilot_binding(
    sdk: Any,
    workspace: Any,
    host_plan: Mapping[str, Any],
    sources: Mapping[str, Any],
    *,
    preparing: bool,
) -> dict[str, Any]:
    inventory = _stable_inventory(sdk)
    mutation_ids = {
        operation_id
        for operation_id, item in inventory.items()
        if item.get("effect") == "mutation"
    }
    compiled = compile_host_plan(
        host_plan, sources, mutation_operations=mutation_ids
    )
    if compiled.get("effect") != "read":
        _fail("PAP_UNSUPPORTED_PATH")
    validated = validate_plan(compiled["plan"])
    selectors = _pilot_selectors(validated)
    catalog, contracts = _selector_contracts(
        sdk, inventory, selectors, preparing=preparing
    )
    return {
        "host_plan_schema_version": HOST_PLAN_SCHEMA_VERSION,
        "plan_schema_version": PLAN_SCHEMA_VERSION,
        "node_count": len(validated.nodes),
        "plan_binding_sha256": _digest(host_plan),
        "source_binding_sha256": _digest(
            _referenced_sources(host_plan, sources)
        ),
        "contract_fingerprint": _digest(contracts),
        "catalog_fingerprint": _digest(catalog),
        "workspace_catalog_fingerprint": workspace_catalog_fingerprint(workspace),
    }


def _stable_inventory(sdk: Any) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    values = sdk.insight.operations(stability="stable")
    if not isinstance(values, list):
        _fail("PAP_CATALOG_DRIFT")
    for item in values:
        if not isinstance(item, Mapping) or not isinstance(item.get("operation_id"), str):
            _fail("PAP_CATALOG_DRIFT")
        operation_id = str(item["operation_id"])
        if operation_id in result:
            _fail("PAP_CATALOG_DRIFT")
        result[operation_id] = dict(item)
    return result


def _pilot_selectors(validated: Any) -> tuple[str, ...]:
    selectors: list[str] = []
    for node in validated.nodes:
        selector = node.request.get("selector")
        if (
            node.kind != "run"
            or not isinstance(selector, str)
            or not selector
            or selector.startswith("@")
        ):
            _fail("PAP_UNSUPPORTED_PATH")
        selectors.append(selector)
    if not selectors or len(selectors) > MAX_DECLARED_NODES:
        _fail("PAP_UNSUPPORTED_PATH")
    return tuple(sorted(set(selectors)))


def _selector_contracts(
    sdk: Any,
    inventory: Mapping[str, Mapping[str, Any]],
    selectors: tuple[str, ...],
    *,
    preparing: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    catalog: list[dict[str, Any]] = []
    contracts: list[dict[str, Any]] = []
    for selector in selectors:
        item = inventory.get(selector)
        invalid = (
            item is None
            or item.get("stability") != "stable"
            or item.get("effect", "read") != "read"
            or item.get("executable", True) is not True
        )
        if invalid:
            _fail("PAP_UNSUPPORTED_PATH" if preparing else "PAP_CATALOG_DRIFT")
        description = sdk.insight.describe(selector)
        if not isinstance(description, Mapping):
            _fail("PAP_CONTRACT_DRIFT")
        catalog.append({"selector": selector, "entry": dict(item)})
        contracts.append({"selector": selector, "contract": dict(description)})
    return catalog, contracts


def _referenced_sources(
    host_plan: Mapping[str, Any], sources: Mapping[str, Any]
) -> dict[str, Any]:
    action = host_plan.get("action")
    control_sources = host_plan.get("control_sources")
    references: set[str] = set()
    if isinstance(action, Mapping):
        for field in ("task_source", "permission_source", "confirmation_source"):
            if isinstance(action.get(field), str):
                references.add(str(action[field]))
        controls = action.get("controls")
        if isinstance(controls, Mapping):
            for field in ("tool", "operation", "path", "destination"):
                if isinstance(controls.get(field), str):
                    references.add(str(controls[field]))
            object_ids = controls.get("object_ids")
            if isinstance(object_ids, list):
                references.update(item for item in object_ids if isinstance(item, str))
    if isinstance(control_sources, Mapping):
        references.update(
            item for item in control_sources.values() if isinstance(item, str)
        )
    return {name: sources[name] for name in sorted(references) if name in sources}


def _compare_binding(
    artifact: Mapping[str, Any], current: Mapping[str, Any]
) -> None:
    reasons = (
        ("plan_binding_sha256", "PAP_INPUT_DRIFT"),
        ("source_binding_sha256", "PAP_SOURCE_DRIFT"),
        ("workspace_catalog_fingerprint", "PAP_CATALOG_DRIFT"),
        ("catalog_fingerprint", "PAP_CATALOG_DRIFT"),
        ("contract_fingerprint", "PAP_CONTRACT_DRIFT"),
        ("node_count", "PAP_INPUT_DRIFT"),
    )
    for field, code in reasons:
        if artifact.get(field) != current.get(field):
            _fail(code)


def _bound_scope_key(workspace: Any, scope_bound: bool) -> str:
    state_root = getattr(workspace, "state_root", None)
    scope = Path(state_root).name if state_root is not None else ""
    if not scope_bound or not _HEX_32.fullmatch(scope):
        _fail("PAP_SCOPE_UNBOUND", field="workspace")
    return scope


def _summary(artifact: Mapping[str, Any], scope_key: str) -> dict[str, Any]:
    nonce = str(artifact["nonce"])
    return {
        "schema_version": PAP_SUMMARY_SCHEMA_VERSION,
        "ok": True,
        "status": "prepared",
        "pap_id": _reference_for(nonce, scope_key),
        "source_kind": "host_plan",
        "plan_schema_version": PLAN_SCHEMA_VERSION,
        "node_count": artifact["node_count"],
        "max_workers": artifact["max_workers"],
        "created_at": artifact["created_at"],
        "expires_at": artifact["expires_at"],
    }


def _reference_for(nonce: str, scope_key: str) -> str:
    tag = hashlib.sha256(
        f"gravity-pap-reference-v1\0{scope_key}\0{nonce}".encode("ascii")
    ).hexdigest()[:32]
    return f"pap1_{nonce}_{tag}"


def _reference_nonce(value: Any, scope_key: str) -> str:
    match = _REFERENCE.fullmatch(value) if isinstance(value, str) else None
    if match is None:
        _fail("PAP_REFERENCE_INVALID")
    nonce, tag = match.groups()
    if _reference_for(nonce, scope_key).rsplit("_", 1)[1] != tag:
        _fail("PAP_IDENTITY_DRIFT")
    return nonce


def _read_artifact(path: Path, nonce: str) -> dict[str, Any]:
    try:
        status = path.lstat()
        if (
            not stat.S_ISREG(status.st_mode)
            or path.is_symlink()
            or status.st_nlink != 1
            or status.st_size <= 0
            or status.st_size > MAX_ARTIFACT_BYTES
        ):
            _fail("PAP_TAMPERED")
        artifact = json.loads(
            path.read_bytes().decode("utf-8"), object_pairs_hook=_unique_object
        )
        _validate_artifact(artifact, nonce)
        return artifact
    except InputValidationError:
        raise
    except (OSError, UnicodeError, ValueError, TypeError, json.JSONDecodeError):
        _fail("PAP_TAMPERED")


def _validate_artifact(value: Any, nonce: str) -> None:
    if not isinstance(value, dict) or set(value) != _ARTIFACT_FIELDS:
        _fail("PAP_TAMPERED")
    if (
        value.get("schema_version") != PAP_SCHEMA_VERSION
        or value.get("source_kind") != "host_plan"
        or value.get("nonce") != nonce
        or value.get("host_plan_schema_version") != HOST_PLAN_SCHEMA_VERSION
        or value.get("plan_schema_version") != PLAN_SCHEMA_VERSION
    ):
        _fail("PAP_TAMPERED")
    for field in (
        "plan_binding_sha256",
        "source_binding_sha256",
        "contract_fingerprint",
        "catalog_fingerprint",
        "workspace_catalog_fingerprint",
        "preflight_fingerprint",
        "artifact_sha256",
    ):
        if not isinstance(value.get(field), str) or not _HEX_64.fullmatch(value[field]):
            _fail("PAP_TAMPERED")
    _bounded_artifact_integer(value.get("node_count"), 1, MAX_DECLARED_NODES)
    _bounded_artifact_integer(value.get("max_workers"), 1, MAX_WORKERS)
    created = _parse_timestamp(value.get("created_at"))
    expires = _parse_timestamp(value.get("expires_at"))
    if expires <= created or _artifact_digest(value) != value["artifact_sha256"]:
        _fail("PAP_TAMPERED")


def _artifact_digest(value: Mapping[str, Any]) -> str:
    selected = {key: item for key, item in value.items() if key != "artifact_sha256"}
    return _digest(selected)


def _bounded_artifact_integer(value: Any, minimum: int, maximum: int) -> None:
    if type(value) is not int or not minimum <= value <= maximum:
        _fail("PAP_TAMPERED")


def _bounded_integer(value: Any, minimum: int, maximum: int, code: str) -> None:
    if type(value) is not int or not minimum <= value <= maximum:
        _fail(code)


def _parse_timestamp(value: Any) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError("timestamp must be canonical UTC")
    parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    if parsed.tzinfo != timezone.utc or _timestamp(parsed) != value:
        raise ValueError("timestamp must be canonical UTC")
    return parsed


def _timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


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
        _fail("PAP_INPUT_DRIFT")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _fail(code: str, *, field: str = "pap_id") -> None:
    raise InputValidationError(
        f"Prepared Analysis Plan stopped before execution ({code}).",
        field=field,
        code=code,
        next_action=(
            "Prepare a fresh PAP from the current principal-scoped SDK and exact "
            "host Plan, then retry without changing its sources or contracts."
        ),
    )


__all__ = [
    "DEFAULT_TTL_SECONDS",
    "MAX_TTL_SECONDS",
    "PAP_SCHEMA_VERSION",
    "PAP_SUMMARY_SCHEMA_VERSION",
    "PreparedAnalysisPlanService",
]
