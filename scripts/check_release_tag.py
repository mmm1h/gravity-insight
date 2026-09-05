"""Require release tags and the installed project version to identify one commit."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path
from typing import Sequence

from gravity_insight import __version__


ROOT = Path(__file__).resolve().parents[1]


def head_release_tags(repository: Path) -> list[str]:
    completed = subprocess.run(
        ["git", "tag", "--points-at", "HEAD", "--list", "v*"],
        cwd=repository,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(f"cannot inspect HEAD tags: {detail}")
    return sorted(line.strip() for line in completed.stdout.splitlines() if line.strip())


def revision_commit(
    repository: Path, revision: str, *, missing_ok: bool = False
) -> str | None:
    completed = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", f"{revision}^{{commit}}"],
        cwd=repository,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )
    if missing_ok and completed.returncode == 1:
        return None
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(f"cannot resolve {revision} to a commit: {detail}")
    return completed.stdout.strip()


def check_release_tags(
    version: str,
    tags: Sequence[str],
    *,
    head_commit: str,
    version_tag_commit: str | None,
) -> str:
    expected = f"v{version}"
    if tags and list(tags) != [expected]:
        actual = ", ".join(tags)
        raise ValueError(
            f"FAIL release-tag: HEAD tags [{actual}] do not match expected {expected}"
        )
    if version_tag_commit is not None and version_tag_commit != head_commit:
        raise ValueError(
            f"FAIL release-tag: {expected} points to {version_tag_commit[:12]} but "
            f"HEAD is {head_commit[:12]}; version {version} is already occupied by "
            "a different commit"
        )
    if version_tag_commit is not None:
        return f"PASS release-tag: {expected} matches version {version}"
    return (
        f"PASS release-tag: HEAD has no v* tag and {expected} does not exist "
        f"locally; version={version}"
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    try:
        repository = args.repository.resolve()
        expected = f"v{__version__}"
        message = check_release_tags(
            __version__,
            head_release_tags(repository),
            head_commit=revision_commit(repository, "HEAD") or "",
            version_tag_commit=revision_commit(
                repository, f"refs/tags/{expected}", missing_ok=True
            ),
        )
    except (RuntimeError, ValueError) as error:
        print(error)
        return 1
    print(message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
