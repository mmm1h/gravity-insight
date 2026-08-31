"""Deterministic governance checks for current repository documentation."""

from __future__ import annotations

import hashlib
import json
from collections import deque
from pathlib import Path, PurePosixPath
import re
from typing import Any


CANONICAL_ARCHITECTURE = "docs/architecture.md"
CANONICAL_MAX_LINES = 400
CANONICAL_MAX_BYTES = 30_000
DIRECTIVE_PATH = "specs/agent-runtime/directive.json"
INDEX_PATH = "specs/agent-runtime/index.json"
INDEX_MARKDOWN_PATH = "specs/agent-runtime/index.md"

_DIRECTIVE_KEYS = {"path", "digest", "version", "approval"}
_MARKDOWN_LINK = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
_RETIRED_REFERENCE = re.compile(
    r"(?:architecture-source\.md|requirement-template\.md|"
    r"R(?:0[0-9]|1[0-7])(?:[A-C])?-[^\s)`\]\"']+\.md)"
)
_PARALLEL_VERSION = re.compile(
    r"(?i)(?:-v\d+|-final)\.md$|^\d{4}-\d{2}-\d{2}.*报告.*\.md$"
)
_LOG_PATTERNS = {
    "dated heading": re.compile(r"(?m)^#{1,6}\s+20\d{2}-\d{2}-\d{2}(?:\s|$)"),
    "round log": re.compile(r"第\s*[一二三四五六七八九十0-9]+\s*轮"),
    "worktree path": re.compile(
        r"(?i)[A-Z]:[\\/]git-pjt[\\/](?:_wt|gravity)[^\s)`]*"
    ),
    "branch record": re.compile(r"(?i)codex/[a-z0-9][a-z0-9_-]+"),
    "old test count": re.compile(
        r"(?i)(?:\b(?:pytest|unittest)\s*[:=]?\s*\d+|"
        r"\b\d+\s+(?:passed|tests?|subtests?)\b)"
    ),
}

# The release/CI migration owns this bootstrap file. This task is explicitly
# forbidden from editing it, so its exact hand-off is reported separately.
_EXTERNAL_HANDOFFS = {"README.md", "AGENTS.md"}


class DocumentationGateError(ValueError):
    """Raised when the documentation binding cannot be interpreted."""


def load_json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise DocumentationGateError(
            f"{path.as_posix()} must contain a JSON object"
        )
    return value


