"""Static no-code Skill package boundaries shared by Hub projections."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import PurePosixPath
from typing import Any

from .agent_runtime_contracts import AgentRuntimeContractError


MAX_PACKAGE_FILES = 64
MAX_FILE_BYTES = 262_144
MAX_TOTAL_BYTES = 2_097_152
MAX_PATH_DEPTH = 6
class SkillPackageError(AgentRuntimeContractError):
    """A static Skill package or Agent projection violates its boundary."""


def validate_package_entries(
    entries: Mapping[str, bytes],
    *,
    expected: Mapping[str, bytes] | None = None,
    allow_skill_md: bool = False,
) -> None:
    if not isinstance(entries, Mapping) or not 1 <= len(entries) <= MAX_PACKAGE_FILES:
        raise SkillPackageError("Skill package file count is outside the boundary")
    normalized: dict[str, bytes] = {}
    casefolded: set[str] = set()
    total = 0
    for raw_path, content in entries.items():
        path = _safe_package_path(raw_path, allow_skill_md=allow_skill_md)
        key = path.casefold()
        if key in casefolded:
            raise SkillPackageError("Skill package paths collide by case")
        casefolded.add(key)
        if not isinstance(content, bytes) or not 1 <= len(content) <= MAX_FILE_BYTES:
            raise SkillPackageError("Skill package file size is outside the boundary")
        total += len(content)
        normalized[path] = content
    if total > MAX_TOTAL_BYTES:
        raise SkillPackageError("Skill package total size is outside the boundary")
    if expected is not None and normalized != dict(expected):
        raise SkillPackageError("Skill package differs from its Render Model")


def _safe_package_path(value: Any, *, allow_skill_md: bool) -> str:
    if (
        not isinstance(value, str)
        or not value
        or "\\" in value
        or ":" in value
    ):
        raise SkillPackageError("Skill package path is not normalized")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise SkillPackageError("Skill package path escapes its boundary")
    if len(path.parts) > MAX_PATH_DEPTH:
        raise SkillPackageError("Skill package path depth is outside the boundary")
    if any(part.casefold() == "scripts" for part in path.parts):
        raise SkillPackageError("ordinary Skill packages cannot contain scripts")
    if path.as_posix() != value:
        raise SkillPackageError("Skill package path is not canonical")
    if value == "SKILL.md" and not allow_skill_md:
        raise SkillPackageError("SKILL.md belongs only to Agent Skills export")
    return value


__all__ = [
    "MAX_FILE_BYTES",
    "MAX_PACKAGE_FILES",
    "MAX_PATH_DEPTH",
    "MAX_TOTAL_BYTES",
    "SkillPackageError",
    "validate_package_entries",
]
