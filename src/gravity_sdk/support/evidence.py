"""Create and resolve immutable, content-addressed evidence snapshots."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Callable

from .documents import (
    load_document,
    render_document,
    replace_atomic_durable,
    write_document_atomic,
)


HASH_PATTERN = re.compile(r"[0-9a-f]{64}")
GIT_SHA_PATTERN = re.compile(r"[0-9a-f]{40}")
UNKNOWN_BEFORE_POLICY = "unknown-before-policy"
PRIVACY_CLASSES = {"aggregate", "aggregate_or_controlled_identifier", "controlled_identifier"}
SENSITIVE_RESULT_FIELDS = {
    "accountid",
    "anonymousid",
    "deviceid",
    "distinctid",
    "email",
    "idfa",
    "imei",
    "mobile",
    "oaid",
    "openid",
    "orderid",
    "phone",
    "roleid",
    "unionid",
    "userid",
}


class EvidenceSnapshotError(ValueError):
    """Evidence metadata or content is unsafe, incomplete, or inconsistent."""


@dataclass(frozen=True)
class EvidenceSnapshot:
    product_root: Path
    snapshot_path: Path
    manifest_path: Path
    result_path: Path
    manifest: dict[str, Any]


@dataclass(frozen=True)
class EvidenceBinding:
    """One consumer execution's immutable Evidence snapshot and decoded result."""

    snapshot: EvidenceSnapshot
    snapshot_id: str
    manifest_sha256: str
    result_sha256: str
    resolved_from: str
    result: Any

    def reference(self) -> dict[str, Any]:
        manifest = self.snapshot.manifest
        relative_root = self.snapshot.product_root
        return {
            "data_product_id": manifest["data_product_id"],
            "snapshot_id": self.snapshot_id,
            "snapshot_path": self.snapshot.snapshot_path.relative_to(relative_root).as_posix(),
            "manifest_path": self.snapshot.manifest_path.relative_to(relative_root).as_posix(),
            "result_path": self.snapshot.result_path.relative_to(relative_root).as_posix(),
            "generated_at": manifest["generated_at"],
            "data_window": manifest["data_window"],
            "timezone": manifest["timezone"],
            "result_sha256": self.result_sha256,
            "manifest_sha256": self.manifest_sha256,
            "privacy_class": manifest["privacy_class"],
            "provenance_status": manifest["provenance_status"],
            "resolved_from": self.resolved_from,
            "path_basis": "evidence_product_root_relative",
        }


