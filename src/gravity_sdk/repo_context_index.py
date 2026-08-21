"""Bounded deterministic Git repository indexing and lexical discovery."""

from __future__ import annotations

import fnmatch
import hashlib
import json
import re
import stat
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence

from .agent_runtime_contracts import canonical_digest
from .context_contract import ContextContractError, normalized_requirement_path
from .repo_context_git import (
    assert_clean_paths,
    assert_index_revision as _assert_index_revision,
    dirty_files as _dirty_files,
    git_ignored as _git_ignored,
    git_snapshot,
    tracked_files as _tracked_files,
)
from .repo_context_structure import extract_structure


_SUPPORTED = {
    ".md": "document",
    ".py": "code",
    ".json": "contract",
    ".toml": "configuration",
}
_SENSITIVE_PARTS = frozenset(
    {
        ".git",
        ".gravity",
        "tmp",
        "output",
        "outputs",
        ".env",
        "secrets",
        "credentials",
        "receipts",
        "evidence",
    }
)
_SENSITIVE_SUFFIXES = frozenset({".pem", ".key", ".p12", ".pfx", ".xlsx", ".csv"})
def build_repo_index(
    root: Path,
    *,
    project_id: str,
    provider: Mapping[str, Any],
) -> dict[str, Any]:
    snapshot = git_snapshot(root)
    limits = provider["contract"]["limits"]
    tracked = _tracked_files(root)
    dirty = _dirty_files(root)
    git_ignored = _git_ignored(root, tracked)
    gravity_ignored = _gravity_ignore_patterns(root)
    entries: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    total_bytes = 0
    for relative in sorted(tracked, key=_path_priority):
        reason = _path_exclusion(
            relative,
            dirty,
            gravity_ignored,
            limits,
            git_ignored=git_ignored,
        )
        if reason is not None:
            excluded.append(_excluded(relative, reason))
            continue
        if len(entries) >= limits["max_index_files"]:
            excluded.append(_excluded(relative, "CONTEXT_INDEX_FILE_LIMIT"))
            continue
        entry, reason = _index_entry(
            root,
            relative,
            project_id=project_id,
            revision=snapshot["source_revision"],
            limits=limits,
            remaining_bytes=limits["max_index_bytes"] - total_bytes,
        )
        if reason is not None:
            excluded.append(_excluded(relative, reason))
            continue
        entries.append(entry)
        total_bytes += entry["size_bytes"]
    if _dirty_files(root) != dirty or git_snapshot(root)["source_revision"] != snapshot[
        "source_revision"
    ]:
        raise ContextContractError(
            "CONTEXT_SNAPSHOT_CHANGED", "Repository changed while indexing"
        )
    payload = {
        "snapshot": snapshot,
        "entries": entries,
        "excluded": excluded,
        "budget": {
            "max_files": limits["max_index_files"],
            "max_total_bytes": limits["max_index_bytes"],
            "used_files": len(entries),
            "used_bytes": total_bytes,
            "tracked_files": len(tracked),
        },
    }
    return {
        "schema_version": "gravity.repo-context-index.v1",
        "status": "available" if not excluded else "partial",
        **payload,
        "index_digest": canonical_digest(payload),
        "network_called": False,
    }


def _index_entry(
    root: Path,
    relative: str,
    *,
    project_id: str,
    revision: str,
    limits: Mapping[str, Any],
    remaining_bytes: int,
) -> tuple[dict[str, Any], str | None]:
    relative_path = PurePosixPath(relative)
    path = root.joinpath(*relative_path.parts)
    if _path_has_link(root, relative_path):
        return {}, "CONTEXT_RESOURCE_LINKED"
    try:
        metadata = path.lstat()
    except OSError:
        return {}, "CONTEXT_RESOURCE_MISSING"
    reason = _metadata_exclusion(path, metadata, limits)
    if reason is not None:
        return {}, reason
    if metadata.st_size > remaining_bytes:
        return {}, "CONTEXT_INDEX_BYTE_LIMIT"
    try:
        content, encoded = _read_utf8(path)
        suffix = path.suffix.casefold()
        structure = extract_structure(
            ".md" if not suffix and _resource_type(relative) == "document" else suffix,
            content,
        )
    except (OSError, UnicodeError):
        return {}, "CONTEXT_CONTENT_UNSUPPORTED"
    except (SyntaxError, ValueError):
        return {}, "CONTEXT_STRUCTURE_INVALID"
    if not content.strip() or b"\x00" in encoded:
        return {}, "CONTEXT_CONTENT_UNSUPPORTED"
    lines = content.splitlines()
    return {
        "uri": f"repo://{project_id}/{relative}",
        "path": relative,
        "resource_type": _resource_type(relative),
        "title": _title(relative, structure),
        "size_bytes": len(encoded),
        "line_count": len(lines),
        "content_hash": hashlib.sha256(encoded).hexdigest(),
        "source_revision": revision,
        "citation": {
            "path": relative,
            "line_start": 1,
            "line_end": max(1, len(lines)),
        },
        "structure": structure,
        "role": "data",
    }, None
