"""Bounded Git metadata boundary for the built-in Repo Context Provider."""

from __future__ import annotations

import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from .context_contract import ContextContractError


def git_snapshot(
    root: Path,
    *,
    source_revision: str | None = None,
    observed_at: str | None = None,
) -> dict[str, str]:
    if source_revision is not None:
        if not _sha(source_revision) or not _observed(observed_at):
            raise ContextContractError(
                "CONTEXT_SNAPSHOT_INVALID", "Injected Git snapshot is invalid"
            )
        return {
            "source_revision": source_revision,
            "observed_at": str(observed_at),
            "branch": "injected-fixture",
        }
    revision = _git(root, "rev-parse", "HEAD").strip()
    branch = _git(root, "branch", "--show-current").strip() or "detached"
    committed = _git(root, "show", "-s", "--format=%cI", "HEAD").strip()
    try:
        rendered = (
            datetime.fromisoformat(committed)
            .astimezone(timezone.utc)
            .isoformat(timespec="seconds")
            .replace("+00:00", "Z")
        )
    except ValueError as exc:
        raise ContextContractError(
            "CONTEXT_SNAPSHOT_INVALID", "Git commit timestamp is invalid"
        ) from exc
    if not _sha(revision):
        raise ContextContractError(
            "CONTEXT_SNAPSHOT_INVALID", "Git revision is invalid"
        )
    return {"source_revision": revision, "observed_at": rendered, "branch": branch}


def assert_clean_paths(root: Path, paths: Sequence[str]) -> None:
    selected = set(paths) & dirty_files(root)
    if selected:
        raise ContextContractError(
            "CONTEXT_SNAPSHOT_CHANGED", "Required Context files have local changes"
        )


def tracked_files(root: Path) -> list[str]:
    return [item for item in _git(root, "ls-files", "-z").split("\0") if item]


def dirty_files(root: Path) -> set[str]:
    unstaged = _git(root, "diff", "--name-only", "-z", "HEAD", "--")
    staged = _git(root, "diff", "--cached", "--name-only", "-z", "HEAD", "--")
    return {
        item.replace("\\", "/")
        for item in (*unstaged.split("\0"), *staged.split("\0"))
        if item
    }


def git_ignored(root: Path, paths: Sequence[str]) -> set[str]:
    if not paths:
        return set()
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "check-ignore", "--no-index", "-z", "--stdin"],
            input="\0".join(paths) + "\0",
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="strict",
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError, UnicodeError) as exc:
        raise ContextContractError(
            "CONTEXT_PROVIDER_UNSUPPORTED", "Project Git ignore rules are unavailable"
        ) from exc
    if result.returncode not in {0, 1}:
        raise ContextContractError(
            "CONTEXT_PROVIDER_UNSUPPORTED", "Project Git ignore rules are invalid"
        )
    return {item for item in result.stdout.split("\0") if item}


def assert_index_revision(root: Path, index: Mapping[str, Any]) -> None:
    revision = _git(root, "rev-parse", "HEAD").strip()
    if revision != index["snapshot"]["source_revision"]:
        raise ContextContractError(
            "CONTEXT_SNAPSHOT_CHANGED", "Repository revision changed after indexing"
        )


def _git(root: Path, *arguments: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *arguments],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="strict",
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError, UnicodeError) as exc:
        raise ContextContractError(
            "CONTEXT_PROVIDER_UNSUPPORTED", "Project Git repository is unavailable"
        ) from exc
    if len(result.stdout.encode("utf-8")) > 16 * 1024 * 1024:
        raise ContextContractError(
            "CONTEXT_RESOURCE_LIMIT", "Git metadata exceeds the output budget"
        )
    return result.stdout


def _sha(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 40
        and all(character in "0123456789abcdef" for character in value)
    )


def _observed(value: Any) -> bool:
    return isinstance(value, str) and bool(
        re.fullmatch(
            r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z",
            value,
        )
    )


__all__ = [
    "assert_clean_paths",
    "assert_index_revision",
    "dirty_files",
    "git_ignored",
    "git_snapshot",
    "tracked_files",
]
