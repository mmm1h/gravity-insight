"""Fail-closed ignore-rule snapshots for the Repo Context Provider."""

from __future__ import annotations

import hashlib
import stat
from pathlib import Path
from typing import Any, Mapping

from .context_contract import ContextContractError


_IGNORE_RULE_FILES = (".gitignore", ".gravityignore")


def read_ignore_rules(
    root: Path,
) -> tuple[dict[str, dict[str, Any]], tuple[str, ...]]:
    snapshot: dict[str, dict[str, Any]] = {}
    gravity_content = ""
    for name in _IGNORE_RULE_FILES:
        content, encoded, present = _read_ignore_rule(root / name)
        snapshot[name] = {
            "present": present,
            "content_hash": hashlib.sha256(encoded).hexdigest(),
        }
        if name == ".gravityignore":
            gravity_content = content
    return snapshot, _gravity_ignore_patterns(gravity_content)


def assert_ignore_rules(
    root: Path, expected: Mapping[str, Mapping[str, Any]]
) -> None:
    current, _patterns = read_ignore_rules(root)
    if current != expected:
        raise ContextContractError(
            "CONTEXT_SNAPSHOT_CHANGED", "Repository ignore rules changed"
        )


def _read_ignore_rule(path: Path) -> tuple[str, bytes, bool]:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return "", b"", False
    except OSError as exc:
        raise ContextContractError(
            "CONTEXT_IGNORE_RULES_INVALID", "Repository ignore rules are unreadable"
        ) from exc
    attributes = getattr(metadata, "st_file_attributes", 0)
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    if (
        stat.S_ISLNK(metadata.st_mode)
        or bool(attributes & reparse)
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_nlink != 1
    ):
        raise ContextContractError(
            "CONTEXT_IGNORE_RULES_INVALID", "Repository ignore rules contain a link"
        )
    try:
        content, encoded = _read_utf8(path)
    except (OSError, UnicodeError) as exc:
        raise ContextContractError(
            "CONTEXT_IGNORE_RULES_INVALID",
            "Repository ignore rules are not readable UTF-8 text",
        ) from exc
    return content, encoded, True


def _read_utf8(path: Path) -> tuple[str, bytes]:
    encoded = path.read_bytes()
    return encoded.decode("utf-8"), encoded


def _gravity_ignore_patterns(content: str) -> tuple[str, ...]:
    return tuple(
        line.strip().lstrip("/")
        for line in content.splitlines()
        if line.strip() and not line.lstrip().startswith(("#", "!"))
    )


__all__ = ["assert_ignore_rules", "read_ignore_rules"]