def search_repo_index(
    root: Path,
    index: Mapping[str, Any],
    query: str,
    *,
    maximum: int,
    excerpt_lines: int,
) -> dict[str, Any]:
    _assert_index_revision(root, index)
    assert_clean_paths(root, [entry["path"] for entry in index["entries"]])
    tokens = _query_tokens(query)
    candidates: list[tuple[int, str, int, dict[str, Any]]] = []
    for entry in index["entries"]:
        path = root.joinpath(*PurePosixPath(entry["path"]).parts)
        try:
            metadata = path.lstat()
            content, encoded = _read_utf8(path)
        except (OSError, UnicodeError) as exc:
            raise ContextContractError(
                "CONTEXT_SNAPSHOT_CHANGED", "Repository resource changed after indexing"
            ) from exc
        if (
            _path_has_link(root, PurePosixPath(entry["path"]))
            or _metadata_exclusion(
                path, metadata, {"max_file_bytes": entry["size_bytes"]}
            )
            is not None
            or hashlib.sha256(encoded).hexdigest() != entry["content_hash"]
        ):
            raise ContextContractError(
                "CONTEXT_SNAPSHOT_CHANGED", "Repository resource changed after indexing"
            )
        lines = content.splitlines()
        structure_text = json.dumps(entry["structure"], ensure_ascii=False).casefold()
        for number, line in enumerate(lines, 1):
            text = line.casefold()
            score = sum(token in text for token in tokens)
            if score == len(tokens):
                result = _search_result(entry, lines, number, excerpt_lines)
                candidates.append((score + 10, entry["path"], number, result))
                break
        else:
            score = sum(token in structure_text for token in tokens)
            if score == len(tokens):
                result = _search_result(entry, lines, 1, excerpt_lines)
                candidates.append((score, entry["path"], 1, result))
    ordered = sorted(candidates, key=lambda item: (-item[0], item[1], item[2]))
    results = [result for _score, _path, _line, result in ordered[:maximum]]
    _assert_index_revision(root, index)
    assert_clean_paths(root, [entry["path"] for entry in index["entries"]])
    return {
        "schema_version": "gravity.repo-context-search.v1",
        "status": "success",
        "query": query,
        "index_digest": index["index_digest"],
        "count": len(results),
        "results": results,
        "truncated": len(candidates) > maximum,
        "network_called": False,
    }


def get_repo_resource(
    root: Path,
    index: Mapping[str, Any],
    uri: str,
    *,
    maximum_lines: int,
) -> dict[str, Any]:
    _assert_index_revision(root, index)
    entry, start, end = _select_uri(index, uri, maximum_lines)
    assert_clean_paths(root, [entry["path"]])
    path = root.joinpath(*PurePosixPath(entry["path"]).parts)
    try:
        metadata = path.lstat()
        content, encoded = _read_utf8(path)
    except (OSError, UnicodeError) as exc:
        raise ContextContractError(
            "CONTEXT_SNAPSHOT_CHANGED", "Repository resource changed after indexing"
        ) from exc
    if (
        _path_has_link(root, PurePosixPath(entry["path"]))
        or _metadata_exclusion(
            path, metadata, {"max_file_bytes": entry["size_bytes"]}
        )
        is not None
        or hashlib.sha256(encoded).hexdigest() != entry["content_hash"]
    ):
        raise ContextContractError(
            "CONTEXT_SNAPSHOT_CHANGED", "Repository resource changed after indexing"
        )
    _assert_index_revision(root, index)
    assert_clean_paths(root, [entry["path"]])
    lines = content.splitlines()
    selected = "\n".join(lines[start - 1 : end])
    return {
        "schema_version": "gravity.repo-context-resource.v1",
        "status": "available",
        "uri": f"{entry['uri']}#L{start}-L{end}",
        "resource_type": entry["resource_type"],
        "title": entry["title"],
        "source_revision": entry["source_revision"],
        "content_hash": entry["content_hash"],
        "role": "data",
        "citation": {"path": entry["path"], "line_start": start, "line_end": end},
        "content": selected,
        "network_called": False,
    }


