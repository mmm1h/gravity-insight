"""Fail-closed local path boundaries for Stage A Hub state and artifacts."""

from __future__ import annotations

import stat
from pathlib import Path

from .skill_hub_contract import SkillHubContractError


def assert_unlinked_path(path: Path, *, reason: str, label: str) -> Path:
    selected = path.absolute()
    for candidate in (selected, *selected.parents):
        try:
            metadata = candidate.lstat()
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise SkillHubContractError(reason, f"{label} is unavailable") from exc
        if stat.S_ISLNK(metadata.st_mode) or is_reparse(metadata):
            raise SkillHubContractError(
                reason, f"{label} contains a link or reparse point"
            )
    return selected


def ensure_unlinked_directory(path: Path, *, reason: str, label: str) -> Path:
    selected = assert_unlinked_path(path, reason=reason, label=label)
    try:
        selected.mkdir(parents=True, exist_ok=True)
        assert_unlinked_path(selected, reason=reason, label=label)
        metadata = selected.lstat()
    except OSError as exc:
        raise SkillHubContractError(reason, f"{label} is unavailable") from exc
    if not stat.S_ISDIR(metadata.st_mode):
        raise SkillHubContractError(reason, f"{label} is not a directory")
    return selected.resolve()


def is_reparse(metadata: object) -> bool:
    attributes = getattr(metadata, "st_file_attributes", 0)
    return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))


__all__ = ["assert_unlinked_path", "ensure_unlinked_directory", "is_reparse"]
