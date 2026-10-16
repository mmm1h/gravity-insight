"""Narrow, runtime-verified exceptions for Darwin's system path aliases."""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path


_DARWIN_ALIASES = {
    "/var": "private/var",
    "/tmp": "private/tmp",
    "/etc": "private/etc",
}


def is_system_alias(path: Path, metadata: os.stat_result) -> bool:
    """Trust only an OS alias whose directory entries users cannot replace.

    Callers must restrict this exception to ancestors, never a managed leaf.
    Do not cache the decision or use resolve(): arbitrary links stay visible.
    """
    target = _DARWIN_ALIASES.get(str(path))
    if sys.platform != "darwin" or target is None:
        return False
    if (
        not stat.S_ISLNK(metadata.st_mode)
        or metadata.st_uid != 0
        or getattr(metadata, "st_file_attributes", 0) & 0x400
    ):
        return False
    try:
        destination = path.parent / target
        if os.readlink(path) != target:
            return False
        for parent in (path.parent, destination.parent):
            info = os.lstat(parent)
            if not _root_directory(info) or info.st_mode & 0o022:
                return False
        # /private/tmp is intentionally writable; its entry in /private is not.
        return _root_directory(os.lstat(destination))
    except OSError:
        return False


def _root_directory(metadata: os.stat_result) -> bool:
    return (
        stat.S_ISDIR(metadata.st_mode)
        and metadata.st_uid == 0
        and not getattr(metadata, "st_file_attributes", 0) & 0x400
    )


def system_alias_path(path: Path) -> Path:
    """Replace only a verified system ancestor, retaining all user components.

    This is a spelling normalization, not a containment or link safety check.
    Leaves (including /tmp itself) and non-Darwin paths are unchanged.
    """
    if sys.platform == "darwin":
        for parent in path.parents:
            target = _DARWIN_ALIASES.get(str(parent))
            if target is not None and is_system_alias(parent, os.lstat(parent)):
                return parent.parent / target / path.relative_to(parent)
    return path