def _gravity_ignore_patterns(root: Path) -> tuple[str, ...]:
    path = root / ".gravityignore"
    if not path.is_file() or path.is_symlink():
        return ()
    try:
        content, _encoded = _read_utf8(path)
    except (OSError, UnicodeError):
        return ()
    return tuple(
        line.strip().lstrip("/")
        for line in content.splitlines()
        if line.strip() and not line.lstrip().startswith(("#", "!"))
    )


def read_context_file(
    root: Path,
    relative: str,
    *,
    maximum: int,
    require_tracked: bool,
    max_depth: int = 64,
) -> tuple[str, Path]:
    relative = normalized_requirement_path(relative)
    path = PurePosixPath(relative)
    dirty = _dirty_files(root) if require_tracked else set()
    reason = _path_exclusion(
        relative,
        set(),
        _gravity_ignore_patterns(root),
        {"max_path_depth": max_depth},
        git_ignored=_git_ignored(root, [relative]) if require_tracked else set(),
    )
    if reason is not None:
        raise ContextContractError(reason, "Context resource is not readable")
    if require_tracked and relative not in set(_tracked_files(root)):
        raise ContextContractError(
            "CONTEXT_RESOURCE_MISSING", "Context resource is not tracked"
        )
    selected = root.joinpath(*path.parts)
    if _path_has_link(root, path):
        raise ContextContractError(
            "CONTEXT_RESOURCE_LINKED", "Context resource path contains a link"
        )
    try:
        metadata = selected.lstat()
    except OSError as exc:
        raise ContextContractError(
            "CONTEXT_RESOURCE_MISSING", "Context resource is missing"
        ) from exc
    if relative in dirty:
        raise ContextContractError(
            "CONTEXT_SNAPSHOT_CHANGED", "Context resource has local changes"
        )
    reason = _metadata_exclusion(selected, metadata, {"max_file_bytes": maximum})
    if reason is not None:
        raise ContextContractError(reason, "Context resource is outside its boundary")
    try:
        content, encoded = _read_utf8(selected)
    except (OSError, UnicodeError) as exc:
        raise ContextContractError(
            "CONTEXT_CONTENT_UNSUPPORTED", "Context resource is not UTF-8 text"
        ) from exc
    if not content.strip() or b"\x00" in encoded:
        raise ContextContractError(
            "CONTEXT_CONTENT_UNSUPPORTED", "Context resource is empty or binary"
        )
    return content, selected


def _path_exclusion(
    relative: str,
    dirty: set[str],
    patterns: Sequence[str],
    limits: Mapping[str, Any],
    *,
    git_ignored: set[str] | None = None,
) -> str | None:
    path = PurePosixPath(relative)
    lowered = {part.casefold() for part in path.parts}
    if relative in dirty:
        return "CONTEXT_SNAPSHOT_CHANGED"
    if lowered & _SENSITIVE_PARTS or any(part.startswith(".env") for part in lowered):
        return "CONTEXT_ACCESS_DENIED"
    if path.suffix.casefold() in _SENSITIVE_SUFFIXES:
        return "CONTEXT_ACCESS_DENIED"
    if len(path.parts) > limits["max_path_depth"]:
        return "CONTEXT_PATH_DEPTH_LIMIT"
    if _resource_type(relative) is None:
        return "CONTEXT_CONTENT_UNSUPPORTED"
    if git_ignored and relative in git_ignored:
        return "CONTEXT_IGNORED"
    if any(_gravity_match(relative, pattern) for pattern in patterns):
        return "CONTEXT_IGNORED"
    return None


def _metadata_exclusion(
    path: Path, metadata: Any, limits: Mapping[str, Any]
) -> str | None:
    attributes = getattr(metadata, "st_file_attributes", 0)
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    if (
        path.is_symlink()
        or bool(attributes & reparse)
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_nlink != 1
    ):
        return "CONTEXT_RESOURCE_LINKED"
    if not 1 <= metadata.st_size <= limits["max_file_bytes"]:
        return "CONTEXT_RESOURCE_LIMIT"
    return None