def serialize_json_result(result: Any) -> bytes:
    return (json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def snapshot_directory_name(generated_at: str) -> str:
    parsed = _aware_datetime(generated_at, "generated_at")
    precision = "microseconds" if parsed.microsecond else "seconds"
    return parsed.isoformat(timespec=precision).replace(":", "-")


def publish_json_snapshot(
    product_root: Path,
    result: Any,
    metadata: dict[str, Any],
    *,
    result_validator: Callable[[Any], None] | None = None,
) -> EvidenceSnapshot:
    """Publish a JSON snapshot without ever replacing an existing snapshot directory.

    The snapshot is assembled and verified in a hidden staging directory.  The
    immutable directory is made visible in one rename, then ``latest.yaml`` is
    updated atomically as the final operation.
    """

    if result_validator is not None:
        result_validator(result)
    result_bytes = serialize_json_result(result)
    result_hash = hashlib.sha256(result_bytes).hexdigest()
    manifest = {
        **metadata,
        "result_file": "result.json",
        "result_sha256": result_hash,
    }
    validate_evidence_manifest(manifest, result=result)

    directory_name = snapshot_directory_name(str(manifest["generated_at"]))
    snapshots_root = product_root / "snapshots"
    snapshots_root.mkdir(parents=True, exist_ok=True)
    final_path = snapshots_root / directory_name
    if final_path.exists():
        raise FileExistsError(f"evidence snapshot already exists and will not be overwritten: {final_path}")

    # Keep staging outside snapshots/. A hard crash can leave the directory
    # behind, but validators and consumers will never mistake it for evidence.
    staging_path = Path(tempfile.mkdtemp(prefix=".snapshot-", dir=product_root))
    try:
        result_path = staging_path / "result.json"
        manifest_path = staging_path / "manifest.yaml"
        _write_bytes_synced(result_path, result_bytes)
        _write_bytes_synced(manifest_path, render_document(manifest).encode("utf-8"))
        validate_snapshot_directory(staging_path, enforce_directory_name=False)
        replace_atomic_durable(staging_path, final_path)
    finally:
        if staging_path.exists():
            shutil.rmtree(staging_path)

    final_manifest = final_path / "manifest.yaml"
    latest = {
        "schema_version": 1,
        "data_product_id": manifest["data_product_id"],
        "snapshot": f"snapshots/{directory_name}",
        "manifest_sha256": _sha256_file(final_manifest),
        "result_sha256": result_hash,
        "updated_at": manifest["generated_at"],
    }
    validate_latest_pointer(latest)
    write_document_atomic(product_root / "latest.yaml", latest)
    return resolve_latest_snapshot(product_root)


def resolve_latest_snapshot(product_root: Path) -> EvidenceSnapshot:
    latest_path = product_root / "latest.yaml"
    latest = load_document(latest_path)
    if not isinstance(latest, dict):
        raise EvidenceSnapshotError(f"{latest_path}: latest pointer must be an object")
    validate_latest_pointer(latest)
    relative = _safe_relative(str(latest["snapshot"]), "snapshot")
    snapshot_path = product_root.joinpath(*relative.parts)
    _require_within_product_root(product_root, snapshot_path)
    resolved = validate_snapshot_directory(snapshot_path)
    if resolved.manifest.get("data_product_id") != latest.get("data_product_id"):
        raise EvidenceSnapshotError(f"{latest_path}: data_product_id differs from snapshot manifest")
    if _sha256_file(resolved.manifest_path) != latest.get("manifest_sha256"):
        raise EvidenceSnapshotError(f"{latest_path}: manifest_sha256 does not match snapshot")
    if resolved.manifest.get("result_sha256") != latest.get("result_sha256"):
        raise EvidenceSnapshotError(f"{latest_path}: result_sha256 does not match snapshot")
    return resolved


def resolve_json_evidence(
    product_root: Path,
    *,
    snapshot_id: str | None = None,
    result_validator: Callable[[Any], None] | None = None,
) -> EvidenceBinding:
    """Resolve current or explicit JSON Evidence and bind one immutable snapshot."""

    if snapshot_id is None:
        snapshot = resolve_latest_snapshot(product_root)
        resolved_from = "latest_pointer"
    else:
        relative = _safe_relative(snapshot_id, "snapshot_id")
        if len(relative.parts) != 1:
            raise EvidenceSnapshotError("snapshot_id must name one immutable snapshot directory")
        snapshot_path = product_root / "snapshots" / relative.name
        _require_within_product_root(product_root, snapshot_path)
        snapshot = validate_snapshot_directory(snapshot_path)
        resolved_from = "explicit_snapshot"
    if snapshot.result_path.suffix.lower() != ".json":
        raise EvidenceSnapshotError(f"{snapshot.result_path}: JSON Evidence resolver requires a .json result")
    try:
        result = json.loads(snapshot.result_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EvidenceSnapshotError(f"{snapshot.result_path}: invalid JSON result: {exc}") from exc
    if result_validator is not None:
        result_validator(result)
    return EvidenceBinding(
        snapshot=snapshot,
        snapshot_id=snapshot.snapshot_path.name,
        manifest_sha256=_sha256_file(snapshot.manifest_path),
        result_sha256=_sha256_file(snapshot.result_path),
        resolved_from=resolved_from,
        result=result,
    )


def validate_snapshot_directory(
    snapshot_path: Path, *, enforce_directory_name: bool = True
) -> EvidenceSnapshot:
    manifest_path = snapshot_path / "manifest.yaml"
    if not manifest_path.is_file():
        raise EvidenceSnapshotError(f"{snapshot_path}: missing manifest.yaml")
    manifest = load_document(manifest_path)
    if not isinstance(manifest, dict):
        raise EvidenceSnapshotError(f"{manifest_path}: manifest must be an object")
    result_relative = _safe_relative(str(manifest.get("result_file", "")), "result_file")
    if len(result_relative.parts) != 1:
        raise EvidenceSnapshotError(f"{manifest_path}: result_file must name a file in the snapshot directory")
    result_path = snapshot_path.joinpath(*result_relative.parts)
    if not result_path.is_file():
        raise EvidenceSnapshotError(f"{manifest_path}: result file is missing: {result_relative.as_posix()}")
    if _sha256_file(result_path) != manifest.get("result_sha256"):
        raise EvidenceSnapshotError(f"{manifest_path}: result_sha256 does not match result bytes")
    result: Any | None = None
    if result_path.suffix.lower() == ".json":
        try:
            result = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise EvidenceSnapshotError(f"{result_path}: invalid JSON result: {exc}") from exc
    validate_evidence_manifest(manifest, result=result)
    expected_directory = snapshot_directory_name(str(manifest["generated_at"]))
    if enforce_directory_name and snapshot_path.name != expected_directory:
        raise EvidenceSnapshotError(
            f"{manifest_path}: snapshot directory {snapshot_path.name!r} does not match generated_at"
        )
    return EvidenceSnapshot(
        product_root=snapshot_path.parent.parent,
        snapshot_path=snapshot_path,
        manifest_path=manifest_path,
        result_path=result_path,
        manifest=manifest,
    )


def validate_evidence_manifest(manifest: dict[str, Any], *, result: Any | None = None) -> None:
    required = {
        "schema_version",
        "data_product_id",
        "evidence_origin",
        "generated_at",
        "data_window",
        "timezone",
        "data_contract_version",
        "query_id",
        "query_version",
        "git_sha",
        "git_dirty",
        "row_count",
        "row_count_semantics",
        "result_file",
        "result_sha256",
        "privacy_class",
        "provenance_status",
        "unknown_fields",
    }
    missing = sorted(required - set(manifest))
    if missing:
        raise EvidenceSnapshotError(f"evidence manifest is missing fields: {', '.join(missing)}")
    if type(manifest["schema_version"]) is not int or manifest["schema_version"] != 1:
        raise EvidenceSnapshotError("evidence manifest schema_version must be integer 1")
    for field in ("data_product_id", "data_contract_version", "query_id", "query_version"):
        if not isinstance(manifest[field], str) or not manifest[field].strip():
            raise EvidenceSnapshotError(f"evidence manifest {field} must be a non-empty string")
    _aware_datetime(str(manifest["generated_at"]), "generated_at")
    window = manifest["data_window"]
    if not isinstance(window, dict) or set(("start", "end")) - set(window):
        raise EvidenceSnapshotError("evidence manifest data_window must contain start and end")
    start = _aware_datetime(str(window["start"]), "data_window.start")
    end = _aware_datetime(str(window["end"]), "data_window.end")
    if start >= end:
        raise EvidenceSnapshotError("evidence manifest data_window start must be before end")
    if not isinstance(manifest["timezone"], str) or not manifest["timezone"].strip():
        raise EvidenceSnapshotError("evidence manifest timezone must be non-empty")
    if manifest["privacy_class"] not in PRIVACY_CLASSES:
        raise EvidenceSnapshotError(f"unsupported evidence privacy_class: {manifest['privacy_class']!r}")
    if not HASH_PATTERN.fullmatch(str(manifest["result_sha256"])):
        raise EvidenceSnapshotError("evidence manifest result_sha256 must be lowercase SHA-256")
    _safe_relative(str(manifest["result_file"]), "result_file")

    unknown_fields = manifest["unknown_fields"]
    if not isinstance(unknown_fields, list) or not all(isinstance(item, str) for item in unknown_fields):
        raise EvidenceSnapshotError("evidence manifest unknown_fields must contain strings")
    unknown = set(unknown_fields)
    if len(unknown) != len(unknown_fields):
        raise EvidenceSnapshotError("evidence manifest unknown_fields must be unique")
    for field in unknown:
        if field not in manifest:
            raise EvidenceSnapshotError(f"evidence manifest unknown field is not present: {field}")

    origin = manifest["evidence_origin"]
    if origin not in {"generated", "rolling_baseline", "git_history_recovery"}:
        raise EvidenceSnapshotError(f"unsupported evidence_origin: {origin!r}")
    recovery_fields = {"source_git_sha", "source_blob_oid"}
    if origin == "generated":
        latest_safe_date = manifest.get("latest_safe_date")
        try:
            parsed_safe_date = date.fromisoformat(str(latest_safe_date))
        except ValueError as exc:
            raise EvidenceSnapshotError("generated evidence requires latest_safe_date in YYYY-MM-DD format") from exc
        if parsed_safe_date != start.date():
            raise EvidenceSnapshotError("generated evidence latest_safe_date must equal data_window.start date")
        if unknown or manifest["provenance_status"] != "complete":
            raise EvidenceSnapshotError("generated evidence requires complete provenance and no unknown fields")
        if GIT_SHA_PATTERN.fullmatch(str(manifest["git_sha"])) is None:
            raise EvidenceSnapshotError("generated evidence requires a full lowercase Git SHA")
        if type(manifest["git_dirty"]) is not bool:
            raise EvidenceSnapshotError("generated evidence requires boolean git_dirty")
    elif origin == "rolling_baseline":
        if manifest["provenance_status"] != "partial_legacy":
            raise EvidenceSnapshotError("rolling baseline evidence must declare partial_legacy provenance")
        if not unknown:
            raise EvidenceSnapshotError("rolling baseline evidence must identify unknown legacy fields")
    else:
        if manifest["provenance_status"] != "partial_legacy":
            raise EvidenceSnapshotError("Git-history recovery evidence must declare partial_legacy provenance")
        if not unknown:
            raise EvidenceSnapshotError("Git-history recovery evidence must identify unknown legacy fields")
        if manifest["git_sha"] != UNKNOWN_BEFORE_POLICY or manifest["git_dirty"] is not None:
            raise EvidenceSnapshotError(
                "Git-history recovery evidence must keep runtime git_sha and git_dirty explicitly unknown"
            )
        missing_recovery = sorted(recovery_fields - set(manifest))
        if missing_recovery:
            raise EvidenceSnapshotError(
                "Git-history recovery evidence is missing source fields: " + ", ".join(missing_recovery)
            )
        if GIT_SHA_PATTERN.fullmatch(str(manifest["source_git_sha"])) is None:
            raise EvidenceSnapshotError("Git-history recovery source_git_sha must be a full lowercase Git SHA")
        if GIT_SHA_PATTERN.fullmatch(str(manifest["source_blob_oid"])) is None:
            raise EvidenceSnapshotError("Git-history recovery source_blob_oid must be a full lowercase Git object ID")
    if origin != "git_history_recovery" and recovery_fields.intersection(manifest):
        raise EvidenceSnapshotError("source recovery fields are allowed only for Git-history recovery evidence")
    for field in ("git_sha", "query_version", "data_contract_version"):
        if manifest[field] == UNKNOWN_BEFORE_POLICY and field not in unknown:
            raise EvidenceSnapshotError(f"{field} uses the legacy sentinel but is absent from unknown_fields")

    row_count = manifest["row_count"]
    if row_count is not None and (type(row_count) is not int or row_count < 0):
        raise EvidenceSnapshotError("evidence manifest row_count must be a non-negative integer or null")
    if row_count is None and "row_count" not in unknown:
        raise EvidenceSnapshotError("null row_count must be listed in unknown_fields")
    if result is not None:
        _validate_row_count(result, row_count, str(manifest["row_count_semantics"]))
        if manifest["privacy_class"] == "aggregate":
            _reject_user_level_fields(result)


def validate_latest_pointer(latest: dict[str, Any]) -> None:
    required = {
        "schema_version",
        "data_product_id",
        "snapshot",
        "manifest_sha256",
        "result_sha256",
        "updated_at",
    }
    missing = sorted(required - set(latest))
    if missing:
        raise EvidenceSnapshotError(f"latest pointer is missing fields: {', '.join(missing)}")
    if type(latest["schema_version"]) is not int or latest["schema_version"] != 1:
        raise EvidenceSnapshotError("latest pointer schema_version must be integer 1")
    snapshot = _safe_relative(str(latest["snapshot"]), "snapshot")
    if len(snapshot.parts) != 2 or snapshot.parts[0] != "snapshots":
        raise EvidenceSnapshotError("latest pointer snapshot must name one snapshots/<timestamp> directory")
    for field in ("manifest_sha256", "result_sha256"):
        if HASH_PATTERN.fullmatch(str(latest[field])) is None:
            raise EvidenceSnapshotError(f"latest pointer {field} must be lowercase SHA-256")
    _aware_datetime(str(latest["updated_at"]), "updated_at")


def _validate_row_count(result: Any, row_count: Any, semantics: str) -> None:
    if semantics == "data_product_count":
        products = result.get("products") if isinstance(result, dict) else None
        actual = len(products) if isinstance(products, dict) else None
    elif semantics == "record_count":
        actual = len(result) if isinstance(result, list) else None
    elif semantics == "object_count":
        actual = 1 if isinstance(result, dict) else None
    elif semantics == UNKNOWN_BEFORE_POLICY and row_count is None:
        return
    else:
        raise EvidenceSnapshotError(f"unsupported row_count_semantics: {semantics!r}")
    if actual is None or actual != row_count:
        raise EvidenceSnapshotError(
            f"evidence row_count mismatch for {semantics}: expected {row_count!r}, got {actual!r}"
        )


def _reject_user_level_fields(value: Any, location: str = "$") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = re.sub(r"[^a-z0-9]", "", str(key).lower()).removesuffix("s")
            if normalized in SENSITIVE_RESULT_FIELDS:
                raise EvidenceSnapshotError(f"aggregate evidence contains user-level field at {location}.{key}")
            _reject_user_level_fields(child, f"{location}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_user_level_fields(child, f"{location}[{index}]")


def _aware_datetime(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise EvidenceSnapshotError(f"evidence {field} must be ISO 8601 date-time") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise EvidenceSnapshotError(f"evidence {field} must contain an explicit timezone")
    return parsed


def _safe_relative(value: str, field: str) -> PurePosixPath:
    path = PurePosixPath(value.replace("\\", "/"))
    if not value or path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise EvidenceSnapshotError(f"unsafe evidence {field}: {value!r}")
    return path


def _require_within_product_root(product_root: Path, target: Path) -> None:
    try:
        target.resolve().relative_to(product_root.resolve())
    except (OSError, ValueError) as exc:
        raise EvidenceSnapshotError(f"evidence snapshot escapes product root: {target}") from exc


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_bytes_synced(path: Path, value: bytes) -> None:
    with path.open("xb") as handle:
        handle.write(value)
        handle.flush()
        os.fsync(handle.fileno())
