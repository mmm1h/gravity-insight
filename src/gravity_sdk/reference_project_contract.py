"""Project-owned Semantic binding adapter for the exact R01 slice."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from .agent_runtime_contracts import canonical_digest
from .context_contract import (
    ContextContractError,
    PROJECT_REPO_PROVIDER_URI,
    compile_context_requirement,
    project_repo_provider_artifact,
)
from .reference_journey_contract import (
    CONTEXT_URI,
    JOURNEY_ID,
    SEMANTIC_URI,
    SKILL_URI,
)
from .reference_semantic_adapter import (
    ReferenceSemanticAdapterError,
    resolve_reference_semantic,
)
from .repo_context_git import assert_clean_paths, git_snapshot
from .repo_context_index import read_context_file
from .repo_context_pack import assemble_context_pack
from .repo_context_provider import RepoContextProvider


SCHEMA_VERSION = "gravity.reference-project-contract.v3"
MAX_CONTEXT_FILES = 4
MAX_FILE_BYTES = 262_144


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
    project_root = Path(root).resolve()
    injected = source_revision is not None
    try:
        snapshot = git_snapshot(
            project_root,
            source_revision=source_revision,
            observed_at=observed_at,
        )
        raw = _read_project_json(
            project_root, contract_path, "project contract", tracked=not injected
        )
        _validate_project_contract(raw)
        semantic_path = str(raw["semantic"]["source_path"])
        source = _read_project_json(
            project_root, semantic_path, "project Semantic source", tracked=not injected
        )
        current = _window(current_window, "current_window")
        reference = _window(reference_window, "reference_window")
        semantic = _resolve_semantic(raw, source, current, reference)
        requirement = raw["context_requirement"]
        timezone_name = _context_timezone(requirement)
        requested_time = {
            "current": _render_window(current, timezone_name),
            "reference": _render_window(reference, timezone_name),
        }
        aliases = _semantic_aliases(semantic)
        pack = (
            assemble_context_pack(
                project_root,
                project_id=raw["project_id"],
                provider=project_repo_provider_artifact(),
                requirement=requirement,
                requested_time=requested_time,
                entity_aliases=aliases,
                source_revision=source_revision,
                observed_at=observed_at,
            )
            if injected
            else RepoContextProvider(project_root, project_id=raw["project_id"]).pack(
                requirement,
                requested_time=requested_time,
                entity_aliases=aliases,
            )
        )
        _verify_snapshot(
            project_root,
            snapshot,
            pack,
            [contract_path, semantic_path],
            injected=injected,
        )
    except ContextContractError as exc:
        raise ReferenceProjectContractError(exc.reason_code) from exc
    required_gaps = [gap for gap in pack["gaps"] if gap.get("required") is True]
    if required_gaps:
        raise ReferenceProjectContractError(str(required_gaps[0]["reason_code"]))
    return {
        "schema_version": SCHEMA_VERSION,
        "project_id": raw["project_id"],
        "owner": raw["owner"],
        "contract_path": PurePosixPath(contract_path).as_posix(),
        "contract_digest": canonical_digest(
            {
                "contract": raw,
                "semantic_source_digest": semantic["source_digest"],
            }
        ),
        "source_revision": pack["provider"]["source_revision"],
        "semantic": semantic,
        "context_pack": pack,
    }


def _validate_project_contract(value: Any) -> None:
    _fields(
        value,
        {"schema_version", "project_id", "owner", "semantic", "context_requirement"},
        "project contract",
    )
    if value["schema_version"] != SCHEMA_VERSION:
        raise ReferenceProjectContractError("project contract schema version changed")
    if value["project_id"] != "merge2" or value["owner"] != "growth-data":
        raise ReferenceProjectContractError("project identity or owner changed")
    _validate_semantic(value["semantic"])
    try:
        requirement = compile_context_requirement(value["context_requirement"])[
            "contract"
        ]
    except ContextContractError as exc:
        raise ReferenceProjectContractError(exc.reason_code) from exc
    checks = (
        requirement["requirement_id"] == CONTEXT_URI,
        requirement["provider_uri"] == PROJECT_REPO_PROVIDER_URI,
        requirement["skill_uri"] == SKILL_URI,
        requirement["journey_id"] == JOURNEY_ID,
        set(requirement["subject_entities"])
        == {"app://project/merge2-legacy", SEMANTIC_URI},
        requirement["required_windows"] == ["current", "reference"],
        1 <= len(requirement["items"]) <= MAX_CONTEXT_FILES,
        requirement["budget"]["max_files"] <= MAX_CONTEXT_FILES,
    )
    if not all(checks):
        raise ReferenceProjectContractError("R01 Context Requirement changed")


def _validate_semantic(value: Any) -> None:
    _fields(value, {"source_path", "uri", "app_alias"}, "semantic")
    if value["uri"] != SEMANTIC_URI or value["app_alias"] != "merge2-legacy":
        raise ReferenceProjectContractError("project Semantic identity changed")
    if not isinstance(value["source_path"], str) or not value["source_path"]:
        raise ReferenceProjectContractError("project Semantic source path is invalid")


def _resolve_semantic(
    raw: Mapping[str, Any],
    source: Mapping[str, Any],
    current: tuple[date, date],
    reference: tuple[date, date],
) -> dict[str, Any]:
    try:
        return resolve_reference_semantic(
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


def _semantic_aliases(semantic: Mapping[str, Any]) -> dict[str, str]:
    alias = semantic["binding"]["app_alias"]
    entity_uri = semantic["definition"]["entity_uri"]
    return {f"app://project/{alias}": entity_uri}


def _context_timezone(requirement: Mapping[str, Any]) -> str:
    timezones = {item["valid_time"]["timezone"] for item in requirement["items"]}
    if len(timezones) != 1:
        raise ReferenceProjectContractError("R01 Context timezones changed")
    return str(next(iter(timezones)))


def _verify_snapshot(
    root: Path,
    expected: Mapping[str, str],
    pack: Mapping[str, Any],
    paths: list[str],
    *,
    injected: bool,
) -> None:
    if pack["provider"]["source_revision"] != expected["source_revision"]:
        raise ContextContractError(
            "CONTEXT_SNAPSHOT_CHANGED", "R01 Context snapshot changed"
        )
    if injected:
        return
    assert_clean_paths(root, paths)
    current = git_snapshot(root)
    if current["source_revision"] != expected["source_revision"]:
        raise ContextContractError(
            "CONTEXT_SNAPSHOT_CHANGED", "R01 project snapshot changed"
        )


def _read_project_json(
    root: Path, relative: str, label: str, *, tracked: bool
) -> dict[str, Any]:
    content, _path = read_context_file(
        root,
        relative,
        maximum=MAX_FILE_BYTES,
        require_tracked=tracked,
        max_depth=16,
    )
    try:
        value = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ReferenceProjectContractError(f"{label} is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ReferenceProjectContractError(f"{label} must be an object")
    return value


def _window(value: Mapping[str, Any], label: str) -> tuple[date, date]:
    _fields(value, {"start", "end"}, label)
    start = _day(value["start"], f"{label}.start")
    end = _day(value["end"], f"{label}.end")
    if start > end:
        raise ReferenceProjectContractError(f"{label} start is after end")
    return start, end


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


def _render_window(value: tuple[date, date], timezone_name: str) -> dict[str, str]:
    return {
        "start": value[0].isoformat(),
        "end": value[1].isoformat(),
        "timezone": timezone_name,
    }


__all__ = [
    "ReferenceProjectContractError",
    "SCHEMA_VERSION",
    "load_reference_project_contract",
]
