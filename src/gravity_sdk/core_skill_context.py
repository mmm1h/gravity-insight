"""Repo Context dependency assembly for the Core Skill Runtime."""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .context_contract import (
    ContextContractError,
    project_repo_provider_artifact,
    public_context_reference,
)
from .project_skill_overlay import ProjectSkillOverlayError
from .repo_context_git import git_snapshot
from .repo_context_pack import assemble_context_pack


def resolve_project_context(
    *,
    workspace: Any,
    journey: Mapping[str, Any],
    skill: Mapping[str, Any] | None,
    overlay: Mapping[str, Any],
    semantics: Sequence[Mapping[str, Any]],
    scope: Mapping[str, Any],
    source_revision: str | None,
    observed_at: str | None,
) -> tuple[list[dict[str, Any]], list[str]]:
    required, declared, reasons = _declarations(journey, skill, overlay)
    aliases = _entity_aliases(semantics, scope, overlay)
    root = Path(getattr(workspace, "root"))
    packs: list[dict[str, Any]] = []
    for uri in sorted(declared):
        public, selected_reasons = _assemble(
            root=root,
            uri=uri,
            required=required,
            requirement=declared[uri],
            overlay=overlay,
            scope=scope,
            aliases=aliases,
            source_revision=source_revision,
            observed_at=observed_at,
        )
        packs.append(public)
        reasons.extend(selected_reasons)
    _verify_revision(root, overlay, source_revision)
    return packs, reasons


def _declarations(
    journey: Mapping[str, Any],
    skill: Mapping[str, Any] | None,
    overlay: Mapping[str, Any],
) -> tuple[set[str], dict[str, Mapping[str, Any]], list[str]]:
    required = set(journey["contract"]["required_context"])
    optional = (
        set(skill["contract"]["context_dependencies"]["optional"])
        if skill is not None
        else set()
    )
    declared = {
        requirement["requirement_id"]: requirement
        for requirement in overlay["contract"]["context_requirements"]
    }
    if set(declared) - (required | optional):
        raise ProjectSkillOverlayError(
            "PROJECT_SKILL_OVERLAY_CONFLICT",
            "Project Skill Overlay contains undeclared Context dependencies",
        )
    reasons = ["CONTEXT_REQUIRED_MISSING"] if required - set(declared) else []
    return required, declared, reasons


def _assemble(
    *,
    root: Path,
    uri: str,
    required: set[str],
    requirement: Mapping[str, Any],
    overlay: Mapping[str, Any],
    scope: Mapping[str, Any],
    aliases: Mapping[str, str],
    source_revision: str | None,
    observed_at: str | None,
) -> tuple[dict[str, Any], list[str]]:
    timezone_name = _timezone(requirement)
    requested = {
        name: {**copy.deepcopy(window), "timezone": timezone_name}
        for name, window in scope["windows"].items()
        if name in requirement["required_windows"]
    }
    pack = assemble_context_pack(
        root,
        project_id=overlay["contract"]["project_id"],
        provider=project_repo_provider_artifact(),
        requirement=requirement,
        requested_time=requested,
        entity_aliases=aliases,
        source_revision=source_revision,
        observed_at=observed_at,
    )
    if pack["provider"]["source_revision"] != overlay["source_revision"]:
        raise ContextContractError(
            "CONTEXT_SNAPSHOT_CHANGED",
            "Project Overlay and Context Pack revisions disagree",
        )
    reasons: list[str] = []
    if uri in required and pack["status"] == "blocked":
        reasons.extend(gap["reason_code"] for gap in pack["gaps"] if gap["required"])
    if uri in required and not pack["claims"]["confirmed_claims_allowed"]:
        reasons.append("CONTEXT_AUTHORITY_INSUFFICIENT")
    return public_context_reference(pack), reasons


def _verify_revision(
    root: Path, overlay: Mapping[str, Any], source_revision: str | None
) -> None:
    if (
        source_revision is None
        and git_snapshot(root)["source_revision"] != overlay["source_revision"]
    ):
        raise ContextContractError(
            "CONTEXT_SNAPSHOT_CHANGED",
            "Project dependencies changed during resolution",
        )


def _timezone(requirement: Mapping[str, Any]) -> str:
    values = {item["valid_time"]["timezone"] for item in requirement["items"]}
    if len(values) != 1:
        raise ProjectSkillOverlayError(
            "PROJECT_SKILL_OVERLAY_INVALID",
            "One Context Requirement must use one timezone",
        )
    return str(next(iter(values)))


def _entity_aliases(
    semantics: Sequence[Mapping[str, Any]],
    scope: Mapping[str, Any],
    overlay: Mapping[str, Any],
) -> dict[str, str]:
    app_alias = scope["app_alias"] or overlay["contract"]["default_scope"]["app_alias"]
    aliases: dict[str, str] = {}
    for resolution in semantics:
        definition = resolution.get("definition")
        if resolution.get("ok") and isinstance(definition, Mapping):
            aliases[f"app://project/{app_alias}"] = definition["contract"]["entity_uri"]
    return aliases


__all__ = ["resolve_project_context"]