def _gravity_match(relative: str, pattern: str) -> bool:
    selected = pattern.rstrip("/")
    return relative == selected or relative.startswith(selected + "/") or fnmatch.fnmatch(relative, pattern)


def _resource_type(relative: str) -> str | None:
    path = PurePosixPath(relative)
    if path.name.casefold() in {"readme", "agents", "claude"}:
        return "document"
    return _SUPPORTED.get(path.suffix.casefold())


def _title(relative: str, structure: Mapping[str, Any]) -> str:
    headings = structure.get("headings", [])
    return str(headings[0]["text"]) if headings else PurePosixPath(relative).name


def _path_priority(value: str) -> tuple[int, str]:
    lowered = value.casefold()
    priority = 0 if PurePosixPath(value).name.casefold() in {"agents.md", "claude.md", "readme.md"} else 1
    if lowered.startswith("docs/"):
        priority = min(priority, 1)
    if any(part in lowered for part in ("contract", "manifest", "schema")):
        priority = min(priority, 2)
    return priority, lowered


def _query_tokens(value: Any) -> tuple[str, ...]:
    if not isinstance(value, str) or not value.strip() or len(value) > 512:
        raise ContextContractError(
            "CONTEXT_QUERY_INVALID", "Context search query is invalid"
        )
    tokens = tuple(dict.fromkeys(value.casefold().split()))
    if len(tokens) > 16:
        raise ContextContractError(
            "CONTEXT_QUERY_INVALID", "Context search query has too many tokens"
        )
    return tokens


def _search_result(
    entry: Mapping[str, Any], lines: Sequence[str], line: int, excerpt_lines: int
) -> dict[str, Any]:
    start = max(1, line - excerpt_lines // 2)
    end = min(len(lines), start + excerpt_lines - 1)
    return {
        "uri": f"{entry['uri']}#L{start}-L{end}",
        "resource_type": entry["resource_type"],
        "title": entry["title"],
        "source_revision": entry["source_revision"],
        "content_hash": entry["content_hash"],
        "role": "data",
        "citation": {"path": entry["path"], "line_start": start, "line_end": end},
        "excerpt": "\n".join(lines[start - 1 : end]),
    }


def _select_uri(
    index: Mapping[str, Any], uri: str, maximum_lines: int
) -> tuple[Mapping[str, Any], int, int]:
    base, _, fragment = str(uri).partition("#")
    entry = next((item for item in index["entries"] if item["uri"] == base), None)
    if entry is None:
        raise ContextContractError("CONTEXT_RESOURCE_MISSING", "Repository URI is not indexed")
    start, end = 1, min(entry["line_count"], maximum_lines)
    match = re.fullmatch(r"L([1-9][0-9]*)-L([1-9][0-9]*)", fragment) if fragment else None
    if fragment and match is None:
        raise ContextContractError("CONTEXT_CITATION_INVALID", "Repository URI line range is invalid")
    if match is not None:
        start, end = int(match.group(1)), int(match.group(2))
    if start > end or end > entry["line_count"] or end - start + 1 > maximum_lines:
        raise ContextContractError("CONTEXT_CITATION_INVALID", "Repository URI line range exceeds bounds")
    return entry, start, end


def _excluded(relative: str, reason: str) -> dict[str, str]:
    return {
        "path_digest": hashlib.sha256(relative.encode("utf-8")).hexdigest(),
        "reason_code": reason,
    }


def _path_has_link(root: Path, relative: PurePosixPath) -> bool:
    selected = root
    for part in relative.parts:
        selected = selected / part
        try:
            metadata = selected.lstat()
        except OSError:
            return False
        attributes = getattr(metadata, "st_file_attributes", 0)
        reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        if selected.is_symlink() or bool(attributes & reparse):
            return True
    return False


def _read_utf8(path: Path) -> tuple[str, bytes]:
    encoded = path.read_bytes()
    return encoded.decode("utf-8"), encoded


__all__ = [
    "assert_clean_paths",
    "build_repo_index",
    "get_repo_resource",
    "git_snapshot",
    "read_context_file",
    "search_repo_index",
]
