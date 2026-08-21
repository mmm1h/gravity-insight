"""Project-owned Semantic and aligned Repo Context for the R01 slice."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
from datetime import date, datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence

from .reference_journey_contract import CONTEXT_URI, JOURNEY_ID, SEMANTIC_URI
from .reference_semantic_adapter import (
    ReferenceSemanticAdapterError,
    resolve_reference_semantic,
)


SCHEMA_VERSION = "gravity.reference-project-contract.v2"
CONTEXT_PACK_SCHEMA_VERSION = "gravity.context-pack.v1"
MAX_CONTEXT_FILES = 4
MAX_FILE_BYTES = 131_072
MAX_TOTAL_BYTES = 262_144
_SENSITIVE_PARTS = frozenset(
    {".git", ".gravity", "tmp", "output", "outputs", ".env", "secrets"}
)


class ReferenceProjectContractError(ValueError):
    """The project contract cannot support the exact R01 Journey."""


def load_reference_project_contract(
    root: str | Path,
    *,
    contract_path: str,
    current_window: Mapping[str, Any],
    reference_window: Mapping[str, Any],
    source_revision: str | None = None,
    observed_at: str | None = None,
) -> dict[str, Any]:
    """Load one exact project contract and build its bounded Context Pack."""

    project_root = Path(root).resolve()
    selected_path = _safe_file(project_root, contract_path, maximum=MAX_FILE_BYTES)
    raw = _read_json(selected_path, "project contract")
    _validate_project_contract(raw)
    current = _window(current_window, "current_window")
    reference = _window(reference_window, "reference_window")
    semantic_source_path = str(raw["semantic"]["source_path"])
    selected_source = _safe_file(
        project_root, semantic_source_path, maximum=MAX_FILE_BYTES
    )
    source = _read_json(selected_source, "project Semantic source")
    try:
        semantic = resolve_reference_semantic(
            source,
            project_id=raw["project_id"],
            owner=raw["owner"],
            uri=raw["semantic"]["uri"],
            app_alias=raw["semantic"]["app_alias"],
            current=current,
            reference=reference,
        )
    except ReferenceSemanticAdapterError as exc:
        raise ReferenceProjectContractError(str(exc)) from exc
    if source_revision is None:
        revision, observation = _git_snapshot(
            project_root,
            [
                contract_path,
                semantic_source_path,
                *[str(item["path"]) for item in raw["context_pack"]["items"]],
            ],
        )
    else:
        revision = _revision(source_revision)
        observation = _observed_at(observed_at)
    context_pack = _context_pack(
        project_root,
        raw["context_pack"],
        current=current,
        reference=reference,
        source_revision=revision,
        observed_at=observation,
    )
    contract_digest = _digest(
        {
            "contract": raw,
            "semantic_source_digest": semantic["source_digest"],
        }
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "project_id": raw["project_id"],
        "owner": raw["owner"],
        "contract_path": PurePosixPath(contract_path).as_posix(),
        "contract_digest": contract_digest,
        "source_revision": revision,
        "semantic": semantic,
        "context_pack": context_pack,
    }


def _validate_project_contract(value: Any) -> None:
    _fields(
        value,
        {"schema_version", "project_id", "owner", "semantic", "context_pack"},
        "project contract",
    )
    if value["schema_version"] != SCHEMA_VERSION:
        raise ReferenceProjectContractError("project contract schema version changed")
    if value["project_id"] != "merge2" or value["owner"] != "growth-data":
        raise ReferenceProjectContractError("project identity or owner changed")
    _validate_semantic(value["semantic"])
    _validate_context_declaration(value["context_pack"])


def _validate_semantic(value: Any) -> None:
    _fields(
        value,
        {"source_path", "uri", "app_alias"},
        "semantic",
    )
    if value["uri"] != SEMANTIC_URI or value["app_alias"] != "merge2-legacy":
        raise ReferenceProjectContractError("project Semantic identity changed")
    if not isinstance(value["source_path"], str) or not value["source_path"]:
        raise ReferenceProjectContractError("project Semantic source path is invalid")


def _validate_context_declaration(value: Any) -> None:
    _fields(value, {"uri", "subject_entities", "items"}, "context_pack")
    if value["uri"] != CONTEXT_URI:
        raise ReferenceProjectContractError("Context Pack identity changed")
    _strings(value["subject_entities"], "context subject_entities")
    items = value["items"]
    if not isinstance(items, list) or not 1 <= len(items) <= MAX_CONTEXT_FILES:
        raise ReferenceProjectContractError("Context Pack item count is invalid")
    for item in items:
        _fields(
            item,
            {
                "path",
                "title",
                "resource_type",
                "entity_refs",
                "valid_time",
                "effective_range",
                "authority",
                "sensitivity",
                "supersedes",
            },
            "context item",
        )
        if item["resource_type"] not in {"document", "project_semantic"}:
            raise ReferenceProjectContractError("context resource type is invalid")
        if item["authority"] not in {"canonical", "supporting"}:
            raise ReferenceProjectContractError("context authority is invalid")
        if item["sensitivity"] not in {"internal", "confidential"}:
            raise ReferenceProjectContractError("context sensitivity is invalid")
        _strings(item["entity_refs"], "context entity_refs")
        _strings(item["supersedes"], "context supersedes", allow_empty=True)
        _range(item["valid_time"], "context valid_time")
        _range(item["effective_range"], "context effective_range")


def _context_pack(
    root: Path,
    declaration: Mapping[str, Any],
    *,
    current: tuple[date, date],
    reference: tuple[date, date],
    source_revision: str,
    observed_at: str,
) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    total_bytes = 0
    for raw in declaration["items"]:
        valid = _range(raw["valid_time"], "context valid_time")
        effective = _range(raw["effective_range"], "context effective_range")
        if not all(
            _contains(valid, window) and _contains(effective, window)
            for window in (current, reference)
        ):
            raise ReferenceProjectContractError("CONTEXT_ENTITY_TIME_MISMATCH")
        path = _safe_file(root, str(raw["path"]), maximum=MAX_FILE_BYTES)
        content = _read_text(path, "context item")
        size = len(content.encode("utf-8"))
        total_bytes += size
        if total_bytes > MAX_TOTAL_BYTES:
            raise ReferenceProjectContractError("Context Pack exceeds total byte budget")
        relative = path.relative_to(root).as_posix()
        item = {
            "schema_version": "gravity.context-item.v1",
            "uri": f"repo://work-dashboard/{relative}",
            "provider_id": "project-repo-r01",
            "resource_type": raw["resource_type"],
            "title": raw["title"],
            "entity_refs": copy.deepcopy(raw["entity_refs"]),
            "valid_time": copy.deepcopy(raw["valid_time"]),
            "effective_range": copy.deepcopy(raw["effective_range"]),
            "observed_at": observed_at,
            "authority": raw["authority"],
            "source_revision": source_revision,
            "content_hash": hashlib.sha256(content.encode("utf-8")).hexdigest(),
            "freshness": "current",
            "source_trust": "project_authoritative",
            "supersedes": copy.deepcopy(raw["supersedes"]),
            "sensitivity": raw["sensitivity"],
            "role": "data",
            "citation": {"path": relative},
            "content": content,
        }
        items.append(item)
    digest_input = [{key: value for key, value in item.items() if key != "content"} for item in items]
    result = {
        "schema_version": CONTEXT_PACK_SCHEMA_VERSION,
        "skill_id": "gravity.game/ap-cost-anomaly-localization",
        "journey_id": JOURNEY_ID,
        "subject_entities": copy.deepcopy(declaration["subject_entities"]),
        "requested_time": {
            "current": _render_window(current),
            "reference": _render_window(reference),
        },
        "authority_policy": {"required": ["canonical"], "allow_supporting": True},
        "items": items,
        "alignment": {
            "matched": [item["uri"] for item in items],
            "excluded": [],
            "superseded": [],
        },
        "required_status": [
            {"uri": item["uri"], "status": "available"} for item in items
        ],
        "conflicts": [],
        "gaps": [],
        "budget": {
            "max_files": MAX_CONTEXT_FILES,
            "max_file_bytes": MAX_FILE_BYTES,
            "max_total_bytes": MAX_TOTAL_BYTES,
            "used_bytes": total_bytes,
        },
    }
    result["pack_digest"] = _digest({**result, "items": digest_input})
    return result


def public_context_reference(pack: Mapping[str, Any]) -> dict[str, Any]:
    """Remove Context bodies before composing an Analysis Result or Receipt."""

    return {
        "schema_version": pack["schema_version"],
        "journey_id": pack["journey_id"],
        "pack_digest": pack["pack_digest"],
        "items": [
            {
                key: copy.deepcopy(item[key])
                for key in (
                    "uri",
                    "provider_id",
                    "resource_type",
                    "entity_refs",
                    "valid_time",
                    "effective_range",
                    "observed_at",
                    "authority",
                    "source_revision",
                    "content_hash",
                    "freshness",
                    "sensitivity",
                    "role",
                    "citation",
                )
            }
            for item in pack["items"]
        ],
        "gaps": copy.deepcopy(pack["gaps"]),
        "conflicts": copy.deepcopy(pack["conflicts"]),
    }


def _safe_file(root: Path, relative: str, *, maximum: int) -> Path:
    path = PurePosixPath(relative.replace("\\", "/"))
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ReferenceProjectContractError("context path must be a normalized relative path")
    lowered = {part.casefold() for part in path.parts}
    if lowered & _SENSITIVE_PARTS or any(part.startswith(".env") for part in lowered):
        raise ReferenceProjectContractError("context path is sensitive or mutable")
    selected = root.joinpath(*path.parts)
    if selected.is_symlink():
        raise ReferenceProjectContractError("context path must not be a symbolic link")
    try:
        resolved = selected.resolve(strict=True)
    except OSError as exc:
        raise ReferenceProjectContractError("required context file is missing") from exc
    try:
        if os.path.commonpath((str(root), str(resolved))) != str(root):
            raise ReferenceProjectContractError("context path escapes the workspace")
    except ValueError as exc:
        raise ReferenceProjectContractError("context path escapes the workspace") from exc
    if not resolved.is_file() or resolved.stat().st_size > maximum:
        raise ReferenceProjectContractError("context file is invalid or exceeds its byte budget")
    return resolved


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReferenceProjectContractError(f"{label} is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ReferenceProjectContractError(f"{label} must be an object")
    return value


def _read_text(path: Path, label: str) -> str:
    try:
        value = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ReferenceProjectContractError(f"{label} is not valid UTF-8 text") from exc
    if not value.strip():
        raise ReferenceProjectContractError(f"{label} must not be empty")
    return value


def _git_snapshot(root: Path, relative_paths: Sequence[str]) -> tuple[str, str]:
    try:
        status = subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "status",
                "--porcelain",
                "--untracked-files=all",
                "--",
                *relative_paths,
            ],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="strict",
            timeout=10,
        )
        result = subprocess.run(
            ["git", "-C", str(root), "show", "-s", "--format=%H%n%cI", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="strict",
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError, UnicodeError) as exc:
        raise ReferenceProjectContractError("project Git snapshot is unavailable") from exc
    if status.stdout.strip():
        raise ReferenceProjectContractError(
            "project contract or Context files have uncommitted changes"
        )
    lines = result.stdout.splitlines()
    if len(lines) != 2:
        raise ReferenceProjectContractError("project Git snapshot is invalid")
    revision = _revision(lines[0])
    try:
        committed = datetime.fromisoformat(lines[1]).astimezone(timezone.utc)
    except ValueError as exc:
        raise ReferenceProjectContractError("project Git timestamp is invalid") from exc
    observed = committed.isoformat(timespec="seconds").replace("+00:00", "Z")
    return revision, observed


def _revision(value: Any) -> str:
    revision = str(value).strip().casefold()
    if len(revision) != 40 or any(
        character not in "0123456789abcdef" for character in revision
    ):
        raise ReferenceProjectContractError("project Git revision is invalid")
    return revision


def _observed_at(value: Any) -> str:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ReferenceProjectContractError("project observation timestamp is invalid")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ReferenceProjectContractError("project observation timestamp is invalid") from exc
    rendered = parsed.astimezone(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )
    if rendered != value:
        raise ReferenceProjectContractError("project observation timestamp is invalid")
    return rendered


def _window(value: Mapping[str, Any], label: str) -> tuple[date, date]:
    _fields(value, {"start", "end"}, label)
    start = _day(value["start"], f"{label}.start")
    end = _day(value["end"], f"{label}.end")
    if start > end:
        raise ReferenceProjectContractError(f"{label} start is after end")
    return start, end


def _range(value: Mapping[str, Any], label: str) -> tuple[date | None, date | None]:
    _fields(value, {"start", "end"}, label)
    start = _day(value["start"], f"{label}.start") if value["start"] is not None else None
    end = _day(value["end"], f"{label}.end") if value["end"] is not None else None
    if start is not None and end is not None and start > end:
        raise ReferenceProjectContractError(f"{label} start is after end")
    return start, end


def _contains(
    effective: tuple[date | None, date | None], window: tuple[date, date]
) -> bool:
    return (effective[0] is None or effective[0] <= window[0]) and (
        effective[1] is None or effective[1] >= window[1]
    )


def _day(value: Any, label: str) -> date:
    try:
        parsed = date.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        parsed = None
    if parsed is None or parsed.isoformat() != value:
        raise ReferenceProjectContractError(f"{label} must be canonical YYYY-MM-DD")
    return parsed


def _fields(value: Any, expected: set[str], label: str) -> None:
    if not isinstance(value, Mapping) or set(value) != expected:
        raise ReferenceProjectContractError(f"{label} fields are invalid")


def _strings(value: Any, label: str, *, allow_empty: bool = False) -> None:
    if (
        not isinstance(value, list)
        or (not allow_empty and not value)
        or any(not isinstance(item, str) or not item for item in value)
        or len(value) != len(set(value))
    ):
        raise ReferenceProjectContractError(f"{label} must be a unique string array")


def _digest(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _render_window(value: tuple[date, date]) -> dict[str, str]:
    return {"start": value[0].isoformat(), "end": value[1].isoformat()}


__all__ = [
    "CONTEXT_PACK_SCHEMA_VERSION",
    "ReferenceProjectContractError",
    "SCHEMA_VERSION",
    "load_reference_project_contract",
    "public_context_reference",
]
