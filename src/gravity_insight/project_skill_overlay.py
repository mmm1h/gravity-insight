"""Tracked project bindings for exact locked Skill composition."""

from __future__ import annotations

import copy
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .agent_runtime_contracts import (
    AgentRuntimeContractError,
    canonical_digest,
    validate_schema,
)
from .context_contract import (
    ContextContractError,
    PROJECT_REPO_PROVIDER_URI,
    compile_context_requirement,
    normalized_requirement_path,
)
from .repo_context_git import assert_clean_paths, git_snapshot
from .repo_context_index import read_context_file


SCHEMA_VERSION = "gravity.project-skill-overlay.v1"
RESOLUTION_SCHEMA_VERSION = "gravity.project-skill-overlay-resolution.v1"
_SCHEMA_NAME = "project-skill-overlay-v1.schema.json"
_MAX_FILE_BYTES = 262_144


class ProjectSkillOverlayError(AgentRuntimeContractError):
    """A project Overlay cannot be safely compiled or frozen."""

    def __init__(self, reason_code: str, message: str) -> None:
        self.reason_code = reason_code
        super().__init__(message)


def compile_project_skill_overlay(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ProjectSkillOverlayError(
            "PROJECT_SKILL_OVERLAY_INVALID", "Project Skill Overlay must be an object"
        )
    contract = copy.deepcopy(dict(value))
    try:
        validate_schema(contract, _SCHEMA_NAME, "Project Skill Overlay")
    except AgentRuntimeContractError as exc:
        raise ProjectSkillOverlayError("PROJECT_SKILL_OVERLAY_INVALID", str(exc)) from exc
    if not contract["overlay_uri"].startswith(
        f"skill://project.{contract['project_id']}/"
    ) or not contract["overlay_uri"].endswith(f"@{contract['version']}"):
        raise ProjectSkillOverlayError(
            "PROJECT_SKILL_OVERLAY_INVALID",
            "Project Skill Overlay identity disagrees with its project or version",
        )
    if contract["semantic_scope"] != contract["default_scope"]:
        raise ProjectSkillOverlayError(
            "PROJECT_SKILL_OVERLAY_INVALID",
            "Project Skill Overlay Semantic and default scopes disagree",
        )
    try:
        contract["semantic_sources"] = sorted(
            normalized_requirement_path(path) for path in contract["semantic_sources"]
        )
        requirements = [
            compile_context_requirement(requirement)["contract"]
            for requirement in contract["context_requirements"]
        ]
    except ContextContractError as exc:
        raise ProjectSkillOverlayError(exc.reason_code, str(exc)) from exc
    identities = [item["requirement_id"] for item in requirements]
    if len(identities) != len(set(identities)):
        raise ProjectSkillOverlayError(
            "PROJECT_SKILL_OVERLAY_INVALID",
            "Project Skill Overlay Context identities are duplicated",
        )
    for requirement in requirements:
        if (
            requirement["provider_uri"] != PROJECT_REPO_PROVIDER_URI
            or requirement["skill_uri"] != contract["extends"]["skill_uri"]
            or requirement["journey_id"] != contract["journey_id"]
        ):
            raise ProjectSkillOverlayError(
                "PROJECT_SKILL_OVERLAY_INVALID",
                "Project Skill Overlay Context binding exceeds the local Skill boundary",
            )
    contract["context_requirements"] = sorted(
        requirements, key=lambda item: item["requirement_id"]
    )
    return {"contract": contract, "digest": canonical_digest(contract)}


def load_project_skill_overlay(
    root: str | Path,
    *,
    contract_path: str,
    source_revision: str | None = None,
    observed_at: str | None = None,
) -> dict[str, Any]:
    candidate = Path(root)
    project_root = candidate.resolve()
    if candidate.is_symlink() or not project_root.is_dir():
        raise ProjectSkillOverlayError(
            "PROJECT_SKILL_OVERLAY_UNAVAILABLE", "Project repository root is invalid"
        )
    injected = source_revision is not None
    try:
        snapshot = git_snapshot(
            project_root,
            source_revision=source_revision,
            observed_at=observed_at,
        )
        normalized_contract_path = normalized_requirement_path(contract_path)
        overlay = compile_project_skill_overlay(
            _read_json(
                project_root,
                normalized_contract_path,
                "Project Skill Overlay",
                tracked=not injected,
            )
        )
        sources = [
            _read_json(
                project_root,
                path,
                "Project Semantic source",
                tracked=not injected,
            )
            for path in overlay["contract"]["semantic_sources"]
        ]
        paths = [normalized_contract_path, *overlay["contract"]["semantic_sources"]]
        if not injected:
            assert_clean_paths(project_root, paths)
            if git_snapshot(project_root)["source_revision"] != snapshot["source_revision"]:
                raise ContextContractError(
                    "CONTEXT_SNAPSHOT_CHANGED", "Project Overlay snapshot changed"
                )
    except ProjectSkillOverlayError:
        raise
    except ContextContractError as exc:
        reason = (
            "PROJECT_SKILL_OVERLAY_MISSING"
            if "missing" in str(exc).casefold()
            else exc.reason_code
        )
        raise ProjectSkillOverlayError(reason, str(exc)) from exc
    return {
        "schema_version": RESOLUTION_SCHEMA_VERSION,
        "contract": overlay["contract"],
        "digest": overlay["digest"],
        "source_revision": snapshot["source_revision"],
        "observed_at": snapshot["observed_at"],
        "semantic_sources": sources,
        "network_called": False,
    }


def _read_json(root: Path, relative: str, label: str, *, tracked: bool) -> dict[str, Any]:
    try:
        content, _path = read_context_file(
            root,
            relative,
            maximum=_MAX_FILE_BYTES,
            require_tracked=tracked,
            max_depth=16,
        )
        value = json.loads(content)
    except ContextContractError:
        raise
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ProjectSkillOverlayError(
            "PROJECT_SKILL_OVERLAY_INVALID", f"{label} is not valid UTF-8 JSON"
        ) from exc
    if not isinstance(value, dict):
        raise ProjectSkillOverlayError(
            "PROJECT_SKILL_OVERLAY_INVALID", f"{label} must be an object"
        )
    return value


__all__ = [
    "ProjectSkillOverlayError",
    "RESOLUTION_SCHEMA_VERSION",
    "SCHEMA_VERSION",
    "compile_project_skill_overlay",
    "load_project_skill_overlay",
]