def _repository_path(value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise DocumentationGateError("directive.path must be a non-empty string")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts:
        raise DocumentationGateError("directive.path must be repository-relative")
    return path.as_posix()


def validate_architecture_binding(root: Path) -> dict[str, Any]:
    """Validate the four-field binding and return value-free measurements."""

    directive = load_json_object(root / DIRECTIVE_PATH)
    if set(directive) != _DIRECTIVE_KEYS:
        raise DocumentationGateError(
            "directive must contain exactly path, digest, version, approval"
        )
    path = _repository_path(directive["path"])
    if path != CANONICAL_ARCHITECTURE:
        raise DocumentationGateError(
            f"directive.path must name the sole owner {CANONICAL_ARCHITECTURE}"
        )
    if directive.get("approval") != "approved":
        raise DocumentationGateError("directive.approval must be approved")
    if not isinstance(directive.get("version"), str) or not directive["version"]:
        raise DocumentationGateError("directive.version must be a non-empty string")
    digest = directive.get("digest")
    if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        raise DocumentationGateError(
            "directive.digest must be a lowercase SHA-256"
        )
    canonical = root / path
    payload = canonical.read_bytes()
    actual = hashlib.sha256(payload).hexdigest()
    if actual != digest:
        raise DocumentationGateError(
            f"canonical architecture digest mismatch: expected {digest}, got {actual}"
        )
    lines = len(payload.decode("utf-8").splitlines())
    if lines > CANONICAL_MAX_LINES:
        raise DocumentationGateError(
            f"canonical architecture has {lines} lines; maximum is {CANONICAL_MAX_LINES}"
        )
    if len(payload) > CANONICAL_MAX_BYTES:
        raise DocumentationGateError(
            f"canonical architecture has {len(payload)} bytes; "
            f"maximum is {CANONICAL_MAX_BYTES}"
        )
    return {
        "path": path,
        "digest": actual,
        "lines": lines,
        "bytes": len(payload),
    }


def _local_targets(path: Path) -> list[Path]:
    targets: list[Path] = []
    for raw in _MARKDOWN_LINK.findall(path.read_text(encoding="utf-8")):
        target = raw.split("#", 1)[0].strip().strip("<>")
        if not target or "://" in target or target.startswith("mailto:"):
            continue
        targets.append((path.parent / target).resolve())
    return targets


def _reachable_docs(root: Path) -> set[Path]:
    docs = (root / "docs").resolve()
    archive = (docs / "archive").resolve()
    allowed = {
        path.resolve()
        for path in docs.rglob("*.md")
        if archive not in path.resolve().parents
    }
    queue: deque[Path] = deque([(docs / "index.md").resolve()])
    reached: set[Path] = set()
    while queue:
        current = queue.popleft()
        if current in reached or current not in allowed or not current.is_file():
            continue
        reached.add(current)
        queue.extend(
            target for target in _local_targets(current) if target in allowed
        )
    return reached


def current_markdown_files(root: Path) -> list[Path]:
    """Return human sources selected by current entry points and machine indexes."""

    files = {
        (root / name).resolve()
        for name in ("README.md", "AGENTS.md", "SECURITY.md", INDEX_MARKDOWN_PATH)
        if (root / name).is_file()
    }
    files.update(_reachable_docs(root))
    try:
        directive = load_json_object(root / DIRECTIVE_PATH)
        old_binding = directive.get("canonical_source")
        fallback = old_binding.get("repository_path") if isinstance(old_binding, dict) else None
        path = _repository_path(directive.get("path", fallback))
        canonical = (root / path).resolve()
        if canonical.is_file():
            files.add(canonical)
    except (DocumentationGateError, json.JSONDecodeError, OSError):
        pass
    try:
        index = load_json_object(root / INDEX_PATH)
    except (DocumentationGateError, json.JSONDecodeError, OSError):
        index = {}
    for item in index.get("requirements", []):
        if isinstance(item, dict) and isinstance(item.get("path"), str):
            candidate = (
                root / "specs/agent-runtime" / item["path"]
            ).resolve()
            if candidate.is_file():
                files.add(candidate)
    return sorted(files)


def _mermaid_blocks(text: str) -> list[list[str]]:
    blocks: list[list[str]] = []
    active: list[str] | None = None
    for line in text.splitlines():
        if active is None and line.strip() == "```mermaid":
            active = []
        elif active is not None and line.strip() == "```":
            blocks.append(active)
            active = None
        elif active is not None:
            active.append(line)
    if active is not None:
        raise DocumentationGateError("unterminated Mermaid fence")
    return blocks


def _validate_mermaid_block(block: list[str]) -> None:
    lines = [
        line.strip()
        for line in block
        if line.strip() and not line.lstrip().startswith("%%")
    ]
    if not lines or re.fullmatch(
        r"flowchart\s+(?:TB|TD|BT|RL|LR)", lines[0]
    ) is None:
        raise DocumentationGateError(
            "Mermaid block must start with a flowchart direction"
        )
    depth = 0
    for line in lines[1:]:
        if line.startswith("subgraph "):
            depth += 1
            continue
        if line == "end":
            depth -= 1
            if depth < 0:
                raise DocumentationGateError("Mermaid subgraph end is unmatched")
            continue
        if "-->" not in line and "-.->" not in line:
            raise DocumentationGateError(f"unsupported Mermaid statement: {line}")
        pairs = (("[", "]"), ("(", ")"), ("{", "}"))
        if any(line.count(left) != line.count(right) for left, right in pairs):
            raise DocumentationGateError(
                f"unbalanced Mermaid node delimiters: {line}"
            )
    if depth:
        raise DocumentationGateError("Mermaid subgraph is unterminated")


def validate_mermaid(text: str) -> int:
    """Validate the intentionally small flowchart subset used by the architecture."""

    blocks = _mermaid_blocks(text)
    if not blocks:
        raise DocumentationGateError("canonical architecture must contain Mermaid")
    for block in blocks:
        _validate_mermaid_block(block)
    return len(blocks)


def _current_file_errors(root: Path, path: Path) -> list[str]:
    errors: list[str] = []
    relative = path.relative_to(root).as_posix()
    text = path.read_text(encoding="utf-8")
    if _PARALLEL_VERSION.search(path.name):
        errors.append(f"parallel documentation version is forbidden: {relative}")
    if relative not in _EXTERNAL_HANDOFFS:
        retired = sorted(set(_RETIRED_REFERENCE.findall(text)))
        if retired:
            errors.append(
                f"{relative} references retired specifications: {retired}"
            )
    for label, pattern in _LOG_PATTERNS.items():
        if pattern.search(text):
            errors.append(f"{relative} contains current-document {label}")
    old_architecture = (root / "specs/agent-runtime/architecture-source.md").resolve()
    for target in _local_targets(path):
        if relative == "README.md" and target == old_architecture:
            continue
        if not target.exists():
            errors.append(f"broken local link: {relative} -> {target}")
    for number, line in enumerate(text.splitlines(), start=1):
        if line.startswith(("<<<<<<< ", ">>>>>>> ")) or line == "=======":
            errors.append(f"merge conflict marker: {relative}:{number}")
    return errors


def documentation_errors(root: Path) -> list[str]:
    """Return all current documentation violations without short-circuiting."""

    root = root.resolve()
    errors: list[str] = []
    try:
        binding = validate_architecture_binding(root)
        validate_mermaid(
            (root / binding["path"]).read_text(encoding="utf-8")
        )
    except (
        DocumentationGateError,
        json.JSONDecodeError,
        OSError,
        UnicodeError,
    ) as exc:
        errors.append(str(exc))
    for path in current_markdown_files(root):
        errors.extend(_current_file_errors(root, path))
    competing = root / "specs/agent-runtime/architecture-source.md"
    if competing.exists():
        relative = competing.relative_to(root).as_posix()
        errors.append(f"parallel canonical owner exists: {relative}")
    return errors
