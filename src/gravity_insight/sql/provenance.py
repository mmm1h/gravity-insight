"""Repository provenance for SQL Evidence.

Repository root and state root are distinct inputs. The consumer workspace
directory holds ``gravity.toml`` and is version controlled; the private state
root only holds generated Evidence and is never a checkout. Resolving one from
the other is what made every normal consumer fail the Git step before any
cleanliness, credential, or product check could run.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

from gravity_insight.paths import PROJECT_ROOT
from gravity_insight.sql.evidence_validation import EvidenceFormatError
from gravity_insight.workspace import Workspace, load_workspace


ROOT = PROJECT_ROOT


def git_toplevel(candidate: Path) -> Path | None:
    """Return the checkout containing ``candidate``, or None when it has none.

    Asking Git rather than looking for a ``.git`` directory keeps linked
    worktrees working, where ``.git`` is a file.
    """

    probe = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=candidate,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    resolved = probe.stdout.strip()
    if probe.returncode or not resolved:
        return None
    return Path(resolved)


def provenance_root(workspace: Workspace | None = None) -> Path | None:
    """Resolve the Git checkout that Evidence provenance describes.

    Maintainers running from the SDK checkout keep their existing provenance
    through the ``ROOT`` fallback; the state root is never probed.
    """

    selected = load_workspace() if workspace is None else workspace
    for candidate in (selected.root, ROOT):
        if candidate == selected.state_root or not candidate.is_dir():
            continue
        toplevel = git_toplevel(candidate)
        if toplevel is not None:
            return toplevel
    return None


def git_state(workspace: Workspace | None = None) -> tuple[str, bool]:
    """Return the SHA and dirty flag publish records, or fail closed."""

    root = provenance_root(workspace)
    if root is None:
        raise EvidenceFormatError("cannot publish evidence without a Git-backed workspace")
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if head.returncode or re.fullmatch(r"[0-9a-f]{40}", head.stdout.strip()) is None:
        raise EvidenceFormatError("cannot publish evidence without a valid repository Git SHA")
    status = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=root,
        capture_output=True,
        check=False,
    )
    if status.returncode:
        raise EvidenceFormatError("cannot determine repository state for evidence provenance")
    return head.stdout.strip(), bool(status.stdout.strip())


def preflight_git_report(repository_root: Path | None) -> dict[str, Any]:
    """Describe the consumer checkout without turning a missing one into a failure.

    Preflight reports; publish enforces. A workspace outside version control is
    a determinate state that belongs in ``offline_blockers``, not an error that
    looks like the tool itself broke.
    """

    absent = {"git_state": "not_git_backed", "git_sha": None, "current_branch": None, "git_dirty": None}
    if repository_root is None:
        return absent
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repository_root, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False
    )
    branch = subprocess.run(
        ["git", "branch", "--show-current"], cwd=repository_root, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False
    )
    status = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"], cwd=repository_root, capture_output=True, check=False
    )
    git_sha = head.stdout.strip()
    if head.returncode or re.fullmatch(r"[0-9a-f]{40}", git_sha) is None or branch.returncode or status.returncode:
        return {**absent, "git_state": "unreadable"}
    return {
        "git_state": "resolved",
        "git_sha": git_sha,
        "current_branch": branch.stdout.strip() or "DETACHED",
        "git_dirty": bool(status.stdout.strip()),
    }


__all__ = [
    "ROOT",
    "git_state",
    "git_toplevel",
    "preflight_git_report",
    "provenance_root",
]
